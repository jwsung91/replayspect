"""WP5b: driven replay of a client-side log, without a seed (replayspect.driven)."""

import json
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.driven import (DRIVEN_SEED, DrivenError, DrivenSetup, driven_match, driven_reconstruct,
                                later_replies, round_trips, rtt_start_plan, run_driven, shift_split,
                                split_sensitivity)
from replayspect.incident import Incident, run_incident, text_log, with_expect, write_incident
from replayspect.ingest import ingest_text, read_rules
from replayspect.reconstruct import Limits
from replayspect.runner import get_system
from replayspect.sim.link import FaultPlan
from replayspect.sut.lift import run_lift
from replayspect.sut.turntable import run_turntable
from replayspect.trace import Event
from replayspect.tracefile import read_trace_file

ROOT = Path(__file__).parent.parent
RULES = ROOT / "examples" / "rules" / "sim-client-ros.yaml"
VARIANTS = Path(__file__).parent / "neutral_variants.py"
LIFT = get_system("lift.v0")


def client_log(trace):
    return [e for e in trace.events if e.actor == "client"]


def recvs(events):
    return [(e.t_us, e.name, e.req_id, {k: v for k, v in e.data.items() if k != "link"})
            for e in events if e.actor == "client" and e.kind == "recv"]


# -- the run --------------------------------------------------------------------------------


@pytest.mark.parametrize("name,run", [("lift.v0", run_lift), ("turntable.v0", run_turntable)])
def test_the_true_link_plan_reproduces_every_client_receive_exactly(name, run):
    for seed in (1, 7, 23):
        hidden = run(seed)  # random faults: drops, duplicates, disconnects
        log = client_log(hidden)
        driven = run_driven(get_system(name), log, FaultPlan.from_trace(hidden), 90_000_000)
        assert recvs(driven.events) == recvs(hidden.events)


def test_nothing_depends_on_the_seed():
    log = client_log(run_lift(3))
    for plan in (FaultPlan.from_dict({"base": "fixed"}), FaultPlan.from_trace(run_lift(3))):
        digests = {run_driven(LIFT, log, plan, 90_000_000, seed=s).digest() for s in (DRIVEN_SEED, 1, 99)}
        assert len(digests) == 1


def test_script_sends_and_decides_as_recorded_and_fidelity_says_which_is_which():
    hidden = run_lift(5)
    log = client_log(hidden)
    driven = run_driven(LIFT, log, FaultPlan.from_trace(hidden), 90_000_000)
    facts = [(e.t_us, e.kind, e.name, e.req_id) for e in driven.events if e.actor == "client" and e.kind != "recv"]
    assert facts == [(e.t_us, e.kind, e.name, e.req_id) for e in log if e.kind != "recv"]
    for e in driven.events:
        fact = e.actor == "client" and e.kind != "recv"
        assert e.fidelity == ("exact" if fact else "reconstructed")


def test_refusals():
    log = client_log(run_lift(3))
    plan = FaultPlan.from_dict({"base": "fixed"})
    with pytest.raises(DrivenError, match="scripts the client side"):
        run_driven(LIFT, log, plan, 90_000_000, actor="device")
    with pytest.raises(DrivenError, match="also has device"):
        run_driven(LIFT, [*log, Event(0, 1, "device", "state", "UP")], plan, 90_000_000)
    with pytest.raises(DrivenError, match="past the run end"):
        run_driven(LIFT, log, plan, 1_000_000)
    with pytest.raises(DrivenError, match="the variant gives no device"):
        run_driven(get_system("lift.v0", f"{VARIANTS}:LIFT_PUBLIC_FAILING"), log, plan, 90_000_000)


