"""Checkers built from contracts, and the judge that runs them over a trace.

Each contract kind has one checker class. A checker sees every event once,
in trace order, and reports each violation at the **earliest event that
proves it**. A violation that can only be known when the run is over (a
command that was never closed) is reported at ``seq = len(trace)``.

The end of the run is passed in explicitly as ``end_us``, the time the
simulation was run until. It is not taken from the last event: a run can
end long after its last event, and deadline checks must not depend on
whether something happened to be logged near the end.

Checkers are compared with the reference oracle on the **first violation
per (run, contract)**. How a checker reports later violations of the same
contract is its own choice and is not part of the specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from replayspect.contract.spec import Contract, ContractSet, EventPattern
from replayspect.trace import Event, Trace


@dataclass(frozen=True)
class Violation:
    contract: str
    req_id: str | None
    seq: int
    detail: str


class Checker:
    def __init__(self, contract: Contract) -> None:
        self.contract = contract
        self.p = contract.params

    def v(self, req_id: str | None, seq: int, detail: str) -> Violation:
        return Violation(self.contract.id, req_id, seq, detail)

    def on_event(self, ev: Event, last: dict[EventPattern, Event]) -> list[Violation]:
        return []

    def on_end(self, end_us: int, end_seq: int) -> list[Violation]:
        return []

    def last_patterns(self) -> set[EventPattern]:
        return set()


class AtMostOnce(Checker):
    """``event`` happens at most once per key; reported at the second one."""

    def __init__(self, contract: Contract) -> None:
        super().__init__(contract)
        self.count: dict[str | None, int] = {}

    def on_event(self, ev, last):
        if not self.p["event"].matches(ev):
            return []
        n = self.count[ev.req_id] = self.count.get(ev.req_id, 0) + 1
        return [self.v(ev.req_id, ev.seq, f"{ev.name} #{n}")] if n == 2 else []


class ExactlyOnce(Checker):
    """For every key that ``start`` has begun, ``event`` happens exactly once,
    no later than ``within`` after the **first** ``start`` of that key.

    Events for keys that never started are ignored. Reported: a late first
    occurrence at that event, a second occurrence at that event, and a key
    with no occurrence past its deadline at the end of the run.
    """

    def __init__(self, contract: Contract) -> None:
        super().__init__(contract)
        self.started: dict[str | None, int] = {}
        self.count: dict[str | None, int] = {}

    def on_event(self, ev, last):
        out = []
        if self.p["start"].matches(ev):
            self.started.setdefault(ev.req_id, ev.t_us)
        if self.p["event"].matches(ev) and ev.req_id in self.started:
            n = self.count[ev.req_id] = self.count.get(ev.req_id, 0) + 1
            if n == 2:
                out.append(self.v(ev.req_id, ev.seq, f"{ev.name} twice"))
            elif n == 1 and ev.t_us - self.started[ev.req_id] > self.p["within_us"]:
                out.append(self.v(ev.req_id, ev.seq, f"{ev.name} after the deadline"))
        return out

    def on_end(self, end_us, end_seq):
        return [
            self.v(k, end_seq, "never happened")
            for k, t0 in self.started.items()
            if not self.count.get(k) and end_us - t0 > self.p["within_us"]
        ]


class StateMachine(Checker):
    """``event`` (a state event: name = new state, data.from, data.on) must be a
    declared transition and must start from the previous state's name."""

    def __init__(self, contract: Contract, transitions) -> None:
        super().__init__(contract)
        self.transitions = transitions
        self.state: str | None = None

    def on_event(self, ev, last):
        if not self.p["event"].matches(ev):
            return []
        frm, on = ev.data.get("from"), ev.data.get("on")
        out = []
        if (frm, on, ev.name) not in self.transitions:
            out.append(self.v(ev.req_id, ev.seq, f"{frm} --{on}--> {ev.name} is not declared"))
        elif frm != self.state:
            out.append(self.v(ev.req_id, ev.seq, f"from {frm} but the state was {self.state}"))
        self.state = ev.name
        return out


class Forbid(Checker):
    """No ``event`` for which ``when`` holds."""

    def on_event(self, ev, last):
        if self.p["event"].matches(ev) and self.p["when"].holds(ev, last):
            return [self.v(ev.req_id, ev.seq, f"{ev.name} where {self.contract.params['when']}")]
        return []

    def last_patterns(self):
        return self.p["when"].last_patterns()


class Consistent(Checker):
    """For every ``event``, ``field`` equals ``equals``."""

    def on_event(self, ev, last):
        if not self.p["event"].matches(ev):
            return []
        a = self.p["field"].evaluate(ev, last)
        b = self.p["equals"].evaluate(ev, last)
        return [] if a == b else [self.v(ev.req_id, ev.seq, f"{a!r} != {b!r}")]

    def last_patterns(self):
        return {o.pattern for o in (self.p["field"], self.p["equals"]) if o.pattern is not None}


class AtMostOneOpen(Checker):
    """Keys are opened by **every** ``opens`` event (a closed key reopens) and
    closed by ``closes``. An ``opens`` event for one key while any other key is
    open is a violation."""

    def __init__(self, contract: Contract) -> None:
        super().__init__(contract)
        self.open: set[str | None] = set()

    def on_event(self, ev, last):
        out = []
        if self.p["closes"].matches(ev):
            self.open.discard(ev.req_id)
        if self.p["opens"].matches(ev):
            others = self.open - {ev.req_id}
            if others:
                out.append(self.v(ev.req_id, ev.seq, f"opened while {sorted(map(str, others))} open"))
            self.open.add(ev.req_id)
        return out


