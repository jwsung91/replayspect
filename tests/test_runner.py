import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.contract import load_contracts
from replayspect.runner import (
    REPRO_FORMAT,
    get_system,
    make_repro,
    read_repro,
    replay,
    run_once,
    search,
    write_repro,
)
from replayspect.shrink import _items, _plan, best_repro, shrink
from replayspect.sim.link import FaultPlan

LIFT = get_system("lift.v0")
CS = LIFT.contracts()
SRC = Path(__file__).parent.parent / "src"


def explicit(seed, mutants):
    rnd = run_once(LIFT, seed, mutants, None, CS)
    return run_once(LIFT, seed, mutants, FaultPlan.from_trace(rnd.trace), CS)


# -- runs and search ------------------------------------------------------------------


def test_run_once_correct_lift_has_no_violations():
    r = run_once(LIFT, 0, (), None, CS)
    assert r.violations == [] and r.until_us == 90_000_000 and r.mutants == ()


def test_unknown_system():
    with pytest.raises(ValueError, match="unknown system"):
        get_system("nope")


def test_search_counts_hits_and_first_seeds():
    res = search(LIFT, range(3), ["M5"], CS)
    assert res.runs == 3
    assert res.hits == {"C5": 3}
    assert res.first_seed == {"C5": 0}
    assert [r.seed for r in res.failures] == [0]


def test_search_reports_patterns_that_never_matched():
    few = search(LIFT, range(5), [], CS)
    assert {str(p) for p in few.unmatched} == {"device.send(ERROR)"}
    assert search(LIFT, range(50), [], CS).unmatched == set()


def test_a_misspelled_pattern_shows_up_as_unmatched():
    text = LIFT.contracts_path.read_text().replace("motor_start", "motor_strat")
    res = search(LIFT, range(3), [], load_contracts(text))
    assert {str(p) for p in res.unmatched} == {"device.effect(motor_strat)", "device.send(ERROR)"}


# -- repro files ------------------------------------------------------------------------


def test_repro_round_trip_and_replay(tmp_path):
    run = explicit(0, ["M5"])
    doc = make_repro(run, "C5", {"faults_before": 1, "faults_after": 1, "runs": 0, "default_delay_sends": 0})
    path = write_repro(doc, tmp_path / "r.json")
    back = read_repro(path)
    assert back == json.loads(json.dumps(doc))
    assert back["format"] == REPRO_FORMAT
    first = back["expect"]["first_violations"][0]
    assert first["contract"] == "C5" and first["detail"] == "'UP' != 'MOVING_DOWN'"
    assert back["explain"]["violation"] == first
    assert any(e["seq"] == first["seq"] for e in back["explain"]["events"])
    assert all(e.get("req_id") == first["req_id"] for e in back["explain"]["key_events"])
    assert set(back["harness"]) == {"version", "git"}
    r = replay(back)
    assert r.ok and r.digest_ok and r.violations_ok and r.target_ok


def test_replay_detects_a_different_execution(tmp_path):
    doc = make_repro(explicit(0, ["M5"]), "C5")
    doc["expect"]["digest"] = "0" * 64
    r = replay(doc)
    assert not r.digest_ok and r.violations_ok and not r.ok
    doc = make_repro(explicit(0, ["M5"]), "C5")
    doc["mutants"] = []
    r = replay(doc)
    assert not r.target_ok and not r.ok


def test_repro_needs_a_plan_and_a_violated_target(tmp_path):
    with pytest.raises(ValueError, match="explicit plan"):
        make_repro(run_once(LIFT, 0, ["M5"], None, CS), "C5")
    with pytest.raises(ValueError, match="does not violate"):
        make_repro(explicit(0, ["M5"]), "C1")
    (tmp_path / "x.json").write_text('{"format": "other"}')
    with pytest.raises(ValueError, match="not a"):
        read_repro(tmp_path / "x.json")


# -- shrinking --------------------------------------------------------------------------------


def test_bug_that_needs_no_faults_shrinks_to_zero():
    r = shrink(LIFT, explicit(0, ["M5"]), "C5", CS)
    assert r.faults_before > 0 and r.faults_after == 0 and r.runs == 1
    assert "C5" in r.run.violated()


@pytest.mark.parametrize("mutant,target", [("M2", "C8"), ("M3", "C7"), ("M6", "C6")])
def test_shrunk_plan_is_one_minimal_and_keeps_the_delays(mutant, target):
    start = explicit(0, [mutant])
    r = shrink(LIFT, start, target, CS)
    assert target in r.run.violated()
    assert r.plan.delays == start.plan.delays
    assert 0 < r.faults_after < r.faults_before
    items = _items(r.plan)
    for i in range(len(items)):
        smaller = _plan(r.plan, items[:i] + items[i + 1:])
        assert target not in run_once(LIFT, 0, [mutant], smaller, CS).violated(), items[i]


