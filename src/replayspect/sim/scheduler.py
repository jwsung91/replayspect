"""Deterministic virtual-time scheduler.

All simulated activity in replayspect runs through one :class:`Scheduler`.
There are no threads, no wall clock, and no sockets: an action runs only when
the scheduler pops it off its queue, and every random draw comes from the
scheduler's seeded RNG. Given the same seed and the same code, a run is
therefore exactly repeatable.

Time is kept as integer microseconds so that ordering never depends on float
rounding. Actions scheduled for the same instant run in the order they were
scheduled (FIFO), fixed by a monotonically increasing sequence number.
"""

from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field
from typing import Callable

Action = Callable[[], None]

US_PER_S = 1_000_000


def seconds_to_us(seconds: float) -> int:
    """Convert seconds to integer microseconds (round half to even)."""
    return round(seconds * US_PER_S)


@dataclass(order=True)
class _Entry:
    time_us: int
    seq: int
    action: Action = field(compare=False)
    label: str = field(compare=False, default="")
    cancelled: bool = field(compare=False, default=False)


class Handle:
    """A scheduled action that can be cancelled before it runs."""

    __slots__ = ("_entry",)

    def __init__(self, entry: _Entry) -> None:
        self._entry = entry

    @property
    def time_us(self) -> int:
        return self._entry.time_us

    @property
    def label(self) -> str:
        return self._entry.label

    @property
    def cancelled(self) -> bool:
        return self._entry.cancelled

    def cancel(self) -> None:
        """Cancel the action. Cancelling twice, or after it ran, is a no-op."""
        self._entry.cancelled = True


class SchedulerError(RuntimeError):
    """Raised on misuse of the scheduler, such as scheduling in the past."""


class Scheduler:
    """Priority queue of ``(time, seq, action)`` driven by virtual time."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self._now_us = 0
        self._seq = 0
        self._queue: list[_Entry] = []

    # -- clock ---------------------------------------------------------------

    @property
    def now_us(self) -> int:
        return self._now_us

    @property
    def now(self) -> float:
        """Current virtual time in seconds (for display; use now_us for logic)."""
        return self._now_us / US_PER_S

    # -- scheduling ------------------------------------------------------------

    def at_us(self, time_us: int, action: Action, label: str = "") -> Handle:
        """Schedule ``action`` at absolute virtual time ``time_us``."""
        if time_us < self._now_us:
            raise SchedulerError(
                f"cannot schedule {label!r} at {time_us}us; now is {self._now_us}us"
            )
        entry = _Entry(time_us, self._seq, action, label)
        self._seq += 1
        heapq.heappush(self._queue, entry)
        return Handle(entry)

    def at(self, time_s: float, action: Action, label: str = "") -> Handle:
        """Schedule ``action`` at absolute virtual time ``time_s`` seconds."""
        return self.at_us(seconds_to_us(time_s), action, label)

    def after_us(self, delay_us: int, action: Action, label: str = "") -> Handle:
        """Schedule ``action`` ``delay_us`` microseconds from now."""
        if delay_us < 0:
            raise SchedulerError(f"negative delay {delay_us}us for {label!r}")
        return self.at_us(self._now_us + delay_us, action, label)

    def after(self, delay_s: float, action: Action, label: str = "") -> Handle:
        """Schedule ``action`` ``delay_s`` seconds from now."""
        return self.after_us(seconds_to_us(delay_s), action, label)

    # -- running ---------------------------------------------------------------

    def pending(self) -> int:
        """Number of scheduled, not-cancelled actions."""
        return sum(1 for e in self._queue if not e.cancelled)

    def step(self) -> bool:
        """Run the next live action. Returns False when the queue is empty."""
        while self._queue:
            entry = heapq.heappop(self._queue)
            if entry.cancelled:
                continue
            self._now_us = entry.time_us
            entry.action()
            return True
        return False

    def run_until_us(self, end_us: int, max_actions: int = 1_000_000) -> int:
        """Run every action scheduled at or before ``end_us``.

        Afterwards the clock reads ``end_us`` even if the queue ran dry
        earlier: virtual time keeps passing when nothing happens. Returns the
        number of actions executed. ``max_actions`` guards against actions
        that keep rescheduling themselves at the same instant.
        """
        if end_us < self._now_us:
            raise SchedulerError(f"run_until {end_us}us is before now {self._now_us}us")
        executed = 0
        while self._queue:
            head = self._queue[0]
            if head.cancelled:
                heapq.heappop(self._queue)
                continue
            if head.time_us > end_us:
                break
            if executed >= max_actions:
                raise SchedulerError(
                    f"exceeded max_actions={max_actions} before {end_us}us; "
                    "is something rescheduling itself without advancing time?"
                )
            self.step()
            executed += 1
        self._now_us = end_us
        return executed

    def run_until(self, end_s: float, max_actions: int = 1_000_000) -> int:
        """Seconds-based form of :meth:`run_until_us`."""
        return self.run_until_us(seconds_to_us(end_s), max_actions)