def test_a_variant_with_a_device_can_be_driven():
    system = get_system("lift.v0", f"{VARIANTS}:LIFT_PUBLIC_FAILING_DEVICE")
    hidden = system.run(4, None, (), 90_000_000)
    driven = run_driven(system, client_log(hidden), FaultPlan.from_trace(hidden), 90_000_000)
    assert recvs(driven.events) == recvs(hidden.events)
    with pytest.raises(ValueError, match="takes no mutants"):
        run_driven(system, client_log(hidden), FaultPlan.from_trace(hidden), 90_000_000, mutants=("M1",))


# -- the judge ------------------------------------------------------------------------------


def test_judge_compares_receives_only_in_order_within_the_tolerance():
    hidden = run_lift(5)
    log = client_log(hidden)
    run = run_driven(LIFT, log, FaultPlan.from_trace(hidden), 90_000_000).events
    quiet = LIFT.quiet_messages
    m = driven_match(log, run, "client", quiet)
    assert m.reproduced and m.matched == m.total > 0 and m.max_dt_us == 0
    # Facts are not compared: dropping every handle from the log changes nothing.
    assert driven_match([e for e in log if e.kind != "handle"], run, "client", quiet).reproduced
    # A receive moved past the tolerance is the first mismatch, named by position.
    i = next(n for n, e in enumerate(log) if e.kind == "recv" and e.name not in quiet)
    late = [*log[:i], Event(log[i].seq, log[i].t_us + 300_000, "client", "recv", log[i].name, log[i].req_id,
                            log[i].data, log=({"line": 9})), *log[i + 1:]]
    bad = driven_match(late, run, "client", quiet)
    assert not bad.reproduced and bad.matched == 0 and bad.first["line"] == 9
    assert driven_match(late, run, "client", quiet, tolerance_us=400_000).reproduced
    # Expected contracts must agree when given.
    assert not driven_match(log, run, "client", quiet, violated=set(), expect={"C3"}).reproduced


def test_receives_after_the_horizon_are_not_compared():
    hidden = run_lift(5)
    first = client_log(hidden)[:1]  # the first command alone; its replies come later
    run = run_driven(LIFT, first, FaultPlan.from_dict({"base": "fixed"}), 90_000_000).events  # ACK at 20 ms
    quiet = LIFT.quiet_messages
    assert driven_match(first, run, "client", quiet, tolerance_us=1_000).reproduced
    assert not driven_match(first, run, "client", quiet, tolerance_us=1_000, horizon_us=90_000_000).reproduced


# -- round trips ------------------------------------------------------------------------------


def test_round_trips_pair_the_jth_reply_with_the_jth_attempt():
    # Lift seed 3: the first ACK (2.123 s) answers the first MOVE_UP (0 s), not the retry at 2 s.
    trips = round_trips(client_log(run_lift(3, plan=FaultPlan.from_dict({"base": "random"}))), "client", ("ACK",))
    first = trips[0]
    assert first[0]["k"] == 0 and first[1]["k"] == 0 and first[2] == 2_123_398
    assert trips[1][0]["k"] == 1 and trips[1][1]["k"] == 1


def test_rtt_start_plan_splits_round_trips_within_the_ranges():
    log = client_log(run_lift(3, plan=FaultPlan.from_dict({"base": "random"})))
    limits = DrivenSetup(LIFT, log, 90_000_000).limits()
    half = rtt_start_plan(log, "client", limits)
    assert half["base"] == "fixed"
    d = {(x["dir"], x["req_id"], x["k"]): x["delay_us"] for x in half["delays"]}
    assert d[("c2s", "r-0001", 0)] == 1_061_699 and d[("s2c", "r-0001", 0)] == 1_061_699
    low = rtt_start_plan(log, "client", limits, split=0.0)
    lo = {(x["dir"], x["req_id"], x["k"]): x["delay_us"] for x in low["delays"]}
    assert lo[("c2s", "r-0001", 0)] == 2_123_398 - 1_500_000  # the reply's range bounds the request's share
    assert Limits.ok(limits, half) and Limits.ok(limits, low)
    with pytest.raises(ValueError, match="split"):
        rtt_start_plan(log, "client", limits, split=1.5)


