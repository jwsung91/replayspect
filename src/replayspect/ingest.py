"""Text log ingest (WP5a): a text log and a rules file in, a trace file out.

The rules file (``replayspect.rules/1``, docs/rules-schema.md) says how to split a log entry
into common fields (``entry.pattern``), how to read its timestamp (``clock``), and which
entries become which trace events (``rules``, first match wins). No model is involved.

What ingest guarantees:

* Every event is ``fidelity: exact`` and ``source: adapter:text``, with ``log.line``: the log
  line it came from.
* Nothing is dropped silently. Entries no rule matches are counted and listed; entries a rule
  marks ``ignore`` are counted.
* Times are as logged. A trace's times never decrease, so events are sorted by time (stable:
  equal times keep log order). An event logged after a later one is flagged ``out_of_order``
  when it steps back by at most ``clock.tolerance``, else ``out_of_tolerance``. A run of
  consecutive ``out_of_tolerance`` events is reported as a suspected clock step. Nothing is
  corrected here; clock estimation belongs to driven replay (WP5b).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from replayspect._json import plain_json_copy
from replayspect.rewind import parse_time_us
from replayspect.trace import EVENT_KINDS, Event
from replayspect.tracefile import Header

RULES_SCHEMA = "replayspect.rules/1"
SOURCE = "adapter:text"
#: Consecutive out_of_tolerance events (in log order) from which a clock step is suspected.
CLOCK_STEP_RUN = 3

_EPOCH_UNITS = {"s": 1_000_000, "ms": 1_000, "us": 1, "ns": Decimal("0.001")}
_OFFSET = re.compile(r"^(?:Z|UTC|[+-]\d{2}:?\d{2})$")
_PLACEHOLDER = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)(?:\|(int|float))?(\?)?\}")
_TOP_KEYS = {"schema", "name", "system", "actor", "clock", "entry", "rules"}
_CLOCK_KEYS = {"format", "unit", "timezone", "tolerance", "origin"}
_ENTRY_KEYS = {"pattern", "time", "continuation"}
_RULE_KEYS = {"name", "where", "match", "event", "ignore"}
_EVENT_KEYS = {"kind", "name", "actor", "req_id", "data"}
_UNSET = object()


class RulesError(ValueError):
    """A rules file that cannot be used; the message names the rules file and, where it applies, the rule."""


class IngestError(ValueError):
    """A log that cannot be ingested; the message names the log line and, where it applies, the rule."""


# -- templates -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    """A rule's event value: a literal, or text with ``{group}`` placeholders.

    ``{g}`` is the group's text, ``{g|int}`` and ``{g|float}`` convert it (the whole value must be
    that one placeholder), and ``{g?}`` (also whole value) leaves the field out when the group did
    not take part in the match. ``{{`` and ``}}`` are literal braces.
    """

    raw: Any
    parts: tuple[tuple[str, str | None], ...] = ()  # ("text", None) or (group, None)
    single: tuple[str, str | None, bool] | None = None  # (group, type, optional) when the whole value

    @classmethod
    def parse(cls, raw: Any, where: str) -> "Template":
        if not isinstance(raw, str):
            try:
                plain_json_copy(raw)
            except ValueError as exc:
                raise ValueError(f"{where}: literal {raw!r} is not plain JSON ({exc})") from None
            return cls(raw)
        parts: list[tuple[str, str | None]] = []
        pos = 0
        whole = None
        for m in _PLACEHOLDER.finditer(raw):
            if m.start() > pos:
                parts.append((raw[pos:m.start()], None))
            tok = m.group(0)
            if tok in ("{{", "}}"):
                parts.append((tok[0], None))
            else:
                group, kind, opt = m.group(1), m.group(2), bool(m.group(3))
                if (kind or opt) and m.span() != (0, len(raw)):
                    raise ValueError(f"{where}: {tok} must be the whole value")
                if m.span() == (0, len(raw)):
                    whole = (group, kind, opt)
                parts.append(("", group))
            pos = m.end()
        if pos < len(raw):
            parts.append((raw[pos:], None))
        if not _balanced(raw):
            raise ValueError(f"{where}: unmatched brace in {raw!r}; write {{{{ or }}}} for a literal brace")
        return cls(raw, tuple(parts), whole)

    def groups(self) -> set[str]:
        return {g for _, g in self.parts if g is not None}

    def render(self, groups: Mapping[str, str | None]) -> Any:
        """The value for one entry, or ``_UNSET`` to leave the field out (``{g?}`` with no match)."""
        if not self.parts and not isinstance(self.raw, str):
            return self.raw
        if self.single is not None:
            group, kind, opt = self.single
            text = groups.get(group)
            if text is None:
                if opt:
                    return _UNSET
                raise ValueError(f"group {group!r} did not take part in the match")
            if kind == "int":
                try:
                    return int(text)
                except ValueError:
                    raise ValueError(f"{text!r} (group {group!r}) is not an integer") from None
            if kind == "float":
                try:
                    v = float(text)
                except ValueError:
                    raise ValueError(f"{text!r} (group {group!r}) is not a number") from None
                if v != v or v in (float("inf"), float("-inf")):
                    raise ValueError(f"{text!r} (group {group!r}) is not a finite number")
                return v
            return text
        out = []
        for text, group in self.parts:
            if group is None:
                out.append(text)
            else:
                v = groups.get(group)
                if v is None:
                    raise ValueError(f"group {group!r} did not take part in the match")
                out.append(v)
        return "".join(out)


def _balanced(raw: str) -> bool:
    """No stray single brace once placeholders and escapes are removed."""
    stripped = _PLACEHOLDER.sub("", raw)
    return "{" not in stripped and "}" not in stripped


# -- the rules file --------------------------------------------------------------------------


@dataclass(frozen=True)
class Clock:
    format: str  # "epoch", "iso8601" or a strptime pattern
    unit: str | None
    tz: tzinfo | None
    tolerance_us: int
    origin_us: int | None  # absolute (µs since the Unix epoch, UTC)

    def absolute_us(self, text: str) -> int:
        """Microseconds since the Unix epoch (UTC) for a logged timestamp."""
        if self.format == "epoch":
            try:
                v = Decimal(text.strip())
            except InvalidOperation:
                raise ValueError(f"cannot read {text!r} as an epoch time") from None
            return int(v * _EPOCH_UNITS[self.unit or "s"])
        if self.format == "iso8601":
            try:
                t = datetime.fromisoformat(text.strip())
            except ValueError:
                raise ValueError(f"cannot read {text!r} as an ISO 8601 time") from None
        else:
            try:
                t = datetime.strptime(text.strip(), self.format)
            except ValueError:
                raise ValueError(f"cannot read {text!r} with format {self.format!r}") from None
        if t.tzinfo is None:
            if self.tz is None:
                raise ValueError(f"{text!r} has no UTC offset and the rules give no clock.timezone; "
                                 "ingest does not guess a time zone")
            t = t.replace(tzinfo=self.tz)
        return _to_us(t)

    def iso(self, abs_us: int) -> str:
        """``abs_us`` as ISO 8601, in the rules' time zone (UTC when none)."""
        t = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=abs_us)
        return t.astimezone(self.tz or timezone.utc).isoformat(timespec="microseconds")


