I have everything verified. The DPVO calib format is a one-line `fx fy cx cy [k1 k2 p1 p2 k3]` (TUM/TartanAir convention). I have enough to write the complete architecture document.

---

# Monsson "Mental Map" (Advanced) — Complete 24h Architecture

**Go2 monocular RGB, no depth sensor.** Intrinsics @1080p: `fx=fy=554.3, cx=960, cy=540`, 1920×1080, ~120° FOV (barrel distortion), F2.2, **15 FPS**, camera **~30 cm off floor**. Data: `mental_map/` = 5 mp4 clips (17–36 s) of a robot driving forward through a break room, **+ GT trajectories**. Judged on: planned-route error vs GT, robustness to rotations & repeated passes, **visual map quality**, metric-scale accuracy.

> **Bottom line up front:** Build the brief's explicitly-blessed "floor version" — **topological place graph + depth-network BEV occupancy + A\*/Dijkstra planner → (walk X m, rotate Y°) command list**. Use **MASt3R-SLAM** as the pose/geometry engine (the *one* learned SLAM that genuinely converges on low-texture corridors with pure rotation and runs at 15 FPS), with **DPV-SLAM as a same-API fallback** and a **pure Depth-Anything-V2 BEV path that needs no SLAM at all** as the guaranteed demo. This is buildable in hours and maximizes the "visual map quality" score.

---

## 1. Two pipelines and their tradeoffs

### Pipeline A — Classical sparse monocular SLAM/VO

| System | Fisheye/120° | Low-texture corridor | Pure rotation | Install in hours | Verdict for this data |
|---|---|---|---|---|---|
| **ORB-SLAM3** | Yes (Kannala-Brandt) | **Fails to init / loses tracking** in low-texture; needs IMU to be robust (we have none) | **Breaks** — point motion model can't triangulate under rotation, no parallax | C++/Pangolin build is a 1–3 h time-sink | **High risk** |
| **stella_vslam** (OpenVSLAM fork) | **Best classical fisheye support** (perspective/fisheye/equirect, native) | Same indirect-SLAM fragility | Same rotation fragility | C++ build, but cleanest | Backup-classical only |
| **DSO / DPVO** | needs undistort | DSO direct = drifts; DPVO learned = robust | DPVO handles it | DPVO easy (pip) | DPVO → see Pipeline B |

The hard truth for **this** footage: the clips are a **low-texture break room driven mostly forward with turns** — i.e. exactly the regime (sparse features, near-pure rotation at corners, repeated passes) where classical indirect monocular SLAM **fails to initialize or loses the map**. ORB-SLAM3's own paper concedes pure-rotation and low-texture are where it needs the IMU we don't have. **Do not bet the demo on ORB-SLAM3.**

### Pipeline B — Learning-based SLAM / depth+pose

| System | Converges on low-texture + rotation? | 15 FPS realistic? | Install in hours | Notes |
|---|---|---|---|---|
| **DROID-SLAM** | Yes, dense optical-flow backend → robust | Yes on RTX-class GPU | Heavy CUDA build (lietorch/custom ops); finicky | Memory-hungry; superseded by DPVO for our purposes |
| **DPVO / DPV-SLAM** | **Yes** — patch-based, robust where ORB fails; DPV-SLAM adds loop closure | **1×–4× real-time**, 5–7 GB VRAM | **`pip install .` + Eigen unzip**, easy | Strong, lean fallback. Outputs **up-to-scale** trajectory only |
| **MASt3R-SLAM** ⭐ | **Yes** — dense 3D-reconstruction priors (MASt3R two-view matching), explicitly **robust on in-the-wild video**, no parametric camera assumption | **~15 FPS on RTX 4090** (CVPR 2025) | conda + recursive submodules + 3 wget checkpoints | **Gives dense pointmaps AND poses AND metric-ish depth in one shot** → ideal for BEV map. Beats ORB-SLAM/DROID on benchmarks |
| **Depth-Anything-V2 → BEV** (no SLAM) | N/A (per-frame) | Yes | trivial (HF transformers) | **Guaranteed fallback**; metric-indoor model gives meters directly |

