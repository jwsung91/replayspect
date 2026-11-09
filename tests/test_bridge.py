"""WP4 bridge experiment: incidents, planner views, the temporary match, bridge sessions and baselines.

Every incident here uses the lift's published mutants.
"""

import ast
import json
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.bridge import (
    BridgeConfig,
    BridgeSession,
    necessary_entries,
    random_baseline,
    read_log,
    summarize_log,
    verify_log,
    without_entry,
)
from replayspect.incident import (
    DIAGNOSTIC_TOLERANCES_US,
    Incident,
    check_preconditions,
    read_incident,
    run_incident,
    view_events,
    view_text,
    with_expect,
    wp4_match,
    write_incident,
)
from replayspect.runner import ROOT, get_system, run_once
from replayspect.session import PLAN_FORMAT_PATH
from replayspect.sim.link import FaultPlan
from replayspect.tracefile import parse_trace_file

LIFT = get_system("lift.v0")
#: Lift M1 (published), seed 4: a duplicate of the first command arriving 1 s later makes it run twice.
CAUSE = {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "dup_extra_us": 1_000_000}
PLAN = {"base": "random", "delays": [], "faults": [CAUSE], "disconnects": []}


def incident(actor="device", offset=0, **kw) -> Incident:
    base = dict(system="lift.v0", seed=4, plan=FaultPlan.from_dict(PLAN), until_us=90_000_000, actor=actor,
                clock_offset_us=offset, mutants=("M1",))
    return with_expect(Incident(**{**base, **kw}))


@pytest.fixture
def inc_file(tmp_path):
    return str(write_incident(incident(), tmp_path / "incident.json"))


# -- incidents and views ------------------------------------------------------------------------


def test_incident_round_trip_and_expect(tmp_path):
    inc = incident("client", 2_500_000)
    assert inc.expect["violated"] == ["C8"]
    back = read_incident(write_incident(inc, tmp_path / "i.json"))
    assert back == inc
    with pytest.raises(FileExistsError):
        write_incident(inc, tmp_path / "i.json")
    with pytest.raises(ValueError, match="cannot be combined"):
        Incident("lift.v0", 0, FaultPlan(), 1, "device", mutants=("M1",), variant="x.py:V")
    with pytest.raises(ValueError, match=">= 0"):
        Incident("lift.v0", 0, FaultPlan(), 1, "device", clock_offset_us=-1)


def test_view_keeps_one_side_without_link_metadata_renumbered_and_offset_once():
    inc = incident("client", 3_000_000)
    run = run_incident(inc)
    view = view_events(run.trace, "client", 3_000_000)
    originals = [e for e in run.trace if e.actor == "client"]
    assert [e.seq for e in view] == list(range(len(view)))
    assert all(e.actor == "client" and "link" not in e.data for e in view)
    # One constant offset for the whole log: every event moves by the same amount.
    assert {v.t_us - o.t_us for v, o in zip(view, originals)} == {3_000_000}


def test_view_file_has_nothing_that_identifies_the_run():
    inc = incident("device")
    tf = parse_trace_file(view_text(inc))
    h = tf.header
    assert (h.seed, h.plan, h.contracts, h.until_us) == (None, None, None, None)
    assert h.slice.of is None and h.slice.actors == ("device",) and h.slice.window is None
    assert all("link" not in e.data for e in tf.trace)


def test_view_validates_against_the_trace_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schemas" / "trace-1.schema.json").read_text())
    v = jsonschema.Draft202012Validator(schema)
    for line in view_text(incident("client", 1_000_000)).splitlines():
        v.validate(json.loads(line))


# -- the WP4 match ----------------------------------------------------------------------------------


def test_match_of_the_incident_with_itself():
    inc = incident()
    hidden = run_incident(inc)
    m = wp4_match(inc, hidden, hidden, LIFT)
    assert m.reproduced and m.digest_same and m.matched == m.total and m.max_dt_us == 0
    assert m.within == {t: True for t in DIAGNOSTIC_TOLERANCES_US}


