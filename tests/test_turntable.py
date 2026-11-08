from pathlib import Path

import pytest

from turntable_oracle import CONTRACTS, TRANSITIONS, check, first_violations, violated
from replayspect.contract import first_violations as judge_first, judge, load_contracts
from replayspect.runner import get_system, run_once, search
from replayspect.session import Session, SessionConfig
from replayspect.sim.link import ChannelProfile, Delay, Disconnect, FaultPlan, MessageFault, MsgKey
from replayspect.sut.turntable import MUTANTS, PROC_US, SEQUENCE, TURN_US, run_turntable
from replayspect.trace import Trace

END = 90_000_000
QUIET = ChannelProfile()  # 1 ms links, no faults
ROOT = Path(__file__).parent.parent
SYSTEM = get_system("turntable.v0")


def events(trace, actor=None, kind=None, name=None):
    return [e for e in trace if (actor is None or e.actor == actor)
            and (kind is None or e.kind == kind) and (name is None or e.name == name)]


def drop(dir, msg, req_id, k):
    return MessageFault(MsgKey(dir, msg, req_id, k), drop=True)


def errors(trace):
    return [(e.req_id, e.data["reason"]) for e in events(trace, "device", "send", "ERROR")]


# -- correct behaviour -------------------------------------------------------------


def test_happy_path_visits_every_position_in_order():
    t = run_turntable(0, QUIET, until_us=40_000_000)
    assert [e.req_id for e in events(t, "client", "send") if e.name in SEQUENCE] == [
        f"r-{n:04d}" for n in range(1, 7)
    ]
    assert [e.name for e in events(t, "client", "send") if e.name in SEQUENCE] == list(SEQUENCE)
    assert [(e.name, e.req_id, e.data) for e in events(t, "device", "state")] == [
        ("INITIAL", None, {"from": None, "on": "init"}),
        ("TURNING_TO_LEFT", "r-0001", {"from": "INITIAL", "on": "TURN_LEFT"}),
        ("LEFT", "r-0001", {"from": "TURNING_TO_LEFT", "on": "arrived"}),
        ("TURNING_TO_INITIAL", "r-0002", {"from": "LEFT", "on": "TURN_RIGHT"}),
        ("INITIAL", "r-0002", {"from": "TURNING_TO_INITIAL", "on": "arrived"}),
        ("TURNING_TO_RIGHT", "r-0003", {"from": "INITIAL", "on": "TURN_RIGHT"}),
        ("RIGHT", "r-0003", {"from": "TURNING_TO_RIGHT", "on": "arrived"}),
        ("TURNING_TO_INITIAL", "r-0004", {"from": "RIGHT", "on": "TURN_LEFT"}),
        ("INITIAL", "r-0004", {"from": "TURNING_TO_INITIAL", "on": "arrived"}),
        ("TURNING_TO_LEFT", "r-0005", {"from": "INITIAL", "on": "TURN_LEFT"}),
        ("LEFT", "r-0005", {"from": "TURNING_TO_LEFT", "on": "arrived"}),
        ("TURNING_TO_INITIAL", "r-0006", {"from": "LEFT", "on": "TURN_RIGHT"}),
        ("INITIAL", "r-0006", {"from": "TURNING_TO_INITIAL", "on": "arrived"}),
    ]
    assert [e.data["dir"] for e in events(t, "device", "effect", "motor_start")] == [
        "left", "right", "right", "left", "left", "right",
    ]
    send = events(t, "client", "send", "TURN_LEFT")[0]
    start, stop = events(t, "device", "effect", "motor_start")[0], events(t, "device", "effect", "motor_stop")[0]
    assert start.t_us == send.t_us + 1_000 + PROC_US
    assert stop.t_us == start.t_us + TURN_US
    assert [(h.name, h.data["cause"]) for h in events(t, "client", "handle")] == [("DONE", "reply")] * 6
    assert check(t, END) == []


def test_lost_ack_is_retried_with_the_same_req_id_and_turns_once():
    plan = FaultPlan(faults=(drop("s2c", "ACK", "r-0001", 0),))
    t = run_turntable(0, QUIET, plan, n_commands=1, until_us=20_000_000)
    assert [e.req_id for e in events(t, "client", "send", "TURN_LEFT")] == ["r-0001", "r-0001"]
    assert len(events(t, "device", "effect", "motor_start")) == 1
    assert violated(t, END) == set()


