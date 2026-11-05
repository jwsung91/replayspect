from pathlib import Path

import pytest

import lift_oracle
from replayspect.contract import (
    Condition,
    ContractError,
    EventPattern,
    Operand,
    Violation,
    contract_patterns,
    first_violation_details,
    first_violations,
    judge,
    load_contracts,
    matched_patterns,
)
from replayspect.contract.spec import parse_duration_us
from replayspect.sut.lift import MUTANTS, run_lift
from replayspect.trace import Event, Trace

LIFT = Path(__file__).parent.parent / "contracts" / "lift.v0.yaml"
END = 90_000_000


def trace_of(*rows):
    """rows: (t_us, actor, kind, name, req_id, data)"""
    clock = {"t": 0}
    tr = Trace(lambda: clock["t"])
    for t_us, actor, kind, name, req_id, data in rows:
        clock["t"] = t_us
        tr.record(actor, kind, name, req_id, data)
    return tr


def one(kind_yaml):
    return load_contracts("contracts:\n" + kind_yaml)


def found(tr, cs, end_us=END):
    return [(v.contract, v.req_id, v.seq) for v in judge(tr, cs, end_us)]


# -- patterns, operands, conditions --------------------------------------------------


def test_event_pattern_parse_and_match():
    p = EventPattern.parse("client.send(MOVE_UP|MOVE_DOWN)")
    ev = Event(0, 0, "client", "send", "MOVE_DOWN", "r-1")
    assert p.matches(ev)
    assert not p.matches(Event(0, 0, "client", "send", "STATUS", "s-1"))
    assert not p.matches(Event(0, 0, "device", "send", "MOVE_UP", "r-1"))
    assert EventPattern.parse("device.state").matches(Event(0, 0, "device", "state", "UP"))


@pytest.mark.parametrize("bad", ["client", "client.sent", "client.send()", "client.send(A|)", "x.y.z", 3])
def test_bad_event_patterns(bad):
    with pytest.raises(ContractError):
        EventPattern.parse(bad)


def test_operands():
    ev = Event(3, 10, "device", "send", "STATUS_REPLY", "s-1", {"state": "UP", "a": {"b": 1}})
    assert Operand.parse("req_id").evaluate(ev, {}) == "s-1"
    assert Operand.parse("data.state").evaluate(ev, {}) == "UP"
    assert Operand.parse("data.a.b").evaluate(ev, {}) == 1
    assert Operand.parse("data.missing").evaluate(ev, {}) is None
    assert Operand.parse("'UP'").evaluate(ev, {}) == "UP"
    assert Operand.parse("null").evaluate(ev, {}) is None
    assert Operand.parse("42").evaluate(ev, {}) == 42
    pat = EventPattern.parse("device.state")
    prev = Event(1, 5, "device", "state", "MOVING_UP", "r-1")
    assert Operand.parse("last(device.state).name").evaluate(ev, {pat: prev}) == "MOVING_UP"
    assert Operand.parse("last(device.state).name").evaluate(ev, {}) is None


@pytest.mark.parametrize("bad", ["data", "foo", "data.a-b", "last(device.state).'x'", "seq"])
def test_bad_operands(bad):
    with pytest.raises(ContractError):
        Operand.parse(bad)


def test_yaml_null_and_integers_are_literals():
    cs = load_contracts("contracts:\n  - {id: K, kind: consistent, event: d.send(X), field: data.v, equals: null}\n"
                        "  - {id: L, kind: consistent, event: d.send(X), field: data.v, equals: 42}")
    tr = trace_of((0, "d", "send", "X", "a", {"v": 42}), (1, "d", "send", "X", "b", {}))
    assert found(tr, cs) == [("K", "a", 0), ("L", "b", 1)]


@pytest.mark.parametrize("bad", ["[1, 2]", "{a: 1}", "true", "1.5"])
def test_non_scalar_operands_are_contract_errors(bad):
    with pytest.raises(ContractError, match="operand"):
        load_contracts(f"contracts:\n  - {{id: K, kind: consistent, event: d.send(X), field: data.v, equals: {bad}}}")


