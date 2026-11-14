"""Rewind: look at a recorded trace at a virtual time, step through it, slice it.

Everything here reads a trace file and nothing else (docs/trace-schema.md;
``replay --trace-out`` writes one). The reader does not know which system
produced the trace, so a trace written by a log adapter can be rewound the
same way as one from the simulator. A header, when the file has one, gives
the default contract file and end time; command-line values override it and
the output says so.

Output is short by default. A view lists at most ``limit`` events; the full
selection goes to a file (``--full``, a trace file whose header records the
cut), never to stdout, because tool output may land in someone's context
window.

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
  It is ``--end``, else the header's ``until_us``, else the last event. A
  slice cut with a window is judged until the window's end when that is
  earlier than ``until_us``: events after it were cut, not missing.
  At a rewind time ``t`` only the events up to ``t`` are judged, with end ``t``:
  what a judge watching the run would have known at that moment.
* **not judged**: a slice whose window starts after time 0 may have lost
  earlier events. Contracts that cutting them can make fail
  (:func:`replayspect.contract.needs_earlier_events`) are not judged on it.
* **no violation in the slice**: on such a slice, a contract that the cut can
  only make miss a violation (:func:`replayspect.contract.misses_without_earlier_events`)
  and that has none is reported with this status, not ``ok``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from replayspect.contract import (
    Contract,
    ContractSet,
    EventPattern,
    first_violation_details,
    judge,
    load_contracts,
    misses_without_earlier_events,
    needs_earlier_events,
)
from replayspect.trace import Event, Trace
from replayspect.tracefile import (
    TraceFile,
    TraceFileError,  # noqa: F401  (re-exported: readers catch it from here)
    core_trace,
    file_sha256,
    parse_trace_file,
    read_trace_file,
    slice_header,
    write_trace_file,
)

_TIME = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(s|ms|us)?$")
_UNIT_US = {"s": 1_000_000, "ms": 1_000, "us": 1, None: 1}


# -- reading ---------------------------------------------------------------------------------


def parse_trace(text: str, name: str = "<trace>") -> Trace:
    """The events of a trace file's text (see :func:`replayspect.tracefile.parse_trace_file`)."""
    return parse_trace_file(text, name).trace


def read_trace(path: Path | str) -> Trace:
    return read_trace_file(path).trace


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
    """One line per event: position, time, actor, kind, name, req_id and the data that identifies it.

    An event a log adapter flagged ends with its log line and flags: ``[log line 4: out_of_order]``;
    a reconstructed event matched to a log line (driven replay) with ``[matches log line 4]``.
    """
    return _event_text(ev) + _flag_text(ev)


def _event_text(ev: Event) -> str:
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


def _flags(ev: Event) -> list[str]:
    return list(ev.log.get("flags", [])) if ev.log else []


def _flag_text(ev: Event) -> str:
    flags = _flags(ev)
    if flags:
        return f" [log line {ev.log['line']}: {', '.join(flags)}]"
    if ev.log and ev.fidelity == "reconstructed":  # driven replay: the log line this receive matched
        return f" [matches log line {ev.log['line']}]"
    return ""


def _compact(d: Any, limit: int = 120) -> str:
    s = json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return s if len(s) <= limit else s[: limit - 3] + "..."


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
    not_judged: list[str] = field(default_factory=list)  # needs events before ``cut_start_us``
    in_slice: list[str] = field(default_factory=list)  # no violation in the slice; earlier events not seen
    cut_start_us: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Each contract's status: violated, ok, no violation in the slice, not exercised or not judged."""
        out = {v.contract: "violated" for v in self.violated}
        out.update({c: "ok" for c in self.ok})
        out.update({c: IN_SLICE for c in self.in_slice})
        out.update({c: "not exercised" for c in self.not_exercised})
        out.update({c: "not judged" for c in self.not_judged})
        return out


IN_SLICE = "no violation in the slice"