def _to_us(t: datetime) -> int:
    d = t - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (d.days * 86_400 + d.seconds) * 1_000_000 + d.microseconds


@dataclass(frozen=True)
class Rule:
    name: str
    where: tuple[tuple[str, re.Pattern[str]], ...]
    match: re.Pattern[str] | None
    ignore: bool
    event: dict[str, Template] = field(default_factory=dict)
    data: dict[str, Template] = field(default_factory=dict)


@dataclass(frozen=True)
class Rules:
    name: str
    system: str | None
    actor: str | None
    clock: Clock
    entry: re.Pattern[str]
    time_group: str
    text_group: str | None
    continuation: re.Pattern[str] | None
    rules: tuple[Rule, ...]
    path: str = "<rules>"


def _tz(text: Any, where: str) -> tzinfo:
    if not isinstance(text, str) or not text:
        raise ValueError(f"{where} must be a UTC offset (+09:00) or a time zone name (Asia/Seoul)")
    if _OFFSET.match(text):
        if text in ("Z", "UTC"):
            return timezone.utc
        sign = 1 if text[0] == "+" else -1
        digits = text[1:].replace(":", "")
        return timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"{where}: unknown time zone {text!r}") from None


def _regex(text: Any, where: str, flags: int = 0) -> re.Pattern[str]:
    if not isinstance(text, str) or not text:
        raise ValueError(f"{where} must be a non-empty regular expression")
    try:
        return re.compile(text, flags)
    except re.error as exc:
        raise ValueError(f"{where}: bad regular expression: {exc}") from None


