import json
import re

import pytest

from replayspect.__main__ import main
from replayspect.session import Session, SessionConfig, read_log, summarize_log, verify_log
from replayspect.sut.lift import MUTANTS, SEARCH_PROFILE

QUIET = {"base": "random"}

#: A plan written from the protocol description alone: the device only receives the
#: third MOVE_UP, late; the client never sees an ACK and gives up while the lift is
#: still moving, then sends MOVE_DOWN quickly. Shows the planning task can be won
#: within the bounds.
REASONED = {
    "base": "random",
    "delays": [
        {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 2, "delay_us": 1_500_000},
        {"dir": "c2s", "msg": "MOVE_DOWN", "req_id": "r-0002", "k": 0, "delay_us": 10_000},
    ],
    "faults": [
        {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "drop": True},
        {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 1, "drop": True},
        {"dir": "s2c", "msg": "ACK", "req_id": "r-0001", "k": 0, "drop": True},
    ],
}


def session(tmp_path=None, **kw):
    cfg = SessionConfig(**{"budget": 20, **kw})
    return Session(cfg, None if tmp_path is None else tmp_path / "log.jsonl")


def all_text(obj):
    return json.dumps(obj, ensure_ascii=False)


# -- what the planner sees -------------------------------------------------------------


def test_describe_has_everything_and_no_hidden_configuration():
    d = session(mutants=("M4",)).describe()
    assert set(d) == {"system", "task", "protocol", "contracts", "plan_format", "limits", "budget"}
    text = all_text(d)
    assert not re.search(r"\bM[1-8]\b", text)
    for word in ("mutant", "Mutant", "뮤턴트", "seeded bug"):
        assert word not in text
    for description in MUTANTS.values():
        assert description not in text
    # no pointers to operator-side sources (implementation, design notes, reference oracle)
    assert not re.search(r"src/|tests/|docs/|\.py\b|oracle|design-v0", text)
    assert d["budget"] == {"total": 20, "used": 0, "left": 20}


def test_limits_come_from_the_profile():
    lim = session().limits()
    assert lim["delay_us"]["c2s"] == list(SEARCH_PROFILE.c2s.delay_us)
    assert lim["dup_extra_us"]["s2c"] == list(SEARCH_PROFILE.s2c.dup_extra_us)
    assert lim["disconnect_duration_us"] == list(SEARCH_PROFILE.disconnect_duration_us)
    assert lim["max_faults_and_disconnects"] == 20


def test_run_result_shape_and_no_mutant_names():
    r = session(mutants=("M5",)).run_plan(QUIET)
    assert set(r) == {"status", "run", "violations", "no_effect", "timeline", "budget"}
    assert r["status"] == "ok" and r["run"] == 0
    assert r["violations"][0]["contract"] == "C5" and r["violations"][0]["at_s"] > 0
    assert not re.search(r"\bM[1-8]\b", all_text(r))
    assert not any("STATUS" in line for line in r["timeline"])
    assert r["timeline"][0] == "0.000s device state DOWN - (from None on init)"


def test_plan_may_be_a_json_string():
    assert session().run_plan(json.dumps(QUIET))["status"] == "ok"


# -- rules ----------------------------------------------------------------------------------


def _fault(**kw):
    f = {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "drop": True}
    f.update(kw)
    return f


@pytest.mark.parametrize("plan,match", [
    ({"base": "fixed"}, 'base": "random'),
    ({}, 'base": "random'),
    ({"base": "random", "delays": [{"dir": "s2c", "msg": "ACK", "req_id": "r-0001", "k": 0,
                                    "delay_us": 60_000_000}]}, "outside the allowed range"),
    ({"base": "random", "faults": [{"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0,
                                    "dup_extra_us": 9_000_000}]}, "outside the allowed range"),
    ({"base": "random", "disconnects": [{"t_us": 1_000_000, "duration_us": 80_000_000}]}, "outside the allowed range"),
    ({"base": "random", "disconnects": [{"t_us": 95_000_000, "duration_us": 500_000}]}, "after the run ends"),
    ({"base": "random", "faults": [_fault(k=i) for i in range(21)]}, "at most 20"),
    ({"base": "random", "faults": [_fault(lose=1)]}, "unknown fields"),
    ({"base": "random", "faults": [_fault(k=None)]}, "k must be an integer"),
    ("{not json", "not valid JSON"),
])
def test_rejected_plans_count_against_the_budget(plan, match):
    s = session()
    r = s.run_plan(plan)
    assert r["status"] == "rejected" and re.search(re.escape(match), r["error"])
    assert r["budget"]["used"] == 1


def test_budget_is_enforced_without_counting_refusals():
    s = session(budget=2)
    s.run_plan(QUIET)
    s.run_plan({"base": "fixed"})
    r = s.run_plan(QUIET)
    assert r == {"status": "budget_exhausted", "budget": {"total": 2, "used": 2, "left": 0}}


