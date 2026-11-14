// lift.v0 device state machine for the WP5c testbed (docs/work-order-wp5c-testbed.md).
//
// Plain C++ with no Arduino headers, so the same code runs on the Uno (lift_uno.ino) and natively
// in the conformance harness (../harness/harness.cpp). Time is passed in, in milliseconds.
// Behaviour follows docs/protocol-lift.md and the Python model (src/replayspect/sut/lift.py). Where
// it cannot follow the model exactly, see examples/testbed-uno/README.md.
//
// Defect switch (stage 3): -DLIFT_DEFECT=N builds the public device-side lift defect MN of the model
// (sut/lift.py MUTANTS): 1, 2, 4, 5, 9, 10 or 11; 0 (the default) is none. M3 (resend the last DONE
// after a reconnect) is not offered: on serial the device never sees a disconnect.
// The build is named only on the device log channel ("build defect=..."), never in READY, so the
// client log does not carry the answer; the testbed link files that line in the truth file, not in
// the device log. With -DLIFT_FIRED_LOG=1 (the native harness only, never the Uno), each time the
// defect's own branch changes what the device does, the device log gets "defect fired MN REQ_ID",
// after any protocol line of that step (later effects of it, such as a result it caused being
// answered from the table, are not marked again). The Uno build leaves it out: on the serial line it
// would delay the replies after it by about 2 ms exactly where the defect fired, a mark in the timing
// even with the line removed. Where a defect fired is computed afterwards by running the device
// log's inputs through the harness (harness/fired_points.py). The build line is written whether or
// not the device log is on, like error lines.
//
// Wire format, one line per message:  NAME REQ_ID [key=value ...]
// Device log lines (when enabled):    # MILLIS KIND NAME [REQ_ID] [key=value ...]
#pragma once

#include <stdint.h>
#include <string.h>

#ifndef LIFT_DEVICE_LOG
#define LIFT_DEVICE_LOG 1
#endif

#ifndef LIFT_DEFECT
#define LIFT_DEFECT 0
#endif
#ifndef LIFT_FIRED_LOG
#define LIFT_FIRED_LOG 0
#endif
#if LIFT_DEFECT != 0 && LIFT_DEFECT != 1 && LIFT_DEFECT != 2 && LIFT_DEFECT != 4 && LIFT_DEFECT != 5 && \
    LIFT_DEFECT != 9 && LIFT_DEFECT != 10 && LIFT_DEFECT != 11
#error "LIFT_DEFECT: 0 (none) or a public device-side lift defect 1, 2, 4, 5, 9, 10, 11 (not 3: no disconnects on serial)"
#endif
#define LIFT_STR2(x) #x
#define LIFT_STR(x) LIFT_STR2(x)

namespace lift {

const uint32_t PROC_MS = 50;      // a new move runs 50 ms after its ACK
const uint32_t TRAVEL_MS = 3000;  // a move takes 3 s
const uint8_t MAX_ID = 15;        // longest req_id
const uint8_t MAX_LINE = 63;      // longest line without the newline
const uint8_t TABLE = 8;          // result table entries (move ids); one run uses 6
const uint8_t QUEUE = 4;          // moves waiting the 50 ms before execution

enum State : uint8_t { DOWN, MOVING_UP, UP, MOVING_DOWN };
enum Result : uint8_t { R_ACK, R_DONE, R_ERROR };
enum Cmd : uint8_t { MOVE_UP, MOVE_DOWN };

inline const char* state_name(State s) {
  switch (s) {
    case DOWN: return "DOWN";
    case MOVING_UP: return "MOVING_UP";
    case UP: return "UP";
    default: return "MOVING_DOWN";
  }
}

inline const char* cmd_name(Cmd c) { return c == MOVE_UP ? "MOVE_UP" : "MOVE_DOWN"; }

// MN of the model is switched on (see LIFT_DEFECT).
inline bool defect(int n) { return LIFT_DEFECT == n; }
// A result is recorded later than at acceptance (M2: at DONE; M9: at execution; M11: the table is
// cleared), so recording an ERROR or DONE may have to add the id, as the model's dict does.
inline bool late_record() { return defect(2) || defect(9) || defect(11); }

// Where the device writes. line(): a protocol line (no newline). log(): a device log line body
// (no "# millis" prefix, no newline); the sink adds the prefix.
struct Sink {
  virtual void line(const char* text) = 0;
  virtual void log(uint32_t now_ms, const char* text) = 0;
};

class Device {
 public:
  explicit Device(Sink& out) : out_(out) {}

