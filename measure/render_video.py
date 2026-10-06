"""把 grey_cloud_ascii.html 逐帧驱动渲染成视频（不靠实时帧率，所以不会掉帧也不会跑偏）。

    python measure/render_video.py --out 名.mp4 --t0 168.5 --dur 60 --w 1080 --h 1080 --fps 25

为什么不用屏幕录制：页面实时跑 50fps，录制会掉帧、而且和音频对不齐。
这里改成"手工时钟"——把 rAF 换成空操作，然后按固定步长调 frame(t*1000)：
  · audio={paused:false,currentTime:t} 让 tNow 精确等于我要的时刻
  · 相邻两次传的时间戳差恰好 1/fps，所以 dt 也精确是 1/fps，phase 正常推进
帧字节直接管给 ffmpeg（image2pipe），不留上万张中间图。

注意 pumpOnsets：正向跳时刻时它的 while 循环会把 t0 之前的所有鼓点一次性放出来，
开局就糊几十条闪电。所以驱动里先把 oi 推到 t0 之后。
"""
import argparse, pathlib, subprocess, sys, tempfile, time
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE.parent / "grey_cloud_ascii.html"
MP3 = HERE.parent / "Grey Cloud - James Primate.mp3"
FF = pathlib.Path(imageio_ffmpeg.get_ffmpeg_exe())

INIT = """([t, fps]) => {
  document.getElementById('start').style.display = 'none';
  window.requestAnimationFrame = () => 0;              // 关掉自走循环
  // 正向跳时刻：先把鼓点游标推到 t 之后，否则第一帧会一次性放出几十条闪电
  while(oi < STEMS.onT.length && STEMS.onT[oi]*ONSET_GAP < t) oi++;
  prevT = t; tNow = t; bolts.length = 0;
  // 驱动必须维护自己的合成页钟。原先写 last=(t-1/fps)*1000，把「歌曲时间」当成
  // performance.now()（页面运行时间）：那个已经排队的 rAF 回调用真实时间戳进来时
  // dt 变成 -99.5 秒，tNow 被推到 5 秒，pumpOnsets 判定「时间回跳」而重置游标；
  // 下一步再拨回目标时刻，它就把该时刻之前所有鼓点一次性放出来（实测 354 条）。
  window.__now = performance.now();
  window.__fps = fps;
  last = window.__now - 1000/fps;
  audio = {paused:false, currentTime:t};               // 立刻钉住 tNow，让漏进来的回调翻不起浪
  return {tNow:+tNow.toFixed(3), oi, bolts:bolts.length};
}"""

