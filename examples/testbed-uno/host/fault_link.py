"""The link between the testbed client and the Uno (WP5c).

It sits between the client and the serial port and applies a fault plan in the simulator's
vocabulary (docs/plan-format.md): per-message extra delay, drop or duplicate, keyed by
``(dir, msg, req_id, k)`` where ``k`` counts sends of the same ``(dir, msg, req_id)``; and
disconnect windows. With no plan it passes every line through.

* **Delay:** the message is held for ``delay_ms`` on top of the physical link.
* **Duplicate:** a second copy goes ``dup_extra_ms`` after the first.
* **Disconnect:** a window anchored on an event (``after``: ``"c2s MOVE_UP r-0003 0"`` or an s2c
  key), starting ``offset_ms`` (>= 0) after it, lasting ``duration_ms``. In the window nothing
  passes either way. A message sent in the window, or held across its start, is lost, as in the
  simulator. The client is told when the window opens and closes (``on_change``).

What the link actually did is written, one JSON line per message or window event, to the
ground-truth file (``t_us`` since the client clock's start). That file is the hidden answer of
testbed-01 and stays outside the repository.

Lines from the device that start with ``#`` are device log lines: not passed to the client but
filed with the receive time in front. Any ``# ... error ...`` line is counted (an invalid run).

Standard library only (the serial port object is passed in).
"""

from __future__ import annotations

import json


def _key(direction: str, line: str, counts: dict) -> tuple[str, str, str | None, int]:
    parts = line.split()
    msg, rid = parts[0], (parts[1] if len(parts) > 1 else None)
    k = counts.get((direction, msg, rid), 0)
    counts[(direction, msg, rid)] = k + 1
    return direction, msg, rid, k


