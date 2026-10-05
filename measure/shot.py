"""按时刻渲染预览并实测帧率（真实 1080x1080 视口，用系统 Edge）。

用法:
  python shot.py [html文件名] [标签] [t1,t2,...] [seed]
  例: python shot.py grey_cloud_ascii.html ascii 20,100,160,228
      python shot.py 风卷残云.html svg 3,16 7
"""
import sys, json, pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE.parent / (sys.argv[1] if len(sys.argv) > 1 else "风卷残云.html")
TAG  = sys.argv[2] if len(sys.argv) > 2 else "shot"
times = [float(t) for t in (sys.argv[3].split(",") if len(sys.argv) > 3 else ["3"])]
seed  = sys.argv[4] if len(sys.argv) > 4 else "7"
OUT   = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\art")
OUT.mkdir(exist_ok=True)

is_ascii = "ascii" in HTML.name
def url_for(t):
    if is_ascii:
        return HTML.as_uri() + f"?demo=1&t={max(0.0, t-1.2)}"
    return HTML.as_uri() + f"?seed={seed}"

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(f"{m.type}: {m.text}") if m.type == "error" else None)

    fps = None
    for t in times:
        pg.goto(url_for(t), wait_until="load")
        pg.wait_for_timeout(900)
        if fps is None:
            fps = pg.evaluate("""async () => { const t0=performance.now(); let n=0;
              await new Promise(r=>{const f=()=>{n++;(performance.now()-t0<3000)?requestAnimationFrame(f):r()};
                                     requestAnimationFrame(f)});
              return +(n/((performance.now()-t0)/1000)).toFixed(1)}""")
        f = OUT / f"{TAG}_{t:g}s.png"
        pg.screenshot(path=str(f))
        print("shot", f)

    info = pg.evaluate("""() => ({art: window.ART || null,
        canvas: !!document.querySelector('canvas')})""")
    print(json.dumps({"fps": fps, "errors": errs[:6], **info}, ensure_ascii=False))
    b.close()
