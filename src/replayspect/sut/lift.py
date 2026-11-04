"""Virtual lift integration: a lift device and the robot-side client.

Protocol (every message carries a ``req_id``):

* client -> device: ``MOVE_UP``, ``MOVE_DOWN``, ``STATUS``
* device -> client: ``ACK``, ``DONE``, ``ERROR {reason}``, ``STATUS_REPLY {state}``

Device, correct behaviour:

1. On a move request it first checks the result table. A known ``req_id``
   gets its stored result again (``ACK`` while in progress, ``DONE`` or
   ``ERROR`` once final) and nothing else happens. A new ``req_id`` is
   recorded as ``ACK``, acknowledged, and handed to step 2 after
   ``PROC_US``.
2. Step 2 checks legality against the current state. ``MOVE_UP`` is legal
   only in ``DOWN`` and ``MOVE_DOWN`` only in ``UP``. Illegal: the result
   becomes ``ERROR`` and ``ERROR`` is sent. Legal: ``motor_start``, the state
   changes to ``MOVING_*``, and after ``TRAVEL_US`` ``motor_stop``, the state
   changes to ``UP``/``DOWN``, the result becomes ``DONE`` and ``DONE`` is sent.
3. The result table survives reconnects. After a reconnect the device sends
   nothing on its own; recovery is driven by the client.

Client, correct behaviour:

* At most one move command is open at a time. The next command is issued
  after the previous one reached a terminal outcome, plus a think time.
* No ``ACK`` within ``ACK_TIMEOUT_US``: resend the **same** ``req_id``, at most
  ``MAX_RETRIES`` times, then give up with ``ERROR`` (cause ``ack_timeout``).
* No ``DONE``/``ERROR`` within ``DONE_TIMEOUT_US`` of the first send: give up
  with ``ERROR`` (cause ``done_timeout``).
* A ``DONE``/``ERROR`` counts only if its ``req_id`` is the open command;
  anything else is ignored. A terminal outcome closes the command.
* After a reconnect, resend the open command with the same ``req_id``.
* ``STATUS`` is polled every ``POLL_US``; replies are not acted on.

Trace schema written by the endpoints (the channel writes send/recv/fault):

* device ``state``: ``name`` is the new state, ``req_id`` the command that
  caused it (``None`` for the initial state), ``data = {"from", "on"}``
  where ``on`` is ``MOVE_UP``, ``MOVE_DOWN``, ``arrived`` or ``init``.
  The device's current state is the ``name`` of its latest ``state`` event.
* device ``effect``: ``motor_start {"dir"}`` and ``motor_stop``, with ``req_id``.
* client ``handle``: ``name`` is ``DONE`` or ``ERROR``, ``req_id`` the command
  being closed, ``data = {"msg_req_id", "cause"}`` where ``msg_req_id`` is the
  ``req_id`` of the message that triggered it (``None`` for timeouts) and
  ``cause`` is ``reply``, ``ack_timeout`` or ``done_timeout``.

Mutants are flags that change behaviour only, never what gets recorded, so
the trace stays an honest record of what a buggy implementation did.
"""

from __future__ import annotations

from typing import Iterable

from replayspect.sim.link import Channel, ChannelProfile, FaultPlan, LinkProfile, Message
from replayspect.sim.scheduler import Handle, Scheduler
from replayspect.trace import Trace

PROC_US = 50_000
TRAVEL_US = 3_000_000
ACK_TIMEOUT_US = 2_000_000
MAX_RETRIES = 2
DONE_TIMEOUT_US = 15_000_000
POLL_US = 1_000_000
THINK_US = (1_000_000, 3_000_000)

MOVES = {"MOVE_UP": ("DOWN", "MOVING_UP", "UP", "up"), "MOVE_DOWN": ("UP", "MOVING_DOWN", "DOWN", "down")}
OPPOSITE_WHILE_MOVING = {"MOVE_UP": "MOVING_DOWN", "MOVE_DOWN": "MOVING_UP"}