def test_operators_inside_quotes_are_not_split():
    ev = Event(0, 0, "c", "send", "X", "r", {"x": "=="})
    assert Condition.parse("data.x == '=='").holds(ev, {})
    assert not Condition.parse("data.x != \"==\"").holds(ev, {})
    with pytest.raises(ContractError):
        Condition.parse("data.x == '=' == 'a'")


def test_conditions():
    ev = Event(0, 0, "client", "handle", "DONE", "r-2", {"msg_req_id": "r-1"})
    assert Condition.parse("data.msg_req_id != req_id").holds(ev, {})
    assert not Condition.parse("data.msg_req_id == req_id").holds(ev, {})
    with pytest.raises(ContractError):
        Condition.parse("req_id = 'x'")


@pytest.mark.parametrize("text,us", [("15s", 15_000_000), ("500ms", 500_000), ("20us", 20), ("1.5s", 1_500_000)])
def test_durations(text, us):
    assert parse_duration_us(text) == us


# -- loading ---------------------------------------------------------------------------


def test_lift_contracts_load():
    cs = load_contracts(LIFT)
    assert cs.protocol == "lift.v0"
    assert cs.ids() == [f"C{i}" for i in range(1, 9)]
    assert (None, "init", "DOWN") in cs.transitions
    assert {c.id for c in cs.contracts} == set(lift_oracle.CONTRACTS)


@pytest.mark.parametrize("text,match", [
    ("contracts:\n  - {id: X, kind: nope}", "unknown kind"),
    ("contracts:\n  - {id: X, kind: at_most_once, per: req_id}", "missing"),
    ("contracts:\n  - {id: X, kind: at_most_once, per: req_id, event: a.send, extra: 1}", "unexpected"),
    ("contracts:\n  - {id: X, kind: at_most_once, per: name, event: a.send}", "per: req_id"),
    ("contracts:\n  - {id: X, kind: at_most_once, per: req_id, event: a.send}\n"
     "  - {id: X, kind: at_most_once, per: req_id, event: a.recv}", "duplicate"),
    ("contracts:\n  - {id: X, kind: state_machine, event: a.state}", "transitions"),
    ("transitions:\n  - [DOWN, UP]\ncontracts:\n  - {id: X, kind: state_machine, event: a.state}", "from, on, to"),
    ("transitions:\n  - [DOWN, on, UP]\ncontracts:\n  - {id: X, kind: state_machine, event: a.state}", "booleans"),
    ("contracts:\n  - {id: X, kind: exactly_once, per: req_id, start: a.send, event: a.handle, within: soon}", "duration"),
    ("contracts:\n  - {id: X, kind: mutually_exclusive, per: req_id, events: [a.send]}", "at least two"),
    ("contracts: []", "non-empty"),
])
def test_loader_errors(text, match):
    with pytest.raises(ContractError, match=match):
        load_contracts(text)


# -- each kind on hand-made traces -------------------------------------------------------


def test_at_most_once_reports_the_second_occurrence_only():
    cs = one("  - {id: K, kind: at_most_once, per: req_id, event: device.effect(motor_start)}")
    tr = trace_of(
        (0, "device", "effect", "motor_start", "r-1", None),
        (1, "device", "effect", "motor_start", "r-2", None),
        (2, "device", "effect", "motor_stop", "r-1", None),
        (3, "device", "effect", "motor_start", "r-1", None),
        (4, "device", "effect", "motor_start", "r-1", None),
    )
    assert found(tr, cs) == [("K", "r-1", 3)]


EXACTLY = ("  - {id: K, kind: exactly_once, per: req_id, start: client.send(MOVE_UP),"
           " event: client.handle(DONE|ERROR), within: 10us}")


