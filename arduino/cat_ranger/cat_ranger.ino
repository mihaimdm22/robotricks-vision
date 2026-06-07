/*
 * cat_ranger.ino  --  CatRanger chassis firmware (Arduino MEGA + Adafruit Motor Shield v1)
 * ===========================================================================
 * THIS IS THE TESTED, ON-THE-RIG firmware. The drive/turn/sensor/LCD/RGB/buzzer
 * logic below is exactly what the team flashed and verified on the physical robot.
 * Do NOT rewrite it. Only SURGICAL, ADDITIVE changes were layered on top so the
 * CatRanger laptop host can read ground-truth distance and drive the rig through its
 * proven single-char command set (see catranger/hw/char_bridge.py):
 *
 *   (1) D-telemetry: emit "D <cm>\n" on Serial1 on a millis() timer (~10 Hz) so the
 *       host's read_distance_cm() gets the HC-SR04 ground truth (the "model 1.84 m
 *       vs ultrasonic 1.86 m" stage moment). No-echo (999) is mapped to -1 to match
 *       the host contract (serial_bridge.py treats -1 as "no reading").
 *   (2) Quiet command link: status acks go to the USB Serial (debug) ONLY, never to
 *       Serial1 (the Bluetooth command link), so they cannot fragment "D <cm>" lines.
 *   (3) Boot into manual mode (mod='b') instead of idle, so the host's drive commands
 *       work even if its bootstrap 'b' is dropped on the wireless link.
 *   (4) Nothing else changed. inainte/inapoi/roteste*90/getDistanta, the AFMotor
 *       M3/M4 mapping, the 30 cm autonomous obstacle stop, RGB/buzzer/LCD: untouched.
 *
 * WIRING (the REAL rig)
 * ---------------------
 *   Motors      : Adafruit Motor Shield v1 -> M3 = LEFT, M4 = RIGHT
 *                 (if a turn comes out reversed, swap the 3 and 4 in AF_DCMotor below)
 *   HC-SR04     : TRIG = A1, ECHO = A2
 *   RGB LED     : R = 53, G = 51, B = 49
 *                 Default build: COMMON CATHODE (HIGH = on). If your module is common
 *                 anode (LOW = on), set RGB_COMMON_ANODE to 1 below.
 *   Buzzer      : pin 22 (fixed 2000 Hz)
 *   LCD         : I2C 16x2 @ 0x27
 *   Command link: Serial1 (TX1=D18, RX1=D19) -> HC-05 / HM-10 Bluetooth @ 9600 baud
 *                 Serial (USB) @ 9600 — same single-char protocol when plugged in direct
 *
 * SINGLE-CHAR PROTOCOL (host -> Arduino, on Serial1)
 * -------------------------------------------------
 *   'a' = autonomous mode (drive forward, auto-stop at 30 cm obstacle)  [STANDALONE
 *         demo only -- it is bearing-blind and will NOT follow a cat; the host must
 *         not use it for follow, see char_bridge.py]
 *   'b' = manual mode / stop
 *   'f' = nudge forward ~400 ms then auto-stop      (manual mode)
 *   'g' = nudge back    ~400 ms then auto-stop      (manual mode)
 *   'h' = turn left  ~90 deg                         (manual mode / obstacle unblock)
 *   'j' = turn right ~90 deg                         (manual mode / obstacle unblock)
 *   'c' = toggle buzzer proximity beeps (metal-detector style)
 *   'v' = toggle RGB distance indicator
 *   'k' = toggle LCD distance display
 *   '8' = enable all peripherals (buzzer + RGB + LCD)
 *   '9' = quiet all peripherals
 * Host -> Arduino line (USB or Serial1):  "I<id>\n"  e.g. I3/7  or I-  (LCD cat id)
 * Arduino -> host:  "D <cm>\n" at ~10 Hz   (-1 = no echo / out of range)
 */

#include <AFMotor.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// Motoare pe M3 si M4 (daca rotirile ies inversate, schimba 3 cu 4)
AF_DCMotor motorStanga(3);
AF_DCMotor motorDreapta(4);

// RGB: most 4-pin modules are common CATHODE (HIGH = on). Set to 1 for common ANODE.
#ifndef RGB_COMMON_ANODE
#define RGB_COMMON_ANODE 0
#endif

#define RED 53
#define GREEN 51
#define BLUE 49

// Buzzer
#define BUZZER 22
#define FRECV_BIP 2000         // frecventa fixa a bipului

