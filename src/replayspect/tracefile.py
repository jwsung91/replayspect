"""Trace files: the format every reader and writer shares (docs/trace-schema.md).

A trace file is UTF-8 JSON Lines: an optional header line, then one event
per line. The simulator (``replay --trace-out``), slices (``rewind --full``)
and, later, log adapters write it; ``rewind`` and the judge read only this.

* **Header** (optional, first line): ``{"type": "header", "schema":
  "replayspect.trace/1", ...}``. It records where the trace came from and
  gives ``rewind`` its default contract file and end time. Files without one
  read as before.
* **Events**: the event core (``seq, t_us, actor, kind, name, req_id,
  data``) plus ``fidelity`` and ``source``. The digest covers the core only.
* **Slices**: a file cut from another trace keeps the original ``seq``
  numbers and says in its header how it was cut (``slice``).

Reading checks every line and names the file and line number on the first
problem. Unknown fields are ignored, so optional additions to the schema do
not break older readers; an unknown schema major is rejected.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

from replayspect.trace import EVENT_KINDS, FIDELITIES, Event, Trace

SCHEMA = "replayspect.trace/1"
_SCHEMA_RE = re.compile(r"^replayspect\.trace/([0-9]+)$")
_SOURCE_RE = re.compile(r"^(sim|adapter:\S+)$")
_REQUIRED = ("seq", "t_us", "actor", "kind", "name")


class TraceFileError(ValueError):
    """A trace file that cannot be read; the message names the file and line."""


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# -- the header ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Slice:
    """How a slice was cut: the selection, and the digest of the trace it was cut from."""

    window: tuple[int, int] | None  # inclusive at both ends
    actors: tuple[str, ...] | None  # sorted
    of: str | None  # digest of the full trace; None in output meant for planners (WP4)

    def to_dict(self) -> dict[str, Any]:
        return {"window": list(self.window) if self.window is not None else None,
                "actors": list(self.actors) if self.actors is not None else None,
                "of": self.of}


@dataclass(frozen=True)
class Header:
    system: str | None = None
    source: str = "sim"
    seed: int | None = None
    plan: dict[str, Any] | None = None  # {"sha256": ..., "repro": path or None}
    contracts: dict[str, Any] | None = None  # {"path": ..., "sha256": ...}
    until_us: int | None = None
    slice: Slice | None = None
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "header",
            "schema": self.schema,
            "system": self.system,
            "source": self.source,
            "seed": self.seed,
            "plan": self.plan,
            "contracts": self.contracts,
            "until_us": self.until_us,
            "slice": self.slice.to_dict() if self.slice is not None else None,
        }


def _opt(d: dict, key: str, kind: type, what: str) -> Any:
    v = d.get(key)
    if v is not None and type(v) is not kind:
        raise ValueError(f"header {key} must be {what} or null, got {v!r}")
    return v


def _nonneg(v: Any, what: str) -> int:
    if type(v) is not int or v < 0:
        raise ValueError(f"{what} must be a non-negative integer, got {v!r}")
    return v


def _check_header(d: dict) -> Header:
    schema = d.get("schema")
    m = _SCHEMA_RE.match(schema) if isinstance(schema, str) else None
    if not m:
        raise ValueError(f"header schema must look like {SCHEMA!r}, got {schema!r}")
    if m.group(1) != "1":
        raise ValueError(f"schema {schema} is not supported; this reader knows {SCHEMA}")
    source = d.get("source", "sim")
    if not isinstance(source, str) or not _SOURCE_RE.match(source):
        raise ValueError(f"header source must be 'sim' or 'adapter:<name>', got {source!r}")
    system = _opt(d, "system", str, "a string")
    seed = d.get("seed")
    if seed is not None:
        _nonneg(seed, "header seed")
    until = d.get("until_us")
    if until is not None:
        _nonneg(until, "header until_us")
    plan = _opt(d, "plan", dict, "an object")
    if plan is not None:
        if not isinstance(plan.get("sha256"), str):
            raise ValueError("header plan needs a sha256 string")
        if plan.get("repro") is not None and not isinstance(plan["repro"], str):
            raise ValueError("header plan repro must be a string or null")
    contracts = _opt(d, "contracts", dict, "an object")
    if contracts is not None:
        for k in ("path", "sha256"):
            if not isinstance(contracts.get(k), str) or not contracts[k]:
                raise ValueError(f"header contracts needs a non-empty {k} string")
    sl = _opt(d, "slice", dict, "an object")
    return Header(system, source, seed, plan, contracts, until, _check_slice(sl) if sl is not None else None, schema)


def _check_slice(d: dict) -> Slice:
    w = d.get("window")
    window = None
    if w is not None:
        if not isinstance(w, list) or len(w) != 2:
            raise ValueError(f"header slice window must be [t0, t1] or null, got {w!r}")
        window = (_nonneg(w[0], "slice window start"), _nonneg(w[1], "slice window end"))
        if window[0] > window[1]:
            raise ValueError(f"header slice window starts after it ends: {w!r}")
    a = d.get("actors")
    actors = None
    if a is not None:
        if not isinstance(a, list) or not all(isinstance(x, str) and x for x in a):
            raise ValueError(f"header slice actors must be a list of names or null, got {a!r}")
        actors = tuple(sorted(set(a)))
    of = d.get("of")
    if of is not None and not isinstance(of, str):
        raise ValueError(f"header slice of must be a digest string or null, got {of!r}")
    return Slice(window, actors, of)


# -- events ----------------------------------------------------------------------------------


def _check_event(d: dict, prev: Event | None, index: int, sliced: bool, default_source: str) -> Event:
    missing = [k for k in _REQUIRED if k not in d]
    if missing:
        raise ValueError(f"missing field(s) {', '.join(missing)}")
    for k in ("seq", "t_us"):
        _nonneg(d[k], k)
    for k in ("actor", "kind", "name"):
        if type(d[k]) is not str or not d[k]:
            raise ValueError(f"{k} must be a non-empty string, got {d[k]!r}")
    if d["kind"] not in EVENT_KINDS:
        raise ValueError(f"unknown event kind {d['kind']!r}; expected one of {sorted(EVENT_KINDS)}")
    if d.get("req_id") is not None and type(d["req_id"]) is not str:
        raise ValueError(f"req_id must be a string, got {d['req_id']!r}")
    if not isinstance(d.get("data", {}), dict):
        raise ValueError(f"data must be an object, got {type(d['data']).__name__}")
    fidelity = d.get("fidelity", "exact")
    if fidelity not in FIDELITIES:
        raise ValueError(f"fidelity must be one of {', '.join(FIDELITIES)}, got {fidelity!r}")
    source = d.get("source", default_source)
    if not isinstance(source, str) or not _SOURCE_RE.match(source):
        raise ValueError(f"source must be 'sim' or 'adapter:<name>', got {source!r}")
    if sliced:
        if prev is not None and d["seq"] <= prev.seq:
            raise ValueError(f"seq {d['seq']} out of order; a slice's seq must increase (previous {prev.seq})")
    elif d["seq"] != index:
        raise ValueError(f"seq {d['seq']} out of order; expected {index}")
    if prev is not None and d["t_us"] < prev.t_us:
        raise ValueError(f"time goes backwards: {d['t_us']}us after {prev.t_us}us")
    return Event.from_dict({**d, "fidelity": fidelity, "source": source})


# -- reading ---------------------------------------------------------------------------------


@dataclass
class TraceFile:
    """A read trace file: the header (None when the file has none) and the events."""

    header: Header | None
    trace: Trace
    name: str = "<trace>"

    @property
    def is_slice(self) -> bool:
        return self.header is not None and self.header.slice is not None


def parse_trace_file(text: str, name: str = "<trace>") -> TraceFile:
    """Parse and check a trace file's text. Errors name the file and line number.

    Events must be numbered 0, 1, 2... in file order (a slice: increasing) with
    times that never decrease. Blank lines are skipped.
    """
    header: Header | None = None
    header_line = 0
    events: list[Event] = []
    first = True
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if not isinstance(d, dict):
                raise ValueError(f"expected a JSON object, got {type(d).__name__}")
            if "type" in d:
                if not first:
                    raise ValueError("a header (a line with 'type') may only be the first line")
                if d["type"] != "header":
                    raise ValueError(f"unknown line type {d['type']!r}; the only one is 'header'")
                header, header_line = _check_header(d), lineno
            else:
                sliced = header is not None and header.slice is not None
                src = header.source if header is not None else "sim"
                events.append(_check_event(d, events[-1] if events else None, len(events), sliced, src))
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            raise TraceFileError(f"{name}:{lineno}: {exc}") from None
        first = False
    if header is not None and header.until_us is not None and events and header.until_us < events[-1].t_us:
        raise TraceFileError(f"{name}:{header_line}: header until_us {header.until_us} is before "
                             f"the last event ({events[-1].t_us}us)")
    return TraceFile(header, Trace.from_events(events), name)


def read_trace_file(path: Path | str) -> TraceFile:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise TraceFileError(f"{p}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise TraceFileError(f"{p}: not UTF-8 text") from None
    return parse_trace_file(text, str(p))


# -- writing ---------------------------------------------------------------------------------


def trace_file_text(events: Iterable[Event], header: Header | None) -> str:
    lines = [canonical(header.to_dict())] if header is not None else []
    lines += [canonical(e.to_record()) for e in events]
    return "".join(line + "\n" for line in lines)


def write_trace_file(path: Path | str, events: Iterable[Event], header: Header | None) -> int:
    """Write a trace file to a new path (never overwrites). Returns the number of events."""
    evs = list(events)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("x", encoding="utf-8") as f:
        f.write(trace_file_text(evs, header))
    return len(evs)


def contracts_ref(path: Path | str) -> dict[str, str]:
    """``{"path", "sha256"}`` for a header. The path is relative to the working directory when under it."""
    p = Path(path)
    try:
        shown = str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        shown = str(p.resolve())
    return {"path": shown, "sha256": file_sha256(p)}


def plan_ref(plan_dict: dict[str, Any], repro: Path | str | None) -> dict[str, Any]:
    return {"sha256": sha256_text(canonical(plan_dict)), "repro": str(repro) if repro is not None else None}


def slice_header(tf: TraceFile, window: tuple[int, int] | None, actors: Sequence[str]) -> Header:
    """The header for a slice of ``tf`` cut by ``window`` and ``actors``.

    Everything but ``slice`` is copied from ``tf``'s header. Cutting a slice
    again narrows the recorded selection and keeps ``of``: the full trace.
    """
    base = tf.header or Header()
    acts = tuple(sorted(set(actors))) or None
    prev = base.slice
    if prev is None:
        of = tf.trace.digest()
    else:
        of = prev.of
        if prev.window is not None:
            if window is None:
                window = prev.window
            else:
                window = (max(window[0], prev.window[0]), min(window[1], prev.window[1]))
                if window[0] > window[1]:
                    raise ValueError("--window does not overlap the window this slice was cut with")
        if prev.actors is not None:
            if acts is None:
                acts = prev.actors
            else:
                acts = tuple(a for a in acts if a in prev.actors)
                if not acts:
                    raise ValueError("--actor names none of the actors this slice was cut with")
    return replace(base, slice=Slice(window, acts, of))


def core_trace(events: Sequence[Event]) -> Trace:
    """``events`` renumbered 0, 1, 2...: what the judge needs (a slice's seq has gaps)."""
    return Trace.from_events([replace(e, seq=i) for i, e in enumerate(events)])


__all__ = [
    "SCHEMA", "Header", "Slice", "TraceFile", "TraceFileError", "canonical", "contracts_ref", "core_trace",
    "file_sha256", "parse_trace_file", "plan_ref", "read_trace_file", "sha256_text", "slice_header",
    "trace_file_text", "write_trace_file",
]
