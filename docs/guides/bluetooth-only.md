# Bluetooth-only operation (move the robot without USB)

Use USB only to **flash firmware** and **bench-test on the desk**. When the robot
rolls on the floor, power it separately and control it from the laptop over
HC-05/HC-06 at **9600 baud**.

## 1. Power (most common mistake)

Unplugging the USB cable from the Mac **cuts power** to the Mega unless you have a
**barrel jack or battery** feeding the board. Bluetooth cannot work on a dead Arduino.

- Flash with USB connected.
- Before moving: plug in **7–12 V barrel** or battery pack, confirm the Mega runs
  (LCD shows *Gata*, HC-06 LED on).
- Then unplug USB **from the laptop** (power stays on from the external supply).

## 2. Wiring (HC-06 ↔ Mega Serial1)

| HC-06 pin | Mega pin | Notes |
|-----------|----------|--------|
| VCC | 5V | |
| GND | GND | common ground with Mega |
| TXD | **19 (RX1)** | module TX → Mega receive |
| RXD | **18 (TX1)** | module RX ← Mega transmit; **use a 2:1 divider** (e.g. 1kΩ + 2kΩ) because HC-06 is 3.3 V logic |
| KEY | GND | AT mode off; transparent UART |

If your build wired the module to **D0/D1 (USB Serial)** instead, edit
`arduino/cat_ranger/link_config.h`:

```cpp
// #define CATRANGER_BT_LINK Serial1
#define CATRANGER_BT_LINK Serial
#define CATRANGER_POLL_USB 0   // required — do not use USB and BT on the same UART
```

Re-flash, then never keep the USB cable attached to a PC while driving over BT.

## 3. Flash firmware

1. Open `arduino/cat_ranger/cat_ranger.ino` in Arduino IDE (includes `link_config.h`).
2. Board: **Arduino Mega 2560**.
3. Upload over USB.
4. Optional: Serial Monitor @ 9600 on USB — you should see `D <cm>` and debug lines.

## 4. Prove the Bluetooth link (before the console)

1. Power Mega from **external supply** (USB unplugged from Mac).
2. macOS **System Settings → Bluetooth** → connect **HC-06** (solid red on module =
   RF link up).
3. Run:

```bash
python scripts/verify_bt_link.py --port /dev/cu.HC-06 --baud 9600
```

**Pass:** `CR BT ready` once, then `D <cm>` lines ~10 Hz. Wave a hand — values change.

**Fail (0 bytes on BT alone):** On **macOS + HC-06**, the port often opens but **RX stays
silent** even while **TX reaches the robot** (phone Serial Terminal still works both
ways). This is a known macOS Classic Bluetooth quirk, not bad wiring.

**macOS hybrid fix (Mega USB plugged into the same Mac for power):** keep USB connected
for power and sonar, command over Bluetooth:

```bash
python scripts/verify_bt_link.py \
  --port /dev/cu.HC-06 --baud 9600 \
  --telemetry-port /dev/cu.usbserial-10
```

The web console **auto-enables hybrid** on macOS when you connect **bt** and a USB Mega
port is present: drive commands on HC-06, `D <cm>` sonar on USB.

**Fail (0 bytes, no USB):** wiring/baud/power, or replace HC-06 with **HM-10 BLE**
(`ble` in the console).

## 5. Console workflow

**HC-06 allows one active link.** If the phone Serial Bluetooth Terminal is connected,
the Mac will open `/dev/cu.HC-06` but receive **0 bytes** (even though the phone shows
`D129`). Close the phone app, disconnect phone ↔ HC-06, then on the Mac: System
Settings → Bluetooth → disconnect and reconnect HC-06 before using the console.

1. `catranger serve` (or your usual start).
2. **Connections → Scan** → pick `/dev/cu.HC-06`, transport **bt**, baud **9600**.
3. **Connect** — banner must show **LIVE** (link verified), not *PORT OPEN — NO MEGA DATA*.
4. Drive from the pad; distance updates in the telemetry panel.

Do **not** connect USB and BT at the same time for control — one link at a time.

## 6. Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| BT connects in macOS but console shows no data | HC-06 not wired to Serial1, or Mega unpowered |
| Stale distance (e.g. old 124 cm) | Previous USB session; disconnect and reconnect BT after verify fails |
| HC-06 slow red blink | Not paired/connected in macOS — click **Connect** in Bluetooth settings |
| USB works, BT silent at all bauds | TX/RX swapped, missing divider on RXD, or module on wrong Mega pins |
| Robot dead after unplugging USB | No external power — add barrel/battery |

## Related

- [install-and-test.md](install-and-test.md) — full bring-up
- [hardware.md](../architecture/hardware.md) — wiring diagram
- `scripts/test_link.py` — servo/distance bench test (add `--drive` for wheel pulse)
