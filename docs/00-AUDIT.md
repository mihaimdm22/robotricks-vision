# Monsson Hack-a-ton 2026 — Full Audit

> Audit of all provided materials, hardware, data, and official challenge rules.
> Compiled 2026-06-06 (final day of the June 5–7 hackathon). Everything below was
> verified firsthand from the source files, the photo, the provided inference data,
> and the official challenge pages + deck.

## 1. The event

- **Monsson "hack a ton 2026"**, hosted by Ambasada.pro. ThePlace, Mamaia. **June 5–7, 2026, 48 hours.** Today is **June 6 → final ~24h.**
- Format: AI-agents hackathon with real company problems, cash prizes, "first client" framing.
- Sponsor: **Monsson SRL** (energy company, Constanța/Dobrogea region). Robotics platform: **Unitree Go2 Edu** quadruped.
- Source deck: `https://hackaton.ambasada.pro/monsson-teme.pdf` (6 slides, Romanian).

## 2. The three Monsson CV challenges

**Each challenge has its own jury and its own €1,000 prize. A team officially competes in exactly ONE.** (There are also non-CV "agent" tracks: Busywork Killer, Watchful, Contradiction Catcher, Warm Leads, etc. — out of scope here.)

| # | Challenge | Difficulty | Core task | Scored metric |
|---|-----------|-----------|-----------|---------------|
| 1 | **Cat Tracker** | 🟡 Intermediate | monocular video → detect + track cats (keep ID through occlusion) → control vector `(dx, dy, rotation)` ≥15 FPS → follow at safe distance | hidden-set accuracy, occlusion robustness, latency, command smoothness |
| 2 | **How Far?** | 🟡 Intermediate | crop + class → distance in meters (deck: also distance *between* objects) | **MAE < 15%** on hidden set; OOD behavior; uncertainty quality; rigor |
| 3 | **Mental Map** | 🔴 Advanced | single RGB stream (no LiDAR/depth) → 2D/2.5D occupancy map or topological graph → plan A→B → `(walk X m, rotate Y°)` | planned-route error vs GT trajectory; rotation/repeat robustness; map visual quality; metric-scale accuracy |

### Per-challenge specifics (verbatim from briefs + deck)

**Cat Tracker**
- Pipeline: Perceive → Track → Estimate (direction & relative speed) → Act (control vector).
- Provided: ~15 clips (30–60s), Go2 camera, varied lighting/angles + partial occlusion; **hidden test set** for scoring.
- Suggested: pretrained detector (YOLO; "cat" is a standard class, **no training required**) + off-the-shelf tracker (ByteTrack/DeepSORT) + simple proportional control with smoothing.
- Deck requirement: **minimum 2 approaches compared** (e.g. YOLO, DETR). BONUS: inter-cat distance (multi-object), reID after full occlusion, predictive following.

**How Far?**
- Website: input = a **crop + class label**; output = meters from camera to object; **MAE < 15%**; bonus = confidence interval. Classes: chairs, people, doors, pots, balls.
- Deck (primary): estimate distance **between 2+ objects** in an RGB frame; BONUS = camera→chosen-reference-object distance.
- Provided: images of common objects at **measured distances** + Go2 intrinsics + hidden test set.
- Suggested: pretrained monocular depth (Depth Anything / MiDaS) for relative cue + **pinhole geometry** (real object height × focal ÷ pixel height → metric), fuse the two.
- Deck requirement: **minimum 2 approaches** (e.g. YOLO, ViT, CNNs).
- Described by the organizers as "the cleanest, best-scoped ML problem on the Monsson track: one frame in, one number out, one clear metric."

**Mental Map**
- From a single RGB stream, **no LiDAR / no depth sensor**: build a 2D/2.5D occupancy map OR topological graph + plan trajectories between arbitrary points → command sequence `(walk X m, rotate Y°)`.
- Provided: **3–4 indoor exploration clips** (office, hallway, room w/ obstacles) + **ground-truth trajectories** for evaluation.
- Suggested: monocular VO/SLAM (ORB-SLAM-style) or learned depth+pose; planning A*/RRT; **Dijkstra on the topological graph = bonus**.
- "High-ceiling challenge: ambitious, most likely to wow judges if it converges. Perfect metric scale is a stretch, not a requirement — get something navigable first."
- BONUS: metric scale from intrinsics+motion; loop-closure to correct drift.

### Deliverables (identical across all three)
1. **Git repo** — code + README + run instructions.
2. **Demo** — notebook or script that runs on the provided mini inference set.
3. **5-minute technical pitch** — architecture, decisions, trade-offs, **performance report**.
4. **Teamwork note** — how the team collaborated.

## 3. The camera (critical for How Far & Mental Map)

From `go2_camera_details.txt` — the Unitree Go2 front camera at 1080p:

```
Intrinsic matrix K (1920×1080):
| 554.3     0    960 |
|    0   554.3   540 |
|    0      0      1 |
fx = fy = 554.3 px   cx = 960   cy = 540
FOV = 120°   Aperture = F2.2   Resolution = 1920×1080   Frame rate = 15 FPS
```

