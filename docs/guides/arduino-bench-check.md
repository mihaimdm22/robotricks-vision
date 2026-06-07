# Arduino rig — pre-demo bench check (5 minutes)

The CharBridge adapter + firmware telemetry are unit-tested on the laptop, but the
*physical* behaviour (motor direction, 90-degree calibration, whether the ultrasonic
beam sees the cat) can only be confirmed on the rig. Run this before the demo.

> Firmware: `arduino/cat_ranger/cat_ranger.ino` (Adafruit Motor Shield v1 rig, single
> char protocol). Host link: `--connection char`. Baud: 9600 (HC-05 / HM-10).

## 0. Flash + pair
- [ ] Open `arduino/cat_ranger/cat_ranger.ino` in the Arduino IDE, install libraries
      `AFMotor`, `LiquidCrystal_I2C`, upload to the Mega. LCD shows `Gata`.
- [ ] Pair the HC-05/HM-10 over Bluetooth (PIN 1234/0000). Note the port
      (`/dev/cu.HC-05-XXXX`).

## 1. Link + ground-truth telemetry (no motion)
```
python scripts/test_link.py --connection char --hw-port /dev/cu.HC-05-XXXX --baud 9600
```
- [ ] Console prints a non-`DummyBridge` link and a live `distance=NN cm` that tracks
      your hand in front of the HC-SR04. (This is the "model 1.84 m vs ultrasonic
      1.86 m" stage feed.)
- [ ] Wave your hand away past ~4 m / cover the sensor: distance shows `--` (the
      firmware's `999` no-echo maps to `-1`, surfaced as no reading). It must NEVER
      show `9.99 m`.

## 2. Drive primitives (wheels WILL move — clear the bench)
```
python scripts/test_link.py --connection char --hw-port /dev/cu.HC-05-XXXX --baud 9600 --drive
```
- [ ] Forward nudge drives BOTH wheels forward briefly, then auto-stops (~400 ms).
      If a wheel runs backward, swap `AF_DCMotor(3)`/`(4)` in the firmware.
- [ ] On the rig directly (phone terminal over BT): send `b` then `h` and `j` —
      confirm ~90-degree turns. If over/under-rotating, tune `TIMP_ROTIRE_90`.
- [ ] If a turn spins the wrong way, swap `FORWARD`/`BACKWARD` in `roteste*90()`.

## 3. Safety
- [ ] Hold an object ~15 cm in front during a forward nudge: the host `CharBridge`
      refuses to nudge when the last reading is inside `safe_stop_cm` (20 cm), so the
      rig stays put. NOTE the firmware's 30 cm `PRAG_OBSTACOL` stop + red RGB are
      autonomous-mode only — manual `case 'f'` does not distance-check, so on the
      follow path the host gate is the obstacle protection, not the firmware.
- [ ] Pull the Bluetooth dongle / kill the host mid-drive: the rig coasts to a stop
      within ~400 ms (the `f` nudge is self-terminating — this is the link-loss
      failsafe). **Do NOT leave it in autonomous `a` for the follow demo** — `a` is
      bearing-blind and has no host watchdog.

## 4. Demo framing (set expectations)
- **A-plan (bulletproof):** run autonomous `a` for the "robot avoids obstacles +
  RGB/buzzer/LCD react" wow moment, with the host overlay showing the live cat track
  and the model-vs-ultrasonic distance comparison.
- **B-plan (experimental):** host FOLLOW mode via `--connection char` produces coarse,
  deliberate face-then-nudge stepwise tracking. It is honest, safe, and a bonus — not
  the headline. Discrete 90-degree turns cannot smoothly track; do not promise that.
