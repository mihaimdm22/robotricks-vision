# Hardware

> **TL;DR** — Three cameras matter: the **Go2** (what the contest scores — trust its
> intrinsics), the **Tapo C211** (the live-demo camera over Wi-Fi — *must be calibrated*
> before its distances mean anything), and a **synthetic** source (no hardware). The robot
> is an **Arduino Mega** over **Bluetooth** with a differential drive, a pan servo, and an
> **HC-SR04 ultrasonic sensor** that gives ±1 cm ground truth and enforces a hard safety
> stop in firmware. The laptop is the single wireless hub — no Raspberry Pi. The same
> `C dx dy rot pan` / `D <cm>` protocol runs over every transport (USB, Classic BT, BLE).

**Modules:** `hw/tapo.py` (RTSP + PTZ) · `hw/serial_bridge.py` (USB/Classic BT) ·
`hw/bluetooth.py` (BLE) · `arduino/cat_ranger/cat_ranger.ino` (firmware).

---

## 1. Wireless topology

```mermaid
flowchart LR
  laptop["Laptop (CatRanger)<br/>brain: detect / depth / control"]
  tapo["Tapo C211<br/>eyes (camera)"]
  arduino["Arduino Mega<br/>motors · servo · HC-SR04"]
  laptop -->|"Wi-Fi / RTSP"| tapo
  laptop -->|"Bluetooth: C dx dy rot pan"| arduino
  arduino -->|"Bluetooth: D <cm>"| laptop
```

Compute split: **laptop = brain · Arduino = motors + sensor · Tapo = eyes.** Deep dive:
[`../research/hardware-and-strategy.md`](../research/hardware-and-strategy.md).

---

## 2. Cameras

| Profile | Config | Intrinsics | Distance trust | Role |
|---|---|---|---|---|
| **Go2 1080p** | `configs/camera/go2_1080p.yaml` | `fx=fy=554.3, cx=960, cy=540`, 120° FOV | **Trusted** (contest spec) | what the hidden test set is scored on |
| **Tapo C211** | `configs/camera/tapo_c211.yaml` | `fx=fy=1100` *(placeholder)*, 110° FOV | **Untrusted until calibrated** | live-demo camera |

> **Camera policy (from CLAUDE.md):** develop and report against **Go2 intrinsics**. Any
> metric demoed on the **Tapo** must be re-anchored — select with `--camera go2|tapo`. No
> distortion coefficients were provided; the Go2 profile uses `dist_model: none` (trust
> centered objects), the Tapo profile uses the one-parameter `dist_model: fov`.

### Tapo C211 over Wi-Fi (`hw/tapo.py`)

RTSP frames + optional pan/tilt via `pytapo`. RTSP needs a Tapo **Camera Account** (Tapo
app → Advanced → Camera Account), *not* your cloud login:

```
rtsp://<user>:<pass>@<cam_ip>:554/stream1   # 1080p main
rtsp://<user>:<pass>@<cam_ip>:554/stream2   # ~360p low-latency
```

```bash
python scripts/demo.py --source "rtsp://USER:PASS@CAM_IP:554/stream1" --camera tapo_c211 --show
```

In the console: connect the RTSP URL in **Connections**, pick the `tapo_c211` profile
(re-anchors distance live), and pan/tilt from the **PTZ** controls.

### Calibrate before trusting Tapo distance

`tapo_c211.yaml` ships placeholder `fx/fy` with `needs_calibration: true`, so the console
flags Tapo distances "uncalibrated" until you re-anchor. Photograph an object of known
height `H` at a known distance `Z`, read its pixel height `PX`, then `fx = fy = PX·Z/H`:

```bash
make calibrate H=0.297 Z=2.0 PX=240    # A4 sheet (0.297 m) at 2.0 m, 240 px tall
# equivalently: python scripts/calibrate_camera.py --camera tapo_c211 \
#     --known-height-m 0.297 --distance-m 2.0 --pixel-height-px 240
```

---

## 3. Robot — Arduino over Bluetooth

The laptop talks to the Mega over a Bluetooth module on **Serial1** (USB stays free for
flashing/debug). The same protocol works on every transport — pick the connection that
matches your module:

| Module | Type | Laptop connects via | Command flags |
|---|---|---|---|
| **HC-05 / HC-06** | Bluetooth Classic (SPP) | OS exposes a **serial port** → `hw/serial_bridge.py` as-is | `--connection bt --hw-port /dev/cu.HC-05... --baud 9600` |
| **HM-10 / HM-19 / AT-09** | BLE | GATT via `bleak` → `hw/bluetooth.py` | `--connection ble --ble <address>` |
| USB cable (no BT) | wired | serial | `--connection usb --hw-port /dev/ttyACM0` |

> HC-05 (Classic SPP) is easiest: pair once, point `--hw-port` at the Bluetooth serial
> device — **zero firmware change**. Its factory baud is **9600** (not 115200).

### Wiring the BT module to the Mega

```
module TXD  →  Mega RX1 (D19)
module RXD  ←  Mega TX1 (D18)   THROUGH a divider (Mega TX is 5V; module RX is 3.3V)
module VCC  →  5V               module GND → GND
camera servo signal → D9        (servo +5V on a dedicated rail, GND common)
```

---

## 4. Command protocol (transport-independent)

```mermaid
sequenceDiagram
  participant L as Laptop (control.py → bridge)
  participant A as Arduino firmware
  L->>A: "C <dx> <dy> <rot> <pan>\n"   (4 ints, each -255..255; pan 0..180)
  A->>A: differential mix: left = dy+rot, right = dy-rot
  A->>A: if 0 ≤ lastCM < SAFE_STOP_CM → force stop
  A->>A: servo.write(pan)
  A-->>L: "D <cm>\n"  @ ~20 Hz   (-1 = out of range / no echo)
```

| Direction | Message | Fields |
|---|---|---|
| host → Arduino | `C dx dy rot pan` | `dx` lateral strafe (ignored on 2WD), `dy` forward (+approach), `rot` turn, `pan` servo 0–180 |
| Arduino → host | `D <cm>` @ ~20 Hz | HC-SR04 distance in cm; `-1` = out of range |

A 2WD differential chassis can't strafe, so `dx` is parsed but unused (kept for protocol
symmetry). Swapping to an L298N or AFMotor shield only changes `driveMotors()`/`setMotor()`
— the protocol is identical.

---

## 5. Safety — defended in two independent places

```mermaid
flowchart LR
  subgraph laptop["Laptop"]
    safe["control.py SAFE state<br/>z < safe_distance_m → back off"]
    estop["E-stop (REST/WS, never gated)"]
  end
  subgraph fw["Arduino firmware"]
    hard["if lastCM < SAFE_STOP_CM → motors = 0"]
  end
  safe --> robot["robot"]
  estop --> robot
  hard --> robot
```

1. **Software (controller):** the `SAFE` state backs the robot off when estimated `Z`
   drops below `safe_distance_m`.
2. **Firmware (independent):** `driveMotors()` zeroes both wheels whenever a valid
   HC-SR04 reading is below `SAFE_STOP_CM`, regardless of what the laptop commands.
3. **E-stop:** any console client can latch a stop over REST or WS; it is checked before
   anything else and is never gated by the control token.

The HC-SR04 is also the **demo's killer feature**: the model says "1.84 m" while the
sensor confirms "1.86 m" — the model-vs-sensor honesty the How-Far jury rewards.

---

## 6. Firmware reference (`arduino/cat_ranger/cat_ranger.ino`)

| Define | Default | Meaning |
|---|---|---|
| `LINK` | `Serial1` | command link (use `Serial` for USB) |
| `LINK_BAUD` | `9600` | HC-05/HM-10 factory baud (use `115200` for USB) |
| `DEBUG_USB` | `0` | mirror `D <cm>` to the USB Serial Monitor |
| `SAFE_STOP_CM` | (firmware) | hard motor-stop threshold |
| `PING_PERIOD_MS` | (firmware) | HC-SR04 sampling / report period (~20 Hz) |
| `SERVO_PIN` | `D9` | camera pan servo |

Pins: left motor `L_IN1/L_IN2/L_EN`, right motor `R_IN3/R_IN4/R_EN`, ultrasonic
`TRIG`/`ECHO`, servo `D9`, BT on `Serial1` (TX1=D18, RX1=D19).

See the [install manual §robot](../guides/install-and-test.md) to flash and bring-up the
rig step by step.
