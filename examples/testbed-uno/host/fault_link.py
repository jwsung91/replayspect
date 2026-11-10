"""The link between the testbed client and the Uno (WP5c).

It sits between the client and the serial port. Stage 1 passes every line through unchanged and
writes what it did to a ground-truth file. Stage 2 (its own instruction) will apply fault plans:
per-message delay, drop, duplicate and disconnect windows.

Lines from the device that start with ``#`` are device log lines. They are not passed to the
client; they go to the device log file with the Orin receive time in front. ``# ... error ...``
lines are counted: any of them makes the run invalid.

Standard library only (the serial port object is passed in).
"""

from __future__ import annotations


class FaultLink:
    def __init__(self, port, clock, truth=None, device_log=None, plan_id: str = "none"):
        self.port, self.clock = port, clock
        self.truth, self.device_log = truth, device_log
        self.plan_id = plan_id
        self.errors: list[str] = []
        self._buf = b""

    # -- client to device ---------------------------------------------------------------------

    def write_line(self, line: str) -> None:
        self.port.write((line + "\n").encode("ascii"))
        self._record("c2s", "pass", line)

    # -- device to client ---------------------------------------------------------------------

    def poll(self) -> list[str]:
        """Protocol lines received since the last call (device log lines are filed, not returned)."""
        n = getattr(self.port, "in_waiting", 0)
        if n:
            self._buf += self.port.read(n)
        out = []
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            # NUL bytes arrive around a reset (seen before READY on a real Uno): not part of any line
            line = raw.replace(b"\x00", b"").rstrip(b"\r").decode("ascii", errors="replace")
            if not line:
                continue
            if line.startswith("#"):
                self._device_line(line)
                continue
            self._record("s2c", "pass", line)
            out.append(line)
        return out

    def _device_line(self, line: str) -> None:
        if self.device_log is not None:
            self.device_log.write(f"{self.clock.stamp()} {line}\n")
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "error":
            self.errors.append(line)

    def _record(self, direction: str, action: str, line: str) -> None:
        if self.truth is not None:
            self.truth.write(f"{self.clock.stamp()} {direction} {action} {line}\n")
