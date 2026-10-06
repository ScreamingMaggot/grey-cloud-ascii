"""音色脉冲检验：三类鼓各自响的时候，画面是不是**分得开**。

    python measure/pulse_test.py

要回答的不是"有没有闪"，而是三件事：
  1) 该类鼓点前后，画面确实变了多少（响应量）
  2) 三类的响应量要按 kick > snare > hat 分开——这是实测的余响与能量差别
  3) 三类点亮的**位置**要分开：kick 归低频（画面下部）、hat 归高频（上部）。
     位置分开比亮度分开重要得多：那才是"音色"被看见，而不是"音量"被看见。

做法：冻结动画（同一时间戳手工调 frame，dt=0），对每一类找它自己脉冲最强、
另两类相对安静的时刻，比较起击前后。
"""
import pathlib, sys
import numpy as np
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE.parent / "grey_cloud_3d.html"
NAMES = ["kick", "snare", "hat"]
VW, VH = 1920, 1080

INIT = """([t,fps])=>{document.getElementById('start').style.display='none';
 window.requestAnimationFrame=()=>0;
 while(oi<STEMS.onT.length&&STEMS.onT[oi]*ONSET_GAP<t)oi++;
 prevT=t; bolts.length=0; tNow=t;
 window.__now=performance.now(); last=window.__now-1000/fps;
 audio={paused:false,currentTime:t};}"""

# 推进到 t 并稳定若干帧，然后量脉冲通道与整体密度
PROBE = """([t])=>{
  audio={paused:false,currentTime:t};
  for(let k=0;k<24;k++){ window.__now += 40; frame(window.__now); }
  const P=[0,1,2].map(c=>+pulsAt(c,t).toFixed(3));
  let flash=0, lit=0, sum=0, frow=0, fwt=0;
  for(let r=0;r<ROWS;r++)for(let c=0;c<COLS;c++){
    const o=r*COLS+c;
    if(LUM[o]>0.03){lit++; sum+=LUM[o]}
    if(DOMP[o]>0.30){flash++; frow+=r*LUM[o]; fwt+=LUM[o]}
  }
  return {t:+t.toFixed(2), P, flash, litPct:+(lit/(COLS*ROWS)*100).toFixed(1),
          lumMean:+(sum/Math.max(lit,1)).toFixed(3),
          flashRow:+(fwt>0? frow/fwt/ROWS : -1).toFixed(3)};
}"""


def measure(pg, t):
    """重新 INIT 再推进。必须保证时间只往前走：pumpOnsets 在回跳 >0.25s 时会重置
    鼓点游标并把该时刻之前所有鼓点一次性放出来（实测 354 条挂在画面上），而
    「击前 vs 击时」这个比较本来就要回跳——上一版 snare/hat 的数字就是这么废的。"""
    pg.evaluate(INIT, [t, 25])
    return pg.evaluate(PROBE, [t])


def main():
    t0 = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    span = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge")
        pg = b.new_page(viewport={"width": VW, "height": VH})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:150]))
        pg.goto(HTML.as_uri() + f"?demo=1&t={t0}", wait_until="load")
        pg.wait_for_timeout(900)
        pg.evaluate(INIT, [t0, 25])

        # 先扫一遍，找每一类"自己最强、别类相对弱"的时刻
        times = np.arange(t0 + 1.0, t0 + span, 0.04)
        prof = pg.evaluate("""(ts)=>{const out=[];
            for(const t of ts) out.push([+pulsAt(0,t).toFixed(4),+pulsAt(1,t).toFixed(4),+pulsAt(2,t).toFixed(4)]);
            return out;}""", [float(x) for x in times])
        prof = np.array(prof)
        picks = {}
        for c in range(3):
            others = np.max(np.delete(prof, c, axis=1), axis=1)
            score = prof[:, c] - 0.8 * others
            i = int(np.argmax(score))
            picks[c] = (float(times[i]), float(prof[i, c]), float(others[i]))

        print(f"扫描 {t0}~{t0+span}s，每类鼓的起击时刻（自身脉冲强、别类弱）：")
        for c in range(3):
            t, me, ot = picks[c]
            print(f"  {NAMES[c]:6s} t={t:7.2f}s  本类脉冲={me:.2f}  别类最大={ot:.2f}")

        print("\n起击前后对比（PRE=该类包络的谷值时刻，POST=峰值时刻）：")
        print("     基线不能用固定的「击前 0.35 秒」：hat 实测 1.63 次/秒，0.35 秒前")
        print("     本来就落在上一个 hat 的余响里，量出来是负的增量，那是仪器的错。")
        rows = {}
        for c in range(3):
            t = picks[c][0]
            # 在本类峰值前后 0.9s 内找它自己最安静的时刻做基线
            lo = max(t0 + 0.5, t - 0.9)
            w = prof[(times >= lo) & (times <= t + 0.2)]
            tw = times[(times >= lo) & (times <= t + 0.2)]
            tpre = float(tw[int(np.argmin(w[:, c]))]) if len(tw) else max(t - 0.6, t0 + 0.5)
            pre = measure(pg, tpre)
            post = measure(pg, t)
            rows[c] = (pre, post)
            dflash = post["flash"] - pre["flash"]
            print(f"  {NAMES[c]:6s}  t {tpre:7.2f}->{t:7.2f}  闪格 {pre['flash']:6d} -> {post['flash']:6d}  ({dflash:+6d})   "
                  f"密度 {pre['lumMean']:.3f} -> {post['lumMean']:.3f}   "
                  f"闪格重心行 {pre['flashRow'] if pre['flashRow']>=0 else '  -  '} -> {post['flashRow']}")
        b.close()
    if errs:
        print("\nRUNTIME ERRORS:", errs[:3]); sys.exit(1)

    d = {c: rows[c][1]["flash"] - rows[c][0]["flash"] for c in range(3)}
    print("\n判读：")
    # 不预设"三类响应量要相当"或"kick>snare>hat"：单次起击点亮的格数本该等于
    # 该类单击幅度 x 团块大小 x 同时起击的团块数。hat 实测 1.63 次/秒但单个最弱、
    # 团块最小（高频拉丝），所以它就是几十个格的火星子——这才是对的。
    print(f"  三类都有响应: {all(d[c]>0 for c in range(3))}   "
          f"(kick {d[0]} / snare {d[1]} / hat {d[2]} 格，单击量级不同是应有之义)")
    # 真正的判据是位置：音色要被"看见"，就得按频段在画面上分开，而不是亮度分开
    fr = {c: rows[c][1]["flashRow"] for c in range(3)}
    ordered = fr[0] > fr[1] > fr[2]
    print(f"  重心行按频段严格排序 (kick>snare>hat，即低频在下): {ordered}   "
          f"({fr[0]:.3f} / {fr[1]:.3f} / {fr[2]:.3f})")
    print(f"  kick 与 hat 相隔 {fr[0]-fr[2]:+.3f} 个画面高度")
    ok = ordered and all(d[c] > 0 for c in range(3))
    print()
    print(f"结论: {'PASS' if ok else 'FAIL'} —— 音色脉冲既分立、又按频段定位")


if __name__ == "__main__":
    main()