  void begin(uint32_t now) {
    state_ = stable_ = DOWN;
    n_results_ = 0;
    n_seen_ = 0;
    n_queue_ = 0;
    moving_ = false;
    out_.line(LIFT_DEVICE_LOG ? "READY log=1" : "READY log=0");
    out_.log(now, LIFT_DEFECT == 0 ? "build defect=none" : "build defect=M" LIFT_STR(LIFT_DEFECT));
    if (LIFT_DEVICE_LOG) out_.log(now, "state DOWN from=- on=init");
  }

  // The earliest time a timer is due, or false when none is pending.
  bool next_due(uint32_t& at) const {
    bool any = false;
    for (uint8_t i = 0; i < n_queue_; i++)
      if (!any || before(queue_[i].due, at)) { at = queue_[i].due; any = true; }
    if (moving_ && (!any || before(travel_due_, at))) { at = travel_due_; any = true; }
    return any;
  }

  // Run every timer due at or before now, in due order (ties: execution queue first, in arrival order).
  void tick(uint32_t now) {
    for (;;) {
      int8_t qi = -1;
      for (uint8_t i = 0; i < n_queue_; i++)
        if (!before(now, queue_[i].due) && (qi < 0 || before(queue_[i].due, queue_[qi].due))) qi = (int8_t)i;
      bool travel = moving_ && !before(now, travel_due_);
      if (qi < 0 && !travel) return;
      if (qi >= 0 && (!travel || !before(travel_due_, queue_[qi].due))) {
        Pending p = queue_[qi];
        for (uint8_t i = (uint8_t)qi; i + 1 < n_queue_; i++) queue_[i] = queue_[i + 1];
        n_queue_--;
        execute(p.cmd, p.id, p.due);
      } else {
        arrive(travel_due_);
      }
    }
  }

  // One received line (no newline).
  void on_line(const char* text, uint32_t now) {
    char name[16], id[MAX_ID + 1];
    const char* p = text;
    uint8_t name_len = word(p, name, sizeof name);
    if (name_len == 0) return;  // a blank line
    if (name_len >= sizeof name) { error(now, "bad_name", ""); return; }
    uint8_t id_len = word(p, id, sizeof id);
    bool has_id = id_len > 0;
    if (id_len > MAX_ID) { error(now, "id_too_long", ""); return; }
    bool is_status = strcmp(name, "STATUS") == 0;
    bool is_up = strcmp(name, "MOVE_UP") == 0, is_down = strcmp(name, "MOVE_DOWN") == 0;
    if (!is_status && !is_up && !is_down) {  // the model ignores other messages
      if (LIFT_DEVICE_LOG) logf(now, "recv ", name, has_id ? id : "", "");
      return;
    }
    if (!has_id) { error(now, "no_req_id", name); return; }
    if (LIFT_DEVICE_LOG) logf(now, "recv ", name, id, "");
    if (is_status) {
      bool old = defect(5) && state_ != stable_;  // M5: during a move, the state before it
      send(now, "STATUS_REPLY", id, "state=", state_name(old ? stable_ : state_));
      if (old) fired(now, id);
      return;
    }
    // A correct device would answer a repeat from its table; M1, M2, M9 and M11 can miss it.
    bool known_to_correct = seen(id);
    int8_t known = defect(1) ? -1 : find(id);
    if (known >= 0) {
      Result r = table_[known].result;
      if (r == R_ACK) send(now, "ACK", id, "", "");
      else if (r == R_DONE) send(now, "DONE", id, "", "");
      else if (defect(10)) { send(now, "DONE", id, "", ""); fired(now, id); }  // M10: DONE, not the ERROR
      else send(now, "ERROR", id, "reason=", "illegal");
      return;
    }
    if (n_queue_ >= QUEUE) { error(now, "queue_full", id); return; }
    if (defect(11)) n_results_ = 0;  // M11: only the most recent id is remembered
    if (!defect(2) && !defect(9)) {
      if (!record(id, R_ACK)) error(now, "table_full", id);  // not recorded: a repeat would run again
    }
    see(id);
    send(now, "ACK", id, "", "");
    if (known_to_correct) fired(now, id);
    Pending& q = queue_[n_queue_++];
    q.cmd = is_up ? MOVE_UP : MOVE_DOWN;
    strncpy(q.id, id, MAX_ID + 1);
    q.id[MAX_ID] = 0;
    q.due = now + PROC_MS;
  }

