"""WP4 main trial: defect answers, the symptom input, session modes and the planner's own-run view.

Every incident here uses the lift's correct implementation, its published mutants, or a neutral variant.
"""

import json
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.bridge import BridgeConfig, BridgeSession, read_log, summarize_log, verify_log
from replayspect.incident import Incident, defect_class, read_incident, with_expect, write_incident
from replayspect.sim.link import FaultPlan

#: Lift M1 (published), seed 4: a duplicate of the first command arriving 1 s later makes it run twice.
CAUSE = {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "dup_extra_us": 1_000_000}
PLAN = {"base": "random", "delays": [], "faults": [CAUSE], "disconnects": []}
SYMPTOM = "The lift moved up twice for one call."


def write(tmp_path, actor="device", offset=0, symptom=SYMPTOM, name="incident.json", **kw):
    base = dict(system="lift.v0", seed=4, plan=FaultPlan.from_dict(PLAN), until_us=90_000_000, actor=actor,
                clock_offset_us=offset, mutants=("M1",), symptom=symptom)
    return str(write_incident(with_expect(Incident(**{**base, **kw})), tmp_path / name))


def variant_incident(tmp_path):
    """A lift incident run by a neutral variant: the defects are not published (condition B)."""
    spec = f"{Path(__file__).parent / 'neutral_variants.py'}:LIFT_PUBLIC_FAILING"
    inc = with_expect(Incident("lift.v0", 4, FaultPlan.from_dict({"base": "random"}), 90_000_000, "device",
                               variant=spec, symptom="Status showed the lift still down while it moved."))
    return str(write_incident(inc, tmp_path / "variant-incident.json"))


# -- the incident's symptom ------------------------------------------------------------------------


def test_symptom_round_trips_and_is_one_line(tmp_path):
    f = write(tmp_path)
    assert read_incident(f).symptom == SYMPTOM
    with pytest.raises(ValueError, match="one non-empty line"):
        Incident("lift.v0", 0, FaultPlan(), 1, "device", symptom="two\nlines")
    with pytest.raises(ValueError, match="one non-empty line"):
        Incident("lift.v0", 0, FaultPlan(), 1, "device", symptom="  ")
    # Incidents written before the field existed still read.
    d = json.loads(open(f).read())
    del d["symptom"]
    assert Incident.from_dict(d).symptom is None


def test_symptom_is_in_describe_and_in_the_registered_hashes(tmp_path):
    s = BridgeSession(BridgeConfig(write(tmp_path)), tmp_path / "log.jsonl")
    assert s.describe()["symptom"] == SYMPTOM
    head = read_log(tmp_path / "log.jsonl")[0]
    assert "symptom" in head["hashes"] and head["question"] == "name"
    other = BridgeSession(BridgeConfig(write(tmp_path, symptom="The lift stopped between floors.", name="b.json")))
    assert other.describe_sha256() != s.describe_sha256()


# -- the defect question ---------------------------------------------------------------------------


def test_condition_a_lists_the_published_defects_and_takes_one_id(tmp_path):
    s = BridgeSession(BridgeConfig(write(tmp_path)), tmp_path / "log.jsonl")
    d = s.describe()
    assert sorted(d["defects"], key=lambda m: int(m[1:])) == [f"M{i}" for i in range(1, 12)]
    assert "name_defect" in d["task"]
    assert s.describe_defect("anything")["status"] == "rejected" and s.ended is None
    assert s.name_defect("M99")["status"] == "rejected" and s.ended is None
    assert s.name_defect("M4") == {"status": "ok", "recorded": "M4", "session": "ended"}
    assert s.name_defect("M1")["status"] == "session_ended"
    assert s.used == 0  # answers do not use the budget
    summary = summarize_log(tmp_path / "log.jsonl")
    assert summary["defect"]["answer"] == "M4" and summary["defect"]["correct"] is False
    assert verify_log(tmp_path / "log.jsonl") == []


def test_condition_b_takes_a_description(tmp_path):
    s = BridgeSession(BridgeConfig(variant_incident(tmp_path)), tmp_path / "log.jsonl")
    d = s.describe()
    assert "defects" not in d and "describe_defect" in d["task"]
    assert s.name_defect("M1")["status"] == "rejected"
    assert s.describe_defect("   ")["status"] == "rejected"
    assert s.describe_defect("x" * 2001)["status"] == "rejected"
    assert s.describe_defect("  The status reply lags behind the motion.  ")["recorded"] == \
        "The status reply lags behind the motion."
    summary = summarize_log(tmp_path / "log.jsonl")
    assert summary["defect"] == {"question": "describe", "answer": "The status reply lags behind the motion."}


def test_defect_class_counts_published_defects_that_reproduce_the_incident(tmp_path):
    inc = read_incident(write(tmp_path))
    cls = defect_class(inc)
    assert "M1" in cls and "M4" not in cls
    assert defect_class(read_incident(variant_incident(tmp_path))) is None


# -- modes ---------------------------------------------------------------------------------------