Observations confirmed from the data:
- **Wide-angle / strong barrel distortion** — straight lines bow outward near frame edges. No distortion coefficients were provided → must undistort with an estimated model or work near the image center where distortion is mild.
- **Low mount** (~30 cm off the floor, dog's-eye view). The ground plane fills the lower frame → enables ground-plane / camera-height scale recovery.
- fx=554.3 with width 1920 and 120° FOV is internally consistent (horizontal FOV ≈ 2·atan(960/554.3) ≈ 120°). The intrinsics are trustworthy.
- 15 FPS is low for fast SLAM/VO baselines → favors keyframe-based or learned methods that tolerate larger inter-frame motion.

## 4. The provided "unique" inference data (what the team has locally)

Path: `/Users/mihaimdm/Downloads/inference_sets_contest/`

| Set | Contents | Notes |
|-----|----------|-------|
| `how_far/` | **20 JPG stills**, 1920×1080 | Target objects are generic (office stool, grey suitcase) in an industrial workshop — **not cats**. Full frames. **No distance labels / no bounding boxes provided.** → usable for self-calibration & qualitative checks, not supervised eval. |
| `mental_map/` | **5 MP4 clips**, 1920×1080 @ 15 FPS, 17–36s (266–538 frames) | Robot drives forward through an indoor break room (fridge, water cooler, doors, office stool). Forward translation + some yaw. **No GT trajectory file present locally** (the briefs say GT exists for the hidden/official set). |
| `go2_camera_details.txt` | intrinsics (above) | |

- **No `cat_tracker/` data locally.** If pursuing Cat Tracker, the team must use the on-site provided clips (~15) or a downloaded/webcam cat video to develop & demo.
- **"Cat" is the hackathon mascot**, not literally the only subject. The How Far data uses generic objects; the deck's How Far example shows *people* with an inter-person distance line ("distance: 317.55").

## 5. The team's physical hardware (from photo `IMG_0651` + `inventory.md`)

> **Important:** the prize is scored on the **Go2 hidden test set** (Go2 footage). The physical rig below is **not what's scored** — it's an optional live-demo prop. Optimize software on the Go2 inference data first.

- **Compute:** Arduino Mega 2560 (in chassis) + 2× more Arduino boards (Uno genuine + Uno clone), 1× Raspberry Pi (clear case, BCM2837-class → likely Pi 3B).
- **Drive:** 2WD transparent acrylic chassis, **L293D motor shield** on the Mega, 2× yellow DC gear motors + wheels.
- **Sensing:** **HC-SR04 ultrasonic** distance sensor (range ~2 cm–4 m, ±~1 cm) — a cheap ground-truth source for the How Far demo; IR/line sensor (TCRT5000-style).
- **Actuation:** **micro-servo + bracket** = a pan/tilt mount for "the camera that can be moved"; small fan/blower; buzzer; 16×2 I²C LCD.
- **Camera:** **TP-Link Tapo C211** (1080p Wi-Fi pan/tilt, RTSP/ONVIF). NOTE: its intrinsics differ from the Go2's, so any metric model anchored to the Go2 must be re-anchored if run on Tapo frames.
- **Misc:** breadboards, jumpers, 9V battery + clip, USB adapter, loose passives.

## 6. The Karpathy reference (reality-check — detail in research doc)

The notes mention "auto research Karpathy" (nanoGPT/nanochat-style `prepare.py`/`train.py`) and `multica-ai/andrej-karpathy-skills` (coding-discipline rules). **All three briefs explicitly say no training is required** (pretrained YOLO, pretrained Depth Anything, classical SLAM). With ~24h left, **train-from-scratch is the wrong bet.** The Karpathy value here is (a) the engineering discipline as a coding-rules layer, and (b) an *optional, time-boxed* light fine-tune as a stretch. Flagged formally at the decision gate.

## 7. Audit takeaways (what this means for strategy)

1. **You can only win one Monsson prize → pick one challenge and go deep.** Building three half-solutions loses to one clean, well-reported solution.
2. **How Far is the highest-probability prize:** crisp metric (MAE<15%), explicitly "best-scoped," solvable with pretrained depth + pinhole geometry + your provided intrinsics, and you already have sample data. Your HC-SR04 gives free ground truth for a killer live demo.
3. **Mental Map is the highest-ceiling / wow pick** but Advanced and risky in 24h (monocular SLAM convergence on low-texture, 15 FPS, distorted wide-angle video is the hard part). Has a blessed "floor version" (topological graph + planned path).
4. **Cat Tracker is the most demo-friendly** (live follow loop on your robot) but you have **no local cat data** and it needs the control loop + smoothness tuning judges explicitly score.
5. **Optimize for the Go2 inference data, not your Arduino robot.** The robot is a bonus demo, not the deliverable.
6. **The "min 2 approaches + performance report" requirement is half the score** — whichever you pick, plan to compare two methods and report numbers, not just ship one model.

→ See `01-RESEARCH-ARCHITECTURE.md` for verified SOTA + buildable architectures per challenge.