STEP = """(t) => {
  audio = {paused:false, currentTime:t};               // frame() 里 tNow 会取这个值
  window.__now += 1000/window.__fps;                   // 页钟按固定步长走 => dt 恒为 1/fps
  frame(window.__now);
  return 0;
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--t0", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=60.0)
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--crf", type=int, default=19)
    ap.add_argument("--fade-out", type=float, default=0.0)
    ap.add_argument("--fade-in", type=float, default=0.0)
    ap.add_argument("--jpeg", action="store_true",
                    help="用 JPEG 帧管进 ffmpeg。实测 1920x1080 下 PNG 截图 366ms/帧、"
                         "JPEG 72ms/帧——瓶颈是 PNG 编码加把 2MB base64 搬过 CDP，"
                         "画面本身只要 30ms。q95 相对 PNG 平均差 1.75/255。")
    a = ap.parse_args()

    n = int(round(a.dur*a.fps))
    out = pathlib.Path(a.out) if pathlib.Path(a.out).is_absolute() else HERE.parent/a.out
    out.parent.mkdir(parents=True, exist_ok=True)

    # fade 的 st 在"输出时间轴"上（从 0 起），不是源曲时刻。之前直接填 a.t0，
    # 结果 4 秒测试片整段落在淡入里——出来是全黑的。
    vf = []
    if a.fade_in > 0:  vf.append(f"fade=t=in:st=0:d={a.fade_in}:color=black")
    if a.fade_out > 0: vf.append(f"fade=t=out:st={a.dur-a.fade_out:.3f}:d={a.fade_out}:color=black")
    af = []
    if a.fade_in > 0:  af.append(f"afade=t=in:st=0:d={a.fade_in}")
    if a.fade_out > 0: af.append(f"afade=t=out:st={a.dur-a.fade_out}:d={a.fade_out}")

    cmd = [str(FF), "-y", "-loglevel", "error",
           "-f", "image2pipe", "-framerate", str(a.fps),
           "-c:v", "mjpeg" if a.jpeg else "png", "-i", "pipe:0",
           "-ss", f"{a.t0:.3f}", "-t", f"{a.dur:.3f}", "-i", str(MP3)]
    if vf: cmd += ["-vf", ",".join(vf)]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf),
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv",
            "-r", str(a.fps), "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-shortest", str(out)]

    print(f"渲染 {a.w}x{a.h} @{a.fps}fps  t={a.t0}..{a.t0+a.dur}s  共 {n} 帧 -> {out.name}")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    t_start = time.time()
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge")
        pg = b.new_page(viewport={"width": a.w, "height": a.h})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
        pg.goto(HTML.as_uri() + f"?demo=1&t={a.t0}", wait_until="load")
        pg.wait_for_timeout(800)
        st = pg.evaluate(INIT, [a.t0, a.fps])
        print(f"  驱动就绪: {st}")
        if errs: print("  PAGE ERRORS:", errs[:3])
        for i in range(n):
            t = a.t0 + i/a.fps
            pg.evaluate(STEP, t)
            png = pg.screenshot(type="jpeg", quality=95) if a.jpeg else pg.screenshot(type="png")
            proc.stdin.write(png)
            if i % 250 == 0:
                el = time.time()-t_start
                eta = el/max(i,1)*(n-i)
                print(f"  {i:5d}/{n}  t={t:7.2f}s  {el:5.0f}s 已用  预计还需 {eta:5.0f}s")
        pg.evaluate("() => ({tNow:+tNow.toFixed(2), bolts:bolts.length})")
        b.close()
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    rc = proc.wait()
    print(f"  ffmpeg rc={rc}  用时 {time.time()-t_start:.0f}s")
    if rc: print(err[-1500:]); sys.exit(1)
    if err.strip(): print("  ffmpeg:", err.strip()[-400:])
    verify(out, a)
    print(f"  完成: {out}  ({out.stat().st_size/1e6:.1f} MB)")


def verify(out, a):
    """成片自检：抽两帧比亮度与差异。
    上一版 fade 的 st 填成了源曲时刻，整段落在淡入里，出来是 11kb/s 的全黑片，
    而 rc=0、时长也对——不看像素根本发现不了。"""
    import numpy as np
    from PIL import Image
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rv_"))
    for pos, tag in ((0.25, "a"), (0.75, "b")):
        subprocess.run([str(FF), "-y", "-loglevel", "error", "-ss", f"{a.dur*pos:.2f}",
                        "-i", str(out), "-frames:v", "1", str(tmp/f"{tag}.png")], check=True)
    A = np.asarray(Image.open(tmp/"a.png").convert("L"), dtype=np.float64)
    B = np.asarray(Image.open(tmp/"b.png").convert("L"), dtype=np.float64)
    chg = float((np.abs(A-B) > 12).mean()*100)
    print(f"  自检: 亮度 {A.mean():.1f} / {B.mean():.1f} (max {A.max():.0f})  两帧差异 {chg:.1f}%")
    bad = []
    if A.mean() < 6 or B.mean() < 6: bad.append("画面全黑——检查 fade 或驱动")
    if chg < 0.3: bad.append("两帧几乎相同——动画没在跑")
    for m in bad: print("  !! " + m)
    return not bad


if __name__ == "__main__":
    main()
