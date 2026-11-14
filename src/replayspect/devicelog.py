"""Device logs: what the device itself wrote, checked against the device model (stage 1 of two sources).

**The device log.** A device that logs its own side writes, per line, its own clock and an event::

    <receive time> # <millis> recv MOVE_UP r-0001
    <receive time> # <millis> send ERROR r-0003 reason=illegal
    <receive time> # <millis> state MOVING_UP r-0001 from=DOWN on=MOVE_UP
    <receive time> # <millis> effect motor_start r-0001 dir=up

(the testbed Uno firmware, ``examples/testbed-uno``; the receive time in front is the host's and is not
read here). Only four kinds become events, an **allow list**: ``recv``, ``send``, ``state``, ``effect``.
An ``error`` line marks the log invalid. Every other line is skipped without a trace: not counted, not
named, not numbered. So the lines that say which defect a build has (``build defect=``, ``defect fired``)
cannot reach a result, and neither can any line added later; the output with or without them is the
same, byte for byte.

**Conformance** (:func:`conform`). The device model (the correct one, or with a defect) is run alone,
fed what the device received, at the device's own times. Its sends, state changes and effects are
compared with what the device logged. No link is involved: no delay, loss or duplicate is estimated.
- A model event matches a logged one with the same kind, name, request id and fields, logged between
  ``early`` before and ``late`` after the model's time. The firmware's timers run on ``millis()`` and
  end up to a few milliseconds late, and inputs in the same millisecond may be taken in another order;
  ``late`` allows for that, nothing else.
- What the model does after the log ends minus ``late`` is not compared.
- **The declaration decides what counts** (:class:`Completeness`, default partial). The model is fed
  only when the device's receives are declared complete (otherwise "not checked"). A model event
  missing from the log is a mismatch only for an output kind declared complete; a logged event the
  model does not make always is. With nothing that can count, the result is "not checked".
- The result is "conforms", or the **first mismatch**: the time, what the model does and what the
  device did there (either may be nothing), the model's state just before and the last input the
  device received. With the correct model this says where the device first left the model, without
  any defect model. It is the first place the outputs differ, which can come after the defect's own
  branch: a repeated request a defect takes as new is answered ``ACK`` either way, and the difference
  shows when it executes (50 ms later in the lift).

**Count check** (:func:`count_check`). With the client's log as well: per message and request id, how
many the client sent against how many the device received, and how many the device sent against how
many the client received. A difference is a message lost on the link, or an extra copy. No clock is
needed. Absence counts only where the side that should show the message is declared complete
(:class:`Completeness`, default partial: nothing is inferred from absence). A loss and an extra copy of
the same message cancel out and are not seen.

**Fidelity.** Every item in the report says how it is known: ``observed: device`` (the device log),
``observed: client`` (the client log), ``inferred: count`` (the count check), ``reconstructed`` (what
the model does).

**What this cannot show.** The device log is written by the firmware that may be defective. A defect
in the logging itself, or one where what the device does and what it logs differ, is not seen.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from replayspect.sim.link import Message
from replayspect.sim.scheduler import Scheduler
from replayspect.trace import Event, Trace

#: The kinds of device log line that become events. Everything else is skipped (``error`` marks the
#: log invalid).
ALLOWED = ("recv", "send", "state", "effect")
OBSERVED_DEVICE, OBSERVED_CLIENT, INFERRED, RECONSTRUCTED = ("observed: device", "observed: client",
                                                             "inferred: count", "reconstructed")
#: Default comparison window (us): a logged event may come this much after the model's.
LATE_US = 2_000
EARLY_US = 0
_LINE = re.compile(r"^\S+ # (?P<ms>\d+) (?P<kind>\S+)(?: (?P<rest>.*))?$")


class DeviceLogError(ValueError):
    """Raised when a device log cannot be read."""


@dataclass(frozen=True)
class DeviceLog:
    """The allowed events of a device log, at the device's clock (``millis() * 1000`` us), in log order."""

    events: tuple[Event, ...]
    errors: tuple[str, ...] = ()  # the ``error`` lines (the log is invalid when there is any)

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def end_us(self) -> int:
        return self.events[-1].t_us if self.events else 0


def _value(v: str) -> str | None:
    return None if v == "-" else v