def test_shrunk_run_is_reproducible():
    r = shrink(LIFT, explicit(0, ["M3"]), "C7", CS)
    again = run_once(LIFT, 0, ["M3"], r.plan, CS)
    assert again.trace.digest() == r.run.trace.digest()


def test_search_keeps_failing_runs_of_the_target():
    res = search(LIFT, range(70), ["M4"], CS, keep_for="C3", keep=2)
    assert res.runs == 70
    assert [r.seed for r in res.kept] == [58, 65]
    assert all("C3" in r.violated() for r in res.kept)


def test_best_repro_keeps_the_smallest_without_rerunning_search():
    res = search(LIFT, range(70), ["M4"], CS, keep_for="C3", keep=2)
    best = best_repro(LIFT, res.kept, "C3", CS)
    # seed 58 shrinks to 6 faults, seed 65 to 3
    assert (best.run.seed, best.faults_after) == (65, 3)
    assert best.total_runs > best.runs
    assert best.summary()["total_runs"] == best.total_runs


def test_best_repro_none_without_candidates_and_rejects_non_failing_runs():
    assert best_repro(LIFT, [], "C1", CS) is None
    with pytest.raises(ValueError, match="does not violate"):
        best_repro(LIFT, [run_once(LIFT, 0, (), None, CS)], "C1", CS)


# -- command line ----------------------------------------------------------------------------------


def test_cli_search_and_replay(tmp_path, capsys):
    code = main(["search", "--mutant", "M5", "--seeds", "3", "--target", "C5", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "C5: violated in 3 runs, first at seed 0" in out
    assert "shrunk C5:" in out and "-> 0 faults" in out
    assert "simulations: 3 search + " in out
    (path,) = tmp_path.glob("*.json")
    assert path.name == "lift.v0-M5-C5-seed0.json"
    assert main(["replay", str(path)]) == 0
    assert "digest ok, first violations ok, target C5 violated" in capsys.readouterr().out


def test_cli_clean_search_exits_zero(capsys):
    assert main(["search", "--seeds", "2"]) == 0
    assert "no contract violated" in capsys.readouterr().out


def test_cli_runs_as_a_module(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    out = subprocess.run([sys.executable, "-m", "replayspect", "search", "--seeds", "1"],
                         env=env, capture_output=True, text=True)
    assert out.returncode == 0 and "1 runs" in out.stdout


def test_run_with_a_plan_carries_its_plan_report():
    from replayspect.sim.link import MessageFault, MsgKey

    plan = FaultPlan(faults=(MessageFault(MsgKey("c2s", "MOVE_UP", "r-9999", 0), drop=True),), base="random")
    r = run_once(LIFT, 0, (), plan, CS)
    assert [f.key.req_id for f in r.plan_report.unmatched_faults] == ["r-9999"]
    assert run_once(LIFT, 0, (), None, CS).plan_report is None


def test_run_context_window():
    r = run_once(LIFT, 0, ["M5"], None, CS)
    v = r.first_of("C5")
    ctx = r.context(v.seq, before=2, after=1)
    assert [e["seq"] for e in ctx] == [v.seq - 2, v.seq - 1, v.seq, v.seq + 1]
    assert r.first_of("C1") is None


def test_run_summary_leaves_out_quiet_messages_and_formats_lines():
    from replayspect.runner import run_summary, summary_line

    r = run_once(LIFT, 0, ["M4"], FaultPlan(base="random"), CS)
    lines = run_summary(r, LIFT)
    assert lines[:3] == [
        "0.000s device state DOWN - (from None on init)",
        "0.000s client send MOVE_UP r-0001 k=0 delay=0.357s",
        "0.357s device recv MOVE_UP r-0001 k=0",
    ]
    assert not any("STATUS" in line for line in lines)
    assert any(line.endswith("(cause reply, message r-0001)") for line in lines)
    assert run_summary(r, LIFT, max_lines=5)[-1].startswith("... ")
    assert LIFT.quiet_messages == {"STATUS", "STATUS_REPLY"}
    assert LIFT.protocol_path.name == "protocol-lift.md"


def test_summary_lines_for_faults():
    from replayspect.runner import run_summary
    from replayspect.sim.link import Disconnect, MessageFault, MsgKey

    plan = FaultPlan(
        faults=(MessageFault(MsgKey("c2s", "MOVE_UP", "r-0001", 0), drop=True),
                MessageFault(MsgKey("s2c", "ACK", "r-0001", 0), dup_extra_us=250_000)),
        disconnects=(Disconnect(20_000_000, 500_000),),
        base="random",
    )
    lines = run_summary(run_once(LIFT, 0, [], plan, CS), LIFT)
    assert "0.000s link drop c2s MOVE_UP r-0001 k=0 injected" in lines
    assert any(" link duplicate s2c ACK r-0001 k=0 extra=0.250s" in line for line in lines)
    assert "20.000s link disconnect for 0.500s" in lines
    assert "20.500s link reconnect" in lines
