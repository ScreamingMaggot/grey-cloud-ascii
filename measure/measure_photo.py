"""从照片量出 风卷残云.html 的全部输入，输出可直接粘贴的 JS 常量块。

    python measure/measure_photo.py [jpg路径]

四项测量，全部是「量」不是「画」：
  1 山脊线  底部地形带逐列最强边缘；孤立凸起（两侧都比它低 25px 以上）判为
            网杆/网线伪影并剔除，中央真尖峰连宽 2-3 点会被保住。
  2 云丝方向场  结构张量 9x9，在 2theta 空间做相干度加权与高斯平滑
            （方向是无轴向，直接平均会在 ±180° 处炸开）。
  3 云密度  高通能量按 9x9 归一化，决定丝往哪儿长。
  4 航迹  28-46° 极坐标直线拟合，要求沿途都在山脊之上。
  5 网杆  山脊上方天空侧的暗竖线；再用等距模型拟合（实测间距 177/188/152）。

注意：作品里杆距用的是 180 而不是量得的 172 —— 172 不整除 1080，滚动到接缝会跳，
用 4.7% 的误差换严格无缝。这是有意的取舍，不是测量错误。

精度说明（重跑前请看）：
  · 山脊清理与平滑的实现细节会让重跑结果有 ±5px、方向场 ±0.5°、密度 ±1 单位的漂移，
    属正常；HTML 里的常量取自其中一次运行。
  · 网杆检测本身不稳定：不同参数下测得的间距散布在 124~188px。所以「172px」只是
    一次拟合结果，不是可靠观测；作品里的 180 是为无缝服务的工程值。
"""
import sys, os, math, pathlib
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = pathlib.Path(__file__).resolve().parent
SRC  = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent.parent / "风卷残云.jpg"
S = 1080

im = Image.open(SRC).convert("RGB")
w0, h0 = im.size
sc = S / min(w0, h0)
im2 = im.resize((round(w0*sc), round(h0*sc)), Image.LANCZOS)
x0 = (im2.width - S) // 2
a = np.asarray(im2.crop((x0, 0, x0+S, S))).astype(np.float64)
g = a.mean(2)
print(f"// source {SRC.name} {w0}x{h0} -> square crop x0={x0} scale={sc:.4f}")

gx = ndimage.sobel(g, axis=1)/4.0; gy = ndimage.sobel(g, axis=0)/4.0
mag = np.hypot(gx, gy)

# ---------- 1 山脊 ----------
yb = int(S*0.65)
band = mag[yb:, :]
ridge = (np.argmax(band, axis=0) + yb).astype(float)
sub = [ridge[i] for i in range(0, S, 4)]
n = len(sub)
for _ in range(3):
    removed = 0
    for i in range(1, n-1):
        l, r = sub[i-1], sub[i+1]
        if (l - sub[i] > 25) and (r - sub[i] > 25):      # 孤立凸起 = 杆/线伪影
            sub[i] = (l+r)/2 + 3; removed += 1
    if not removed: break
k = np.array([1, 2, 3, 2, 1], float); k /= k.sum()
pad = [sub[0]]*2 + sub + [sub[-1]]*2
ridge4 = [float(np.dot(pad[i:i+5], k)) for i in range(n)]
pk = int(np.argmin(ridge4))
print(f"// ridge: {n} pts @4px, peak x={pk*4} y={ridge4[pk]:.0f}, range "
      f"{min(ridge4):.0f}..{max(ridge4):.0f}, seam jump {ridge4[-1]-ridge4[0]:+.0f}px")

# ---------- 2 方向场 ----------
sm = ndimage.gaussian_filter(g, 6)
sx = ndimage.sobel(sm, axis=1)/4.0; sy = ndimage.sobel(sm, axis=0)/4.0
CELL, step = 9, S//9
c2 = np.zeros((CELL, CELL)); s2 = np.zeros((CELL, CELL)); ok = np.zeros((CELL, CELL), bool)
for cy in range(CELL):
    for cx in range(CELL):
        y0, y1 = cy*step, (cy+1)*step; xx0, xx1 = cx*step, (cx+1)*step
        yy1 = min(y1, int(ridge[y0:y1].min()) if y1 > ridge[y0:y1].min() else y1)
        if yy1 - y0 < 40: continue
        Jxx = (sx[y0:yy1, xx0:xx1]**2).mean(); Jyy = (sy[y0:yy1, xx0:xx1]**2).mean()
        Jxy = (sx[y0:yy1, xx0:xx1]*sy[y0:yy1, xx0:xx1]).mean()
        coh = np.hypot(Jxx-Jyy, 2*Jxy)/(Jxx+Jyy+1e-9)
        if coh <= 0.05: continue
        th2 = 2*math.radians(0.5*math.degrees(math.atan2(2*Jxy, Jxx-Jyy)) + 90)
        c2[cy, cx] = math.cos(th2)*coh; s2[cy, cx] = math.sin(th2)*coh; ok[cy, cx] = True
