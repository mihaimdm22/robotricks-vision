<!-- /autoplan restore point: /Users/davidmarin/.gstack/projects/mihaimdm22-robotricks-vision/arduino-integration-autoplan-restore-20260607-110042.md -->
# Arduino Integration Plan — tested firmware → 10x bulletproof demo rig

> Goal: make the **tested, working** rig drivable by the CatRanger perception host
> **without touching the proven drive logic**. Today the two literally can't talk —
> the rig speaks single-char `f/g/h/j` and emits no distance; the host sends `C ...`
> and reads `D <cm>`. We bridge that gap on the host (a `CharBridge` adapter) and add
> exactly one thing to the firmware: `D <cm>` telemetry. "Bulletproof" = the tested
> firmware stays the always-working demo; nothing we add can brick it.

## What this serves (and what it explicitly does NOT)
**Does NOT touch any scored metric.** Verified: command smoothness, MAE, FPS, and
continuity are all computed in software from the host `Command` stream / Go2 video
(`catranger/eval/metrics.py`), upstream of the Arduino. Per CLAUDE.md the rig is "a
live-demo prop." So this work buys **live-demo capability**, not points:
- The host can finally drive the proven rig (perception → steer) — new capability.
- The HC-SR04 `D <cm>` unlocks the "1.84 m model vs 1.86 m ultrasonic" GT stage
  moment (TODOS.md line 29-31).
- It frees the hours a firmware rewrite would have burned for the P0 eval report +
  P1 fallback video (the actual graded/insurance deliverables).

## What already exists (do NOT rebuild)
- `catranger/hw/serial_bridge.py` — owns the `C <dx> <dy> <rot> <pan>\n` /
  `D <cm>\n` protocol + normalized→PWM scaling. **Keep as the contract.**
