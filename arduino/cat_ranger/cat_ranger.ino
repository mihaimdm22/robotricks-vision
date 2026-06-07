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
 *   RGB LED     : R = 53, G = 51, B = 49  (common ANODE: LOW = on)
 *   Buzzer      : pin 22 (fixed 2000 Hz)
 *   LCD         : I2C 16x2 @ 0x27
 *   Command link: Serial1 (TX1=D18, RX1=D19) -> HC-05 / HM-10 Bluetooth @ 9600 baud
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
 * Arduino -> host (on Serial1):  "D <cm>\n" at ~10 Hz   (-1 = no echo / out of range)
 */

#include <AFMotor.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// Motoare pe M3 si M4 (daca rotirile ies inversate, schimba 3 cu 4)
AF_DCMotor motorStanga(3);
AF_DCMotor motorDreapta(4);

// RGB (common anode: LOW = aprins)
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

char mod = 0; // 0=idle, 'a'=autonom, 'b'=manual
bool blocatDeObstacol = false;

// Timing non-blocking
unsigned long ultimaActualizareLCD = 0;
unsigned long ultimulBip = 0;
unsigned long ultimaTelemetrie = 0;    // ADDITIVE: last "D <cm>" emit
long distantaCurenta = 999;

// ---------- FUNCTII RGB ----------
void setRGB(bool r, bool g, bool b) {
  digitalWrite(RED, r ? LOW : HIGH);
  digitalWrite(GREEN, g ? LOW : HIGH);
  digitalWrite(BLUE, b ? LOW : HIGH);
}

// ---------- SENZOR ----------
long getDistanta() {
  digitalWrite(TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long durata = pulseIn(ECHO, HIGH, 30000); // timeout 30ms
  if (durata == 0) return 999; // nimic detectat
  return durata * 0.034 / 2;
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

// ---------- RGB pe 5 intervale ----------
void culoareDistanta(long d) {
  if (d <= 30) {
    setRGB(1, 0, 0);        // rosu - foarte aproape
  } else if (d <= 60) {
    setRGB(1, 1, 0);        // galben
  } else if (d <= 90) {
    setRGB(0, 1, 0);        // verde
  } else if (d <= 120) {
    setRGB(0, 1, 1);        // cyan
  } else {
    setRGB(0, 0, 1);        // albastru - departe
  }
}

// ---------- BUZZER tip detector de metale ----------
void bipDetector(long d) {
  if (d > 60) {
    noTone(BUZZER);
    return;
  }
  int interval = map(constrain(d, PRAG_OBSTACOL, 60), 60, PRAG_OBSTACOL, 1000, 80);

  if (millis() - ultimulBip >= (unsigned long)interval) {
    ultimulBip = millis();
    tone(BUZZER, FRECV_BIP, 50);
  }
}

// ---------- LCD update throttled ----------
void actualizeazaLCD(long d) {
  if (millis() - ultimaActualizareLCD >= LCD_INTERVAL) {
    ultimaActualizareLCD = millis();
    lcd.setCursor(0, 0);
    if (blocatDeObstacol) {
      lcd.print("OBSTACOL! h/j   ");
    } else {
      lcd.print("Distanta:       ");
    }
    lcd.setCursor(0, 1);
    lcd.print(d);
    lcd.print(" cm        ");
  }
}

// ---------- MOD AUTONOM ----------
void ruleazaAutonom() {
  distantaCurenta = getDistanta();

  culoareDistanta(distantaCurenta);
  bipDetector(distantaCurenta);
  actualizeazaLCD(distantaCurenta);

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
  setRGB(0, 0, 0);

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

void loop() {
  if (Serial1.available()) {
    char c = Serial1.read();
    Serial.print("Comanda: ");      // USB debug only
    Serial.println(c);

    switch (c) {
      case 'a': // PORNESTE MOD AUTONOM
        mod = 'a';
        blocatDeObstacol = false;
        Serial.println("Mod autonom PORNIT");   // ADDITIVE: ack on USB, not Serial1
        break;

      case 'b': // MOD MANUAL
        mod = 'b';
        blocatDeObstacol = false;
        stopMotoare();
        noTone(BUZZER);
        setRGB(0, 0, 0);
        lcd.clear();
        lcd.print("Mod manual");
        Serial.println("Mod manual");           // ADDITIVE: ack on USB, not Serial1
        break;

      case 'f': // putin inainte
        if (mod == 'b') {
          inainte(VITEZA_NORMALA);
          delay(TIMP_MERS_SCURT);
          stopMotoare();
          Serial.println("Inainte");            // ADDITIVE: ack on USB, not Serial1
        }
        break;

      case 'g': // putin inapoi
        if (mod == 'b') {
          inapoi(VITEZA_NORMALA);
          delay(TIMP_MERS_SCURT);
          stopMotoare();
          Serial.println("Inapoi");             // ADDITIVE: ack on USB, not Serial1
        }
        break;

      case 'h': // stanga 90 (manual SAU deblocare obstacol in autonom)
        if (mod == 'b' || (mod == 'a' && blocatDeObstacol)) {
          rotesteStanga90();
          blocatDeObstacol = false;
          Serial.println("Stanga 90");          // ADDITIVE: ack on USB, not Serial1
        }
        break;

      case 'j': // dreapta 90 (manual SAU deblocare obstacol in autonom)
        if (mod == 'b' || (mod == 'a' && blocatDeObstacol)) {
          rotesteDreapta90();
          blocatDeObstacol = false;
          Serial.println("Dreapta 90");         // ADDITIVE: ack on USB, not Serial1
        }
        break;
    }
  }

  if (mod == 'a') {
    ruleazaAutonom();
  }

  // ADDITIVE: stream ground-truth distance to the host (~10 Hz). In manual/idle this
  // also refreshes the reading on the timer, so the loop never blocks on pulseIn()
  // more than once per D_INTERVAL.
  trimiteTelemetrie();
}
