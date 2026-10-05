"""视差纵深检验：逐层单独合成，量每层在鼠标左右两端之间的水平位移。

    python measure/parallax_test.py

两处坑，都得避开：
1) 不能"左右各截一张全画面图"来比。按高度分带隔离不了深度——每层云都铺满整幅，
   只是密度随高度不同，所以任何一条带里都混着 6 层的位移，量出来是一个平均值。
   改成每层单独 drawImage 到黑底上再截图。
2) 必须先冻结。云在流、雨在下，两张图隔着 2 秒的话，互相关量到的是"时间差"。
   冻结办法：rAF 换成空操作，再用同一个时间戳手工调 frame()，dt 恒为 0，
   tNow/phase 都不动，只有视差缓动 sx 在收敛。

判读：位移从最远层到最近层单调上升、且最大/最小 > 3 倍，才谈得上体积盒。
"""
import pathlib, numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE.parent / "grey_cloud_ascii.html"
OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\plx"); OUT.mkdir(exist_ok=True)
VW, VH = 1920, 1080
KM = [13.0, 7.5, 4.2, 2.2, 1.1, 0.5]
# PAR 要和 grey_cloud_ascii.html 里的视差基准一致；改了一边忘了另一边，设计列就骗人
PAR = float(__import__("re").search(r"const PAR=([\d.]+)",
      (HERE.parent/"grey_cloud_ascii.html").read_text(encoding="utf-8")).group(1))

FREEZE = """(t) => {
  window.requestAnimationFrame = () => 0;      // 停掉自走循环
  audio = {paused:false, currentTime:t};       // tNow 被钉死
  /* 手工调 frame 也必须传同一个时间戳：performance.now() 每次都在走，dt 就不是 0，
     phase 会偷偷推进，量到的位移里混进"云自己在流"。 */
  window.__T = performance.now();
  for(let i=0;i<300;i++) frame(window.__T);
  return {tNow:+tNow.toFixed(2), sx:+sx.toFixed(3), phase:+phase.toFixed(4)};
}"""

# i<NL：只合成第 i 层云；i==NL：只合成雨幕（前景，位移应当最大）
ONLY = """(i) => {
  cx.setTransform(1,0,0,1,0,0);
  cx.fillStyle='#000'; cx.fillRect(0,0,cv.width,cv.height);
  if(i<NL){ const L=DEPTHS[i]; cx.save(); parallax(L.near);
            cx.drawImage(L.cv,-L.ox,-L.oy); cx.restore() }
  else    { cx.save(); parallax(1.00); drawRain(); cx.restore() }
}"""


def settle(pg, m, i):
    st = pg.evaluate("""(a) => { mx=a; for(let i=0;i<300;i++) frame(window.__T);
        return {sx:+sx.toFixed(3), tNow:+tNow.toFixed(2), phase:+phase.toFixed(4)} }""", m)
    pg.evaluate(ONLY, i)
    return st


def best_shift(A, B, sub=3, max_shift=400):
    """二维平移匹配：若 B 是 A 右移 s，则 A[:,x] == B[:,x+s]，逐 s 求平均绝对差。
    为什么不用一维列均值：远雾和雨幕太稀疏，列均值几乎没有结构，实测换 mx 后
    峰值位置虽然对，但 corr 只有 0.05，分不出真位移和噪声。二维用全部纹理。
    窗口宽度必须与 s 无关：一开始让重叠区随 s 收窄，结果大位移处只剩 42 列，
    而远层大多是黑底，样本越少均值越容易碰巧偏低——量出 1734px 这种鬼数字。
    sub=3 降采样把代价压到可接受（视差是整幅级位移，3px 内不会错认）。
    返回 (位移px, 最佳残差, 零位移残差)；1-最佳/零位移 就是置信度。"""
    a = A[::sub, ::sub]; b = B[::sub, ::sub]
    H, W = a.shape
    smax = max_shift//sub
    pad = 10
    WM = W-2*pad-smax
    assert WM > 40, "视口太窄，窗口不够"
    rows = slice(pad, H-pad)
    best, bs, r0 = 1e9, 0, None
    for s in range(0, smax+1):
        d = float(np.abs(a[rows, pad:pad+WM] - b[rows, pad+s:pad+s+WM]).mean())
        if s == 0: r0 = d
        if d < best: best, bs = d, s
    return bs*sub, best, r0