def test_match_reports_the_first_mismatch_in_each_clock():
    inc = incident("client", 2_000_000)
    hidden = run_incident(inc)
    other = run_once(LIFT, 4, ["M1"], FaultPlan(base="random"))
    m = wp4_match(inc, hidden, other, LIFT)
    assert not m.reproduced and m.matched < m.total
    shown = m.for_planner(2_000_000)["first_mismatch"]
    raw = m.first_mismatch
    if raw["expected_t_s"] is not None:
        assert shown["expected_t_s_log_clock"] == pytest.approx(raw["expected_t_s"] + 2.0)
    assert shown["got_t_s_run_clock"] == raw["got_t_s"]  # the run's own clock, as in its timeline


@pytest.mark.parametrize("delay_us,within", [
    (700_000, {100_000: False, 250_000: True, 500_000: True, 1_000_000: True}),   # 0.11 s off
    (300_000, {100_000: False, 250_000: False, 500_000: True, 1_000_000: True}),  # 0.29 s off
])
def test_match_tolerances_are_diagnostic_columns(delay_us, within):
    """Same faults, one reply delay changed: the same lines at shifted times."""
    inc = incident()
    hidden = run_incident(inc)
    plan = {**PLAN, "delays": [{"dir": "s2c", "msg": "DONE", "req_id": "r-0003", "k": 0, "delay_us": delay_us}]}
    m = wp4_match(inc, hidden, run_once(LIFT, 4, ["M1"], FaultPlan.from_dict(plan)), LIFT)
    assert m.lines_same and m.contracts_same and m.max_dt_us > 0 and not m.digest_same
    assert m.within == within
    assert m.reproduced == within[inc.tolerance_us]


def test_preconditions_pass_for_a_fault_triggered_incident():
    for actor in ("device", "client"):
        p = check_preconditions(incident(actor))
        assert p.ok, actor


def test_preconditions_catch_a_defect_only_the_poll_replies_show():
    """Lift M5 changes only what STATUS_REPLY says. With polls left out of the comparison the
    correct implementation matches every line, so the view cannot show the defect; the status
    rule (poll reply data, consecutive repeats merged) brings it back."""
    plain = with_expect(Incident("lift.v0", 0, FaultPlan(base="random"), 90_000_000, "device", mutants=("M5",)))
    p = check_preconditions(plain)
    assert p.self_match and p.correct_differs and not p.correct_log_differs and not p.ok
    with_rule = with_expect(Incident("lift.v0", 0, FaultPlan(base="random"), 90_000_000, "device",
                                     mutants=("M5",), status_rule=True))
    assert check_preconditions(with_rule).ok


# -- bridge sessions -------------------------------------------------------------------------------


def test_reproduce_confirm_the_cause_then_name_the_defect(inc_file, tmp_path):
    log = tmp_path / "log.jsonl"
    s = BridgeSession(BridgeConfig(inc_file, budget=10), log)
    out = s.run_plan(PLAN)
    assert out["status"] == "ok" and out["reproduction"]["reproduced"]
    assert s.check_cause(0, "faults[0]") == {"status": "ok", "run": 1, "confirmed": True, "violations": [],
                                             "budget": {"total": 10, "used": 2, "left": 8}}
    assert s.ended is None  # a confirmed cause no longer ends the session; the defect answer does
    assert s.name_defect("M1") == {"status": "ok", "recorded": "M1", "session": "ended"}
    assert s.run_plan(PLAN)["status"] == "session_ended" and s.used == 2
    assert verify_log(log) == []
    summary = summarize_log(log)
    assert summary["reproduced"] and summary["runs_to_reproduction"] == 1
    assert summary["candidates"] == 1 and summary["candidate_entries"] == ["faults[0]"]
    assert (summary["nominations"], summary["confirmed"], summary["nominated_hidden_fault"]) == (1, 1, 1)
    assert summary["exact_reproduction"]
    assert summary["defect"]["answer"] == "M1" and summary["defect"]["correct"]
    assert "M1" in summary["defect"]["equivalent"]
    assert summary["defect"]["chance"] == len(summary["defect"]["equivalent"]) / 11


