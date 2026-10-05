"""烘焙鼓点（分类 onset）与脉冲包络，注入 grey_cloud_ascii.html。

    python measure/bake_stems.py [drums.mp3] [vocals.mp3] [main.mp3]

为什么需要单独一条脉冲通道：实测主曲调制谱显示脉冲只存在于两端
（20~150Hz 深度 0.33~0.44 @4.0Hz；3000~11000Hz 深度 0.18~0.46 @5.3Hz），
中频只有 0.13~0.19。而主曲能量在作品里套了 6.5s 包络来表达「云越压越实」——
那正好把 4~5Hz 的脉动当噪声滤掉了。所以脉动必须单独走一条高时间分辨率通道。

另一个实测要点：低频 4Hz 的泵**不是鼓造成的**。kick 只检测到 117 个（约 0.5/s），
远低于 4Hz —— 那是低频声部自身的节奏性起伏（sidechain／音序 gating），
因此脉冲取自混音本身的去趋势调制，而不是 onset 的叠加。

鼓的三类是 k-means(k=3) 在 [log质心, <150Hz占比, 中频占比, >6kHz占比, 平坦度]
上跑出来的，再按质心从低到高指派 KICK/SNARE/HAT；实测质心 373 / 2749 / 6232 Hz，
三档拉开两个数量级，分得很开。固定 RandomState 保证每次跑结果一致。
"""
import sys, os, re, io, base64, subprocess, pathlib
import numpy as np

HERE   = pathlib.Path(__file__).resolve().parent
ROOT   = HERE.parent
DRUMS  = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(r"D:\Download\audio [drums].mp3")
VOCALS = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path(r"D:\Download\audio [vocals].mp3")
MAIN   = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "Grey Cloud - James Primate.mp3"
TARGET = ROOT / "grey_cloud_ascii.html"

FF = os.environ.get("FFMPEG") or str(pathlib.Path(
    r"D:\Enviornment\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"))
SR = 22050

def mono(p, tag):
    c = HERE / f"_{tag}.f32"
    if not c.exists():
        subprocess.run([FF, "-y", "-i", str(p), "-ac", "1", "-ar", str(SR),
                        "-f", "f32le", str(c)], check=True, capture_output=True)
    return np.fromfile(c, dtype="<f4")

D = mono(DRUMS, "drums"); V = mono(VOCALS, "vocals"); M = mono(MAIN, "main")

# ---------- 鼓 onset：谱通量，阈值放宽到能覆盖 4Hz 节奏 ----------
WIN, HOP = 1024, 256
w = np.hanning(WIN)
n = (len(D) - WIN) // HOP + 1
idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
S = np.abs(np.fft.rfft(D[idx] * w, axis=1))
flux = np.maximum(S[1:] - S[:-1], 0).sum(1)
flux = np.concatenate([[0.0], flux])
fps = SR / HOP
env = np.array([flux[max(0, i-6):i+7].mean() for i in range(len(flux))])
floor = np.percentile(flux, 45)
peaks = []
for i in range(2, len(flux) - 2):
    if not (flux[i] >= flux[i-1] and flux[i] > flux[i+1]): continue
    if not (flux[i] > env[i] * 1.45 and flux[i] > floor): continue
    if not peaks or (i - peaks[-1]) / fps > 0.055: peaks.append(i)
    elif flux[i] > flux[peaks[-1]]: peaks[-1] = i
ts = np.array([p / fps for p in peaks])
amp = np.clip(flux[peaks] / np.percentile(flux[peaks], 99), 0, 1)

# ---------- 每个 onset 的频谱特征 -> k-means 三类 ----------
FW = 2048; fr = np.fft.rfftfreq(FW, 1/SR); wf = np.hanning(FW)
FE = []
for t in ts:
    seg = D[int(t*SR):int(t*SR)+FW]
    if len(seg) < FW: seg = np.pad(seg, (0, FW-len(seg)))
    Sp = np.abs(np.fft.rfft(seg*wf)); tot = Sp.sum() + 1e-9
    cen = (fr*Sp).sum()/tot
    lo = Sp[fr < 150].sum()/tot; hi = Sp[fr > 6000].sum()/tot
    fl = np.exp(np.mean(np.log(Sp+1e-9)))/np.mean(Sp+1e-9)
    FE.append([np.log10(max(cen,1)), lo, 1-lo-hi, hi, fl])
