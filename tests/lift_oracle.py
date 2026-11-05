"""Reference oracle for the lift contracts, written by hand in plain Python.

This is not the product's checker. It pins down what each contract means
on a trace, so the lift and its mutants can be tested now, and the
contract-driven checkers built later can be cross-checked against it.

Every check reads only the trace and the schema documented in
``replayspect.sut.lift``.

Each violation is reported at the earliest event that proves it. A
violation that can only be known at the end of the run (a command never
closed) gets ``seq = len(trace)``. Contract-driven checkers are compared
with this oracle on the first violation per (run, contract), see
:func:`first_violations`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from replayspect.trace import Trace

MOVES = ("MOVE_UP", "MOVE_DOWN")
TERMINAL = ("DONE", "ERROR")
DONE_WITHIN_US = 15_000_000
TRANSITIONS = {
    (None, "init", "DOWN"),
    ("DOWN", "MOVE_UP", "MOVING_UP"),
    ("MOVING_UP", "arrived", "UP"),
    ("UP", "MOVE_DOWN", "MOVING_DOWN"),
    ("MOVING_DOWN", "arrived", "DOWN"),
}

CONTRACTS = {
    "C1": "motor starts at most once per req_id",
    "C2": "the client closes each move command exactly once, within 15 s of first sending it",
    "C3": "device state changes only along declared transitions, starting from the previous state",
    "C4": "the client completes a command only with a DONE carrying that command's req_id",
    "C5": "STATUS_REPLY reports the device's current state",
    "C6": "the client has at most one move command open at a time",
    "C7": "the device sends no more DONE/ERROR for a req_id than it has received requests with that req_id",
    "C8": "the device never sends both DONE and ERROR for the same req_id",
}


@dataclass(frozen=True)
class Violation:
    contract: str
    req_id: str | None
    seq: int
    detail: str


def check(trace: Trace, end_us: int) -> list[Violation]:
    out: list[Violation] = []
    motor = Counter()
    first_send: dict[str, int] = {}
    closes: dict[str, list] = defaultdict(list)
    device_state = None
    open_cmds: set[str] = set()
    terminal_sent: dict[str, set] = defaultdict(set)
    received = Counter()
    answered = Counter()

    for e in trace:
        r = e.req_id
        if e.actor == "device" and e.kind == "effect" and e.name == "motor_start":
            motor[r] += 1
            if motor[r] == 2:
                out.append(Violation("C1", r, e.seq, "second motor_start"))

        elif e.actor == "device" and e.kind == "state":
            if (e.data.get("from"), e.data.get("on"), e.name) not in TRANSITIONS:
                out.append(Violation("C3", r, e.seq, f"{e.data.get('from')} --{e.data.get('on')}--> {e.name}"))
            elif e.data.get("from") != device_state:
                out.append(Violation("C3", r, e.seq, f"from {e.data.get('from')} but state was {device_state}"))
            device_state = e.name

        elif e.actor == "client" and e.kind == "send" and e.name in MOVES:
            first_send.setdefault(r, e.t_us)
            others = sorted(open_cmds - {r})
            if others:
                out.append(Violation("C6", r, e.seq, f"opened while {others} open"))
            open_cmds.add(r)  # every send (re)opens, even a closed command

        elif e.actor == "client" and e.kind == "handle" and e.name in TERMINAL:
            if r in first_send:
                closes[r].append(e)
                t0 = first_send[r]
                if len(closes[r]) == 2:
                    out.append(Violation("C2", r, e.seq, "closed twice"))
                elif len(closes[r]) == 1 and e.t_us - t0 > DONE_WITHIN_US:
                    out.append(Violation("C2", r, e.seq, "closed after 15 s"))
            open_cmds.discard(r)
            if e.name == "DONE" and e.data.get("msg_req_id") != r:
                out.append(Violation("C4", r, e.seq, f"completed by DONE of {e.data.get('msg_req_id')}"))

        elif e.actor == "device" and e.kind == "send" and e.name == "STATUS_REPLY":
            if e.data.get("state") != device_state:
                out.append(Violation("C5", r, e.seq, f"reported {e.data.get('state')}, actual {device_state}"))

        elif e.actor == "device" and e.kind == "recv" and e.name in MOVES:
            received[r] += 1

        elif e.actor == "device" and e.kind == "send" and e.name in TERMINAL:
            answered[r] += 1
            if answered[r] > received[r]:
                out.append(Violation("C7", r, e.seq, f"{e.name} #{answered[r]} for {received[r]} request(s)"))
            before = set(terminal_sent[r])
            terminal_sent[r].add(e.name)
            if len(terminal_sent[r]) == 2 and len(before) == 1:
                out.append(Violation("C8", r, e.seq, "both DONE and ERROR sent"))

    for r, t0 in first_send.items():
        if not closes.get(r) and end_us - t0 > DONE_WITHIN_US:
            out.append(Violation("C2", r, len(trace), "never closed"))
    return out


def first_violations(trace: Trace, end_us: int) -> dict[str, int]:
    """Map each violated contract to the seq of its earliest violation."""
    first: dict[str, int] = {}
    for v in check(trace, end_us):
        first[v.contract] = min(v.seq, first.get(v.contract, v.seq))
    return first


def violated(trace: Trace, end_us: int) -> set[str]:
    return {v.contract for v in check(trace, end_us)}