- `catranger/hw/bluetooth.py` — Classic-SPP + BLE links, already defaults BT to
  9600 baud (matches the tested firmware's `Serial1.begin(9600)`).
- `catranger/web/controller.py` — already bulletproof host-side: watchdog timeout,
  e-stop latch, heartbeat, link-loss → DummyBridge degrade, `shutdown()` sends a
  final all-zero command, and FIRMWARE_SAFE_STOP awareness. **Reuse, don't touch
  the state machine.**
- `arduino/cat_ranger/cat_ranger.ino` — the *theoretical* firmware: correct
  protocol, but assumes direct H-bridge + servo on Mega pins that the real rig does
  not use.

## The tested firmware (ground truth of the real rig)
Source: `.context/attachments/cKBqg6/pasted_text_2026-06-07_10-56-26.txt`. Proven on
hardware. Establishes the **real wiring** we must honor:
- Motors: **Adafruit Motor Shield v1 / AFMotor** on **M3 (left)** and **M4 (right)**.
- Ultrasonic HC-SR04: **TRIG=A1, ECHO=A2** (not D30/D31).
- RGB status LED (common-anode): R=53, G=51, B=49. Buzzer: pin 22 @ 2000 Hz.
- LCD: I2C 16x2 @ 0x27. Command link: **Serial1 @ 9600** (HC-05/HM-10 Bluetooth).
- Single-char protocol: `a`=autonomous, `b`=manual, `f`/`g`=nudge fwd/back,
  `h`/`j`=turn 90° left/right.

### What the tested firmware does NOT have (the bulletproofing gap)
1. **Blocking `delay()`** in every motion (`inainte()+delay(400)`, `roteste*90()`
   `delay(250)`). During a turn the loop is frozen: no distance reads, no new
   commands, no safety check. Fatal for smooth perception-follow.
2. **No host-command watchdog.** Autonomous `inainte()` runs forever; if the
   follow host crashes mid-approach the robot keeps driving.
3. **Bang-bang only.** No continuous proportional PWM, so the host P-controller's
   smooth output (the *scored* command-smoothness metric) is thrown away.
4. **No servo pan** (host sends a pan angle; this chassis has none).

## Decision (chosen at premise gate): host CharBridge adapter + additive firmware
**Freeze the tested drive/turn logic. Touch it only additively.** Two pieces:

### Piece 1 — Firmware: additive only (≤10 lines into the TESTED sketch)
We add to the firmware the team actually flashed (not the repo's theoretical one):
- **Emit `D <cm>` on a millis() timer** (~10–20 Hz) on the command link, copied from
  `arduino/cat_ranger/cat_ranger.ino`. Unlocks the host's `read_distance_cm()` and the
  "1.84 m model vs 1.86 m ultrasonic" GT stage moment.
- **Mute / gate the Romanian status strings** (`"Mod autonom PORNIT"`, `"Inainte"`,
  `"Stanga 90"`) on the command link so they don't fragment `D` lines at 9600 baud.
  Keep them only on the USB `Serial` debug port, never on `Serial1`.
- **Map the no-echo sentinel `999 → -1`** in the `D` emit (1 line): the host contract
  treats `-1` as "no reading"; emitting `D 999` would show "9.99 m" on the GT overlay.
- **Nothing else changes** — `inainte/inapoi/roteste*90/getDistanta`, the AFMotor
  M3/M4 mapping, RGB/buzzer/LCD bling, autonomous obstacle stop: all untouched and
  still tested-good. The repo's theoretical `cat_ranger.ino` is retired/renamed so the
  one true firmware is the tested one.

### Piece 2 — Host: a new `CharBridge` (fully unit-testable, zero hardware risk)
A bridge implementing the existing `send`/`read_distance_cm`/`close` contract (the
`_BridgeLike` Protocol the controller already depends on), wired into `open_link`. It
**quantizes** the `Follower`'s continuous Command into the rig's proven char vocabulary.

**Honest constraint (CONFIRMED by Eng review — see below):** the tested chars are
*discrete, time-boxed* — `f`=nudge fwd ~400 ms then auto-stop, `h`/`j`=blocking ~90°
turn, `a`=autonomous-forward-until-obstacle, `b`=manual-stop. **They cannot express a
smooth follow.** Two firmware facts kill the obvious mapping: (1) autonomous `a` drives
**dead straight, ignoring cat bearing** — it cannot follow a cat it doesn't know the
position of; (2) link-loss while in `a` drives the robot **forever** (no firmware
watchdog). So:

**Primary demo (A-plan, bulletproof): autonomous drive + live `D` telemetry overlay.**
The rig runs its tested `a` obstacle-avoidance wander while the host *displays* the cat
track and the "model 1.84 m vs ultrasonic 1.86 m" GT comparison. No quantization, no
juddering, nothing to brick.

**Host-driven follow (B-plan, labeled experimental): coarse stop-and-go via the
self-terminating manual gait** — `b` is home base; fire `h`/`j` only when
`|bearing| > ~45°` (wide deadband, a 90° turn overshoots a 15° error into a limit
cycle); fire one `f` nudge when the cat is roughly ahead and vision-distance > setpoint
and last GT > safe floor. **Never use `a` for follow** (bearing-blind + unsafe on link
loss). Each `f` self-terminates in 400 ms, so a dead link coasts to a stop — inherently
safe. `read_distance_cm()` parses the new `D <cm>` exactly like `ArduinoBridge`.

**CharBridge is an explicitly STATEFUL adapter** (the controller calls `send()` every
frame at ~15 Hz, but the firmware is an edge-triggered automaton): it holds last-mode
(so a steady command emits its char **once**, never per-frame), a per-char debounce
≥ the blocking-primitive duration, an in-flight-suppression timer modeling the firmware
`delay(250/400)` deaf window, and an **injectable clock** (like `Follower`/controller)
so all of it is unit-testable. `close()`/shutdown sends `b` (best-effort stop).

### Host-side housekeeping
- Single-source `safe_stop_cm` (firmware floor) in YAML config; document the one place
  to change it. The host controller already neutralizes forward inside this floor.
- `open_link(connection="char", ...)` selects `CharBridge`; degrade to `DummyBridge`
  if the port is unavailable, like the other transports.

## Tests (host-side, required by quality gates — `make check` must stay green)
- `tests/test_char_bridge.py` (new): quantization table — forward intent → `a`,
  off-bearing → `h`/`j`, stop/safe → `b`; min-interval de-bounce; `read_distance_cm`
  parses `D <cm>` and passes `-1` through as before; `close()` is safe.
- Confirm host tick cadence keeps the link fed without flooding (rate-limit assert).
- Firmware can't run in CI → add a `docs/` bench-test checklist (wheel direction,
  HC-SR04 `D` stream over BT, autonomous stop, char-driven turn) tied to TODOS.md
  line 22-25 so a human verifies on the rig before the demo.

## Checkable done-conditions (Karpathy goal-driven)
1. ✅ `make check` (ruff + mypy + pytest) passes — **225 passed, 1 skipped, 91.6%
   coverage**; 15 new CharBridge unit tests.
2. ⏳ Firmware compiles for Arduino Mega (AFMotor + Wire + LiquidCrystal_I2C) — the
   sketch is the tested one + 3 additive blocks; verify in a teammate's IDE / arduino-cli.
3. ⏳ On the rig (`docs/guides/arduino-bench-check.md`): `python scripts/test_link.py
   --connection char --hw-port <port> --baud 9600` streams `D <cm>`, `--drive` nudges
   both wheels, and cutting the link coasts to a stop within ~400 ms (self-terminating
   `f` nudge — the link-loss failsafe).
4. **(revised per Eng review — the old "smooth continuous motion" goal is
   unachievable over discrete chars and is struck.)** A-plan: autonomous `a` drive runs
   while the host overlay shows the live cat track + "model vs ultrasonic" distance,
   RGB/LCD/buzzer react. B-plan (experimental): FOLLOW produces deliberate stepwise
   face-then-nudge tracking; link loss coasts to a stop within 400 ms.

---
# /autoplan REVIEW — Phase 1 (CEO / Strategy)

**Voices:** Claude subagent (independent strategist). Codex `[unavailable]` — this
account rejects every model (`gpt-5.4/5.1/5/o3...` "not supported with a ChatGPT
account"), so this phase is `[subagent-only]`.

## CEO consensus table
```
CEO DUAL VOICES — CONSENSUS TABLE
  Dimension                            Claude   Codex   Consensus
  ──────────────────────────────────── ──────── ─────── ─────────
  1. Premises valid?                   NO       N/A     single-critical
  2. Right problem to solve?           NO       N/A     single-critical
  3. Scope calibration correct?        NO       N/A     single-critical
  4. Alternatives explored enough?     NO       N/A     flagged
  5. Competitive/time risks covered?   NO       N/A     flagged
  6. 6-month/6-hour trajectory sound?  NO       N/A     flagged
  CONFIRMED = both agree. Single-voice critical = flagged regardless.
```

## CRITICAL premise failure (VERIFIED against code, not opinion)
The plan claims (line ~16) it "touches the scored command-smoothness metric." **False,
and I verified it:** `catranger/eval/metrics.py:187 smoothness(commands: list[Command])`
computes the metric from the host `Follower`'s **Command stream** (per-channel jerk +
rotation oscillation count), inside `run_eval(results, commands, frame_times)` — pure
software, on Go2 video. The Arduino firmware's PWM is **downstream of every scored
metric**. CLAUDE.md line 3: "Scored on the Go2 hidden test set; the Arduino+Tapo rig is
a **live-demo prop**." So a firmware rewrite improves **zero** scored numbers.

## The 6-hour regret (HIGH)
It is 2am; the rewritten firmware compiles but drives wrong — AFMotor M3/M4 swapped (the
tested firmware's own comment warns `daca rotirile ies inversate, schimba 3 cu 4`),
FORWARD/BACKWARD polarity, low-PWM stiction (proportional output that whines but doesn't
move), or the new watchdog zeroing motors because the host tick over 9600-baud BT exceeds
`CMD_TIMEOUT_MS`. Each needs the one physical rig + a re-flash to diagnose. Meanwhile the
P0 eval report and the P1 fallback video never got done. This violates CLAUDE.md's
"always keep a working git state that demos."

## Higher-leverage work the plan ignores (from TODOS.md, VERIFIED)
- **P0**: `make eval` → `outputs/report/report.md` (graded deliverable), demo notebook
  clean, 5-min deck. **P1**: record a **fallback follow video** (line 17, the on-stage
  insurance), capture a distance GT set (line 112, unblocks the headline MAE), Tapo
  intrinsics calibration (line 86, on the rubric).

## The recommended reframe (lower risk, still a real 10x in capability)
The tested firmware currently can NOT be driven by the perception host: it speaks
single-char `f/g/h/j/a/b` and **never emits `D <cm>`**, so the host's `serial_bridge`
(which sends `C ...` and reads `D ...`) cannot talk to it at all. Two **additive,
low-risk** moves make the proven rig fully demo-capable:
1. **Firmware (≤10 lines, additive only):** add a `D <cm>` telemetry emit on a millis()
   timer (copied from `arduino/cat_ranger/cat_ranger.ino`) and mute the Romanian status
   chatter on the command link. Delivers the "1.84 m model vs 1.86 m ultrasonic" GT stage
   moment (TODOS) without touching the tested drive/turn logic.
2. **Host (new `CharBridge`, fully unit-testable):** an adapter implementing the existing
   `send`/`read_distance_cm`/`close` contract (the `_BridgeLike` Protocol the controller
   already depends on) that quantizes the `Follower`'s smooth Command into the rig's proven
   chars. Zero firmware-drive risk; the already-bulletproof host state machine is unchanged.

## NOT in scope (deferred)
- New PCB / servo pan mount (host sends pan; chassis has none — documented no-op).
- Rewriting the host control state machine (already bulletproof).
- Any change to the scored perception core (`detect/depth/distance/track/pipeline`).
- Autonomous-mode path-planning beyond the tested obstacle back-up behavior.

---
# /autoplan REVIEW — Phase 3 (Eng) — `[subagent-only]`, Codex unavailable

## Eng consensus table
```
ENG DUAL VOICES — CONSENSUS TABLE
  Dimension                            Claude   Codex   Consensus
  ──────────────────────────────────── ──────── ─────── ─────────
  1. Architecture sound?               YES      N/A     bridge contract fits cleanly
  2. Test coverage sufficient?         YES*     N/A     *with the 7 unit tests below
  3. Performance risks addressed?      YES      N/A     9600 baud fine; debounce is the gate
  4. Security/safety threats covered?  PARTIAL  N/A     link-loss-mid-`a` is critical
  5. Error paths handled?              YES      N/A     parser tolerates gappy `D`
  6. Deployment risk manageable?       YES      N/A     additive firmware, bench checklist
```

## Findings (severity → fix)
- **CRITICAL — `a` is bearing-blind:** `ruleazaAutonom()` drives dead straight on the
  HC-SR04 only; it has no idea where the cat is. → Never map follow to `a`.
- **CRITICAL — link-loss mid-`a` drives forever** (no firmware watchdog on the char
  path). → Use the self-terminating `b`+`f` gait; `f` stops itself in 400 ms, so a dead
  link coasts to a halt. `a` only as a standalone, human-supervised demo mode.
- **HIGH — 90° turn vs ~0.3 rad rotation = limit cycle:** wide ~45° turn-deadband +
  strong debounce; accept stepwise, not smooth.
- **HIGH — blocking `delay()` deaf window:** host `in_flight_until` timer suppresses
  sends during the firmware's 250/400 ms blocking primitive.
- **MEDIUM — `D 999` no-echo:** map `999 → -1` in firmware (1 line).
- **MEDIUM — three distance floors** (vision 0.4 m / host 20 cm / firmware 30 cm) can
  disagree; document, don't claim a single source of truth.
- **MEDIUM — stateful adapter:** hold last-mode (emit char once, not per-frame),
  injectable clock; unit-test transitions.

## Required unit tests (gate in `make check`)
1. Quantization table (fwd→`f`, big +bearing→`j`, big −bearing→`h`, small bearing→none,
   SAFE/v_fwd≤0→`b`); 2. steady command emits its char **once** not per-frame; 3.
debounce ≥ primitive duration (injected clock); 4. in-flight suppression after a turn;
5. `read_distance_cm` parses `D`, passes `-1`, `None` on partial, skips non-`D`; 6.
`close()` sends `b`, exception-safe; 7. `open_link("char", ...)` selects CharBridge,
degrades to DummyBridge. Bench-only: 90° calibration, beam-sees-cat-vs-wall, real BT
`D` cadence, motor direction, follow feel.

# /autoplan REVIEW — Phase 3.5 (DX) — proportional inline pass
Surface is small and operator-facing: one new `--connection char` selector + a bench
checklist + firmware flashing. TTHW for a teammate: flash the (already-flashed) sketch →
`scripts/test_link.py --connection bt --hw-port <port> --baud 9600` should stream `D`
and accept a char. Findings: (1) name the transport `char` consistently with existing
`usb`/`bt`/`ble`/`dummy` in `open_link` — guessable, no new mental model; (2) the bench
checklist IS the DX deliverable here — a teammate must be able to verify the rig in
<5 min without reading code; (3) error path: if `D` never arrives, `read_distance_cm`
returns `None` and the overlay should show "GT: —" not crash (already true). No new docs
site, no API. DX is adequate with the checklist; nothing gold-plated.

---
## Decision Audit Trail
<!-- AUTONOMOUS DECISION LOG -->

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 1 | CEO | Codex voice unavailable → proceed subagent-only | Mechanical | P6 bias-to-action | Account rejects all codex models; degradation matrix → `[subagent-only]` | Blocking on codex |
| 2 | CEO | Verify "smoothness scored on firmware" claim against eval code | Mechanical | P1 completeness | `metrics.py:187` proves metric is on host Command stream, not Arduino | Taking plan at its word |
| 3 | CEO | Surface firmware-rewrite-vs-adapter as PREMISE GATE (not auto-decided) | **Premise gate** | autoplan rule | Premises require human judgment; the rewrite's whole justification is falsified | Auto-deciding the pivot |
| 4 | CEO | User chose adapter path (A) at premise gate | User decision | — | Lowest risk, real capability gain, frees time for P0/P1 | Rewrite (B), hybrid (C) |
| 5 | Eng | Demote `a` from follow mapping; never use for follow | Mechanical | P1+P5 | `ruleazaAutonom` drives bearing-blind straight; link-loss runs forever | Using `a` as "approach" |
| 6 | Eng | Promote autonomous+telemetry to A-plan; char-follow B-plan/experimental | Mechanical | P1 completeness | Discrete chars can't smoothly follow; honest demo framing is bulletproof | Promising smooth follow |
| 7 | Eng | Strike done-condition #4 "smooth continuous motion" | Mechanical | P5 explicit | Unachievable over 90°/400ms primitives — limit cycle | Keeping a false goal |
| 8 | Eng | Map firmware `999 → -1` in `D` emit (1 line) | Mechanical | P1 | Host contract uses `-1` for no-echo; else GT shows "9.99 m" | Emitting raw 999 |
| 9 | Eng | CharBridge must be stateful + injectable clock (no per-frame spam) | Mechanical | P5 explicit | `send()` called ~15 Hz vs edge-triggered firmware automaton | Stateless send() |
