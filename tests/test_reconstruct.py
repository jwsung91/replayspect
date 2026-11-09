"""Rule-based reconstruction of a fault plan from one participant's log (WP4 main baseline).

Every incident here uses the lift's correct implementation or its published mutants.
"""

import json

import pytest

from replayspect.__main__ import main
from replayspect.bridge import BridgeConfig, BridgeSession, read_log, reconstruct_baseline, summarize_log
from replayspect.incident import Incident, run_incident, run_view, view_text, with_expect, write_incident
from replayspect.reconstruct import MAX_TRIES_PER_LINE, Feedback, Limits, empty_plan, reconstruct
from replayspect.runner import get_system
from replayspect.sim.link import FaultPlan
from replayspect.tracefile import canonical, parse_trace_file

LIFT = get_system("lift.v0")
#: Lift M1 (published), seed 4: a duplicate of the first command arriving 1 s later makes it run twice.
DUP = {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "dup_extra_us": 1_000_000}
#: Correct lift, seed 4: the first command is lost and its first resend arrives late.
DROP_DELAY = {"base": "random", "disconnects": [],
              "faults": [{"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "drop": True}],
              "delays": [{"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 1, "delay_us": 1_200_000}]}


def write(tmp_path, plan, actor="device", offset=0, mutants=(), name="incident.json"):
    inc = with_expect(Incident("lift.v0", 4, FaultPlan.from_dict(plan), 90_000_000, actor, offset, mutants))
    return str(write_incident(inc, tmp_path / name))


def dup_plan():
    return {"base": "random", "delays": [], "faults": [DUP], "disconnects": []}


@pytest.mark.parametrize("actor,offset", [("device", 0), ("client", 2_500_000)])
@pytest.mark.parametrize("plan,mutants", [(dup_plan(), ("M1",)), (DROP_DELAY, ())])
def test_reconstructs_small_incidents_from_either_side(tmp_path, plan, mutants, actor, offset):
    f = write(tmp_path, plan, actor, offset, mutants)
    s, r = reconstruct_baseline(BridgeConfig(f), tmp_path / "log.jsonl")
    assert r.status == "reproduced", r.reason
    assert r.runs < 40
    summary = summarize_log(tmp_path / "log.jsonl")
    assert summary["reproduced"] and summary["runs_to_reproduction"] == r.runs
    if offset:
        assert abs(r.offset_us - offset) < 100_000  # read off the log, never told


def test_run_view_keeps_the_runs_own_link_data():
    run = run_incident(with_expect(Incident("lift.v0", 4, FaultPlan.from_dict(DROP_DELAY), 90_000_000, "device")))
    view = run_view(run.trace, "device")
    assert [e.seq for e in view] == list(range(len(view)))
    assert {e.actor for e in view} == {"device"}
    recv = next(e for e in view if e.kind == "recv" and e.name == "MOVE_UP")
    link = recv.data["link"]
    assert link["k"] == 1 and link["delay_us"] == 1_200_000  # the dropped k=0 never arrived
    assert recv.t_us == link["sent_us"] + link["delay_us"]


def test_reads_only_the_planner_log_and_never_reruns_a_plan(tmp_path):
    """The WP5 path: a trace file of one side plus an oracle; nothing else about the hidden run."""
    f = write(tmp_path, DROP_DELAY, "client", 1_700_000)
    session = BridgeSession(BridgeConfig(f))
    log = parse_trace_file(session.describe()["log"]).trace
    assert all("link" not in e.data for e in log)
    plans = []

    def oracle(plan):
        plans.append(canonical(plan))
        out = session.run_plan(plan)
        rep = out["reproduction"]
        return Feedback(rep["reproduced"], int(rep["lines_matched"].split("/")[0]),
                        run_view(session.last_run.trace, "client"))

    r = reconstruct(log, "client", LIFT.quiet_messages, ("STATUS", "STATUS_REPLY"),
                    Limits.from_describe(session.describe()["limits"]), oracle, clock_known=False)
    assert r.status == "reproduced"
    assert len(plans) == len(set(plans)) == r.runs
    assert plans[0] == canonical(empty_plan())


def test_cap_is_reported_with_the_furthest_mismatch(tmp_path):
    f = write(tmp_path, DROP_DELAY, "client", 1_000_000)
    _, r = reconstruct_baseline(BridgeConfig(f), max_edits=1)
    assert r.status == "cap" and not r.reconstructed
    assert len(r.edits) == 1 and "1 edits kept" in r.reason


def test_stuck_when_no_edit_improves_the_first_mismatch(tmp_path):
    """An oracle whose answer never changes: the same mismatch keeps coming back."""
    f = write(tmp_path, DROP_DELAY)
    session = BridgeSession(BridgeConfig(f))
    log = parse_trace_file(session.describe()["log"]).trace
    session.run_plan(empty_plan())
    frozen = Feedback(False, 1, run_view(session.last_run.trace, "device"))
    calls = []

    def oracle(plan):
        calls.append(plan)
        return frozen

    r = reconstruct(log, "device", LIFT.quiet_messages, ("STATUS", "STATUS_REPLY"),
                    Limits.from_describe(session.describe()["limits"]), oracle, clock_known=True)
    assert r.status == "stuck" and r.reason.startswith("no edit improves line 1: expected ")
    assert len(calls) == r.runs <= 1 + MAX_TRIES_PER_LINE  # one step's tries, then give up


def test_budget_ends_the_search(tmp_path):
    f = write(tmp_path, DROP_DELAY)
    s, r = reconstruct_baseline(BridgeConfig(f, budget=2), tmp_path / "log.jsonl")
    assert r.status == "budget" and r.runs == 3  # the third call is refused
    assert s.ended == "budget used up"


def test_not_reproducing_finishes_the_session_with_the_reason(tmp_path):
    f = write(tmp_path, DROP_DELAY, "client", 1_000_000)
    s, r = reconstruct_baseline(BridgeConfig(f), tmp_path / "log.jsonl", max_edits=1)
    assert r.status == "cap" and s.ended == "finished by the planner"
    finish = [x for x in read_log(tmp_path / "log.jsonl") if x.get("type") == "finish"]
    assert finish and finish[0]["note"].startswith("reconstruct: cap: 1 edits kept")
    assert not summarize_log(tmp_path / "log.jsonl")["reproduced"]


def test_cli_reconstruct_baseline(tmp_path, capsys):
    f = write(tmp_path, dup_plan(), mutants=("M1",))
    assert main(["incident", "baseline", f, "--strategy", "reconstruct", "--log-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("reconstruct: reproduced after ")
    assert (tmp_path / "reconstruct.jsonl").exists()
    assert main(["incident", "verify", str(tmp_path / "reconstruct.jsonl")]) == 0
    head = json.loads((tmp_path / "reconstruct.jsonl").read_text().splitlines()[0])
    assert head["config"]["budget"] == 120


def test_view_text_unchanged_by_run_view():
    inc = with_expect(Incident("lift.v0", 4, FaultPlan.from_dict(DROP_DELAY), 90_000_000, "device"))
    assert "link" not in view_text(inc)