def test_exactly_once_twice_late_never_and_ignored():
    cs = one(EXACTLY)
    tr = trace_of(
        (0, "client", "send", "MOVE_UP", "a", None),     # 0  a: closed twice
        (1, "client", "send", "MOVE_UP", "b", None),     # 1  b: closed late
        (2, "client", "send", "MOVE_UP", "c", None),     # 2  c: never closed
        (3, "client", "handle", "DONE", "a", None),      # 3
        (5, "client", "send", "MOVE_UP", "a", None),     # 4  restart does not move the deadline
        (6, "client", "handle", "ERROR", "a", None),     # 5  second close -> violation
        (12, "client", "handle", "DONE", "b", None),     # 6  11us after start -> late
        (13, "client", "handle", "DONE", "z", None),     # 7  z never started -> ignored
    )
    assert found(tr, cs, end_us=100) == [("K", "a", 5), ("K", "b", 6), ("K", "c", 8)]


def test_exactly_once_open_key_is_fine_before_its_deadline():
    cs = one(EXACTLY)
    tr = trace_of((0, "client", "send", "MOVE_UP", "a", None))
    assert found(tr, cs, end_us=10) == []
    assert found(tr, cs, end_us=11) == [("K", "a", 1)]


def test_state_machine_checks_transitions_and_continuity():
    cs = load_contracts(
        "transitions:\n  - [null, init, A]\n  - [A, go, B]\n  - [B, back, A]\n"
        "contracts:\n  - {id: K, kind: state_machine, event: dev.state}"
    )
    tr = trace_of(
        (0, "dev", "state", "A", None, {"from": None, "on": "init"}),
        (1, "dev", "state", "B", "r", {"from": "A", "on": "go"}),
        (2, "dev", "state", "A", "r", {"from": "A", "on": "back"}),   # undeclared (A --back--> A)
        (3, "dev", "state", "B", "r", {"from": "B", "on": "go"}),     # undeclared
        (4, "dev", "state", "A", "r", {"from": "B", "on": "back"}),   # declared, from matches B
        (5, "dev", "state", "B", "r", {"from": "A", "on": "go"}),     # fine
        (6, "dev", "state", "A", "r", {"from": "B", "on": "back"}),   # fine
        (7, "dev", "state", "A", "r", {"from": "B", "on": "back"}),   # declared but state was A
    )
    assert found(tr, cs) == [("K", "r", 2), ("K", "r", 3), ("K", "r", 7)]


def test_forbid():
    cs = one("  - {id: K, kind: forbid, event: client.handle(DONE), when: data.msg_req_id != req_id}")
    tr = trace_of(
        (0, "client", "handle", "DONE", "r-1", {"msg_req_id": "r-1"}),
        (1, "client", "handle", "DONE", "r-2", {"msg_req_id": "r-1"}),
        (2, "client", "handle", "ERROR", "r-3", {"msg_req_id": None}),
    )
    assert found(tr, cs) == [("K", "r-2", 1)]


def test_consistent_with_last():
    cs = one("  - {id: K, kind: consistent, event: dev.send(STATUS_REPLY), field: data.state,"
             " equals: last(dev.state).name}")
    tr = trace_of(
        (0, "dev", "send", "STATUS_REPLY", "s-1", {"state": "DOWN"}),   # no state yet -> None
        (1, "dev", "state", "DOWN", None, {}),
        (2, "dev", "send", "STATUS_REPLY", "s-2", {"state": "DOWN"}),
        (3, "dev", "state", "MOVING_UP", "r-1", {}),
        (4, "dev", "send", "STATUS_REPLY", "s-3", {"state": "DOWN"}),
    )
    assert found(tr, cs) == [("K", "s-1", 0), ("K", "s-3", 4)]


def test_at_most_one_open_reopens_closed_keys():
    cs = one("  - {id: K, kind: at_most_one_open, per: req_id, opens: c.send(MOVE),"
             " closes: c.handle(DONE)}")
    tr = trace_of(
        (0, "c", "send", "MOVE", "a", None),
        (1, "c", "send", "MOVE", "a", None),      # same key again: fine
        (2, "c", "handle", "DONE", "a", None),
        (3, "c", "send", "MOVE", "a", None),      # reopens a
        (4, "c", "send", "MOVE", "b", None),      # a is open -> violation
    )
    assert found(tr, cs) == [("K", "b", 4)]