// Senzor ultrasunete
#define TRIG A1
#define ECHO A2

// LCD
LiquidCrystal_I2C lcd(0x27, 16, 2);

// Parametri ajustabili
#define VITEZA_NORMALA 100     // viteza fixa
#define VITEZA_ROTIRE  150     // viteza la rotiri
#define PRAG_OBSTACOL  30      // cm - cand se opreste
#define TIMP_ROTIRE_90 250     // ms - calibreaza pentru 90 grade
#define TIMP_MERS_SCURT 400    // ms - "putin inainte/inapoi"
#define LCD_INTERVAL   250     // ms - update LCD de 4 ori/sec
#define D_INTERVAL     100     // ms - emit "D <cm>" to the host ~10x/sec  (ADDITIVE)
#define RANGE_MAX_CM   200     // HC-SR04 working band (2 m)
#define BUZZER_FAR_CM  180     // metal-detector beeps from here down
#define SONAR_HOLD_MS  1200    // hold last valid cm for RGB/buzzer/LCD

char mod = 0; // 0=idle, 'a'=autonom, 'b'=manual
bool blocatDeObstacol = false;
bool buzzerOn = true;
bool rgbOn = true;
bool lcdOn = true;
char catIdStr[17] = "";       // from host "I3/7" or "I-"

// Timing non-blocking
unsigned long ultimaActualizareLCD = 0;
unsigned long ultimulBip = 0;
unsigned long ultimaTelemetrie = 0;    // ADDITIVE: last "D <cm>" emit
unsigned long ultimaCitireValida = 0;
long distantaCurenta = 999;
long distantaValida = 999;

// Last RGB mix (hold during no-echo so the LED does not flash white/off).
bool rgbLastR = false;
bool rgbLastG = false;
bool rgbLastB = true;

// ---------- FUNCTII RGB ----------
void setRGB(bool r, bool g, bool b) {
#if RGB_COMMON_ANODE
  digitalWrite(RED, r ? LOW : HIGH);
  digitalWrite(GREEN, g ? LOW : HIGH);
  digitalWrite(BLUE, b ? LOW : HIGH);
#else
  digitalWrite(RED, r ? HIGH : LOW);
  digitalWrite(GREEN, g ? HIGH : LOW);
  digitalWrite(BLUE, b ? HIGH : LOW);
#endif
}

void setRGBOff() {
#if RGB_COMMON_ANODE
  setRGB(0, 0, 0);
#else
  digitalWrite(RED, LOW);
  digitalWrite(GREEN, LOW);
  digitalWrite(BLUE, LOW);
#endif
}

