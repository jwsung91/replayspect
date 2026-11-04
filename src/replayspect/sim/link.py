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
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
class MessageFault:
    """Explicit decisions for the ``n``-th message sent on ``dir`` (0-based).

    ``n`` counts every send attempt on that direction, including messages
    dropped because the connection was down, so plan keys stay stable.
    """

    dir: str
    n: int
    drop: bool = False
    delay_us: int | None = None
    dup_extra_us: int | None = None

    def __post_init__(self) -> None:
        if self.dir not in DIRECTIONS:
            raise LinkError(f"dir must be one of {DIRECTIONS}, got {self.dir!r}")
        if self.n < 0:
            raise LinkError("n must be >= 0")
        if self.drop and (self.delay_us is not None or self.dup_extra_us is not None):
            raise LinkError("a dropped message cannot also have delay_us or dup_extra_us")
        for name in ("delay_us", "dup_extra_us"):
            v = getattr(self, name)
            if v is not None and v < 0:
                raise LinkError(f"{name} must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"dir": self.dir, "n": self.n}
        if self.drop:
            d["drop"] = True
        if self.delay_us is not None:
            d["delay_us"] = self.delay_us
        if self.dup_extra_us is not None:
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


@dataclass(frozen=True)
class FaultPlan:
    """Everything that happens on the channel in explicit mode."""

    messages: tuple[MessageFault, ...] = ()
    disconnects: tuple[Disconnect, ...] = ()

    def __post_init__(self) -> None:
        keys = [(m.dir, m.n) for m in self.messages]
        if len(keys) != len(set(keys)):
            raise LinkError("duplicate (dir, n) in plan messages")
        ds = sorted(self.disconnects, key=lambda d: d.t_us)
        for a, b in zip(ds, ds[1:]):
            if b.t_us < a.t_us + a.duration_us:
                raise LinkError(f"overlapping disconnects at {a.t_us}us and {b.t_us}us")

    def message(self, direction: str, n: int) -> MessageFault | None:
        for m in self.messages:
            if m.dir == direction and m.n == n:
                return m
        return None

    def to_dict(self) -> dict[str, Any]:
        msgs = sorted(self.messages, key=lambda m: (DIRECTIONS.index(m.dir), m.n))
        return {
            "messages": [m.to_dict() for m in msgs],
            "disconnects": [d.to_dict() for d in sorted(self.disconnects, key=lambda d: d.t_us)],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "FaultPlan":
        return cls(
            messages=tuple(MessageFault(**m) for m in d.get("messages", [])),
            disconnects=tuple(Disconnect(**x) for x in d.get("disconnects", [])),
        )

    @classmethod
    def from_trace(cls, trace: Trace) -> "FaultPlan":
        """Reconstruct the plan that reproduces ``trace`` in explicit mode."""
        msgs: dict[tuple[str, int], MessageFault] = {}
        disconnects: list[Disconnect] = []
        for ev in trace:
            if ev.kind == "send" and "link" in ev.data:
                link = ev.data["link"]
                if "delay_us" in link:
                    key = (link["dir"], link["n"])
                    msgs[key] = MessageFault(link["dir"], link["n"], delay_us=link["delay_us"])
            elif ev.kind == "fault" and ev.actor == "link":
                if ev.name == "drop" and ev.data.get("reason") == DROP_INJECTED:
                    key = (ev.data["dir"], ev.data["n"])
                    msgs[key] = MessageFault(ev.data["dir"], ev.data["n"], drop=True)
                elif ev.name == "duplicate":
                    key = (ev.data["dir"], ev.data["n"])
                    msgs[key] = replace(msgs[key], dup_extra_us=ev.data["extra_us"])
                elif ev.name == "disconnect":
                    disconnects.append(Disconnect(ev.t_us, ev.data["duration_us"]))
        return cls(tuple(msgs.values()), tuple(disconnects))


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
        n = self._n[direction]
        self._n[direction] += 1
        link: dict[str, Any] = {"dir": direction, "n": n}

        if not self.up:
            self._trace.record(sender, "send", msg.name, msg.req_id, link=link, **msg.fields)
            self._record_drop(direction, n, msg, DROP_DISCONNECTED)
            return

        drop, delay_us, dup_extra_us = self._decide(direction, n)
        if drop:
            self._trace.record(sender, "send", msg.name, msg.req_id, link=link, **msg.fields)
            self._record_drop(direction, n, msg, DROP_INJECTED)
            return

        link["delay_us"] = delay_us
        self._trace.record(sender, "send", msg.name, msg.req_id, link=link, **msg.fields)
        epoch = self.epoch
        self._sched.after_us(
            delay_us, lambda: self._arrive(direction, n, 0, epoch, msg), f"{direction}:{msg.name}"
        )
        if dup_extra_us is not None:
            self._trace.record(
                "link", "fault", "duplicate", msg.req_id,
                dir=direction, n=n, msg=msg.name, extra_us=dup_extra_us,
            )
            self._sched.after_us(
                delay_us + dup_extra_us,
                lambda: self._arrive(direction, n, 1, epoch, msg),
                f"{direction}:{msg.name}:dup",
            )

    def _decide(self, direction: str, n: int) -> tuple[bool, int, int | None]:
        """Return ``(drop, delay_us, dup_extra_us)`` for one message."""
        prof = self.profile.link(direction)
        if self.plan is not None:
            mf = self.plan.message(direction, n)
            if mf is None:
                return False, prof.delay_us[0], None
            if mf.drop:
                return True, 0, None
            delay = mf.delay_us if mf.delay_us is not None else prof.delay_us[0]
            return False, delay, mf.dup_extra_us
        rng = self._rng[direction]
        # Fixed draw order: drop, delay, duplicate, duplicate extra delay.
        if rng.random() < prof.drop_p:
            return True, 0, None
        delay = rng.randint(*prof.delay_us)
        dup = rng.random() < prof.dup_p
        extra = rng.randint(*prof.dup_extra_us) if dup else None
        return False, delay, extra

    def _arrive(self, direction: str, n: int, copy: int, epoch: int, msg: Message) -> None:
        if not self.up or epoch != self.epoch:
            self._record_drop(direction, n, msg, DROP_CONNECTION_LOST, copy=copy)
            return
        receiver = _RECEIVER_OF_DIR[direction]
        self._trace.record(
            receiver, "recv", msg.name, msg.req_id,
            link={"dir": direction, "n": n, "copy": copy}, **msg.fields,
        )
        self._on_message[receiver](msg)

    def _record_drop(self, direction: str, n: int, msg: Message, reason: str, copy: int | None = None) -> None:
        data: dict[str, Any] = {"dir": direction, "n": n, "msg": msg.name, "reason": reason}
        if copy is not None:
            data["copy"] = copy
        self._trace.record("link", "fault", "drop", msg.req_id, **data)

    # -- connection --------------------------------------------------------------

    def _disconnect(self, duration_us: int) -> None:
        if not self.up:
            return
        self.up = False
        self.epoch += 1
        self._trace.record("link", "fault", "disconnect", duration_us=duration_us)
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
