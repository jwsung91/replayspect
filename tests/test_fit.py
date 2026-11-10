"""WP5b second design: fit a client-side log by fixing what it shows (replayspect.fit)."""

from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.driven import DrivenSetup, run_driven
from replayspect.fit import (Choice, Ranges, _Runner, attempts_of, fit_log, fit_replies, logged_disconnects,
                             report_lines)
from replayspect.incident import text_log
from replayspect.ingest import ingest_text, read_rules
from replayspect.runner import get_system
from replayspect.sim.link import FaultPlan
from replayspect.sut.lift import run_lift
from replayspect.trace import Event

RULES = Path(__file__).parent.parent / "examples" / "rules" / "sim-client-ros.yaml"
LIFT = get_system("lift.v0")


def logged(trace, ms=False):
    return ingest_text(text_log(trace.events, "client", ms=ms).encode(), read_rules(RULES)).events


def true_choice(hidden, log):
    """The hidden run's own request arrivals, drops and duplicates, as an arrival choice."""
    plan = FaultPlan.from_trace(hidden)
    d = {(x.key.msg, x.key.req_id, x.key.k): x.delay_us for x in plan.delays if x.key.dir == "c2s"}
    drops = {(f.key.msg, f.key.req_id, f.key.k) for f in plan.faults if f.key.dir == "c2s" and f.drop}
    dups = {(f.key.msg, f.key.req_id, f.key.k): f.dup_extra_us for f in plan.faults
            if f.key.dir == "c2s" and f.dup_extra_us is not None}
    atts = attempts_of(log, "client")
    return Choice(tuple((a.key, None if a.key in drops else d[a.key]) for a in atts),
                  tuple(sorted(dups.items(), key=lambda kv: str(kv[0]))))


def test_connection_lines_become_client_states_and_disconnects():
    hidden = run_lift(7)
    log = logged(hidden)
    states = [(e.name, e.t_us) for e in log if e.kind == "state"]
    assert states and states[0][0] == "DISCONNECTED"
    true = [(d.t_us, d.duration_us) for d in FaultPlan.from_trace(hidden).disconnects]
    assert [(d["t_us"], d["duration_us"]) for d in logged_disconnects(log, "client", 90_000_000)] == true
    open_end = [Event(0, 5, "client", "state", "DISCONNECTED")]
    assert logged_disconnects(open_end, "client", 100) == [{"t_us": 5, "duration_us": 95}]


@pytest.mark.parametrize("seed", [1, 5, 7, 23])
def test_with_the_true_arrivals_reply_delays_are_computed_and_reproduce(seed):
    # The core claim: reply delays do not change the device, so given the request arrivals,
    # one run gives every reply's send time and the plan follows by arithmetic.
    hidden = run_lift(seed)
    log = logged(hidden)
    setup = DrivenSetup(LIFT, log, 90_000_000)
    fit, _ = _Runner(setup, Ranges.of(setup), logged_disconnects(log, "client", 90_000_000), 10).evaluate(
        true_choice(hidden, log))
    assert not [e for e in fit.unexplained if e.name not in LIFT.quiet_messages]
    assert fit.match.reproduced and fit.match.max_dt_us == 0


def test_fit_reproduces_from_the_log_alone_and_reports():
    res = fit_log(DrivenSetup(LIFT, logged(run_lift(7)), 90_000_000), branches=True)
    assert res.reproduced and res.runs <= 10 and res.matched == res.receives
    text = "\n".join(report_lines(res))
    assert "not evidence that there is no defect" in text
    assert "attempts with a branch point:" in text and res.branch_checked is not None


def test_a_receive_no_device_send_explains_is_unexplained():
    log = logged(run_lift(7))
    fake = Event(len(log), log[-1].t_us - 1_000_000, "client", "recv", "DONE", "r-0099", log={"line": 999})
    log = sorted([*log, fake], key=lambda e: e.t_us)
    res = fit_log(DrivenSetup(LIFT, log, 90_000_000), cap=20)
    assert not res.reproduced and any(e.req_id == "r-0099" for e in res.fit.unexplained)
    assert "DONE r-0099" in "\n".join(report_lines(res)) and "log line 999" in "\n".join(report_lines(res))