class Plan:
    def __init__(self, d: dict | None = None):
        d = d or {}
        self.id = d.get("id", "none")
        self.faults: dict[tuple, dict] = {}
        for f in d.get("faults", []):
            key = (f["dir"], f["msg"], f.get("req_id"), int(f.get("k", 0)))
            acts = [a for a in ("delay_ms", "drop", "dup_extra_ms") if f.get(a) not in (None, False)]
            if len(acts) != 1:
                raise ValueError(f"fault {f}: give exactly one of delay_ms, drop, dup_extra_ms")
            self.faults[key] = f
        self.disconnects = []
        for w in d.get("disconnects", []):
            if w["offset_ms"] < 0 or w["duration_ms"] <= 0:
                raise ValueError(f"disconnect {w}: offset_ms must be >= 0 and duration_ms > 0")
            d0, msg, rid, k = w["after"].split()
            self.disconnects.append({"after": (d0, msg, rid, int(k)), "offset_us": int(w["offset_ms"] * 1000),
                                     "duration_us": int(w["duration_ms"] * 1000)})

    @classmethod
    def load(cls, path: str | None) -> "Plan":
        if not path or path == "none":
            return cls()
        with open(path) as f:
            d = json.load(f)
        d.setdefault("id", path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        return cls(d)


class FaultLink:
    def __init__(self, port, clock, truth=None, device_log=None, plan: Plan | None = None):
        self.port, self.clock = port, clock
        self.truth, self.device_log = truth, device_log
        self.plan = plan or Plan()
        self.plan_id = self.plan.id
        self.errors: list[str] = []
        self.build: str | None = None  # the build line's defect field, filed in the truth file
        self.on_change = None  # callback(up: bool, now_us: int), set by the client
        self._buf = b""
        self._counts: dict = {}
        self._c2s: list[tuple[int, int, str, tuple, str]] = []  # (due, order, line, key, what) held toward the device
        self._s2c: list[tuple[int, int, str, tuple, str]] = []  # held toward the client
        self._order = 0
        self._windows: list[tuple[int, int]] = []  # (start, end) scheduled or open
        self._down_since: int | None = None
        self._epoch = 0  # disconnect count: a message held across a window start is lost

    # -- windows --------------------------------------------------------------------------------

    def _anchor(self, key: tuple, now: int) -> None:
        for w in self.plan.disconnects:
            if w["after"] == key and not w.get("used"):
                w["used"] = True
                self._windows.append((now + w["offset_us"], now + w["offset_us"] + w["duration_us"]))
        self._update(now)

    def _update(self, now: int) -> None:
        """Open or close windows due by ``now``."""
        for start, end in sorted(self._windows):
            if self._down_since is None and start <= now < end:
                self._down_since = start
                self._epoch += 1
                self._record({"t_us": start, "action": "disconnect", "duration_us": end - start})
                if self.on_change:
                    self.on_change(False, start)
            if self._down_since == start and now >= end:
                self._down_since = None
                self._windows.remove((start, end))
                self._record({"t_us": end, "action": "reconnect"})
                if self.on_change:
                    self.on_change(True, end)
        self._windows = [w for w in self._windows if w[1] > now or self._down_since == w[0]]

    def down(self) -> bool:
        return self._down_since is not None

    # -- one message through the plan ----------------------------------------------------------------

    def _apply(self, direction: str, line: str, now: int, queue: list) -> None:
        key = _key(direction, line, self._counts)
        if direction == "c2s":
            self._anchor(key, now)
        else:
            self._anchor(key, now)
        base = {"t_us": now, "dir": key[0], "msg": key[1], "req_id": key[2], "k": key[3]}
        if self.down():
            self._record({**base, "action": "lost_in_disconnect"})
            return
        f = self.plan.faults.get(key)
        if f is None:
            self._hold(queue, now, line, key, "pass", base)
        elif f.get("drop"):
            self._record({**base, "action": "drop"})
        elif f.get("delay_ms") is not None:
            self._hold(queue, now + int(f["delay_ms"] * 1000), line, key, "delay", {**base, "delay_ms": f["delay_ms"]})
        else:
            self._hold(queue, now, line, key, "pass", base)
            self._hold(queue, now + int(f["dup_extra_ms"] * 1000), line, key, "dup",
                       {**base, "dup_extra_ms": f["dup_extra_ms"]})

    def _hold(self, queue: list, due: int, line: str, key: tuple, what: str, rec: dict) -> None:
        self._order += 1
        queue.append((due, self._order, line, key, what, self._epoch, rec))

    def _release(self, queue: list, now: int) -> list[str]:
        out = []
        for item in sorted(q for q in queue if q[0] <= now):
            queue.remove(item)
            due, _, line, key, what, epoch, rec = item
            if self.down() or epoch != self._epoch:
                self._record({**rec, "action": "lost_in_disconnect", "t_out_us": due})
                continue
            self._record({**rec, "action": what, "t_out_us": due})
            out.append(line)
        return out

    # -- client to device ---------------------------------------------------------------------

    def write_line(self, line: str) -> None:
        now = self.clock.now_us()
        self._update(now)
        self._apply("c2s", line, now, self._c2s)
        self._flush(now)

    def _flush(self, now: int) -> None:
        for line in self._release(self._c2s, now):
            self.port.write((line + "\n").encode("ascii"))

    # -- device to client ---------------------------------------------------------------------

    def poll(self) -> list[str]:
        """Lines for the client now (device log lines are filed, not returned)."""
        now = self.clock.now_us()
        self._update(now)
        self._flush(now)
        n = getattr(self.port, "in_waiting", 0)
        if n:
            self._buf += self.port.read(n)
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            # NUL bytes arrive around a reset (seen before READY on a real Uno): not part of any line
            line = raw.replace(b"\x00", b"").rstrip(b"\r").decode("ascii", errors="replace")
            if not line:
                continue
            if line.startswith("#"):
                self._device_line(line)
                continue
            if line.startswith("READY"):  # boot line: not a protocol message, never faulted
                self._hold(self._s2c, now, line, ("s2c", "READY", None, 0), "pass",
                           {"t_us": now, "dir": "s2c", "msg": "READY", "req_id": None, "k": 0})
                continue
            self._apply("s2c", line, now, self._s2c)
        return self._release(self._s2c, now)

    def _device_line(self, line: str) -> None:
        parts = line.split()
        # The experiment's answer goes to the truth file, never to the device log: the build line
        # ("# 0 build defect=M4") and, from an older build, "# T defect fired M4 r-0004".
        if len(parts) >= 3 and (parts[2].startswith("build") or parts[2:4] == ["defect", "fired"]):
            if parts[2].startswith("build"):
                self.build = next((w.split("=", 1)[1] for w in parts[2:] if w.startswith("defect=")), "")
            rec = {"action": "build" if parts[2].startswith("build") else "defect_fired",
                   "t_us": self.clock.now_us(), "device_ms": int(parts[1]) if parts[1].isdigit() else None,
                   "line": line[1:].strip()}
            self._record(rec)
            return
        if self.device_log is not None:
            self.device_log.write(f"{self.clock.stamp()} {line}\n")
        if len(parts) >= 3 and parts[2] == "error":
            self.errors.append(line)

    def _record(self, rec: dict) -> None:
        if self.truth is not None:
            self.truth.write(json.dumps(rec, sort_keys=True) + "\n")
