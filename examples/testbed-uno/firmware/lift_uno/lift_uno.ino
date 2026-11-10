// lift.v0 device on an Arduino Uno (WP5c testbed). Serial I/O and timing around lift_device.h.
//
// 115200 baud, one ASCII line per message, '\n'-terminated ('\r' is dropped). Non-blocking: no
// delay(). Each loop runs the due timers first, then handles at most one complete input line.
// Build options: -DLIFT_DEVICE_LOG=0 turns the "# millis ..." device log lines off (errors are
// always written). The LED (pin 13) is on while the lift moves.
#include "lift_device.h"

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
  lift::State s = device.state();
  digitalWrite(LED_BUILTIN, (s == lift::MOVING_UP || s == lift::MOVING_DOWN) ? HIGH : LOW);
}