  State state() const { return state_; }

 private:
  struct Entry { char id[MAX_ID + 1]; Result result; };
  struct Pending { Cmd cmd; char id[MAX_ID + 1]; uint32_t due; };

  static bool before(uint32_t a, uint32_t b) { return (int32_t)(a - b) < 0; }  // wrap-safe

  // Next space-separated token into out (cut to size-1 chars); returns its full length, 0 at the end.
  static uint8_t word(const char*& p, char* out, uint8_t size) {
    while (*p == ' ') p++;
    uint8_t n = 0, full = 0;
    while (*p && *p != ' ') {
      if (n + 1 < size) out[n++] = *p;
      if (full < 255) full++;
      p++;
    }
    out[n] = 0;
    return full;
  }

  int8_t find(const char* id) const {
    for (uint8_t i = 0; i < n_results_; i++)
      if (strcmp(table_[i].id, id) == 0) return (int8_t)i;
    return -1;
  }

  // Set the id's result, adding the id if it is new; false when the table is full.
  bool record(const char* id, Result r) {
    int8_t i = find(id);
    if (i < 0) {
      if (n_results_ >= TABLE) return false;
      i = (int8_t)n_results_++;
      strncpy(table_[i].id, id, MAX_ID + 1);
      table_[i].id[MAX_ID] = 0;
    }
    table_[i].result = r;
    return true;
  }

  // Update a recorded id's result (with no defect, every running id was recorded when accepted,
  // unless the table was full; a defect that records later adds it here).
  void set_result(uint32_t now, const char* id, Result r) {
    if (late_record()) {
      if (!record(id, r)) error(now, "table_full", id);
    } else {
      int8_t i = find(id);
      if (i >= 0) table_[i].result = r;
    }
  }

  // The ids a correct device would have recorded (every accepted id, while there is room): only
  // used to tell when a defect makes the device miss a repeat.
  bool seen(const char* id) const {
    for (uint8_t i = 0; i < n_seen_; i++)
      if (strcmp(seen_[i], id) == 0) return true;
    return false;
  }

  void see(const char* id) {
    if (seen(id) || n_seen_ >= TABLE) return;
    strncpy(seen_[n_seen_], id, MAX_ID + 1);
    seen_[n_seen_++][MAX_ID] = 0;
  }

  void fired(uint32_t now, const char* id) {
    if (LIFT_FIRED_LOG) logf(now, "defect fired M" LIFT_STR(LIFT_DEFECT), "", id, "");
  }

