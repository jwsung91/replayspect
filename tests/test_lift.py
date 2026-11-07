import pytest

from lift_oracle import CONTRACTS, check, violated
from replayspect.sim.link import ChannelProfile, FaultPlan, MessageFault, MsgKey, Disconnect
from replayspect.sut.lift import MUTANTS, TRAVEL_US, PROC_US, run_lift

END = 90_000_000
QUIET = ChannelProfile()  # 1 ms links, no faults

#: What each mutant is designed to break. M6 and M8 may also break a second
#: contract as a direct consequence (see docs/design-v0.md).
INTENDED = {"M1": "C8", "M2": "C8", "M3": "C7", "M4": "C3", "M5": "C5", "M6": "C6", "M7": "C4", "M8": "C2",
            "M9": "C8", "M10": "C8", "M11": "C8"}
ALSO_ALLOWED = {"M6": {"C2"}, "M8": {"C6"}}
#: First seed (with SEARCH_PROFILE) at which the intended contract is violated.
FIRST_DETECTION = {"M1": 0, "M2": 0, "M3": 0, "M4": 58, "M5": 0, "M6": 0, "M7": 1, "M8": 5,
                   "M9": 113, "M10": 36, "M11": 65}


def events(trace, actor=None, kind=None, name=None):
    return [e for e in trace if (actor is None or e.actor == actor)
            and (kind is None or e.kind == kind) and (name is None or e.name == name)]


# -- correct behaviour -------------------------------------------------------------


def test_happy_path_trace_shape():
    t = run_lift(0, QUIET, n_commands=2, until_us=20_000_000)
    assert [(e.name, e.req_id, e.data) for e in events(t, "device", "state")] == [
        ("DOWN", None, {"from": None, "on": "init"}),
        ("MOVING_UP", "r-0001", {"from": "DOWN", "on": "MOVE_UP"}),
        ("UP", "r-0001", {"from": "MOVING_UP", "on": "arrived"}),
        ("MOVING_DOWN", "r-0002", {"from": "UP", "on": "MOVE_DOWN"}),
        ("DOWN", "r-0002", {"from": "MOVING_DOWN", "on": "arrived"}),
    ]
    send = events(t, "client", "send", "MOVE_UP")[0]
    start = events(t, "device", "effect", "motor_start")[0]
    stop = events(t, "device", "effect", "motor_stop")[0]
    assert start.t_us == send.t_us + 1_000 + PROC_US
    assert stop.t_us == start.t_us + TRAVEL_US
    assert start.data == {"dir": "up"}
    handles = events(t, "client", "handle")
    assert [(h.name, h.req_id, h.data) for h in handles] == [
        ("DONE", "r-0001", {"msg_req_id": "r-0001", "cause": "reply"}),
        ("DONE", "r-0002", {"msg_req_id": "r-0002", "cause": "reply"}),
    ]


def test_lost_ack_is_retried_with_the_same_req_id_and_executes_once():
    plan = FaultPlan(faults=(MessageFault(MsgKey("s2c", "ACK", "r-0001", 0), drop=True),))
    t = run_lift(0, QUIET, plan, n_commands=1, until_us=20_000_000)
    assert [e.req_id for e in events(t, "client", "send", "MOVE_UP")] == ["r-0001", "r-0001"]
    assert len(events(t, "device", "effect", "motor_start")) == 1
    assert [e.name for e in events(t, "device", "send") if e.req_id == "r-0001"] == ["ACK", "ACK", "DONE"]
    assert violated(t, END) == set()


def test_client_resends_open_command_after_reconnect_and_device_does_not_push():
    # DONE for r-0001 is lost in the disconnect; the client recovers by resending.
    plan = FaultPlan(disconnects=(Disconnect(t_us=3_000_000, duration_us=500_000),))
    t = run_lift(0, QUIET, plan, n_commands=1, until_us=20_000_000)
    sends = events(t, "client", "send", "MOVE_UP")
    assert [e.req_id for e in sends] == ["r-0001", "r-0001"]
    assert sends[1].t_us == 3_500_000
    done = [e for e in events(t, "device", "send", "DONE")]
    assert len(done) == 2  # arrival (lost) and the answer to the resend
    assert len(events(t, "device", "effect", "motor_start")) == 1
    assert violated(t, END) == set()


def test_illegal_command_gets_error_and_no_motion():
    # Force an illegal state by making the first command never reach the device:
    # the client gives up, then sends MOVE_DOWN while the lift is still DOWN.
    plan = FaultPlan(faults=tuple(
        MessageFault(MsgKey("c2s", "MOVE_UP", "r-0001", k), drop=True) for k in range(3)
    ))
    t = run_lift(0, QUIET, plan, n_commands=2, until_us=30_000_000)
    err = [e for e in events(t, "device", "send", "ERROR")]
    assert [(e.req_id, e.data["reason"]) for e in err] == [("r-0002", "illegal")]
    assert events(t, "device", "effect", "motor_start") == []
    assert [(h.name, h.data["cause"]) for h in events(t, "client", "handle")] == [
        ("ERROR", "ack_timeout"), ("ERROR", "reply"),
    ]
    assert violated(t, END) == set()


def seeds(n, fast):
    """Seeds 0..n-1; those from ``fast`` on are marked slow."""
    return [s if s < fast else pytest.param(s, marks=pytest.mark.slow) for s in range(n)]


@pytest.mark.parametrize("seed", seeds(300, fast=20))
def test_correct_lift_violates_nothing(seed):
    assert check(run_lift(seed), END) == []


@pytest.mark.parametrize("seed", seeds(30, fast=5))
def test_lift_run_replays_from_its_plan(seed):
    original = run_lift(seed)
    # The plan fixes the link; the seed still drives the endpoints (think time).
    replay = run_lift(seed, plan=FaultPlan.from_trace(original))
    assert replay.digest() == original.digest()


# -- mutants ---------------------------------------------------------------------------


def test_mutant_table_is_complete():
    assert set(MUTANTS) == set(INTENDED) == set(FIRST_DETECTION)
    assert set(INTENDED.values()) <= set(CONTRACTS)


@pytest.mark.parametrize("mutant", sorted(MUTANTS))
def test_mutant_is_first_caught_at_pinned_seed(mutant):
    contract = INTENDED[mutant]
    first = FIRST_DETECTION[mutant]
    for seed in range(first):
        assert contract not in violated(run_lift(seed, mutants=[mutant]), END)
    assert contract in violated(run_lift(first, mutants=[mutant]), END)


@pytest.mark.parametrize("n", [10, pytest.param(100, marks=pytest.mark.slow)])
@pytest.mark.parametrize("mutant", sorted(MUTANTS))
def test_mutant_only_breaks_its_own_contracts(mutant, n):
    allowed = {INTENDED[mutant]} | ALSO_ALLOWED.get(mutant, set())
    for seed in range(n):
        assert violated(run_lift(seed, mutants=[mutant]), END) <= allowed, seed


def test_unknown_mutant_is_rejected():
    with pytest.raises(ValueError):
        run_lift(0, mutants=["M99"])


def test_lift_digest_is_stable_across_processes():
    import os
    import subprocess
    import sys
    from pathlib import Path

    src = Path(__file__).parent.parent / "src"
    code = "from replayspect.sut.lift import run_lift; print(run_lift(3, mutants=['M7']).digest())"
    digests = set()
    for hash_seed in ("0", "1", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(src))
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        digests.add(out.stdout.strip())
    assert digests == {run_lift(3, mutants=["M7"]).digest()}