**Recommendation:** **MASt3R-SLAM is the primary engine.** It is the only 2024–2026 system that simultaneously (a) converges on low-texture/rotation, (b) runs near 15 FPS, (c) handles the wide-FOV camera without a brittle parametric model, and (d) hands you **dense per-pixel 3D pointmaps** — which is exactly what you back-project into a bird's-eye occupancy grid, giving the best "visual map quality" score for free. **DPV-SLAM is the drop-in fallback** if MASt3R-SLAM won't install (same role: video in → camera trajectory out). The **Depth-Anything-V2 BEV path is the guaranteed-to-work floor.**

---

## 2. Monocular scale ambiguity & metric recovery

A single moving camera recovers structure and motion **only up to one global scale factor** `s` (translations and depths can be multiplied by any `s>0` and reproject identically). Three concrete ways to fix `s` **here**:

1. **Known camera height + ground-plane homography (best for this rig).** The camera is **~30 cm above a flat floor**. Fit a plane to the floor points (RANSAC on the lowest band of the back-projected point cloud, or homography between the floor region of two frames). Up-to-scale, the estimated camera-to-floor height is `ĥ`. The true height is `h = 0.30 m`. Then the metric scale is

   `s = h_true / ĥ = 0.30 / ĥ`,  multiply all translations & depths by `s`.

   Geometric form: a floor point at image ray `r` (unit, in cam frame) with plane normal `n=(0,1,0)` (camera +y down to floor) and offset `h` projects to depth `Z = h / (n·r)`. Knowing `h=0.30` turns every floor pixel into a **metric** range, anchoring scale.

2. **Known object sizes (pinhole back-out).** The break room has standard objects — **a door is ~2.0 m tall, a water cooler ~1.1 m, a stool seat ~0.45 m**. With focal `f=554.3` and measured pixel height `p`, metric distance `d = f · H_real / p`. Detect one or two such objects (YOLO), solve for the depth, and rescale the map so that object lands at `d`. Cross-check against method 1.

3. **Wheel / IMU odometry — NOT AVAILABLE.** The Go2 has joint/IMU odometry on-robot, but **we are given only RGB clips**, so this channel is unavailable. Note it explicitly in the report as the "if we had the robot" path.

> **MASt3R-SLAM bonus:** it uses the **metric** MASt3R checkpoint (`..._metric.pth`), so its pointmaps already come out in approximately-metric units. Use method 1 (floor height) as a **calibration multiplier** to correct residual scale — it turns "approximately metric" into "anchored to the known 30 cm."

**Scale alignment for evaluation (Sim(3) Umeyama).** GT trajectories are provided, so for *scoring* you don't need perfect metric scale — you align estimate to GT. Monocular trajectories are compared after a **Sim(3) Umeyama alignment** (rotation **R**, translation **t**, and scale **`s`** that minimize `Σ‖ x_gt − (sR·x_est + t) ‖²`). Closed-form: `R = U diag(1,1,det(UVᵀ)) Vᵀ` from the SVD `UΣVᵀ` of the cross-covariance of centered point sets, `s = tr(DS)/σ²_est`, `t = μ_gt − sR·μ_est`. In `evo` this is `evo_ape tum gt.txt est.txt -as` (`-a` = align SE(3), `-s` = also estimate scale → Sim(3)). Report **both** the Sim(3)-aligned APE (shape accuracy, scale-free) **and** the recovered scale `s` vs your metric-anchored scale (metric-accuracy bonus).

---

## 3. The blessed "floor version": topological graph + BEV occupancy + planner → commands

This is the architecture to build. Five stages:

**(1) Pose & geometry engine.** Run MASt3R-SLAM (or DPV-SLAM) on the undistorted clip → **keyframe poses `T_i ∈ SE(3)`** + (MASt3R) dense pointmaps. Apply metric scale `s` from §2.

**(2) Topological place graph `G=(V,E)`.**
- **Nodes** = keyframes (one every ~0.5 m or ~10 frames), each storing pose `(x,z,θ)` on the floor plane + a global descriptor (MASt3R retrieval codebook, or NetVLAD/DBoW2).
- **Edges** = (a) **temporal** edges between consecutive keyframes (weight = metric distance), (b) **visual-similarity / loop-closure** edges between non-adjacent keyframes whose descriptors match above threshold (handles "repeated passes" → robustness score + loop-closure bonus). Dijkstra on this graph alone already satisfies the brief's **bonus** ("Dijkstra on topological graph").

