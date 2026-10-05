"""从 mp3 烘焙驱动曲线，并注入 grey_cloud_ascii.html —— 一条命令重建作品数据。

    python measure/bake_curves.py [mp3路径]

产出两层时间尺度：
  · rms/low/mid/high/cent —— 6.5s 滑动包络，表达「云越压越实」的趋势
  · crack                 —— 低频被抽空的瞬时事件，保留锐度

为什么必须分开：实测高频曲线逐帧剧抖（41,24,38,65,34,61,25,53,46,79…），
若用瞬时值控制覆盖度，画面会在十秒内从 3% 跳到 22%——那是闪烁，不是积聚。
"""
import sys, os, re, io, subprocess, pathlib
import numpy as np

HERE   = pathlib.Path(__file__).resolve().parent
ROOT   = HERE.parent
MP3    = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "Grey Cloud - James Primate.mp3"
TARGET = ROOT / "grey_cloud_ascii.html"

FF = os.environ.get("FFMPEG") or str(pathlib.Path(
    r"D:\Enviornment\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"))
if not pathlib.Path(FF).exists():
    raise SystemExit("找不到 ffmpeg：请设 FFMPEG 环境变量指向可执行文件")

# ---------- 解码（缓存到 measure/，删掉即可重算） ----------
cache = HERE / "_mono.f32"
if not cache.exists():
    subprocess.run([FF, "-y", "-i", str(MP3), "-ac", "2", "-ar", "22050",
                    "-f", "f32le", str(cache)], check=True, capture_output=True)
x = np.fromfile(cache, dtype="<f4").reshape(-1, 2).mean(1)

SR, WIN, STEP = 22050, 2048, int(22050 * 0.5)
freqs, wdw = np.fft.rfftfreq(WIN, 1 / SR), np.hanning(WIN)
n = len(x) // STEP
LO = (freqs >= 20) & (freqs < 130)
MI = (freqs >= 350) & (freqs < 2200)
HI = (freqs >= 4200) & (freqs < 11000)
RMS = np.zeros(n); L = np.zeros(n); M = np.zeros(n); H = np.zeros(n); C = np.zeros(n)
for i in range(n):
    fr = x[i*STEP:i*STEP+WIN] * wdw
    S = np.abs(np.fft.rfft(fr)) + 1e-9
    RMS[i] = np.sqrt(np.mean(fr**2)); L[i] = S[LO].sum()
    M[i] = S[MI].sum(); H[i] = S[HI].sum(); C[i] = (freqs*S).sum()/S.sum()

# ---------- 归一化 ----------
def smooth(a, k):
    ker = np.ones(k)/k
    return np.convolve(np.pad(a, (k//2, k//2), mode="edge"), ker, mode="valid")[:len(a)]
def nz(v, floor_db=None):
    v = v.astype(float)
    if floor_db is not None:
        db = np.clip(20*np.log10(np.maximum(v, 1e-9)), floor_db, None)
        v = (db - floor_db)/(db.max() - floor_db)
    else:
        v = (v - v.min())/(v.max() - v.min() + 1e-12)
    return np.clip(v*100, 0, 100).round().astype(int)

W = 13                                                  # 6.5s 包络
rms, Ln, Mn, Hn, Cn = (nz(smooth(RMS, W), -38), nz(smooth(L, W)), nz(smooth(M, W)),
                       nz(smooth(H, W)), nz(smooth(C, W)))
base = np.array([np.median(L[max(0, i-60):i+60]) + 1e-9 for i in range(n)])
cr = np.clip((1 - smooth(L, 3)/base - 0.22)/0.40, 0, 1)*100
for i in range(n):                                      # 首尾静音段不算事件
    if i*0.5 < 10 or i*0.5 > 222: cr[i] = 0
crn = cr.round().astype(int)

js = "const CURVES={\n" + ",\n".join(
    f"  {k}:[{','.join(map(str, a.tolist()))}]"
    for k, a in [("rms", rms), ("low", Ln), ("mid", Mn), ("high", Hn),
                 ("cent", Cn), ("crack", crn)]) + "};"

# ---------- 注入 ----------
html = io.open(TARGET, encoding="utf-8").read()
m = re.search(r"const CURVES=\{.*?\};", html, re.S)
if not m:
    raise SystemExit(f"const CURVES={{...}}; not found in {TARGET.name}, injection aborted")
io.open(TARGET, "w", encoding="utf-8").write(html[:m.start()] + js + html[m.end():])

seg = lambda a, b: Hn[int(a*2):int(b*2)].mean()
print(f"{MP3.name}: {n} bins / {n*0.5:.0f}s  -> injected into {TARGET.name}")
print(f"  high envelope  20-100s {seg(20,100):.0f} -> 140-190s {seg(140,190):.0f} -> >210s {Hn[420:].mean():.0f}")
print(f"  low-dropout events: {int((crn>40).sum())}")
