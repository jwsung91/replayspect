"""contracts/generic/: the generic rules written once against roles, expanded by the loader (WP6/7b stage 4).

The expansion must give what stage 3 wrote by hand (docs/notes/generic-contracts/): the same patterns, and
the same first violations on simulator seeds for the correct systems and every lift mutant. The judge does
not change.
"""

from pathlib import Path

import pytest

from replayspect.claim import Input, judge_one
from replayspect.contract import ContractError, judge_report, load_contracts
from replayspect.contract.checkers import first_violation_details
from replayspect.runner import get_system
from replayspect.sut.lift import MUTANTS
from replayspect.trace import Event, Trace

ROOT = Path(__file__).parent.parent
GENERIC = ROOT / "contracts" / "generic"
HAND = ROOT / "docs" / "notes" / "generic-contracts"
SYSTEMS = ("lift.v0", "turntable.v0")
#: stage 3's hand-written ids -> the expanded ids (G7 did not go on; P1 was a file of its own)
HAND_IDS = {"G1a": "G1.motor_start", "G1b": "G1.motor_stop", "G2a": "G2.ack", "G2b": "G2.final",
            "G2c": "G2.poll.STATUS", "G3": "G3", "G4": "G4", "G5": "G5", "G6": "G6", "G6b": "G6b", "P1": "P1"}


def hand(name):
    """Stage 3's instances for one system, under the expanded ids."""
    cs = load_contracts(HAND / f"{name}.yaml")
    p1 = load_contracts(HAND / f"P1.{name}.yaml")
    return {HAND_IDS[c.id]: c for c in cs.contracts + p1.contracts if c.id in HAND_IDS}


def generic(name):
    return load_contracts(GENERIC / f"{name}.yaml")


# -- the expansion ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", SYSTEMS)
def test_expansion_gives_stage_3s_instances(name):
    cs, want = generic(name), hand(name)
    assert cs.protocol == name
    assert sorted(cs.ids()) == sorted(want)
    for c in cs.contracts:
        h = want[c.id]
        assert (c.kind, dict(c.params)) == (h.kind, dict(h.params)), c.id
        assert c.grade == "generic" and c.source == h.source, c.id


def binding(roles, rules):
    return {"protocol": "x.v0", "rules": rules, "roles": roles}


ROLES = {"requests": ["GO"], "acknowledgement": "ACK", "final_success": "DONE", "final_failure": "ERROR",
         "polls": {"STATUS": "STATUS_REPLY", "PING": "PONG"}, "effects": ["start", "stop"],
         "action": {"starts": "start", "ends": "stop"}, "rest_states": ["IDLE"]}


def test_each_writes_one_contract_per_name_and_a_mapping_gives_its_value(tmp_path):
    rules = tmp_path / "r.yaml"
    rules.write_text("""rules:
  - rule: R1
    quote: one reply per poll
    each: polls
    contract: {id: "R1.{each}", desc: "x", kind: count_le, per: req_id,
               event: "device.send({each.value})", bound: "device.recv({each})"}
  - rule: R2
    quote: ends after
    contract: {id: R2, desc: "x", kind: only_after, per: req_id,
               event: "device.send({final_success})", after: "device.state({rest_states}|{action.ends})"}
""")
    cs = load_contracts(binding(ROLES, str(rules)))
    got = {c.id: (str(c.params["event"]), str(c.params.get("bound") or c.params.get("after"))) for c in cs.contracts}
    assert got == {"R1.STATUS": ("device.send(STATUS_REPLY)", "device.recv(STATUS)"),
                   "R1.PING": ("device.send(PONG)", "device.recv(PING)"),
                   "R2": ("device.send(DONE)", "device.state(IDLE|stop)")}
    assert all(c.grade == "generic" for c in cs.contracts)
    assert cs.contracts[0].source == {"rule": "R1", "quote": "one reply per poll"}


def test_a_binding_file_finds_its_rules_next_to_it(tmp_path):
    (tmp_path / "rules.yaml").write_text((GENERIC / "rules.yaml").read_text())
    (tmp_path / "x.yaml").write_text((GENERIC / "lift.v0.yaml").read_text())
    assert load_contracts(tmp_path / "x.yaml").ids() == generic("lift.v0").ids()


@pytest.mark.parametrize("roles, rules, message", [
    ({k: v for k, v in ROLES.items() if k != "effects"}, None, "G1: no role 'effects'"),
    ({**ROLES, "acknowledgement": "A|B"}, None, "role acknowledgement"),
    ({**ROLES, "requests": [True]}, None, "role requests"),        # an unquoted yes/on read as a boolean
    ({**ROLES, "requests": []}, None, "role requests"),
    ({**ROLES, "action": {"starts": "start"}}, None, "G6: no role 'action.ends'"),
    (ROLES, "rules:\n  - {rule: R, contract: {id: R, desc: x, kind: at_most_once, per: req_id,"
            " event: 'device.effect({each})'}}\n", "R: {each} outside an each rule"),
    (ROLES, "rules:\n  - {rule: R, contract: {id: R, desc: x, kind: at_most_once, per: req_id,"
            " event: device.effect(x), grade: stated}}\n", "R: a rule's contract sets no grade or source"),
    (ROLES, "rules:\n  - {rule: R, each: acknowledgement, contract: {id: R, desc: x, kind: at_most_once,"
            " per: req_id, event: device.effect(x)}}\n", "R: each needs a list or mapping role"),
])
def test_expansion_refuses_what_it_cannot_write(tmp_path, roles, rules, message):
    path = GENERIC / "rules.yaml"
    if rules is not None:
        path = tmp_path / "r.yaml"
        path.write_text(rules)
    with pytest.raises(ContractError, match=message.replace("|", r"\|").replace("{", r"\{").replace("}", r"\}")):
        load_contracts(binding(roles, str(path)))