def _keys(d: Any, allowed: set[str], where: str) -> dict:
    if not isinstance(d, dict):
        raise ValueError(f"{where} must be a mapping")
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {', '.join(map(str, unknown))}; "
                         f"allowed: {', '.join(sorted(allowed))}")
    return d


def _clock(d: Any) -> Clock:
    d = _keys(d, _CLOCK_KEYS, "clock")
    fmt = d.get("format")
    if not isinstance(fmt, str) or not fmt:
        raise ValueError("clock.format must be epoch, iso8601 or a strptime pattern such as '%Y-%m-%d %H:%M:%S.%f'")
    unit = d.get("unit")
    if fmt == "epoch":
        if unit is not None and unit not in _EPOCH_UNITS:
            raise ValueError(f"clock.unit must be one of {', '.join(_EPOCH_UNITS)}, got {unit!r}")
    elif unit is not None:
        raise ValueError("clock.unit is for clock.format epoch only")
    elif fmt != "iso8601" and "%" not in fmt:
        raise ValueError(f"clock.format {fmt!r} is not epoch, iso8601 or a strptime pattern")
    tz = _tz(d["timezone"], "clock.timezone") if d.get("timezone") is not None else None
    if fmt not in ("epoch", "iso8601") and "%z" not in fmt and tz is None:
        raise ValueError(f"clock.format {fmt!r} has no UTC offset (%z); give clock.timezone "
                         "(ingest does not guess a time zone)")
    tol = d.get("tolerance", 0)
    try:
        tolerance = parse_time_us(str(tol))
    except ValueError:
        raise ValueError(f"clock.tolerance must be a time such as 5ms or 0.005s, got {tol!r}") from None
    origin = d.get("origin")
    origin_us = None
    if origin is not None:
        try:
            t = datetime.fromisoformat(str(origin))
        except ValueError:
            raise ValueError(f"clock.origin must be an ISO 8601 time, got {origin!r}") from None
        if t.tzinfo is None:
            if tz is None:
                raise ValueError("clock.origin has no UTC offset and there is no clock.timezone")
            t = t.replace(tzinfo=tz)
        origin_us = _to_us(t)
    return Clock(fmt, unit, tz, tolerance, origin_us)