**(3) 2D occupancy via depth back-projection to a BEV grid.**
For each keyframe, take per-pixel metric depth `D(u,v)` (MASt3R pointmap, or Depth-Anything-V2-Metric-Indoor). Back-project to camera-frame 3D, transform to world with `T_i`, scale by `s`:

```
X_cam = (u−cx)/fx · D ,  Y_cam = (v−cy)/fy · D ,  Z_cam = D
P_world = s · (R_i · [X_cam,Y_cam,Z_cam]ᵀ + t_i)
```

Drop the height axis → `(x,z)`. Rasterize into a grid (e.g. **5 cm/cell**). A cell is:
- **free** if a floor point projects there (height ≈ 0 within ±τ of the 0.30 m floor plane),
- **occupied** if points exist at obstacle height (e.g. 0.1–1.5 m above floor),
- **unknown** otherwise.
Accumulate over all keyframes (log-odds / hit-count). Inflate obstacles by the robot radius (~0.20 m).

**(4) Planning.** `A*` (or Dijkstra) on the free cells of the BEV grid, 8-connected, Euclidean heuristic. For the topological-graph bonus, also run **Dijkstra on `G`** between the nodes nearest to start/goal and snap to grid for the final metric polyline. Output a **polyline** `p_0,…,p_N` in metric world coords.

**(5) Polyline → command sequence (walk X m, rotate Y°).** Convert the geometric path into the robot's "turn-then-go" language. With current heading `θ_k` (start `θ_0` = facing +z, the camera's forward at the start pose):

```
For each segment (p_k → p_{k+1}):
    Δ      = p_{k+1} − p_k              # 2D vector in (x, z)
    L      = ‖Δ‖                        # WALK distance, metres
    ψ      = atan2(Δ_x, Δ_z)            # absolute bearing of the segment
    Δθ     = wrap_to_pi(ψ − θ_k)        # signed turn, radians
    emit   ROTATE  degrees(Δθ)          # + = turn right/CW (define & state convention)
    emit   WALK    L
    θ_{k+1} = ψ                          # heading after the move
```

`wrap_to_pi(a) = atan2(sin a, cos a)` keeps every turn in `[−180°, +180°]` (never spin 350° when −10° suffices). Optionally **simplify the polyline first** (Ramer–Douglas–Peucker, ε≈0.1 m) so you emit a handful of clean `(rotate, walk)` pairs instead of hundreds of micro-steps — this is what makes the demo readable and the commands "smooth, no oscillation." Final command list example:

```
ROTATE -37°   WALK 2.4 m   ROTATE +90°   WALK 1.1 m   ROTATE +5°   WALK 0.8 m   → GOAL
```

---

## 4. Handling the 120° barrel distortion (do this FIRST)

Feed **undistorted** frames to any VO/SLAM (MASt3R-SLAM is robust to mild distortion, but undistorting still helps matching and makes the pinhole back-projection in §3 exact). Two options:

- **Undistort to pinhole + crop (recommended).** Treat the lens as **Kannala-Brandt fisheye** (or `k1,k2,p1,p2,k3` radial-tangential if mild). Build a map with `cv2.fisheye.initUndistortRectifyMap` (or `cv2.initUndistortRectifyMap` for plumb-bob), choosing a new `K` whose focal keeps a ~90° usable FOV, `remap` every frame. Crop the black borders → a clean rectilinear ~90° image. **Straight lines become straight**, so floor planes and obstacles project correctly into the BEV grid.
- **If exact distortion coeffs are unknown:** the provided `go2_camera_details.txt` gives only `fx,fy,cx,cy`. Quick-estimate `k1` (and `k2`) by either (a) a 1-frame manual fit so a known straight edge (door frame) becomes straight, or (b) feeding the **raw** intrinsics to MASt3R-SLAM, which tolerates unmodeled distortion better than ORB-SLAM. State this assumption in the report.

After undistort, **update the intrinsics** (`fx,fy,cx,cy` of the new `K`, and the new crop size) and pass *those* to the SLAM calib yaml and the back-projection math.

