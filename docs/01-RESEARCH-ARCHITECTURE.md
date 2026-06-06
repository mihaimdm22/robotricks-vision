# Monsson Hack-a-ton 2026 — Research & Architecture (Executive Synthesis)

> Verified SOTA + buildable architectures for the three Monsson CV challenges.
> Produced by a 5-agent research pass, each section adversarially fact-checked
> (model names, formulas, install commands, 24h feasibility). Zero critical/high
> issues found across all sections. Full per-topic write-ups in `docs/research/`.

**Companion docs:** `00-AUDIT.md` (your materials, hardware, rules, data) · this file (what to build) · `docs/research/*.md` (full detail per topic).

---

## TL;DR — the recommendation

1. **Compete in ONE Monsson challenge** (each has its own jury + €1,000). **Pick: How Far?** — cleanest metric (MAE<15%), best-scoped, you have sample data, and your HC-SR04 gives a free ground-truth for a killer live demo. **Mental Map** is the high-ceiling "wow" stretch if How Far lands early. **Cat Tracker** is the most demo-friendly but you have no local cat clips.
2. **Do not train from scratch.** Use pretrained perception + classical geometry. The only "fitting" is a 1-line per-class scale calibration (`np.polyfit`, not a training run). The briefs say no training is required; with ~24h left it's a time trap. (Detail: `docs/research/karpathy-and-data-pipeline.md`.)
3. **Honor Karpathy as discipline, not as a trainer:** a `CLAUDE.md` engineering-rules layer + a *frozen-metric keep/reject loop* (`karpathy/autoresearch` is exactly that pattern). Optional, hard-time-boxed fine-tune only if the baseline is green early.
4. **Optimize for the Go2 hidden test set, not your Arduino/Tapo robot.** The robot is a 90-second wow-demo prop, not the graded deliverable. Timebox hardware to ≤3h, late, after the number is locked.

---

## Challenge decision table (full reasoning in `docs/research/hardware-and-strategy.md` §5)

| Criterion | **How Far? ✅ PICK** | Cat Tracker | Mental Map |
|---|---|---|---|
| Difficulty | 🟡 Intermediate | 🟡 Intermediate | 🔴 Advanced |
| Effort to a working number (24h) | **Low–Med** | Med | High |
| Risk of no clean metric | **Low** | Med (tracking jitter/reID) | High (VO scale drift) |
| Data on hand | 20 Go2 stills (unlabeled) | **None locally** | 5 Go2 clips (+GT exists) |
| Live-demo wow | **High** (ultrasonic GT match) | High (robot chases cat) | Med (map on screen) |
| P(clean scored result) | **High** | Med | Low–Med |
| "2 approaches" satisfied trivially? | **Yes** (geometry vs depth) | Yes (YOLO vs RT-DETR) | Partly |

---

## How Far? — architecture in one screen  → `docs/research/how-far.md`

**Method:** two independent estimates, fused, calibrated, with uncertainty.
- **Approach A — pinhole geometry:** `Z = fy · H_real / h_pixels`. Per-class real-size priors (person 1.70 m, door 2.04 m, chair/stool seat 0.45 m, ball ⌀0.22 m, pot 0.30 m). Use `fy`; weight by how centered the box is (distortion grows with radius²).
- **Approach B — learned metric depth:** **UniDepthV2** (`lpiccinelli/unidepth-v2-vitl14`) is the pick — you feed it your real `K` → true-metric depth + a per-pixel confidence map (free uncertainty). Alternatives: Metric3D v2 (uses `fx`), Depth Anything V2 Metric-Indoor. (Detector = YOLO11 → the "ViT vs YOLO = 2 approaches" box is ticked since the depth net is a ViT.)
- **Fusion:** per-class scale calibration `α_c` + confidence-weighted **median** of {geometry, metric-net, anchored-relative}. Median kills the single bad estimate (clipped door, edge object). This is what clears 15%.
- **Uncertainty (scored bonus):** (a) inter-estimator spread `σ≈0.5·|Z_geo−Z_uni|`, plus (b) **split-conformal interval** from residual quantiles (`CI_90 = [Z(1−q̂), Z(1+q̂)]`) — verified jury-defensible.
- **No-label self-calibration on your 20 stills:** fit `α_c` by cross-estimator agreement, and the **floor-plane trick** — fit the ground plane, force it to sit at the known ~0.30 m camera height → an *absolute* scale anchor with zero labels (verification flagged this as a genuinely strong move).
- **Distance *between* objects (deck framing):** back-project both box centers to 3D (`X=(u−cx)Z/fx, Y=(v−cy)Z/fy, Z`), Euclidean distance. Same pipeline gives camera→object (bonus).
- **Distortion:** no coeffs provided → either center-crop-and-trust, or one-pass FOV/division-model undistort (closed form from the known 120°). State the assumption in the pitch.

