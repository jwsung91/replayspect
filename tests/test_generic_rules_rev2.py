"""contracts/generic/ rev2: the present rules and P4, bound with progress_states (WP6/7d, after stage 0b).

The present three files stay byte for byte (testbed-07 registered two of them); rev2 is beside them. Under
rev2 the present rules expand to the same contracts as before, and P4 is the one stage 0b wrote by hand
(docs/notes/generic-contracts-rev2/)."""

from pathlib import Path

import pytest

from replayspect.contract import judge_report, load_contracts
from replayspect.runner import get_system
from replayspect.trace import Event, Trace
from replayspect.tracefile import file_sha256

ROOT = Path(__file__).parent.parent
GENERIC = ROOT / "contracts" / "generic"
NOTE = ROOT / "docs" / "notes" / "generic-contracts-rev2"
SYSTEMS = ("lift.v0", "turntable.v0")

#: rules.yaml and the turntable binding: testbed-07's registration. The lift binding: as written in WP6/7b
#: stage 4 (#62), unchanged since.
PRESENT = {
    "rules.yaml": "fcbfd0af403d2227d6231432d7395e0568c0dee5de06f10b8123f5bd2197a115",
    "turntable.v0.yaml": "1b3b445b47c05361fa683392f72c92a1716e738d82045a8d2f3f91eabaa8efdc",
    "lift.v0.yaml": "e85499d7783a189b47b9237ebe415b2890edbdcbf11c1071869963dc64a9d2d4",
}


def contracts(path):
    return {c.id: c for c in load_contracts(path).contracts}


def same(c):
    return c.kind, {k: str(v) for k, v in dict(c.params).items()}, c.grade, c.source


@pytest.mark.parametrize("name", sorted(PRESENT))
def test_the_present_files_are_byte_for_byte_the_registered_ones(name):
    assert file_sha256(GENERIC / name) == PRESENT[name]


@pytest.mark.parametrize("name", SYSTEMS)
def test_the_present_rules_expand_to_the_same_contracts_under_rev2(name):
    old, new = contracts(GENERIC / f"{name}.yaml"), contracts(GENERIC / f"{name}.rev2.yaml")
    assert sorted(new) == sorted([*old, "P4"])
    for cid, c in old.items():
        assert same(new[cid]) == same(c), cid


@pytest.mark.parametrize("name", SYSTEMS)
def test_p4_is_the_candidate_stage_0b_confirmed(name):
    new, hand = contracts(GENERIC / f"{name}.rev2.yaml")["P4"], contracts(NOTE / f"P4.{name}.yaml")["P4"]
    assert same(new) == same(hand)


def test_the_rev2_bindings_name_the_rev2_rules():
    for name in SYSTEMS:
        assert load_contracts(GENERIC / f"{name}.rev2.yaml").protocol == name
        assert "rules: rules.rev2.yaml" in (GENERIC / f"{name}.rev2.yaml").read_text()


def trace_of(*rows):
    return Trace.from_events([Event(i, t, a, k, n, r, d or {}) for i, (t, a, k, n, r, d) in enumerate(rows)])


@pytest.mark.parametrize("start", ["before", "after", "none"])
def test_p4_the_turning_state_only_after_the_motor_start(start):
    cs = load_contracts(GENERIC / "turntable.v0.rev2.yaml")
    p4 = cs.__class__(cs.protocol, cs.transitions, tuple(c for c in cs.contracts if c.id == "P4"))
    go = (55_000, "device", "effect", "motor_start", "r-0001", {"dir": "left"})
    turn = (55_000, "device", "state", "TURNING_TO_LEFT", "r-0001", {"from": "INITIAL", "on": "TURN_LEFT"})
    rows = {"before": (go, turn), "after": (turn, go), "none": (turn,)}[start]
    found, _ = judge_report(trace_of(*rows), p4, 10_000_000)
    assert [v.req_id for v in found] == ([] if start == "before" else ["r-0001"])


@pytest.mark.slow
@pytest.mark.parametrize("name", SYSTEMS)
def test_no_false_positive_on_seeds_0_999_of_the_correct_system(name):
    system, cs = get_system(name), load_contracts(GENERIC / f"{name}.rev2.yaml")
    for seed in range(1000):
        trace = system.run(seed, None, (), system.until_us)
        assert judge_report(trace, cs, system.until_us) == ([], {}), seed
