// Native conformance harness for lift_device.h (no Arduino).
// stdin: one input per line, "T_MS LINE" (times non-decreasing); a final line "END T_MS" runs timers until then.
// stdout: "T_MS OUT LINE" for protocol lines and "T_MS LOG BODY" for device log lines.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../lift_uno/lift_device.h"

struct Print : lift::Sink {
  uint32_t now = 0;
  void line(const char* text) override { std::printf("%u OUT %s\n", now, text); }
  void log(uint32_t t, const char* text) override { std::printf("%u LOG %s\n", t, text); }
};

static void run_until(lift::Device& d, Print& out, uint32_t t) {
  uint32_t due;
  while (d.next_due(due) && (int32_t)(due - t) <= 0) {
    out.now = due;
    d.tick(due);
  }
  out.now = t;
}

int main() {
  Print out;
  lift::Device dev(out);
  dev.begin(0);
  char buf[256];
  while (std::fgets(buf, sizeof buf, stdin)) {
    size_t n = std::strlen(buf);
    while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r')) buf[--n] = 0;
    if (!n) continue;
    if (std::strncmp(buf, "END ", 4) == 0) {
      run_until(dev, out, (uint32_t)std::strtoul(buf + 4, nullptr, 10));
      break;
    }
    char* rest;
    uint32_t t = (uint32_t)std::strtoul(buf, &rest, 10);
    while (*rest == ' ') rest++;
    run_until(dev, out, t);  // timers first, then the input (the firmware loop's order)
    dev.on_line(rest, t);
  }
  return 0;
}
