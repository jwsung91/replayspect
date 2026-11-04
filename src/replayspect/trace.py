"""Execution trace: the single source of truth that contracts are judged on.

Every observable thing in a run is recorded as an :class:`Event`: messages
sent and received, messages a client actually handled, physical effects,
state changes, and injected faults. The checker never looks inside the
simulator; it only reads the trace.

A trace serialises to canonical JSON Lines (sorted keys, no extra whitespace)
so that its SHA-256 digest is stable across processes and machines. If a
replayed run produces a different digest, determinism is broken, and that is
treated as a bug in itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Mapping

#: The only event kinds a trace may contain.
#: ``recv`` (a message arrived) and ``handle`` (the client acted on it) are
#: separate on purpose: some contracts allow receiving a late reply but forbid
#: treating it as a completion.
EVENT_KINDS = frozenset({"send", "recv", "handle", "effect", "state", "fault"})


class TraceError(ValueError):
    """Raised when an event is malformed."""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class Event:
    seq: int
    t_us: int
    actor: str
    kind: str
    name: str
    req_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "seq": self.seq,
            "t_us": self.t_us,
            "actor": self.actor,
            "kind": self.kind,
            "name": self.name,
        }
        if self.req_id is not None:
            d["req_id"] = self.req_id
        if self.data:
            d["data"] = dict(self.data)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Event":
        return cls(
            seq=d["seq"],
            t_us=d["t_us"],
            actor=d["actor"],
            kind=d["kind"],
            name=d["name"],
            req_id=d.get("req_id"),
            data=d.get("data", {}),
        )


class Trace:
    """Append-only, time-ordered list of events."""

    def __init__(self, clock_us: Callable[[], int]) -> None:
        self._clock_us = clock_us
        self._events: list[Event] = []

    def record(
        self,
        actor: str,
        kind: str,
        name: str,
        req_id: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Event:
        """Append an event stamped with the current virtual time.

        ``data`` is a single mapping rather than keyword arguments, so its
        keys can never collide with the parameters (``name``, ``req_id``...),
        and ``req_id=...`` passed by keyword always lands in ``req_id``.

        ``data`` is stored as a snapshot of its JSON form: a deep copy in
        which tuples become lists. Mutating the caller's objects afterwards
        cannot change a recorded event.
        """
        data = {} if data is None else data
        if kind not in EVENT_KINDS:
            raise TraceError(f"unknown event kind {kind!r}; expected one of {sorted(EVENT_KINDS)}")
        try:
            snapshot = json.loads(_canonical(data))
        except (TypeError, ValueError) as exc:
            raise TraceError(f"event data must be JSON-serialisable: {exc}") from exc
        t_us = self._clock_us()
        if self._events and t_us < self._events[-1].t_us:
            raise TraceError(f"time went backwards: {t_us}us after {self._events[-1].t_us}us")
        ev = Event(len(self._events), t_us, actor, kind, name, req_id, snapshot)
        self._events.append(ev)
        return ev

    # -- reading ----------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    def __getitem__(self, seq: int) -> Event:
        return self._events[seq]

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    # -- serialisation ------------------------------------------------------------

    def to_jsonl(self) -> str:
        return "".join(_canonical(e.to_dict()) + "\n" for e in self._events)

    def digest(self) -> str:
        """SHA-256 of the canonical JSONL form."""
        return hashlib.sha256(self.to_jsonl().encode("utf-8")).hexdigest()

    @classmethod
    def from_events(cls, events: Iterable[Event]) -> "Trace":
        evs = list(events)
        tr = cls(clock_us=lambda: evs[-1].t_us if evs else 0)
        tr._events = evs
        return tr

    @classmethod
    def from_jsonl(cls, text: str) -> "Trace":
        return cls.from_events(
            Event.from_dict(json.loads(line)) for line in text.splitlines() if line.strip()
        )
