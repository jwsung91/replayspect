"""The testbed client (WP5c): the robot's main controller, driving the Uno lift over serial.

Behaviour is the client of docs/protocol-lift.md:
* 6 move commands, alternating MOVE_UP / MOVE_DOWN from MOVE_UP, ids r-0001...; at most one open;
  a think time of 1 to 3 s (seeded) after each command closes;
* no ACK within 2 s: resend with the same id, at most twice, then close as failed (ack_timeout);
* no DONE or ERROR within 15 s of the first send: close as failed (done_timeout);
* DONE or ERROR closes the command only if its id is the open one's;
* after a reconnect, resend the open command; STATUS every second (s-0001...), replies not acted on.

The log (one line per send, receive, result, link change) is what ``ingest`` reads with
``rules/testbed-client.yaml``. Timestamps are the wall clock read once at start plus the monotonic
time since, written in microseconds, so a clock correction during a run cannot make the log jump.
The resolution is µs; the accuracy is coarser (USB serial delivers bytes in bursts, and the loop
polls every half millisecond or so).

A run is invalid when the device writes any ``# ... error`` line, or when ``READY`` comes again
(the board reset). The last log line says which.

Usage (on the Orin):  python3 client.py --port /dev/ttyACM0 --log client.log --device-log device.log
Needs pyserial (``pip install pyserial``) for a real port; the rest is the standard library.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # fault_link.py sits next to this file
from fault_link import FaultLink, Plan  # noqa: E402

ACK_TIMEOUT_US = 2_000_000
MAX_RETRIES = 2
DONE_TIMEOUT_US = 15_000_000
POLL_US = 1_000_000
THINK_MS = (1_000, 3_000)


class Clock:
    """Wall clock read once, then advanced by the monotonic clock. ``now_us`` is the time since start."""

    def __init__(self, wall: datetime | None = None, mono=time.monotonic):
        self._mono = mono
        self.start_wall = wall or datetime.now().astimezone()
        self.start_mono = mono()

    def now_us(self) -> int:
        return int(round((self._mono() - self.start_mono) * 1_000_000))

    def stamp(self, us: int | None = None) -> str:
        t = self.start_wall + timedelta(microseconds=self.now_us() if us is None else us)
        return t.isoformat(timespec="microseconds")


class Client:
    def __init__(self, link: FaultLink, clock: Clock, log, seed: int = 0, commands: int = 6, run_s: int = 90):
        self.link, self.clock, self.log = link, clock, log
        self.rng = random.Random(seed)
        self.seed, self.commands, self.run_us = seed, commands, run_s * 1_000_000
        self.counters = {"r": 0, "s": 0}
        self.issued = 0
        self.want = "MOVE_UP"
        self.current: str | None = None
        self.cmd: str | None = None
        self.acked = False
        self.retries = 0
        self.timers: list[tuple[int, int, str, str | None]] = []  # (due, order, kind, req_id)
        self._order = 0
        self.started_at: int | None = None
        self.firmware = "unknown"
        self.resets = 0
        self.up = True
        link.on_change = self.link_change

    # -- log ----------------------------------------------------------------------------------

    def write(self, text: str, us: int | None = None) -> None:
        self.log.write(f"{self.clock.stamp(us)} {text}\n")

    # -- timers -------------------------------------------------------------------------------

    def at(self, due: int, kind: str, req_id: str | None = None) -> None:
        self._order += 1
        self.timers.append((due, self._order, kind, req_id))

    def new_id(self, prefix: str) -> str:
        self.counters[prefix] += 1
        return f"{prefix}-{self.counters[prefix]:04d}"

    def send(self, name: str, req_id: str, now: int) -> None:
        self.link.write_line(f"{name} {req_id}")
        self.write(f"TX {name} req={req_id}", now)

    # -- life cycle ---------------------------------------------------------------------------

    def start(self, now: int, ready_line: str) -> None:
        self.firmware = " ".join(ready_line.split()[1:]) or "unknown"
        self.write(f"# testbed client: firmware {self.firmware}; think_seed={self.seed}; plan={self.link.plan_id}; "
                   f"commands={self.commands}; run_s={self.run_us // 1_000_000}; started={self.clock.stamp(now)}", now)
        self.started_at = now
        self.at(now, "issue")
        self.at(now + POLL_US, "poll")

    def done(self, now: int) -> bool:
        return self.started_at is not None and now - self.started_at >= self.run_us

    def finish(self, now: int) -> bool:
        """Write the closing line; returns whether the run is valid."""
        reasons = []
        if self.link.errors:
            reasons.append(f"device_errors={len(self.link.errors)}")
        if self.resets:
            reasons.append(f"resets={self.resets}")
        self.write(f"# end valid={'no' if reasons else 'yes'}" + (f" reasons={','.join(reasons)}" if reasons else ""), now)
        return not reasons

    def step(self, now: int) -> None:
        """Run the timers due by ``now``, then handle the lines received."""
        while True:
            due = [t for t in self.timers if t[0] <= now]
            if not due:
                break
            t = min(due)
            self.timers.remove(t)
            self.fire(t[2], t[3], now, t[0])
        for line in self.link.poll():
            if self.started_at is None:
                if line.startswith("READY"):
                    self.start(now, line)  # anything before READY is boot noise
            else:
                self.receive(line, now)

    def fire(self, kind: str, req_id: str | None, now: int, due: int | None = None) -> None:
        """``now``: when it actually runs (sends and timeouts count from it); ``due``: when it was due
        (polls keep their 1 s cadence from it)."""
        if kind == "issue":
            if self.issued >= self.commands:
                return
            self.issued += 1
            self.cmd, self.current = self.want, self.new_id("r")
            self.want = "MOVE_DOWN" if self.want == "MOVE_UP" else "MOVE_UP"
            self.acked, self.retries = False, 0
            self.send(self.cmd, self.current, now)
            self.at(now + ACK_TIMEOUT_US, "ack_timeout", self.current)
            self.at(now + DONE_TIMEOUT_US, "done_timeout", self.current)
        elif kind == "ack_timeout":
            if self.current != req_id or self.acked:
                return
            if self.retries < MAX_RETRIES:
                self.retries += 1
                self.send(self.cmd, req_id, now)
                self.at(now + ACK_TIMEOUT_US, "ack_timeout", req_id)
            else:
                self.close("ERROR", None, "ack_timeout", now)
        elif kind == "done_timeout":
            if self.current == req_id:
                self.close("ERROR", None, "done_timeout", now)
        elif kind == "poll":
            self.send("STATUS", self.new_id("s"), now)
            self.at((now if due is None else due) + POLL_US, "poll")

    def close(self, outcome: str, reply_id: str | None, cause: str, now: int) -> None:
        self.write(f"result {self.current} {outcome} cause={cause}" + (f" reply={reply_id}" if reply_id else ""), now)
        self.timers = [t for t in self.timers if t[2] not in ("ack_timeout", "done_timeout")]
        self.current = None
        self.at(now + self.rng.randint(*THINK_MS) * 1000, "issue")

    def receive(self, line: str, now: int) -> None:
        parts = line.split()
        name = parts[0]
        if name == "READY":
            self.resets += 1
            self.write(f"# READY again ({line}): the board reset; this run is invalid", now)
            return
        req_id = parts[1] if len(parts) > 1 else None
        fields = " ".join(sorted(parts[2:]))
        self.write(f"RX {name}" + (f" req={req_id}" if req_id else "") + (f" {fields}" if fields else ""), now)
        if self.current is None:
            return
        if name == "ACK" and req_id == self.current:
            self.acked = True
        elif name in ("DONE", "ERROR") and req_id == self.current:
            self.close(name, req_id, "reply", now)

    def link_change(self, up: bool, now: int) -> None:
        """Called by the link when it observes the connection go down or come back (stage 2)."""
        self.up = up
        self.write(f"link {'up' if up else 'down'}", now)
        if up and self.current is not None:
            self.send(self.cmd, self.current, now)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WP5c testbed client: drive the Uno lift over serial and log it.")
    ap.add_argument("--port", required=True, help="serial port, e.g. /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--log", required=True, help="client log (new file)")
    ap.add_argument("--device-log", required=True, help="device log, the board's '#' lines (new file)")
    ap.add_argument("--truth", help="what the link did (new file; stage 2 keeps it outside the repository)")
    ap.add_argument("--seed", type=int, default=0, help="think time seed")
    ap.add_argument("--plan", default="none", help="link fault plan, a JSON file (default none: pass through)")
    ap.add_argument("--run-seconds", type=int, default=90)
    ap.add_argument("--commands", type=int, default=6)
    args = ap.parse_args(argv)
    import serial  # pyserial

    with open(args.log, "x") as log, open(args.device_log, "x") as dlog, \
            (open(args.truth, "x") if args.truth else open("/dev/null", "w")) as truth:
        port = serial.Serial(args.port, args.baud, timeout=0)  # opening resets the Uno
        clock = Clock()
        link = FaultLink(port, clock, truth, dlog, Plan.load(args.plan))
        client = Client(link, clock, log, args.seed, args.commands, args.run_seconds)
        deadline = time.monotonic() + 10
        while client.started_at is None:
            if time.monotonic() > deadline:
                print("no READY from the board within 10 s")
                return 2
            client.step(clock.now_us())
            time.sleep(0.001)
        while True:
            now = clock.now_us()
            if client.done(now):
                break
            client.step(now)
            time.sleep(0.0005)
        valid = client.finish(clock.now_us())
        port.close()
    print(f"run {'valid' if valid else 'INVALID'}: {args.log}, {args.device_log}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
