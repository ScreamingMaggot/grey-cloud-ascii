"""多视口验收：检查是否铺满、帧率、运行时报错，并出图。

    python measure/multi_view.py [html文件名] [时刻列表]

宽窗口是重点回归项：早先按「视口宽/固定列数」算字符宽度，宽屏右侧会空出一条竖带。
"""
import sys, pathlib, json
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE.parent / (sys.argv[1] if len(sys.argv) > 1 else "grey_cloud_ascii.html")
TIMES = [float(t) for t in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["150"])]
OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\check"); OUT.mkdir(exist_ok=True)
VIEWS = [(2560, 1440), (1920, 1080), (1080, 1080)]

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge")
    for (vw, vh) in VIEWS:
        pg = b.new_page(viewport={"width": vw, "height": vh})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:140]))
        pg.on("console", lambda m: errs.append(f"{m.type}:{m.text[:110]}") if m.type == "error" else None)
        for t in TIMES:
            pg.goto(HTML.as_uri() + f"?demo=1&t={max(0.0, t - 1.2)}", wait_until="load")
            pg.wait_for_timeout(1500)
            st = pg.evaluate("""() => ({
              COLS, ROWS, charW:+PXW.toFixed(2),
              rowW:Math.round(COLS*PXW), vpW:innerWidth,
              bolts:bolts.length, level:+level.toFixed(2),
              sharp:+sharp.toFixed(2), mel:+mel.toFixed(2), dying:+dying.toFixed(2)
            })""")
            fps = pg.evaluate("""async () => { const t0=performance.now(); let n=0;
              await new Promise(r=>{const f=()=>{n++;(performance.now()-t0<2000)?requestAnimationFrame(f):r()};
                                     requestAnimationFrame(f)});
              return +(n/((performance.now()-t0)/1000)).toFixed(1)}""")
            f = OUT / f"{HTML.stem}_{vw}x{vh}_{t:g}s.png"
            pg.screenshot(path=str(f), scale="css")
            ok = "OK " if st["rowW"] >= st["vpW"] else "GAP"
            print(f"{ok} {vw}x{vh} t={t:5.0f}s fps={fps:6.1f} {json.dumps(st)}")
            if errs: print("   errors:", errs[:2])
        pg.close()
    b.close()
