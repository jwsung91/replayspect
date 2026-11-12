"""Fit a client-side log with the fewest faults (WP5b fit, minimal explanations).

Driven replay (:mod:`replayspect.driven`) scripts the client, so the client never reacts to a
reply. The delay of a reply (s2c) changes nothing on the device: it only sets when the client
receives it. What the device does depends only on when requests arrive (c2s) and on the
disconnects. So for a given **arrival choice** (when each request attempt reaches the device, or
that it is lost, plus an optional duplicate) one run gives every device send, and the replies
follow by arithmetic:

1. **First run.** Requests arrive as chosen; the device runs.
2. **Reply pairing.** For each reply name and request id, the device's sends are paired with the
   logged receives by a **minimum-fault assignment**: a receive is the first copy of a send or a
   duplicate of one already received; order may change (each message has its own delay); a send
   with no receive was lost. Every assignment that ties for the fewest faults is kept. A logged
   receive no device send can explain is **unexplained**: the link can lose and duplicate what the
   device sent, not invent it.
3. **Check run.** Each plan (arrivals, reply delays, drops, duplicates, the logged disconnects)
   is run and judged as driven replay judges (:func:`replayspect.driven.driven_match`).

**Faults.** A drop, a duplicate, or a delay above the usual delay plus the tolerance
(:class:`Usual`), in either direction. Not faults: a message lost in a logged disconnect when the
delay it needs is within that limit, and a reply still in flight at the end of the log. A fault is
identified by kind and ``(dir, msg, req_id, k)``; its value (delay, extra delay) is not part of the
identity. Two explanations with the same faults are the same explanation, and the values they differ
in (another reply pairing, another arrival point) are reported as the range seen, lowest to highest,
each end found on the whole log. It is the range of the values in the explanations found, not every
value that would fit: values between and beyond the option points are not tried. The range is per
fault: the ends of two faults need not go together.

**Disconnects are facts** when the client logged them (``DISCONNECTED`` / ``CONNECTED`` state
events). A request sent just before a logged disconnect, still in flight when it began, is lost
with it (the link drops what is in flight), which is not a fault.

**The default arrival.** Each attempt arrives at the time closest to ``send + usual`` at which its
delay and the delays of the replies it caused are all within the limit; if there is no such time,
at ``send + usual``. The ranges stay wide; the default is the usual value, not the middle of the
range.

**Search.** The search units are the anomalous commands (the rule of :func:`anomaly_windows`:
retry, error, error reply, the same reply twice, late ``ACK``, late ``DONE``), plus any command
with a receive the default leaves unexplained, plus any poll with a fault in the default (a poll
does not change the device, so its lost request and lost reply tie and both are reported). Attempts
of other commands and polls keep the default. In each unit, in time order, each attempt has these
options: the default; dropped; arriving at its minimum delay, just after a device event, at an
*anchored* time (where a logged reply of its request would have the usual delay), at the time
nearest the usual delay where both its delay and a logged reply's delay are within the limit
(whichever send that reply is paired with), or just after a logged disconnect begins; duplicated,
with the copy anchored the same way. Choices are run in order of how many attempts leave the
default. A choice whose request-side faults alone exceed the fewest faults found so far is skipped
(the reply side can only add faults), so when the unit's choices are exhausted every explanation
with the fewest faults in that option space has been run. With ``plus_one`` the search keeps going
to one fault more, as a diagnostic, and every command outside the units with no fault is then
searched for one fault more on the whole log (:func:`_one_more`). Each unit is judged on the log up
to just after the command, from its first send, with the earlier units fixed at their first minimal
explanation. The units' sets are then combined and the combinations are run on the whole log (all
of them when there are at most :data:`COMBINATIONS_RUN`, otherwise the first); if one fails, the
units are searched together.

**Report.** The fewest faults ``f*``, the number of explanations, the faults common to every minimal
explanation (common, not shown to be true: see below) and, per request id, the alternatives where
the minimal explanations differ. Apart from the fit, the
**observed slow round trips**: request-to-``ACK`` gaps longer than the log's median by more than
the limit, computed from the log alone (:func:`slow_round_trips`).

**What "minimal" does not mean.** The fewest faults is a choice, not the truth: a log whose real
faults are not the fewest is always misread. "Every minimal explanation" holds within the option
points above, not over every real-valued timing; :func:`random_arrivals` checks it with draws off
those points, which is not a proof. A duplicate copy is placed only at anchored times, on the
reasoning that a copy matters through the reply it causes; a device whose copies change state would
need more points.

**What "explained by loss" does not mean.** A device that fails to send a reply looks exactly like
a reply lost on the link. A log explained with drops is not shown to be free of defects.

**Branch points** (``branches``): for a fitted log, each command attempt's arrival is moved to just
after each device event in the interval the log allows; if a move stops the fit reproducing, the
attempt has a branch point (the device's behaviour depends on an arrival time the log does not fix).
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field, replace
from itertools import combinations, product
from typing import Any, Callable, Iterator, Sequence

from replayspect.contract import judge
from replayspect.driven import DrivenMatch, DrivenSetup, driven_match, run_driven
from replayspect.sim.link import DROP_DISCONNECTED, FaultPlan
from replayspect.trace import Event, Trace

#: Client state names that mark the client's view of the connection.
DOWN, UP = "DISCONNECTED", "CONNECTED"
#: Default cap on runs for the fit (all units together) and, separately, for the branch-point check.
FIT_RUNS = 2000
BRANCH_RUNS = 120
#: Reply keys with more sends or receives than this are paired in order (flagged), not by search.
PAIR_MAX = 6
#: Tied reply pairings kept per arrival choice (each costs a check run).
PAIRINGS_MAX = 8
#: The units' explanation sets are all run on the whole log when there are at most this many combinations.
COMBINATIONS_RUN = 50
#: Runs the runner keeps whole (the most recent). Every run's result stays cached, but its trace and its
#: plans are dropped after this many newer runs and rebuilt (the run is deterministic; not counted
#: again) if asked for: keeping them all made memory grow with the run count, to several GB near the cap.
TRACES_KEPT = 32
#: Other arrival choices kept per explanation that give the same faults with other values; each is run
#: on the whole log to widen the value ranges (:attr:`Explanation.spans`).
SPAN_CHOICES = 4

Fault = tuple  # (kind, dir, msg, req_id, k)
Span = tuple  # (lowest, highest) value in microseconds; None for a drop


def _widen(spans: dict[Fault, Span], fd: dict[Fault, int | None]) -> None:
    for k, v in fd.items():
        if v is not None:
            lo, hi = spans.get(k, (v, v))
            spans[k] = (min(lo, v), max(hi, v))


def _union(spans) -> Span | None:
    got = [x for x in spans if x is not None]
    return (min(x[0] for x in got), max(x[1] for x in got)) if got else None


@dataclass(frozen=True)
class Ranges:
    """Delay ranges the fit may use. Defaults are the simulator profile's; a real link can be faster."""

    c2s: tuple[int, int]
    s2c: tuple[int, int]
    dup_extra: tuple[int, int]

    @classmethod
    def of(cls, setup: DrivenSetup) -> "Ranges":
        p = setup.system.profile
        return cls(tuple(p.c2s.delay_us), tuple(p.s2c.delay_us), tuple(p.s2c.dup_extra_us))


@dataclass(frozen=True)
class Usual:
    """The usual delay per direction (the default arrival) and the limit above which a delay is a fault.

    :meth:`given` (``--usual-delay``): the limit is the usual delay plus the tolerance. :meth:`of`
    (no usual delay given, e.g. simulator logs): the usual delay is the range's low end and the limit
    its high end, so no delay inside the range is a fault (only drops and duplicates are).
    """

    c2s: int
    s2c: int
    c2s_limit: int
    s2c_limit: int

    @classmethod
    def of(cls, ranges: Ranges) -> "Usual":
        return cls(ranges.c2s[0], ranges.s2c[0], ranges.c2s[1], ranges.s2c[1])

    @classmethod
    def given(cls, c2s: int, s2c: int, tolerance_us: int) -> "Usual":
        return cls(c2s, s2c, c2s + tolerance_us, s2c + tolerance_us)


@dataclass(frozen=True)
class Attempt:
    key: tuple[str, str | None, int]  # (msg, req_id, k)
    t_us: int  # sent

    @property
    def req_id(self) -> str | None:
        return self.key[1]

    def plan_key(self) -> dict[str, Any]:
        return {"dir": "c2s", "msg": self.key[0], "req_id": self.key[1], "k": self.key[2]}


@dataclass(frozen=True)
class Choice:
    """How each request attempt reaches the device: delay, None (dropped), plus an optional duplicate."""

    delays: tuple[tuple[tuple[str, str | None, int], int | None], ...]
    dups: tuple[tuple[tuple[str, str | None, int], int], ...] = ()

    def delay(self, key) -> int | None:
        return dict(self.delays)[key]

    def with_delay(self, key, d: int | None) -> "Choice":
        return Choice(tuple((k, d if k == key else v) for k, v in self.delays), self.dups)

    def with_dup(self, key, extra: int) -> "Choice":
        return Choice(self.delays, tuple(sorted({**dict(self.dups), key: extra}.items(), key=lambda kv: str(kv[0]))))

    def assign(self, items: dict[tuple, tuple[int | None, int | None]]) -> "Choice":
        """Set ``key -> (delay, dup extra or None)`` for the given attempts."""
        d = dict(self.delays)
        dups = dict(self.dups)
        for k, (delay, extra) in items.items():
            d[k] = delay
            dups.pop(k, None)
            if delay is not None and extra is not None:
                dups[k] = extra
        return Choice(tuple((k, d[k]) for k, _ in self.delays), tuple(sorted(dups.items(), key=lambda kv: str(kv[0]))))

    def of(self, keys) -> dict[tuple, tuple[int | None, int | None]]:
        d, dups = dict(self.delays), dict(self.dups)
        return {k: (d[k], dups.get(k)) for k in keys}