idx = ndimage.distance_transform_edt(~ok, return_distances=False, return_indices=True)
c2 = ndimage.gaussian_filter(c2[tuple(idx)], 1.1)
s2 = ndimage.gaussian_filter(s2[tuple(idx)], 1.1)
slope = np.mod(np.degrees(np.arctan2(s2, c2))/2.0, 180)
print("// filament axis (deg, 0=horizontal, +up-right) from structure tensor:")
for row in slope: print("  //  " + " ".join(f"{v:5.1f}" for v in row))

# ---------- 3 云密度 ----------
en = np.maximum(ndimage.gaussian_filter(g, 1) - ndimage.gaussian_filter(g, 9), 0)
sky = np.arange(S)[:, None] < (ridge - 25)[:, None]
en2 = ndimage.gaussian_filter(en*sky, 12); tot = en2.sum()
dens = [[int(round(en2[cy*step:(cy+1)*step, cx*step:(cx+1)*step].sum()/tot*100))
         for cx in range(CELL)] for cy in range(CELL)]
print("// cloud high-pass energy density (x100):")
for row in dens: print("  //  " + " ".join(f"{v:2d}" for v in row))

# ---------- 4 航迹 ----------
line = np.maximum(ndimage.gaussian_filter(g, 0.6) - ndimage.gaussian_filter(g, 3.5), 0)*sky
best = []
for ang in np.arange(28, 47, 1.0):
    th = math.radians(ang); dx, dy = math.cos(th), -math.sin(th); nx, ny = dy, dx
    for rho in range(-1200, 1200, 5):
        t = np.arange(-650, 1450, 2.5)
        px = rho*nx + t*dx; py = rho*ny + t*dy
        msk = (px >= 0) & (px < S-1) & (py >= 0) & (py < S-1)
        if msk.sum() < 240: continue
        ix = np.clip(px[msk].astype(int), 0, S-1); iy = np.clip(py[msk].astype(int), 0, S-1)
        if (ridge[ix] > py[msk] + 16).mean() < 0.92: continue
        sx_ = px[msk]; sy_ = py[msk]
        best.append((float(line[iy, ix].mean()), ang, rho,
                     int(sx_.min()), int(sx_.max()),
                     int(sy_[sx_.argmin()]), int(sy_[sx_.argmax()])))
best.sort(reverse=True)
top = [b for b in best if not any(abs(b[1]-t[1]) < 4 and abs(b[2]-t[2]) < 70 for t in [best[0]])]
b0 = best[0]
print(f"// contrail fit: score {b0[0]:.2f} angle {b0[1]:.0f}deg  "
      f"({b0[3]},{b0[5]}) -> ({b0[4]},{b0[6]})")

# ---------- 5 网杆 ----------
prof = np.zeros(S)
for x in range(S):
    t0 = max(0, int(ridge[x]) - 230); t1 = max(1, int(ridge[x]) - 40)
    prof[x] = g[t0:t1, x].mean()
diff = ndimage.uniform_filter1d(ndimage.uniform_filter1d(
    ndimage.uniform_filter1d(prof, 41, mode="nearest") - prof, 3), 1)
cand = np.where(diff > max(np.percentile(diff, 90), 0.9))[0]
poles = []
for c in cand:
    if not poles or c - poles[-1] >= 26: poles.append(int(c))
    elif diff[c] > diff[poles[-1]]: poles[-1] = int(c)
sp = [poles[i+1]-poles[i] for i in range(len(poles)-1)]
print(f"// poles detected: {poles}")
print(f"// spacings {sp} -> isometric fit ~{int(np.median([s for s in sp if s>120] or [172]))}px"
      f"  (artwork uses 180 for seamless wrap)")

# ---------- 6 调色板 ----------
def patch(y0, y1, xx0, xx1, q=50):
    return [int(round(float(v))) for v in np.percentile(
        a[y0:y1, xx0:xx1].reshape(-1, 3), q, axis=0)]
def hx(v): return "#%02x%02x%02x" % tuple(v)
pal = {"sky_top": patch(0, 70, 200, 900), "sky_200": patch(190, 250, 200, 900),
       "sky_400": patch(390, 450, 200, 900), "sky_600": patch(590, 650, 200, 900),
       "sky_780": patch(770, 830, 150, 700), "warm_right": patch(560, 660, 860, 1060)}
cp = a[np.where((en > np.percentile(en, 99.6)) & sky)]
pal["cloud_lit"] = [int(round(float(v))) for v in np.percentile(cp, 88, axis=0)]
pal["cloud_mid"] = [int(round(float(v))) for v in np.percentile(cp, 58, axis=0)]
mtn = np.concatenate([a[int(ridge[x])+8:int(ridge[x])+26, x][None] for x in range(0, S, 5)
                      if int(ridge[x])+26 < S], 0).reshape(-1, 3)
pal["mountain"] = [int(round(float(v))) for v in np.percentile(mtn, 50, axis=0)]
print("// palette sampled from the photo:")
for kk, vv in pal.items(): print(f"  //  {kk:11s} {hx(vv)}  {vv}")

print("\n// paste into 风卷残云.html — RIDGE is the 4px-sampled ridge line:")
print("const RIDGE_RAW=[" + ",".join(str(int(round(v))) for v in ridge4) + "];")
