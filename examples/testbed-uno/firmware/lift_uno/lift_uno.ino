// lift.v0 device on an Arduino Uno (WP5c testbed). Serial I/O and timing around lift_device.h.
//
// 115200 baud, one ASCII line per message, '\n'-terminated ('\r' is dropped). Non-blocking: no
// delay(). Each loop runs the due timers first, then handles at most one complete input line.
// Build options: -DLIFT_DEVICE_LOG=0 turns the "# millis ..." device log lines off (errors are
// always written). The LED (pin 13) is on while the lift moves.
// -DLIFT_TRAVEL_SENSOR=1: a servo (pin 9) sweeps between DOWN_DEG and UP_DEG in about TRAVEL_MS, and
// two end sensors pulled low when active (hall sensor or switch: down pin 2, up pin 3) end the move
// (see lift_device.h). The sensors are read every SENSOR_MS; digitalRead does not block.
#include "lift_device.h"

#if LIFT_TRAVEL_SENSOR
#include <Servo.h>
const uint8_t SERVO_PIN = 9, DOWN_PIN = 2, UP_PIN = 3;
const int DOWN_DEG = 0, UP_DEG = 90;  // calibration: servo angles at the two ends of the rig
const uint32_t SENSOR_MS = 5;
const uint32_t STEP_MS = lift::TRAVEL_MS / (UP_DEG > DOWN_DEG ? UP_DEG - DOWN_DEG : DOWN_DEG - UP_DEG);
static Servo servo;
static int angle = DOWN_DEG;
static uint32_t last_sample = 0, last_step = 0;

// While moving, one degree toward the move's end every STEP_MS; held still otherwise.
static void sweep(lift::State s, uint32_t now) {
  int target = s == lift::MOVING_UP ? UP_DEG : s == lift::MOVING_DOWN ? DOWN_DEG : angle;
  if (target == angle || now - last_step < STEP_MS) return;
  last_step = now;
  angle += target > angle ? 1 : -1;
  servo.write(angle);
}
#endif

struct SerialSink : lift::Sink {
  void line(const char* text) override {
    Serial.print(text);
    Serial.print('\n');
  }
  void log(uint32_t now_ms, const char* text) override {
    Serial.print("# ");
    Serial.print(now_ms);
    Serial.print(' ');
    Serial.print(text);
    Serial.print('\n');
  }
};

static SerialSink sink;
static lift::Device device(sink);
static char buf[lift::MAX_LINE + 1];
static uint8_t len = 0;
static bool overflow = false;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
#if LIFT_TRAVEL_SENSOR
  pinMode(DOWN_PIN, INPUT_PULLUP);
  pinMode(UP_PIN, INPUT_PULLUP);
  servo.attach(SERVO_PIN);
  servo.write(angle);  // the device starts in DOWN
#endif
  device.begin(millis());
}

void loop() {
  uint32_t now = millis();
  device.tick(now);
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[len] = 0;
      if (overflow) sink.log(now, "error line_too_long");
      else device.on_line(buf, now);
      len = 0;
      overflow = false;
      break;  // one line per loop, so timers are not starved
    }
    if (len < lift::MAX_LINE) buf[len++] = c;
    else overflow = true;
  }
#if LIFT_TRAVEL_SENSOR
  now = millis();
  if (now - last_sample >= SENSOR_MS) {
    last_sample = now;
    device.on_position(now, digitalRead(UP_PIN) == LOW, digitalRead(DOWN_PIN) == LOW);
  }
  sweep(device.state(), now);
#endif
  lift::State s = device.state();
  digitalWrite(LED_BUILTIN, (s == lift::MOVING_UP || s == lift::MOVING_DOWN) ? HIGH : LOW);
}
