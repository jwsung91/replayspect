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
from fault_link import FaultLink, Plan  # noqa: E402

RULES = TB / "rules" / "testbed-client.yaml"
WALL = datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone(timedelta(hours=9)))


class FakeTime:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakePort:
    """The lift model behind a link with a fixed delay each way, in milliseconds."""

    def __init__(self, clock, delay_ms=3, extra=b"", ready=b"READY log=1"):
        self.clock, self.delay = clock, delay_ms
        self.sched = Scheduler(0)
        self.trace = Trace(lambda: self.sched.now_us)
        self.pending = [(0, ready + b"\n" + extra)]
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
        now = self.clock.now_us() // 1000
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
        now = self.clock.now_us() // 1000
        for line in data.decode().splitlines():
            name, rid = line.split()
            self.sched.at_us((now + self.delay) * 1000, lambda n=name, r=rid: self.on_message(Message(n, r, {})))


def run_client(run_s=90, extra=b"", seed=0, plan=None, ready=b"READY log=1"):
    ft = FakeTime()
    clock = tb_client.Clock(WALL, ft)
    port = FakePort(clock, extra=extra, ready=ready)
    log, dlog, truth = io.StringIO(), io.StringIO(), io.StringIO()
    link = FaultLink(port, clock, truth, dlog, Plan(plan))
    c = tb_client.Client(link, clock, log, seed=seed, run_s=run_s)
    while c.started_at is None:
        c.step(clock.now_us())
        ft.t += 0.001
    while not c.done(clock.now_us()):
        c.step(clock.now_us())
        ft.t += 0.001
    valid = c.finish(clock.now_us())
    return log.getvalue(), dlog.getvalue(), truth.getvalue(), valid


@pytest.fixture(scope="module")
def clean():
    return run_client()


def test_client_log_has_a_header_and_ingests_cleanly(clean):
    log, _, truth, valid = clean
    first, last = log.splitlines()[0], log.splitlines()[-1]
    assert valid and "# testbed client: firmware log=1; think_seed=0; plan=none" in first
    assert last.endswith("# end valid=yes")
    res = ingest_text(log.encode(), read_rules(RULES))
    assert not res.unmatched and res.ignored == 2
    kinds = {e.kind for e in res.events}
    assert kinds == {"send", "recv", "handle"}
    assert sum(e.kind == "handle" for e in res.events) == 6
    import json
    recs = [json.loads(x) for x in truth.splitlines()]
    assert sum(r.get("dir") == "c2s" and r["action"] == "pass" for r in recs) == sum(e.kind == "send" for e in res.events)


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
    log, _, _, valid = run_client(run_s=5, extra=b"READY log=1\n")
    assert not valid and "resets=1" in log.splitlines()[-1] and "READY again" in log


def test_the_client_log_never_names_a_defect():
    # Stage 3: the build's defect is the answer. The firmware names it only in the device log; a
    # READY that still names one (an older build) is not copied into the client log either.
    log, dlog, truth, valid = run_client(run_s=3, ready=b"READY log=1 defect=M4", extra=b"# 0 build defect=M4\n")
    assert valid and "defect" not in log and "firmware log=1;" in log.splitlines()[0]


def test_the_build_line_and_any_defect_fired_line_go_to_the_truth_file_not_the_device_log():
    # The device log is an input to the analysis; the build's defect is the answer. An older build's
    # "defect fired" line is filed with it.
    extra = b"# 0 build defect=M4\n# 0 state DOWN from=- on=init\n# 8050 defect fired M4 r-0004\n"
    _, dlog, truth, valid = run_client(run_s=3, extra=extra)
    assert valid and "defect" not in dlog and "# 0 state DOWN from=- on=init" in dlog
    recs = [r for r in truth_of(truth) if r["action"] in ("build", "defect_fired")]
    assert [(r["action"], r["device_ms"], r["line"]) for r in recs] == [
        ("build", 0, "0 build defect=M4"), ("defect_fired", 8050, "8050 defect fired M4 r-0004")]


def test_nul_bytes_around_a_reset_are_dropped():
    # A real Uno sent b"\x00\x00READY ..." after the port opened.
    class Port:
        in_waiting = 30
        def read(self, n):
            return b"\x00\x00READY log=0 defect=none\n"
    link = FaultLink(Port(), tb_client.Clock(WALL, FakeTime()))
    assert link.poll() == ["READY log=0 defect=none"]


def truth_of(truth):
    import json
    return [json.loads(x) for x in truth.splitlines()]


def test_plan_faults_are_applied_and_recorded():
    plan = {"id": "t", "faults": [
        {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "drop": True},
        {"dir": "s2c", "msg": "ACK", "req_id": "r-0002", "k": 0, "delay_ms": 2500},
        {"dir": "s2c", "msg": "DONE", "req_id": "r-0003", "k": 0, "dup_extra_ms": 500}]}
    log, _, truth, valid = run_client(run_s=60, plan=plan)
    recs = truth_of(truth)
    assert valid and "plan=t" in log.splitlines()[0]
    acts = {(r["dir"], r["msg"], r["req_id"], r["k"]): r["action"] for r in recs if "msg" in r and r["action"] != "pass"}
    assert acts[("c2s", "MOVE_UP", "r-0001", 0)] == "drop"
    assert acts[("s2c", "ACK", "r-0002", 0)] == "delay" and acts[("s2c", "DONE", "r-0003", 0)] == "dup"
    assert "TX MOVE_UP req=r-0001" in log and log.count("TX MOVE_UP req=r-0001") == 2  # the drop forced a retry
    assert log.count("RX DONE req=r-0003") == 2