def trigger_patterns(c: Contract) -> set[EventPattern]:
    """The events a contract is about (not the ones it only refers to, such as ``last(...)`` or a bound)."""
    pats = {c.params[k] for k in ("event", "start", "opens") if k in c.params}
    return pats | set(c.params.get("events", ()))


def contract_status(events: Sequence[Event], cs: ContractSet, end_us: int, end_why: str,
                    cut_start_us: int | None = None) -> ContractStatus:
    """Judge ``events`` until ``end_us``.

    A contract that is not violated is ``ok`` only if one of its trigger
    events occurred; otherwise it is ``not exercised``: it could not have
    failed, which is not the same as holding.

    ``cut_start_us``: the events are a slice whose window starts there, so
    earlier events may be missing. A contract that missing earlier events can
    make fail is ``not judged``; the others are judged on what is left. Of
    those, one that the cut can only make miss a violation is ``in_slice``,
    not ``ok``, when it has none: no violation in the slice, earlier events
    not seen. A cut at the window's end needs no such status: judging stops at
    the window's end, as at a rewind time, and the first line says so.
    """
    not_judged = [c.id for c in cs.contracts if cut_start_us is not None and needs_earlier_events(c)]
    judged = ContractSet(cs.protocol, cs.transitions, tuple(c for c in cs.contracts if c.id not in not_judged))
    # Judged renumbered 0, 1, 2...: a slice's seq has gaps. Violations point at
    # positions in ``events``; status_lines prints the original seq.
    firsts = first_violation_details(judge(core_trace(events), judged, end_us))
    violated = {v.contract for v in firsts}
    st = ContractStatus(end_us, end_why, firsts, not_judged=not_judged, cut_start_us=cut_start_us)
    for c in judged.contracts:
        if c.id in violated:
            continue
        pats = trigger_patterns(c)
        exercised = any(p.matches(e) for e in events for p in pats)
        if not exercised:
            st.not_exercised.append(c.id)
        elif cut_start_us is not None and misses_without_earlier_events(c):
            st.in_slice.append(c.id)
        else:
            st.ok.append(c.id)
    return st


def status_lines(st: ContractStatus, events: Sequence[Event], label: str) -> list[str]:
    lines = [f"judged until t={fmt_t(st.end_us)} ({st.end_why})"]
    for v in st.violated:
        where = f"#{events[v.seq].seq} {fmt_t(events[v.seq].t_us)}" if v.seq < len(events) else "end of run"
        lines.append(f"  {v.contract} violated at {where} {v.req_id or '-'}: {v.detail}")
    lines.append(f"{label}: {len(st.violated)} violated, {len(st.ok)} ok"
                 + (f" ({', '.join(st.ok)})" if st.ok else "")
                 + (f", {IN_SLICE} (earlier events not seen): {', '.join(st.in_slice)}" if st.in_slice else "")
                 + (f", not exercised: {', '.join(st.not_exercised)}" if st.not_exercised else "")
                 + (f", not judged: {', '.join(st.not_judged)} (the slice starts at t={fmt_t(st.cut_start_us)}; "
                    "earlier events may be cut)" if st.not_judged else ""))
    return lines


# -- judging defaults from the header -------------------------------------------------------


@dataclass
class JudgeSetup:
    """What to judge with: the contracts, the end time and why, and lines saying where they came from."""

    contracts: ContractSet | None = None
    end_us: int | None = None  # None: the last event
    end_why: str | None = None
    notes: list[str] = field(default_factory=list)
    cut_start_us: int | None = None  # a slice whose window starts after 0: earlier events may be cut