  void execute(Cmd cmd, const char* id, uint32_t now) {
    if (defect(9)) set_result(now, id, R_ACK);  // M9: recorded when it starts executing
    State need = cmd == MOVE_UP ? DOWN : UP;
    bool legal = state_ == need;
    if (defect(4) && moving_ && state_ == (cmd == MOVE_UP ? MOVING_DOWN : MOVING_UP)) {
      legal = true;  // M4: the opposite move is taken; the running move is dropped and sends no DONE
      fired(now, id);
    }
    if (!legal) {
      set_result(now, id, R_ERROR);
      send(now, "ERROR", id, "reason=", "illegal");
      return;
    }
    if (LIFT_DEVICE_LOG) logf(now, "effect motor_start ", id, "", cmd == MOVE_UP ? " dir=up" : " dir=down");
    State moving = cmd == MOVE_UP ? MOVING_UP : MOVING_DOWN;
    set_state(now, moving, cmd_name(cmd), id);
    moving_ = true;
    travel_cmd_ = cmd;
    strncpy(travel_id_, id, MAX_ID + 1);
    travel_id_[MAX_ID] = 0;
    travel_due_ = now + TRAVEL_MS;
  }

  void arrive(uint32_t now) {
    moving_ = false;
    if (LIFT_DEVICE_LOG) logf(now, "effect motor_stop ", travel_id_, "", "");
    set_state(now, travel_cmd_ == MOVE_UP ? UP : DOWN, "arrived", travel_id_);
    set_result(now, travel_id_, R_DONE);
    send(now, "DONE", travel_id_, "", "");
  }

  void set_state(uint32_t now, State s, const char* on, const char* id) {
    State old = state_;
    state_ = s;
    if (s == DOWN || s == UP) stable_ = s;
    if (LIFT_DEVICE_LOG) {
      char buf[MAX_LINE + 1];
      snprint(buf, "state ", state_name(s), " ", id, " from=", state_name(old), " on=", on);
      out_.log(now, buf);
    }
  }

  void send(uint32_t now, const char* name, const char* id, const char* key, const char* value) {
    char buf[MAX_LINE + 1];
    snprint(buf, name, " ", id, *key ? " " : "", key, value, "", "");
    out_.line(buf);  // the protocol line first: a device log line must not delay it
    if (LIFT_DEVICE_LOG) {
      char lb[MAX_LINE + 1];
      snprint(lb, "send ", buf, "", "", "", "", "", "");
      out_.log(now, lb);
    }
  }

  void logf(uint32_t now, const char* a, const char* b, const char* c, const char* d) {
    char buf[MAX_LINE + 1];
    snprint(buf, a, b, *c ? " " : "", c, d, "", "", "");
    out_.log(now, buf);
  }

  void error(uint32_t now, const char* why, const char* what) {
    char buf[MAX_LINE + 1];
    snprint(buf, "error ", why, *what ? " " : "", what, "", "", "", "");
    out_.log(now, buf);  // always written, even with the device log off: it makes the run invalid
  }

  // Concatenate up to eight pieces into buf (MAX_LINE + 1 bytes), cutting at the end.
  static void snprint(char* buf, const char* a, const char* b, const char* c, const char* d, const char* e,
                      const char* f, const char* g, const char* h) {
    const char* parts[8] = {a, b, c, d, e, f, g, h};
    uint8_t n = 0;
    for (uint8_t i = 0; i < 8; i++)
      for (const char* p = parts[i]; *p && n < MAX_LINE; p++) buf[n++] = *p;
    buf[n] = 0;
  }

  Sink& out_;
  State state_ = DOWN;
  State stable_ = DOWN;  // the last state that was not a move (M5)
  Entry table_[TABLE];
  uint8_t n_results_ = 0;
  char seen_[TABLE][MAX_ID + 1];
  uint8_t n_seen_ = 0;
  Pending queue_[QUEUE];
  uint8_t n_queue_ = 0;
  bool moving_ = false;
  Cmd travel_cmd_ = MOVE_UP;
  char travel_id_[MAX_ID + 1] = {0};
  uint32_t travel_due_ = 0;
};

}  // namespace lift
