"""闪电余辉检验：光辉应当「外扩 + 变淡」，不是原地收缩。

    python measure/halo_test.py [时刻]

按颜色把像素分成「蓝白核心」和「黄橙光晕」（灰色云层两者都不满足，所以不会被
云本身污染），然后量光晕像素到通道折线的距离分布。
判读：r95（95 分位距离）随 grow 上升 = 外扩；r95 下降或不变 = 原地变暗/向内收缩。
"""
import sys, pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE.parent / "grey_cloud_ascii.html"
T0 = float(sys.argv[1]) if len(sys.argv) > 1 else 40
OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\halo"); OUT.mkdir(exist_ok=True)

PROBE = """async () => {
  const cv=document.getElementById('c'), g=cv.getContext('2d');
  const rows=[];
  await new Promise(res=>{
    const t0=performance.now();
    const f=()=>{
      if(bolts.length){
        const b=bolts[0], grow=(tNow-b.t)/b.life;
        if(grow>=0 && grow<=1.05){
          const R=300;
          const x0=Math.max(0,Math.round(b.cx-R)), x1=Math.min(cv.width,Math.round(b.cx+R));
          const y0=Math.max(0,Math.round(b.cy-R)), y1=Math.min(cv.height,Math.round(b.cy+R));
          const d=g.getImageData(x0,y0,x1-x0,y1-y0).data, W=x1-x0, H=y1-y0;
          /* 逐像素找最近通道点是 O(像素x点数)，一帧就几千万次，帧率掉了测的
             就不是同一件事。改成 4px 栅格 + 多源 BFS 距离场：一次建场，逐像素查表。 */
          const CS=4, gw=Math.ceil(W/CS), gh=Math.ceil(H/CS);
          const dist=new Int32Array(gw*gh).fill(-1), q=[];
          const pts=[]; for(const one of [b.pts].concat(b.br)) for(const p of one) pts.push(p);
          for(const p of pts){
            const gx=Math.round((p[0]-x0)/CS), gy=Math.round((p[1]-y0)/CS);
            for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){
              const j=gy+dy, i=gx+dx;
              if(i<0||i>=gw||j<0||j>=gh) continue;
              if(dist[j*gw+i]===-1){ dist[j*gw+i]=0; q.push(j*gw+i) }
            }
          }
          for(let head=0;head<q.length;head++){
            const o=q[head], x=o%gw, y=(o/gw)|0, dd=dist[o]+1;
            const nb=[[x-1,y],[x+1,y],[x,y-1],[x,y+1]];
            for(const n of nb){
              if(n[0]<0||n[0]>=gw||n[1]<0||n[1]>=gh) continue;
              const oo=n[1]*gw+n[0];
              if(dist[oo]===-1){ dist[oo]=dd; q.push(oo) }
            }
          }
          let halo=0, core=0, far=0; const ds=[];
          for(let y=0;y<H;y++)for(let x=0;x<W;x++){
            const i=(y*W+x)*4, r=d[i], gg=d[i+1], bb=d[i+2];
            // 云层本身是冷灰(176,182,193)，bb-r 就有 17，所以核心必须同时接近纯白
            if(bb>200 && r>190 && bb-r>10){ core++; continue }     // 蓝白：高温通道
            if(r>16 && (r-bb)>0.30*r && bb<210){                  // 黄橙：光晕
              // 判据用「色度比」而不是绝对亮度：绝对阈值会让变暗的外圈先掉出
              // 检测，量出来的是"向内收缩"，其实是仪器假象。
              const dv=dist[((y/CS)|0)*gw+((x/CS)|0)];
              if(dv<0) continue;
              const pd=dv*CS;
              if(pd>200){ far++; continue }   // 远处的暖色多半是裂缝天光，不算光晕
              ds.push(pd); halo++;
            }
          }
          ds.sort((a,bb)=>a-bb);
          rows.push({grow:+grow.toFixed(2), core, halo, far,
                     r50:halo?+ds[Math.floor(ds.length*0.5)].toFixed(1):0,
                     r95:halo?+ds[Math.min(ds.length-1,Math.floor(ds.length*0.95))].toFixed(1):0});
        }
      }
      if(performance.now()-t0<4000) requestAnimationFrame(f); else res();
    };
    requestAnimationFrame(f);
  });
  return rows;
}"""

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto(HTML.as_uri() + f"?demo=1&t={max(0.0, T0-0.4)}", wait_until="load")
    pg.wait_for_timeout(600)
    rows = pg.evaluate(PROBE)
    pg.screenshot(path=str(OUT / "last.png"), scale="css")
    b.close()

if errs:
    print("RUNTIME ERRORS:", errs[:3]); sys.exit(1)
if not rows:
    print(f"t={T0}s no bolt in window, try 40 / 60 / 120")
    sys.exit(2)

print(f"t about {T0}s   {len(rows)} frames sampled")
print("  grow   core_px  halo_px  skipped  r_p50  r_p95")
for r in rows:
    print(f"  {r['grow']:5.2f}  {r['core']:7d}  {r['halo']:8d}  {r['far']:7d}  {r['r50']:6.1f}  {r['r95']:6.1f}")

# 按 grow 分箱比较头尾：外扩应表现为 r_p95 随 grow 上升
lo = [r["r95"] for r in rows if r["grow"] < 0.25 and r["halo"] > 200]
hi = [r["r95"] for r in rows if r["grow"] > 0.55 and r["halo"] > 200]
if lo and hi:
    a = sum(lo)/len(lo); bb = sum(hi)/len(hi)
    print(f"\nr_p95  early(grow<0.25) {a:.1f}px  ->  late(grow>0.55) {bb:.1f}px   ratio {bb/max(a,1e-6):.2f}")
    print("VERDICT: ratio > 1.15 => glow expands outward;  ~1.0 => fades in place;  < 1 => shrinks inward")
else:
    print("\nnot enough clean samples (need halo>200 both early and late)")