## Mental Map — architecture in one screen  → `docs/research/mental-map.md`

**Build the brief's blessed "floor version":** topological place graph + depth→BEV occupancy grid + A*/Dijkstra → `(walk X m, rotate Y°)` command list.
- **Pose/geometry engine:** **MASt3R-SLAM** (CVPR 2025) — the one learned SLAM that converges on low-texture corridors + pure rotation at ~15 FPS and hands you dense pointmaps. **DPV-SLAM** = same-role fallback. **⚠️ Do NOT bet on ORB-SLAM3** (fails on low-texture/rotation without IMU; C++ build is a time sink).
- **Guaranteed fallback (no SLAM, no CUDA build):** per-frame Depth-Anything-V2-Metric → BEV grid with simple forward-motion odometry → always produces a clean map + path + command list.
- **Metric scale:** floor-plane + known 0.30 m camera height (`s = 0.30/ĥ`); object-size cross-check. For *scoring*, Sim(3) Umeyama-align to the provided GT trajectory (`evo_ape -as`).
- **Polyline → commands:** RDP-simplify the path, then per segment `ROTATE wrap_to_pi(ψ−θ)`, `WALK ‖Δ‖`.
- **Risk:** Medium-High (install/convergence). Has a real fallback, but it's the Advanced challenge for a reason.

## Cat Tracker — architecture in one screen  → `docs/research/cat-tracker.md`

**Cat = COCO class 15 → zero training.** Spend time on the tracker + control loop (where the points are).
- **Approach A:** YOLO11s + ByteTrack (fast, low jitter). **Approach B:** RT-DETR-l + BoT-SORT `with_reid:True` (transformer + appearance ReID through full occlusion). Same control loop → clean comparison. (YOLO26 NMS-free / RF-DETR as extra columns.)
- **Control:** bbox → normalized errors → P/PD → **anti-oscillation stack** (deadband → EMA → slew-limit → clamp → target-lock hysteresis → coast-on-occlusion). Judges explicitly score smoothness.
- **Safe distance:** bbox-area setpoint or pinhole range (reuse the How Far trick); HC-SR04 enforces it on the real robot.
- **Latency:** YOLO11s+tracker ≈ 60–80 FPS on a consumer GPU — huge headroom over the 15 FPS bar.
- **No local cat data** → demo on a public clip (`yt-dlp`) or webcam; eval harness measures FPS, ID-switches, jerk/oscillation, synthetic-occlusion re-acquire.

---

## The repo skeleton (shared across challenges)  → `docs/research/karpathy-and-data-pipeline.md`

Config-driven, undistort-first, one command per stage:

```
prepare  →  infer  →  evaluate  →  report
```

- `CLAUDE.md` = Karpathy engineering rules (don't assume / minimum code / goal-driven / one frozen metric / surgical changes).
- `configs/camera/go2_1080p.yaml` holds the intrinsics; geometry code never hard-codes numbers.
- `--model` flag = the "2 approaches" comparison; `make report` auto-generates the performance-report deliverable.
- `notebooks/demo.ipynb` runs the stages on the provided inference set = the graded demo.

**Optional public datasets** (enrichment/calibration only — the prize is the hidden Go2 set): COCO cat, Roboflow Universe cat detection (low-angle fine-tune), Open Images V7 Cat; NYU Depth V2 / KITTI depth (How Far sanity); TUM RGB-D / KITTI Odometry (Mental Map VO sanity).

---

## Verification notes (what the fact-check confirmed or corrected)

- ✅ All model names, HF/pip handles, and install commands verified to exist (2024–2026).
- ✅ Pinhole math, anchoring LSQ, Sim(3) Umeyama, split-conformal CI, polyline→command math — all confirmed correct.
- ⚠️ **No distortion coefficients** are provided (only fx,fy,cx,cy) → committed approach = center-crop or FOV/division-model undistort; cannot run true `cv2.undistort`. State as an assumption.
- ⚠️ **Verify GPU in hour 0.** UniDepthV2 (How Far) and MASt3R-SLAM (Mental Map) are ViT-Large and want a real GPU; both have lighter fallbacks (Depth-Anything-V2-Small, DPV-SLAM).
- ⚠️ **No local cat clips** — Cat Tracker can't be demoed on provided data without a downloaded/webcam clip or the Tapo.
- ⚠️ MASt3R-SLAM's "15 FPS" is an RTX-4090 number; budget the install as the main Mental Map risk and start it building first.

→ Next: pick the challenge and I scaffold the runnable repo. See the decision gate.