def test_symptom_only_has_no_log_and_no_runs(tmp_path):
    s = BridgeSession(BridgeConfig(write(tmp_path), mode="symptom_only"), tmp_path / "log.jsonl")
    d = s.describe()
    assert set(d) == {"system", "task", "symptom", "protocol", "contracts", "defects"}
    assert s.run_plan(PLAN)["status"] == "not_available" and s.used == 0
    assert s.check_cause(0, "faults[0]")["status"] == "not_available"
    assert s.name_defect("M1")["status"] == "ok"
    assert summarize_log(tmp_path / "log.jsonl")["defect"]["correct"] is True


def test_answer_only_gives_a_reproducing_plan_and_its_logged_side(tmp_path):
    f = write(tmp_path, actor="client", offset=2_000_000)
    s = BridgeSession(BridgeConfig(f, mode="answer_only", given_plan=PLAN), tmp_path / "log.jsonl")
    d = s.describe()
    assert d["reproducing_plan"] == PLAN and d["reproducing_run"]["reproduction"]["reproduced"]
    assert "limits" not in d and "budget" not in d and "log" in d
    assert all(" client " in line for line in d["reproducing_run"]["timeline"])
    assert s.run_plan(PLAN)["status"] == "not_available"
    assert s.name_defect("M1")["status"] == "ok"
    head = read_log(tmp_path / "log.jsonl")[0]
    assert head["config"]["mode"] == "answer_only" and head["config"]["given_plan"] == PLAN
    assert verify_log(tmp_path / "log.jsonl") == []


def test_mode_rules(tmp_path):
    f = write(tmp_path)
    with pytest.raises(ValueError, match="mode must be"):
        BridgeSession(BridgeConfig(f, mode="chat"))
    with pytest.raises(ValueError, match="given plan"):
        BridgeSession(BridgeConfig(f, mode="answer_only"))
    with pytest.raises(ValueError, match="given plan"):
        BridgeSession(BridgeConfig(f, given_plan=PLAN))
    with pytest.raises(ValueError, match="does not reproduce"):
        BridgeSession(BridgeConfig(f, mode="answer_only", given_plan={"base": "random"}))
    bare = write(tmp_path, symptom=None, name="bare.json")
    with pytest.raises(ValueError, match="needs an incident with a symptom"):
        BridgeSession(BridgeConfig(bare, mode="symptom_only"))


# -- the planner's own runs -------------------------------------------------------------------------


@pytest.mark.parametrize("actor", ["device", "client"])
def test_run_plan_shows_only_the_logged_side_without_violation_details(tmp_path, actor):
    s = BridgeSession(BridgeConfig(write(tmp_path, actor=actor)))
    out = s.run_plan(PLAN)
    other = "client" if actor == "device" else "device"
    assert out["timeline"] and all(f" {actor} " in line for line in out["timeline"])
    assert not any(f" {other} " in line or " link " in line for line in out["timeline"])
    recv = next(line for line in out["timeline"] if " recv " in line)
    assert " k=" in recv and " sent=" in recv and " delay=" in recv  # the run's own link data
    assert out["violations"] and all(set(v) == {"contract", "req_id", "at_s"} for v in out["violations"])


def test_used_up_budget_leaves_the_answer_open(tmp_path):
    s = BridgeSession(BridgeConfig(write(tmp_path), budget=1))
    s.run_plan(PLAN)
    assert s.run_plan(PLAN)["status"] == "budget_exhausted" and not s.can_run() and s.ended is None
    assert s.name_defect("M1")["status"] == "ok" and s.ended == "defect answered"


# -- operator CLI and MCP ------------------------------------------------------------------------


def test_cli_plan_and_check_show_what_the_operator_needs(tmp_path, capsys):
    f = write(tmp_path)
    assert main(["incident", "check", f]) == 0
    assert "equivalent published defects M1" in capsys.readouterr().out
    s = BridgeSession(BridgeConfig(f), tmp_path / "log.jsonl")
    s.run_plan({"base": "random"})
    s.run_plan(PLAN)
    assert main(["incident", "plan", str(tmp_path / "log.jsonl"), "--out", str(tmp_path / "p.json")]) == 0
    assert json.loads((tmp_path / "p.json").read_text()) == PLAN
    assert main(["incident", "plan", str(tmp_path / "log.jsonl"), "--out", str(tmp_path / "p.json")]) == 2


@pytest.mark.parametrize("mode,cond,tools", [
    ("full", "a", ["check_cause", "describe", "finish", "name_defect", "run_plan"]),
    ("symptom_only", "a", ["describe", "finish", "name_defect"]),
    ("answer_only", "a", ["describe", "finish", "name_defect"]),
    ("full", "b", ["check_cause", "describe", "describe_defect", "finish", "run_plan"]),
    ("symptom_only", "b", ["describe", "describe_defect", "finish"]),
])
def test_mcp_tools_by_mode_and_condition(tmp_path, mode, cond, tools):
    pytest.importorskip("mcp")
    import asyncio

    from replayspect.mcp_server import build_bridge_server

    f = write(tmp_path) if cond == "a" else variant_incident(tmp_path)
    given = (PLAN if cond == "a" else {"base": "random"}) if mode == "answer_only" else None
    server = build_bridge_server(BridgeSession(BridgeConfig(f, mode=mode, given_plan=given), tmp_path / "l.jsonl"))
    assert sorted(t.name for t in asyncio.run(server.list_tools())) == tools