def judge_setup(tf: TraceFile, contracts_path: str | None = None, end_us: int | None = None) -> JudgeSetup:
    """Command-line values first, then the header's; say which, and when they differ from the header."""
    h = tf.header
    st = JudgeSetup()
    hc = h.contracts if h is not None else None
    if contracts_path is not None:
        st.contracts = load_contracts(Path(contracts_path))
        if hc is None:
            pass
        elif file_sha256(contracts_path) == hc["sha256"]:
            st.notes.append(f"contracts file: {contracts_path} (given; same file as the header's)")
        else:
            st.notes.append(f"contracts file: {contracts_path} (given; differs from header: {hc['path']})")
    elif hc is not None:
        p = Path(hc["path"])
        if not p.is_file():
            st.notes.append(f"contracts file: {hc['path']} (from header) not found; not judged; pass --contracts")
        else:
            st.contracts = load_contracts(p)
            now = file_sha256(p)
            if now == hc["sha256"]:
                st.notes.append(f"contracts file: {hc['path']} (from header)")
            else:
                st.notes.append(f"contracts file: {hc['path']} (from header; changed since the trace was "
                                f"written: sha256 {hc['sha256'][:12]} in header, {now[:12]} now)")
    until = h.until_us if h is not None else None
    window = h.slice.window if h is not None and h.slice is not None else None
    if window is not None and window[0] > 0:
        st.cut_start_us = window[0]
    if end_us is not None:
        if st.contracts is None:
            raise ValueError("--end is the end time for judging; it needs contracts (--contracts or the trace header)")
        st.end_us = end_us
        if until is None:
            st.end_why = "given"
        elif until == end_us:
            st.end_why = "given; same as header"
        else:
            st.end_why = f"given; differs from header: {fmt_t(until)}"
    elif until is not None:
        st.end_us, st.end_why = until, "header until_us"
        if window is not None and window[1] < until:  # events after the window were cut, not missing
            st.end_us, st.end_why = window[1], f"slice window end; the run went on to {fmt_t(until)}"
    return st


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
    end_why: str | None = None,
    notes: Sequence[str] = (),
    limit: int = 50,
    cut_start_us: int | None = None,
) -> View:
    """Build the rewind output for ``trace``. Pure: the same arguments give the same lines.

    ``notes`` (where the contracts came from) follow the contract status.
    ``cut_start_us``: the trace is a slice whose window starts there (see :func:`contract_status`).
    """
    events = trace.events
    selected = sel.apply(events)
    lines: list[str] = []
    last_t = events[-1].t_us if events else 0
    end = end_us if end_us is not None else last_t

    if contracts is not None:
        # Always first: deadline contracts depend on the end time.
        why = end_why or ("given" if end_us is not None else "last event; pass --end to change")
        st = contract_status(events, contracts, end, why, cut_start_us)
        lines += status_lines(st, events, f"contracts ({contracts.protocol or 'unnamed'})")
    lines += notes

    span = f"{fmt_t(events[0].t_us)}..{fmt_t(last_t)}" if events else "empty"
    lines.append(f"trace: {len(events)} events, {span}; actors: {_counts(events, lambda e: e.actor)}")
    if sel.window is not None or sel.actors:
        lines.append(f"selection ({sel.describe()}): {len(selected)} events; "
                     f"kinds: {_counts(selected, lambda e: e.kind)}")
    else:
        lines.append(f"kinds: {_counts(events, lambda e: e.kind)}")
    flagged = [(f, e) for e in events for f in _flags(e)]
    if flagged:
        lines.append(f"flagged by the log adapter: {_counts(flagged, lambda fe: fe[0])} "
                     "(times as logged; see docs/trace-schema.md)")

    if ref is not None:
        theirs = sel.apply(ref.events)
        lines += divergence_lines(divergence(selected, theirs), len(selected), len(theirs))

    if at_us is not None:
        cursor = cursor_at(trace, at_us)
        lines += _snapshot(trace, cursor, at_us, sel)
        if contracts is not None:
            past = events[:cursor]
            st = contract_status(past, contracts, at_us, "the rewind time", cut_start_us)
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


def write_full(tf: TraceFile, sel: Selection, path: Path | str) -> int:
    """Write the selected events of ``tf`` as a trace file to a new path. Never overwrites.

    The file reads back like any trace file. Its header is ``tf``'s with
    ``slice`` set to the selection and the digest of the full trace.
    """
    header = slice_header(tf, sel.window, sorted(sel.actors))
    return write_trace_file(path, sel.apply(tf.trace.events), header)