def test_count_le_is_checked_at_every_event():
    cs = one("  - {id: K, kind: count_le, per: req_id, event: d.send(DONE), bound: d.recv(MOVE)}")
    tr = trace_of(
        (0, "d", "recv", "MOVE", "a", None),
        (1, "d", "send", "DONE", "a", None),
        (2, "d", "send", "DONE", "a", None),      # 2 > 1
        (3, "d", "recv", "MOVE", "a", None),
        (4, "d", "recv", "MOVE", "a", None),
        (5, "d", "send", "DONE", "a", None),      # 3 <= 3, fine; the earlier excess still counted
    )
    assert found(tr, cs) == [("K", "a", 2)]


def test_mutually_exclusive_reports_once():
    cs = one("  - {id: K, kind: mutually_exclusive, per: req_id, events: [d.send(DONE), d.send(ERROR)]}")
    tr = trace_of(
        (0, "d", "send", "ERROR", "a", None),
        (1, "d", "send", "ERROR", "a", None),
        (2, "d", "send", "DONE", "a", None),
        (3, "d", "send", "ERROR", "a", None),
        (4, "d", "send", "DONE", "b", None),
    )
    assert found(tr, cs) == [("K", "a", 2)]


def test_first_violations():
    cs = load_contracts(LIFT)
    tr = trace_of(
        (0, "device", "effect", "motor_start", "r-1", {"dir": "up"}),
        (1, "device", "effect", "motor_start", "r-1", {"dir": "up"}),
        (2, "device", "effect", "motor_start", "r-1", {"dir": "up"}),
    )
    assert first_violations(judge(tr, cs, END)) == {"C1": 1}


# -- equivalence with the reference oracle -----------------------------------------------


@pytest.mark.parametrize("n", [10, pytest.param(100, marks=pytest.mark.slow)])
@pytest.mark.parametrize("mutant", [None] + sorted(MUTANTS))
def test_judge_matches_oracle_on_first_violations(mutant, n):
    cs = load_contracts(LIFT)
    for seed in range(n):
        tr = run_lift(seed, mutants=[mutant] if mutant else [])
        assert first_violations(judge(tr, cs, END)) == lift_oracle.first_violations(tr, END), seed


# -- judge API details -------------------------------------------------------------------


def test_end_before_last_event_is_rejected():
    tr = trace_of((5_000, "d", "send", "X", "a", None))
    cs = one("  - {id: K, kind: at_most_once, per: req_id, event: d.send(X)}")
    assert judge(tr, cs, 5_000) == []
    with pytest.raises(ValueError, match="before the last event"):
        judge(tr, cs, 5)


def test_first_violation_details_breaks_seq_ties_by_req_id():
    vs = [Violation("C2", "b", 9, ""), Violation("C2", "a", 9, ""), Violation("C1", None, 9, ""),
          Violation("C1", "z", 3, ""), Violation("C3", "a", 1, "")]
    assert [(v.contract, v.req_id, v.seq) for v in first_violation_details(vs)] == [
        ("C3", "a", 1), ("C1", "z", 3), ("C2", "a", 9),
    ]


def test_contract_patterns_include_last_references():
    pats = {str(p) for p in contract_patterns(load_contracts(LIFT))}
    assert pats == {
        "client.handle(DONE)", "client.handle(DONE|ERROR)", "client.send(MOVE_DOWN|MOVE_UP)",
        "device.effect(motor_start)", "device.recv(MOVE_DOWN|MOVE_UP)", "device.send(DONE)",
        "device.send(DONE|ERROR)", "device.send(ERROR)", "device.send(STATUS_REPLY)",
        "device.state",  # used by C3 and by C5's last(device.state)
    }


def test_matched_patterns():
    cs = load_contracts(LIFT)
    tr = trace_of((0, "device", "state", "DOWN", None, {"from": None, "on": "init"}))
    assert {str(p) for p in matched_patterns(tr, cs)} == {"device.state"}
