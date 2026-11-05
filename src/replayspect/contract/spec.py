"""Contract files: loading, event patterns and the tiny expression language.

A contract file is YAML with a protocol section and a list of contracts::

    protocol: lift.v0
    transitions:            # [from, on, to]; from is null for the initial state
      - [null, init, DOWN]
      - [DOWN, MOVE_UP, MOVING_UP]
    contracts:
      - id: C1
        desc: ...
        kind: at_most_once
        per: req_id
        event: device.effect(motor_start)

Transitions are written as triples, not mappings, on purpose: YAML 1.1
(which PyYAML implements) reads an unquoted ``on`` key as the boolean
``True``. The loader also rejects any value that is not a plain string
where a name is expected, which catches ``yes``/``no``/``on``/``off`` used
as state or message names.

**Event pattern**: ``actor.kind`` or ``actor.kind(NAME|NAME...)``, for
example ``client.send(MOVE_UP|MOVE_DOWN)`` or ``device.state``.

**Operand**: ``req_id``, ``name``, ``actor``, ``kind``, ``t_us``,
``data.<field>[.<field>...]``, a literal (``'text'``, ``"text"``, an
integer, ``null``), or ``last(<pattern>).<operand>``, which reads the most
recent earlier event matching the pattern (``null`` if there is none).

**Condition**: ``<operand> == <operand>`` or ``<operand> != <operand>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from replayspect.trace import EVENT_KINDS, Event

KINDS = (
    "at_most_once",
    "exactly_once",
    "state_machine",
    "forbid",
    "consistent",
    "at_most_one_open",
    "count_le",
    "mutually_exclusive",
)


class ContractError(ValueError):
    """Raised for a malformed contract file."""


# -- event patterns -------------------------------------------------------------------

_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.([a-z]+)(?:\(([A-Za-z0-9_]+(?:\|[A-Za-z0-9_]+)*)\))?$")


@dataclass(frozen=True)
class EventPattern:
    actor: str
    kind: str
    names: frozenset[str] | None  # None matches any name

    @classmethod
    def parse(cls, text: str) -> "EventPattern":
        if not isinstance(text, str):
            raise ContractError(f"event pattern must be a string, got {text!r}")
        m = _PATTERN.match(text.strip())
        if not m:
            raise ContractError(f"bad event pattern {text!r}; expected actor.kind or actor.kind(NAME|NAME)")
        actor, kind, names = m.groups()
        if kind not in EVENT_KINDS:
            raise ContractError(f"unknown event kind {kind!r} in {text!r}")
        return cls(actor, kind, frozenset(names.split("|")) if names else None)

    def matches(self, ev: Event) -> bool:
        return (
            ev.actor == self.actor
            and ev.kind == self.kind
            and (self.names is None or ev.name in self.names)
        )

    def __str__(self) -> str:
        names = f"({'|'.join(sorted(self.names))})" if self.names else ""
        return f"{self.actor}.{self.kind}{names}"


# -- operands and conditions -----------------------------------------------------------

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LAST = re.compile(r"^last\((.+?)\)\.(.+)$")
_FIELDS = ("req_id", "name", "actor", "kind", "t_us")


@dataclass(frozen=True)
class Operand:
    """One side of a condition. ``source`` is 'event', 'last' or 'literal'."""

    source: str
    path: tuple[str, ...] = ()
    pattern: EventPattern | None = None
    value: Any = None

    @classmethod
    def parse(cls, text: str) -> "Operand":
        t = text.strip()
        if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
            return cls("literal", value=t[1:-1])
        if t == "null":
            return cls("literal", value=None)
        if re.fullmatch(r"-?[0-9]+", t):
            return cls("literal", value=int(t))
        m = _LAST.match(t)
        if m:
            inner = cls.parse(m.group(2))
            if inner.source != "event":
                raise ContractError(f"last(...) must be followed by an event field, got {t!r}")
            return cls("last", inner.path, EventPattern.parse(m.group(1)))
        return cls("event", _parse_path(t))

    def evaluate(self, ev: Event, last: Mapping[EventPattern, Event]) -> Any:
        if self.source == "literal":
            return self.value
        target = ev if self.source == "event" else last.get(self.pattern)  # type: ignore[arg-type]
        if target is None:
            return None
        return _lookup(target, self.path)


def _parse_path(t: str) -> tuple[str, ...]:
    parts = tuple(t.split("."))
    if not all(_IDENT.match(p) for p in parts):
        raise ContractError(f"bad operand {t!r}")
    if parts[0] == "data":
        if len(parts) < 2:
            raise ContractError(f"operand {t!r} needs a field after data.")
        return parts
    if len(parts) != 1 or parts[0] not in _FIELDS:
        raise ContractError(f"unknown operand {t!r}; use {', '.join(_FIELDS)} or data.<field>")
    return parts


def _lookup(ev: Event, path: tuple[str, ...]) -> Any:
    if path[0] != "data":
        return getattr(ev, path[0])
    value: Any = ev.data
    for p in path[1:]:
        if not isinstance(value, Mapping) or p not in value:
            return None
        value = value[p]
    return value


@dataclass(frozen=True)
class Condition:
    left: Operand
    op: str
    right: Operand

    @classmethod
    def parse(cls, text: str) -> "Condition":
        if not isinstance(text, str):
            raise ContractError(f"condition must be a string, got {text!r}")
        for op in ("==", "!="):
            if text.count(op) == 1:
                left, right = text.split(op)
                return cls(Operand.parse(left), op, Operand.parse(right))
        raise ContractError(f"bad condition {text!r}; expected '<operand> == <operand>' or '!='")

    def holds(self, ev: Event, last: Mapping[EventPattern, Event]) -> bool:
        a, b = self.left.evaluate(ev, last), self.right.evaluate(ev, last)
        return (a == b) if self.op == "==" else (a != b)

    def last_patterns(self) -> set[EventPattern]:
        return {o.pattern for o in (self.left, self.right) if o.pattern is not None}


# -- contracts -------------------------------------------------------------------------

_DURATION = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(s|ms|us)$")
_UNIT_US = {"s": 1_000_000, "ms": 1_000, "us": 1}


def parse_duration_us(text: Any) -> int:
    m = _DURATION.match(str(text).strip())
    if not m:
        raise ContractError(f"bad duration {text!r}; use e.g. 15s, 500ms, 20us")
    return round(float(m.group(1)) * _UNIT_US[m.group(2)])


@dataclass(frozen=True)
class Contract:
    id: str
    kind: str
    desc: str
    params: Mapping[str, Any]


_REQUIRED = {
    "at_most_once": {"per", "event"},
    "exactly_once": {"per", "start", "event", "within"},
    "state_machine": {"event"},
    "forbid": {"event", "when"},
    "consistent": {"event", "field", "equals"},
    "at_most_one_open": {"per", "opens", "closes"},
    "count_le": {"per", "event", "bound"},
    "mutually_exclusive": {"per", "events"},
}
_COMMON = {"id", "kind", "desc"}


def _contract(raw: Mapping[str, Any]) -> Contract:
    if not isinstance(raw, Mapping):
        raise ContractError(f"each contract must be a mapping, got {raw!r}")
    cid, kind = raw.get("id"), raw.get("kind")
    if not isinstance(cid, str) or not cid:
        raise ContractError(f"contract without a string id: {raw!r}")
    if kind not in KINDS:
        raise ContractError(f"{cid}: unknown kind {kind!r}; expected one of {KINDS}")
    keys = set(raw)
    missing = _REQUIRED[kind] - keys
    extra = keys - _REQUIRED[kind] - _COMMON
    if missing:
        raise ContractError(f"{cid}: missing {sorted(missing)} for kind {kind}")
    if extra:
        raise ContractError(f"{cid}: unexpected {sorted(extra)} for kind {kind}")
    if "per" in raw and raw["per"] != "req_id":
        raise ContractError(f"{cid}: only per: req_id is supported in v0")

    p: dict[str, Any] = {}
    try:
        for key in ("event", "start", "opens", "closes", "bound"):
            if key in raw:
                p[key] = EventPattern.parse(raw[key])
        if "events" in raw:
            if not isinstance(raw["events"], list) or len(raw["events"]) < 2:
                raise ContractError(f"{cid}: events needs a list of at least two patterns")
            p["events"] = tuple(EventPattern.parse(x) for x in raw["events"])
        if "within" in raw:
            p["within_us"] = parse_duration_us(raw["within"])
        if "when" in raw:
            p["when"] = Condition.parse(raw["when"])
        if "field" in raw:
            p["field"] = Operand.parse(raw["field"])
            p["equals"] = Operand.parse(raw["equals"])
    except ContractError as exc:
        raise ContractError(f"{cid}: {exc}") from None
    return Contract(cid, kind, str(raw.get("desc", "")), p)


@dataclass(frozen=True)
class ContractSet:
    protocol: str
    transitions: frozenset[tuple[str | None, str, str]]
    contracts: tuple[Contract, ...]

    def ids(self) -> list[str]:
        return [c.id for c in self.contracts]


def _name(value: Any, where: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str:
        raise ContractError(
            f"{where}: expected a plain string, got {value!r}"
            " (YAML reads unquoted yes/no/on/off as booleans; quote them)"
        )
    return value


def load_contracts(source: Path | str | Mapping[str, Any]) -> ContractSet:
    """Load a contract set.

    ``source`` is a :class:`~pathlib.Path` to a YAML file, a ``str`` of YAML
    text, or an already-parsed mapping.
    """
    if isinstance(source, Path):
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    elif isinstance(source, str):
        raw = yaml.safe_load(source)
    else:
        raw = source
    if not isinstance(raw, Mapping):
        raise ContractError("contract file must be a mapping")
    protocol = _name(raw.get("protocol"), "protocol", allow_none=True) or ""
    transitions = set()
    for i, t in enumerate(raw.get("transitions") or []):
        if not isinstance(t, list) or len(t) != 3:
            raise ContractError(f"transitions[{i}] must be [from, on, to], got {t!r}")
        transitions.add((
            _name(t[0], f"transitions[{i}].from", allow_none=True),
            _name(t[1], f"transitions[{i}].on"),
            _name(t[2], f"transitions[{i}].to"),
        ))
    items = raw.get("contracts")
    if not isinstance(items, list) or not items:
        raise ContractError("contracts must be a non-empty list")
    contracts = tuple(_contract(c) for c in items)
    ids = [c.id for c in contracts]
    if len(ids) != len(set(ids)):
        raise ContractError(f"duplicate contract ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    if any(c.kind == "state_machine" for c in contracts) and not transitions:
        raise ContractError("a state_machine contract needs a transitions list")
    return ContractSet(protocol, frozenset(transitions), contracts)  # type: ignore[arg-type]
