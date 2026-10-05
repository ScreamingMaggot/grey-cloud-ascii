"""沿视频的同一时间轴复现轨迹，逐时刻打印状态量与画面亮度。

    python measure/luminance_trace.py [起点秒] [终点秒] [步长秒]

用途：查"画面比声音先塌"这类问题。判据是**亮度对状态量的敏感度**——
如果相邻步长里 level/sharp/mel/baseMean 几乎没动而亮度跳了几倍，
问题不在驱动量而在形态场（实测就抓到过：噪声第三维没插值，
相位动 0.02 就让全局覆盖率从 65.7 掉到 20.1）。

必须按视频的连续相位跑：直接 `?demo=1&t=207` 打开时 phase 从 0 重新累积，
和渲染到第 35 秒的画面不是同一张图。
"""
import sys, pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE.parent / "grey_cloud_ascii.html"
T0 = float(sys.argv[1]) if len(sys.argv) > 1 else 172.0
T1 = float(sys.argv[2]) if len(sys.argv) > 2 else 232.0
DT = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
FPS = 25

INIT = """([t,fps])=>{document.getElementById('start').style.display='none';
 window.requestAnimationFrame=()=>0;
 while(oi<STEMS.onT.length&&STEMS.onT[oi]*ONSET_GAP<t)oi++;
 prevT=t; bolts.length=0; last=(t-1/fps)*1000;}"""

STEP = """(t)=>{audio={paused:false,currentTime:t};frame(t*1000);
 return {tNow:+tNow.toFixed(2),level:+level.toFixed(3),sharp:+sharp.toFixed(3),
  sharpSlow:+sharpSlow.toFixed(3),mel:+mel.toFixed(3),dying:+dying.toFixed(3),
  crack:+crack.toFixed(3),baseMean:+baseMean.toFixed(3),pulseLo:+pulseLo.toFixed(3),
  phase:+phase.toFixed(3),
  lum:(()=>{const d=cx.getImageData(0,0,cv.width,cv.height).data;let s=0;
    for(let i=0;i<d.length;i+=400)s+=d[i];return +(s/(d.length/400)).toFixed(1)})()};}"""

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1080, "height": 1080})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:140]))
    pg.goto(HTML.as_uri() + f"?demo=1&t={T0}", wait_until="load")
    pg.wait_for_timeout(800)
    pg.evaluate(INIT, [T0, FPS])
    rows = []
    t = T0
    while t <= T1 + 1e-9:
        pg.evaluate(STEP, t)
        for k in range(6):                       # 在该时刻多推几帧让它稳定
            pg.evaluate(STEP, t + k/10000)
        rows.append(pg.evaluate(STEP, t + 0.0007))
        t += DT
    fps = pg.evaluate("""async()=>{const t0=performance.now();let n=0;
      window.requestAnimationFrame=f=>setTimeout(()=>f(performance.now()),0);
      await new Promise(r=>{const f=()=>{n++;(performance.now()-t0<2000)?requestAnimationFrame(f):r()};
                             requestAnimationFrame(f)});
      return +(n/((performance.now()-t0)/1000)).toFixed(1)}""")
    b.close()

if errs:
    print("RUNTIME ERRORS:", errs[:3])

print(f"  t      亮度   level sharp sharpSl  mel  dying crack baseMn pulseLo  phase")
prev = None
worst = (0, 0.0)
for r in rows:
    mark = ""
    if prev is not None and prev > 8:
        jump = abs(r["lum"]-prev)/prev
        if jump > worst[0]: worst = (jump, r["tNow"])
        if jump > 0.25: mark = f"  <<< 跳变 {jump*100:.0f}%"
    prev = r["lum"]
    print(f"  {r['tNow']:6.1f} {r['lum']:6.1f}   {r['level']:.2f}  {r['sharp']:.2f}  {r['sharpSlow']:.2f}"
          f"  {r['mel']:.2f}  {r['dying']:.2f}  {r['crack']:.2f}  {r['baseMean']:.3f} {r['pulseLo']:+.3f}"
          f" {r['phase']:+8.3f}{mark}")

print(f"\n最大单步亮度跳变：{worst[0]*100:.0f}%（t={worst[1]:.1f}s，步长 {DT}s）")
print("判读：>25% 的跳变说明形态场对相位刀锋敏感，画面会'换脸'而不是'演化'")
print(f"（末态帧率参考值 {fps}fps —— 该页 rAF 已被驱动接管，此数仅供参照）")
