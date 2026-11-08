"""Rewind: look at a recorded trace at a virtual time, step through it, slice it.

Everything here reads a trace file and nothing else: canonical JSON Lines,
one event per line, as written by :meth:`replayspect.trace.Trace.to_jsonl`
(``replay --trace-out`` writes one). The reader does not know which system
produced the trace, so a trace written by a log adapter can be rewound the
same way as one from the simulator.

Output is short by default. A view lists at most ``limit`` events; the full
selection goes to a file (``--full``), never to stdout, because tool output
may land in someone's context window.

Terms used below:

* **selection**: the events kept by ``--window t0 t1`` (inclusive at both
  ends) and ``--actor``. Listings, steps, divergence and the full dump use
  the selection; the state at a time is always computed from every event.
* **cursor**: rewinding to ``t`` puts the cursor after every event with
  ``t_us <= t``. Everything before the cursor has happened.
* **step**: ``n`` selected events after the cursor, or ``-n`` before it.
* **divergence**: the first position where the selected events of two traces
  differ in time, actor, kind, name, req_id or data (seq is the position).
* **judged until**: contracts are judged with an end time. Deadline contracts
  (for example "closed within 15 s") depend on it, so it is always printed.
  At a rewind time ``t`` only the events up to ``t`` are judged, with end ``t``:
  what a judge watching the run would have known at that moment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from replayspect.contract import Contract, ContractSet, EventPattern, first_violation_details, judge
from replayspect.trace import EVENT_KINDS, Event, Trace

_FIELDS = {"seq", "t_us", "actor", "kind", "name", "req_id", "data"}
_REQUIRED = ("seq", "t_us", "actor", "kind", "name")
_TIME = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(s|ms|us)?$")
_UNIT_US = {"s": 1_000_000, "ms": 1_000, "us": 1, None: 1}


class TraceFileError(ValueError):
    """A trace file that cannot be read; the message names the file and line."""


# -- reading ---------------------------------------------------------------------------------


def _check_event(d: Any, index: int, prev_t: int | None) -> Event:
    if not isinstance(d, dict):
        raise ValueError(f"expected a JSON object, got {type(d).__name__}")
    missing = [k for k in _REQUIRED if k not in d]
    if missing:
        raise ValueError(f"missing field(s) {', '.join(missing)}")
    for k in ("seq", "t_us"):
        if type(d[k]) is not int or d[k] < 0:
            raise ValueError(f"{k} must be a non-negative integer, got {d[k]!r}")
    for k in ("actor", "kind", "name"):
        if type(d[k]) is not str or not d[k]:
            raise ValueError(f"{k} must be a non-empty string, got {d[k]!r}")
    if d["kind"] not in EVENT_KINDS:
        raise ValueError(f"unknown event kind {d['kind']!r}; expected one of {sorted(EVENT_KINDS)}")
    if d.get("req_id") is not None and type(d["req_id"]) is not str:
        raise ValueError(f"req_id must be a string, got {d['req_id']!r}")
    if not isinstance(d.get("data", {}), dict):
        raise ValueError(f"data must be an object, got {type(d['data']).__name__}")
    if d["seq"] != index:
        raise ValueError(f"seq {d['seq']} out of order; expected {index}")
    if prev_t is not None and d["t_us"] < prev_t:
        raise ValueError(f"time goes backwards: {d['t_us']}us after {prev_t}us")
    return Event.from_dict(d)


def parse_trace(text: str, name: str = "<trace>") -> Trace:
    """Parse and check a trace file's text. Errors name the file and line number.

    Events must be numbered 0, 1, 2... in file order with times that never
    decrease. Blank lines are skipped. Fields other than the event fields are
    ignored, so later additions to the schema do not break the reader.
    """
    events: list[Event] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            events.append(_check_event(d, len(events), events[-1].t_us if events else None))
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            raise TraceFileError(f"{name}:{lineno}: {exc}") from None
    return Trace.from_events(events)


def read_trace(path: Path | str) -> Trace:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise TraceFileError(f"{p}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise TraceFileError(f"{p}: not UTF-8 text") from None
    return parse_trace(text, str(p))


def parse_time_us(text: str) -> int:
    """``1500000`` (microseconds), ``1500000us``, ``1500ms``, ``1.5s`` -> 1_500_000."""
    m = _TIME.match(str(text).strip())
    if not m:
        raise ValueError(f"bad time {text!r}; use microseconds (1500000) or a unit (1.5s, 1500ms, 1500000us)")
    return round(float(m.group(1)) * _UNIT_US[m.group(2)])


# -- selecting -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    window: tuple[int, int] | None = None  # inclusive at both ends
    actors: frozenset[str] = frozenset()  # empty: every actor

    def __post_init__(self) -> None:
        if self.window is not None and self.window[0] > self.window[1]:
            raise ValueError(f"window starts after it ends: {self.window[0]}us > {self.window[1]}us")

    def keeps(self, ev: Event) -> bool:
        if self.window is not None and not self.window[0] <= ev.t_us <= self.window[1]:
            return False
        return not self.actors or ev.actor in self.actors

    def apply(self, events: Iterable[Event]) -> list[Event]:
        return [e for e in events if self.keeps(e)]

    def describe(self) -> str:
        parts = []
        if self.window is not None:
            parts.append(f"window {fmt_t(self.window[0])}..{fmt_t(self.window[1])}")
        if self.actors:
            parts.append(f"actor {', '.join(sorted(self.actors))}")
        return "; ".join(parts) or "all events"


def cursor_at(trace: Trace, t_us: int) -> int:
    """Index after the last event with ``t_us <= t``."""
    events = trace.events
    lo, hi = 0, len(events)
    while lo < hi:
        mid = (lo + hi) // 2
        if events[mid].t_us <= t_us:
            lo = mid + 1
        else:
            hi = mid
    return lo


def step(trace: Trace, cursor: int, n: int, sel: Selection) -> list[Event]:
    """``n`` selected events after ``cursor`` (``n > 0``) or the ``-n`` before it, in time order."""
    events = trace.events
    if n >= 0:
        return sel.apply(events[cursor:])[:n]
    before = sel.apply(events[:cursor])
    return before[len(before) + n:]


# -- describing ------------------------------------------------------------------------------


def fmt_t(us: int) -> str:
    return f"{us / 1_000_000:.6f}s"


def event_line(ev: Event) -> str:
    """One line per event: position, time, actor, kind, name, req_id and the data that identifies it."""
    head = f"#{ev.seq} {fmt_t(ev.t_us)} {ev.actor} {ev.kind} {ev.name} {ev.req_id or '-'}"
    d = ev.data
    if not d:
        return head
    if ev.kind in ("send", "recv") and isinstance(d.get("link"), dict):
        link = d["link"]
        extra = " copy" if link.get("copy") else ""
        rest = {k: v for k, v in d.items() if k != "link"}
        return f"{head} k={link.get('k')}{extra}" + (f" {_compact(rest)}" if rest else "")
    return f"{head} {_compact(d)}"


def _compact(d: Any, limit: int = 120) -> str:
    s = json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return s if len(s) <= limit else s[: limit - 3] + "..."


def full_line(ev: Event) -> str:
    head = f"#{ev.seq} {fmt_t(ev.t_us)} {ev.actor} {ev.kind} {ev.name} {ev.req_id or '-'}"
    if not ev.data:
        return head
    return head + " " + json.dumps(ev.data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _same(a: Event, b: Event) -> bool:
    return (a.t_us, a.actor, a.kind, a.name, a.req_id, dict(a.data)) == (
        b.t_us, b.actor, b.kind, b.name, b.req_id, dict(b.data))


@dataclass(frozen=True)
class Divergence:
    index: int | None  # position in the selections; None when they are identical
    ours: Event | None
    theirs: Event | None
    compared: int


def divergence(ours: Sequence[Event], theirs: Sequence[Event]) -> Divergence:
    """First position where two event sequences differ (seq is ignored; the position is the index)."""
    for i, (a, b) in enumerate(zip(ours, theirs)):
        if not _same(a, b):
            return Divergence(i, a, b, i)
    n = min(len(ours), len(theirs))
    if len(ours) == len(theirs):
        return Divergence(None, None, None, n)
    return Divergence(n, ours[n] if n < len(ours) else None, theirs[n] if n < len(theirs) else None, n)


def divergence_lines(d: Divergence, n_ours: int, n_theirs: int) -> list[str]:
    if d.index is None:
        return [f"reference: identical ({d.compared} events)"]
    lines = [f"reference: first divergence at position {d.index} (after {d.compared} identical events)"]
    lines.append(f"  this:      {event_line(d.ours) if d.ours else f'(ends; {n_ours} events)'}")
    lines.append(f"  reference: {event_line(d.theirs) if d.theirs else f'(ends; {n_theirs} events)'}")
    return lines


@dataclass
class ContractStatus:
    end_us: int
    end_why: str  # printed next to the end time: why judging stopped there
    violated: list[Any] = field(default_factory=list)  # first violation per contract
    ok: list[str] = field(default_factory=list)
    not_exercised: list[str] = field(default_factory=list)


def trigger_patterns(c: Contract) -> set[EventPattern]:
    """The events a contract is about (not the ones it only refers to, such as ``last(...)`` or a bound)."""
    pats = {c.params[k] for k in ("event", "start", "opens") if k in c.params}
    return pats | set(c.params.get("events", ()))


def contract_status(events: Sequence[Event], cs: ContractSet, end_us: int, end_why: str) -> ContractStatus:
    """Judge ``events`` until ``end_us``.

    A contract that is not violated is ``ok`` only if one of its trigger
    events occurred; otherwise it is ``not exercised``: it could not have
    failed, which is not the same as holding.
    """
    trace = Trace.from_events(events)
    firsts = first_violation_details(judge(trace, cs, end_us))
    violated = {v.contract for v in firsts}
    st = ContractStatus(end_us, end_why, firsts)
    for c in cs.contracts:
        if c.id in violated:
            continue
        pats = trigger_patterns(c)
        exercised = any(p.matches(e) for e in events for p in pats)
        (st.ok if exercised else st.not_exercised).append(c.id)
    return st


def status_lines(st: ContractStatus, events: Sequence[Event], label: str) -> list[str]:
    lines = [f"judged until t={fmt_t(st.end_us)} ({st.end_why})"]
    for v in st.violated:
        where = f"#{v.seq} {fmt_t(events[v.seq].t_us)}" if v.seq < len(events) else "end of run"
        lines.append(f"  {v.contract} violated at {where} {v.req_id or '-'}: {v.detail}")
    lines.append(f"{label}: {len(st.violated)} violated, {len(st.ok)} ok"
                 + (f" ({', '.join(st.ok)})" if st.ok else "")
                 + (f", not exercised: {', '.join(st.not_exercised)}" if st.not_exercised else ""))
    return lines


# -- the view --------------------------------------------------------------------------------


@dataclass
class View:
    """What ``rewind`` prints. Build it with :func:`view`; ``lines`` is the output."""

    lines: list[str]
    selected: list[Event]


def _counts(events: Iterable[Event], key) -> str:
    out: dict[str, int] = {}
    for e in events:
        out[key(e)] = out.get(key(e), 0) + 1
    return ", ".join(f"{k} {v}" for k, v in sorted(out.items())) or "none"


def _listing(events: Sequence[Event], limit: int, title: str) -> list[str]:
    lines = [f"{title} ({len(events)}):"]
    lines += [f"  {event_line(e)}" for e in events[:limit]]
    if len(events) > limit:
        lines.append(f"  ... {len(events) - limit} more (raise --limit or write them with --full)")
    return lines


def _snapshot(trace: Trace, cursor: int, t_us: int, sel: Selection) -> list[str]:
    events = trace.events
    past = events[:cursor]
    lines = [f"at t={fmt_t(t_us)}: {cursor} of {len(events)} events have happened"
             + (f"; next #{events[cursor].seq} at {fmt_t(events[cursor].t_us)}" if cursor < len(events) else "; trace ends")]
    states: dict[str, Event] = {}
    last: dict[str, Event] = {}
    for e in past:
        last[e.actor] = e
        if e.kind == "state":
            states[e.actor] = e
    for actor in sorted(last):
        if sel.actors and actor not in sel.actors:
            continue
        st = states.get(actor)
        state = f"state {st.name} (since {fmt_t(st.t_us)})" if st else "no state recorded"
        lines.append(f"  {actor}: {state}; last event {event_line(last[actor])}")
    return lines


def view(
    trace: Trace,
    *,
    at_us: int | None = None,
    step_n: int | None = None,
    sel: Selection = Selection(),
    ref: Trace | None = None,
    contracts: ContractSet | None = None,
    end_us: int | None = None,
    limit: int = 50,
) -> View:
    """Build the rewind output for ``trace``. Pure: the same arguments give the same lines."""
    events = trace.events
    selected = sel.apply(events)
    lines: list[str] = []
    last_t = events[-1].t_us if events else 0
    end = end_us if end_us is not None else last_t

    if contracts is not None:
        # Always first: deadline contracts depend on the end time.
        why = "given" if end_us is not None else "last event; pass --end to change"
        st = contract_status(events, contracts, end, why)
        lines += status_lines(st, events, f"contracts ({contracts.protocol or 'unnamed'})")

    span = f"{fmt_t(events[0].t_us)}..{fmt_t(last_t)}" if events else "empty"
    lines.append(f"trace: {len(events)} events, {span}; actors: {_counts(events, lambda e: e.actor)}")
    if sel.window is not None or sel.actors:
        lines.append(f"selection ({sel.describe()}): {len(selected)} events; "
                     f"kinds: {_counts(selected, lambda e: e.kind)}")
    else:
        lines.append(f"kinds: {_counts(events, lambda e: e.kind)}")

    if ref is not None:
        theirs = sel.apply(ref.events)
        lines += divergence_lines(divergence(selected, theirs), len(selected), len(theirs))

    if at_us is not None:
        cursor = cursor_at(trace, at_us)
        lines += _snapshot(trace, cursor, at_us, sel)
        if contracts is not None:
            past = events[:cursor]
            st = contract_status(past, contracts, at_us, "the rewind time")
            lines += ["  " + line for line in status_lines(st, past, "contracts so far")]
    else:
        cursor = 0

    if step_n is not None:
        stepped = step(trace, cursor, step_n, sel)
        where = f"t={fmt_t(at_us)}" if at_us is not None else "the start"
        direction = "after" if step_n >= 0 else "before"
        lines += _listing(stepped, limit, f"step {step_n}: selected events {direction} {where}")
    elif sel.window is not None:
        lines += _listing(selected, limit, "events in the window")
    return View(lines, selected)


def write_full(events: Iterable[Event], path: Path | str) -> int:
    """Write every given event, one full line each, to a new file. Never overwrites."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("x", encoding="utf-8") as f:
        for e in events:
            f.write(full_line(e) + "\n")
            n += 1
    return n
