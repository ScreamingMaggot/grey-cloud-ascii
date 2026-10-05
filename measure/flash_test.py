"""闪烁检验：连拍若干帧，量化相邻帧变化率与亮度波动。

    python measure/flash_test.py [时刻]

用途：区分「云在涌」和「整幅在闪」。健康的脉动应该是——亮度波动小（不闪），
但相邻帧有部分像素变化（云在动）。若亮度波动很大，说明能量被接到了明暗上而不是形变上。
"""
import sys, pathlib, numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE.parent / "grey_cloud_ascii.html"
T0   = float(sys.argv[1]) if len(sys.argv) > 1 else 60
N, STEP_MS = 8, 125
OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\flash"); OUT.mkdir(exist_ok=True)

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1080, "height": 1080})
    pg.goto(HTML.as_uri() + f"?demo=1&t={max(0.0, T0-1.0)}", wait_until="load")
    pg.wait_for_timeout(1200)
    shots = []
    for i in range(N):
        f = OUT / f"f{i}.png"
        pg.screenshot(path=str(f), scale="css")
        shots.append(np.asarray(Image.open(f).convert("L"), dtype=np.int16))
        pg.wait_for_timeout(STEP_MS)
    st = pg.evaluate("""() => JSON.stringify({level:+level.toFixed(2), sharp:+sharp.toFixed(2),
        pulseLo:+pulseLo.toFixed(2), rings:0, bolts:bolts.length})""")
    b.close()

lum = np.array([s.mean() for s in shots])
chg = [float((np.abs(shots[i+1]-shots[i]) > 24).mean()*100) for i in range(N-1)]
lit = np.array([float((s > 28).mean()*100) for s in shots])
print(f"t={T0}s  {st}")
print(f"  mean luminance   {lum.min():.2f} .. {lum.max():.2f}   swing {lum.max()-lum.min():.2f}  ({(lum.max()-lum.min())/max(lum.mean(),1e-6)*100:.1f}% of mean)")
print(f"  lit coverage     {lit.min():.1f}% .. {lit.max():.1f}%   swing {lit.max()-lit.min():.1f}pp")
print("  frame-to-frame changed pixels: " + " ".join(f"{c:.1f}%" for c in chg))
print("\n判读：亮度摆幅 <8% 且覆盖率摆幅 <6pp 视为「在涌不在闪」；")
print("      相邻帧变化率 3–18% 说明云形在动而无整幅跳变。")
