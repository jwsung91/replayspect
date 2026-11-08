"""Virtual turntable integration: a turntable device and the robot-side client.

The protocol is described for planners in ``docs/protocol-turntable.md``.
In short (every message carries a ``req_id``):

* client -> device: ``TURN_LEFT``, ``TURN_RIGHT``, ``STATUS``
* device -> client: ``ACK``, ``DONE``, ``ERROR {reason}``, ``STATUS_REPLY {state}``

Device, correct behaviour:

1. On a turn request it first checks the result table. A known ``req_id``
   gets its stored result again (``ACK`` while in progress, ``DONE`` or
   ``ERROR`` with the stored reason once final) and nothing else happens. A
   new ``req_id`` is recorded as ``ACK``, acknowledged, and handed to step 2
   after ``PROC_US``.
2. Step 2 looks the (state, command) pair up in :data:`STEPS`. A turn moves
   one 90-degree step between ``LEFT``, ``INITIAL`` and ``RIGHT``. A pair
   in :data:`LIMITS` (already at the end in that direction) is refused with
   reason ``limit``; any other missing pair (the table is turning) with
   reason ``illegal``. Legal: ``motor_start``, the state changes to the
   ``TURNING_TO_*`` state, and after ``TURN_US`` ``motor_stop``, the state
   changes to the target, the result becomes ``DONE`` and ``DONE`` is sent.
3. The result table survives reconnects. After a reconnect the device sends
   nothing on its own; recovery is driven by the client.

Client, correct behaviour:

* At most one turn command is open at a time, issued in the fixed order
  :data:`SEQUENCE`. A failed command does not change the order. The next
  command is issued after the previous one reached a terminal outcome, plus
  a think time.
* Retries, timeouts, reply matching, reconnect resends and ``STATUS``
  polling are the same as the lift client (``replayspect.sut.lift``).

Trace schema written by the endpoints (the channel writes send/recv/fault):

* device ``state``: ``name`` is the new state, ``req_id`` the command that
  caused it (``None`` for the initial state), ``data = {"from", "on"}``
  where ``on`` is ``TURN_LEFT``, ``TURN_RIGHT``, ``arrived`` or ``init``.
* device ``effect``: ``motor_start {"dir"}`` (``left``/``right``) and
  ``motor_stop``, with ``req_id``.
* client ``handle``: as for the lift, ``data = {"msg_req_id", "cause"}``.

Mutants are flags that change behaviour only, never what gets recorded.
None are defined yet.
"""

from __future__ import annotations

from typing import Iterable

from replayspect.sim.link import Channel, ChannelProfile, FaultPlan, LinkProfile, Message
from replayspect.sim.scheduler import Handle, Scheduler
from replayspect.trace import Trace

PROC_US = 50_000
TURN_US = 3_000_000
ACK_TIMEOUT_US = 2_000_000
MAX_RETRIES = 2
DONE_TIMEOUT_US = 15_000_000
POLL_US = 1_000_000
THINK_US = (1_000_000, 3_000_000)

COMMANDS = ("TURN_LEFT", "TURN_RIGHT")
#: The client's commands, in order. From INITIAL it visits LEFT, INITIAL, RIGHT, INITIAL, LEFT, INITIAL.
SEQUENCE = ("TURN_LEFT", "TURN_RIGHT", "TURN_RIGHT", "TURN_LEFT", "TURN_LEFT", "TURN_RIGHT")
#: (state, command) -> (turning state, target, motor direction)
STEPS = {
    ("INITIAL", "TURN_LEFT"): ("TURNING_TO_LEFT", "LEFT", "left"),
    ("INITIAL", "TURN_RIGHT"): ("TURNING_TO_RIGHT", "RIGHT", "right"),
    ("LEFT", "TURN_RIGHT"): ("TURNING_TO_INITIAL", "INITIAL", "right"),
    ("RIGHT", "TURN_LEFT"): ("TURNING_TO_INITIAL", "INITIAL", "left"),
}
#: Refused with reason ``limit``: already at the end position in that direction.
LIMITS = {("LEFT", "TURN_LEFT"), ("RIGHT", "TURN_RIGHT")}

MUTANTS: dict[str, str] = {}

#: Random faults used for search: the same ranges as the lift.
SEARCH_PROFILE = ChannelProfile(
    c2s=LinkProfile(delay_us=(10_000, 1_500_000), drop_p=0.15, dup_p=0.15, dup_extra_us=(0, 4_000_000)),
    s2c=LinkProfile(delay_us=(10_000, 1_500_000), drop_p=0.15, dup_p=0.15, dup_extra_us=(0, 4_000_000)),
    disconnect_mean_interval_us=10_000_000,
    disconnect_duration_us=(200_000, 2_500_000),
)