def test_delay_ranges_are_parameters():
    # Every message takes exactly 10 ms: fits with the profile's range, not with a 20 ms minimum.
    hidden = run_lift(3, plan=FaultPlan.from_dict({"base": "fixed"}))
    log = logged(hidden)
    setup = DrivenSetup(LIFT, log, 90_000_000)
    assert fit_log(setup).reproduced
    slow = Ranges((20_000, 1_500_000), (20_000, 1_500_000), (0, 4_000_000))
    res = fit_log(setup, slow, cap=10)
    assert not res.reproduced and res.fit.unexplained


def test_run_cap_is_reported_as_incomplete():
    res = fit_log(DrivenSetup(LIFT, logged(run_lift(23)), 90_000_000), cap=3)
    assert res.runs <= 3
    if not res.reproduced:
        assert res.status == "incomplete" and res.incomplete_reason == "cap"
        assert "run cap reached" in report_lines(res)[0] and "not evidence about the device" in report_lines(res)[0]


def test_unexplained_only_when_the_whole_choice_space_was_run():
    # A one-command log with a receive the device never sends: the choice space is small, so every
    # choice is run, and the receive is reported as unexplained (evidence), not as a fitter limit.
    log = [e for e in logged(run_lift(3, plan=FaultPlan.from_dict({"base": "fixed"}))) if e.t_us < 500_000]
    log.append(Event(len(log), 400_000, "client", "recv", "DONE", "r-0099"))
    res = fit_log(DrivenSetup(LIFT, log, 5_000_000), cap=400)
    assert res.status == "unexplained" and res.space is not None and res.space * 2 <= 400
    assert "every choice in the fitter's choice space was run" in report_lines(res)[0]
    # The same log on a long run (many attempts): too many choices to run, so incomplete.
    long_log = sorted([*logged(run_lift(3)), Event(0, 400_000, "client", "recv", "DONE", "r-0099")],
                      key=lambda e: e.t_us)
    big = fit_log(DrivenSetup(LIFT, long_log, 90_000_000), cap=30)
    assert big.status == "incomplete" and big.incomplete_reason in ("space", "cap", "no_improvement")


def test_violation_outcomes_are_reported_and_ambiguity_is_not_resolved_without_expect():
    res = fit_log(DrivenSetup(LIFT, logged(run_lift(7)), 90_000_000), branches=True)
    assert res.reproduced and res.outcomes and not res.expect_given
    text = "\n".join(report_lines(res))
    assert "explanations matching every receive, by violated contracts" in text
    res.outcomes = {(): 3, ("C3",): 1}
    assert res.ambiguous and "none is chosen" in "\n".join(report_lines(res))
    res.expect_given = True
    assert not res.ambiguous


def test_moves_are_deterministic():
    setup = DrivenSetup(LIFT, logged(run_lift(11)), 90_000_000)
    a, b = fit_log(setup), fit_log(setup)
    assert (a.status, a.runs, a.moves, a.fit.plan) == (b.status, b.runs, b.moves, b.fit.plan)


def test_cli_drive_fit(tmp_path, capsys):
    log, trace = tmp_path / "c.log", tmp_path / "c.jsonl"
    log.write_text(text_log(run_lift(7).events, "client"))
    assert main(["ingest", str(log), "--rules", str(RULES), "--out", str(trace)]) == 0
    capsys.readouterr()
    assert main(["drive", str(trace), "--until", "90s", "--fit", "--branches"]) == 0
    out = capsys.readouterr().out
    assert "fit: reproduced" in out and "explained by loss:" in out and "attempts with a branch point" in out
    assert main(["drive", str(trace), "--until", "90s", "--fit", "--s2c-delay", "1s", "1.5s", "--fit-runs", "5"]) == 1
    assert main(["drive", str(trace), "--fit", "--reconstruct"]) == 2
    assert main(["drive", str(trace), "--fit", "--c2s-delay", "2s", "1s"]) == 2
