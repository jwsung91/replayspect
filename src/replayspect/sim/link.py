"""Link model: the only place faults happen.

A :class:`Channel` connects the two endpoints of an integration, ``client``
and ``device``, through two one-way links: ``c2s`` (client to device) and
``s2c`` (device to client). Every message sent through it can be delayed,
dropped or duplicated, and the whole connection can go down and come back.

The channel records ``send``, ``recv`` and ``fault`` events itself, so every
endpoint produces uniform trace entries. Each message carries link metadata
under the reserved data key ``link``.

Two modes:

* **random** (no plan): decisions are drawn from named RNG streams forked from
  the scheduler seed.
* **explicit** (a :class:`FaultPlan`): only the faults in the plan happen.

Both modes record the realised decisions in the trace in the same form, so
:meth:`FaultPlan.from_trace` turns any random run into an explicit plan that
replays to the same trace digest. Shrinking is built on that property.

Explicit decisions address a message by :class:`MsgKey`: direction, message
name, request id, and ``k``, the occurrence of that ``(name, req_id)`` on
that direction. Removing a retry of one request therefore never shifts the
keys of any other request. A plan keeps baseline timing (``delays``) apart
from faults (``faults``, ``disconnects``), so removing a fault entry removes
only that fault.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from replayspect.sim.scheduler import Scheduler
from replayspect.trace import Trace

ENDPOINTS = ("client", "device")
DIRECTIONS = ("c2s", "s2c")
_DIR_OF_SENDER = {"client": "c2s", "device": "s2c"}
_RECEIVER_OF_DIR = {"c2s": "device", "s2c": "client"}

#: Drop reasons recorded in ``fault/drop`` events.
DROP_INJECTED = "injected"  # a decided fault (random draw or plan entry)
DROP_DISCONNECTED = "disconnected"  # sent while the connection was down
DROP_CONNECTION_LOST = "connection_lost"  # in flight when the connection dropped


class LinkError(ValueError):
    """Raised on invalid link configuration or use."""


@dataclass(frozen=True)
class Message:
    """An application message. ``fields`` must be JSON-serialisable."""

    name: str
    req_id: str | None = None
    fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "link" in self.fields:
            raise LinkError("message field name 'link' is reserved")


def _check_range(name: str, rng: tuple[int, int]) -> None:
    lo, hi = rng
    if not (isinstance(lo, int) and isinstance(hi, int)) or lo < 0 or hi < lo:
        raise LinkError(f"{name} must be (lo, hi) ints with 0 <= lo <= hi, got {rng!r}")


@dataclass(frozen=True)
class LinkProfile:
    """Fault parameters for one direction. Ranges are inclusive, in microseconds."""

    delay_us: tuple[int, int] = (1_000, 1_000)
    drop_p: float = 0.0
    dup_p: float = 0.0
    dup_extra_us: tuple[int, int] = (0, 0)

    def __post_init__(self) -> None:
        _check_range("delay_us", self.delay_us)
        _check_range("dup_extra_us", self.dup_extra_us)
        for name in ("drop_p", "dup_p"):
            p = getattr(self, name)
            if not 0.0 <= p <= 1.0:
                raise LinkError(f"{name} must be within [0, 1], got {p}")


@dataclass(frozen=True)
class ChannelProfile:
    """Per-direction link profiles plus random disconnect behaviour."""

    c2s: LinkProfile = LinkProfile()
    s2c: LinkProfile = LinkProfile()
    #: Mean time between disconnects (exponential). ``None`` disables them.
    disconnect_mean_interval_us: int | None = None
    disconnect_duration_us: tuple[int, int] = (500_000, 500_000)

    def __post_init__(self) -> None:
        _check_range("disconnect_duration_us", self.disconnect_duration_us)
        m = self.disconnect_mean_interval_us
        if m is not None and m <= 0:
            raise LinkError("disconnect_mean_interval_us must be positive or None")

    def link(self, direction: str) -> LinkProfile:
        return self.c2s if direction == "c2s" else self.s2c


@dataclass(frozen=True)
class MsgKey:
    """Identifies one send: the ``k``-th ``(msg, req_id)`` on ``dir`` (0-based).

    Messages without a ``req_id`` share one counter per ``(dir, msg)``, so
    adding or removing such a message shifts the ``k`` of later ones with the
    same name. Give messages a ``req_id`` whenever a plan needs to target
    them. Keys are not orderable; sort with :meth:`sort_key`.
    """

    dir: str
    msg: str
    req_id: str | None
    k: int

    def __post_init__(self) -> None:
        if self.dir not in DIRECTIONS:
            raise LinkError(f"dir must be one of {DIRECTIONS}, got {self.dir!r}")
        if self.k < 0:
            raise LinkError("k must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {"dir": self.dir, "msg": self.msg, "req_id": self.req_id, "k": self.k}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "MsgKey":
        return cls(d["dir"], d["msg"], d.get("req_id"), d["k"])

    def sort_key(self) -> tuple:
        return (DIRECTIONS.index(self.dir), self.msg, self.req_id or "", self.k)


@dataclass(frozen=True)
class Delay:
    """Baseline delivery delay of one message. Not a fault."""

    key: MsgKey
    delay_us: int

    def __post_init__(self) -> None:
        if self.delay_us < 0:
            raise LinkError("delay_us must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {**self.key.to_dict(), "delay_us": self.delay_us}


@dataclass(frozen=True)
class MessageFault:
    """A fault on one message: either a drop or a duplicate, never both."""

    key: MsgKey
    drop: bool = False
    dup_extra_us: int | None = None

    def __post_init__(self) -> None:
        if self.drop == (self.dup_extra_us is not None):
            raise LinkError("a message fault is exactly one of drop=True or dup_extra_us")
        if self.dup_extra_us is not None and self.dup_extra_us < 0:
            raise LinkError("dup_extra_us must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d = self.key.to_dict()
        if self.drop:
            d["drop"] = True
        else:
            d["dup_extra_us"] = self.dup_extra_us
        return d


@dataclass(frozen=True)
class Disconnect:
    t_us: int
    duration_us: int

    def __post_init__(self) -> None:
        if self.t_us < 0 or self.duration_us <= 0:
            raise LinkError("disconnect needs t_us >= 0 and duration_us > 0")

    def to_dict(self) -> dict[str, Any]:
        return {"t_us": self.t_us, "duration_us": self.duration_us}


def _key_from(d: Mapping[str, Any]) -> MsgKey:
    return MsgKey(d["dir"], d["msg"], d.get("req_id"), d["k"])


@dataclass(frozen=True)
class FaultPlan:
    """Everything that happens on the channel in explicit mode.

    ``delays`` is baseline timing; messages without an entry use the low end
    of the profile's ``delay_us``. ``faults`` and ``disconnects`` are the
    faults; removing one of them removes only that fault.
    """

    delays: tuple[Delay, ...] = ()
    faults: tuple[MessageFault, ...] = ()
    disconnects: tuple[Disconnect, ...] = ()

    def __post_init__(self) -> None:
        for label, keys in (("delays", [d.key for d in self.delays]), ("faults", [f.key for f in self.faults])):
            if len(keys) != len(set(keys)):
                raise LinkError(f"duplicate message key in plan {label}")
        ds = sorted(self.disconnects, key=lambda d: d.t_us)
        for a, b in zip(ds, ds[1:]):
            if b.t_us < a.t_us + a.duration_us:
                raise LinkError(f"overlapping disconnects at {a.t_us}us and {b.t_us}us")
        object.__setattr__(self, "_delay_of", {d.key: d.delay_us for d in self.delays})
        object.__setattr__(self, "_fault_of", {f.key: f for f in self.faults})

    def delay(self, key: MsgKey) -> int | None:
        return self._delay_of.get(key)  # type: ignore[attr-defined]

    def fault(self, key: MsgKey) -> MessageFault | None:
        return self._fault_of.get(key)  # type: ignore[attr-defined]

    def without_fault(self, key: MsgKey) -> "FaultPlan":
        """The same plan minus the fault on ``key`` (used by shrinking)."""
        return FaultPlan(self.delays, tuple(f for f in self.faults if f.key != key), self.disconnects)

    def to_dict(self) -> dict[str, Any]:
        return {
            "delays": [d.to_dict() for d in sorted(self.delays, key=lambda d: d.key.sort_key())],
            "faults": [f.to_dict() for f in sorted(self.faults, key=lambda f: f.key.sort_key())],
            "disconnects": [d.to_dict() for d in sorted(self.disconnects, key=lambda d: d.t_us)],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "FaultPlan":
        return cls(
            delays=tuple(Delay(_key_from(x), x["delay_us"]) for x in d.get("delays", [])),
            faults=tuple(
                MessageFault(_key_from(x), drop=x.get("drop", False), dup_extra_us=x.get("dup_extra_us"))
                for x in d.get("faults", [])
            ),
            disconnects=tuple(Disconnect(**x) for x in d.get("disconnects", [])),
        )

    @classmethod
    def from_trace(cls, trace: Trace) -> "FaultPlan":
        """Reconstruct the plan that reproduces ``trace`` in explicit mode."""
        delays: list[Delay] = []
        faults: list[MessageFault] = []
        disconnects: list[Disconnect] = []
        for ev in trace:
            if ev.kind == "send" and "link" in ev.data:
                link = ev.data["link"]
                if "delay_us" in link:
                    delays.append(Delay(MsgKey(link["dir"], ev.name, ev.req_id, link["k"]), link["delay_us"]))
            elif ev.kind == "fault" and ev.actor == "link":
                if ev.name == "drop" and ev.data.get("reason") == DROP_INJECTED:
                    faults.append(MessageFault(_key_from({**ev.data, "req_id": ev.req_id}), drop=True))
                elif ev.name == "duplicate":
                    faults.append(MessageFault(
                        _key_from({**ev.data, "req_id": ev.req_id}), dup_extra_us=ev.data["extra_us"]
                    ))
                elif ev.name == "disconnect":
                    disconnects.append(Disconnect(ev.t_us, ev.data["duration_us"]))
        return cls(tuple(delays), tuple(faults), tuple(disconnects))


def _snapshot_fields(msg: Message) -> dict[str, Any]:
    """Deep-copy message fields through JSON, rejecting anything that would change.

    A tuple would arrive as a list and an integer key as a string, which can
    silently change endpoint logic, so such fields are refused at send time
    instead. The reserved ``link`` key is checked here too, because
    ``Message.fields`` is a mutable dict that may have changed since
    construction.
    """
    original = dict(msg.fields)
    try:
        snapshot = json.loads(json.dumps(original, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise LinkError(f"{msg.name}: message fields must be JSON-serialisable: {exc}") from exc
    if snapshot != original or not _same_types(snapshot, original):
        raise LinkError(
            f"{msg.name}: message fields must survive a JSON round trip unchanged "
            "(use lists not tuples, string keys only)"
        )
    if "link" in snapshot:
        raise LinkError("message field name 'link' is reserved")
    return snapshot


def _same_types(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same_types(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same_types(x, y) for x, y in zip(a, b))
    return True


MessageHandler = Callable[[Message], None]
ConnectionHandler = Callable[[bool], None]


class Channel:
    """Two one-way links and a shared connection between client and device."""

    def __init__(
        self,
        sched: Scheduler,
        trace: Trace,
        profile: ChannelProfile | None = None,
        plan: FaultPlan | None = None,
    ) -> None:
        self._sched = sched
        self._trace = trace
        self.profile = profile or ChannelProfile()
        self.plan = plan
        self._rng = {d: sched.fork_rng(f"link/{d}") for d in DIRECTIONS}
        self._disc_rng = sched.fork_rng("link/disconnect")
        self._n = {d: 0 for d in DIRECTIONS}
        self._k: dict[tuple[str, str, str | None], int] = {}
        self._on_message: dict[str, MessageHandler] = {}
        self._on_connection: dict[str, ConnectionHandler | None] = {}
        self.up = True
        self.epoch = 0
        self._started = False
        self._planned_disconnects = sorted(plan.disconnects, key=lambda d: d.t_us) if plan else []

    @property
    def mode(self) -> str:
        return "random" if self.plan is None else "explicit"

    # -- wiring ------------------------------------------------------------------

    def attach(
        self,
        endpoint: str,
        on_message: MessageHandler,
        on_connection: ConnectionHandler | None = None,
    ) -> None:
        if endpoint not in ENDPOINTS:
            raise LinkError(f"endpoint must be one of {ENDPOINTS}, got {endpoint!r}")
        self._on_message[endpoint] = on_message
        self._on_connection[endpoint] = on_connection

    def start(self) -> None:
        """Schedule disconnects. Call once, after attaching both endpoints."""
        if self._started:
            raise LinkError("channel already started")
        missing = [e for e in ENDPOINTS if e not in self._on_message]
        if missing:
            raise LinkError(f"endpoints not attached: {missing}")
        self._started = True
        if self.plan is not None:
            first = min((d.t_us for d in self.plan.disconnects), default=None)
            if first is not None and first < self._sched.now_us:
                raise LinkError(f"disconnect at {first}us is in the past")
        self._schedule_next_disconnect()

    # -- sending -----------------------------------------------------------------

    def send(self, sender: str, msg: Message) -> None:
        if not self._started:
            raise LinkError("channel not started")
        if sender not in ENDPOINTS:
            raise LinkError(f"sender must be one of {ENDPOINTS}, got {sender!r}")
        direction = _DIR_OF_SENDER[sender]
        fields = _snapshot_fields(msg)
        n = self._n[direction]
        self._n[direction] += 1
        kk = (direction, msg.name, msg.req_id)
        k = self._k.get(kk, 0)
        self._k[kk] = k + 1
        key = MsgKey(direction, msg.name, msg.req_id, k)

        # Decide for every send, even one that will be lost, so the trace
        # always records the delay the message would have had. Removing a
        # drop or a disconnect from a plan then restores that original delay
        # instead of falling back to the profile minimum.
        drop, delay_us, dup_extra_us = self._decide(key)
        link: dict[str, Any] = {"dir": direction, "n": n, "k": k, "delay_us": delay_us}
        self._trace.record(sender, "send", msg.name, msg.req_id, {**fields, "link": link})

        if not self.up:
            self._record_drop(key, n, DROP_DISCONNECTED)
            return
        if drop:
            self._record_drop(key, n, DROP_INJECTED)
            return

        epoch = self.epoch
        self._sched.after_us(
            delay_us, lambda: self._arrive(key, n, 0, epoch, fields), f"{direction}:{msg.name}"
        )
        if dup_extra_us is not None:
            self._trace.record(
                "link", "fault", "duplicate", msg.req_id,
                {"dir": direction, "n": n, "msg": msg.name, "k": k, "extra_us": dup_extra_us},
            )
            self._sched.after_us(
                delay_us + dup_extra_us,
                lambda: self._arrive(key, n, 1, epoch, fields),
                f"{direction}:{msg.name}:dup",
            )

    def _decide(self, key: MsgKey) -> tuple[bool, int, int | None]:
        """Return ``(drop, delay_us, dup_extra_us)`` for one message.

        ``delay_us`` is always meaningful, even when the message is dropped.
        ``dup_extra_us`` is ``None`` for a dropped message.
        """
        prof = self.profile.link(key.dir)
        if self.plan is not None:
            fault = self.plan.fault(key)
            delay = self.plan.delay(key)
            if delay is None:
                delay = prof.delay_us[0]
            if fault is not None and fault.drop:
                return True, delay, None
            return False, delay, (fault.dup_extra_us if fault is not None else None)
        rng = self._rng[key.dir]
        # Fixed draw order for every message, dropped or not: drop?, delay,
        # duplicate?, and the duplicate's extra delay only if duplicated.
        # tests/test_link.py pins the resulting values; changing the order
        # changes what every existing seed produces.
        drop = rng.random() < prof.drop_p
        delay = rng.randint(*prof.delay_us)
        dup = rng.random() < prof.dup_p
        extra = rng.randint(*prof.dup_extra_us) if dup else None
        return drop, delay, (None if drop else extra)

    def _arrive(self, key: MsgKey, n: int, copy: int, epoch: int, fields: Mapping[str, Any]) -> None:
        if not self.up or epoch != self.epoch:
            self._record_drop(key, n, DROP_CONNECTION_LOST, copy=copy)
            return
        receiver = _RECEIVER_OF_DIR[key.dir]
        self._trace.record(
            receiver, "recv", key.msg, key.req_id,
            {**fields, "link": {"dir": key.dir, "n": n, "k": key.k, "copy": copy}},
        )
        # Each delivery gets its own copy, so a receiver that mutates the
        # message cannot affect a duplicate still in flight.
        self._on_message[receiver](Message(key.msg, key.req_id, json.loads(json.dumps(fields))))

    def _record_drop(self, key: MsgKey, n: int, reason: str, copy: int | None = None) -> None:
        data: dict[str, Any] = {"dir": key.dir, "n": n, "msg": key.msg, "k": key.k, "reason": reason}
        if copy is not None:
            data["copy"] = copy
        self._trace.record("link", "fault", "drop", key.req_id, data)

    # -- connection --------------------------------------------------------------

    def _disconnect(self, duration_us: int) -> None:
        if not self.up:
            return
        self.up = False
        self.epoch += 1
        self._trace.record("link", "fault", "disconnect", None, {"duration_us": duration_us})
        self._notify(False)
        self._sched.after_us(duration_us, self._reconnect, "link:reconnect")

    def _reconnect(self) -> None:
        self.up = True
        self._trace.record("link", "fault", "reconnect")
        self._notify(True)
        self._schedule_next_disconnect()

    def _notify(self, up: bool) -> None:
        for endpoint in ENDPOINTS:  # fixed order: client, then device
            cb = self._on_connection.get(endpoint)
            if cb is not None:
                cb(up)

    def _schedule_next_disconnect(self) -> None:
        """Schedule the next disconnect, at start and after each reconnect.

        Both modes schedule at exactly the same points in the run, so the
        scheduler's same-instant ordering is identical in random and explicit
        mode, which is what makes a plan from :meth:`FaultPlan.from_trace`
        replay to the same digest.
        """
        if self.plan is not None:
            if not self._planned_disconnects:
                return
            d = self._planned_disconnects.pop(0)
            self._sched.at_us(d.t_us, lambda: self._disconnect(d.duration_us), "link:disconnect")
            return
        mean = self.profile.disconnect_mean_interval_us
        if mean is None:
            return
        wait = max(1, round(self._disc_rng.expovariate(1.0 / mean)))
        duration = self._disc_rng.randint(*self.profile.disconnect_duration_us)
        self._sched.after_us(wait, lambda: self._disconnect(duration), "link:disconnect")