def test_client_resends_open_command_after_reconnect_and_device_does_not_push():
    plan = FaultPlan(disconnects=(Disconnect(t_us=3_000_000, duration_us=500_000),))
    t = run_turntable(0, QUIET, plan, n_commands=1, until_us=20_000_000)
    sends = events(t, "client", "send", "TURN_LEFT")
    assert [(e.req_id, e.t_us) for e in sends] == [("r-0001", 0), ("r-0001", 3_500_000)]
    assert len(events(t, "device", "send", "DONE")) == 2  # arrival (lost) and the answer to the resend
    assert len(events(t, "device", "effect", "motor_start")) == 1
    assert violated(t, END) == set()


def test_a_turn_past_the_end_is_refused_with_reason_limit_and_the_order_goes_on():
    # r-0001 (TURN_LEFT) never arrives, so r-0002 turns to RIGHT and r-0003 (TURN_RIGHT) hits the limit.
    plan = FaultPlan(faults=tuple(drop("c2s", "TURN_LEFT", "r-0001", k) for k in range(3)))
    t = run_turntable(0, QUIET, plan, until_us=60_000_000)
    assert errors(t) == [("r-0003", "limit")]
    assert [e.name for e in events(t, "device", "state") if e.data["on"] == "arrived"] == [
        "RIGHT", "INITIAL", "LEFT", "INITIAL",
    ]
    assert [e.name for e in events(t, "client", "send") if e.name in SEQUENCE] == [
        "TURN_LEFT", "TURN_LEFT", "TURN_LEFT", *SEQUENCE[1:],
    ]
    assert violated(t, END) == set()


def test_a_repeated_refused_request_gets_the_stored_reason():
    plan = FaultPlan(faults=(
        *(drop("c2s", "TURN_LEFT", "r-0001", k) for k in range(3)),
        MessageFault(MsgKey("c2s", "TURN_RIGHT", "r-0003", 0), dup_extra_us=500_000),
    ))
    t = run_turntable(0, QUIET, plan, until_us=60_000_000)
    assert errors(t) == [("r-0003", "limit"), ("r-0003", "limit")]
    assert violated(t, END) == set()


def test_a_command_executed_while_turning_is_refused_with_reason_illegal():
    # r-0001 reaches the device only on its last resend, 3 s late, and its ACK is lost: the client
    # gives up at 6 s, and r-0002 executes while the table is still turning (until about 10 s).
    plan = FaultPlan(
        faults=(drop("c2s", "TURN_LEFT", "r-0001", 0), drop("c2s", "TURN_LEFT", "r-0001", 1),
                drop("s2c", "ACK", "r-0001", 0)),
        delays=(Delay(MsgKey("c2s", "TURN_LEFT", "r-0001", 2), 3_000_000),),
    )
    for seed in range(5):
        t = run_turntable(seed, QUIET, plan, until_us=60_000_000)
        assert errors(t)[0] == ("r-0002", "illegal"), seed
        assert violated(t, END) == set(), seed


def seeds(n, fast):
    """Seeds 0..n-1; those from ``fast`` on are marked slow."""
    return [s if s < fast else pytest.param(s, marks=pytest.mark.slow) for s in range(n)]


@pytest.mark.parametrize("seed", seeds(300, fast=20))
def test_correct_turntable_violates_nothing(seed):
    assert check(run_turntable(seed), END) == []


@pytest.mark.parametrize("seed", seeds(30, fast=5))
def test_turntable_run_replays_from_its_plan(seed):
    original = run_turntable(seed)
    assert run_turntable(seed, plan=FaultPlan.from_trace(original)).digest() == original.digest()


def test_random_runs_reach_both_refusal_reasons():
    reasons = {r for seed in range(200) for _, r in errors(run_turntable(seed))}
    assert reasons == {"limit", "illegal"}


def test_no_mutants_yet_and_unknown_ones_are_rejected():
    assert MUTANTS == {}
    with pytest.raises(ValueError):
        run_turntable(0, mutants=["M1"])