@dataclass
class Fit:
    """One arrival choice, its reply pairing (the first of the tied ones) and, after the check run, the match."""

    plan: dict[str, Any]
    unexplained: list[Event]  # logged receives no device send explains (polls included)
    drops: int  # link losses: request attempts and replies
    dups: int
    in_flight: int  # device sends left in flight at the end of the log
    match: DrivenMatch | None = None
    violated: set[str] | None = None
    lost_to_disconnect: int = 0  # messages in flight when a logged disconnect began (not faults)
    delays: int = 0  # delays above the limit (faults)
    faults: dict[Fault, int | None] = field(default_factory=dict)  # identity -> value (us) or None for a drop
    #: every tied pairing: (plan, faults); the first is ``plan``/``faults``
    alternatives: list[tuple[dict[str, Any], dict[Fault, int | None]]] = field(default_factory=list)
    pairings_cut: bool = False  # more tied pairings than PAIRINGS_MAX
    paired_in_order: int = 0  # reply keys too large to search, paired in order

    def score(self, setup: DrivenSetup) -> tuple:
        quiet = setup.system.quiet_messages
        judged = [e for e in self.unexplained if e.t_us >= setup.judge_from_us]
        unexpl = sum(1 for e in judged if e.name not in quiet)
        polls = len(judged) - unexpl
        lines_bad = 0 if (self.match is not None and self.match.max_dt_us is not None
                          and self.match.max_dt_us <= setup.tolerance_us) else 1
        contracts_bad = 1 if (self.match is not None and self.match.contracts_same is False) else 0
        return (unexpl, lines_bad, contracts_bad, polls, len(self.faults))


