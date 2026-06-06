/*
 * cat_ranger.ino  --  CatRanger chassis firmware (Arduino Mega 2560)
 * ---------------------------------------------------------------------------
 * Drives a 2-wheel-drive chassis, a camera pan servo, and reports HC-SR04
 * ultrasonic distance back to the host. The laptop does all the perception;
 * this sketch just actuates and reports ground-truth distance.
 *
 * CONNECTIVITY -- WIRELESS (Bluetooth) or wired (USB)
 * --------------------------------------------------------------------------
 * The host (laptop running CatRanger) connects over BLUETOOTH. A transparent
 * UART Bluetooth module bridges the wireless link to the Mega's hardware serial,
 * so this firmware just talks to a Stream -- it does not care whether the bytes
 * arrive over USB, HC-05 (Bluetooth Classic / SPP) or HM-10 (BLE). Pick the link:
 *
 *     #define LINK      Serial1     // <-- Bluetooth module on Serial1 (default)
 *     #define LINK_BAUD 9600        // HC-05 / HM-10 factory baud (NOT 115200)
 *   ( for a wired USB cable instead:  #define LINK Serial  /  LINK_BAUD 115200 )
 *
 * Wire the module to Serial1 (keeps USB free for flashing + Serial Monitor debug):
 *     module TXD  -> Mega RX1 (D19)
 *     module RXD  <- Mega TX1 (D18)  THROUGH a divider  (Mega TX is 5V; module RX
 *                                    wants ~3.3V: e.g. 1k in series + 2k to GND)
 *     module VCC  -> 5V        module GND -> GND
 *   HC-05 (Classic/SPP): host sees a serial port (/dev/cu.HC-05..., /dev/rfcomm0)
 *                        -> CatRanger `--connection bt --hw-port <that port>`.
 *   HM-10 (BLE)        : host talks GATT -> CatRanger `--connection ble --ble <addr>`.
 *   Both are transparent UART, so THIS SKETCH IS THE SAME for either module.
 *
 * SERIAL PROTOCOL (must match catranger/hw/serial_bridge.py exactly)
 * ------------------------------------------------------------------
 *   IN  (host -> Arduino):  "C <dx> <dy> <rot> <pan>\n"   (4 ints)
 *        dx   : lateral strafe   [-255..255]  (2WD chassis ignores this; see note)
 *        dy   : FORWARD drive     [-255..255]  (+ = forward / approach)
 *        rot  : yaw / turn        [-255..255]  (+ = turn right / clockwise)
 *        pan  : camera servo angle [0..180]    (90 = centered)
 *   OUT (Arduino -> host):  "D <cm>\n"  at ~20 Hz   (-1 = no echo / out of range)
 *
 * Differential mix:  left = dy + rot,  right = dy - rot   (then clamped to PWM).
 *   pure dy  -> both wheels forward      (drive straight)
 *   pure rot -> wheels oppose            (turn in place)
 * A 2WD differential chassis cannot strafe, so `dx` is parsed but unused here.
 *
 * WIRING / PIN MAP  (direct H-bridge control -- NO motor-shield library needed)
 * ----------------------------------------------------------------------------
 *   LEFT  motor : IN1 = D22, IN2 = D23, ENA(PWM) = D2
 *   RIGHT motor : IN3 = D24, IN4 = D25, ENB(PWM) = D3
 *   CAMERA servo: signal = D9   (servo +5V to a dedicated 5V rail, GND common)
 *   HC-SR04     : TRIG = D30,  ECHO = D31
 *   BT module   : on Serial1 (TX1=D18, RX1=D19) -- see CONNECTIVITY above
 *
 *   Power: motors from a SEPARATE battery pack into the H-bridge Vmotor; tie all
 *   GNDs together. Do NOT run motors off the Arduino 5V regulator. HC-SR04 ECHO is
 *   5V -- safe on a 5V Mega input pin directly.
 *
 * SAFE-DISTANCE NOTE
 * ------------------
 * If the measured distance is below SAFE_STOP_CM (and valid), the chassis is forced
 * to STOP regardless of the incoming forward command -- last line of defense so the
 * robot never rams the cat / a wall. The host follower should back off too.
 *
 * If you have a classic Adafruit Motor Shield v1, swap the H-bridge calls in
 * driveMotors() for AFMotor. The protocol and the rest stay identical.
 */

#include <Servo.h>