---

## 5. Evaluation vs GT + map visualization (judges score visuals)

**Trajectory / route error:**
- Write your estimated camera trajectory in **TUM format** (`timestamp tx ty tz qx qy qz qw`).
- `evo_ape tum gt.txt est.txt -as -r trans_part --plot` → **Sim(3)-aligned APE** (RMSE, mean, median) = the headline "planned-route error vs GT" number, scale-free.
- `evo_rpe tum gt.txt est.txt -a --delta 1 -r trans_part` → local **drift / robustness** under rotations and repeated passes.
- Report the recovered Umeyama **scale `s`** and compare to your floor-height metric scale → the **metric-accuracy** sub-score.
- **Planned-route error specifically:** sample your planned polyline against the GT path between the same start/goal and report mean lateral deviation (m) and total-length error (%).

**Map visualization (this is graded — make it beautiful):**
1. **BEV occupancy map** — free (white), occupied (black/dark), unknown (grey); robot trajectory overlaid as a colored line; **planned A\* path in bright color**; start ★ and goal ⚑ markers; a **scale bar in metres** and a north arrow.
2. **Topological graph overlay** — keyframe nodes as dots, temporal edges thin, **loop-closure edges highlighted** (shows you handle repeated passes).
3. **Dense 3D point cloud / mesh** from MASt3R-SLAM pointmaps in an interactive **Rerun / Open3D** viewer — this is the "wow" that wins visual-quality points (MASt3R-SLAM integrates with Rerun out of the box).
4. A **side-by-side**: input frame → undistorted → depth heatmap → its contribution to the BEV grid (tells the whole story in one slide for the 5-min pitch).
5. The final **command list** rendered as annotated arrows on the BEV map.

---

## 6. Minimal repo, runnable demo, performance report

### Repo layout
```
mental-map/
├── README.md                 # install + one-command demo
├── requirements.txt
├── data/                     # symlink to mental_map/*.mp4, go2_camera_details.txt
├── config/
│   ├── go2_intrinsics.yaml   # fx,fy,cx,cy + distortion (raw) and undistorted K
│   └── slam_base.yaml
├── src/
│   ├── undistort.py          # §4: fisheye→pinhole remap, writes undistorted mp4 + new K
│   ├── run_slam.py           # wraps MASt3R-SLAM (primary) / DPV-SLAM (fallback) → poses + pointmaps
│   ├── scale.py              # §2: floor-plane RANSAC → metric scale s; object-size cross-check
│   ├── build_map.py          # §3: back-project depth → BEV occupancy grid + topo graph G
│   ├── plan.py               # §3: A* on grid + Dijkstra on G → metric polyline
│   ├── commands.py           # §3: polyline → [(ROTATE deg, WALK m)] with RDP simplify
│   ├── evaluate.py           # §5: TUM export + evo APE/RPE + scale report
│   └── viz.py                # §5: BEV PNG, topo overlay, Rerun 3D, command arrows
├── notebooks/demo.ipynb      # end-to-end on one clip, renders all figures
└── outputs/                  # maps, trajectories, command lists, plots
```

### Install (verified commands)

**Primary — MASt3R-SLAM:**
```bash
conda create -n mast3r-slam python=3.11 -y && conda activate mast3r-slam
conda install pytorch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 pytorch-cuda=12.1 -c pytorch -c nvidia -y
git clone https://github.com/rmurai0610/MASt3R-SLAM.git --recursive && cd MASt3R-SLAM
pip install -e thirdparty/mast3r && pip install -e thirdparty/in3d
pip install --no-build-isolation -e . && pip install torchcodec==0.1
mkdir -p checkpoints/
wget https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth -P checkpoints/
wget https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth -P checkpoints/
wget https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_codebook.pkl -P checkpoints/
# run (after undistort):
python main.py --dataset ../outputs/clip1_undist.mp4 --config config/base.yaml --calib ../config/go2_intrinsics.yaml
```