def test_turntable_digest_is_stable_across_processes():
    import os
    import subprocess
    import sys

    code = "from replayspect.sut.turntable import run_turntable; print(run_turntable(3).digest())"
    digests = set()
    for hash_seed in ("0", "1", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(ROOT / "src"))
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        digests.add(out.stdout.strip())
    assert digests == {run_turntable(3).digest()}


# -- contracts ---------------------------------------------------------------------------


def test_contract_file_matches_the_oracle():
    cs = SYSTEM.contracts()
    assert cs.protocol == "turntable.v0"
    assert {c.id for c in cs.contracts} == set(CONTRACTS)
    assert cs.transitions == frozenset(TRANSITIONS)


@pytest.mark.parametrize("n", [20, pytest.param(200, marks=pytest.mark.slow)])
def test_judge_matches_oracle_on_first_violations(n):
    cs = SYSTEM.contracts()
    for seed in range(n):
        tr = run_turntable(seed)
        assert judge_first(judge(tr, cs, END)) == first_violations(tr, END), seed


def trace_of(*rows):
    """rows: (t_us, actor, kind, name, req_id, data)"""
    clock = {"t": 0}
    tr = Trace(lambda: clock["t"])
    for t_us, actor, kind, name, req_id, data in rows:
        clock["t"] = t_us
        tr.record(actor, kind, name, req_id, data)
    return tr


@pytest.mark.parametrize("turning, end", [
    ("TURNING_TO_RIGHT", "RIGHT"),      # LEFT straight through to RIGHT
    ("TURNING_TO_INITIAL", "LEFT"),     # stops at the wrong sensor
])
def test_c3_catches_a_turn_that_ends_at_the_wrong_position(turning, end):
    tr = trace_of(
        (0, "device", "state", "INITIAL", None, {"from": None, "on": "init"}),
        (1, "device", "state", "TURNING_TO_LEFT", "r-0001", {"from": "INITIAL", "on": "TURN_LEFT"}),
        (2, "device", "state", "LEFT", "r-0001", {"from": "TURNING_TO_LEFT", "on": "arrived"}),
        (3, "device", "state", turning, "r-0002", {"from": "LEFT", "on": "TURN_RIGHT"}),
        (4, "device", "state", end, "r-0002", {"from": turning, "on": "arrived"}),
    )
    assert judge_first(judge(tr, SYSTEM.contracts(), 10)) == {"C3": 3 if turning == "TURNING_TO_RIGHT" else 4}
    assert first_violations(tr, 10) == judge_first(judge(tr, SYSTEM.contracts(), 10))


def test_random_search_exercises_every_contract_pattern():
    res = search(SYSTEM, range(30))
    assert res.unmatched == set()
    assert res.hits == {}


# -- planning session ---------------------------------------------------------------------


def test_session_describes_the_turntable_without_lift_or_hidden_details():
    d = Session(SessionConfig(system="turntable.v0", budget=5), None).describe()
    assert d["system"] == "turntable.v0"
    assert "Turntable integration protocol" in d["protocol"]
    assert "protocol: turntable.v0" in d["contracts"]
    for word in ("lift", "MOVE_UP", "mutant", "src/", "tests/", ".py"):
        assert word not in d["protocol"] + d["contracts"], word


def test_session_runs_turntable_plans():
    s = Session(SessionConfig(system="turntable.v0", budget=3, seed_base=100), None)
    out = s.run_plan({"base": "random", "faults": [
        {"dir": "c2s", "msg": "TURN_LEFT", "req_id": "r-0001", "k": k, "drop": True} for k in range(3)
    ]})
    assert out["status"] == "ok" and out["violations"] == []
    assert run_once(SYSTEM, 100).violations == []


def test_vocabulary_covers_the_command_and_poll_ids_of_correct_runs():
    vocab = SYSTEM.vocabulary
    commands, polls = dict(vocab.commands), set(vocab.polls)
    for seed in range(30):
        for e in run_turntable(seed):
            if e.kind != "send" or e.req_id is None:
                continue
            if e.req_id.startswith("r-"):
                assert e.req_id in commands
                assert e.name == commands[e.req_id] if e.actor == "client" else e.name in vocab.command_replies
            else:
                assert e.req_id in polls