class CountLe(Checker):
    """At every ``event``, its running count for the key is at most the running
    count of ``bound`` for the same key."""

    def __init__(self, contract: Contract) -> None:
        super().__init__(contract)
        self.bound: dict[str | None, int] = {}
        self.count: dict[str | None, int] = {}

    def on_event(self, ev, last):
        if self.p["bound"].matches(ev):
            self.bound[ev.req_id] = self.bound.get(ev.req_id, 0) + 1
        if self.p["event"].matches(ev):
            n = self.count[ev.req_id] = self.count.get(ev.req_id, 0) + 1
            b = self.bound.get(ev.req_id, 0)
            if n > b:
                return [self.v(ev.req_id, ev.seq, f"{ev.name} #{n} with only {b}")]
        return []


class MutuallyExclusive(Checker):
    """Per key, at most one of the listed ``events`` patterns ever matches;
    reported once, at the event where a second pattern first matches."""

    def __init__(self, contract: Contract) -> None:
        super().__init__(contract)
        self.seen: dict[str | None, set[int]] = {}

    def on_event(self, ev, last):
        for i, pat in enumerate(self.p["events"]):
            if pat.matches(ev):
                s = self.seen.setdefault(ev.req_id, set())
                before = len(s)
                s.add(i)
                if before == 1 and len(s) == 2:
                    return [self.v(ev.req_id, ev.seq, "both " + " and ".join(str(p) for p in self.p["events"]))]
        return []


def build_checkers(cs: ContractSet) -> list[Checker]:
    out: list[Checker] = []
    for c in cs.contracts:
        if c.kind == "state_machine":
            out.append(StateMachine(c, cs.transitions))
        else:
            out.append({
                "at_most_once": AtMostOnce,
                "exactly_once": ExactlyOnce,
                "forbid": Forbid,
                "consistent": Consistent,
                "at_most_one_open": AtMostOneOpen,
                "count_le": CountLe,
                "mutually_exclusive": MutuallyExclusive,
            }[c.kind](c))
    return out


def judge(trace: Trace | Iterable[Event], contracts: ContractSet, end_us: int) -> list[Violation]:
    """Run every contract over ``trace`` and return all violations, in report order.

    ``end_us`` is the time the run was simulated until. It must not be earlier
    than the last event; a smaller value usually means a unit mistake, which
    would silently flip deadline checks.
    """
    events = list(trace)
    if events and end_us < events[-1].t_us:
        raise ValueError(f"end_us={end_us} is before the last event at {events[-1].t_us}us")
    checkers = build_checkers(contracts)
    watched: set[EventPattern] = set().union(*(c.last_patterns() for c in checkers)) if checkers else set()
    last: dict[EventPattern, Event] = {}
    out: list[Violation] = []
    for ev in events:
        for c in checkers:
            out.extend(c.on_event(ev, last))
        for pat in watched:
            if pat.matches(ev):
                last[pat] = ev
    for c in checkers:
        out.extend(c.on_end(end_us, len(events)))
    return out


def first_violations(violations: Iterable[Violation]) -> dict[str, int]:
    """Map each violated contract to the seq of its earliest violation."""
    first: dict[str, int] = {}
    for v in violations:
        first[v.contract] = min(v.seq, first.get(v.contract, v.seq))
    return first


def first_violation_details(violations: Iterable[Violation]) -> list[Violation]:
    """The earliest violation of each contract, sorted by ``(seq, req_id, contract)``.

    Several keys can fail at the same seq (for example at the end of the run);
    the smallest ``req_id`` wins (``None`` sorts first), so the choice is stable.
    """
    best: dict[str, Violation] = {}
    for v in violations:
        cur = best.get(v.contract)
        if cur is None or _order(v) < _order(cur):
            best[v.contract] = v
    return sorted(best.values(), key=lambda v: (*_order(v), v.contract))


def _order(v: Violation) -> tuple[int, str]:
    return (v.seq, "" if v.req_id is None else v.req_id)


def matched_patterns(trace: Trace | Iterable[Event], contracts: ContractSet) -> set[EventPattern]:
    """Every pattern used by ``contracts`` that matches at least one event of ``trace``.

    A contract whose patterns never match anything cannot fail, so "no
    violations" over a batch of runs means little until every pattern has
    matched at least once. Compare against :func:`contract_patterns`.
    """
    pats = contract_patterns(contracts)
    hit: set[EventPattern] = set()
    for ev in trace:
        for p in pats - hit:
            if p.matches(ev):
                hit.add(p)
    return hit


def contract_patterns(contracts: ContractSet) -> set[EventPattern]:
    """Every event pattern the contracts refer to, including inside ``last(...)``."""
    pats: set[EventPattern] = set()
    for c in contracts.contracts:
        for key in ("event", "start", "opens", "closes", "bound"):
            if key in c.params:
                pats.add(c.params[key])
        pats.update(c.params.get("events", ()))
        if "when" in c.params:
            pats |= c.params["when"].last_patterns()
        for key in ("field", "equals"):
            if key in c.params and c.params[key].pattern is not None:
                pats.add(c.params[key].pattern)
    return pats
