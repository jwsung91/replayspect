"""v1 baseline: Hypothesis-generated plans run through a planning session."""

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, given, settings  # noqa: E402

from replayspect.__main__ import main  # noqa: E402
from replayspect.hyp import hyp_search, plans  # noqa: E402
from replayspect.runner import get_system, run_once  # noqa: E402
from replayspect.session import Session, SessionConfig  # noqa: E402
from replayspect.sim.link import FaultPlan, check_plan_bounds  # noqa: E402
from replayspect.sut.lift import MUTANTS  # noqa: E402

LIFT = get_system("lift.v0")
SRC = Path(__file__).parent.parent / "src"


@settings(max_examples=300, deadline=None, database=None, suppress_health_check=list(HealthCheck))
@given(plans(LIFT))
def test_generated_plans_always_pass_the_session_checks(plan):
    parsed = FaultPlan.from_dict(plan)
    assert parsed.base == "random"
    check_plan_bounds(parsed, LIFT.profile, LIFT.until_us, 20)


def test_vocabulary_covers_the_command_and_poll_ids_of_correct_runs():
    vocab = LIFT.vocabulary
    commands, polls = dict(vocab.commands), set(vocab.polls)
    cs = LIFT.contracts()
    for seed in range(30):
        for e in run_once(LIFT, seed, (), None, cs).trace:
            if e.kind != "send" or e.req_id is None:
                continue
            if e.req_id.startswith("r-"):
                assert e.req_id in commands
                assert e.name == commands[e.req_id] if e.actor == "client" else e.name in vocab.command_replies
            else:
                assert e.req_id in polls


def test_same_hypothesis_seed_gives_the_same_result():
    a = hyp_search(("M8",), seed_base=4000, budget=60, hyp_seed=3)
    b = hyp_search(("M8",), seed_base=4000, budget=60, hyp_seed=3)
    assert (a.runs, a.first_violation_run, a.violated, a.entries) == (b.runs, b.first_violation_run, b.violated, b.entries)
    assert a.plans == b.plans


def test_same_result_in_a_fresh_process_with_another_hash_seed():
    code = ("from replayspect.hyp import hyp_search; "
            "r = hyp_search(('M4',), 1000, 60, 7); print(r.runs, r.first_violation_run, r.entries)")
    outs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                       env={"PYTHONPATH": str(SRC), "PYTHONHASHSEED": h}).stdout
        for h in ("0", "12345")
    }
    assert len(outs) == 1


def test_runs_follow_the_session_seeds_and_stop_at_the_first_violation():
    r = hyp_search(("M8",), seed_base=4000, budget=120, hyp_seed=1)
    assert r.first_violation_run is not None and r.runs == r.first_violation_run + 1 == len(r.plans)
    # replaying the same plans in a fresh session gives the same runs: run i used seed_base + i
    s = Session(SessionConfig(mutants=("M8",), seed_base=4000, budget=120), None)
    outcomes = [bool(s.run_plan(p)["violations"]) for p in r.plans]
    assert outcomes == [False] * r.first_violation_run + [True]


def test_local_source_constants_do_not_reach_generated_plans(monkeypatch):
    from hypothesis.internal.conjecture import providers
    from sortedcontainers import SortedSet

    from replayspect.hyp import Constants

    marker = 777_777  # in every delay range; pretend some local module defines it
    monkeypatch.setattr(providers, "_get_local_constants", lambda: Constants(integers=SortedSet([marker])))
    providers.CONSTANTS_CACHE.cache.clear()
    r = hyp_search((), seed_base=1000, budget=120, hyp_seed=0)
    values = [v for p in r.plans for section in ("delays", "faults", "disconnects")
              for e in p[section] for k, v in e.items() if k.endswith("_us")]
    assert len(values) > 500 and marker not in values
    assert providers._get_local_constants().integers == SortedSet([marker])  # restored afterwards


def test_a_correct_implementation_uses_the_whole_budget_without_violations_or_rejections():
    r = hyp_search((), seed_base=1000, budget=60, hyp_seed=0)
    assert (r.runs, r.first_violation_run, r.rejected) == (60, None, 0)
    assert len(r.plans) == 60
    assert 0 < r.no_effect_entries < r.entries


@pytest.mark.slow
def test_every_mutant_is_found_with_some_hypothesis_seed():
    for m in sorted(MUTANTS):
        assert any(hyp_search((m,), 0, 120, h).first_violation_run is not None for h in range(5)), m


@pytest.mark.slow
def test_correct_implementation_never_violates_over_many_seeds():
    for h in range(10):
        assert hyp_search((), h * 1000, 120, h).first_violation_run is None


def test_cli_hypothesis_baseline(capsys):
    assert main(["baseline", "--mutant", "M1", "--budget", "10", "--strategy", "hypothesis", "--hyp-seeds", "2"]) == 0
    out = capsys.readouterr().out
    assert "hypothesis seeds 0..1" in out
    assert "hypothesis seed 1: first violation at run 0 (1 runs), violated C8; rejected 0" in out
    assert "detected 2/2; runs to first violation when detected: median 1.0, min 1, max 1" in out


def test_cli_random_baseline_is_unchanged(capsys):
    assert main(["baseline", "--mutant", "M4", "--budget", "60"]) == 0
    assert "seeds 0..59, mutants ['M4']: first violation at run 58 (59 runs)" in capsys.readouterr().out


TURNTABLE = get_system("turntable.v0")


@settings(max_examples=100, deadline=None, database=None, suppress_health_check=list(HealthCheck))
@given(plans(TURNTABLE))
def test_generated_turntable_plans_pass_the_session_checks(plan):
    parsed = FaultPlan.from_dict(plan)
    check_plan_bounds(parsed, TURNTABLE.profile, TURNTABLE.until_us, 20)
    assert {e["msg"] for e in plan["faults"] + plan["delays"]} <= {
        "TURN_LEFT", "TURN_RIGHT", "STATUS", "ACK", "DONE", "ERROR", "STATUS_REPLY"}


def test_correct_turntable_uses_the_whole_hypothesis_budget_without_violations():
    r = hyp_search((), seed_base=1000, budget=60, hyp_seed=0, system="turntable.v0")
    assert (r.runs, r.first_violation_run, r.rejected) == (60, None, 0)
