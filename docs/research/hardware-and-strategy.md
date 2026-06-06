I have the hardware inventory confirmed (HC-SR04, micro-servos, L293D shield, Mega 2560, Pi, 2WD chassis — matches the brief; note there's actually an extra Uno + sensor shield, and 2 servos available for a pan/tilt mount). I have everything I need to write the deliverable.

Here is the polished strategy document.

---

# Monsson "hack a ton 2026" — Final-Day Battle Plan

**Status:** ~24h left · Team challenge · Live demo + 5-min pitch · Mamaia, RO

---

## 0. The One Thing That Decides Everything (read this twice)

> ### 🎯 You are scored on the **Go2 hidden test set**, NOT on your Arduino+Tapo robot.
>
> Every prize (3 challenges × €1000, separate juries) is won or lost on **how well your software performs on the provided Go2 inference data and the Go2 hidden test set.** The physical robot you built (Mega 2560 + L293D + HC-SR04 + servo + Pi + Tapo C211) **earns zero points by itself.** It is a *stage prop*.

**What this means concretely:**

| If you spend an hour on… | Points impact |
|---|---|
| Improving MAE / route-error on Go2 frames | **Direct** — this is the scored number |
| Re-anchoring your model to the Go2 intrinsics (`fx=fy=554.3`) | **Direct** — wrong intrinsics = wrong metric scale = lost MAE |
| Making the demo notebook run cleanly on the provided mini set | **Direct** — it's a graded deliverable |
| Wiring the Tapo to the Pi to the Arduino to chase a real cat | **Zero scored points** (but high *wow*, see §6) |
| Training a model from scratch (the Karpathy idea) | **Negative** — see §1 |

**Rule of thumb for the next 24h:** *If a task does not improve the number computed on Go2 footage, it is either a demo garnish or a distraction. Triage accordingly.*

---

## 1. Kill the "train from scratch" instinct — but keep the Karpathy discipline

You mentioned wanting to **train a model from scratch (nanoGPT/nanochat-style `prepare.py` + `train.py`)**. For a vision-geometry hackathon judged on MAE/route-error in 24h, **training from scratch is a trap:**

- You have **no distance labels** in `how_far/` (20 unlabeled full frames) and only **5 unlabeled clips** in `mental_map/`. You cannot supervise a from-scratch metric model with that.
- The winning move is **pretrained perception + classical geometry**, where the *only* thing you "fit" is a 1-parameter scale/bias calibration — a `np.polyfit`, not a training run.

**Keep the Karpathy *coding discipline*, drop the Karpathy *training pipeline*:**

> *Think before coding · simplest thing that works first · surgical changes · one explicit, verifiable goal (the MAE/route number) · measure every change.*

The Karpathy-style `prepare.py` / `eval.py` split is still the right *repo skeleton* — just `prepare.py` = "load frames + intrinsics + run pretrained model", `eval.py` = "compute the scored metric on the mini set". That's exactly the graded deliverable.

---

## 2. Camera reality — Go2 vs. your Tapo C211

This is the single most common silent failure in this hackathon. **The metric scale of any geometry-based estimate is a direct function of the camera intrinsics.** Use the wrong `f`, and your distances are off by a constant multiplier.

### Go2 (what you're scored on)
```
fx = fy = 554.3      # pixels, at 1920x1080
cx = 960, cy = 540
FOV  = 120°          # wide-angle → strong barrel distortion
res  = 1920x1080 @ 15 FPS, F2.2, mounted ~30 cm off the floor (dog's-eye)
```
Two consequences that bite:
1. **Barrel distortion is real at 120°.** Objects near the frame edge are bent. If you do pinhole geometry on an edge object without undistorting, your height-in-pixels is wrong. Either (a) operate on center-ish crops, or (b) apply a mild undistort. *If the organizers gave no distortion coefficients, state that assumption in the pitch and prefer center crops.*
2. **Low mount + wide FOV** means the floor fills the lower frame — great for "object sits on the ground plane" tricks (§4), bad for assuming objects are centered vertically.

### Tapo C211 (your demo prop only)
- **Pull frames:** RTSP is the clean path.
  ```
  rtsp://<user>:<pass>@<cam_ip>:554/stream1     # 1080p main stream
  rtsp://<user>:<pass>@<cam_ip>:554/stream2     # ~360p substream, lower latency
  ```
  The `<user>:<pass>` are the **Tapo "Camera Account"** you set in the Tapo app under *Advanced Settings → Camera Account* (NOT your TP-Link cloud login). Then:
  ```python
  import cv2
  cap = cv2.VideoCapture("rtsp://user:pass@192.168.1.50:554/stream1",
                         cv2.CAP_FFMPEG)
  ok, frame = cap.read()          # 1920x1080 BGR
  ```
  ONVIF is also supported (port 2020 on Tapo) if you want auto-discovery, but RTSP+FFmpeg is fewer moving parts for a demo.
- **Pan/Tilt control** (it's a PTZ cam): three options —
  - **Tapo app** (manual, fine for a scripted demo).
  - **ONVIF PTZ** (`ContinuousMove` / `AbsoluteMove`) via the `onvif-zeep` Python lib.
  - **`pytapo`** library — cleanest for code: `from pytapo import Tapo; tapo.moveMotor(x, y)` and presets. This is the one to use if you want the *camera* to track instead of the *chassis*.
- ⚠️ **Intrinsics differ.** The C211's `fx, fy` are **not** 554.3 — different sensor, different lens, likely different effective resolution on substream. **Any metric model demoed on live Tapo frames must be re-anchored** (recompute/refit the scale) or it will report wrong meters on stage. Easiest re-anchor: hold an object of known size at a known distance, snap one frame, solve for the effective focal length, done. Treat Go2-tuned and Tapo-tuned as **two configs of the same code**, selected by a `--camera go2|tapo` flag.

**Bottom line:** develop and report against **Go2 intrinsics**. The Tapo path is a *second, separately-calibrated entry point* you only light up for the live wow-moment.

---

## 3. Compute reality — laptop is the brain, Pi is the gateway

| Workload | Pi 3/4 real-time? | Verdict |
|---|---|---|
| Depth Anything / MiDaS depth | ❌ seconds/frame | **Laptop GPU** |
| YOLO detection/tracking @15 FPS | ❌ on Pi | **Laptop GPU** |
| Monocular VO / SLAM | ❌ | **Laptop GPU** |
| Reading HC-SR04, driving L293D, panning servo | ✅ trivial | **Arduino (via Pi)** |
| Pulling RTSP frames, serial bridge | ✅ | **Pi** |

**Architecture for the live demo:**
```
Tapo C211 ──RTSP──▶ Laptop (GPU: detection/depth/geometry → dx,dy,rot)
                        │
                        ▼ (USB / wifi)
                       Pi (gateway) ──USB-serial──▶ Arduino Mega
                                                     ├─ L293D → 2 DC motors
                                                     ├─ servo → pan camera
                                                     └─ HC-SR04 → ground-truth distance ▲ back to laptop
```
The Pi does **not** run the models. It shuttles frames in and commands out. The laptop is the brain. This keeps your scored pipeline (which runs on the laptop against Go2 files anyway) **identical** to your demo pipeline, minus the I/O endpoints.

---

## 4. The HC-SR04 trick — your secret weapon for *How Far?*

The HC-SR04 ultrasonic sensor (range **~2 cm – 4 m, ±~1 cm**, 15° cone) is a **cheap ground-truth distance source.** This is gold for the **How Far?** challenge because the most persuasive thing you can do in a 5-min pitch is:

> *"Our model says the stool is 1.84 m away. Our ultrasonic ground truth says 1.86 m. Live. On stage."*

That single moment does more for the *methodological rigor* and *uncertainty* judging criteria than three slides of math. The sensor's ±1 cm beats the contest's MAE<15% bar by a mile, so it's a credible GT. It also doubles as the **safe-distance enforcer** for Cat Tracker (stop/back-off when distance < threshold).

**Arduino sketch (minimal, complete):**
```cpp
#include <Servo.h>
// L293D shield: adjust pins to your shield's mapping (AFMotor lib if classic Adafruit shield)
const int TRIG=30, ECHO=31, SERVO_PIN=9;
const int M1A=22, M1B=23, M2A=24, M2B=25;   // example direction pins
Servo pan;

long readCM(){
  digitalWrite(TRIG,LOW); delayMicroseconds(2);
  digitalWrite(TRIG,HIGH); delayMicroseconds(10); digitalWrite(TRIG,LOW);
  long us = pulseIn(ECHO,HIGH,30000);        // timeout ~5 m
  return us ? us/58 : -1;                     // cm, -1 = no echo
}
void drive(int dx,int dy,int rot){            // crude differential mix
  int l=dy+rot, r=dy-rot;
  digitalWrite(M1A,l>=0); digitalWrite(M1B,l<0);
  digitalWrite(M2A,r>=0); digitalWrite(M2B,r<0);
  // (PWM via analogWrite on enable pins for speed = |l|,|r|)
}
void setup(){
  Serial.begin(115200); pan.attach(SERVO_PIN);
  pinMode(TRIG,OUTPUT); pinMode(ECHO,INPUT);
  pinMode(M1A,OUTPUT);pinMode(M1B,OUTPUT);pinMode(M2A,OUTPUT);pinMode(M2B,OUTPUT);
}
void loop(){
  // Protocol IN:  "C dx dy rot pan\n"   (ints)
  if(Serial.available()){
    String s=Serial.readStringUntil('\n');
    int dx,dy,rot,p;
    if(sscanf(s.c_str(),"C %d %d %d %d",&dx,&dy,&rot,&p)==4){
      pan.write(constrain(p,0,180));
      drive(dx,dy,rot);
    }
  }
  // Protocol OUT: "D <cm>\n"  ground-truth distance, 20 Hz
  static unsigned long t=0;
  if(millis()-t>50){ t=millis(); Serial.print("D "); Serial.println(readCM()); }
}
```

**Pi-side (pyserial) outline:**
```python
import serial, threading
ser = serial.Serial("/dev/ttyACM0", 115200, timeout=0.1)

def send_cmd(dx, dy, rot, pan):           # called by laptop over socket
    ser.write(f"C {dx} {dy} {rot} {pan}\n".encode())

def read_gt():                            # ground-truth distance loop
    for line in iter(ser.readline, b""):
        if line.startswith(b"D"):
            cm = int(line.split()[1])
            push_to_laptop(cm)            # compare vs model estimate

threading.Thread(target=read_gt, daemon=True).start()
```
Protocol is intentionally tiny: **Pi → Arduino** = `C dx dy rot pan`; **Arduino → Pi** = `D <cm>`. That's the whole contract. The laptop decides `dx/dy/rot`, the Arduino reports ground truth back up the chain.

---

## 5. WHICH challenge to pick — the decision

### Recommendation: **HOW FAR? (primary)**, with *Mental Map* as the stretch only if How Far lands early.

**Why How Far wins for *your* situation specifically:**
- It's the **only challenge where you have a clean, killer live demo** thanks to the HC-SR04 ground truth (§4). Judges *feel* a 1.84 vs 1.86 m match.
- The technique is **well-trodden and de-riskable in hours**: pretrained detector (YOLO) → known real-world object height × `fx` / pixel-height → metric distance (pinhole), fused with a **Depth Anything/MiDaS** relative cue, then a **1-line affine calibration** to anchor the scale. Two genuinely different approaches = satisfies the "minimum 2 approaches" rule for free.
- **Uncertainty/confidence-interval bonus is cheap**: report the spread between the geometric and depth estimates as your CI. Methodological-rigor points, almost free.
- **You have on-hand data to dev against** (`how_far/`, 20 frames) even though they're unlabeled — you self-label a few with a tape measure / the HC-SR04 to build a tiny calibration + sanity set.

### Reasoning table

| Criterion | **How Far? ✅ PICK** | Cat Tracker | Mental Map |
|---|---|---|---|
| **Effort to a working number (24h)** | Low–Med | Med | **High** |
| **Risk of no clean metric** | **Low** | Med (tracking jitter, reID) | **High** (VO scale drift) |
| **Data on hand** | 20 Go2 stills (unlabeled) | **None locally** (no cat clips) | 5 Go2 clips + GT trajectories |
| **Wow-factor of live demo** | **High** (ultrasonic GT match) | High (robot chases cat) | Med (map on screen) |
| **P(clean scored result)** | **High** | Med | Low–Med |
| **"2 approaches" satisfied trivially?** | **Yes** (geometry vs depth) | Yes (YOLO vs DETR) | Partly |
| **Hidden-set robustness exposure** | Med (OOD distances) | High (occlusion/sudden motion) | High (rotations/repeats) |

**Reading the table:** How Far is the **lowest-risk path to a real, defensible number** *and* the **highest-impact live demo for the hardware you actually have.** Cat Tracker is tempting for wow but **you have no cat clips locally** — you'd be flying blind on the exact data distribution the jury scores, and tracking is where things oscillate and break on stage. Mental Map is the most impressive *if* it works, but monocular metric-scale VO in 24h is a coin-flip on the scored route error — pick it only if you're chasing the "Advanced" glory and accept the risk.

**If you have appetite for the Advanced jury:** do **How Far first, get a green number locked by hour ~12**, then port the *same* depth backbone into a quick Mental Map attempt (depth + simple forward-motion odometry → 2.5D occupancy → A*). The pretrained-depth investment is shared, so the marginal cost is lower than starting Mental Map cold.

---

## 6. Using the physical rig as a wow-factor demo *without* it eating your day

**Timebox the hardware to ≤3 hours, late, and only after the scored number is locked.** Sequence:

1. **Hours 0–12:** 100% software on Go2 data. Lock the How Far MAE + the demo notebook that runs on the provided mini set. *This is your prize.*
2. **Hours 12–18:** polish — undistortion, calibration fit, confidence interval, README, pitch deck, performance report.
3. **Hours 18–21 (optional):** stand up the rig. Tapo RTSP → laptop → Pi serial → Arduino. The **one** scripted moment: place the stool, model prints meters, HC-SR04 prints meters, they match. Servo pans to "find" the object. That's it.
4. **Keep a recorded fallback video** of the rig working. Live hardware fails on stage; a clip never does. Show the clip, then attempt it live as a bonus.

**Framing for the 5-min pitch:** "Our scored pipeline runs entirely on the Go2 data — here's the MAE. *And* because we believe in our numbers, we re-anchored it to a $5 webcam and validated against an ultrasonic ground truth, live." That sentence converts a prop into a **rigor argument**, which is exactly what the How Far jury rewards (methodological rigor + uncertainty quality), instead of a distraction.

---

## 7. 24-hour checklist

- [ ] Repo skeleton (Karpathy-discipline): `prepare.py` (load frames + Go2 intrinsics + pretrained model), `eval.py` (compute scored MAE on mini set), `demo.ipynb`.
- [ ] Hardcode Go2 `fx=fy=554.3, cx=960, cy=540`; add a `--camera go2|tapo` flag for the demo re-anchor.
- [ ] **Approach A:** YOLO box + pinhole metric distance (real height × `fx` / pixel height).
- [ ] **Approach B:** Depth Anything/MiDaS relative depth + affine calibration to meters.
- [ ] Fuse A+B; report disagreement as the **confidence interval** (bonus).
- [ ] Self-measure a handful of `how_far/` frames (tape / HC-SR04) → calibration + sanity MAE.
- [ ] Handle 120° barrel distortion (undistort or prefer center crops); note assumption in pitch.
- [ ] Performance report: MAE on mini set, behavior at extreme/OOD distances, latency.
- [ ] *(Optional, last)* Rig demo: RTSP→laptop→Pi→Arduino, ultrasonic GT match. Record fallback clip.
- [ ] 5-min pitch: architecture · 2-approach comparison · trade-offs · **the number** · collaboration note.

**The whole strategy in one line:** *Win How Far on the Go2 data with pretrained-perception + pinhole geometry + a 1-line calibration; turn the Arduino/HC-SR04 rig into a 90-second rigor-flex demo, not a project.*