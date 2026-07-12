// ============================================================
// Photometric Stereo - Phase-Controlled LED Sequencer
// Arduino Uno  |  Pins 2-6 -> MOSFET IN1-IN5 -> LEDs 1-5
//
// TWO MODES (select via Serial):
//   MANUAL mode ('m'):  you press Enter to advance each LED
//                       gives you time to take a phone photo
//   AUTO mode ('a'):    each LED stays on for AUTO_HOLD_MS,
//                       then advances automatically
//
// At the end of a full sequence all LEDs go off and the
// controller waits for a new mode command.
//
// SERIAL commands (9600 baud):
//   'm'  -> start Manual mode
//   'a'  -> start Auto mode
//   'n'  -> (Manual mode) advance to next LED
//   'r'  -> reset / abort current sequence
//   '+'  -> increase auto hold time by 1 s
//   '-'  -> decrease auto hold time by 1 s (min 2 s)
//
// DIRECT control (for Python / programmatic use):
//   '0'  -> all LEDs off  (works from any state)
//   '1'-'5' -> turn on that LED only (aborts any running sequence)
//
// ACK byte (for Python synchronization):
//   Every DIRECT command ('0'-'5') writes a single byte 'K'
//   right after the digitalWrite() takes effect, so the host
//   can block on read(1) instead of guessing a fixed delay.
// ============================================================

const int LED_PINS[5] = {2, 3, 4, 5, 6};  // Matches MOSFET IN1-IN5
const int NUM_LEDS     = 5;

// -- Timing --------------------------------------------------
unsigned long AUTO_HOLD_MS = 5000;   // Default: 5 s per LED in auto mode
const unsigned long BLINK_MS = 200;  // Ready-blink duration

// -- State machine --------------------------------------------
enum State { IDLE, MANUAL_HOLD, AUTO_RUNNING };
State state       = IDLE;
int   currentLED  = -1;   // which LED is currently ON (0-based)
unsigned long ledOnAt = 0;

// --------------------------------------------------------------
void allOff() {
  for (int i = 0; i < NUM_LEDS; i++)
    digitalWrite(LED_PINS[i], LOW);
}

void activateLED(int index) {
  allOff();
  digitalWrite(LED_PINS[index], HIGH);
  ledOnAt = millis();
  Serial.print(F(">>> LED "));
  Serial.print(index + 1);
  Serial.print(F(" ON  (pin "));
  Serial.print(LED_PINS[index]);
  Serial.println(F(")"));
}

void readyBlink() {
  // Brief double-blink on LED 1 to signal sequence start
  for (int b = 0; b < 2; b++) {
    digitalWrite(LED_PINS[0], HIGH);
    delay(BLINK_MS);
    digitalWrite(LED_PINS[0], LOW);
    delay(BLINK_MS);
  }
}

void printStatus() {
  Serial.println(F("--------------------------------------"));
  Serial.print(F("Auto hold time : "));
  Serial.print(AUTO_HOLD_MS / 1000);
  Serial.println(F(" s"));
  Serial.println(F("Commands: 'm'=manual  'a'=auto  'r'=reset"));
  Serial.println(F("          '+'=hold+1s  '-'=hold-1s"));
  Serial.println(F("--------------------------------------"));
}

void startSequence(State mode) {
  state      = mode;
  currentLED = 0;
  Serial.println(F(""));
  Serial.println(F("=== SEQUENCE START ==="));
  if (mode == MANUAL_HOLD)
    Serial.println(F("MANUAL mode - take photo then press 'n' to advance"));
  else {
    Serial.print(F("AUTO mode   - each LED on for "));
    Serial.print(AUTO_HOLD_MS / 1000);
    Serial.println(F(" s"));
  }
  readyBlink();
  activateLED(currentLED);
  if (mode == MANUAL_HOLD)
    Serial.println(F("  --> Take photo now.  Press 'n' when ready."));
}

void advanceOrFinish() {
  currentLED++;
  if (currentLED >= NUM_LEDS) {
    allOff();
    state = IDLE;
    Serial.println(F(""));
    Serial.println(F("=== SEQUENCE COMPLETE - all LEDs off ==="));
    printStatus();
  } else {
    activateLED(currentLED);
    if (state == MANUAL_HOLD)
      Serial.println(F("  --> Take photo now.  Press 'n' when ready."));
  }
}

// --------------------------------------------------------------
void setup() {
  Serial.begin(9600);
  for (int i = 0; i < NUM_LEDS; i++) {
    pinMode(LED_PINS[i], OUTPUT);
    digitalWrite(LED_PINS[i], LOW);
  }
  Serial.println(F(""));
  Serial.println(F("Photometric Stereo Phase Controller"));
  Serial.println(F("===================================="));
  printStatus();
}

void loop() {
  // -- Handle serial input --------------------------------
  if (Serial.available()) {
    char c = (char)Serial.read();

    // -- Direct LED control ('0'=off, '1'-'5'=single LED) --
    if (c == '0') {
      allOff();
      state = IDLE;
      Serial.println(F("[DIRECT] All LEDs off"));
      Serial.write('K');   // ACK: off takes effect immediately above
    }
    else if (c >= '1' && c <= '5') {
      int idx = c - '1';
      if (idx < NUM_LEDS) {
        state = IDLE;          // abort any running sequence
        activateLED(idx);
        Serial.print(F("[DIRECT] LED "));
        Serial.print(idx + 1);
        Serial.println(F(" on"));
        Serial.write('K');   // ACK: LED is physically on as of this point
      }
    }
    else if (c == 'r' || c == 'R') {
      allOff();
      state = IDLE;
      Serial.println(F("[RESET] Sequence aborted."));
      printStatus();
    }
    else if (c == '+') {
      AUTO_HOLD_MS += 1000;
      Serial.print(F("Hold time -> "));
      Serial.print(AUTO_HOLD_MS / 1000);
      Serial.println(F(" s"));
    }
    else if (c == '-') {
      if (AUTO_HOLD_MS > 2000) AUTO_HOLD_MS -= 1000;
      Serial.print(F("Hold time -> "));
      Serial.print(AUTO_HOLD_MS / 1000);
      Serial.println(F(" s"));
    }
    else if ((c == 'm' || c == 'M') && state == IDLE) {
      startSequence(MANUAL_HOLD);
    }
    else if ((c == 'a' || c == 'A') && state == IDLE) {
      startSequence(AUTO_RUNNING);
    }
    else if ((c == 'n' || c == 'N') && state == MANUAL_HOLD) {
      // Advance to next LED
      advanceOrFinish();
    }
  }

  // -- Auto timing ------------------------------------------
  if (state == AUTO_RUNNING) {
    if ((millis() - ledOnAt) >= AUTO_HOLD_MS) {
      advanceOrFinish();
    }
  }
}