def test_cause_checks_are_counted_and_need_a_reproducing_run(inc_file):
    s = BridgeSession(BridgeConfig(inc_file, budget=6))
    s.run_plan({"base": "random"})  # run 0: does not reproduce
    assert s.check_cause(0, "faults[0]")["status"] == "rejected"
    assert s.check_cause(7, "faults[0]")["status"] == "rejected"
    s.run_plan(PLAN)  # run 3: reproduces
    assert s.check_cause(3, "faults[3]")["status"] == "rejected"
    assert s.check_cause(3, "bogus")["status"] == "rejected"
    assert s.used == 6 and not s.can_run() and s.ended is None
    assert s.check_cause(3, "faults[0]")["status"] == "budget_exhausted" and s.used == 6
    assert s.name_defect("M1")["status"] == "ok"  # out of runs, the answer is still open


def test_unconfirmed_cause_keeps_the_session_open(inc_file):
    s = BridgeSession(BridgeConfig(inc_file, budget=10))
    # A short disconnect at the very end changes nothing the log compares.
    plan = {**PLAN, "disconnects": [{"t_us": 89_000_000, "duration_us": 200_000}]}
    assert s.run_plan(plan)["reproduction"]["reproduced"]
    assert necessary_entries(s, plan) == ["faults[0]"]
    out = s.check_cause(0, "disconnects[0]")
    assert out["status"] == "ok" and not out["confirmed"] and out["violations"] == ["C8"]
    assert s.ended is None
    assert s.check_cause(0, "faults[0]")["confirmed"] and s.ended is None


def test_rejected_plans_and_refusals(inc_file):
    s = BridgeSession(BridgeConfig(inc_file, budget=3))
    assert s.run_plan({"base": "fixed"})["status"] == "rejected"
    assert s.run_plan("{not json")["status"] == "rejected"
    assert s.finish()["status"] == "session_ended"
    assert s.run_plan(PLAN)["status"] == "session_ended" and s.used == 2


def test_without_entry_indexes_the_plan_as_submitted():
    plan = {"base": "random", "faults": [{"a": 1}, {"b": 2}]}
    assert without_entry(plan, "faults[0]") == {"base": "random", "faults": [{"b": 2}]}


def test_log_header_records_hashes_for_preregistration(inc_file, tmp_path):
    log = tmp_path / "log.jsonl"
    s = BridgeSession(BridgeConfig(inc_file), log)
    head = read_log(log)[0]
    assert head["hashes"]["describe"] == s.describe_sha256()
    assert set(head["hashes"]) == {"protocol", "contracts", "plan_format", "log", "describe"}
    assert len(head["incident_sha256"]) == 64
    # The digest does not depend on how much budget is left.
    s.run_plan(PLAN)
    assert s.describe_sha256() == head["hashes"]["describe"]


# -- isolation ----------------------------------------------------------------------------------------


def _sut_identifiers() -> set[str]:
    """Classes and upper-case constants of the SUT modules that the public documents never mention."""
    public = "".join(p.read_text() for p in (LIFT.protocol_path, LIFT.contracts_path, PLAN_FORMAT_PATH))
    names = set()
    for f in (ROOT / "src" / "replayspect" / "sut").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name) and t.id.isupper())
    return {n for n in names if len(n) > 3 and n not in public}