// ---- link selection (Bluetooth by default; see CONNECTIVITY) --------------
#define LINK       Serial1   // Bluetooth module on Serial1; use `Serial` for USB
#define LINK_BAUD  9600      // HC-05 / HM-10 factory baud (use 115200 for USB)
#define DEBUG_USB  0         // 1 = also mirror "D <cm>" to the USB Serial Monitor

// ---- pin map -------------------------------------------------------------
const int L_IN1 = 22, L_IN2 = 23, L_EN = 2;   // left motor  (EN must be PWM)
const int R_IN3 = 24, R_IN4 = 25, R_EN = 3;   // right motor (EN must be PWM)
const int SERVO_PIN = 9;                       // camera pan servo
const int TRIG = 30, ECHO = 31;                // HC-SR04

// ---- tuning --------------------------------------------------------------
const int  PWM_MAX        = 255;   // analogWrite ceiling
const int  SAFE_STOP_CM   = 20;    // hard stop if a valid reading is closer
const unsigned long PING_PERIOD_MS = 50;       // ~20 Hz distance reports
const unsigned long ECHO_TIMEOUT_US = 30000;   // ~5 m round trip

Servo pan;
int   lastPan = 90;     // remembered servo angle (centered until told otherwise)
long  lastCM  = -1;     // most recent ultrasonic reading (cm), -1 = invalid

// Read the HC-SR04. Returns distance in cm, or -1 on no echo / timeout.
long readCM() {
  digitalWrite(TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long us = pulseIn(ECHO, HIGH, ECHO_TIMEOUT_US);
  if (us == 0) return -1;          // no echo within timeout
  return us / 58;                  // microseconds -> centimeters
}

// Drive one motor from a signed speed (-PWM_MAX..PWM_MAX).
void setMotor(int in_a, int in_b, int en, int speed) {
  bool fwd = speed >= 0;
  int  mag = abs(speed);
  if (mag > PWM_MAX) mag = PWM_MAX;
  digitalWrite(in_a, fwd ? HIGH : LOW);
  digitalWrite(in_b, fwd ? LOW  : HIGH);
  analogWrite(en, mag);
}

// Differential mix of forward(dy) + turn(rot) into the two wheels.
// dx is accepted for protocol symmetry but unused on a 2WD chassis.
void driveMotors(int dx, int dy, int rot) {
  (void)dx;                        // no strafe on differential drive
  int left  = dy + rot;
  int right = dy - rot;
  // Safety: a valid, too-close reading forces a full stop.
  if (lastCM >= 0 && lastCM < SAFE_STOP_CM) {
    left = 0;
    right = 0;
  }
  setMotor(L_IN1, L_IN2, L_EN, left);
  setMotor(R_IN3, R_IN4, R_EN, right);
}

void stopMotors() {
  analogWrite(L_EN, 0);
  analogWrite(R_EN, 0);
}

void setup() {
  LINK.begin(LINK_BAUD);          // the Bluetooth (or USB) command link
#if DEBUG_USB
  if (&LINK != &Serial) Serial.begin(115200);
#endif
  pinMode(L_IN1, OUTPUT); pinMode(L_IN2, OUTPUT); pinMode(L_EN, OUTPUT);
  pinMode(R_IN3, OUTPUT); pinMode(R_IN4, OUTPUT); pinMode(R_EN, OUTPUT);
  pinMode(TRIG, OUTPUT);  pinMode(ECHO, INPUT);
  pan.attach(SERVO_PIN);
  pan.write(lastPan);     // center the camera
  stopMotors();
}

void loop() {
  // ---- IN: parse "C dx dy rot pan" -------------------------------------
  if (LINK.available()) {
    String s = LINK.readStringUntil('\n');
    int dx, dy, rot, p;
    if (sscanf(s.c_str(), "C %d %d %d %d", &dx, &dy, &rot, &p) == 4) {
      lastPan = constrain(p, 0, 180);
      pan.write(lastPan);
      driveMotors(dx, dy, rot);
    }
  }

  // ---- OUT: "D <cm>" at ~20 Hz -----------------------------------------
  static unsigned long t = 0;
  unsigned long now = millis();
  if (now - t >= PING_PERIOD_MS) {
    t = now;
    lastCM = readCM();            // update for both reporting and the safety stop
    LINK.print("D ");
    LINK.println(lastCM);
#if DEBUG_USB
    if (&LINK != &Serial) { Serial.print("D "); Serial.println(lastCM); }
#endif
  }
}