def _rule(d: Any, i: int, entry_groups: set[str], has_default_actor: bool) -> Rule:
    if not isinstance(d, dict):
        raise ValueError(f"rules[{i}] must be a mapping")
    name = d.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"rules[{i}] needs a name")
    where_label = f"rule {name!r}"
    try:
        _keys(d, _RULE_KEYS, where_label)
        match = _regex(d["match"], f"{where_label} match", re.M) if d.get("match") is not None else None
        groups = entry_groups | (set(match.groupindex) if match else set())
        where = []
        for k, v in _keys(d.get("where") or {}, entry_groups, f"{where_label} where (entry.pattern groups)").items():
            where.append((k, _regex(v, f"{where_label} where.{k}")))
        ignore = d.get("ignore", False)
        if type(ignore) is not bool:
            raise ValueError(f"{where_label}: ignore must be true or false")
        ev = d.get("event")
        if ignore:
            if ev is not None:
                raise ValueError(f"{where_label}: an ignore rule has no event")
            return Rule(name, tuple(where), match, True)
        if ev is None:
            raise ValueError(f"{where_label} needs an event (or ignore: true)")
        _keys(ev, _EVENT_KEYS, f"{where_label} event")
        event: dict[str, Template] = {}
        for k in ("kind", "name", "actor", "req_id"):
            if k in ev and ev[k] is not None:
                if not isinstance(ev[k], str):
                    raise ValueError(f"{where_label} event.{k} must be a string")
                event[k] = Template.parse(ev[k], f"{where_label} event.{k}")
        for k in ("kind", "name"):
            if k not in event:
                raise ValueError(f"{where_label} event needs {k}")
        if "actor" not in event and not has_default_actor:
            raise ValueError(f"{where_label} event needs an actor (or give actor at the top of the rules file)")
        for k in ("kind", "name", "actor"):
            if k in event and event[k].single and event[k].single[2]:
                raise ValueError(f"{where_label} event.{k} cannot be optional")
            if k in event and event[k].single and event[k].single[1]:
                raise ValueError(f"{where_label} event.{k} must be text, not a number")
        if "req_id" in event and event["req_id"].single and event["req_id"].single[1]:
            raise ValueError(f"{where_label} event.req_id must be text, not a number")
        if not event["kind"].groups() and event["kind"].raw not in EVENT_KINDS:
            raise ValueError(f"{where_label} event.kind {event['kind'].raw!r} is not one of {sorted(EVENT_KINDS)}")
        data_raw = ev.get("data") or {}
        if not isinstance(data_raw, dict) or not all(isinstance(k, str) and k for k in data_raw):
            raise ValueError(f"{where_label} event.data must be a mapping with text keys")
        if "link" in data_raw:
            raise ValueError(f"{where_label} event.data.link is reserved for channel metadata")
        data = {k: Template.parse(v, f"{where_label} event.data.{k}") for k, v in data_raw.items()}
        for k, t in list(event.items()) + [(f"data.{k}", t) for k, t in data.items()]:
            missing = t.groups() - groups
            if missing:
                raise ValueError(f"{where_label} event.{k} uses group(s) {', '.join(sorted(missing))} that neither "
                                 "entry.pattern nor match defines")
        return Rule(name, tuple(where), match, False, event, data)
    except ValueError as exc:
        msg = str(exc)
        raise ValueError(msg if msg.startswith(where_label) else f"{where_label}: {msg}") from None


def parse_rules(text: str, path: str = "<rules>") -> Rules:
    """Read and check a rules file. Errors name the file and, for a rule's problem, the rule."""
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulesError(f"{path}: not YAML: {exc}") from None
    try:
        d = _keys(d, _TOP_KEYS, "rules file")
        if d.get("schema") != RULES_SCHEMA:
            raise ValueError(f"schema must be {RULES_SCHEMA!r}, got {d.get('schema')!r}")
        name = d.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        system = d.get("system")
        if system is not None and (not isinstance(system, str) or not system):
            raise ValueError("system must be a non-empty string")
        actor = d.get("actor")
        if actor is not None and (not isinstance(actor, str) or not actor):
            raise ValueError("actor must be a non-empty string")
        clock = _clock(d.get("clock"))
        e = _keys(d.get("entry"), _ENTRY_KEYS, "entry")
        entry = _regex(e.get("pattern"), "entry.pattern", re.S)
        time_group = e.get("time", "time")
        if time_group not in entry.groupindex:
            raise ValueError(f"entry.pattern has no group {time_group!r} for the timestamp "
                             "(name it (?P<time>...) or set entry.time)")
        cont = _regex(e["continuation"], "entry.continuation") if e.get("continuation") is not None else None
        raw_rules = d.get("rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise ValueError("rules must be a non-empty list")
        rules = tuple(_rule(r, i, set(entry.groupindex), actor is not None) for i, r in enumerate(raw_rules))
        names = [r.name for r in rules]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"rule name(s) used twice: {', '.join(dup)}")
    except ValueError as exc:
        raise RulesError(f"{path}: {exc}") from None
    text_group = "text" if "text" in entry.groupindex else None
    return Rules(name, system, actor, clock, entry, time_group, text_group, cont, rules, path)