// ---------- SENZOR ----------
long getDistanta() {
  digitalWrite(TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long durata = pulseIn(ECHO, HIGH, 25000); // ~4 m max; 2 m needs ~12 ms
  if (durata == 0) return 999; // nimic detectat
  long cm = (long)(durata * 0.034 / 2);
  if (cm > RANGE_MAX_CM) return 999;
  return cm;
}

// Hold last valid reading so RGB/buzzer/LCD don't flicker on occasional no-echo.
long distantaPentruFeedback(long d) {
  if (d >= 999 || d < 0) {
    if (millis() - ultimaCitireValida < SONAR_HOLD_MS && distantaValida < 999) {
      return distantaValida;
    }
    return 999;
  }
  distantaValida = d;
  ultimaCitireValida = millis();
  return d;
}

// ---------- TELEMETRIE host (ADDITIVE) ----------
// Emit "D <cm>\n" on the Bluetooth command link for the laptop host. Maps the
// 999 "no echo" sentinel to -1 so it matches catranger/hw/serial_bridge.py.
// Refreshes the reading itself, on the timer, only when NOT in autonomous mode
// (autonomous already pings every loop). This keeps manual/idle mode from blocking
// the command loop on pulseIn() more than ~10x/sec.
void trimiteTelemetrie() {
  if (millis() - ultimaTelemetrie >= D_INTERVAL) {
    ultimaTelemetrie = millis();
    if (mod != 'a') distantaCurenta = getDistanta();
    long out = (distantaCurenta >= 999) ? -1 : distantaCurenta;
    Serial1.print("D ");
    Serial1.println(out);
    // USB host (CharBridge over /dev/cu.usbserial-*) reads Serial, not Serial1.
    Serial.print("D ");
    Serial.println(out);
  }
}

// ---------- MOTOARE ----------
void inainte(int viteza) {
  motorStanga.setSpeed(viteza);
  motorDreapta.setSpeed(viteza);
  motorStanga.run(FORWARD);
  motorDreapta.run(FORWARD);
}

void inapoi(int viteza) {
  motorStanga.setSpeed(viteza);
  motorDreapta.setSpeed(viteza);
  motorStanga.run(BACKWARD);
  motorDreapta.run(BACKWARD);
}

void stopMotoare() {
  motorStanga.run(RELEASE);
  motorDreapta.run(RELEASE);
}

void rotesteStanga90() {
  motorStanga.setSpeed(VITEZA_ROTIRE);
  motorDreapta.setSpeed(VITEZA_ROTIRE);
  motorStanga.run(BACKWARD);
  motorDreapta.run(FORWARD);
  delay(TIMP_ROTIRE_90);
  stopMotoare();
}

void rotesteDreapta90() {
  motorStanga.setSpeed(VITEZA_ROTIRE);
  motorDreapta.setSpeed(VITEZA_ROTIRE);
  motorStanga.run(FORWARD);
  motorDreapta.run(BACKWARD);
  delay(TIMP_ROTIRE_90);
  stopMotoare();
}

// ---------- RGB pe 5 intervale (0–200 cm) ----------
void culoareDistanta(long d) {
  if (d >= 999) {
    setRGB(rgbLastR, rgbLastG, rgbLastB);
    return;
  }
  bool r = false, g = false, b = false;
  if (d <= 40) {
    r = true;                               // rosu - foarte aproape
  } else if (d <= 80) {
    r = g = true;                           // galben
  } else if (d <= 120) {
    g = true;                               // verde
  } else if (d <= 160) {
    g = b = true;                           // cyan
  } else {
    b = true;                               // albastru - departe (<=200)
  }
  rgbLastR = r;
  rgbLastG = g;
  rgbLastB = b;
  setRGB(r, g, b);
}

// ---------- BUZZER tip detector de metale (2 m band) ----------
void bipDetector(long d) {
  if (d >= 999 || d > BUZZER_FAR_CM) {
    noTone(BUZZER);
    return;
  }
  int interval = map(constrain(d, PRAG_OBSTACOL, BUZZER_FAR_CM), BUZZER_FAR_CM, PRAG_OBSTACOL, 900, 70);

  if (millis() - ultimulBip >= (unsigned long)interval) {
    ultimulBip = millis();
    tone(BUZZER, FRECV_BIP, 90);
  }
}

// ---------- LCD update throttled ----------
void actualizeazaLCD(long d) {
  if (!lcdOn) return;
  if (millis() - ultimaActualizareLCD >= LCD_INTERVAL) {
    ultimaActualizareLCD = millis();
    lcd.setCursor(0, 0);
    if (blocatDeObstacol) {
      lcd.print("OBSTACOL! h/j   ");
    } else if (catIdStr[0] != '\0' && catIdStr[0] != '-') {
      lcd.print("Cat id:");
      lcd.print(catIdStr);
    } else if (mod == 'b') {
      lcd.print("Manual 0-200cm ");
    } else if (mod == 'a') {
      lcd.print("Auto 0-200cm   ");
    } else {
      lcd.print("Dist 0-200cm   ");
    }
    lcd.setCursor(0, 1);
    if (d >= 999) {
      lcd.print("--- / 200cm   ");
    } else {
      lcd.print(d);
      lcd.print(" cm / 200cm  ");
    }
  }
}

// ---------- Peripherals (RGB + buzzer + LCD) from ultrasonic reading ----------
void feedbackPeriferice(long d) {
  if (rgbOn) {
    culoareDistanta(d);
  } else {
    setRGBOff();
  }
  if (buzzerOn) {
    bipDetector(d);
  } else {
    noTone(BUZZER);
  }
  actualizeazaLCD(d);
}

// ---------- MOD AUTONOM ----------
void ruleazaAutonom() {
  distantaCurenta = getDistanta();
  long dFeed = distantaPentruFeedback(distantaCurenta);

  feedbackPeriferice(dFeed);

  if (distantaCurenta <= PRAG_OBSTACOL) {
    blocatDeObstacol = true;
    stopMotoare();
  } else {
    blocatDeObstacol = false;
    inainte(VITEZA_NORMALA);
  }
}

void setup() {
  Serial.begin(9600);
  Serial1.begin(9600);

  stopMotoare();

  pinMode(RED, OUTPUT);
  pinMode(GREEN, OUTPUT);
  pinMode(BLUE, OUTPUT);
  setRGBOff();

  pinMode(BUZZER, OUTPUT);
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);

  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Gata");

  // ADDITIVE: boot straight into manual mode so the host's single-char drive commands
  // (f/g/h/j) are honoured immediately. If CharBridge's bootstrap 'b' is ever dropped
  // on the 9600 Bluetooth link, the rig still starts in the mode the host assumes,
  // instead of being stuck in idle (mod=0) silently ignoring every move command.
  mod = 'b';
}