def read_device_log(text: str) -> DeviceLog:
    """Parse a device log (module doc). Lines that are not ``<time> # <millis> <kind> ...`` are skipped."""
    events: list[Event] = []
    errors: list[str] = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m is None:
            continue
        kind, rest = m["kind"], (m["rest"] or "").split()
        if kind == "error":
            errors.append(" ".join(rest))
            continue
        if kind not in ALLOWED or not rest:
            continue
        name, args = rest[0], rest[1:]
        req_id = None
        if args and "=" not in args[0]:
            req_id, args = _value(args[0]), args[1:]
        data: dict[str, Any] = {}
        for a in args:
            if "=" not in a:
                raise DeviceLogError(f"device log: cannot read {line!r}")
            k, v = a.split("=", 1)
            data[k] = _value(v)
        events.append(Event(len(events), int(m["ms"]) * 1000, "device", kind, name, req_id, data,
                            source="adapter:device-log"))
    return DeviceLog(tuple(events), tuple(errors))


# -- conformance --------------------------------------------------------------------------------


class _Feed:
    """The device model's channel: inputs are put in by hand, sends are recorded."""

    def __init__(self, sched: Scheduler, trace: Trace) -> None:
        self.sched, self.trace = sched, trace
        self.on_message = None

    def attach(self, endpoint, on_message, on_connection=None) -> None:
        self.on_message = on_message

    def send(self, sender: str, msg: Message) -> None:
        self.trace.record("device", "send", msg.name, msg.req_id, dict(msg.fields))


def _sig(e: Event) -> tuple:
    return (e.kind, e.name, e.req_id, tuple(sorted((k, v) for k, v in e.data.items() if k != "link")))


def show(e: Event | None) -> str | None:
    if e is None:
        return None
    data = " ".join(f"{k}={'-' if v is None else v}" for k, v in sorted(e.data.items()) if k != "link")
    return " ".join(x for x in (e.kind, e.name, e.req_id or "", data) if x)


def _item(e: Event | None, fidelity: str) -> dict[str, Any] | None:
    return None if e is None else {"t_us": e.t_us, "event": show(e), "fidelity": fidelity}


@dataclass
class Conformance:
    """One device model against a device log."""

    model: str  # "correct" or the defect's name
    status: str  # "conforms", "differs" or "not checked"
    compared: int  # logged events compared (sends, state changes, effects)
    matched: int
    mismatches: int  # unmatched events that count, model and device together
    first: dict[str, Any] | None  # the first mismatch (module doc)
    max_late_us: int | None  # the largest lateness among the matches
    absence_counts: tuple[str, ...] = ()  # the output kinds where a missing logged event is a mismatch
    reason: str | None = None  # why not checked

    @property
    def conforms(self) -> bool:
        return self.status == "conforms"

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "status": self.status, "conforms": self.conforms, "reason": self.reason,
                "absence_counts": list(self.absence_counts), "compared": self.compared, "matched": self.matched,
                "mismatches": self.mismatches, "first": self.first, "max_late_us": self.max_late_us}


#: How an input and a timer in the same millisecond are ordered. "timers-first" is what the firmware
#: does (testbed-uno README, difference 3); "input-first" exists to check what that rule changes.
SAME_MS = ("timers-first", "input-first")


def run_model(system, log: DeviceLog, mutants: Sequence[str] = (), until_us: int | None = None,
              same_ms: str = "timers-first") -> list[Event]:
    """The device model fed the device's receives at the device's times: its events, in time order."""
    if same_ms not in SAME_MS:
        raise ValueError(f"same_ms: one of {', '.join(SAME_MS)}")
    if system.device is None:
        raise DeviceLogError(f"{system.name} has no device model")
    sched = Scheduler(0)
    trace = Trace(lambda: sched.now_us)
    feed = _Feed(sched, trace)
    system.device(sched, trace, feed, tuple(sorted(mutants)))
    for e in log.events:
        if e.kind == "recv":
            msg = Message(e.name, e.req_id, {k: v for k, v in e.data.items() if v is not None})
            if same_ms == "input-first":
                sched.at_us(e.t_us, lambda m=msg: feed.on_message(m), f"device-log:recv:{e.req_id}")
                continue
            # the firmware runs the timers due in a millisecond first, then the input: the input is
            # queued again at its own time when that time comes, after every timer already due then
            sched.at_us(e.t_us, lambda m=msg, t=e.t_us: sched.at_us(t, lambda: feed.on_message(m),
                                                                    f"device-log:recv:{m.req_id}"),
                        f"device-log:recv:{e.req_id}")
    sched.run_until_us(log.end_us + LATE_US if until_us is None else until_us)
    return list(trace.events)