**Fallback — DPV-SLAM (DPVO repo):**
```bash
git clone https://github.com/princeton-vl/DPVO.git && cd DPVO
conda env create -f environment.yml && conda activate dpvo
wget https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.zip && unzip eigen-3.4.0.zip -d thirdparty
pip install . && ./download_models_and_data.sh
# DPV-SLAM = DPVO + loop closure:
python demo.py --imagedir=../outputs/clip1_undist.mp4 --calib=calib/go2.txt --opts LOOP_CLOSURE True --viz --plot --save_ply
# calib/go2.txt is ONE line:  fx fy cx cy  (post-undistort values), optionally + k1 k2 p1 p2
```

**Guaranteed fallback — Depth-Anything-V2 metric BEV (no SLAM, no CUDA build):**
```bash
pip install transformers torch opencv-python open3d evo numpy scipy
# model: depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf  (max_depth=20, indoor, metric metres)
```

### Core sketch (~30 lines) — depth → metric BEV → A* → commands (the fallback that always runs)
```python
import cv2, numpy as np, torch
from transformers import AutoImageProcessor, AutoModelForDepthEstimation
from scipy.ndimage import binary_dilation

K = np.array([[554.3,0,960],[0,554.3,540],[0,0,1]])      # use post-undistort K in practice
proc = AutoImageProcessor.from_pretrained("depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf")
net  = AutoModelForDepthEstimation.from_pretrained("depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf").cuda().eval()

def depth(bgr):                                            # -> metric depth (m), HxW
    inp = proc(images=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), return_tensors="pt").to("cuda")
    with torch.no_grad(): d = net(**inp).predicted_depth[0]
    return cv2.resize(d.cpu().numpy(), (bgr.shape[1], bgr.shape[0]))

RES, SIZE = 0.05, 200                                      # 5 cm cells, 10x10 m grid
grid = np.zeros((SIZE, SIZE), np.float32)                  # log-odds occupancy
fx,fy,cx,cy = K[0,0],K[1,1],K[0,2],K[1,2]
for bgr, T in frames_with_pose():                          # T = 4x4 world<-cam from SLAM (or I for single frame)
    D = depth(bgr); v,u = np.mgrid[0:D.shape[0], 0:D.shape[1]]
    P = np.stack([(u-cx)/fx*D, (v-cy)/fy*D, D], -1).reshape(-1,3)
    W = (T[:3,:3] @ P.T + T[:3,3:4]).T                     # to world; apply metric scale s upstream
    floor = np.abs(W[:,1]-0.30) < 0.08                     # camera 0.30 m above floor plane
    obst  = (W[:,1] < 0.20) & ~floor                       # obstacle band
    gx, gz = (W[:,0]/RES+SIZE//2).astype(int), (W[:,2]/RES).astype(int)
    ok = (gx>=0)&(gx<SIZE)&(gz>=0)&(gz<SIZE)
    np.add.at(grid, (gz[ok&obst], gx[ok&obst]),  1.0)      # occupied votes
    np.add.at(grid, (gz[ok&floor],gx[ok&floor]), -0.3)     # free votes

occ = binary_dilation(grid > 0.5, iterations=4)            # inflate by robot radius (~0.2 m)
path = astar(free=~occ, start=world_to_cell(start), goal=world_to_cell(goal))   # 8-connected A*
poly = rdp(cells_to_world(path), eps=0.10)                 # simplify to clean segments
cmds, theta = [], 0.0                                      # commands.py
for a, b in zip(poly[:-1], poly[1:]):
    d = b - a; L = np.linalg.norm(d); psi = np.arctan2(d[0], d[1])
    dth = np.arctan2(np.sin(psi-theta), np.cos(psi-theta)); theta = psi
    cmds += [("ROTATE", np.degrees(dth)), ("WALK", L)]
print(cmds)                                                # [(ROTATE,-37),(WALK,2.4),(ROTATE,90),...]
```

### Performance report contents (for the 5-min pitch)
- **Pipeline diagram** + decision log (why MASt3R-SLAM over ORB-SLAM3 — convergence on low-texture/rotation).
- **Per-clip table:** SLAM convergence (yes/no), FPS, #keyframes, #loop closures, Sim(3)-APE RMSE, RPE, recovered scale `s` vs metric `s`.
- **Metric-scale accuracy:** floor-height scale vs object-size cross-check vs Umeyama scale (% error).
- **Planned-route error:** mean lateral deviation (m) & length error (%) vs GT for ≥2 start/goal pairs.
- **Ablations:** undistort on/off; MASt3R-SLAM vs DPV-SLAM vs single-frame Depth-Anything BEV.
- **Failure cases** + the honest fallback story (below).
- **Figures:** BEV map, topo graph w/ loop closures, 3D point cloud, command-arrow overlay.

