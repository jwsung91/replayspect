// turntable.v0 device state machine for the testbed, the second system after the lift.
//
// Plain C++ with no Arduino headers, so the same code runs on the board (turntable_uno.ino) and
// natively in the conformance harness (../harness/harness.cpp built with -DHARNESS_TURNTABLE=1).
// Time is passed in, in milliseconds. Behaviour follows docs/protocol-turntable.md and the Python
// model (src/replayspect/sut/turntable.py). Wire format, device log lines, timer order and limits
// (table, queue, line length, error lines) are those of the lift firmware (lift_device.h, see
// examples/testbed-uno/README.md). The model defines no defects, so there is no defect switch, and
// the build line is always "build defect=none".
//
// Wire format, one line per message:  NAME REQ_ID [key=value ...]
// Device log lines (when enabled):    # MILLIS KIND NAME [REQ_ID] [key=value ...]
#pragma once

#include <stdint.h>
#include <string.h>

#ifndef TURNTABLE_DEVICE_LOG
#define TURNTABLE_DEVICE_LOG 1
#endif

namespace turntable {

const uint32_t PROC_MS = 50;      // a new turn runs 50 ms after its ACK
const uint32_t TURN_MS = 3000;    // a turn takes 3 s
const uint8_t MAX_ID = 15;        // longest req_id
const uint8_t MAX_LINE = 63;      // longest line without the newline
const uint8_t TABLE = 8;          // result table entries (turn ids); one run uses 6
const uint8_t QUEUE = 4;          // turns waiting the 50 ms before execution

enum State : uint8_t { INITIAL, LEFT, RIGHT, TURNING_TO_LEFT, TURNING_TO_INITIAL, TURNING_TO_RIGHT };
enum Result : uint8_t { R_ACK, R_DONE, R_LIMIT, R_ILLEGAL };  // the last two: ERROR with that reason
enum Cmd : uint8_t { TURN_LEFT, TURN_RIGHT };

inline const char* state_name(State s) {
  switch (s) {
    case INITIAL: return "INITIAL";
    case LEFT: return "LEFT";
    case RIGHT: return "RIGHT";
    case TURNING_TO_LEFT: return "TURNING_TO_LEFT";
    case TURNING_TO_INITIAL: return "TURNING_TO_INITIAL";
    default: return "TURNING_TO_RIGHT";
  }
}

inline const char* cmd_name(Cmd c) { return c == TURN_LEFT ? "TURN_LEFT" : "TURN_RIGHT"; }

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
    state_ = INITIAL;
    n_results_ = 0;
    n_queue_ = 0;
    turning_ = false;
    out_.line(TURNTABLE_DEVICE_LOG ? "READY log=1" : "READY log=0");
    out_.log(now, "build defect=none");
    if (TURNTABLE_DEVICE_LOG) out_.log(now, "state INITIAL from=- on=init");
  }

  // The earliest time a timer is due, or false when none is pending.
  bool next_due(uint32_t& at) const {
    bool any = false;
    for (uint8_t i = 0; i < n_queue_; i++)
      if (!any || before(queue_[i].due, at)) { at = queue_[i].due; any = true; }
    if (turning_ && (!any || before(turn_due_, at))) { at = turn_due_; any = true; }
    return any;
  }

  // Run every timer due at or before now, in due order (ties: execution queue first, in arrival order).
  void tick(uint32_t now) {
    for (;;) {
      int8_t qi = -1;
      for (uint8_t i = 0; i < n_queue_; i++)
        if (!before(now, queue_[i].due) && (qi < 0 || before(queue_[i].due, queue_[qi].due))) qi = (int8_t)i;
      bool turn = turning_ && !before(now, turn_due_);
      if (qi < 0 && !turn) return;
      if (qi >= 0 && (!turn || !before(turn_due_, queue_[qi].due))) {
        Pending p = queue_[qi];
        for (uint8_t i = (uint8_t)qi; i + 1 < n_queue_; i++) queue_[i] = queue_[i + 1];
        n_queue_--;
        execute(p.cmd, p.id, p.due);
      } else {
        arrive(turn_due_);
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
    bool is_left = strcmp(name, "TURN_LEFT") == 0, is_right = strcmp(name, "TURN_RIGHT") == 0;
    if (!is_status && !is_left && !is_right) {  // the model ignores other messages
      if (TURNTABLE_DEVICE_LOG) logf(now, "recv ", name, has_id ? id : "", "");
      return;
    }
    if (!has_id) { error(now, "no_req_id", name); return; }
    if (TURNTABLE_DEVICE_LOG) logf(now, "recv ", name, id, "");
    if (is_status) {
      send(now, "STATUS_REPLY", id, "state=", state_name(state_));
      return;
    }
    int8_t known = find(id);
    if (known >= 0) {
      reply(now, id, table_[known].result);
      return;
    }
    if (n_queue_ >= QUEUE) { error(now, "queue_full", id); return; }
    if (!record(id, R_ACK)) error(now, "table_full", id);  // not recorded: a repeat would run again
    send(now, "ACK", id, "", "");
    Pending& q = queue_[n_queue_++];
    q.cmd = is_left ? TURN_LEFT : TURN_RIGHT;
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

  // Add a new id with its result; false when the table is full.
  bool record(const char* id, Result r) {
    if (n_results_ >= TABLE) return false;
    Entry& e = table_[n_results_++];
    strncpy(e.id, id, MAX_ID + 1);
    e.id[MAX_ID] = 0;
    e.result = r;
    return true;
  }

  // Update a recorded id's result (an id is missing only when the table was full at acceptance).
  void set_result(const char* id, Result r) {
    int8_t i = find(id);
    if (i >= 0) table_[i].result = r;
  }

  void reply(uint32_t now, const char* id, Result r) {
    if (r == R_ACK) send(now, "ACK", id, "", "");
    else if (r == R_DONE) send(now, "DONE", id, "", "");
    else send(now, "ERROR", id, "reason=", r == R_LIMIT ? "limit" : "illegal");
  }

  void execute(Cmd cmd, const char* id, uint32_t now) {
    bool left = cmd == TURN_LEFT;
    State turning, target;
    if (state_ == INITIAL) {
      turning = left ? TURNING_TO_LEFT : TURNING_TO_RIGHT;
      target = left ? LEFT : RIGHT;
    } else if ((state_ == LEFT && !left) || (state_ == RIGHT && left)) {
      turning = TURNING_TO_INITIAL;
      target = INITIAL;
    } else {  // at the end in that direction (limit), or turning (illegal)
      Result r = (state_ == LEFT || state_ == RIGHT) ? R_LIMIT : R_ILLEGAL;
      set_result(id, r);
      reply(now, id, r);
      return;
    }
    if (TURNTABLE_DEVICE_LOG) logf(now, "effect motor_start ", id, "", left ? " dir=left" : " dir=right");
    set_state(now, turning, cmd_name(cmd), id);
    turning_ = true;
    target_ = target;
    strncpy(turn_id_, id, MAX_ID + 1);
    turn_id_[MAX_ID] = 0;
    turn_due_ = now + TURN_MS;
  }

  void arrive(uint32_t now) {
    turning_ = false;
    if (TURNTABLE_DEVICE_LOG) logf(now, "effect motor_stop ", turn_id_, "", "");
    set_state(now, target_, "arrived", turn_id_);
    set_result(turn_id_, R_DONE);
    send(now, "DONE", turn_id_, "", "");
  }

  void set_state(uint32_t now, State s, const char* on, const char* id) {
    State old = state_;
    state_ = s;
    if (TURNTABLE_DEVICE_LOG) {
      char buf[MAX_LINE + 1];
      snprint(buf, "state ", state_name(s), " ", id, " from=", state_name(old), " on=", on);
      out_.log(now, buf);
    }
  }

  void send(uint32_t now, const char* name, const char* id, const char* key, const char* value) {
    char buf[MAX_LINE + 1];
    snprint(buf, name, " ", id, *key ? " " : "", key, value, "", "");
    out_.line(buf);  // the protocol line first: a device log line must not delay it
    if (TURNTABLE_DEVICE_LOG) {
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
  State state_ = INITIAL;
  Entry table_[TABLE];
  uint8_t n_results_ = 0;
  Pending queue_[QUEUE];
  uint8_t n_queue_ = 0;
  bool turning_ = false;
  State target_ = INITIAL;
  char turn_id_[MAX_ID + 1] = {0};
  uint32_t turn_due_ = 0;
};

}  // namespace turntable