@dataclass
class Explanation:
    faults: dict[Fault, int | None]  # the unit's faults (identity -> first value found)
    choice: dict[tuple, tuple[int | None, int | None]]  # the unit's attempts: key -> (delay, dup extra)
    violated: tuple[str, ...] = ()
    #: per fault with a value, the lowest and highest value among the merged explanations (same faults,
    #: another reply pairing or arrival point), each found on the whole log: what the log leaves open
    spans: dict[Fault, Span] = field(default_factory=dict)
    #: other arrival choices with the same faults (at most SPAN_CHOICES), run on the whole log for spans
    others: list[dict[tuple, tuple[int | None, int | None]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        _widen(self.spans, self.faults)

    def merge(self, fd: dict[Fault, int | None], choice: dict | None = None) -> None:
        """Fold in an explanation with the same faults: widen the spans, keep its choice if new."""
        _widen(self.spans, fd)
        if choice is not None and choice != self.choice and choice not in self.others \
                and len(self.others) < SPAN_CHOICES:
            self.others.append(choice)

    def shown(self) -> dict[Fault, Span | None]:
        return {k: self.spans.get(k) for k in self.faults}


@dataclass
class UnitSet:
    """The minimal explanations of one search unit (a command, or several searched together)."""

    req_ids: tuple[str, ...]
    attempts: tuple[tuple, ...]
    f: int | None  # fewest faults of the unit's request ids; None when nothing reproduced
    explanations: list[Explanation] = field(default_factory=list)
    plus_one: list[Explanation] = field(default_factory=list)
    minimal_shown: bool = False
    plus_one_shown: bool = False
    exhausted: bool = False  # every choice of the unit was run
    choices_run: int = 0
    why: tuple[str, ...] = ()


@dataclass
class FitResult:
    #: reproduced; unexplained: every choice of some unit was run and a receive stays unexplained
    #: (evidence about the device); incomplete: nothing reproduced within the cap
    #: (``incomplete_reason``: cap), a limit of the fitter, not evidence.
    status: str
    runs: int
    fit: Fit
    moves: list[str] = field(default_factory=list)  # kept for callers; the minimal search makes no moves
    receives: int = 0  # logged receives, polls left out
    matched: int = 0  # of them matched in the check run
    disconnects_from_log: int = 0
    quiet: frozenset[str] = frozenset()
    branch_attempts: int | None = None  # command attempts with a branch point
    branch_checked: int | None = None
    branch_runs: int = 0
    branch_capped: bool = False
    incomplete_reason: str | None = None
    space: int | None = None
    #: violated-contract sets of the explanations that matched every receive, with how many choices gave each
    outcomes: dict[tuple[str, ...], int] = field(default_factory=dict)
    expect_given: bool = False
    window: tuple[int, int] | None = None
    usual: Usual | None = None
    min_faults: int | None = None  # f*
    units: list[UnitSet] = field(default_factory=list)
    outside: list[dict[Fault, int | None]] = field(default_factory=list)  # tied pairings of faults outside the units
    outside_spans: list[dict[Fault, Span]] = field(default_factory=list)  # value ranges of ``outside``, same order
    plus_one: bool = False  # the f*+1 level was asked for
    combinations: tuple[int, int] = (0, 0)  # (run on the whole log and reproduced, total)
    joint: bool = False  # the units were searched together after a combination failed
    slow: list[dict[str, Any]] = field(default_factory=list)  # observed slow round trips (from the log)
    #: commands outside the units searched for one fault more (``plus_one``); each has the empty explanation
    more: list[UnitSet] = field(default_factory=list)
    choice: Choice | None = None  # the arrival choice of the reported plan (the first explanation)
    random_check: dict[str, Any] | None = None  # :func:`random_arrivals`, when run
    models: dict[str, Any] | None = None  # :func:`judge_models`, when other device models were fitted

    @property
    def reproduced(self) -> bool:
        return self.status == "reproduced"

    @property
    def ambiguous(self) -> bool:
        """More than one violation outcome fits every receive (only meaningful without --expect)."""
        return not self.expect_given and len(self.outcomes) > 1

    @property
    def minimal_shown(self) -> bool:
        return self.reproduced and all(u.minimal_shown for u in self.units) and self.combinations[0] == self.combinations[1]

    @property
    def plus_one_shown(self) -> bool:
        return (self.plus_one and self.minimal_shown and all(u.plus_one_shown for u in self.units)
                and all(u.plus_one_shown for u in self.more))

    @property
    def n_explanations(self) -> int:
        if not self.reproduced:
            return 0
        n = max(1, len(self.outside))
        for u in self.units:
            n *= max(1, len(u.explanations))
        return n

    @property
    def n_plus_one(self) -> int:
        if not self.reproduced:
            return 0
        total = 0
        for i, u in enumerate(self.units):
            n = len(u.plus_one) * max(1, len(self.outside))
            for j, v in enumerate(self.units):
                if j != i:
                    n *= max(1, len(v.explanations))
            total += n
        rest = max(1, len(self.outside))
        for v in self.units:
            rest *= max(1, len(v.explanations))
        return total + sum(len(u.plus_one) for u in self.more) * rest

    def _outside_shown(self) -> list[dict[Fault, Span | None]]:
        spans = self.outside_spans or [{} for _ in self.outside]
        return [{k: sp.get(k) for k in o} for o, sp in zip(self.outside, spans)]

    def common(self) -> dict[Fault, Span | None]:
        """Faults in every minimal explanation, each with its value range over all of them (None: a drop).
        Common to the minimal explanations, not shown to be true: a log whose real faults are not the
        fewest is misread here too."""
        out: dict[Fault, Span | None] = {}
        if not self.reproduced:
            return out
        sets = [[x.shown() for x in u.explanations] for u in self.units if u.explanations]
        if self.outside:
            sets.append(self._outside_shown())
        for xs in sets:
            same = set(xs[0])
            for x in xs[1:]:
                same &= set(x)
            for k in same:
                out[k] = _union(x[k] for x in xs)
        return out

    def alternatives(self) -> list[tuple[str, list[dict[Fault, Span | None]]]]:
        """Per request id (or unit), the minimal explanations' faults minus the common ones, with ranges."""
        groups: list[tuple[str, list[dict[Fault, Span | None]]]] = []
        if not self.reproduced:
            return groups
        for u in self.units:
            if len(u.explanations) > 1:
                same = set(u.explanations[0].faults)
                for x in u.explanations[1:]:
                    same &= set(x.faults)
                groups.append((", ".join(u.req_ids), [{k: v for k, v in x.shown().items() if k not in same}
                                                      for x in u.explanations]))
        if len(self.outside) > 1:
            outs = self._outside_shown()
            same = set(outs[0])
            for x in outs[1:]:
                same &= set(x)
            by: dict[str, list[dict]] = {}
            for x in outs:
                for rid in sorted({k[3] or "-" for k in x if k not in same}):
                    alt = {k: v for k, v in x.items() if k not in same and (k[3] or "-") == rid}
                    got = by.setdefault(rid, [])
                    old = next((g for g in got if g.keys() == alt.keys()), None)
                    if old is None:
                        got.append(alt)
                    else:
                        for k in old:
                            old[k] = _union([old[k], alt[k]])
            groups += [(rid, alts) for rid, alts in by.items() if len(alts) > 1]
        return groups

    def to_dict(self) -> dict[str, Any]:
        def fl(fs):
            return [{"kind": k[0], "dir": k[1], "msg": k[2], "req_id": k[3], "k": k[4],
                     "seen_range_us": None if v is None else list(v)}
                    for k, v in sorted(fs.items(), key=lambda kv: str(kv[0]))]

        return {
            "status": self.status, "incomplete_reason": self.incomplete_reason, "runs": self.runs,
            "min_faults": self.min_faults, "explanations": self.n_explanations,
            "minimal_shown": self.minimal_shown, "plus_one": self.plus_one, "plus_one_explanations": self.n_plus_one,
            "plus_one_shown": self.plus_one_shown, "combinations": list(self.combinations), "joint": self.joint,
            "usual": None if self.usual is None else vars(self.usual),
            "common": fl(self.common()),
            "alternatives": [{"group": g, "alternatives": [fl(a) for a in alts]} for g, alts in self.alternatives()],
            "units": [{"req_ids": list(u.req_ids), "why": list(u.why), "f": u.f, "minimal_shown": u.minimal_shown,
                       "plus_one_shown": u.plus_one_shown, "exhausted": u.exhausted, "choices_run": u.choices_run,
                       "explanations": [fl(x.shown()) for x in u.explanations],
                       "plus_one": [fl(x.shown()) for x in u.plus_one]} for u in self.units],
            "plus_one_outside_units": [{"req_ids": list(u.req_ids), "plus_one_shown": u.plus_one_shown,
                                        "choices_run": u.choices_run, "plus_one": [fl(x.shown()) for x in u.plus_one]}
                                       for u in self.more],
            "outside": [fl(x) for x in self._outside_shown()],
            "slow_round_trips": self.slow,
            "random_check": self.random_check,
            "models": self.models,
            "unexplained": [{"name": e.name, "req_id": e.req_id, "t_us": e.t_us} for e in self.fit.unexplained
                            if e.name not in self.quiet],
            "plan": self.fit.plan,
        }


# -- reading the log ------------------------------------------------------------------------


def attempts_of(log: Sequence[Event], actor: str) -> list[Attempt]:
    seen: dict[tuple, int] = {}
    out = []
    for e in log:
        if e.actor == actor and e.kind == "send":
            k = seen.get((e.name, e.req_id), 0)
            seen[(e.name, e.req_id)] = k + 1
            out.append(Attempt((e.name, e.req_id, k), e.t_us))
    return out


def logged_disconnects(log: Sequence[Event], actor: str, until_us: int) -> list[dict[str, int]]:
    """Disconnects from the client's DISCONNECTED/CONNECTED state events (an open one lasts to the end)."""
    out, down = [], None
    for e in log:
        if e.actor != actor or e.kind != "state":
            continue
        if e.name == DOWN and down is None:
            down = e.t_us
        elif e.name == UP and down is not None:
            if e.t_us > down:
                out.append({"t_us": down, "duration_us": e.t_us - down})
            down = None
    if down is not None and until_us > down:
        out.append({"t_us": down, "duration_us": until_us - down})
    return out


def slow_round_trips(log: Sequence[Event], actor: str, quiet: frozenset[str], limit_us: int,
                     reply: str = "ACK") -> list[dict[str, Any]]:
    """Observed slow round trips, from the log alone (not the fit).

    For each request attempt (polls left out), the gap from its send to the first ``reply`` of the
    same id received before the next attempt. A gap longer than the log's median gap by more than
    ``limit_us`` is listed with the request id, the attempt and the excess.
    """
    by: dict[str, list[Event]] = {}
    for e in log:
        if e.actor == actor and e.req_id is not None and e.name not in quiet and e.kind in ("send", "recv"):
            by.setdefault(e.req_id, []).append(e)
    gaps = []
    for rid, es in by.items():
        sends = [e for e in es if e.kind == "send"]
        acks = [e for e in es if e.kind == "recv" and e.name == reply]
        for i, s in enumerate(sends):
            nxt = sends[i + 1].t_us if i + 1 < len(sends) else None
            a = next((a for a in acks if a.t_us >= s.t_us and (nxt is None or a.t_us < nxt)), None)
            if a is not None:
                gaps.append((rid, s.name, i, a.t_us - s.t_us))
    if not gaps:
        return []
    g = sorted(x[3] for x in gaps)
    median = g[len(g) // 2] if len(g) % 2 else (g[len(g) // 2 - 1] + g[len(g) // 2]) // 2
    return [{"req_id": rid, "msg": msg, "k": k, "gap_us": gap, "median_us": median, "excess_us": gap - median}
            for rid, msg, k, gap in sorted(gaps, key=lambda x: (x[0], x[2])) if gap - median > limit_us]


# -- the two runs ---------------------------------------------------------------------------


def _first_plan(choice: Choice, disconnects: list[dict[str, int]]) -> dict[str, Any]:
    delays, faults = [], []
    for (msg, rid, k), d in choice.delays:
        key = {"dir": "c2s", "msg": msg, "req_id": rid, "k": k}
        if d is None:
            faults.append({**key, "drop": True})
        else:
            delays.append({**key, "delay_us": int(d)})
    for (msg, rid, k), extra in choice.dups:
        if choice.delay((msg, rid, k)) is not None:
            faults.append({"dir": "c2s", "msg": msg, "req_id": rid, "k": k, "dup_extra_us": int(extra)})
    return {"base": "fixed", "delays": delays, "faults": faults, "disconnects": list(disconnects)}


def _choice_faults(choice: Choice, usual: Usual) -> dict[Fault, int | None]:
    out: dict[Fault, int | None] = {}
    dups = dict(choice.dups)
    for (msg, rid, k), d in choice.delays:
        if d is None:
            out[("drop", "c2s", msg, rid, k)] = None
            continue
        if d > usual.c2s_limit:
            out[("delay", "c2s", msg, rid, k)] = int(d)
        if (msg, rid, k) in dups:
            out[("dup", "c2s", msg, rid, k)] = int(dups[(msg, rid, k)])
    return out


def _device_sends(trace: Trace) -> list[tuple[Event, dict]]:
    """The device's s2c sends that reached the link (not dropped for a disconnect at send time)."""
    lost = {(e.data.get("dir"), e.data.get("n")) for e in trace.events
            if e.actor == "link" and e.kind == "fault" and e.name == "drop"
            and e.data.get("reason") == DROP_DISCONNECTED}
    out = []
    for e in trace.events:
        link = e.data.get("link")
        if e.kind == "send" and link is not None and link.get("dir") == "s2c" and (link["dir"], link["n"]) not in lost:
            out.append((e, link))
    return out


def _cut_by_disconnect(t0: int, t1: int, disconnects: list[dict[str, int]]) -> bool:
    return any(t0 < d["t_us"] <= t1 for d in disconnects)


def _unreceived(t: int, ranges: Ranges, limit: int, horizon: int, disconnects: list[dict[str, int]]):
    """What a device send with no logged receive was: ('late', None) arrives after the log at any delay;
    ('in_flight', d) or ('lost', d) at delay d, not a fault; ('drop', None), a fault."""
    lo, hi = ranges.s2c
    if t + lo > horizon:
        return "late", None
    need = max(lo, horizon - t + 1)
    if need <= min(hi, limit):
        return "in_flight", need
    for d in disconnects:
        nd = d["t_us"] - t + 1
        if t < d["t_us"] and lo <= nd <= min(hi, limit):
            return "lost", nd
    return "drop", None


def _pair_key(ss: list[int], rs: list[int], ranges: Ranges, limit: int, horizon: int,
              disconnects: list[dict[str, int]]) -> tuple[tuple[int, int], list[list[tuple]]]:
    """Every minimum-fault assignment of receives ``rs`` to sends ``ss`` (times, sorted).

    An assignment gives each receive ``("f", j)`` (first copy of send j), ``("d", j)`` (a duplicate
    of send j, whose first copy is an earlier receive) or ``("u",)`` (unexplained). The cost is
    (unexplained receives, faults): a first copy later than ``limit``, a duplicate, and an
    unreceived send that is not late, in flight or lost to a disconnect.
    """
    lo, hi = ranges.s2c
    dlo, dhi = ranges.dup_extra
    unrecv_cost = [0 if _unreceived(t, ranges, limit, horizon, disconnects)[0] != "drop" else 1 for t in ss]
    best: list = [None]
    ties: list[list[tuple]] = []
    first_at: list[int | None] = [None] * len(ss)
    dup_used = [False] * len(ss)
    cur: list[tuple] = []

    def rec(i: int, u: int, f: int) -> None:
        if best[0] is not None and (u, f) > best[0]:
            return
        if i == len(rs):
            total = (u, f + sum(c for j, c in enumerate(unrecv_cost) if first_at[j] is None))
            if best[0] is None or total < best[0]:
                best[0] = total
                ties.clear()
            if total == best[0] and len(ties) < PAIRINGS_MAX * 4:
                ties.append(list(cur))
            return
        r = rs[i]
        for j, s in enumerate(ss):
            if first_at[j] is None and lo <= r - s <= hi and not _cut_by_disconnect(s, r, disconnects):
                first_at[j] = r
                cur.append(("f", j))
                rec(i + 1, u, f + (1 if r - s > limit else 0))
                cur.pop()
                first_at[j] = None
        for j, s in enumerate(ss):
            if first_at[j] is not None and not dup_used[j] and dlo <= r - first_at[j] <= dhi \
                    and not _cut_by_disconnect(s, r, disconnects):
                dup_used[j] = True
                cur.append(("d", j))
                rec(i + 1, u, f + 1)
                cur.pop()
                dup_used[j] = False
        cur.append(("u",))
        rec(i + 1, u + 1, f)
        cur.pop()

    rec(0, 0, 0)
    return best[0], ties


def _pair_in_order(ss: list[int], rs: list[int], ranges: Ranges, disconnects: list[dict[str, int]]) -> list[tuple]:
    """The earlier pairing, for keys too large to search: each receive to the earliest send that can explain it."""
    lo, hi = ranges.s2c
    dlo, dhi = ranges.dup_extra
    used: list[int | None] = [None] * len(ss)
    dup_done: set[int] = set()
    out, i = [], 0
    for r in rs:
        j = next((j for j in range(i, len(ss)) if used[j] is None and lo <= r - ss[j] <= hi
                  and not _cut_by_disconnect(ss[j], r, disconnects)), None)
        if j is not None:
            used[j] = r
            i = j + 1
            out.append(("f", j))
            continue
        d = next((j for j in range(i - 1, -1, -1) if used[j] is not None and j not in dup_done
                  and dlo <= r - used[j] <= dhi and not _cut_by_disconnect(ss[j], r, disconnects)), None)
        if d is not None:
            dup_done.add(d)
            out.append(("d", d))
            continue
        out.append(("u",))
    return out


def fit_replies(setup: DrivenSetup, first: Trace, choice: Choice, disconnects: list[dict[str, int]],
                ranges: Ranges, usual: Usual | None = None) -> Fit:
    """Pair the first run's device sends with the logged receives (minimum faults) and build the plans."""
    usual = usual or Usual.of(ranges)
    base = _first_plan(choice, disconnects)
    c2s_faults = _choice_faults(choice, usual)
    horizon = setup.horizon_us
    sends: dict[tuple, list[tuple[Event, dict]]] = {}
    for e, link in _device_sends(first):
        sends.setdefault((e.name, e.req_id), []).append((e, link))
    recvs: dict[tuple, list[Event]] = {}
    for e in setup.log:
        if e.actor == setup.actor and e.kind == "recv":
            recvs.setdefault((e.name, e.req_id), []).append(e)
    per_key: list[list[tuple[list, list, dict, list, dict]]] = []  # options per key: (delays, faults, fdict, unexpl, counts)
    in_order = 0
    for name_rid in sorted(set(sends) | set(recvs), key=str):
        ss, rs = sends.get(name_rid, []), recvs.get(name_rid, [])
        st, rt = [e.t_us for e, _ in ss], [e.t_us for e in rs]
        if len(ss) > PAIR_MAX or len(rs) > PAIR_MAX:
            assignments = [_pair_in_order(st, rt, ranges, disconnects)]
            in_order += 1
        else:
            _, assignments = _pair_key(st, rt, ranges, usual.s2c_limit, horizon, disconnects)
        opts = []
        for asg in assignments:
            delays, faults, fd, unexpl = [], [], {}, []
            counts = {"in_flight": 0, "lost": 0}
            first_at: dict[int, int] = {}
            for r, a in zip(rs, asg):
                if a[0] == "f":
                    first_at[a[1]] = r.t_us
            for r, a in zip(rs, asg):
                if a[0] == "u":
                    unexpl.append(r)
                    continue
                e, link = ss[a[1]]
                key = {"dir": "s2c", "msg": e.name, "req_id": e.req_id, "k": link["k"]}
                if a[0] == "f":
                    d = r.t_us - e.t_us
                    delays.append({**key, "delay_us": int(d)})
                    if d > usual.s2c_limit:
                        fd[("delay", "s2c", e.name, e.req_id, link["k"])] = int(d)
                else:
                    extra = r.t_us - first_at[a[1]]
                    faults.append({**key, "dup_extra_us": int(extra)})
                    fd[("dup", "s2c", e.name, e.req_id, link["k"])] = int(extra)
            for j, (e, link) in enumerate(ss):
                if j in first_at:
                    continue
                key = {"dir": "s2c", "msg": e.name, "req_id": e.req_id, "k": link["k"]}
                what, d = _unreceived(e.t_us, ranges, usual.s2c_limit, horizon, disconnects)
                if what == "late":
                    continue
                if what in ("in_flight", "lost"):
                    delays.append({**key, "delay_us": int(d)})
                    counts[what] += 1
                else:
                    faults.append({**key, "drop": True})
                    fd[("drop", "s2c", e.name, e.req_id, link["k"])] = None
            opts.append((delays, faults, fd, unexpl, counts))
        per_key.append(opts)
    alts = []
    cut = False
    for combo in product(*per_key):
        if len(alts) >= PAIRINGS_MAX:
            cut = True
            break
        plan = {**base, "delays": list(base["delays"]), "faults": list(base["faults"])}
        fd = dict(c2s_faults)
        for delays, faults, f, _, _ in combo:
            plan["delays"] += delays
            plan["faults"] += faults
            fd.update(f)
        alts.append((plan, fd, combo))
    plan, fd, combo = alts[0] if alts else ({**base}, dict(c2s_faults), ())
    unexplained = sorted((e for opt in combo for e in opt[3]), key=lambda e: e.t_us)
    fit = Fit(plan, unexplained, sum(1 for k in fd if k[0] == "drop"), sum(1 for k in fd if k[0] == "dup"),
              sum(opt[4]["in_flight"] for opt in combo), lost_to_disconnect=sum(opt[4]["lost"] for opt in combo),
              delays=sum(1 for k in fd if k[0] == "delay"), faults=fd,
              alternatives=[(p, f) for p, f, _ in alts], pairings_cut=cut, paired_in_order=in_order)
    return fit


@dataclass
class _Eval:
    fit: Fit
    trace: Trace | None  # the first run's trace, None once dropped (see TRACES_KEPT)
    #: per tied pairing: (faults, reproduced, violated)
    results: list[tuple[dict[Fault, int | None], bool, tuple[str, ...]]] = field(default_factory=list)
    #: runs it again: the trace and its fit (for the plans dropped with the trace)
    again: Callable[[], tuple[Trace, Fit]] | None = field(default=None, repr=False, compare=False)
    keep: Callable[["_Eval"], None] | None = field(default=None, repr=False, compare=False)

    @property
    def first(self) -> Trace:
        if self.trace is None:
            assert self.again is not None
            self.trace, fit = self.again()
            self.fit.plan, self.fit.alternatives = fit.plan, fit.alternatives
            if self.keep is not None:
                self.keep(self)
        return self.trace

    def drop(self) -> None:
        """Drop what is large and can be rebuilt: the trace, the plan and the tied pairings' plans (the
        check runs are done, their results are in ``results`` and ``fit.match``). It changes this
        ``fit`` in place, so a ``Fit`` handed out of the runner must be a copy (``replace``)."""
        self.trace = None
        self.fit.plan, self.fit.alternatives = None, []  # type: ignore[assignment]

    def whole(self) -> "_Eval":
        self.first  # noqa: B018 - rebuilds what was dropped
        return self


class _Runner:
    """Runs choices for one setup; the run count is shared through ``budget`` ([runs, cap])."""

    def __init__(self, setup: DrivenSetup, ranges: Ranges, disconnects: list[dict[str, int]], cap: int | list[int],
                 usual: Usual | None = None) -> None:
        self.setup, self.ranges, self.disconnects = setup, ranges, disconnects
        self.usual = usual or Usual.of(ranges)
        self.budget = cap if isinstance(cap, list) else [0, cap]
        self.cache: dict[Choice, _Eval] = {}
        self.outcomes: dict[tuple[str, ...], int] = {}
        self._kept: deque[_Eval] = deque()

    def _keep(self, ev: _Eval) -> None:
        self._kept.append(ev)
        while len(self._kept) > TRACES_KEPT:
            self._kept.popleft().drop()

    def _first_run(self, choice: Choice) -> Trace:
        s = self.setup
        return run_driven(s.system, s.log, FaultPlan.from_dict(_first_plan(choice, self.disconnects)),
                          s.until_us, s.mutants, s.actor)

    def _again(self, choice: Choice) -> tuple[Trace, Fit]:
        first = self._first_run(choice)
        return first, fit_replies(self.setup, first, choice, self.disconnects, self.ranges, self.usual)

    @property
    def runs(self) -> int:
        return self.budget[0]

    @property
    def cap(self) -> int:
        return self.budget[1]

    def _run(self) -> bool:
        if self.budget[0] + 1 > self.budget[1]:
            return False
        self.budget[0] += 1
        return True

    def evaluate(self, choice: Choice) -> tuple[Fit, Trace] | None:
        ev = self.evaluate_all(choice)
        return None if ev is None else (replace(ev.whole().fit), ev.first)

    def evaluate_all(self, choice: Choice) -> _Eval | None:
        """One run, plus a check run per tied pairing when no receive (polls left out) is unexplained."""
        if choice in self.cache:
            return self.cache[choice]
        s = self.setup
        if not self._run():
            return None
        first = self._first_run(choice)
        fit = fit_replies(s, first, choice, self.disconnects, self.ranges, self.usual)
        ev = _Eval(fit, first, again=lambda: self._again(choice), keep=self._keep)
        self._keep(ev)
        if any(e.name not in s.system.quiet_messages and e.t_us >= s.judge_from_us for e in fit.unexplained):
            self.cache[choice] = ev
            return ev
        if self.budget[0] + len(fit.alternatives) > self.budget[1]:
            return None
        vocab = s.system.vocabulary
        poll_reply = (vocab.poll_reply if vocab is not None else "STATUS_REPLY") if s.status_rule else None
        for i, (plan, fd) in enumerate(fit.alternatives):
            self.budget[0] += 1
            check = run_driven(s.system, s.log, FaultPlan.from_dict(plan), s.until_us, s.mutants, s.actor)
            violated = {v.contract for v in judge(check, s.system.contracts(), s.until_us)}
            m = driven_match(s.log, check.events, s.actor, s.system.quiet_messages, s.tolerance_us,
                             s.horizon_us, violated, s.expect, poll_reply, s.judge_from_us)
            if i == 0:
                fit.match, fit.violated = m, violated
            ok = m.reproduced
            if m.max_dt_us is not None and m.max_dt_us <= s.tolerance_us and m.status_same is not False:
                key = tuple(sorted(violated))
                self.outcomes[key] = self.outcomes.get(key, 0) + 1
            ev.results.append((fd, ok, tuple(sorted(violated))))
        self.cache[choice] = ev
        return ev


# -- the arrival choice ---------------------------------------------------------------------


def _prompt_pairs(first: Trace) -> dict[tuple, int]:
    """For each request attempt the device received: the reply it sent at that same instant."""
    out: dict[tuple, int] = {}
    events = first.events
    for i, e in enumerate(events):
        link = e.data.get("link")
        if e.actor != "device" or e.kind != "recv" or link is None or link.get("copy"):
            continue
        for f in events[i + 1:]:
            if f.t_us != e.t_us:
                break
            fl = f.data.get("link")
            if f.actor == "device" and f.kind == "send" and fl is not None and f.req_id == e.req_id:
                out[(e.name, e.req_id, link["k"])] = (f.name, fl["k"])
                break
    return out


def _arrival_bounds(setup: DrivenSetup, attempts: list[Attempt], probe: Trace, ranges: Ranges) -> dict[tuple, tuple[int, int]]:
    """For each attempt, the arrival interval its replies allow, using the probe run's device timing.

    The probe tells, for the attempt that arrived first for its request, how long after that
    arrival the device sent each reply (``ACK`` at once, ``DONE`` after the move...). Each logged
    receive of such a reply then bounds the arrival: ``recv - delay_max - lag <= arrival <=
    recv - delay_min - lag``. Retries get the bound of their own prompt reply only.
    """
    lo, hi = ranges.c2s
    slo, shi = ranges.s2c
    recv_times: dict[tuple, list[int]] = {}
    for e in setup.log:
        if e.actor == setup.actor and e.kind == "recv":
            recv_times.setdefault((e.name, e.req_id), []).append(e.t_us)
    first_arrival: dict[str | None, tuple[tuple, int]] = {}
    arrivals: dict[str | None, set[int]] = {}
    sends: dict[str | None, list[tuple[str, int, int]]] = {}
    for e in probe.events:
        link = e.data.get("link")
        if e.actor != "device" or link is None:
            continue
        if e.kind == "recv":
            if not link.get("copy") and e.req_id not in first_arrival:
                first_arrival[e.req_id] = ((e.name, e.req_id, link["k"]), e.t_us)
            else:
                arrivals.setdefault(e.req_id, set()).add(e.t_us)  # a later attempt or a copy
        elif e.kind == "send":
            sends.setdefault(e.req_id, []).append((e.name, link["k"], e.t_us))
    prompt = _prompt_pairs(probe)
    # A device send lost at the instant it was made (link down) never reaches the log: number each
    # reply by the sends that reached the link, which is what the log's receives count.
    index: dict[tuple, int] = {}
    counter: dict[tuple, int] = {}
    for e, link in _device_sends(probe):
        n = counter.get((e.name, e.req_id), 0)
        index[(e.name, e.req_id, link["k"])] = n
        counter[(e.name, e.req_id)] = n + 1
    out = {}
    for a in attempts:
        a_lo, a_hi = a.t_us + lo, a.t_us + hi
        replies: list[tuple[str, int, int]] = []  # (reply name, which receive, lag after arrival)
        fa = first_arrival.get(a.req_id)
        if fa is not None and fa[0] == a.key:
            others = arrivals.get(a.req_id, set())
            replies = [(n, k, t - fa[1]) for n, k, t in sends.get(a.req_id, [])
                       if t >= fa[1] and (t == fa[1] or t not in others)]
        elif a.key in prompt:
            replies = [(prompt[a.key][0], prompt[a.key][1], 0)]
        for name, k, lag in replies:
            j = index.get((name, a.req_id, k))
            times = recv_times.get((name, a.req_id), [])
            if j is not None and j < len(times):
                a_lo = max(a_lo, times[j] - shi - lag)
                a_hi = min(a_hi, times[j] - slo - lag)
        out[a.key] = (a_lo, a_hi)
    return out


def _sent_while_down(a: Attempt, disconnects: list[dict[str, int]]) -> bool:
    return any(d["t_us"] <= a.t_us < d["t_us"] + d["duration_us"] for d in disconnects)


def _default_choice(setup: DrivenSetup, attempts: list[Attempt], runner: _Runner) -> Choice:
    """Each attempt arrives at the time closest to ``send + usual`` where its delay and its replies'
    delays are all within the limit (:func:`_arrival_bounds` with the ranges cut at the limits, read
    off a probe run where every attempt arrives at the minimum delay); with no such time, at
    ``send + usual``."""
    ranges, usual = runner.ranges, runner.usual
    lo, hi = ranges.c2s
    base = Choice(tuple((a.key, lo) for a in attempts))
    probe = runner.evaluate(base)
    if probe is None:
        return base
    tight = Ranges((lo, min(hi, usual.c2s_limit)), (ranges.s2c[0], min(ranges.s2c[1], usual.s2c_limit)), ranges.dup_extra)
    bounds = _arrival_bounds(setup, attempts, probe[1], tight)
    delays = []
    for a in attempts:
        want = min(max(usual.c2s, lo), hi)
        if _sent_while_down(a, runner.disconnects):
            delays.append((a.key, lo))  # sent while the link was down: lost at once, its delay means nothing
            continue
        b_lo, b_hi = bounds[a.key]
        if b_lo <= b_hi:
            d = min(max(a.t_us + want, b_lo), b_hi) - a.t_us
        else:
            d = want
        delays.append((a.key, min(max(d, lo), hi)))
    return Choice(tuple(delays))


def _cut_points(first: Trace, t0: int, t1: int, quiet: frozenset[str] = frozenset()) -> list[int]:
    """Times of the device's events strictly inside (t0, t1), polls left out: the instants where an
    arrival moving past them can change what the device does."""
    return sorted({e.t_us for e in first.events if e.actor == "device" and t0 < e.t_us < t1 and e.name not in quiet})


def _reply_lags(first: Trace, rid: str | None) -> dict[str, set[int]]:
    """How long after the first arrival of ``rid`` the device sent each reply, plus 0 for every reply
    name (a repeated id gets its stored result at once)."""
    t0 = None
    out: dict[str, set[int]] = {}
    for e in first.events:
        if e.actor != "device" or e.req_id != rid:
            continue
        link = e.data.get("link") or {}
        if e.kind == "recv" and t0 is None and not link.get("copy"):
            t0 = e.t_us
        elif e.kind == "send" and t0 is not None:
            out.setdefault(e.name, {0}).add(e.t_us - t0)
    return out


def _options(setup: DrivenSetup, first: Trace, a: Attempt, d0: int | None, ranges: Ranges, usual: Usual,
             disconnects: list[dict[str, int]], last_arrival: int | None = None) -> list[tuple[int | None, int | None, int]]:
    """An attempt's options ``(delay, dup extra, request-side faults)``, the default first (see the module doc).

    ``last_arrival``: no arrival or copy later than this (a unit judged on a cut log cannot see what
    an arrival after the cut causes, so such an arrival would look free of reply faults)."""
    lo, hi = ranges.c2s
    dlo, dhi = ranges.dup_extra
    quiet = setup.system.quiet_messages

    def cost(d: int) -> int:
        return 1 if d > usual.c2s_limit else 0

    lags = _reply_lags(first, a.req_id)
    poll = a.key[0] in quiet
    recv = [e for e in setup.log if e.actor == setup.actor and e.kind == "recv" and e.req_id == a.req_id
            and (poll or e.name not in quiet)]
    cand = {lo}
    cand |= {t + 1 - a.t_us for t in _cut_points(first, a.t_us + lo, a.t_us + hi, quiet)}
    for r in recv:
        for lag in lags.get(r.name, {0}) | {0}:
            cand.add(r.t_us - usual.s2c - lag - a.t_us)
            # the arrival nearest the usual delay at which both this attempt and a reply to it received
            # at r are within the limits, whichever send that receive is paired with
            w_lo = max(lo, r.t_us - usual.s2c_limit - lag - a.t_us)
            w_hi = min(hi, usual.c2s_limit, r.t_us - ranges.s2c[0] - lag - a.t_us)
            if w_lo <= w_hi:
                cand.add(min(max(usual.c2s, w_lo), w_hi))
    cand |= {d["t_us"] + 1 - a.t_us for d in disconnects}
    out: list[tuple[int | None, int | None, int]] = [(d0, None, 0 if d0 is None else cost(d0))]
    out.append((None, None, 1))
    end = float("inf") if last_arrival is None else last_arrival
    out += [(d, None, cost(d)) for d in sorted(cand) if lo <= d <= hi and d != d0 and a.t_us + d <= end]
    if d0 is not None:
        arr = a.t_us + d0
        extras = {r.t_us - usual.s2c - arr for r in recv}
        out += [(d0, x, 1 + cost(d0)) for x in sorted(extras) if dlo <= x <= dhi and arr + x <= end]
    return out


def _choices(base: Choice, keys: list[tuple], options: list[list[tuple]], bound) -> Iterator[Choice]:
    """Choices in order of how many attempts leave the default; skips those whose request-side
    faults exceed ``bound()`` (read at each step, so it tightens as better explanations are found)."""
    n = len(keys)
    for d in range(n + 1):
        for subset in combinations(range(n), d):
            for picks in product(*(options[i][1:] for i in subset)):
                if sum(p[2] for p in picks) > bound():
                    continue
                yield base.assign({keys[i]: (p[0], p[1]) for i, p in zip(subset, picks)})


# -- search units ---------------------------------------------------------------------------


def _commands(log: Sequence[Event], actor: str, quiet: frozenset[str], late_us: int = 50_000) -> dict[str, tuple[int, int, list[str]]]:
    """Per command request id: (first send, last event, why it is anomalous) — the rule of :func:`anomaly_windows`."""
    ev = [e for e in log if e.actor == actor]
    by: dict[str, list[Event]] = {}
    for e in ev:
        if e.req_id is not None and e.name not in quiet:
            by.setdefault(e.req_id, []).append(e)
    gaps = []
    info = {}
    for rid, es in by.items():
        sends = [e for e in es if e.kind == "send"]
        if not sends:
            continue
        acks = [e for e in es if e.kind == "recv" and e.name == "ACK"]
        dones = [e for e in es if e.kind == "recv" and e.name == "DONE"]
        if acks and dones:
            gaps.append(dones[0].t_us - acks[0].t_us)
        info[rid] = (sends, acks, dones, es)
    gaps.sort()
    median = (gaps[len(gaps) // 2] if len(gaps) % 2 else (gaps[len(gaps) // 2 - 1] + gaps[len(gaps) // 2]) // 2) if gaps else None
    out = {}
    for rid, (sends, acks, dones, es) in info.items():
        why = []
        if len(sends) > 1:
            why.append("retry")
        if any(e.kind == "handle" and e.name == "ERROR" for e in es):
            why.append("failed")
        if any(e.kind == "recv" and e.name == "ERROR" for e in es):
            why.append("error reply")
        names = [e.name for e in es if e.kind == "recv"]
        if any(names.count(n) > 1 for n in set(names)) and len(sends) == 1:
            why.append("same reply twice")
        if acks and acks[0].t_us - sends[0].t_us > late_us:
            why.append("late ACK")
        if acks and dones and median is not None and dones[0].t_us - acks[0].t_us > median + late_us:
            why.append("late DONE")
        closes = [e.t_us for e in es if e.kind == "handle"]
        end = max(closes) if closes else max(e.t_us for e in es)
        out[rid] = (sends[0].t_us, max(end, max(e.t_us for e in es)), why)
    return out


def anomaly_windows(log: Sequence[Event], actor: str, quiet: frozenset[str], margin_us: int = 1_000_000,
                    late_us: int = 50_000) -> list[tuple[int, int, list[str]]]:
    """Windows around what looks wrong in a client log, chosen without knowing the answer.

    A command (a request id that is not a poll) is anomalous when it was sent more than once, closed
    with ``ERROR`` (any cause), got an ``ERROR`` reply, got the same reply twice, waited more than
    ``late_us`` for its first ``ACK``, or waited from ``ACK`` to ``DONE`` more than ``late_us``
    longer than the log's median for that gap. A logged disconnect is anomalous too. The window
    runs from ``margin_us`` before the command's first send (the disconnect) to ``margin_us`` after
    it closed (the reconnect). Overlapping windows are merged.
    """
    wins: list[tuple[int, int, list[str]]] = []
    for rid, (t0, t1, why) in _commands(log, actor, quiet, late_us).items():
        if why:
            wins.append((t0 - margin_us, t1 + margin_us, [f"{rid}: {', '.join(why)}"]))
    down = None
    for e in log:
        if e.actor != actor:
            continue
        if e.kind == "state" and e.name == "DISCONNECTED":
            down = e.t_us
        elif e.kind == "state" and e.name == "CONNECTED" and down is not None:
            wins.append((down - margin_us, e.t_us + margin_us, ["disconnect"]))
            down = None
    wins.sort()
    merged: list[tuple[int, int, list[str]]] = []
    for a, b, w in wins:
        a = max(a, 0)
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b), merged[-1][2] + w)
        else:
            merged.append((a, b, w))
    return merged


def _judge_start(log: Sequence[Event], actor: str, quiet: frozenset[str], t0: int, tol: int) -> int:
    """A judging start at or before ``t0`` with no logged receive (polls left out) in the two
    tolerances before it, so a simulated receive just before the start cannot be compared by mistake."""
    times = sorted(e.t_us for e in log if e.actor == actor and e.kind == "recv" and e.name not in quiet and e.t_us < t0)
    start = t0
    while times and times[-1] >= start - 2 * tol:
        start = times.pop()
    return start


def _leaves_unexplained(ev: _Eval, rids: set[str]) -> bool:
    """A receive of one of ``rids`` that no device send explains, polls included. Driven replay leaves
    poll replies out of the match, so without this a lost poll request would pass with its logged
    reply unexplained. (Tied pairings leave the same number of receives of a key unexplained.)"""
    return any(str(e.req_id) in rids for e in ev.fit.unexplained)


def _search_unit(runner: _Runner, base: Choice, attempts: list[Attempt], rids: set[str | None], plus_one: bool,
                 why: Sequence[str] = (), last_arrival: int | None = None) -> UnitSet:
    """Every minimal explanation of one unit (and, with ``plus_one``, those with one fault more)."""
    s = runner.setup
    keys = [a.key for a in attempts]
    unit = UnitSet(tuple(sorted(str(r) for r in rids)), tuple(keys), None, why=tuple(why))
    probe = runner.evaluate_all(base)
    if probe is None:
        return unit
    d0 = dict(base.delays)
    options = [_options(s, probe.first, a, d0[a.key], runner.ranges, runner.usual, runner.disconnects, last_arrival)
               for a in attempts]
    found: dict[frozenset, tuple[int, Explanation]] = {}
    best: list[int | None] = [None]
    extra = 1 if plus_one else 0

    def bound() -> float:
        return float("inf") if best[0] is None else best[0] + extra

    complete = True
    for choice in _choices(base, keys, options, bound):
        ev = runner.evaluate_all(choice)
        if ev is None:
            complete = False
            break
        unit.choices_run += 1
        if _leaves_unexplained(ev, {str(r) for r in rids}):
            continue
        for fd, ok, violated in ev.results:
            if not ok:
                continue
            uf = {k: v for k, v in fd.items() if k[3] in rids}
            f = len(uf)
            ident = frozenset(uf)
            if ident not in found:
                found[ident] = (f, Explanation(uf, choice.of(keys), violated))
            else:
                found[ident][1].merge(uf, choice.of(keys))
            if best[0] is None or f < best[0]:
                best[0] = f
    unit.exhausted = complete and best[0] is None
    if best[0] is None:
        return unit
    unit.f = best[0]
    unit.explanations = [x for f, x in found.values() if f == best[0]]
    unit.plus_one = [x for f, x in found.values() if f == best[0] + 1] if plus_one else []
    unit.minimal_shown = complete
    unit.plus_one_shown = complete and plus_one
    return unit


def _poll_units(setup: DrivenSetup, fit: Fit) -> dict[str, tuple[int, int, list[str]]]:
    """Polls (attempts of a quiet message with a request id) with a fault in ``fit`` or a receive it
    leaves unexplained: request id -> (first send, last event, why)."""
    quiet = setup.system.quiet_messages
    polls: dict[str, list[Event]] = {}
    for e in setup.log:
        if e.actor == setup.actor and e.req_id is not None and e.name in quiet and e.kind in ("send", "recv"):
            polls.setdefault(e.req_id, []).append(e)
    bad = {str(k[3]) for k in fit.faults} | {str(e.req_id) for e in fit.unexplained}
    out = {}
    for rid, es in polls.items():
        sends = [e for e in es if e.kind == "send"]
        if rid in bad and sends and any(e.t_us >= setup.judge_from_us for e in es):
            out[rid] = (sends[0].t_us, max(e.t_us for e in es), ["poll"])
    return out


def _one_more(runner: _Runner, base: Choice, attempts: list[Attempt], rid: str, final: _Eval, f_star: int) -> UnitSet:
    """The explanations with one fault more than ``f_star`` that move only ``rid``'s attempts away from
    ``base`` (where ``rid`` has no fault) and leave every other request id's faults as in a minimal
    explanation of ``final``. Searched on the whole log; the unit's ``explanations`` is the empty one."""
    s = runner.setup
    keys = [a.key for a in attempts]
    unit = UnitSet((rid,), tuple(keys), 0, [Explanation({}, base.of(keys))], why=("one fault more",))
    rest = [frozenset(k for k in fd if str(k[3]) != rid) for fd, ok, _ in final.results if ok]
    d0 = dict(base.delays)
    options = [_options(s, final.first, a, d0[a.key], runner.ranges, runner.usual, runner.disconnects)
               for a in attempts]
    found: dict[frozenset, Explanation] = {}
    complete = True
    for choice in _choices(base, keys, options, lambda: 1):
        if choice == base:
            continue
        ev = runner.evaluate_all(choice)
        if ev is None:
            complete = False
            break
        unit.choices_run += 1
        if _leaves_unexplained(ev, {rid}):
            continue
        for fd, ok, violated in ev.results:
            if not ok or len(fd) != f_star + 1:
                continue
            if frozenset(k for k in fd if str(k[3]) != rid) not in rest:
                continue
            mine = {k: v for k, v in fd.items() if str(k[3]) == rid}
            if frozenset(mine) in found:
                found[frozenset(mine)].merge(mine)
            else:
                found[frozenset(mine)] = Explanation(mine, choice.of(keys), violated)
    unit.plus_one = list(found.values())
    unit.minimal_shown = True
    unit.plus_one_shown = unit.exhausted = complete
    return unit


def fit_log(setup: DrivenSetup, ranges: Ranges | None = None, cap: int = FIT_RUNS, branches: bool = False,
            branch_cap: int = BRANCH_RUNS, window: tuple[int, int] | None = None, usual: Usual | None = None,
            plus_one: bool = False) -> FitResult:
    """Fit ``setup.log`` with the fewest faults (see the module docstring).

    ``usual``: the usual delays and fault limits (default :meth:`Usual.of` the ranges). ``plus_one``:
    also collect the explanations with one fault more than the fewest (a diagnostic).
    ``window``: fit only ``(t0, t1)``. The script stops at t1, receives before t0 are not judged, and
    only commands first sent inside the window are searched; the rest keep the default. The run still
    starts at 0 (no device start state yet).
    """
    ranges = ranges or Ranges.of(setup)
    usual = usual or Usual.of(ranges)
    if window is not None:
        t0, t1 = window
        setup = replace(setup, log=[e for e in setup.log if e.t_us <= t1], judge_from_us=t0)
    quiet = setup.system.quiet_messages
    all_attempts = attempts_of(setup.log, setup.actor)
    disconnects = logged_disconnects(setup.log, setup.actor, setup.until_us)
    budget = [0, cap]
    runner = _Runner(setup, ranges, disconnects, budget, usual)
    n_recv = sum(1 for e in setup.log if e.actor == setup.actor and e.kind == "recv" and e.name not in quiet)
    slow = slow_round_trips(setup.log, setup.actor, quiet, usual.c2s_limit)

    def result(status, fit, **kw) -> FitResult:
        out = FitResult(status, budget[0], fit, receives=n_recv, matched=fit.match.matched if fit.match else 0,
                        disconnects_from_log=len(disconnects), quiet=quiet, outcomes=dict(runner.outcomes),
                        expect_given=setup.expect is not None, usual=usual, plus_one=plus_one, slow=slow, **kw)
        out.window = window
        return out

    default = _default_choice(setup, all_attempts, runner)
    ev0 = runner.evaluate_all(default)
    if ev0 is None:
        return result("incomplete", Fit(_first_plan(default, disconnects), [], 0, 0, 0), incomplete_reason="cap")
    cmds = _commands(setup.log, setup.actor, quiet)
    in_win = {rid for rid, (t0, _, _) in cmds.items() if window is None or window[0] <= t0 <= window[1]}
    unit_rids = [rid for rid in in_win if cmds[rid][2]]
    sent = {a.req_id for a in all_attempts}
    for e in ev0.fit.unexplained:
        if e.name not in quiet and e.t_us >= setup.judge_from_us and e.req_id in sent and e.req_id in in_win \
                and e.req_id not in unit_rids:
            unit_rids.append(e.req_id)
    # A poll with a fault in the default (a lost or repeated reply, or a reply nothing explains) is a
    # unit too: a poll does not change the device, so a lost request and a lost reply look the same
    # and only the search can say which explanations tie.
    poll_rids: set[str] = set()
    for rid, info in _poll_units(setup, ev0.fit).items():
        if window is None or window[0] <= info[0] <= window[1]:
            cmds[rid] = info
            unit_rids.append(rid)
            poll_rids.add(rid)
    unit_rids.sort(key=lambda r: cmds[r][0])

    def unit_attempts(rids) -> list[Attempt]:
        return [a for a in all_attempts if a.req_id in rids and not _sent_while_down(a, disconnects)]

    choice = default
    units: list[UnitSet] = []
    for i, rid in enumerate(unit_rids):
        t_first, t_end, why = cmds[rid]
        # judged up to the next unit's first send (or the end of the log), so what the unit's choices
        # cause later (a DONE after a move) is seen
        cut = cmds[unit_rids[i + 1]][0] - 1 if i + 1 < len(unit_rids) else setup.log[-1].t_us
        cut = max(cut, t_end)
        start = _judge_start(setup.log, setup.actor, quiet, t_first, setup.tolerance_us)
        su = replace(setup, log=[e for e in setup.log if e.t_us <= cut], judge_from_us=max(setup.judge_from_us, start),
                     end_us=max(cut, setup.log[0].t_us) if cut < setup.log[-1].t_us else setup.end_us)
        ru = _Runner(su, ranges, disconnects, budget, usual)
        ru.outcomes = runner.outcomes
        # each unit gets a fair share of what is left, keeping some for the whole-log runs
        reserve = min(cap // 10, 200)
        share = max(0, (cap - reserve - budget[0]) // (len(unit_rids) - i))
        budget[1] = min(cap, budget[0] + share)
        u = _search_unit(ru, choice, unit_attempts({rid}), {rid}, plus_one, why, cut - setup.tolerance_us)
        budget[1] = cap
        if rid in poll_rids and not u.explanations:
            # a poll the option space cannot explain keeps the default, as polls did before: poll
            # replies are not matched, and an unexplained one is reported apart
            continue
        units.append(u)
        if u.explanations:
            choice = choice.assign(u.explanations[0].choice)

    def compose(picks: Sequence[Explanation]) -> Choice:
        c = default
        for x in picks:
            c = c.assign(x.choice)
        return c

    def on_whole_log(us: list[UnitSet]) -> None:
        """Recount each unit's candidates on the whole log (a unit was judged on a cut log), the other
        units at their first explanation; keep the fewest and, with ``plus_one``, one more."""
        firsts = [u.explanations[0] if u.explanations else None for u in us]
        for i, u in enumerate(us):
            if not u.explanations:
                continue
            got: dict[frozenset, tuple[int, Explanation]] = {}
            # the cut log's values are not kept: each choice (and the others with the same faults) is
            # run on the whole log, so the spans hold only values that reproduce the whole log
            cands = [y for x in u.explanations + u.plus_one
                     for y in [replace(x, spans={}, others=[])] + [replace(x, choice=c, spans={}, others=[])
                                                                    for c in x.others]]
            for x in cands:
                picks = [p for j, p in enumerate(firsts) if j != i and p is not None] + [x]
                ev = runner.evaluate_all(compose(picks))
                if ev is None:
                    u.minimal_shown = u.plus_one_shown = False
                    return
                if _leaves_unexplained(ev, set(u.req_ids)):
                    continue
                for fd, ok, violated in ev.results:
                    if ok:
                        uf = {k: v for k, v in fd.items() if str(k[3]) in u.req_ids}
                        if frozenset(uf) in got:
                            got[frozenset(uf)][1].merge(uf)
                        else:
                            got[frozenset(uf)] = (len(uf), Explanation(uf, x.choice, violated))
            if not got:
                u.explanations, u.plus_one, u.f = [], [], None
                continue
            u.f = min(n for n, _ in got.values())
            u.explanations = [x for n, x in got.values() if n == u.f]
            u.plus_one = [x for n, x in got.values() if n == u.f + 1] if plus_one else []

    on_whole_log(units)
    units = [u for u in units if u.explanations or not set(u.req_ids) <= poll_rids]
    if units and all(u.explanations for u in units):
        choice = compose([u.explanations[0] for u in units])
    final = runner.evaluate_all(choice)
    joint = False
    need_joint = False
    combos = (0, 0)
    ok_units = units and all(u.explanations for u in units)
    if final is not None and ok_units:
        sets = [u.explanations for u in units]
        total = 1
        for x in sets:
            total *= len(x)
        to_run = list(product(*sets)) if total <= COMBINATIONS_RUN else [tuple(x[0] for x in sets)]
        passed = 0
        for picks in to_run:
            ev = runner.evaluate_all(compose(picks))
            if ev is None:
                break
            passed += any(ok for _, ok, _ in ev.results)
        combos = (passed, total) if total <= COMBINATIONS_RUN else ((total if passed == 1 else 0), total)
        if passed < len(to_run) and len(units) > 1:
            need_joint = True
    elif final is not None and not units:
        combos = (1, 1) if any(ok for _, ok, _ in final.results) else (0, 1)
    if final is not None and len(units) > 1 and (need_joint or not ok_units):
        # a unit or a combination failed: search the units together, on the whole log
        rids = set().union(*(set(u.req_ids) for u in units))
        j = _search_unit(runner, default, unit_attempts(rids), rids, plus_one,
                         [w for u in units for w in u.why])
        joint = True
        units = [j]
        on_whole_log(units)
        if j.explanations:
            choice = compose([j.explanations[0]])
            final = runner.evaluate_all(choice)
            combos = (1, 1) if final is not None and any(ok for _, ok, _ in final.results) else (0, 1)

    if final is None:
        return result("incomplete", replace(ev0.whole().fit), units=units, incomplete_reason="cap")
    fit = replace(final.whole().fit)  # a copy: a later drop of the cached entry must not reach the result
    reproduced = any(ok for _, ok, _ in final.results) and all(u.explanations for u in units)
    unit_ids = set().union(*(set(u.req_ids) for u in units)) if units else set()
    if reproduced:
        outside: list[dict[Fault, int | None]] = []
        outside_spans: list[dict[Fault, Span]] = []
        for fd, ok, _ in final.results:
            if ok:
                o = {k: v for k, v in fd.items() if str(k[3]) not in unit_ids}
                i = next((j for j, p in enumerate(outside) if p.keys() == o.keys()), None)
                if i is None:
                    outside.append(o)
                    outside_spans.append({})
                _widen(outside_spans[-1 if i is None else i], o)
        out = result("reproduced", fit, units=units, outside=outside, outside_spans=outside_spans,
                     combinations=combos, joint=joint, choice=choice)
        out.min_faults = sum(u.f or 0 for u in units) + min((len(o) for o in outside), default=0)
        if plus_one:
            # one fault more on a command outside the units (the units' own f*+1 is above)
            free = [rid for rid in sorted(in_win - unit_ids, key=lambda r: cmds[r][0])
                    if not any(str(k[3]) == rid for o in outside for k in o)]
            for rid in free:
                atts = unit_attempts({rid})
                if not atts:
                    continue
                m = _one_more(runner, choice, atts, rid, final, out.min_faults)
                out.more.append(m)
                if not m.plus_one_shown:
                    break
            out.runs = budget[0]
    else:
        left = [e for e in fit.unexplained if e.name not in quiet and e.t_us >= setup.judge_from_us]
        never_sent = [e for e in left if e.req_id not in sent]
        # a unit's exhausted space is evidence only when every earlier unit reproduced: otherwise it
        # started from a device state no explanation of the earlier commands gives
        first_fail = next((u for u in units if not u.explanations), None)
        if never_sent or (first_fail is not None and first_fail.exhausted):
            out = result("unexplained", fit, units=units)
        else:
            out = result("incomplete", fit, units=units, incomplete_reason="cap")
    if branches and out.reproduced:
        _branch_points(setup, out, choice, final.first, all_attempts, ranges, disconnects, branch_cap, usual)
    return out


def random_arrivals(setup: DrivenSetup, res: FitResult, ranges: Ranges, usual: Usual, draws: int = 400,
                    seed: int = 0) -> dict[str, Any]:
    """A check of ``res.min_faults``, not a proof: arrivals drawn at random, off the option points.

    Each draw takes one command (a request id that is not a poll) and redraws its attempts: dropped
    (15%), or arriving near its fitted arrival (+-60 ms), inside the interval its replies allow, or
    anywhere in the range, with a duplicate 15% of the time. Every other attempt keeps the reported
    plan's arrival. A draw that reproduces the log with fewer faults than ``f*`` shows an explanation
    the option points missed. Returns the counts and those draws' faults (``fewer``).
    """
    if not res.reproduced or res.choice is None:
        raise ValueError("the random-arrival check needs a reproduced fit")
    rng = random.Random(seed)
    quiet = setup.system.quiet_messages
    disconnects = logged_disconnects(setup.log, setup.actor, setup.until_us)
    runner = _Runner(setup, ranges, disconnects, 10**12, usual)
    every = attempts_of(setup.log, setup.actor)
    atts = [a for a in every if a.key[0] not in quiet and not _sent_while_down(a, disconnects)]
    by: dict[str | None, list[Attempt]] = {}
    for a in atts:
        by.setdefault(a.req_id, []).append(a)
    rids = sorted(by, key=str)
    probe = runner.evaluate(Choice(tuple((a.key, ranges.c2s[0]) for a in every)))
    bounds = _arrival_bounds(setup, atts, probe[1], ranges) if probe is not None else {}
    base = res.choice
    lo, hi = ranges.c2s
    reproduced, fewest, fewer = 0, None, []
    for _ in range(draws if rids else 0):
        items = {}
        for a in by[rng.choice(rids)]:
            if rng.random() < 0.15:
                items[a.key] = (None, None)
                continue
            b_lo, b_hi = bounds.get(a.key, (1, 0))
            near = base.delay(a.key)
            mode = rng.random()
            if mode < 0.4:
                d = (usual.c2s if near is None else near) + rng.randint(-60_000, 60_000)
            elif b_lo <= b_hi and mode < 0.8:
                d = rng.randint(b_lo, b_hi) - a.t_us
            else:
                d = rng.randint(lo, hi)
            extra = rng.randint(*ranges.dup_extra) if rng.random() < 0.15 else None
            items[a.key] = (min(max(d, lo), hi), extra)
        ev = runner.evaluate_all(base.assign(items))
        for fd, ok, _ in ev.results:
            if ok:
                reproduced += 1
                fewest = len(fd) if fewest is None else min(fewest, len(fd))
                if len(fd) < (res.min_faults or 0) and fd not in fewer:
                    fewer.append(fd)
    return {"draws": draws if rids else 0, "seed": seed, "runs": runner.runs, "reproduced": reproduced,
            "fewest": fewest, "fewer": [[list(k) + [v] for k, v in sorted(fd.items(), key=lambda kv: str(kv[0]))]
                                        for fd in fewer]}


def _branch_points(setup: DrivenSetup, out: FitResult, choice: Choice, first: Trace, attempts: list[Attempt],
                   ranges: Ranges, disconnects: list[dict[str, int]], cap: int, usual: Usual) -> None:
    """Move each arriving command attempt to just after every device event inside the interval its
    replies allow (:func:`_arrival_bounds`, from the fitted run) and count the attempts where some
    move stops the fit reproducing."""
    quiet = setup.system.quiet_messages
    bounds = _arrival_bounds(setup, attempts, first, ranges)
    runner = _Runner(setup, ranges, disconnects, cap, usual)
    checked = with_branch = 0
    for a in attempts:
        d = choice.delay(a.key)
        if d is None or a.key[0] in quiet:
            continue
        b_lo, b_hi = bounds[a.key]
        cuts = [t for t in _cut_points(first, max(b_lo, a.t_us + ranges.c2s[0]) - 1, b_hi, quiet)
                if t + 1 - a.t_us != d]
        if not cuts:
            continue
        checked += 1
        for t in cuts:
            res = runner.evaluate(choice.with_delay(a.key, t + 1 - a.t_us))
            if res is None:
                out.branch_capped = True
                break
            if not (res[0].match is not None and res[0].match.reproduced):
                with_branch += 1
                break
        if out.branch_capped:
            break
    out.branch_attempts, out.branch_checked, out.branch_runs = with_branch, checked, runner.runs
    for k, n in runner.outcomes.items():
        out.outcomes[k] = out.outcomes.get(k, 0) + n


def device_models(system) -> list[str]:
    """The system's published device-side defects, the models ``judge_models`` may compare. Client
    defects are not among them: in driven replay the client is the script."""
    return [m for m, d in system.published_defects if d.startswith("device:")]


def _settled(r: FitResult) -> bool:
    """Reproduced, the minimal set complete, and no random draw found fewer faults."""
    return r.status == "reproduced" and r.minimal_shown and not (r.random_check and r.random_check["fewer"])


def _capped(r: FitResult) -> bool:
    """The run cap ended the search: nothing reproduced, or the minimal set is not shown."""
    return r.status == "incomplete" or (r.status == "reproduced" and not r.minimal_shown)


def judge_models(correct: FitResult, others: dict[str, FitResult]) -> dict[str, Any]:
    """Compare the fewest faults under the correct device model with each defect model's.

    - A defect model is a **candidate** when its fit is settled (reproduced, minimal set complete, no
      random draw with fewer) and the correct model's fit is unexplained, or settled with more faults.
    - A defect model that ends **unexplained**, or **hits the cap without reproducing**, is not a
      candidate. (The second is not proven: more runs might reproduce it with fewer faults. The
      ``capped`` list says where it applies.)
    - **Undecided:** a defect model that reproduced but is not settled, or any defect model that
      reproduced while the correct model's fit is not settled and not unexplained.
    - **Verdict:** the candidates with the fewest faults, "A or B", when there is one; otherwise
      "undecided" when a model is undecided; otherwise "correct model". A tie is no accusation.
    - ``difference`` is the correct model's ``f*`` minus the accused set's (None when the correct
      model is unexplained). ``capped`` names every fit, the correct model's included, that the cap
      ended."""
    def row(r: FitResult) -> dict[str, Any]:
        return {"status": r.status, "min_faults": r.min_faults, "explanations": r.n_explanations,
                "minimal_shown": r.minimal_shown, "runs": r.runs,
                "random_fewer": None if r.random_check is None else len(r.random_check["fewer"])}

    ok_unexplained = correct.status == "unexplained"
    fewer, undecided = [], []
    for m, r in others.items():
        if r.status != "reproduced":
            continue  # unexplained, or the cap ended it before anything reproduced: not a candidate
        if not _settled(r):
            undecided.append(m)
        elif ok_unexplained or (_settled(correct) and (r.min_faults or 0) < (correct.min_faults or 0)):
            fewer.append(m)
        elif not _settled(correct):
            undecided.append(m)
    best = min((others[m].min_faults or 0 for m in fewer), default=None)
    accused = sorted((m for m in fewer if others[m].min_faults == best), key=_model_order)
    capped = (["correct"] if _capped(correct) else []) + sorted((m for m, r in others.items() if _capped(r)),
                                                                key=_model_order)
    verdict = ("defect suspected: " + " or ".join(accused)) if accused else ("undecided" if undecided else "correct model")
    return {
        "correct": row(correct), "models": {m: row(r) for m, r in others.items()},
        "fewer": sorted(fewer, key=_model_order), "accused": accused, "accused_size": len(accused),
        "difference": None if not accused or ok_unexplained else (correct.min_faults or 0) - (best or 0),
        "undecided": sorted(undecided, key=_model_order), "capped": capped, "capped_count": len(capped),
        "verdict": verdict,
        "fits": {m: r.to_dict() for m, r in others.items()},
    }


def _model_order(m: str) -> tuple:
    return (len(m), m)


def model_lines(d: dict[str, Any]) -> list[str]:
    def one(name: str, r: dict[str, Any]) -> str:
        st = (f"f* {r['min_faults']}, {r['explanations']} explanations" if r["status"] == "reproduced" else r["status"])
        if r["status"] == "reproduced" and not r["minimal_shown"]:
            st += ", minimal not shown"
        if r["random_fewer"]:
            st += f", random check found fewer ({r['random_fewer']})"
        return f"  {name}: {st}"
    lines = ["device models (the fewest faults each needs; a defect is accused only with fewer faults than the "
             "correct model, and a tie is no accusation):", one("correct", d["correct"])]
    lines += [one(m, r) for m, r in d["models"].items()]
    v = d["verdict"]
    if d["accused"]:
        v += (" (the correct model is unexplained)" if d["difference"] is None
              else f" ({d['difference']} fault{'s' if d['difference'] != 1 else ''} fewer)")
    lines.append(f"verdict: {v}" + (f"; undecided: {', '.join(d['undecided'])}" if d["undecided"] else "")
                 + (f"; ended by the run cap: {', '.join(d['capped'])} (a defect model the cap ended before it "
                    "reproduced is not a candidate)" if d["capped"] else ""))
    return lines


def _show_fault(k: Fault, v: Span | None, with_id: bool = True) -> str:
    kind, d, msg, rid, n = k
    if v is None:
        val = ""
    else:
        val = f"{v[0] / 1e6:.3f}s" if v[0] == v[1] else f"{v[0] / 1e6:.3f}-{v[1] / 1e6:.3f}s"
        val = " " + ("" if kind == "delay" else "+") + val
    return f"{kind} {d} {msg}{' ' + str(rid) if with_id else ''} k{n}{val}"


def report_lines(res: FitResult) -> list[str]:
    f = res.fit
    head = {"reproduced": "reproduced",
            "unexplained": "unexplained: every choice in the fitter's choice space was run (evidence about the device)",
            "incomplete": "incomplete: the fit did not get to the end ("
                          + {"cap": "run cap reached"}.get(res.incomplete_reason or "", res.incomplete_reason or "")
                          + "); what stays unexplained is a limit of the fitter, not evidence about the device"}[res.status]
    win = f" in window {res.window[0] / 1e6:.6f}s..{res.window[1] / 1e6:.6f}s" if res.window else ""
    lines = [f"fit{win}: {head}, {res.runs} runs"]
    if res.reproduced:
        shown = "minimal shown" if res.minimal_shown else "best found, minimal not shown (run cap)"
        line = f"fewest faults: {res.min_faults}; explanations with that many: {res.n_explanations} ({shown})"
        if res.plus_one:
            line += (f"; with one fault more: {res.n_plus_one}"
                     + ("" if res.plus_one_shown else " (not complete)"))
        lines.append(line)
        if res.combinations[1] > 1:
            lines.append(f"unit combinations run on the whole log: {res.combinations[0]} of {res.combinations[1]} reproduce"
                         + (" (searched together after a failed combination)" if res.joint else ""))
        com = res.common()
        lines.append("common to every minimal explanation (values as seen in the explanations found, not every "
                     "possible value): "
                     + ("; ".join(_show_fault(k, v) for k, v in sorted(com.items(), key=lambda kv: str(kv[0]))) or "none"))
        und = res.alternatives()
        if und:
            lines.append("alternatives (the minimal explanations differ; values as seen in the explanations found):")
            for g, alts in und:
                lines.append(f"  {g}: " + " | ".join("; ".join(_show_fault(k, v) for k, v in sorted(a.items(), key=lambda kv: str(kv[0])))
                                                   or "no fault" for a in alts))
    lines += [
        f"receives fitted: {res.matched}/{res.receives} (polls left out); disconnects from the log: {res.disconnects_from_log}",
        f"explained by loss: {f.drops} link faults (a device that does not send a reply looks the same as a lost "
        "reply, so this is not evidence that there is no defect)",
        f"explained by duplicate: {f.dups}; late beyond the usual delay: {f.delays}; lost to a logged disconnect: "
        f"{f.lost_to_disconnect}; in flight at the end of the log: {f.in_flight}",
        f"unexplained: {len(f.unexplained)}, poll replies {sum(e.name in res.quiet for e in f.unexplained)}"
        + (" (no device send explains: " + ", ".join(
            f"{e.name} {e.req_id or '-'} at {e.t_us / 1e6:.6f}s" + (f" log line {e.log['line']}" if e.log else "")
            for e in f.unexplained[:5]) + (" ..." if len(f.unexplained) > 5 else "") + ")" if f.unexplained else ""),
    ]
    if res.models is not None:
        lines += model_lines(res.models)
    rc = res.random_check
    if rc is not None:
        lines.append(f"random arrivals (a check, not a proof): {rc['draws']} draws, {rc['reproduced']} reproduced, "
                     f"fewest faults among them {'-' if rc['fewest'] is None else rc['fewest']}; "
                     f"fewer than the fewest found: {len(rc['fewer'])}"
                     + (" (the option points missed a smaller explanation)" if rc["fewer"] else ""))
    if res.slow:
        lines.append("observed slow round trips (from the log, not the fit): " + ", ".join(
            f"{s['msg']} {s['req_id']} k{s['k']} +{s['excess_us'] / 1000:.1f}ms" for s in res.slow))
    if res.outcomes:
        shown = ", ".join(f"{'+'.join(k) if k else 'no violation'} ({n})" for k, n in sorted(res.outcomes.items()))
        lines.append(f"explanations matching every receive, by violated contracts (choices tried): {shown}")
        if res.ambiguous:
            lines.append("more than one violation outcome fits the log: none is chosen")
    if res.branch_checked is not None:
        lines.append(f"attempts with a branch point: {res.branch_attempts} of {res.branch_checked} checked "
                     f"({res.branch_runs} runs" + ("; run cap reached" if res.branch_capped else "") + ")")
    return lines


__all__ = ["anomaly_windows", "BRANCH_RUNS", "DOWN", "Explanation", "FIT_RUNS", "Fit", "FitResult", "Ranges", "UP",
           "UnitSet", "Usual", "attempts_of", "device_models", "fit_log", "fit_replies", "judge_models",
           "logged_disconnects", "model_lines", "random_arrivals", "report_lines", "slow_round_trips"]
