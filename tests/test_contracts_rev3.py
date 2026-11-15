"""contracts/lift.v0.rev3.yaml: rev2 unchanged plus C14, its source, and which contracts each mutant breaks."""

from pathlib import Path

import pytest

from replayspect.contract import judge, load_contracts
from replayspect.sut.lift import MUTANTS, run_lift
from test_contracts_rev2 import BREAKS as BREAKS_REV2
from test_contracts_rev2 import _doc_lines, trace_of

ROOT = Path(__file__).parent.parent
REV2 = load_contracts(ROOT / "contracts" / "lift.v0.rev2.yaml")
REV3 = load_contracts(ROOT / "contracts" / "lift.v0.rev3.yaml")
END = 90_000_000

#: What each mutant breaks under rev3 (seeds 0-999 with SEARCH_PROFILE; docs/design-v0.md "rev3").
BREAKS = {**BREAKS_REV2, "M1": {"C8", "C14"}, "M11": {"C8", "C14"}}


def test_rev3_keeps_rev2_and_adds_one():
    assert REV3.protocol == REV2.protocol and REV3.transitions == REV2.transitions
    assert REV3.contracts[:13] == REV2.contracts
    (c14,) = REV3.contracts[13:]
    assert (c14.id, c14.kind, str(c14.params["event"]), str(c14.params["after"])) == (
        "C14", "never_after", "device.send(ACK)", "device.send(DONE|ERROR)")


def test_c14_quotes_its_lines():
    c = REV3.contracts[13]
    assert c.grade == "stated" and set(c.source) == {"doc", "lines", "quote"}
    assert c.source["doc"] == "docs/protocol-lift.md" and c.source["lines"] == "37-39"
    assert " ".join(c.source["quote"].split()) in _doc_lines(c.source["lines"])


def test_c14_catches_an_ack_after_the_final_answer_and_nothing_else():
    def found(*rows):
        return [(v.contract, v.req_id) for v in judge(trace_of(*rows), REV3, END) if v.contract == "C14"]
    # a correct device: ACK again while in progress, DONE or ERROR again once finished
    assert found((0, "device", "send", "ACK", "r-1", None), (1, "device", "send", "ACK", "r-1", None),
                 (2, "device", "send", "DONE", "r-1", None), (3, "device", "send", "DONE", "r-1", None),
                 (4, "device", "send", "ACK", "r-2", None), (5, "device", "send", "ERROR", "r-2", None),
                 (6, "device", "send", "ERROR", "r-2", None)) == []
    assert found((0, "device", "send", "DONE", "r-1", None), (1, "device", "send", "ACK", "r-1", None)) == [
        ("C14", "r-1")]
    assert found((0, "device", "send", "ERROR", "r-1", None), (1, "device", "send", "ACK", "r-1", None)) == [
        ("C14", "r-1")]


@pytest.mark.parametrize("n", [10, pytest.param(100, marks=pytest.mark.slow)])
@pytest.mark.parametrize("mutant", [None] + sorted(MUTANTS))
def test_each_implementation_breaks_only_its_rev3_contracts(mutant, n):
    for seed in range(n):
        got = {v.contract for v in judge(run_lift(seed, mutants=[mutant] if mutant else []), REV3, END)}
        assert got <= (BREAKS[mutant] if mutant else set()), (mutant, seed, got)