def test_a_binding_has_no_contracts_of_its_own():
    with pytest.raises(ContractError, match="roles and contracts"):
        load_contracts({**binding(ROLES, str(GENERIC / "rules.yaml")),
                        "contracts": [{"id": "K", "kind": "state_machine", "event": "device.state"}]})


# -- the judge does not change: same first violations as the hand-written instances ---------------------


def firsts(cs, contracts, trace, end_us):
    one = cs.__class__(cs.protocol, cs.transitions, tuple(contracts))
    found, unjudged = judge_report(trace, one, end_us)
    return {v.contract: (v.seq, v.req_id) for v in first_violation_details(found)}, unjudged


RUNS = [("lift.v0", ())] + [("lift.v0", (m,)) for m in sorted(MUTANTS)] + [("turntable.v0", ())]


@pytest.mark.parametrize("name, mutants", RUNS, ids=lambda x: x if isinstance(x, str) else "+".join(x) or "-")
def test_expanded_contracts_judge_like_the_hand_written_ones_on_seeds_0_99(name, mutants):
    system, cs, want = get_system(name), generic(name), hand(name)
    hand_cs = load_contracts(HAND / f"{name}.yaml")
    caught = 0
    for seed in range(100):
        trace = system.run(seed, None, mutants, system.until_us)
        got = firsts(cs, cs.contracts, trace, system.until_us)
        exp = firsts(hand_cs, [want[i] for i in cs.ids()], trace, system.until_us)
        exp = ({HAND_IDS.get(k, k): v for k, v in exp[0].items()},
               {HAND_IDS.get(k, k): v for k, v in exp[1].items()})
        assert got == exp, (name, mutants, seed)
        caught += bool(got[0])
    if not mutants:
        assert caught == 0
    if mutants in (("M1",), ("M2",), ("M3",)):  # caught on most seeds: the comparison is not vacuous
        assert caught > 50, caught


@pytest.mark.slow
@pytest.mark.parametrize("name", SYSTEMS)
def test_no_false_positive_on_seeds_0_999_of_the_correct_system(name):
    system, cs = get_system(name), generic(name)
    for seed in range(1000):
        trace = system.run(seed, None, (), system.until_us)
        assert judge_report(trace, cs, system.until_us) == ([], {}), seed


# -- G6 and G6b: the two orders that tell them apart, and where G6b is not judged --------------------------


def trace_of(*rows):
    return Trace.from_events([Event(i, t, a, k, n, r, d or {}) for i, (t, a, k, n, r, d) in enumerate(rows)])


def violated(cid, trace):
    cs = generic("lift.v0")
    c = next(c for c in cs.contracts if c.id == cid)
    found, unjudged = judge_report(trace, cs.__class__(cs.protocol, cs.transitions, (c,)), 10_000_000)
    return [v.req_id for v in found], unjudged


def test_stop_then_done_then_state_breaks_g6b_not_g6():
    tr = trace_of((0, "device", "effect", "motor_stop", "r-1", None), (1, "device", "send", "DONE", "r-1", None),
                  (2, "device", "state", "UP", "r-1", {"from": "MOVING_UP", "on": "arrived"}))
    assert violated("G6b", tr) == (["r-1"], {}) and violated("G6", tr) == ([], {})


def test_state_then_done_then_stop_breaks_g6_not_g6b():
    tr = trace_of((0, "device", "state", "UP", "r-1", {"from": "MOVING_UP", "on": "arrived"}),
                  (1, "device", "send", "DONE", "r-1", None), (2, "device", "effect", "motor_stop", "r-1", None))
    assert violated("G6", tr) == (["r-1"], {}) and violated("G6b", tr) == ([], {})


def test_g6b_is_not_judged_on_a_device_log_without_complete_state_lines():
    cs = generic("lift.v0")
    c = next(c for c in cs.contracts if c.id == "G6b")
    events = [Event(0, 1, "device", "send", "DONE", "r-1")]  # no state line: a missing one could explain it
    inp = Input("x", "device log", events, 10, "end", None, None, frozenset({"recv", "send", "effect"}))
    assert judge_one(c, cs, inp) == {"status": "not judged", "needs_complete": ["device state"], "violations": []}
    full = Input("x", "device log", events, 10, "end", None, None, frozenset({"recv", "send", "effect", "state"}))
    assert judge_one(c, cs, full)["status"] == "violated"


def test_g6b_does_not_judge_a_key_with_a_reordered_line():
    flag = {"line": 4, "flags": ["out_of_order"]}
    tr = Trace.from_events([Event(0, 1, "device", "send", "DONE", "r-1", log={"line": 3}),
                            Event(1, 2, "device", "state", "UP", "r-1", {"from": "MOVING_UP", "on": "arrived"}, log=flag)])
    assert violated("G6b", tr) == ([], {"G6b": ["r-1"]})