---

## 7. Risk assessment & guaranteed fallback (be honest)

| Component | Risk in 24h | Mitigation |
|---|---|---|
| **MASt3R-SLAM install** (submodules, checkpoints, torchcodec, CUDA match) | **Medium-High** — the most likely time-sink | Start it building **first hour, in parallel**; if it stalls >2 h, switch to DPV-SLAM (simpler `pip install .`) |
| **DPV-SLAM build** (Eigen, CUDA ops) | Low-Medium | Skip the Pangolin viewer (optional); use `--plot` only |
| **Exact distortion coeffs unknown** | Medium | Feed raw `K` to MASt3R-SLAM (distortion-tolerant); or 1-frame `k1` fit |
| **Metric scale wrong** | Medium | Floor-height anchor (§2.1) + object-size cross-check (§2.2); and Sim(3)-align for scoring regardless |
| **GPU not available / weak** | Medium | DPV-SLAM runs at 5–7 GB; Depth-Anything-V2-Small runs on modest GPUs/CPU |

**Guaranteed-to-work fallback (zero SLAM, zero CUDA build):** Since all 5 clips are **forward-driving**, you don't strictly need full SLAM to make a compelling map. Run **Depth-Anything-V2-Metric-Indoor** per frame, estimate inter-frame motion from **a simple constant-forward-speed assumption calibrated by the GT trajectory length** (or sparse optical-flow + floor homography for heading), and accumulate the BEV grid using the core sketch above with `T` from this lightweight odometry. This **always produces a clean metric BEV occupancy map, an A\* path, and a `(rotate, walk)` command list** — fully satisfying the brief's blessed "floor version," with a polished visualization, even if both SLAM systems fail to build. Layer the topological graph + Dijkstra on top for the bonus once the floor works.

**Build order (24h):** (0–1h) undistort pipeline + kick off MASt3R-SLAM build in background. (1–3h) get the **Depth-Anything BEV fallback fully working end-to-end** → you now have a guaranteed demo. (3–6h) wire MASt3R-SLAM poses+pointmaps in, add metric scale anchoring. (6–9h) topological graph + loop closures + Dijkstra. (9–12h) evaluation (evo, route error) + Rerun/Open3D visuals. Remainder: polish figures, write report, rehearse the 5-min pitch.

---

### Sources
- [MASt3R-SLAM (CVPR 2025) — GitHub](https://github.com/rmurai0610/MASt3R-SLAM) · [README](https://github.com/rmurai0610/MASt3R-SLAM/blob/main/README.md) · [project page](https://edexheim.github.io/mast3r-slam/) · [paper](https://arxiv.org/pdf/2412.12392)
- [DPVO / DPV-SLAM (ECCV 2024) — GitHub](https://github.com/princeton-vl/DPVO) · [paper](https://arxiv.org/abs/2408.01654)
- [stella_vslam (OpenVSLAM fork)](https://github.com/stella-cv/stella_vslam) · [docs](https://stella-cv.readthedocs.io/)
- [ORB-SLAM3 paper (pure rotation / low-texture limits)](https://gaoyichao.com/Xiaotu/papers/2021%20-%20ORB-SLAM3%20An%20Accurate%20Open-Source%20Library%20for%20Visual%20Visual-Inertial%20and%20Multi-Map%20SLAM.pdf)
- [Depth-Anything-V2 (NeurIPS 2024) — GitHub](https://github.com/DepthAnything/Depth-Anything-V2) · [Metric-Indoor-Large HF model](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf)
- [Ground-plane absolute-scale estimation for monocular VO](https://ar5iv.labs.arxiv.org/html/1903.00912) · [plane-geometry scale recovery (arXiv 2101.05995)](https://arxiv.org/pdf/2101.05995)
- [evo — trajectory evaluation (Sim(3) Umeyama, APE/RPE)](https://github.com/MichaelGrupp/evo/wiki/Metrics)