def test_seed_schedule_and_log(tmp_path):
    s = session(tmp_path, mutants=("M5",), seed_base=500, budget=4)
    s.run_plan(QUIET)
    s.run_plan({"base": "fixed"})
    s.run_plan(QUIET)
    recs = read_log(tmp_path / "log.jsonl")
    head, runs = recs[0], recs[1:]
    assert head["config"]["mutants"] == ["M5"] and head["config"]["seed_base"] == 500
    assert set(head["hashes"]) == {"protocol", "contracts", "plan_format"}
    assert "python" in head and "harness" in head
    assert [(r["run"], r["seed"], r["status"]) for r in runs] == [(0, 500, "ok"), (1, 501, "rejected"), (2, 502, "ok")]
    assert runs[0]["violated"] == ["C5"] and len(runs[0]["digest"]) == 64


def test_log_summary_and_exact_replay(tmp_path):
    s = session(tmp_path, mutants=("M4",), seed_base=1, budget=5)
    s.run_plan(QUIET)
    s.run_plan("{oops")
    s.run_plan(REASONED)  # seed 3
    summary = summarize_log(tmp_path / "log.jsonl")
    assert (summary["runs"], summary["rejected"], summary["first_violation_run"]) == (3, 1, 2)
    assert summary["runs_to_first_violation"] == 3 and summary["violated"] == ["C3"]
    assert verify_log(tmp_path / "log.jsonl") == []


def test_tampered_log_is_detected(tmp_path):
    s = session(tmp_path, mutants=("M4",), budget=2)
    s.run_plan(REASONED)
    path = tmp_path / "log.jsonl"
    recs = read_log(path)
    recs[1]["digest"] = "0" * 64
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    assert verify_log(path) == [0]


def test_a_reasoned_plan_wins_where_random_search_rarely_does():
    s = session(mutants=("M4",), budget=50)
    hits = sum(bool(s.run_plan(REASONED)["violations"]) for _ in range(50))
    assert hits >= 30  # 39 of 50 seeds; random search: about 2 in 100
    clean = session(budget=50)
    assert not any(clean.run_plan(REASONED)["violations"] for _ in range(50))


# -- command line ------------------------------------------------------------------------------


def test_cli_baseline(capsys):
    assert main(["baseline", "--mutant", "M4", "--budget", "60"]) == 0
    assert "seeds 0..59, mutants ['M4']: first violation at run 58 (59 runs)" in capsys.readouterr().out


def test_cli_session_summary_and_verify(tmp_path, capsys):
    s = session(tmp_path, mutants=("M4",), budget=3)
    s.run_plan(QUIET)
    s.run_plan(REASONED)
    assert main(["session", str(tmp_path / "log.jsonl"), "--verify"]) == 0
    out = capsys.readouterr().out
    assert "runs 2 (rejected 0" in out and "first violation at run 1 (2 runs), violated C3" in out
    assert "replay: ok" in out


# -- session identity and log integrity -------------------------------------------------


def test_existing_log_cannot_reset_budget_or_seeds(tmp_path):
    s = session(tmp_path, seed_base=500, budget=1)
    s.run_plan(QUIET)
    path = tmp_path / "log.jsonl"
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        session(tmp_path, seed_base=500, budget=1)
    with pytest.raises(FileExistsError):
        session(tmp_path, seed_base=900, budget=20)
    assert path.read_bytes() == before
    assert summarize_log(path)["runs"] == 1
    assert verify_log(path) == []


def test_even_empty_log_paths_are_reserved(tmp_path):
    path = tmp_path / "log.jsonl"
    path.touch()
    with pytest.raises(FileExistsError):
        session(tmp_path)
    assert path.read_bytes() == b""


@pytest.mark.parametrize("reader", [read_log, summarize_log, verify_log])
def test_combined_sessions_are_not_one_trial(tmp_path, reader):
    session(tmp_path).run_plan(QUIET)
    path = tmp_path / "log.jsonl"
    text = path.read_text()
    path.write_text(text + text)
    with pytest.raises(ValueError, match="session header"):
        reader(path)


@pytest.mark.parametrize("field,value", [("run", 1), ("run", False), ("seed", 7), ("status", "other")])
def test_invalid_run_sequence_is_rejected(tmp_path, field, value):
    session(tmp_path).run_plan(QUIET)
    path = tmp_path / "log.jsonl"
    recs = read_log(path)
    recs[1][field] = value
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    with pytest.raises(ValueError, match="invalid run record"):
        read_log(path)


def test_log_cannot_exceed_its_budget(tmp_path):
    session(tmp_path, budget=1).run_plan(QUIET)
    path = tmp_path / "log.jsonl"
    recs = read_log(path)
    recs.append({**recs[1], "run": 1, "seed": 1})
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    with pytest.raises(ValueError, match="budget"):
        read_log(path)