MUTANTS = {
    "M1": "device: no duplicate detection; every request is treated as new",
    "M2": "device: records a request id only when it completes (DONE), not when it is accepted",
    "M3": "device: after a reconnect, resends the last DONE without being asked",
    "M4": "device: accepts a move in the opposite direction while moving",
    "M5": "device: STATUS during a move reports the state before the move",
    "M6": "client: a retry gets a new req_id instead of reusing the original",
    "M7": "client: any DONE completes the open command, whatever its req_id",
    "M8": "client: after an ack timeout, keeps the command open until the next one starts",
}

#: Random faults used for mutant search. Delays and duplicate offsets reach
#: past the ACK timeout and the travel time, so late and stale messages occur.
SEARCH_PROFILE = ChannelProfile(
    c2s=LinkProfile(delay_us=(10_000, 1_500_000), drop_p=0.15, dup_p=0.15, dup_extra_us=(0, 4_000_000)),
    s2c=LinkProfile(delay_us=(10_000, 1_500_000), drop_p=0.15, dup_p=0.15, dup_extra_us=(0, 4_000_000)),
    disconnect_mean_interval_us=10_000_000,
    disconnect_duration_us=(200_000, 2_500_000),
)


class LiftDevice:
    def __init__(self, sched: Scheduler, trace: Trace, ch: Channel, mutants: frozenset[str]) -> None:
        self.sched, self.trace, self.ch, self.m = sched, trace, ch, mutants
        self.state = "DOWN"
        self.stable = "DOWN"  # last non-moving state, used by M5
        self.results: dict[str, str] = {}
        self.last_done: str | None = None
        self.travel: Handle | None = None
        ch.attach("device", self.on_message, self.on_connection)
        trace.record("device", "state", "DOWN", None, {"from": None, "on": "init"})

    def send(self, name: str, req_id: str, fields: dict | None = None) -> None:
        self.ch.send("device", Message(name, req_id, fields or {}))

    def set_state(self, new: str, on: str, req_id: str) -> None:
        old, self.state = self.state, new
        if not new.startswith("MOVING"):
            self.stable = new
        self.trace.record("device", "state", new, req_id, {"from": old, "on": on})

    # -- messages -------------------------------------------------------------

    def on_message(self, msg: Message) -> None:
        if msg.name == "STATUS":
            state = self.stable if "M5" in self.m else self.state
            self.send("STATUS_REPLY", msg.req_id, {"state": state})
            return
        if msg.name not in MOVES:
            return
        r = msg.req_id
        if "M1" not in self.m and r in self.results:
            result = self.results[r]
            self.send(result, r, {"reason": "illegal"} if result == "ERROR" else None)
            return
        if "M2" not in self.m:
            self.results[r] = "ACK"
        self.send("ACK", r)
        self.sched.after_us(PROC_US, lambda: self.execute(msg.name, r), f"device:execute:{r}")

    def execute(self, cmd: str, r: str) -> None:
        need, moving, _, direction = MOVES[cmd]
        legal = self.state == need
        if "M4" in self.m and self.state == OPPOSITE_WHILE_MOVING[cmd]:
            legal = True
            if self.travel is not None:
                self.travel.cancel()
        if not legal:
            self.results[r] = "ERROR"
            self.send("ERROR", r, {"reason": "illegal"})
            return
        self.trace.record("device", "effect", "motor_start", r, {"dir": direction})
        self.set_state(moving, cmd, r)
        self.travel = self.sched.after_us(TRAVEL_US, lambda: self.arrive(cmd, r), f"device:arrive:{r}")

    def arrive(self, cmd: str, r: str) -> None:
        self.travel = None
        self.trace.record("device", "effect", "motor_stop", r)
        self.set_state(MOVES[cmd][2], "arrived", r)
        self.results[r] = "DONE"
        self.last_done = r
        self.send("DONE", r)

    def on_connection(self, up: bool) -> None:
        if up and "M3" in self.m and self.last_done is not None:
            self.send("DONE", self.last_done)


