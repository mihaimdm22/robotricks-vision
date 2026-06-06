The provided data isn't in this workspace (it's referenced in the brief, not committed here). That's fine — I have the verified spec from the context. I have everything I need to write the deliverable.

---

# Karpathy Reality-Check + Reproducible Data Pipeline

*ML-lead memo for the Monsson "hack a ton 2026" — final-day build plan. ~24h left, demoed live, 5-min pitch.*

---

## Part 1 — Karpathy Reality-Check

### What these five things actually are (verified)

| Project | What it really is | Relevance to a 24h CV hackathon |
|---|---|---|
| **[nanoGPT](https://github.com/karpathy/nanoGPT)** | ~300-line `train.py` + ~300-line `model.py` that **pretrains a GPT from scratch** on text. The `data/*/prepare.py` scripts tokenize raw text into `train.bin`/`val.bin`. Repro of GPT-2 (124M) = **~4 days on an 8×A100 node**. | This is a *text LLM pretraining* template. The `prepare.py → train.py` **shape** is worth borrowing; the *workload* (train-from-scratch) is not. |
| **[nanochat](https://github.com/karpathy/nanochat)** | ~8,000-line full-stack ChatGPT clone (tokenizer in Rust, pretrain on FineWeb, SFT, optional GRPO RL). "Best ChatGPT $100 can buy" = **~4h on an 8×H100 node (~$24/h)**. | A *training-infra showcase*. Irrelevant to monocular CV. Cost/time alone disqualifies it as a hackathon path. |
| **[micrograd](https://github.com/karpathy/micrograd)** | A tiny scalar-valued autograd engine + a PyTorch-like NN API. Pedagogical "how does backprop work." | Teaching tool. Zero production value here. Mention only as conceptual lineage. |
| **[karpathy/autoresearch](https://github.com/karpathy/autoresearch)** | An **autonomous-experimentation loop**: you write a `program.md` of research directions, a coding agent (Claude Code / Codex) edits `train.py`, runs a **fixed 5-min** experiment, reads one metric, and keeps/rejects the change. ~12 experiments/hr, ~100 overnight. **One GPU, one file, one metric.** | The single *most* applicable Karpathy idea here — **not as a trainer, but as a discipline**: a frozen harness with one metric and an automated keep/reject loop. We steal the *loop*, not the *training*. |
| **[multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills)** | A `CLAUDE.md` (+ `EXAMPLES.md`, a Claude-Code plugin and skills folder) codifying Karpathy's anti-pitfalls: **don't assume / surface tradeoffs, minimum code (nothing speculative), goal-driven execution** (imperative → declarative goals with verification loops). | The **coding-discipline layer**. Drop it in verbatim-ish as our engineering rules. This is the highest-ROI "Karpathy spirit" item for a team shipping under time pressure. |

### Straight verdict: train a CV model from scratch? **No. Don't.**

For this hackathon, training a CV model from scratch (a nanoGPT-style `prepare.py`/`train.py` pipeline) is the **wrong** call. Decisive reasons:

1. **The briefs explicitly say no training is required**, and the prize is scored on a *hidden Go2 test set* you never see. From-scratch training on ~20 stills + 5 clips would massively overfit your tiny local data and **generalize worse** than a pretrained backbone that already saw millions of images. You'd be trading a strong prior for noise.
2. **nanoGPT/nanochat are text-LLM pretraining templates.** None of them ships a CV detector or a depth model. Reusing their *shape* is fine; reusing their *task* means re-deriving YOLO/Depth-Anything quality in 24h — impossible.
3. **The clock.** A from-scratch detector that's even mediocre needs thousands of labeled boxes + hours of GPU + a tuning loop you won't have time to debug live. Pretrained **YOLO** (cats are COCO class 15 — zero labeling needed) and **Depth-Anything V2 / MiDaS** (metric-ish monocular depth out of the box) give you a *working demo in the first hour*.
4. **The rubrics reward engineering judgment, not heroics.** All three challenges score MAE/route-error/latency/uncertainty + "minimum 2 approaches compared." That's a *pretrained-models-fused-well* game, not a *train-from-scratch* game.

**So: use pretrained YOLO + Depth-Anything/MiDaS as the spine of all three challenges.** That is the correct, defensible, time-respecting decision — and it's exactly what the deck's "Suggested" hints point at.

### The RIGHT way to incorporate the Karpathy spirit

You don't honor Karpathy by training from scratch. You honor him with **discipline + a frozen metric loop + an optional, time-boxed fine-tune**. Two concrete layers:

#### (a) Coding-discipline layer — a project `CLAUDE.md` / engineering-rules file

Adopt the `multica-ai/andrej-karpathy-skills` rules as our `CLAUDE.md` at repo root, lightly tuned for a CV hackathon. Core rules, condensed:

```markdown
# ENGINEERING RULES (Karpathy-derived) — hack-a-ton 2026

1. DON'T ASSUME. Surface tradeoffs. If a brief is ambiguous (How-Far:
   "between objects" vs "camera-to-object"), state the assumption in code
   comments AND in the README, and support BOTH outputs.

2. MINIMUM CODE. Nothing speculative. No abstraction for single-use code.
   No config knob nobody asked for. If it's not on the rubric, don't build it.

3. GOAL-DRIVEN EXECUTION. Turn every task into a declarative goal with a
   verifiable check:
     - "infer runs on all 20 how_far stills and writes 20 overlays" (checkable)
     - "evaluate prints MAE and it is a finite float" (checkable)
   Loop until the check passes; don't hand-wave "should work."

4. ONE METRIC, FROZEN HARNESS (autoresearch spirit). Each challenge has ONE
   headline number (MAE / route-error / FPS). The eval harness is FROZEN.
   Every change is judged keep/reject against it. No moving the goalposts.

5. SURGICAL CHANGES. Touch the fewest files. Reproducible: one `make` target
   per stage, deterministic seeds, config in one YAML.
```

Why this matters more than the model: with 4 people and 24h, the failure mode is *thrash* — half-built reID, a depth fusion that silently NaNs, a demo that won't run on the judges' machine. These five rules are the antidote, and "we ran a Karpathy-style frozen-metric keep/reject loop" is a *great* line in the 5-min pitch.

#### (b) Optional light-touch fine-tune / calibration — a **stretch**, time-boxed, go/no-go

This is where a *tiny* amount of "training" is genuinely worth it — not from scratch, but **calibration on top of pretrained models**. Frame all of these as stretch goals behind hard time-gates:

| Stretch | What it is | Worth it because | Go/No-Go gate |
|---|---|---|---|
| **How-Far per-class scale calibration** (recommended #1) | Fit ONE scalar/affine correction per object class so metric distance matches your few measured ground-truth distances. `d_metric = a_class · d_raw + b_class`, least-squares on a handful of points. **Seconds to fit, no GPU.** | Directly attacks the MAE rubric and the Go2's barrel distortion bias. Turns a generic depth model into a *calibrated* one. This alone can move MAE under the 15% target. | **GO** if you have ≥3 measured distances per class by hour 6. Else ship raw depth + pinhole geometry. |
| **YOLO fine-tune for cats** (Cat Tracker) | Pull a small cat set from Roboflow Universe, fine-tune YOLOv8n for ~20–40 epochs on a single GPU (Roboflow/Colab, ~20–40 min). | COCO "cat" is already strong, but Go2's *low, wide-angle, dog's-eye* view is OOD. A light fine-tune on low-angle cats can cut occlusion/false-negative misses. | **GO** only if detection+tracking baseline is green by **hour 8** AND a GPU is free. Hard **NO-GO** after hour 14 — never fine-tune into the demo window. |
| **Confidence-interval head** (How-Far bonus) | Use depth-vs-geometry disagreement as an empirical uncertainty; optionally fit a tiny isotonic/linear calibrator on residuals. | The rubric explicitly rewards uncertainty quality. Cheap, no training. | **GO** if MAE path is done by hour 16. |

**Time-boxing rule (autoresearch-style):** each stretch runs as a *fixed-budget experiment* against the frozen eval harness. If it doesn't beat the baseline metric inside its box, **reject and revert** — exactly the keep/reject loop. Never let a fine-tune block the live demo. Baseline-first, stretch-second, always a working `git` state to demo.

---

## Part 2 — Data Pipeline + Datasets

### Design goals
Config-driven, reproducible, one command per stage. The pipeline ingests the provided inference sets (`how_far/` stills, `mental_map/` videos), **undistorts with the Go2 intrinsics** (120° FOV = strong barrel distortion — non-negotiable for metric accuracy), runs the chosen model, writes predictions + overlays, and computes metrics. Same skeleton serves all three challenges; only the `model` and `task` configs change.

### Go2 intrinsics (from `go2_camera_details.txt`)
`fx=fy=554.3, cx=960, cy=540` at 1920×1080, FOV≈120°, F2.2, 15 FPS, camera ~30 cm off floor. The wide FOV + that focal length implies heavy radial distortion; we estimate distortion coefficients (no factory `k1..k3` given) by fitting straight-line edges in the break-room clips, or fall back to a single-parameter FOV/division model. **Undistortion happens once, up front, and every downstream stage consumes rectified frames** so pinhole geometry (`d = f · H_real / h_pixels`) is valid.

### Directory layout

```
robotricks-vision/
├── CLAUDE.md                      # Karpathy engineering rules (Part 1a)
├── Makefile                       # prepare -> infer -> evaluate -> report
├── pyproject.toml                 # ultralytics, opencv, torch, depth-anything, supervision, typer
├── configs/
│   ├── camera/go2_1080p.yaml      # fx,fy,cx,cy + estimated distortion coeffs
│   ├── how_far.yaml               # task=distance, model=depth_anything_v2 + pinhole fuse
│   ├── cat_tracker.yaml           # task=track, model=yolov8 + bytetrack
│   └── mental_map.yaml            # task=slam, model=orbslam|depth+pose, planner=dijkstra
├── data/
│   ├── raw/                       # provided inference sets (read-only, gitignored)
│   │   ├── how_far/               # 20 JPG 1920x1080
│   │   ├── mental_map/            # 5 mp4 1920x1080@15fps
│   │   └── go2_camera_details.txt
│   ├── external/                  # downloaded public datasets (see below)
│   └── processed/                 # undistorted frames, train.jsonl-style manifests
│       ├── how_far/undistorted/*.jpg
│       ├── mental_map/<clip>/frames/*.jpg
│       └── manifests/*.jsonl      # one row per sample: path, intrinsics, gt(if any)
├── outputs/
│   ├── predictions/*.jsonl        # raw model outputs per stage
│   ├── overlays/*.jpg|*.mp4       # human-checkable visuals for the demo
│   ├── metrics/*.json             # MAE / route-error / FPS — the frozen numbers
│   └── report/report.md           # auto-generated performance report for the pitch
├── src/robotricks/
│   ├── io/loader.py               # config-driven dataset loader (stills + video frames)
│   ├── calib/undistort.py         # Go2 intrinsics, init_undistort_rectify_map
│   ├── models/                    # yolo.py, depth.py, track.py, vo.py  (thin wrappers)
│   ├── tasks/                     # how_far.py, cat_tracker.py, mental_map.py
│   ├── eval/metrics.py            # MAE, %err, route-error, latency/FPS, uncertainty
│   └── report/build.py            # metrics + overlays -> report.md
└── notebooks/demo.ipynb           # runs end-to-end on the provided mini set (deliverable)
```

### Config-driven loader (the spine)
`src/robotricks/io/loader.py` reads a task YAML and yields a uniform `Sample(image, intrinsics, meta, gt)` regardless of source:
- **Stills** (`how_far`): one `Sample` per JPG, already undistorted.
- **Video** (`mental_map`/cat clips): `cv2.VideoCapture` → frame extraction at a configurable stride (e.g. every Nth frame for speed; full rate for tracking), each frame undistorted on the fly, timestamps preserved for VO and speed estimation.
- Intrinsics injected from `configs/camera/go2_1080p.yaml` so geometry code never hard-codes numbers.

This single abstraction is what makes the pipeline reproducible: change the YAML, not the code.

### Recommended PUBLIC datasets (exact handles + why)

These are for **optional fine-tune / calibration / extra sanity eval** — the scored prize is the hidden Go2 set, so treat these as enrichment, not the main course.

#### Cat Tracker
| Dataset | Handle | Why it fits | License / size / quick-start |
|---|---|---|---|
| **COCO – cat class** | `cat` = category id **17** (class index **15** in the 80-class YOLO map) | YOLOv8/v11 pretrained on COCO already detect cats out of the box — **zero labeling, instant baseline**. | CC-BY 4.0 (annotations); images Flickr terms. ~118k train imgs (you only need the pretrained weights). Quick-start: `from ultralytics import YOLO; YOLO('yolov8n.pt')`. |
| **Roboflow Universe – cat detection** | e.g. search Universe for "cats" / "cat detection" projects (e.g. `roboflow-universe/cat-detection`-style projects); pull in YOLO format | Adds **low-angle / cluttered indoor cats** to fine-tune for the Go2's dog's-eye OOD view. Roboflow gives YOLO-format export + a one-line download snippet. | Mixed CC licenses per project — check each. Typically a few hundred–few thousand imgs. Quick-start: `roboflow` pip pkg → `project.version(n).download("yolov8")`. |
| **Open Images V7 – Cat** | class `Cat` (`/m/01yrx`) | Largest *box-labeled* cat pool if you want a bigger fine-tune set; great for reID-flavored variety (many breeds/poses). | CC-BY 4.0 annotations. Millions of imgs total; use FiftyOne to pull only Cat boxes. Quick-start: `fiftyone zoo` `open-images-v7` with `classes=["Cat"]`. |
| **Hugging Face datasets** | `cats_vs_dogs`, or video MOT-style sets via `datasets`/`huggingface_hub` | Quick image variety for sanity / augmentation; HF Hub for any community cat-tracking clips. | Per-dataset (mostly permissive). `load_dataset("cats_vs_dogs")`. |

> Tracking itself needs **no dataset** — use **ByteTrack/BoT-SORT** (built into `ultralytics` / `supervision`) on top of detections for identity + reID across occlusion. The bonus "inter-cat distance" reuses the How-Far geometry module.

#### How Far?
| Dataset | Handle | Why it fits | License / size / quick-start |
|---|---|---|---|
| **NYU Depth V2** | `nyu_depth_v2` (HF: `sayakpaul/nyu_depth_v2`) | **Indoor** RGB-D with metric depth — exact domain match (office/room scenes, similar object classes: chairs, doors). Perfect to **sanity-check + calibrate** your monocular depth scale before the hidden test. | Mostly research-use; ~50k frames (labeled subset 1449). Quick-start: `load_dataset("sayakpaul/nyu_depth_v2")`. |
| **KITTI (depth)** | `kitti` depth benchmark | Standard **metric monocular-depth benchmark** — good for verifying Depth-Anything/MiDaS scaling behavior at *long* range (the rubric tests extreme/OOD distances). | CC-BY-NC-SA 3.0 (non-commercial — fine for a hackathon). Large; grab the depth subset only. |
| **TUM RGB-D** | `tum_rgbd` (freiburg sequences) | Indoor RGB-D with **ground-truth trajectories** — doubles as VO/SLAM sanity for Mental Map. | Research license. Per-sequence GB-scale. Quick-start: download a `freiburg1_*` sequence. |
| **Depth-Anything V2 weights** | HF `depth-anything/Depth-Anything-V2-Small` (or `Base`) | The actual model — strong monocular relative/metric depth, runs real-time on a consumer GPU. **Fuse with pinhole `d=f·H/h`** for metric distance. | Apache-2.0 (Small/Base). Quick-start: `transformers` pipeline `depth-anything`. |

> **How-Far core method (no training):** (1) Depth-Anything for a dense relative-depth cue; (2) pinhole geometry from known real-world object heights (chair ~0.9 m, door ~2.0 m, person ~1.7 m) × `fx` ÷ pixel height; (3) **fuse** the two and apply the per-class scale calibration (Part 1b). Output BOTH "distance between objects" (deck) and "camera-to-object" (website) to cover the ambiguity.

#### Mental Map
| Dataset | Handle | Why it fits | License / size / quick-start |
|---|---|---|---|
| **TUM RGB-D** | `freiburg2_*`, `freiburg3_*` | Indoor handheld trajectories w/ GT pose — **the** benchmark to validate monocular VO scale + loop closure before running on the break-room clips. | Research license. Quick-start: ORB-SLAM3 ships TUM configs. |
| **KITTI Odometry** | `kitti odometry` seqs 00–10 | Standard VO/odometry benchmark with GT poses — sanity for your trajectory-error metric and metric-scale recovery from motion. | CC-BY-NC-SA 3.0. Large; pull 1–2 sequences. |
| **ScanNet** | `scannet` (request access) | Indoor RGB-D + reconstructed meshes + 2D/2.5D structure — closest analog to "build a 2D/2.5D occupancy map of an explored room." Use for map-quality sanity if time allows. | Requires ToS + access form (slow — only if you have spare time). ~1.5 TB full; use a handful of scenes. |

> **Mental Map core method (no training):** monocular VO (ORB-SLAM3-style) **or** Depth-Anything depth + learned/PnP pose → integrate into a 2D occupancy grid (or topological graph) → plan with **Dijkstra on the graph** (deck bonus) / A* on the grid → emit `walk X m, rotate Y°` command sequence. Metric scale from intrinsics + known forward motion (bonus).

### Makefile / CLI sketch (`prepare → infer → evaluate → report`)

```makefile
# Makefile — one target per pipeline stage, all config-driven
CHALLENGE ?= how_far          # how_far | cat_tracker | mental_map
CFG       := configs/$(CHALLENGE).yaml

.PHONY: prepare infer evaluate report all clean

prepare:                         ## undistort + extract frames + build manifests
	python -m robotricks.cli prepare --config $(CFG)

infer:                           ## run model -> predictions + overlays
	python -m robotricks.cli infer   --config $(CFG)

evaluate:                        ## compute the ONE frozen metric (+ FPS, uncertainty)
	python -m robotricks.cli evaluate --config $(CFG)

report:                          ## metrics + overlays -> report/report.md (for the pitch)
	python -m robotricks.cli report  --config $(CFG)

all: prepare infer evaluate report   ## full reproducible run

clean:
	rm -rf data/processed outputs
```

CLI (Typer) mirrors the Makefile so a judge can run either:
```bash
python -m robotricks.cli prepare  --config configs/how_far.yaml
python -m robotricks.cli infer    --config configs/how_far.yaml --model depth_anything_v2
python -m robotricks.cli evaluate --config configs/how_far.yaml   # -> outputs/metrics/how_far.json
python -m robotricks.cli report   --config configs/how_far.yaml   # -> outputs/report/report.md
# or just:
make all CHALLENGE=how_far
```

Each stage is **idempotent and checkpointed** (skips work whose output exists), so the live demo never re-runs a 20-min inference under pressure — you `make report` from cached predictions. Deterministic seeds + pinned versions in `pyproject.toml` make it reproducible on the judges' machine. The `notebooks/demo.ipynb` deliverable simply calls these stages on `data/raw/` so the "runs on the provided mini inference set" requirement is satisfied verbatim.

### How this maps back to the rubric (so the pitch writes itself)
- **"Minimum 2 approaches compared"** → the `--model` flag: e.g. `infer --model yolov8` vs `--model rtdetr` for Cat Tracker; `depth_anything` vs `pinhole_only` vs `fused` for How-Far. The frozen `evaluate` stage prints both numbers side by side → instant comparison table.
- **Performance report** → `make report` auto-generates `report.md` (metric table + overlay thumbnails) — that *is* the required deliverable.
- **Latency/FPS, uncertainty, route-error** → all live in `eval/metrics.py`, one JSON per run, the single frozen number the keep/reject loop optimizes.

---

### Bottom line
**Don't train from scratch.** Use pretrained **YOLO + Depth-Anything/MiDaS + classic VO/planning**, wrap them in this config-driven, undistort-first, one-command-per-stage pipeline, and honor Karpathy two ways: the `CLAUDE.md` discipline layer and a **frozen-metric keep/reject loop** governing one *optional, hard-time-boxed* calibration/fine-tune. Baseline first and always demo-able; stretch only if the gate is green.

**Sources:** [nanoGPT](https://github.com/karpathy/nanoGPT) · [nanochat](https://github.com/karpathy/nanochat) · [micrograd](https://github.com/karpathy/micrograd) · [karpathy/autoresearch](https://github.com/karpathy/autoresearch) · [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) ([CLAUDE.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md))