def test_disconnect_window_is_anchored_logged_and_resent_after():
    plan = {"id": "d", "disconnects": [{"after": "c2s MOVE_UP r-0001 0", "offset_ms": 100, "duration_ms": 1500}]}
    log, _, truth, valid = run_client(run_s=10, plan=plan)
    lines = log.splitlines()
    down = next(i for i, x in enumerate(lines) if x.endswith(" link down"))
    up = next(i for i, x in enumerate(lines) if x.endswith(" link up"))
    assert valid and down < up
    recs = truth_of(truth)
    assert [r["action"] for r in recs if r["action"] in ("disconnect", "reconnect")] == ["disconnect", "reconnect"]
    d = next(r for r in recs if r["action"] == "disconnect")
    assert d["duration_us"] == 1_500_000
    assert any(r["action"] == "lost_in_disconnect" for r in recs)  # the ACK in flight, or a poll


def test_messages_lost_to_a_logged_disconnect_are_not_counted_as_faults():
    plan = {"id": "d", "disconnects": [{"after": "c2s MOVE_UP r-0003 0", "offset_ms": 0, "duration_ms": 1500}]}
    log, *_ = run_client(run_s=40, plan=plan)
    from replayspect.driven import DrivenSetup
    from replayspect.fit import Ranges, fit_log
    from replayspect.runner import get_system
    ev = ingest_text(log.encode(), read_rules(RULES)).events
    res = fit_log(DrivenSetup(get_system("lift.v0"), ev, ev[-1].t_us + 25_000, tolerance_us=25_000),
                  Ranges((0, 5_000_000), (0, 5_000_000), (0, 5_000_000)))
    assert res.reproduced and res.fit.drops == 0 and not res.fit.plan["faults"]


def test_bad_plans_are_refused():
    with pytest.raises(ValueError, match="exactly one"):
        Plan({"faults": [{"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "drop": True, "delay_ms": 5}]})
    with pytest.raises(ValueError, match="offset_ms must be >= 0"):
        Plan({"disconnects": [{"after": "c2s MOVE_UP r-0001 0", "offset_ms": -1, "duration_ms": 5}]})


def test_timestamps_follow_the_monotonic_clock_from_one_wall_reading():
    ft = FakeTime()
    c = tb_client.Clock(WALL, ft)
    ft.t = 1.2345
    assert c.stamp() == "2026-11-11T10:00:01.234500+09:00"


# -- windows chosen from the log alone -----------------------------------------------------------

from replayspect.driven import DrivenSetup  # noqa: E402
from replayspect.fit import Ranges, anomaly_windows, fit_log  # noqa: E402
from replayspect.runner import get_system  # noqa: E402


def ingested(log):
    return ingest_text(log.encode(), read_rules(RULES)).events


def test_anomaly_windows_find_late_done_and_retries_and_nothing_in_a_clean_log(clean):
    lift = get_system("lift.v0")
    assert anomaly_windows(ingested(clean[0]), "client", lift.quiet_messages) == []
    plan = {"id": "w", "faults": [{"dir": "s2c", "msg": "DONE", "req_id": "r-0002", "k": 0, "delay_ms": 1000},
                                  {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0003", "k": 0, "drop": True}]}
    log, *_ = run_client(run_s=60, plan=plan)
    wins = anomaly_windows(ingested(log), "client", lift.quiet_messages)
    why = "; ".join(w for _, _, ws in wins for w in ws)
    assert "r-0002: late DONE" in why and "r-0003: retry" in why


def test_window_fit_judges_only_its_window():
    lift = get_system("lift.v0")
    plan = {"id": "w", "faults": [{"dir": "s2c", "msg": "DONE", "req_id": "r-0002", "k": 0, "delay_ms": 1000}]}
    log, *_ = run_client(run_s=40, plan=plan)
    events = ingested(log)
    (a, b, _), = anomaly_windows(events, "client", lift.quiet_messages)
    setup = DrivenSetup(lift, events, 40_000_000, tolerance_us=25_000)
    ranges = Ranges((0, 5_000_000), (0, 5_000_000), (0, 5_000_000))
    res = fit_log(setup, ranges, window=(a, b))
    assert res.reproduced and res.window == (a, b)
    assert "in window" in "\n".join(__import__("replayspect.fit", fromlist=["x"]).report_lines(res))


def test_cli_window_auto(tmp_path, capsys):
    plan = {"id": "w", "faults": [{"dir": "s2c", "msg": "DONE", "req_id": "r-0002", "k": 0, "delay_ms": 1000}]}
    log, *_ = run_client(run_s=40, plan=plan)
    lp, tp = tmp_path / "c.log", tmp_path / "c.jsonl"
    lp.write_text(log)
    assert main(["ingest", str(lp), "--rules", str(RULES), "--out", str(tp)]) == 0
    capsys.readouterr()
    assert main(["drive", str(tp), "--fit", "--link-delay", "0", "5s", "--tolerance", "25ms", "--window", "auto"]) == 0
    out = capsys.readouterr().out
    assert "windows: 1" in out and "late DONE" in out and "fit in window" in out
    assert main(["drive", str(tp), "--fit", "--window", "1s"]) == 2