def test_shift_split_keeps_the_round_trip_and_optionally_later_replies():
    limits = DrivenSetup(LIFT, [], 90_000_000).limits()
    req = {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0}
    ack = {"dir": "s2c", "msg": "ACK", "req_id": "r-0001", "k": 0}
    done = {"dir": "s2c", "msg": "DONE", "req_id": "r-0001", "k": 0}
    plan = {"base": "fixed", "delays": [{**req, "delay_us": 500_000}, {**ack, "delay_us": 500_000},
                                        {**done, "delay_us": 600_000}], "faults": [], "disconnects": []}
    new = shift_split(plan, req, ack, 200_000, limits, later_replies=[done])
    got = {x["msg"]: x["delay_us"] for x in new["delays"]}
    assert got == {"MOVE_UP": 700_000, "ACK": 300_000, "DONE": 400_000}
    assert shift_split(plan, req, ack, 495_000, limits) is None  # the ACK would go below its minimum
    # A later reply at the base delay (not in the plan) is kept in place too.
    bare = {**plan, "delays": plan["delays"][:2]}
    earlier = shift_split(bare, req, ack, -200_000, limits, later_replies=[done])
    assert {x["msg"]: x["delay_us"] for x in earlier["delays"]}["DONE"] == 10_000 + 200_000
    assert shift_split(bare, req, ack, 200_000, limits, later_replies=[done]) is None  # below its minimum


# -- the reader -------------------------------------------------------------------------------


def test_reader_reproduces_without_the_seed_and_counts_start_entries_apart():
    log = client_log(run_lift(11, plan=FaultPlan.from_dict({"base": "random"})))
    setup = DrivenSetup(LIFT, log, 90_000_000)
    plain = driven_reconstruct(setup, budget=120)
    rtt = driven_reconstruct(setup, budget=120, rtt=True)
    assert plain.reconstructed and plain.start_entries == 0
    assert rtt.reconstructed and rtt.start_entries > 0 and rtt.runs < plain.runs
    assert setup.run(rtt.plan)[1].reproduced
    # max_edits limits search edits only: the start plan itself is never cut.
    capped = driven_reconstruct(setup, budget=120, rtt=True, max_edits=0)
    assert capped.status in ("cap", "reproduced") and capped.edits == [] and capped.start_entries == rtt.start_entries


def test_later_replies_are_read_off_the_log():
    log = [Event(0, 1, "client", "recv", "ACK", "r-1"), Event(1, 2, "client", "recv", "DONE", "r-1"),
           Event(2, 3, "client", "recv", "DONE", "r-2"), Event(3, 4, "client", "recv", "ERROR", "r-1")]
    assert later_replies(log, "client", "r-1", ("ACK",)) == [
        {"dir": "s2c", "msg": "DONE", "req_id": "r-1", "k": 0}, {"dir": "s2c", "msg": "ERROR", "req_id": "r-1", "k": 0}]


def test_with_the_true_plan_no_round_trip_is_sensitive_unless_the_device_outcome_changes():
    # Correct lift, no defect: moving when a command arrives keeps every receive time, so nothing breaks
    # unless the device's answer itself changes (an arrival moved past another command or a timeout).
    hidden = run_lift(5)
    log = client_log(hidden)
    setup = DrivenSetup(LIFT, log, 90_000_000)
    s = split_sensitivity(setup, FaultPlan.from_trace(hidden).to_dict())
    assert s.pairs > 0 and s.sensitive < s.pairs


def test_split_sensitivity_counts_round_trips_the_log_does_not_pin_down():
    log = client_log(run_lift(11, plan=FaultPlan.from_dict({"base": "random"})))
    setup = DrivenSetup(LIFT, log, 90_000_000)
    res = driven_reconstruct(setup, budget=120, rtt=True)
    s = split_sensitivity(setup, res.plan)
    assert 0 <= s.sensitive <= s.pairs and s.pairs > 0 and len(s.keys) == s.sensitive