class TurntableDevice:
    def __init__(self, sched: Scheduler, trace: Trace, ch: Channel, mutants: frozenset[str]) -> None:
        self.sched, self.trace, self.ch, self.m = sched, trace, ch, mutants
        self.state = "INITIAL"
        self.results: dict[str, str] = {}
        self.reasons: dict[str, str] = {}
        self.turn: Handle | None = None
        ch.attach("device", self.on_message, self.on_connection)
        trace.record("device", "state", "INITIAL", None, {"from": None, "on": "init"})

    def send(self, name: str, req_id: str, fields: dict | None = None) -> None:
        self.ch.send("device", Message(name, req_id, fields or {}))

    def set_state(self, new: str, on: str, req_id: str) -> None:
        old, self.state = self.state, new
        self.trace.record("device", "state", new, req_id, {"from": old, "on": on})

    # -- messages -------------------------------------------------------------

    def on_message(self, msg: Message) -> None:
        if msg.name == "STATUS":
            self.send("STATUS_REPLY", msg.req_id, {"state": self.state})
            return
        if msg.name not in COMMANDS:
            return
        r = msg.req_id
        if r in self.results:
            result = self.results[r]
            self.send(result, r, {"reason": self.reasons[r]} if result == "ERROR" else None)
            return
        self.results[r] = "ACK"
        self.send("ACK", r)
        self.sched.after_us(PROC_US, lambda: self.execute(msg.name, r), f"device:execute:{r}")

    def execute(self, cmd: str, r: str) -> None:
        step = STEPS.get((self.state, cmd))
        if step is None:
            reason = "limit" if (self.state, cmd) in LIMITS else "illegal"
            self.results[r], self.reasons[r] = "ERROR", reason
            self.send("ERROR", r, {"reason": reason})
            return
        turning, target, direction = step
        self.trace.record("device", "effect", "motor_start", r, {"dir": direction})
        self.set_state(turning, cmd, r)
        self.turn = self.sched.after_us(TURN_US, lambda: self.arrive(target, r), f"device:arrive:{r}")

    def arrive(self, target: str, r: str) -> None:
        self.turn = None
        self.trace.record("device", "effect", "motor_stop", r)
        self.set_state(target, "arrived", r)
        self.results[r] = "DONE"
        self.send("DONE", r)

    def on_connection(self, up: bool) -> None:
        pass


class TurntableClient:
    def __init__(
        self, sched: Scheduler, trace: Trace, ch: Channel, mutants: frozenset[str], n_commands: int
    ) -> None:
        if not 0 <= n_commands <= len(SEQUENCE):
            raise ValueError(f"n_commands must be 0..{len(SEQUENCE)}")
        self.sched, self.trace, self.ch, self.m = sched, trace, ch, mutants
        self.rng = sched.fork_rng("turntable/client")
        self.n_commands = n_commands
        self.issued = 0
        self.counters = {"r": 0, "s": 0}
        self.current: str | None = None
        self.cmd: str | None = None
        self.acked = False
        self.retries = 0
        self.timers: list[Handle] = []
        self.issue_scheduled = False
        ch.attach("client", self.on_message, self.on_connection)

    def new_id(self, prefix: str = "r") -> str:
        """Turn commands get ``r-NNNN``, status polls ``s-NNNN``, from separate counters."""
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
        self.cmd, self.current = SEQUENCE[self.issued], self.new_id()
        self.issued += 1
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
            self.ch.send("client", Message(self.cmd, r))
            self.timers.append(
                self.sched.after_us(ACK_TIMEOUT_US, lambda: self.ack_timeout(r), "client:ack_timeout")
            )
            return
        self.close("ERROR", None, "ack_timeout")

    def done_timeout(self, r: str) -> None:
        if self.current == r:
            self.close("ERROR", None, "done_timeout")

    def close(self, outcome: str, msg_req_id: str | None, cause: str) -> None:
        r = self.current
        self.trace.record("client", "handle", outcome, r, {"msg_req_id": msg_req_id, "cause": cause})
        for t in self.timers:
            t.cancel()
        self.timers = []
        self.current = None
        self.schedule_issue(self.rng.randint(*THINK_US))

    # -- messages -----------------------------------------------------------------

    def on_message(self, msg: Message) -> None:
        if self.current is None:
            return
        if msg.name == "ACK" and msg.req_id == self.current:
            self.acked = True
        elif msg.name in ("DONE", "ERROR") and msg.req_id == self.current:
            self.close(msg.name, msg.req_id, "reply")

    def on_connection(self, up: bool) -> None:
        if up and self.current is not None:
            self.ch.send("client", Message(self.cmd, self.current))

    def poll(self) -> None:
        self.ch.send("client", Message("STATUS", self.new_id("s")))
        self.sched.after_us(POLL_US, self.poll, "client:poll")


def run_turntable(
    seed: int,
    profile: ChannelProfile | None = SEARCH_PROFILE,
    plan: FaultPlan | None = None,
    mutants: Iterable[str] = (),
    n_commands: int = len(SEQUENCE),
    until_us: int = 90_000_000,
) -> Trace:
    """Run one turntable integration and return its trace."""
    ms = frozenset(mutants)
    unknown = ms - MUTANTS.keys()
    if unknown:
        raise ValueError(f"unknown mutants: {sorted(unknown)}")
    sched = Scheduler(seed)
    trace = Trace(lambda: sched.now_us)
    ch = Channel(sched, trace, profile, plan)
    TurntableDevice(sched, trace, ch, ms)
    client = TurntableClient(sched, trace, ch, ms, n_commands)
    ch.start()
    client.start()
    sched.run_until_us(until_us)
    return trace