def conform(system, log: DeviceLog, mutants: Sequence[str] = (), late_us: int = LATE_US,
            early_us: int = EARLY_US, complete: "Completeness | None" = None,
            same_ms: str = "timers-first") -> Conformance:
    """Compare the device model's sends, state changes and effects with the device log (module doc).

    ``complete``: the device's declaration (default partial). The model is fed only when the
    receives are declared complete; a model event missing from the log counts only for a declared
    output kind; a logged event the model does not make always counts. With nothing that can count,
    the result is "not checked", never "conforms"."""
    name = "+".join(sorted(mutants)) or "correct"
    declared = (complete or Completeness()).device
    outputs = ("send", "state", "effect")
    device = [e for e in log.events if e.kind in outputs]
    absence = tuple(k for k in outputs if k in declared)
    if "recv" not in declared:
        return Conformance(name, "not checked", 0, 0, 0, None, None, absence,
                           "the device's receives are not declared complete: the model cannot be fed")
    if not absence and not device:
        return Conformance(name, "not checked", 0, 0, 0, None, None, absence,
                           "no send, state or effect line, and none declared complete: nothing to compare")
    model = [e for e in run_model(system, log, mutants, same_ms=same_ms)
             if e.actor == "device" and e.kind in outputs]
    end = log.end_us
    free: dict[tuple, list[int]] = {}
    for i, e in enumerate(device):
        free.setdefault(_sig(e), []).append(i)
    matched_dev: set[int] = set()
    unmatched_model: list[Event] = []
    lates: list[int] = []
    for e in model:
        cands = [i for i in free.get(_sig(e), []) if i not in matched_dev
                 and -early_us <= device[i].t_us - e.t_us <= late_us]
        if cands:
            i = min(cands, key=lambda j: device[j].t_us)
            matched_dev.add(i)
            lates.append(device[i].t_us - e.t_us)
        elif e.t_us <= end - late_us and e.kind in absence:
            unmatched_model.append(e)
    unmatched_dev = [device[i] for i in range(len(device)) if i not in matched_dev]
    first = None
    if unmatched_model or unmatched_dev:
        m0 = min(unmatched_model, key=lambda e: e.t_us, default=None)
        d0 = min(unmatched_dev, key=lambda e: e.t_us, default=None)
        t = min(x.t_us for x in (m0, d0) if x is not None)
        at_m = m0 if m0 is not None and m0.t_us <= t + late_us else None
        at_d = d0 if d0 is not None and d0.t_us <= t + late_us else None
        # the counterpart on the other side, if it is about the same request and near in time
        if at_m is not None and at_d is not None and at_m.req_id != at_d.req_id:
            if at_m.t_us <= at_d.t_us:
                at_d = None
            else:
                at_m = None
        req = (at_m or at_d).req_id
        states = [e for e in model if e.kind == "state" and e.t_us < t]
        inputs = [e for e in log.events if e.kind == "recv" and e.t_us <= t]
        first = {"t_us": t, "req_id": req, "model": _item(at_m, RECONSTRUCTED), "device": _item(at_d, OBSERVED_DEVICE),
                 "model_state": states[-1].name if states else None,
                 "last_input": _item(inputs[-1] if inputs else None, OBSERVED_DEVICE)}
    return Conformance(name, "conforms" if first is None else "differs", len(device), len(matched_dev),
                       len(unmatched_model) + len(unmatched_dev), first, max(lates) if lates else None, absence)


# -- the count check ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Completeness:
    """Which kinds each source logs completely. Default: partial (nothing is inferred from absence)."""

    client: frozenset[str] = frozenset()  # of "send", "recv"
    device: frozenset[str] = frozenset()  # of "recv", "send", "state", "effect"

    KINDS = {"client": {"send", "recv"}, "device": {"recv", "send", "state", "effect"}}

    @classmethod
    def parse(cls, specs: Sequence[str]) -> "Completeness":
        """``["device:recv,send,state,effect", "client:send,recv"]``."""
        got: dict[str, set[str]] = {"client": set(), "device": set()}
        for s in specs:
            src, _, kinds = s.partition(":")
            ks = {k.strip() for k in kinds.split(",") if k.strip()}
            if src not in got or not ks or ks - cls.KINDS[src]:
                raise ValueError(f"--complete {s!r}: client:send,recv or device: any of recv,send,state,effect")
            got[src] |= ks
        return cls(frozenset(got["client"]), frozenset(got["device"]))