FE = np.array(FE); X = (FE-FE.mean(0))/(FE.std(0)+1e-9)
best = None
for seed in range(40):                                   # 固定种子 -> 结果可复现
    rs = np.random.RandomState(seed)
    C = X[rs.choice(len(X), 3, replace=False)].copy()
    for _ in range(80):
        lab = ((X[:, None, :]-C[None, :, :])**2).sum(2).argmin(1)
        newC = np.array([X[lab == k].mean(0) if (lab == k).sum() else C[k] for k in range(3)])
        if np.allclose(newC, C, atol=1e-7): C = newC; break
        C = newC
    lab = ((X[:, None, :]-C[None, :, :])**2).sum(2).argmin(1)
    inertia = ((X-C[lab])**2).sum()
    if best is None or inertia < best[0]: best = (inertia, C, lab)
inertia, C, lab = best
cen_med = [np.median(10**FE[lab == k, 0]) for k in range(3)]
rank_of = {k: sorted(range(3), key=lambda j: cen_med[j]).index(k) for k in range(3)}
cls = np.array([rank_of[k] for k in lab])                # 0=KICK 1=SNARE 2=HAT

# ---------- 脉冲：主曲两端去趋势调制，30fps ----------
PW, PH = 1024, 735                                       # 735 采样 @22050 = 30fps
pn = (len(M)-PW)//PH + 1
pidx = np.arange(PW)[None, :] + PH*np.arange(pn)[:, None]
PS = np.abs(np.fft.rfft(M[pidx]*np.hanning(PW), axis=1))
pf = np.fft.rfftfreq(PW, 1/SR)
def band_env(a, b):
    e = PS[:, (pf >= a) & (pf < b)].sum(1)
    tr = np.convolve(np.pad(e, 15, mode="edge"), np.ones(31)/31, "valid")[:len(e)]
    m = e - tr
    # 按 99 分位定标：固定除数会让大部分点饱和成方波，脉动就失去层次了
    sc = np.percentile(np.abs(m), 99) or 1e-9
    return np.clip(m/sc, -1, 1)
pLo = ((band_env(20, 150)*0.5 + 0.5)*255).round().astype(np.uint8)
pHi = ((band_env(3000, 11000)*0.5 + 0.5)*255).round().astype(np.uint8)

# ---------- 旋律声部包络（0.5s 一格） ----------
STEP = int(SR*0.5); nv = len(V)//STEP
ve = np.array([np.sqrt(np.mean(V[i*STEP:(i+1)*STEP]**2)) for i in range(nv)])
vn = np.clip(ve/max(ve.max(), 1e-9), 0, 1)          # 只归一化一次
VOC = [int(round(v*100)) for v in vn]

b64 = lambda a: base64.b64encode(a.tobytes()).decode()
js = ("const STEMS={\n"
      f"  onT:[{','.join(str(int(round(t*100))) for t in ts)}],\n"
      f"  onA:[{','.join(str(int(round(a*100))) for a in amp)}],\n"
      f"  cls:[{','.join(str(int(c)) for c in cls)}],\n"
      f"  voc:[{','.join(map(str, VOC))}],\n"
      f"  pLo:'{b64(pLo)}',\n"
      f"  pHi:'{b64(pHi)}'}};\n"
      "const ONSET_GAP=0.01, PULSE_FPS=30;   // onT 单位 0.01s；pLo/pHi 每帧 30 分之一秒")

html = io.open(TARGET, encoding="utf-8").read()
pat = r"const STEMS=\{.*?\};\nconst ONSET_GAP=[^\n]*"
if re.search(pat, html, re.S):
    out = re.sub(pat, lambda m: js, html, count=1, flags=re.S)
else:
    k = html.find("const CURVES=")
    if k < 0: raise SystemExit("anchor not found")
    out = html[:k] + js + "\n" + html[k:]
io.open(TARGET, "w", encoding="utf-8").write(out)

NAMES = ["KICK", "SNARE", "HAT"]
print(f"injected into {TARGET.name}: {len(ts)} onsets, pulse {len(pLo)}+{len(pHi)} bytes b64")
print(f"kmeans inertia {inertia:.0f}")
for c in range(3):
    m = cls == c
    print(f"  {NAMES[c]:6s} n={int(m.sum()):4d} centroid {np.median(10**FE[m,0]):6.0f}Hz "
          f"low<150 {np.median(FE[m,1]):.2f} hi>6k {np.median(FE[m,3]):.2f} rate {m.sum()/235:.2f}/s")
print(f"  pulse  low mean|amp| {np.abs(pLo/127.5-1).mean():.2f}  high {np.abs(pHi/127.5-1).mean():.2f}")
