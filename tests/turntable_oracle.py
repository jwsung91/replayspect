"""Reference oracle for the turntable contracts.

The turntable contracts are the lift contracts with other command names and
other transitions, so this binds :mod:`lift_oracle` to them. The transitions
are written out by hand here, not read from the contract file, so the oracle
stays an independent statement of what C3 allows.
"""

from __future__ import annotations

import lift_oracle
from replayspect.trace import Trace

COMMANDS = ("TURN_LEFT", "TURN_RIGHT")
TRANSITIONS = {
    (None, "init", "INITIAL"),
    ("INITIAL", "TURN_LEFT", "TURNING_TO_LEFT"),
    ("TURNING_TO_LEFT", "arrived", "LEFT"),
    ("INITIAL", "TURN_RIGHT", "TURNING_TO_RIGHT"),
    ("TURNING_TO_RIGHT", "arrived", "RIGHT"),
    ("LEFT", "TURN_RIGHT", "TURNING_TO_INITIAL"),
    ("RIGHT", "TURN_LEFT", "TURNING_TO_INITIAL"),
    ("TURNING_TO_INITIAL", "arrived", "INITIAL"),
}
CONTRACTS = lift_oracle.CONTRACTS
KW = {"moves": COMMANDS, "transitions": TRANSITIONS}


def check(trace: Trace, end_us: int) -> list[lift_oracle.Violation]:
    return lift_oracle.check(trace, end_us, **KW)


def first_violations(trace: Trace, end_us: int) -> dict[str, int]:
    return lift_oracle.first_violations(trace, end_us, **KW)


def violated(trace: Trace, end_us: int) -> set[str]:
    return lift_oracle.violated(trace, end_us, **KW)