def read_rules(path: Path | str) -> Rules:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise RulesError(f"{p}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise RulesError(f"{p}: not UTF-8 text") from None
    return parse_rules(text, str(p))


# -- reading the log ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    line: int  # first line, 1-based
    text: str  # continuation lines joined with "\n"


def entries(data: bytes, cont: re.Pattern[str] | None, name: str = "<log>") -> tuple[list[Entry], int]:
    """Split a log into entries. UTF-8; a trailing CR is removed from every line. Returns (entries, blank lines).

    Blank lines are skipped and counted. A line that matches ``cont`` joins the entry before it.
    """
    out: list[Entry] = []
    blank = 0
    raw_lines = data.split(b"\n")
    if raw_lines and raw_lines[-1] == b"":
        raw_lines.pop()
    for lineno, raw in enumerate(raw_lines, start=1):
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestError(f"{name}:{lineno}: not UTF-8 (byte {exc.start + 1} of the line)") from None
        if not line.strip():
            blank += 1
            continue
        if cont is not None and out and cont.match(line):
            out[-1] = Entry(out[-1].line, out[-1].text + "\n" + line)
        else:
            out.append(Entry(lineno, line))
    return out, blank


# -- ingest ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClockStep:
    first_line: int
    last_line: int
    events: int
    back_us: int  # how far the first event stepped back


@dataclass
class Ingested:
    rules: Rules
    events: list[Event]
    header: Header
    entries: int
    blank: int
    ignored: int
    unmatched: list[Entry]
    clock_steps: list[ClockStep]

    def flag_counts(self) -> dict[str, int]:
        out = {"out_of_order": 0, "out_of_tolerance": 0}
        for e in self.events:
            for f in (e.log or {}).get("flags", []):
                out[f] += 1
        return out

    def summary(self, log_name: str, out: str, unmatched_path: str | None) -> list[str]:
        fc = self.flag_counts()
        lines = [f"ingest {log_name} with rules {self.rules.name} ({self.rules.path})",
                 f"entries {self.entries} (blank lines {self.blank}): events {len(self.events)}, "
                 f"ignored {self.ignored}, unmatched {len(self.unmatched)}"
                 + (f" -> {unmatched_path}" if self.unmatched and unmatched_path else ""),
                 f"flagged {sum(fc.values())}: out_of_order {fc['out_of_order']}, "
                 f"out_of_tolerance {fc['out_of_tolerance']} (tolerance {self.rules.clock.tolerance_us}us)"]
        if self.clock_steps:
            steps = "; ".join(f"lines {c.first_line}-{c.last_line} ({c.events} events, "
                              f"{c.back_us / 1e6:.6f}s back)" for c in self.clock_steps)
            lines.append(f"clock_step suspected {len(self.clock_steps)}: {steps}; not corrected")
        else:
            lines.append("clock_step suspected 0")
        if self.events:
            lines.append(f"time 0 is {self.header.origin}; events {self.events[0].t_us / 1e6:.6f}s.."
                         f"{self.events[-1].t_us / 1e6:.6f}s")
        lines.append(f"trace: {len(self.events)} events -> {out}")
        return lines


def _groups(rules: Rules, m: re.Match[str], rm: re.Match[str] | None) -> dict[str, str | None]:
    g = dict(m.groupdict())
    if rm is not None:
        g.update(rm.groupdict())
    return g


def _first_rule(rules: Rules, entry: Entry) -> tuple[Rule, re.Match[str], re.Match[str] | None] | None:
    m = rules.entry.match(entry.text)
    if m is None:
        return None
    text = m.group(rules.text_group) if rules.text_group else entry.text
    text = text or ""
    for r in rules.rules:
        if any(m.group(k) is None or not rx.fullmatch(m.group(k)) for k, rx in r.where):
            continue
        rm = None
        if r.match is not None:
            rm = r.match.search(text)
            if rm is None:
                continue
        return r, m, rm
    return None


def _event_fields(rules: Rules, r: Rule, groups: Mapping[str, str | None]) -> dict[str, Any]:
    vals: dict[str, Any] = {}
    for k, t in r.event.items():
        v = t.render(groups)
        if v is not _UNSET:
            vals[k] = v
    kind = vals["kind"]
    if kind not in EVENT_KINDS:
        raise ValueError(f"event kind {kind!r} is not one of {sorted(EVENT_KINDS)}")
    for k in ("name", "actor"):
        if k in vals and (not isinstance(vals[k], str) or not vals[k]):
            raise ValueError(f"event {k} is empty")
    data = {}
    for k, t in r.data.items():
        v = t.render(groups)
        if v is not _UNSET:
            data[k] = v
    return {"kind": kind, "name": vals["name"], "actor": vals.get("actor", rules.actor),
            "req_id": vals.get("req_id") or None, "data": data}


def ingest_text(data: bytes, rules: Rules, name: str = "<log>", contracts: dict[str, str] | None = None) -> Ingested:
    """Ingest a log's bytes. Raises :class:`IngestError` naming the line (and rule) on the first problem."""
    ents, blank = entries(data, rules.continuation, name)
    found: list[tuple[int, int, dict[str, Any]]] = []  # (absolute µs, line, fields), in log order
    ignored = 0
    unmatched: list[Entry] = []
    for ent in ents:
        hit = _first_rule(rules, ent)
        if hit is None:
            unmatched.append(ent)
            continue
        r, m, rm = hit
        if r.ignore:
            ignored += 1
            continue
        try:
            abs_us = rules.clock.absolute_us(m.group(rules.time_group) or "")
            fields = _event_fields(rules, r, _groups(rules, m, rm))
        except ValueError as exc:
            raise IngestError(f"{name}:{ent.line}: rule {r.name!r}: {exc}") from None
        found.append((abs_us, ent.line, fields))

    flags: dict[int, list[str]] = {}
    back: dict[int, int] = {}
    latest = None
    for abs_us, line, _ in found:
        if latest is not None and abs_us < latest:
            lag = latest - abs_us
            flags[line] = ["out_of_order" if lag <= rules.clock.tolerance_us else "out_of_tolerance"]
            back[line] = lag
        latest = abs_us if latest is None else max(latest, abs_us)
    steps = _clock_steps([(line, flags.get(line), back.get(line, 0)) for _, line, _ in found])

    ordered = sorted(found, key=lambda x: x[0])  # stable: equal times keep log order
    if rules.clock.origin_us is not None:
        origin = rules.clock.origin_us
        if ordered and ordered[0][0] < origin:
            raise IngestError(f"{name}:{ordered[0][1]}: event before clock.origin "
                              f"({rules.clock.iso(ordered[0][0])} < {rules.clock.iso(origin)})")
    else:
        origin = ordered[0][0] if ordered else 0
    events = []
    for seq, (abs_us, line, f) in enumerate(ordered):
        log: dict[str, Any] = {"line": line}
        if line in flags:
            log["flags"] = flags[line]
        try:
            data = plain_json_copy(f["data"])
        except ValueError as exc:
            raise IngestError(f"{name}:{line}: event data is not plain JSON: {exc}") from None
        events.append(Event(seq, abs_us - origin, f["actor"], f["kind"], f["name"], f["req_id"], data,
                            "exact", SOURCE, log))
    header = Header(system=rules.system, source=SOURCE, seed=None, plan=None, contracts=contracts,
                    until_us=None, slice=None, origin=rules.clock.iso(origin))
    return Ingested(rules, events, header, len(ents), blank, ignored, unmatched, steps)


def _clock_steps(seq: Sequence[tuple[int, list[str] | None, int]]) -> list[ClockStep]:
    """Runs of at least CLOCK_STEP_RUN consecutive out_of_tolerance events, in log order."""
    out: list[ClockStep] = []
    run: list[tuple[int, int]] = []

    def close() -> None:
        if len(run) >= CLOCK_STEP_RUN:
            out.append(ClockStep(run[0][0], run[-1][0], len(run), run[0][1]))
        run.clear()

    for line, fl, lag in seq:
        if fl == ["out_of_tolerance"]:
            run.append((line, lag))
        else:
            close()
    close()
    return out


def unmatched_text(unmatched: Sequence[Entry]) -> str:
    """The unmatched entries, one per line as ``line: text``; continuation lines indented."""
    return "".join(f"{e.line}: " + e.text.replace("\n", "\n    ") + "\n" for e in unmatched)


__all__ = ["CLOCK_STEP_RUN", "ClockStep", "Entry", "IngestError", "Ingested", "RULES_SCHEMA", "Rules",
           "RulesError", "SOURCE", "entries", "ingest_text", "parse_rules", "read_rules", "unmatched_text"]
