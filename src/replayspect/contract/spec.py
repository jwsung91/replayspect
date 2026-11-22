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

**Provenance** (optional, any kind; not used in judging): ``grade`` (one of
:data:`GRADES`; ``stated``: the protocol document says it) and ``source``, a
mapping of ``doc`` (the document), ``lines`` (its line numbers), ``quote``
(the sentence) and ``found`` (how the rule was found), each a non-empty
string. A ``generic`` contract (a rule that does not depend on the protocol,
written for it) must have a source, and its source holds ``rule`` (the rule's
id, such as ``G1``) and optionally ``quote`` (the rule in words), nothing else.

**Roles** (the generic rules, ``contracts/generic/``): a file with ``roles`` instead of ``contracts``
binds one protocol's names to roles and names a rules file (``rules``, relative to the binding file; to
the current directory when the binding is given as text or a mapping)::

    protocol: lift.v0
    rules: rules.yaml
    roles:
      requests: [MOVE_UP, MOVE_DOWN]      # a name, a list of names or a mapping of name -> name
      polls: {STATUS: STATUS_REPLY}

Each rule of the rules file (``rule``, optional ``quote``, optional ``each``, ``contract``) is expanded
into a contract of an existing kind with ``grade: generic`` and ``source: {rule, quote}``. In the
contract's strings ``{role}`` becomes the role's names joined with ``|`` and ``{role.key}`` one entry of
a mapping role; ``each: <role>`` (a list or mapping role) writes one contract per name, as ``{each}``
(for a mapping, the key) and ``{each.value}``. A ``{`` or ``}`` left in any string after expansion is
refused. The judge sees only the expanded contracts; :func:`rules_file` names a binding's rules file, so a
report can record it beside the binding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
    "only_after",
    "never_after",
)
#: stated: the protocol document says it; generic: a rule that does not depend on the protocol, written for it
GRADES = ("stated", "generic")
SOURCE_KEYS = ("doc", "lines", "quote", "found")
#: A generic contract's source names its rule (an id such as G1) and may quote the rule in words, nothing else.
GENERIC_SOURCE_KEYS = ("rule", "quote")


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
    def parse(cls, text: Any) -> "Operand":
        # YAML may already have turned `null` or `42` into Python values.
        if text is None:
            return cls("literal", value=None)
        if type(text) is int:
            return cls("literal", value=text)
        if type(text) is not str:
            raise ContractError(f"operand must be a string, null or an integer, got {text!r}")
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


def _operators_outside_quotes(text: str) -> list[tuple[int, str]]:
    """Positions of ``==`` and ``!=`` that are not inside a quoted literal."""
    out: list[tuple[int, str]] = []
    quote: str | None = None
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif text[i:i + 2] in ("==", "!="):
            out.append((i, text[i:i + 2]))
            i += 2
            continue
        i += 1
    return out


@dataclass(frozen=True)
class Condition:
    left: Operand
    op: str
    right: Operand
    #: The condition as written in the contract file; violation details quote it.
    text: str = field(default="", compare=False, repr=False)

    def __str__(self) -> str:
        return self.text or f"{self.left} {self.op} {self.right}"

    @classmethod
    def parse(cls, text: str) -> "Condition":
        if not isinstance(text, str):
            raise ContractError(f"condition must be a string, got {text!r}")
        found = _operators_outside_quotes(text)
        if len(found) != 1:
            raise ContractError(f"bad condition {text!r}; expected '<operand> == <operand>' or '!='")
        i, op = found[0]
        return cls(Operand.parse(text[:i]), op, Operand.parse(text[i + 2:]), " ".join(text.split()))

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
    grade: str | None = None  # provenance, not used in judging
    source: Mapping[str, str] | None = None


_REQUIRED = {
    "at_most_once": {"per", "event"},
    "exactly_once": {"per", "start", "event", "within"},
    "state_machine": {"event"},
    "forbid": {"event", "when"},
    "consistent": {"event", "field", "equals"},
    "at_most_one_open": {"per", "opens", "closes"},
    "count_le": {"per", "event", "bound"},
    "mutually_exclusive": {"per", "events"},
    "only_after": {"per", "event", "after"},
    "never_after": {"per", "event", "after"},
}
_COMMON = {"id", "kind", "desc", "grade", "source"}


def _provenance(cid: str, raw: Mapping[str, Any]) -> tuple[str | None, Mapping[str, str] | None]:
    grade, source = raw.get("grade"), raw.get("source")
    if "grade" in raw and grade not in GRADES:
        raise ContractError(f"{cid}: grade must be one of {GRADES}, got {grade!r}")
    generic = grade == "generic"
    if generic and not (isinstance(source, Mapping) and "rule" in source):
        raise ContractError(f"{cid}: a generic contract needs a source with its rule ({', '.join(GENERIC_SOURCE_KEYS)})")
    if "source" in raw:
        if not isinstance(source, Mapping) or not source:
            raise ContractError(f"{cid}: source must be a non-empty mapping of {', '.join(SOURCE_KEYS)}")
        allowed = GENERIC_SOURCE_KEYS if generic else SOURCE_KEYS
        extra = set(source) - set(allowed)
        if extra:
            raise ContractError(f"{cid}: unexpected {sorted(map(str, extra))} in source; "
                                + (f"a generic source has {', '.join(allowed)}" if generic else f"use {', '.join(allowed)}"))
        bad = [k for k, v in source.items() if type(v) is not str or not v.strip()]
        if bad:
            raise ContractError(f"{cid}: source {', '.join(bad)} must be a non-empty string (quote line ranges)")
        source = dict(source)
    return grade, source


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
        for key in ("event", "start", "opens", "closes", "bound", "after"):
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
    if "after" in p and p["after"] == p["event"]:
        raise ContractError(f"{cid}: event and after are the same pattern ({p['event']})")
    grade, source = _provenance(cid, raw)
    return Contract(cid, kind, str(raw.get("desc", "")), p, grade, source)


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