# -- text logs and the command line ------------------------------------------------------------


def test_text_log_round_trips_through_ingest():
    hidden = run_lift(5)
    for ms in (False, True):
        res = ingest_text(text_log(hidden.events, "client", ms=ms).encode(), read_rules(RULES))
        assert not res.unmatched and res.events[0].t_us == 0
        want = [(e.t_us // (1000 if ms else 1) * (1000 if ms else 1), e.kind, e.name, e.req_id)
                for e in client_log(hidden)]
        assert [(e.t_us, e.kind, e.name, e.req_id) for e in res.events] == want
        assert recvs(res.events) == [(t // (1000 if ms else 1) * (1000 if ms else 1), n, r, d)
                                     for t, n, r, d in recvs(hidden.events)]


def incident_file(tmp_path):
    inc = with_expect(Incident("lift.v0", 5, FaultPlan.from_dict({"base": "random"}), 90_000_000, "device",
                               mutants=("M4",)))
    return write_incident(inc, tmp_path / "inc.json"), inc


def test_cli_incident_text_ingest_drive_and_rewind(tmp_path, capsys):
    f, inc = incident_file(tmp_path)
    log, trace, run = tmp_path / "c.log", tmp_path / "c.jsonl", tmp_path / "run.jsonl"
    assert main(["incident", "text", str(f), "--out", str(log)]) == 0
    assert main(["incident", "text", str(f), "--out", str(log)]) == 2  # never overwrites
    assert main(["ingest", str(log), "--rules", str(RULES), "--out", str(trace)]) == 0
    capsys.readouterr()
    expect = sorted(run_incident(inc).violated()) or ["none"]
    args = ["drive", str(trace), "--mutant", "M4", "--until", "90s", "--reconstruct", "--rtt", "--sensitivity",
            "--trace-out", str(run), "--plan-out", str(tmp_path / "plan.json")]
    if expect != ["none"]:
        args += ["--expect", *expect]
    code = main(args)
    out = capsys.readouterr().out
    assert "client side scripted" in out and "start delays from round trips (split 0.5)" in out
    assert code in (0, 1) and ("reproduced: yes" in out) == (code == 0)
    tf = read_trace_file(run)
    assert tf.header.origin == "2026-11-10T08:00:00.000000+09:00"
    if code == 0:
        assert "split sensitivity:" in out
        assert any(e.log and e.fidelity == "reconstructed" for e in tf.trace.events)
        assert main(["rewind", str(run), "--actor", "client", "--window", "0", "10s"]) == 0
        assert "[matches log line" in capsys.readouterr().out
    assert json.loads((tmp_path / "plan.json").read_text())["base"] == "fixed"


def test_cli_drive_plain_plan_and_errors(tmp_path, capsys):
    hidden = run_lift(5)
    log = tmp_path / "c.log"
    log.write_text(text_log(hidden.events, "client"))
    trace = tmp_path / "c.jsonl"
    assert main(["ingest", str(log), "--rules", str(RULES), "--out", str(trace)]) == 0
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps(FaultPlan.from_trace(hidden).to_dict()))
    capsys.readouterr()
    assert main(["drive", str(trace), "--plan", str(plan), "--until", "90s"]) == 0
    assert "largest time difference 0.000ms" in capsys.readouterr().out
    assert main(["drive", str(trace), "--until", "90s"]) == 1  # base fixed, no faults: not the same run
    assert main(["drive", str(trace), "--plan", str(plan), "--reconstruct"]) == 2
    assert "cannot be combined" in capsys.readouterr().err
    assert main(["drive", str(trace), "--system", "turntable.v0", "--variant", f"{VARIANTS}:SAME_TURNTABLE"]) == 2
    assert "gives no device" in capsys.readouterr().err
