I now have everything verified. Writing the final architecture document.

---

# Monsson "How Far?" — Complete CV Architecture (buildable in hours)

**Robot:** Unitree Go2 Edu. Monocular front RGB. **Intrinsics @1080p:** `fx=fy=554.3, cx=960, cy=540`, `1920×1080`, **FOV 120° (strong barrel distortion)**, F2.2, 15 FPS, mounted **~30 cm off the floor** (dog's-eye view). Indoor industrial/office.
**Task (website):** crop + class label → **distance in meters**, **MAE < 15%** on hidden set, + **bonus confidence interval**.
**Task (deck):** distance **between** two objects in a frame; bonus = camera→reference distance. We build **both** and pick at demo time.

---

## 0. The intrinsics are internally inconsistent — and that's the single most important thing to notice

A pinhole with `fx=554.3` at width `W=1920` implies horizontal FOV `2·atan(960/554.3) = 120.1°`. So **the focal already encodes the 120° field**. This means two things, and getting them right is most of the score:

1. The **vendor `fx=554.3` is a *rectilinear-equivalent* focal** — it is the focal you would use **only on an already-undistorted (rectified) image**. On the **raw** barrel-distorted frame, a straight pinhole projection does **not** hold near the edges, so any geometry computed on raw pixel heights of off-center objects is biased.
2. At 120° the standard Brown–Conrady polynomial is at the edge of where it breaks down (it is reasonable up to ~120°, fisheye module is for >160°). Confirmed by OpenCV community guidance.

**No distortion coefficients are provided.** Two defensible options, in priority order:

- **Option 1 (recommended, fast): ignore distortion but only trust *centered* objects.** Crop the object, use its **vertical** pixel extent measured **near the optical center** where distortion is smallest. Radial distortion grows with `r²` from center, so a chair imaged in the central third of the frame has <2–3% height error. This is the cheapest way to keep geometry honest. Our pipeline therefore **weights geometry by how centered the box is**.
- **Option 2 (if time): synthesize a distortion model from the known FOV** using the **FOV (division) model** `r_d = (1/ω)·atan(2·r_u·tan(ω/2))` with `ω = 120° = 2.094 rad`, build an OpenCV-style map and call `cv2.remap`. This is a single closed-form pass, no calibration board needed, and removes the edge bias. Use it to undistort the **full frame once**, then do geometry on the rectified image with `fx=554.3`. (If you undistort, re-estimate `fx` from the new rectified FOV; in practice keeping `554.3` is close enough for MAE<15%.)

```python
import numpy as np, cv2
W, H, fx, fy, cx, cy = 1920, 1080, 554.3, 554.3, 960.0, 540.0
omega = np.deg2rad(120.0)              # FOV/division model angular param
K = np.array([[fx,0,cx],[0,fy,cy],[0,0,1]], np.float32)
xs, ys = np.meshgrid(np.arange(W), np.arange(H))
x = (xs - cx)/fx; y = (ys - cy)/fy; ru = np.sqrt(x*x+y*y) + 1e-9
rd = np.arctan(2*ru*np.tan(omega/2))/omega      # FOV model forward
scale = rd/ru
map_x = (x*scale*fx + cx).astype(np.float32)
map_y = (y*scale*fy + cy).astype(np.float32)
undist = cv2.remap(raw_bgr, map_x, map_y, cv2.INTER_LINEAR)  # one-pass rectify
```

> **Low-mount caveat (≈30 cm):** the camera looks slightly up; floor objects appear in the lower frame and tall objects (doors, people) are foreshortened/clipped at top. Always measure the object's **full real-world vertical segment that is actually visible in the crop**, and prefer **width** as a cross-check for objects whose top is cut off (very common for doors and standing people at close range).

---

## 1. Approach A — Geometry from size (pinhole prior)

### Derivation
Pinhole projection of a vertical segment of real height `H_real` (meters) at depth `Z` (meters) onto the image: the segment subtends `h_pixels`. From similar triangles,

```
h_pixels / fy  =  H_real / Z      ⇒      Z = fy · H_real / h_pixels
```

`fy` (not `fx`) because object height is vertical. `cx, cy` **don't enter the height-ratio formula** — they only matter when you **back-project the box center to a 3D ray** (Section 6) and when judging how off-center (and thus distortion-biased) the object is. Edge objects: error rises with radial distance, hence the centering weight.

### Object-size prior table (meters)
Use the **mode/typical adult-industrial value**, with a spread for the uncertainty model. Dimensions verified against architectural/anthropometric references.

| Class | Cue used | Typical `H_real` (m) | Range (m) | Source / note |
|---|---|---|---|---|
| **person** (standing) | full height | **1.70** | 1.55–1.90 | Global adult mean ♂1.71 / ♀1.59 (Our World in Data) |
| person (head→hip, if legs cut) | torso | 0.85 | 0.75–0.95 | anthropometric |
| **door** (interior) | leaf height | **2.04** (80 in) | 2.00–2.10 | "6/8" standard door = 80 in (Bob Vila / door specs) |
| **chair / office stool** | seat height | **0.45** | 0.42–0.50 | standard seat 0.44 m (firstinarchitecture) |
| chair (full, with back) | total height | 0.90 | 0.80–1.00 | office chair typical |
| **pot** (plant/cooking) | rim height | 0.30 | 0.15–0.50 | high variance → low geometry weight |
| **ball** | **diameter** | 0.22 | 0.07–0.25 | football ⌀0.22, basketball ⌀0.24; use width not height |

**Per-class cue rule:** balls → use **width/diameter** (rotationally symmetric, no clipping). Doors/people → height but **fall back to width** when the top is clipped (door leaf width ≈0.81 m / 32 in; shoulder width ≈0.45 m). Pots have huge variance → geometry is weak, lean on the depth net.

### Where the box comes from
Website task gives the **crop + class** → `h_pixels` is just the crop height (minus a small letterbox guard). Deck task gives a **full frame** → run a detector to get boxes. Use **YOLOv8/YOLO11** (`pip install ultralytics`) as approach #1 detector — this also satisfies the deck's "minimum 2 approaches (YOLO, ViT, CNN)" requirement since the depth net is a ViT.

---

## 2. Approach B — Learned monocular **metric** depth

Critical distinction (this is where teams lose points): **relative vs metric.**

| Model | pip / HF handle | Output | Uses intrinsics? | TRUE metric? | Hackathon verdict |
|---|---|---|---|---|---|
| **Depth Anything V2 (relative)** | `transformers`; `depth-anything/Depth-Anything-V2-Large-hf` | relative (affine-invariant) | no | ❌ relative only | great edges, **must be anchored** |
| **Depth Anything V2 Metric** | `depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf` (`max_depth=20`) | metric depth | no (baked-in dataset scale) | ⚠️ metric but scale tuned to Hypersim/indoor, **not your fx** | **primary depth net**, indoor variant |
| **Metric3D v2** | `YvanYin/Metric3D` (torch.hub) / `zachL1/Metric3D` | metric depth + normals | **yes (canonical-camera rescale)** | ✅ true metric **via your `fx`** | **best for using the given intrinsics** |
| **UniDepth / UniDepthV2** | `lpiccinelli/unidepth-v2-vitl14` (`UniDepthV2.from_pretrained`) | metric depth + K + confidence | **yes (optional K input)** | ✅ true metric, can ingest your K | **best single model**; gives **confidence map** for free |
| **Apple Depth Pro** | `apple/DepthPro-hf` | metric depth + focal | estimates focal itself | ✅ metric, sharp | strong, ignores given K (may fight your fx) |
| **ZoeDepth** | `Intel/zoedepth-nyu-kitti` | metric | no | ⚠️ older (2023) | fallback only |
| **MiDaS** | `Intel/dpt-large` | relative | no | ❌ relative | legacy baseline only |

**Recommendation:** primary = **UniDepthV2** (feed it your real `K` → metric depth + per-pixel confidence in one call); secondary = **Metric3D v2** (uses `fx` via canonical rescale) **or** Depth Anything V2 Metric-Indoor. Keep **Depth Anything V2 relative** as a high-detail backbone you **anchor** with the size prior.

### Anchoring relative → metric with the size prior
For a relative map `D_rel`, recover scale `s` and shift `t` (`Z = s·D_rel + t`) from objects of known size. For each detected object you have an **independent geometric depth** `Z_geo = fy·H_real/h_pixels` and the relative depth `d_i` at its box. Solve least-squares `Z_geo,i ≈ s·d_i + t` over all objects in the frame (≥2 objects → closed form; 1 object → fix `t=0`, `s = Z_geo/d`). Now the entire relative map is metric and you can read depth anywhere. **This single trick is what lets a relative model hit MAE<15%.**

```python
# anchor a relative depth map to metric using known-size objects
import numpy as np
d  = np.array([D_rel[cy_i, cx_i] for (cx_i,cy_i) in centers])   # relative at box centers
zg = np.array([fy*H_REAL[c]/h_px for (c,h_px) in zip(classes,heights)])  # geometry
A  = np.vstack([d, np.ones_like(d)]).T
s, t = np.linalg.lstsq(A, zg, rcond=None)[0]      # metric = s*D_rel + t
Z_metric_map = s*D_rel + t
```

### UniDepthV2 core call (verified usage)
```python
import torch
from unidepth.models import UniDepthV2
model = UniDepthV2.from_pretrained("lpiccinelli/unidepth-v2-vitl14").to("cuda").eval()
rgb = torch.from_numpy(img_rgb).permute(2,0,1)                 # 3,H,W uint8
K   = torch.tensor([[554.3,0,960.],[0,554.3,540.],[0,0,1.]])  # OUR intrinsics
pred = model.infer(rgb, K)            # pass K → true metric
depth = pred["depth"].squeeze().cpu().numpy()                 # meters, H×W
conf  = pred.get("confidence")                                # per-pixel confidence (bonus)
```

---

## 3. Fusion to maximize MAE < 15%

Per object, you have up to three independent metric estimates: `Z_geo` (geometry), `Z_uni` (UniDepth metric), `Z_anchor` (anchored relative). Combine as a **per-class-calibrated, confidence-weighted median**:

1. **Per-class scale calibration** (the biggest lever): on the 20 unlabeled images + any measured samples, fit a single multiplicative correction `α_c` per class so geometry and depth net agree (Section 5). Apply `Z_geo ← α_c·Z_geo`.
2. **Confidence weights**:
   - geometry weight `w_geo = centering(box) · cue_reliability(class)` — high for centered chairs/people/doors, low for pots, low for edge boxes.
   - depth-net weight `w_uni = mean(conf)` over the box (UniDepth gives this directly).
3. **Robust combine:** `Z = weighted_median([Z_geo, Z_uni, Z_anchor], [w_geo, w_uni, w_anchor])`. Median (not mean) kills the single bad estimate (e.g. a clipped door inflating `Z_geo`).

```python
def fuse(Z_geo, Z_uni, Z_anchor, w_geo, w_uni, w_anchor):
    import numpy as np
    z = np.array([Z_geo, Z_uni, Z_anchor]); w = np.array([w_geo, w_uni, w_anchor])
    ok = np.isfinite(z) & (w > 0); z, w = z[ok], w[ok]
    order = np.argsort(z); z, w = z[order], w[order]
    c = np.cumsum(w); return float(z[np.searchsorted(c, 0.5*c[-1])])   # weighted median
```

Why this clears 15%: geometry alone is unbiased for **centered, known-size** objects (chairs, people) → typically 5–10% MAE; the metric net carries pots/edges/clipped cases; the median prevents either failure mode from dominating. Per-class `α_c` removes the systematic offset that otherwise eats the whole budget.

---

## 4. Uncertainty / confidence interval (scored bonus)

Two stacked methods, both cheap:

**(a) Inter-estimator spread (instant, always available).** The disagreement between the independent estimates is a direct, honest uncertainty. Report `σ ≈ 0.5·|Z_geo − Z_uni|` (or the IQR of the three). Wide spread on pots/edges, tight on centered chairs — exactly the right behavior.

**(b) Conformal residuals (rigorous, for the report).** On any images where you can get/measure GT (a handful you measure live, or the deck's stated measured-distance set), compute calibration residuals `r_i = |Z_pred,i − Z_gt,i| / Z_gt,i`. The **90% quantile `q̂`** of those residuals gives a **split-conformal interval** with formal coverage:
```
CI_90 = [ Z·(1 − q̂),  Z·(1 + q̂) ]
```
This is the textbook split-conformal / CQR construction and is **methodologically defensible to a jury**. Combine: final interval = max of (a) and (b) half-widths. Report both the interval **and** empirical coverage on held-out calibration points ("90% interval covered 9/10").

---

## 5. Using the 20 unlabeled `how_far/` images (no GT)

No labels, but they are **gold for self-calibration and sanity checks**:

1. **Cross-estimator agreement = self-supervision.** For each image, run geometry **and** the metric net. Fit the **per-class scale `α_c`** that minimizes disagreement `|α_c·Z_geo − Z_uni|` across all 20 images. This calibrates geometry to the depth net's metric scale **without any labels** (assumes the net is roughly right on average — true for UniDepth/Metric3D indoors).
2. **Floor-plane geometry check (free GT-ish signal).** Camera is ~30 cm up looking roughly forward. Fit the **ground plane** in the metric point cloud (`pred["points"]` from UniDepth, or back-project the depth map). The plane's height should be ≈0.30 m and roughly horizontal — if not, your scale is off; rescale so floor sits at 0.30 m. This is an **absolute** scale anchor that needs no labels.
3. **Monotonicity / OOD sanity:** verify that an object that is larger in pixels returns smaller depth; flag extreme/OOD distances (object filling frame → near clamp; tiny object → far clamp) for the "behavior at extreme distances" rubric item.
4. **Qualitative report panels:** depth map + back-projected ground plane + per-object depth labels overlaid on all 20 → this is most of your performance-report figures.

### Deck framing: distance **between** two objects
Back-project each box center to a **3D point**, then Euclidean distance:
```python
def backproject(u, v, Z, fx, fy, cx, cy):     # pixel + depth -> 3D camera coords
    return np.array([(u-cx)*Z/fx, (v-cy)*Z/fy, Z])
P1 = backproject(u1, v1, Z1, fx, fy, cx, cy)   # Z1 from fused estimate
P2 = backproject(u2, v2, Z2, fx, fy, cx, cy)
dist_between = float(np.linalg.norm(P1 - P2))  # meters
```
`cx, cy` matter **here** (lateral offset), unlike the height formula. This same back-projection produces the camera→object distance (bonus) as simply `Z` of the chosen reference. **Undistort first** (Section 0) so the rays are correct for off-center boxes.

---

## 6. Minimal repo layout

```
how_far/
  README.md                 # run instructions, results table, design decisions
  requirements.txt
  go2_camera_details.txt     # given intrinsics
  src/
    intrinsics.py            # K, FOV-model undistortion map (Section 0)
    geometry.py              # Z = fy*H/h ; backproject ; SIZE_PRIOR table
    depth_net.py             # UniDepthV2 + Metric3D + DAv2-metric wrappers
    detect.py                # YOLO11 boxes (deck/full-frame path)
    anchor.py                # relative->metric LSQ (Section 2)
    fuse.py                  # per-class alpha calib + weighted median (Section 3)
    uncertainty.py           # spread + split-conformal CI (Section 4)
    selfcalib.py             # 20-image self-calibration + floor-plane check (Section 5)
  demo.py                    # runnable end-to-end
  report/                    # figures + performance_report.md
  data/how_far/  data/mental_map/
```

`requirements.txt`:
```
torch torchvision
transformers>=4.45.0          # Depth Anything V2 / DepthPro pipelines
ultralytics                   # YOLO11 detector (approach #1)
opencv-python numpy scipy
# UniDepth: git clone https://github.com/lpiccinelli-eth/UniDepth && pip install -e .
# Metric3D: torch.hub.load('yvanyin/metric3d', 'metric3d_vit_large', pretrain=True)
```

### `demo.py` outline
```python
# 1. load image (crop+class for website task, or full frame for deck task)
# 2. undist = remap(raw)                              # FOV-model rectify (Section 0)
# 3. boxes  = yolo(undist)  OR  use given crop+label
# 4. depth, conf, pts = unidepth.infer(undist, K)     # metric net + confidence
# 5. for each object:
#       h_px   = box height (or width for ball/clipped)
#       Z_geo  = alpha[cls]*fy*SIZE_PRIOR[cls]/h_px
#       Z_uni  = median(depth in box)
#       Z_anch = anchored relative depth (if DAv2-relative used)
#       Z      = fuse(Z_geo, Z_uni, Z_anch, w_geo, w_uni, w_anch)
#       lo,hi  = conformal_interval(Z, q_hat); sigma = 0.5*abs(Z_geo - Z_uni)
# 6. floor-plane check -> rescale so ground ≈ 0.30 m  (Section 5)
# 7. (deck) dist = ||backproject(c1,Z1) - backproject(c2,Z2)||
# 8. overlay Z ± CI on image; dump per-object CSV + figures
```

---

## 7. Performance report contents (for the 5-min pitch)

1. **Two approaches compared** (rubric requirement): geometry-from-size vs metric depth net — per-class MAE table, where each wins (geometry on centered chairs/people; net on pots/edges/clipped).
2. **Fusion ablation:** geometry-only vs net-only vs fused weighted-median MAE → show fusion clears 15%.
3. **Uncertainty:** conformal interval width per class + **empirical coverage** ("90% interval, 9/10 covered"); spread-vs-error scatter.
4. **Self-calibration evidence:** per-class `α_c`, floor-plane height recovered ≈0.30 m on the 20 images (validates scale with no labels).
5. **OOD behavior:** near/far clamp handling; distortion-edge degradation and how centering-weight mitigates it.
6. **Latency:** ~per-frame time (UniDepth V2 is ~30% faster than V1; YOLO11 + one depth pass is real-time-ish on a consumer GPU).
7. **Decisions/tradeoffs:** why UniDepth primary (ingests our K, gives confidence), why median fusion, the FOV-model undistortion choice given missing dist-coeffs.

**Build order (hours):** (1) geometry + size table + crop path → first numbers in <1 h. (2) Add UniDepthV2 with our K → metric net. (3) Per-class `α_c` + weighted-median fusion. (4) Conformal CI + floor-plane check + overlays for the deck. Everything above is closed-form or a single pretrained forward pass — **no training required** (drop the from-scratch Karpathy plan; there's no labeled data and no time).

---

### Sources
- [Depth Anything V2 (GitHub)](https://github.com/DepthAnything/Depth-Anything-V2) · [Metric-Indoor-Large-hf](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf) (`max_depth=20`) · [transformers DAv2 doc](https://huggingface.co/docs/transformers/main/en/model_doc/depth_anything_v2)
- [UniDepth (GitHub)](https://github.com/lpiccinelli-eth/UniDepth) · [unidepth-v2-vitl14 (HF)](https://huggingface.co/lpiccinelli/unidepth-v2-vitl14) · [UniDepthV2 paper (arXiv 2502.20110)](https://arxiv.org/abs/2502.20110)
- [Metric3D v2 (GitHub)](https://github.com/YvanYin/Metric3D) · [zachL1/Metric3D (HF)](https://huggingface.co/zachL1/Metric3D) · [Metric3D v2 paper](https://arxiv.org/html/2404.15506v2) (canonical-camera `scale = fx/1000` rescale)
- [Apple Depth Pro (GitHub)](https://github.com/apple/ml-depth-pro) · [apple/DepthPro-hf (HF)](https://huggingface.co/apple/DepthPro-hf)
- [OpenCV fisheye module](https://docs.opencv.org/3.4/db/d58/group__calib3d__fisheye.html) · [wide-angle undistortion discussion](https://forum.opencv.org/t/wide-angle-or-fisheye-lens-the-undistorted-result-and-how-to-fix-the-perspective-distortion/5440)
- Size priors: [door = 80 in standard (Bob Vila)](https://www.bobvila.com/articles/standard-size-for-doors/) · [seat height 0.44 m / sitting dims (firstinarchitecture)](https://www.firstinarchitecture.co.uk/average-heights-dimensions-of-person-sitting/) · [human height mean ♂1.71/♀1.59 (Our World in Data)](https://ourworldindata.org/human-height)
- Uncertainty: [Conformalized Quantile Regression](https://valeman.medium.com/conformalized-quantile-regression-smarter-uncertainty-prediction-for-data-scientists-6389bea7a7c4) · [Conformal prediction lecture notes (Berkeley, 2024)](https://www.stat.berkeley.edu/~ryantibs/statlearn-s24/lectures/conformal.pdf)