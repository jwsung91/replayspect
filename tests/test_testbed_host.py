"""WP5c stage 1: the testbed client and link, end to end without hardware.

A fake port answers as the lift model would, with a fixed link delay each way. The client's log
must ingest with rules/testbed-client.yaml and reproduce by driven replay with an empty plan at
that delay, every receive within a millisecond.
"""

import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.ingest import ingest_text, read_rules
from replayspect.sim.link import Message
from replayspect.sim.scheduler import Scheduler
from replayspect.sut.lift import LiftDevice
from replayspect.trace import Trace

TB = Path(__file__).parent.parent / "examples" / "testbed-uno"
sys.path.insert(0, str(TB / "host"))
import client as tb_client  # noqa: E402
from fault_link import FaultLink  # noqa: E402

RULES = TB / "rules" / "testbed-client.yaml"
WALL = datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone(timedelta(hours=9)))


class FakeTime:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakePort:
    """The lift model behind a link with a fixed delay each way, in milliseconds."""

    def __init__(self, clock, delay_ms=3, extra=b""):
        self.clock, self.delay = clock, delay_ms
        self.sched = Scheduler(0)
        self.trace = Trace(lambda: self.sched.now_us)
        self.pending = [(0, b"READY log=1 defect=none\n" + extra)]
        self.buf = b""
        port = self

        class Ch:
            def attach(self, endpoint, on_message, on_connection=None):
                port.on_message = on_message

            def send(self, sender, msg):
                fields = "".join(f" {k}={v}" for k, v in sorted(msg.fields.items()))
                port.pending.append((port.sched.now_us // 1000 + port.delay, f"{msg.name} {msg.req_id}{fields}\n".encode()))

        LiftDevice(self.sched, self.trace, Ch(), frozenset())

    def _advance(self):
        now = self.clock.now_ms()
        self.sched.run_until_us(now * 1000)
        due = [p for p in self.pending if p[0] <= now]
        self.pending = [p for p in self.pending if p[0] > now]
        for _, b in sorted(due, key=lambda p: p[0]):
            self.buf += b

    @property
    def in_waiting(self):
        self._advance()
        return len(self.buf)

    def read(self, n):
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def write(self, data):
        now = self.clock.now_ms()
        for line in data.decode().splitlines():
            name, rid = line.split()
            self.sched.at_us((now + self.delay) * 1000, lambda n=name, r=rid: self.on_message(Message(n, r, {})))


def run_client(run_s=90, extra=b"", seed=0):
    ft = FakeTime()
    clock = tb_client.Clock(WALL, ft)
    port = FakePort(clock, extra=extra)
    log, dlog, truth = io.StringIO(), io.StringIO(), io.StringIO()
    link = FaultLink(port, clock, truth, dlog)
    c = tb_client.Client(link, clock, log, seed=seed, run_s=run_s)
    while c.started_at is None:
        c.step(clock.now_ms())
        ft.t += 0.001
    while not c.done(clock.now_ms()):
        c.step(clock.now_ms())
        ft.t += 0.001
    valid = c.finish(clock.now_ms())
    return log.getvalue(), dlog.getvalue(), truth.getvalue(), valid


@pytest.fixture(scope="module")
def clean():
    return run_client()


def test_client_log_has_a_header_and_ingests_cleanly(clean):
    log, _, truth, valid = clean
    first, last = log.splitlines()[0], log.splitlines()[-1]
    assert valid and "# testbed client: firmware log=1 defect=none; think_seed=0; plan=none" in first
    assert last.endswith("# end valid=yes")
    res = ingest_text(log.encode(), read_rules(RULES))
    assert not res.unmatched and res.ignored == 2
    kinds = {e.kind for e in res.events}
    assert kinds == {"send", "recv", "handle"}
    assert sum(e.kind == "handle" for e in res.events) == 6
    assert truth.count(" c2s pass ") == sum(e.kind == "send" for e in res.events)


def test_clean_run_reproduces_with_an_empty_plan_at_the_link_delay(clean, tmp_path, capsys):
    log, *_ = clean
    lp, tp = tmp_path / "client.log", tmp_path / "client.jsonl"
    lp.write_text(log)
    assert main(["ingest", str(lp), "--rules", str(RULES), "--out", str(tp)]) == 0
    capsys.readouterr()
    assert main(["drive", str(tp), "--link-delay", "3ms", "3ms", "--residuals"]) == 0
    out = capsys.readouterr().out
    assert "reproduced: yes" in out and "residuals (recorded - simulated)" in out
    assert "max 0.000 ms" in out.split("residuals")[1].splitlines()[0]
    # The profile's 10 ms minimum would put every receive 14 ms late: still within 250 ms, not 0.
    assert main(["drive", str(tp), "--residuals"]) == 0
    assert "min -14.000" in capsys.readouterr().out


def test_device_error_or_reset_makes_the_run_invalid():
    log, dlog, _, valid = run_client(run_s=5, extra=b"# 3 error table_full r-0009\n")
    assert not valid and log.splitlines()[-1].endswith("valid=no reasons=device_errors=1")
    assert "error table_full" in dlog
    log, _, _, valid = run_client(run_s=5, extra=b"READY log=1 defect=none\n")
    assert not valid and "resets=1" in log.splitlines()[-1] and "READY again" in log


def test_timestamps_follow_the_monotonic_clock_from_one_wall_reading():
    ft = FakeTime()
    c = tb_client.Clock(WALL, ft)
    ft.t = 1.2345
    assert c.stamp() == "2026-11-11T10:00:01.234+09:00"
