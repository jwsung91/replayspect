"""contracts/lift.v0.rev2.yaml: C1-C8 as in lift.v0.yaml, C9-C13 with their sources, what each new
contract catches, and which contracts each mutant breaks under it."""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from replayspect.contract import first_violations, judge, load_contracts
from replayspect.sut.lift import MUTANTS, run_lift
from replayspect.trace import Trace

ROOT = Path(__file__).parent.parent
REV2 = load_contracts(ROOT / "contracts" / "lift.v0.rev2.yaml")
V0 = load_contracts(ROOT / "contracts" / "lift.v0.yaml")
NEW = [c for c in REV2.contracts if c.id not in {"C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"}]
END = 90_000_000

#: What each mutant breaks under rev2 (seeds 0-999 with SEARCH_PROFILE; docs/design-v0.md "rev2").
BREAKS = {"M1": {"C8"}, "M2": {"C8"}, "M3": {"C7"}, "M4": {"C3", "C9"}, "M5": {"C5"}, "M6": {"C6", "C2"},
          "M7": {"C4"}, "M8": {"C2", "C6"}, "M9": {"C8"}, "M10": {"C8", "C10"}, "M11": {"C8"}}


def trace_of(*rows):
    """rows: (t_us, actor, kind, name, req_id, data)"""
    clock = {"t": 0}
    tr = Trace(lambda: clock["t"])
    for t_us, actor, kind, name, req_id, data in rows:
        clock["t"] = t_us
        tr.record(actor, kind, name, req_id, data)
    return tr


def test_rev2_keeps_v0_and_adds_five():
    assert REV2.protocol == V0.protocol and REV2.transitions == V0.transitions
    assert REV2.contracts[:8] == V0.contracts
    assert [(c.id, c.kind) for c in NEW] == [("C9", "exactly_once"), ("C10", "only_after"), ("C11", "consistent"),
                                             ("C12", "count_le"), ("C13", "count_le")]


def _doc_lines(spec: str) -> str:
    lines = (ROOT / "docs" / "protocol-lift.md").read_text(encoding="utf-8").splitlines()
    picked = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        picked += lines[int(a) - 1:int(b or a)]
    return " ".join(" ".join(picked).replace("`", "").split())


@pytest.mark.parametrize("c", NEW, ids=lambda c: c.id)
def test_each_new_contract_quotes_its_lines_and_names_no_defect(c):
    assert c.grade == "stated" and set(c.source) == {"doc", "lines", "quote", "found"}
    assert c.source["doc"] == "docs/protocol-lift.md"
    text = _doc_lines(c.source["lines"])
    for piece in c.source["quote"].split(" ... "):
        assert piece in text, (c.id, piece)
    # The contract file is shown to planners: no defect, mutant or blind slot in what it says.
    words = " ".join([c.desc, c.source["quote"], c.source["found"]])
    assert not re.search(r"\bM\d+\b|\bB\d\d\b|blind|defect|mutant|testbed-0", words, re.IGNORECASE), c.id


@pytest.mark.parametrize("cid, rows, seq", [
    ("C9", [(0, "device", "effect", "motor_start", "r-1", None),
            (3_002_000, "device", "effect", "motor_stop", "r-1", None),       # on the deadline: fine
            (4_000_000, "device", "effect", "motor_start", "r-2", None),
            (7_002_001, "device", "effect", "motor_stop", "r-2", None)], 3),  # 1 us late
    ("C10", [(0, "device", "send", "DONE", "r-1", None)], 0),
    ("C11", [(0, "device", "send", "ERROR", "r-1", {"reason": "illegal"}),
             (1, "device", "send", "ERROR", "r-2", {"reason": "busy"})], 1),
    ("C12", [(0, "device", "recv", "MOVE_UP", "r-1", None), (0, "device", "send", "ACK", "r-1", None),
             (5, "device", "send", "ACK", "r-1", None)], 2),                  # an ACK nobody asked for
    ("C13", [(0, "device", "recv", "STATUS", "s-1", None), (0, "device", "send", "STATUS_REPLY", "s-1", {"state": "DOWN"}),
             (5, "device", "send", "STATUS_REPLY", "s-1", {"state": "DOWN"})], 2),
])
def test_each_new_contract_catches_a_trace_that_breaks_it(cid, rows, seq):
    only = replace(REV2, contracts=tuple(c for c in REV2.contracts if c.id == cid))
    assert first_violations(judge(trace_of(*rows), only, END)) == {cid: seq}


def test_a_correct_device_breaks_none_of_the_new_contracts():
    tr = trace_of(
        (0, "device", "recv", "MOVE_UP", "r-1", None), (0, "device", "send", "ACK", "r-1", None),
        (50_000, "device", "effect", "motor_start", "r-1", None),
        (1_000_000, "device", "recv", "MOVE_UP", "r-1", None), (1_000_000, "device", "send", "ACK", "r-1", None),
        (3_050_000, "device", "effect", "motor_stop", "r-1", None), (3_050_000, "device", "send", "DONE", "r-1", None),
        (4_000_000, "device", "recv", "MOVE_UP", "r-1", None), (4_000_000, "device", "send", "DONE", "r-1", None),
        (5_000_000, "device", "recv", "MOVE_UP", "r-2", None), (5_000_000, "device", "send", "ACK", "r-2", None),
        (5_050_000, "device", "send", "ERROR", "r-2", {"reason": "illegal"}),
        (6_000_000, "device", "recv", "STATUS", "s-1", None), (6_000_000, "device", "send", "STATUS_REPLY", "s-1", {"state": "UP"}),
    )
    assert [v for v in judge(tr, REV2, END) if v.contract in {c.id for c in NEW}] == []


@pytest.mark.parametrize("n", [10, pytest.param(100, marks=pytest.mark.slow)])
@pytest.mark.parametrize("mutant", [None] + sorted(MUTANTS))
def test_each_implementation_breaks_only_its_rev2_contracts(mutant, n):
    for seed in range(n):
        got = {v.contract for v in judge(run_lift(seed, mutants=[mutant] if mutant else []), REV2, END)}
        assert got <= (BREAKS[mutant] if mutant else set()), (mutant, seed, got)