// Shared by Serial (USB) and Serial1 (Bluetooth) — same single-char protocol.
void proceseazaComanda(char c) {
  Serial.print("Comanda: ");      // USB debug echo
  Serial.println(c);

  switch (c) {
    case 'a': // PORNESTE MOD AUTONOM
      mod = 'a';
      blocatDeObstacol = false;
      Serial.println("Mod autonom PORNIT");
      break;

    case 'b': // MOD MANUAL
      mod = 'b';
      blocatDeObstacol = false;
      stopMotoare();
      if (lcdOn) {
        lcd.clear();
        lcd.print("Mod manual");
      }
      Serial.println("Mod manual");
      break;

    case 'c': // toggle buzzer proximity beeps
      buzzerOn = !buzzerOn;
      if (!buzzerOn) noTone(BUZZER);
      Serial.print("Buzzer ");
      Serial.println(buzzerOn ? "ON" : "OFF");
      break;

    case 'v': // toggle RGB distance colors
      rgbOn = !rgbOn;
      if (!rgbOn) setRGBOff();
      Serial.print("RGB ");
      Serial.println(rgbOn ? "ON" : "OFF");
      break;

    case 'k': // toggle LCD distance display
      lcdOn = !lcdOn;
      if (!lcdOn) {
        lcd.clear();
      } else if (mod == 'b') {
        lcd.print("Mod manual");
      }
      Serial.print("LCD ");
      Serial.println(lcdOn ? "ON" : "OFF");
      break;

    case '8': // enable all peripherals
      buzzerOn = rgbOn = lcdOn = true;
      Serial.println("Peripherals ALL ON");
      break;

    case '9': // quiet all peripherals
      buzzerOn = rgbOn = lcdOn = false;
      noTone(BUZZER);
      setRGBOff();
      lcd.clear();
      Serial.println("Peripherals ALL OFF");
      break;

    case 'f': // putin inainte
      if (mod == 'b') {
        inainte(VITEZA_NORMALA);
        delay(TIMP_MERS_SCURT);
        stopMotoare();
        Serial.println("Inainte");
      }
      break;

    case 'g': // putin inapoi
      if (mod == 'b') {
        inapoi(VITEZA_NORMALA);
        delay(TIMP_MERS_SCURT);
        stopMotoare();
        Serial.println("Inapoi");
      }
      break;

    case 'h': // stanga 90 (manual SAU deblocare obstacol in autonom)
      if (mod == 'b' || (mod == 'a' && blocatDeObstacol)) {
        rotesteStanga90();
        blocatDeObstacol = false;
        Serial.println("Stanga 90");
      }
      break;

    case 'j': // dreapta 90 (manual SAU deblocare obstacol in autonom)
      if (mod == 'b' || (mod == 'a' && blocatDeObstacol)) {
        rotesteDreapta90();
        blocatDeObstacol = false;
        Serial.println("Dreapta 90");
      }
      break;
  }
}

// Host sends "I3/7\n" or "I-\n" to show tracked cat id on LCD line 0.
void proceseazaIdHost(Stream &s) {
  char buf[17];
  uint8_t i = 0;
  unsigned long deadline = millis() + 50;
  while (i < 16 && millis() < deadline) {
    if (!s.available()) continue;
    char x = (char)s.read();
    if (x == '\n' || x == '\r') break;
    buf[i++] = x;
  }
  buf[i] = '\0';
  strncpy(catIdStr, buf, 16);
  catIdStr[16] = '\0';
}

void pollStream(Stream &s) {
  while (s.available()) {
    char c = (char)s.read();
    if (c == 'I') {
      proceseazaIdHost(s);
      continue;
    }
    proceseazaComanda(c);
  }
}

void loop() {
  pollStream(Serial1);
  pollStream(Serial);

  if (mod == 'a') {
    ruleazaAutonom();
    trimiteTelemetrie();
  } else {
    trimiteTelemetrie();
    long dFeed = distantaPentruFeedback(distantaCurenta);
    feedbackPeriferice(dFeed);
  }
}