with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": VW, "height": VH})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto(HTML.as_uri()+"?demo=1&t=150", wait_until="load")
    pg.wait_for_timeout(1500)
    fz = pg.evaluate(FREEZE, 150.0)
    NL = pg.evaluate("NL")
    near = pg.evaluate("DEPTHS.map(d=>+d.near.toFixed(4))")
    print(f"frozen: {fz}   NL={NL}  near={near}")
    rows = []
    # 对照：同一 mx 连拍两张，必须量出 0 位移、置信≈1。
    # 上一版没做这一步，仪器把"重叠区变窄"当成了"匹配得好"，报了 1734px 我没察觉。
    print("\n对照（同一鼠标位置连拍两张，应当 0px / 置信≈1）：")
    for i in [0, 3, NL]:
        pg.evaluate("""(a)=>{mx=a;for(let j=0;j<300;j++)frame(window.__T)}""", -1.0)
        pg.evaluate(ONLY, i)
        pg.screenshot(path=str(OUT/"c0.png"), scale="css")
        pg.evaluate("""(a)=>{mx=a;for(let j=0;j<300;j++)frame(window.__T)}""", -1.0)
        pg.evaluate(ONLY, i)
        pg.screenshot(path=str(OUT/"c1.png"), scale="css")
        A = np.asarray(Image.open(OUT/"c0.png").convert("L"), dtype=np.float64)
        B = np.asarray(Image.open(OUT/"c1.png").convert("L"), dtype=np.float64)
        s, d, d0 = best_shift(A, B)
        ok = "PASS" if s == 0 else "FAIL"
        print(f"  {ok}  layer {i}: shift={s}px  残差 {d:.3f} vs 零位残差 {d0:.3f}")
        if s != 0: errs.append(f"control layer {i}: nonzero shift {s}")
    print()
    for i in range(NL+1):
        sL = settle(pg, -1.0, i)
        pg.screenshot(path=str(OUT / f"L{i}.png"), scale="css")
        sR = settle(pg, 1.0, i)
        pg.screenshot(path=str(OUT / f"R{i}.png"), scale="css")
        if sL["phase"] != sR["phase"] or sL["tNow"] != sR["tNow"]:
            errs.append(f"layer {i} not frozen: {sL} vs {sR}")
        A = np.asarray(Image.open(OUT/f"L{i}.png").convert("L"), dtype=np.float64)
        B = np.asarray(Image.open(OUT/f"R{i}.png").convert("L"), dtype=np.float64)
        if A.std() < 1 or B.std() < 1:
            rows.append((i, near[i] if i < NL else 1.0, None)); continue
        k = near[i] if i < NL else 1.0
        s, d, d0 = best_shift(A, B)
        rows.append((i, k, (s, d, d0)))
    b.close()

if errs:
    print("PROBLEM:", errs[:3]); raise SystemExit(1)

print("\n  layer      near   设计位移   实测位移   残差比   置信")
sh = []
for i, k, r in rows:
    tag = f"云 {i}（{KM[i]:>4}km）" if i < NL else "雨幕（前景）"
    if r is None:
        print(f"  {tag:<16} {k:.3f}   {2*PAR*VW*k:6.0f}px      --        --     该层此时刻全黑")
        continue
    s, d, d0 = r
    conf = 1 - d/max(d0, 1e-6)
    print(f"  {tag:<16} {k:.3f}   {2*PAR*VW*k:6.0f}px   {s:7.0f}px   {conf:7.3f}   {'可信' if conf>0.5 else '弱'}")
    sh.append((s, conf))

good = [s for s, c in sh if c > 0.5]
if len(good) >= 3:
    mono = all(b >= a-6 for a, b in zip(good, good[1:]))
    print(f"\n单调（越近位移越大）: {mono}    最大/最小: {max(good)}/{min(good)} = {max(good)/max(1,min(good)):.2f}")
    print("判读：单调且比值 > 3 => 各层位移不一致，体积盒成立；比值≈1 => 整幅平移，无纵深")
else:
    print("\n高置信层不足 3 个，位移差结论不成立——需要换时刻或加大视差幅度")