class LiftClient:
    def __init__(
        self, sched: Scheduler, trace: Trace, ch: Channel, mutants: frozenset[str], n_commands: int
    ) -> None:
        self.sched, self.trace, self.ch, self.m = sched, trace, ch, mutants
        self.rng = sched.fork_rng("lift/client")
        self.n_commands = n_commands
        self.issued = 0
        self.counters = {"r": 0, "s": 0}
        self.want = "MOVE_UP"
        self.current: str | None = None
        self.cmd: str | None = None
        self.acked = False
        self.retries = 0
        self.timers: list[Handle] = []
        self.issue_scheduled = False
        ch.attach("client", self.on_message, self.on_connection)

    def new_id(self, prefix: str = "r") -> str:
        """Move commands get ``r-NNNN``, status polls ``s-NNNN``, from separate counters."""
        self.counters[prefix] += 1
        return f"{prefix}-{self.counters[prefix]:04d}"

    def start(self) -> None:
        self.schedule_issue(0)
        self.sched.after_us(POLL_US, self.poll, "client:poll")

    def schedule_issue(self, delay_us: int) -> None:
        if not self.issue_scheduled:
            self.issue_scheduled = True
            self.sched.after_us(delay_us, self.issue, "client:issue")

    # -- commands ---------------------------------------------------------------

    def issue(self) -> None:
        self.issue_scheduled = False
        if self.issued >= self.n_commands:
            return
        self.issued += 1
        self.cmd, self.current = self.want, self.new_id()
        self.want = "MOVE_DOWN" if self.want == "MOVE_UP" else "MOVE_UP"
        self.acked, self.retries = False, 0
        self.ch.send("client", Message(self.cmd, self.current))
        r = self.current
        self.timers = [
            self.sched.after_us(ACK_TIMEOUT_US, lambda: self.ack_timeout(r), "client:ack_timeout"),
            self.sched.after_us(DONE_TIMEOUT_US, lambda: self.done_timeout(r), "client:done_timeout"),
        ]

    def ack_timeout(self, r: str) -> None:
        if self.current != r or self.acked:
            return
        if self.retries < MAX_RETRIES:
            self.retries += 1
            if "M6" in self.m:
                self.current = r = self.new_id()
            self.ch.send("client", Message(self.cmd, r))
            self.timers.append(
                self.sched.after_us(ACK_TIMEOUT_US, lambda: self.ack_timeout(r), "client:ack_timeout")
            )
            return
        self.close("ERROR", None, "ack_timeout", keep_open="M8" in self.m)

    def done_timeout(self, r: str) -> None:
        if self.current == r:
            self.close("ERROR", None, "done_timeout")

    def close(self, outcome: str, msg_req_id: str | None, cause: str, keep_open: bool = False) -> None:
        r = self.current
        self.trace.record("client", "handle", outcome, r, {"msg_req_id": msg_req_id, "cause": cause})
        for t in self.timers:
            t.cancel()
        self.timers = []
        if not keep_open:
            self.current = None
        self.schedule_issue(self.rng.randint(*THINK_US))

    # -- messages -----------------------------------------------------------------

    def on_message(self, msg: Message) -> None:
        if self.current is None:
            return
        if msg.name == "ACK" and msg.req_id == self.current:
            self.acked = True
        elif msg.name in ("DONE", "ERROR"):
            if msg.req_id == self.current or ("M7" in self.m and msg.name == "DONE"):
                self.close(msg.name, msg.req_id, "reply")

    def on_connection(self, up: bool) -> None:
        if up and self.current is not None:
            self.ch.send("client", Message(self.cmd, self.current))

    def poll(self) -> None:
        self.ch.send("client", Message("STATUS", self.new_id("s")))
        self.sched.after_us(POLL_US, self.poll, "client:poll")


def run_lift(
    seed: int,
    profile: ChannelProfile | None = SEARCH_PROFILE,
    plan: FaultPlan | None = None,
    mutants: Iterable[str] = (),
    n_commands: int = 6,
    until_us: int = 90_000_000,
) -> Trace:
    """Run one lift integration and return its trace."""
    ms = frozenset(mutants)
    unknown = ms - MUTANTS.keys()
    if unknown:
        raise ValueError(f"unknown mutants: {sorted(unknown)}")
    sched = Scheduler(seed)
    trace = Trace(lambda: sched.now_us)
    ch = Channel(sched, trace, profile, plan)
    LiftDevice(sched, trace, ch, ms)
    client = LiftClient(sched, trace, ch, ms, n_commands)
    ch.start()
    client.start()
    sched.run_until_us(until_us)
    return trace