def test_nothing_hidden_reaches_the_planner(tmp_path):
    """Planner outputs carry no seed, plan, mutant or variant, incident path, offset, hidden digest,
    SUT source identifier or variant file content. A sentinel variant and directory make leaks visible."""
    secret_dir = tmp_path / "zq81secretdir"
    secret_dir.mkdir()
    (secret_dir / "zq81_variant.py").write_text(
        "# zq81-sentinel-comment\n"
        "from replayspect.sim.link import Channel\n"
        "from replayspect.sim.scheduler import Scheduler\n"
        "from replayspect.sut import lift\n"
        "from replayspect.trace import Trace\n"
        "from replayspect.variant import Variant\n"
        "def _run(seed, profile, plan, until_us):\n"
        "    sched = Scheduler(seed); trace = Trace(lambda: sched.now_us)\n"
        "    ch = Channel(sched, trace, profile, plan)\n"
        "    lift.LiftDevice(sched, trace, ch, frozenset({'M1'}))\n"
        "    c = lift.LiftClient(sched, trace, ch, frozenset({'M1'}), 6)\n"
        "    ch.start(); c.start(); sched.run_until_us(until_us); return trace\n"
        "ZQ81_HIDDEN = Variant('lift.v0', _run)\n")
    spec = f"{secret_dir / 'zq81_variant.py'}:ZQ81_HIDDEN"
    inc = with_expect(Incident("lift.v0", 4, FaultPlan.from_dict(PLAN), 90_000_000, "client", 3_337_000,
                               variant=spec))
    path = write_incident(inc, secret_dir / "incident.json")
    s = BridgeSession(BridgeConfig(str(path), budget=5))
    outputs = [s.describe(), s.run_plan(PLAN), s.run_plan({"base": "random"}), s.check_cause(0, "faults[0]"),
               s.finish()]
    text = json.dumps(outputs)
    for word in ("zq81", "secretdir", "incident.json", str(tmp_path), '"seed"', "M1", inc.expect["digest"],
                 "rs-control"):
        assert word.lower() not in text.lower(), word
    # The offset is never stated. (The log's own times can still be aligned with a run's
    # timeline; that is the inference the client-side view asks for.)
    stated = json.dumps([{k: v for k, v in o.items() if k != "log"} for o in outputs])
    assert "3337000" not in stated and "3.337" not in stated
    for name in _sut_identifiers():
        assert name not in text, name
    view = s.describe()["log"]
    assert json.loads(view.splitlines()[0])["slice"]["of"] is None


# -- baselines --------------------------------------------------------------------------------------


def test_random_baseline_is_deterministic_and_follows_the_rules(inc_file, tmp_path):
    a = random_baseline(BridgeConfig(inc_file, budget=8), 0, tmp_path / "a.jsonl")
    b = random_baseline(BridgeConfig(inc_file, budget=8), 0, tmp_path / "b.jsonl")
    ra, rb = read_log(tmp_path / "a.jsonl")[1:], read_log(tmp_path / "b.jsonl")[1:]
    assert ra == rb and a.used == b.used <= 8 and not a.can_run()
    assert all(r["status"] == "ok" for r in ra)  # random plans always pass the session's checks
    assert verify_log(tmp_path / "a.jsonl") == []


def test_hypothesis_baseline_runs_the_same_loop(inc_file, tmp_path):
    pytest.importorskip("hypothesis")
    from replayspect.bridge import hypothesis_baseline

    s = hypothesis_baseline(BridgeConfig(inc_file, budget=6), 0, tmp_path / "h.jsonl")
    assert 0 < s.used <= 6
    assert verify_log(tmp_path / "h.jsonl") == []


# -- CLI ----------------------------------------------------------------------------------------------


def test_cli_incident_commands(inc_file, tmp_path, capsys):
    assert main(["incident", "check", inc_file]) == 0
    assert ": ok; matches itself yes" in capsys.readouterr().out
    assert main(["incident", "view", inc_file, "--out", str(tmp_path / "trace-m1.jsonl")]) == 2
    assert "must not mention" in capsys.readouterr().err
    assert main(["incident", "view", inc_file, "--out", str(tmp_path / "incident-01.jsonl")]) == 0
    assert parse_trace_file((tmp_path / "incident-01.jsonl").read_text()).header.seed is None
    assert main(["incident", "view", inc_file, "--out", str(tmp_path / "incident-01.jsonl")]) == 2
    capsys.readouterr()
    assert main(["incident", "baseline", inc_file, "--runs", "1", "--budget", "4", "--log-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("random 0: ") and "random-0.jsonl" in out
    log = str(tmp_path / "random-0.jsonl")
    assert main(["incident", "summary", log]) == 0 and "calls" in capsys.readouterr().out
    assert main(["incident", "verify", log]) == 0 and "replay ok" in capsys.readouterr().out


def test_mcp_bridge_server_tools_for_a_published_defect_list(inc_file, tmp_path):
    pytest.importorskip("mcp")
    import asyncio

    from replayspect.mcp_server import build_bridge_server

    server = build_bridge_server(BridgeSession(BridgeConfig(inc_file, budget=3), tmp_path / "log.jsonl"))
    tools = asyncio.run(server.list_tools())
    assert sorted(t.name for t in tools) == ["check_cause", "describe", "finish", "name_defect", "run_plan"]