_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_SLOT = re.compile(r"\{([a-z_]+)(?:\.([a-z_]+))?\}")


def _roles(raw: Any) -> dict[str, Any]:
    """Check a roles section: each role a name, a non-empty list of names or a non-empty mapping of names."""
    if not isinstance(raw, Mapping) or not raw:
        raise ContractError("roles must be a non-empty mapping")

    def name(v: Any, role: str) -> str:
        if type(v) is not str or not _NAME.match(v):
            raise ContractError(f"role {role}: {v!r} is not a name (letters, digits, _; quote yes/no/on/off)")
        return v

    out: dict[str, Any] = {}
    for role, v in raw.items():
        if isinstance(v, list) and v:
            out[role] = [name(x, role) for x in v]
        elif isinstance(v, Mapping) and v:
            out[role] = {name(k, role): name(x, role) for k, x in v.items()}
        elif isinstance(v, (list, Mapping)):
            raise ContractError(f"role {role}: empty")
        else:
            out[role] = name(v, role)
    return out


def _expand(rules: Any, roles: dict[str, Any]) -> list[dict[str, Any]]:
    """The raw contracts the rules give for these roles."""
    items = rules.get("rules") if isinstance(rules, Mapping) else None
    if not isinstance(items, list) or not items:
        raise ContractError("a rules file needs a non-empty list of rules")
    out = []
    for r in items:
        rule = r.get("rule") if isinstance(r, Mapping) else None
        contract = r.get("contract") if isinstance(r, Mapping) else None
        if type(rule) is not str or not rule or not isinstance(contract, Mapping):
            raise ContractError(f"each rule needs a rule id and a contract, got {r!r}")
        if "grade" in contract or "source" in contract:
            raise ContractError(f"{rule}: a rule's contract sets no grade or source (the expansion does)")
        each = r.get("each")
        if each is None:
            items_of: list[tuple[str | None, str | None]] = [(None, None)]
        elif each not in roles:
            raise ContractError(f"{rule}: no role {each!r}")
        elif isinstance(roles[each], list):
            items_of = [(x, None) for x in roles[each]]
        elif isinstance(roles[each], dict):
            items_of = list(roles[each].items())
        else:
            raise ContractError(f"{rule}: each needs a list or mapping role, {each!r} is one name")

        for key, value in items_of:
            def slot(m: re.Match, key=key, value=value) -> str:
                role, sub = m.groups()
                if role == "each":
                    if key is None:
                        raise ContractError(f"{rule}: {{each}} outside an each rule")
                    if sub is None:
                        return key
                    if sub == "value" and value is not None:
                        return value
                    raise ContractError(f"{rule}: {m.group(0)} needs an each over a mapping role")
                v = roles.get(role)
                if v is None or (sub is not None and (not isinstance(v, dict) or sub not in v)):
                    raise ContractError(f"{rule}: no role {role + ('.' + sub if sub else '')!r}")
                if sub is not None:
                    return v[sub]
                if isinstance(v, dict):
                    raise ContractError(f"{rule}: role {role} is a mapping; use {{{role}.<key>}}")
                return "|".join(v) if isinstance(v, list) else v

            def fill(x: Any) -> Any:
                if isinstance(x, str):
                    return _SLOT.sub(slot, x)
                if isinstance(x, list):
                    return [fill(y) for y in x]
                return x

            source = {"rule": rule}
            if r.get("quote") is not None:
                source["quote"] = r["quote"]
            filled = {k: fill(v) for k, v in contract.items()}
            for k, v in filled.items():
                if any("{" in x or "}" in x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)):
                    raise ContractError(f"{rule}: {{ or }} left after expansion in {k}: {v!r}")
            out.append({**filled, "grade": "generic", "source": source})
    return out


def rules_file(path: Path) -> Path | None:
    """The rules file a binding file names (module doc, "Roles"), or None for a plain contract file. Its
    contents decide the expanded contracts as much as the binding's, so a report records both."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, Mapping) and "roles" in raw and isinstance(raw.get("rules"), str):
        return Path(path).parent / raw["rules"]
    return None


def load_contracts(source: Path | str | Mapping[str, Any]) -> ContractSet:
    """Load a contract set.

    ``source`` is a :class:`~pathlib.Path` to a YAML file, a ``str`` of YAML
    text, or an already-parsed mapping.
    """
    base = Path()
    if isinstance(source, Path):
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        base = source.parent
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
    if "roles" in raw:
        if "contracts" in raw:
            raise ContractError("a file has roles and contracts; a binding's contracts come from its rules file")
        rules = raw.get("rules")
        if type(rules) is not str or not rules:
            raise ContractError("a binding needs rules: the path of its rules file")
        try:
            rules_raw = yaml.safe_load((base / rules).read_text(encoding="utf-8"))
        except OSError as exc:
            raise ContractError(f"rules file {rules!r}: {exc.strerror or exc}") from None
        items = _expand(rules_raw, _roles(raw["roles"]))
    else:
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