def count_check(client: Sequence[Event], log: DeviceLog, complete: Completeness,
                client_actor: str = "client") -> dict[str, Any]:
    """Messages lost on the link and extra copies, by count per (message, request id) (module doc).

    A loss needs the receiving side complete; an extra copy needs the sending side complete. A count
    is a lower bound unless the other side is complete too. Polls are counted like any message."""
    tx = Counter((e.name, e.req_id) for e in client if e.actor == client_actor and e.kind == "send")
    rx = Counter((e.name, e.req_id) for e in client if e.actor == client_actor and e.kind == "recv")
    d_rx = Counter((e.name, e.req_id) for e in log.events if e.kind == "recv")
    d_tx = Counter((e.name, e.req_id) for e in log.events if e.kind == "send")
    items: list[dict[str, Any]] = []
    sides = (("c2s", tx, d_rx, ("client", "send"), ("device", "recv")),
             ("s2c", d_tx, rx, ("device", "send"), ("client", "recv")))
    for direction, sent, got, (s_src, s_kind), (r_src, r_kind) in sides:
        s_full = s_kind in getattr(complete, s_src)
        r_full = r_kind in getattr(complete, r_src)
        for key in sorted(set(sent) | set(got), key=lambda k: (k[1] or "", k[0])):
            n_s, n_r = sent[key], got[key]
            if n_s > n_r and r_full:
                items.append({"dir": direction, "msg": key[0], "req_id": key[1], "what": "lost", "n": n_s - n_r,
                              "exact": s_full, "fidelity": INFERRED})
            elif n_r > n_s and s_full:
                items.append({"dir": direction, "msg": key[0], "req_id": key[1], "what": "extra copy",
                              "n": n_r - n_s, "exact": r_full, "fidelity": INFERRED})
    return {"complete": {"client": sorted(complete.client), "device": sorted(complete.device)},
            "items": items,
            "not_inferred": [f"{src} {k}" for src, ks in (("client", complete.client), ("device", complete.device))
                             for k in ("send", "recv") if k not in ks]}


def device_report(system, log: DeviceLog, models: Sequence[str] = (), client: Sequence[Event] | None = None,
                  complete: Completeness = Completeness(), late_us: int = LATE_US,
                  same_ms: str = "timers-first") -> dict[str, Any]:
    """Stage 1 on one device log: the correct model and each named defect model, and the count check."""
    rows = [conform(system, log, ms, late_us, complete=complete, same_ms=same_ms) for ms in [()] + [(m,) for m in models]]
    out: dict[str, Any] = {
        "valid": log.valid, "errors": list(log.errors),
        "device_events": len(log.events), "fidelity": OBSERVED_DEVICE,
        "models": [r.to_dict() for r in rows],
        "conforming": [r.model for r in rows if r.conforms],
    }
    if client is not None:
        out["counts"] = count_check(client, log, complete)
    return out


def report_lines(rep: dict[str, Any]) -> list[str]:
    def ts(t: int) -> str:
        return f"{t / 1e6:.3f}s"
    lines = [f"device log: {rep['device_events']} events (observed: device)"
             + ("" if rep["valid"] else f"; INVALID, error lines: {', '.join(rep['errors'])}")]
    for r in rep["models"]:
        if r["status"] == "not checked":
            lines.append(f"  {r['model']}: not checked ({r['reason']})")
            continue
        if r["conforms"]:
            lines.append(f"  {r['model']}: conforms ({r['matched']} of {r['compared']} device events matched, "
                         f"latest {r['max_late_us'] / 1000 if r['max_late_us'] is not None else 0:g} ms after the model)")
            continue
        f = r["first"]
        lines.append(f"  {r['model']}: first mismatch at {ts(f['t_us'])} ({f['req_id'] or '-'}): model "
                     f"{f['model']['event'] if f['model'] else 'nothing'}, device "
                     f"{f['device']['event'] if f['device'] else 'nothing'}; model state {f['model_state']}, "
                     f"last input {f['last_input']['event'] if f['last_input'] else '-'} "
                     f"({r['mismatches']} unmatched in all)")
    if any(r["status"] != "not checked" for r in rep["models"]):
        lines.append("conforming models: " + (", ".join(rep["conforming"]) or "none")
                     + ("" if rep["models"][0]["absence_counts"] == ["send", "state", "effect"] else
                        f" (a missing logged event counts only for: {', '.join(rep['models'][0]['absence_counts']) or 'none'})"))
    if "counts" in rep:
        c = rep["counts"]
        lines.append("count check (inferred: count; a loss and an extra copy of the same message cancel out): "
                     + (", ".join(f"{x['dir']} {x['msg']} {x['req_id'] or '-'} {x['what']} x{x['n']}"
                                  + ("" if x["exact"] else " (at least)") for x in c["items"]) or "nothing lost or copied")
                     + (f"; not inferred from absence: {', '.join(c['not_inferred'])} (partial)" if c["not_inferred"] else ""))
    return lines
