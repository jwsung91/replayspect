"""Driven replay (WP5b): reproduce one participant's log without a seed.

A log from one side fixes what that side did: what it sent and when, and its own decisions.
Driven replay keeps those as facts and simulates only the other side:

* the **script** (:class:`ScriptedEndpoint`) takes the logged participant's place on the
  channel. It sends every recorded message at its recorded time and records the participant's
  own decisions (``handle``, ``state``, ``effect``) at theirs. Its message and connection
  callbacks do nothing: retries and resends are in the log already. Recorded receives are not
  scheduled; producing them is the simulation's job.
* the **other side** is the system's device model (``System.device``), on the package's
  scheduler and channel.
* the **link** follows a fault plan. With ``base: fixed`` an unplanned delay is the profile
  minimum, so nothing in the run is drawn from a seed: the device models draw no random numbers,
  and the script replaces the only participant that did. The scheduler's seed is fixed
  (:data:`DRIVEN_SEED`) and unused; the tests check that another seed gives the same digest.

The log's times are the simulation's times (one source, so there is no clock to correct). The
script covers the client side; a device-side log would need the client's schedule inferred.

Fidelity: the script's facts are ``exact``; everything the models produced (the device, the
link, and the receives on the scripted side) is ``reconstructed``.

**The judge** compares the scripted side's receives only, polls left out. The script's sends and
decisions are in both traces by construction, so they prove nothing, and at an equal time a
scheduled fact can come before a simulated arrival, which would make a positional comparison
fail for no reason. Receives match when kind, name, request id and data (without ``link``)
agree, in order, and each is within the tolerance of its log line. When the expected violated
contracts are known (an existing incident) they must agree too.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Sequence

from replayspect.contract import judge
from replayspect.incident import TOLERANCE_US, line_key, run_view, status_sequence
from replayspect.reconstruct import Feedback, Limits, Result, empty_plan, reconstruct
from replayspect.runner import System
from replayspect.sim.link import Channel, FaultPlan, Message
from replayspect.sim.scheduler import Scheduler
from replayspect.trace import Event, Trace

#: The scheduler seed of every driven run. Nothing draws from it (see the module docstring).
DRIVEN_SEED = 0
#: Event kinds the script records as facts (sends go through the channel).
FACT_KINDS = ("handle", "state", "effect")
#: Default split of a round trip between the request (c2s) and the reply (s2c).
DEFAULT_SPLIT = 0.5


class DrivenError(ValueError):
    pass


# -- the script -----------------------------------------------------------------------------


def script_events(log: Sequence[Event], actor: str) -> list[Event]:
    """The logged participant's events; refuses a log with other participants in it."""
    others = sorted({e.actor for e in log if e.actor != actor})
    if others:
        raise DrivenError(f"driven replay takes one participant's log; this one also has {', '.join(others)}")
    if not any(e.kind == "send" for e in log):
        raise DrivenError(f"the log has no messages sent by {actor}")
    return list(log)


class ScriptedEndpoint:
    """Takes ``actor``'s place on the channel and replays its recorded sends and decisions.

    A recorded event runs **after everything already due at its instant**: it is scheduled at its
    time and, when that time comes, scheduled again at the same time, behind what is queued
    there. A participant usually acts in response to something at that instant (a reconnect it
    resends on, a reply it closes a command on), so its action must not overtake the cause; in
    the log the cause is not visible. Recorded events keep their log order among themselves.
    """

    def __init__(self, sched: Scheduler, trace: Trace, ch: Channel, actor: str, events: Sequence[Event]) -> None:
        ch.attach(actor, lambda msg: None, lambda up: None)
        for ev in events:
            if ev.kind == "send":
                fields = {k: v for k, v in ev.data.items() if k != "link"}
                msg = Message(ev.name, ev.req_id, fields)
                action = (lambda m=msg: ch.send(actor, m))
                label = f"script:send:{ev.name}"
            elif ev.kind in FACT_KINDS:
                data = {k: v for k, v in ev.data.items() if k != "link"}
                action = (lambda e=ev, d=data: trace.record(actor, e.kind, e.name, e.req_id, d))
                label = f"script:{ev.kind}:{ev.name}"
            else:
                continue  # recv: what the simulation has to produce; fault: the link's, not a participant's
            sched.at_us(ev.t_us, lambda t=ev.t_us, a=action, lb=label: sched.at_us(t, a, lb), label + ":due")


def run_driven(system: System, log: Sequence[Event], plan: FaultPlan, until_us: int,
               mutants: Sequence[str] = (), actor: str = "client", seed: int = DRIVEN_SEED) -> Trace:
    """Run the device model against the scripted ``actor`` (``seed`` exists for the seed-blindness test)."""
    if actor != "client":
        raise DrivenError("driven replay scripts the client side; a device-side log needs the client's "
                          "schedule inferred (later work)")
    if system.device is None:
        raise DrivenError(f"{system.name} has no device model for driven replay"
                          + (" (the variant gives no device)" if system.variant is not None else ""))
    events = script_events(log, actor)
    if events and events[-1].t_us > until_us:
        raise DrivenError(f"the log runs to {events[-1].t_us}us, past the run end {until_us}us")
    sched = Scheduler(seed)
    trace = Trace(lambda: sched.now_us)
    ch = Channel(sched, trace, system.profile, plan)
    system.device(sched, trace, ch, tuple(sorted(mutants)))
    ScriptedEndpoint(sched, trace, ch, actor, events)
    ch.start()
    sched.run_until_us(until_us)
    return Trace.from_events(_relabel(trace.events, actor))


def _relabel(events: Sequence[Event], actor: str) -> list[Event]:
    out = []
    for e in events:
        fact = e.actor == actor and e.kind != "recv"
        out.append(e if fact else replace(e, fidelity="reconstructed"))
    return out


# -- the judge ------------------------------------------------------------------------------


def compared_receives(events: Sequence[Event], actor: str, quiet: frozenset[str]) -> list[Event]:
    return [e for e in events if e.actor == actor and e.kind == "recv" and e.name not in quiet]


@dataclass(frozen=True)
class DrivenMatch:
    reproduced: bool
    matched: int  # receives equal from the start, before the first mismatch
    total: int  # receives in the log
    max_dt_us: int | None  # largest time difference when every receive matches in kind and order
    contracts_same: bool | None  # None when no expectation was given
    status_same: bool | None  # None unless the poll replies are compared
    first: dict[str, Any] | None  # the first mismatch
    pairs: tuple[tuple[Event, Event], ...]  # (log receive, simulated receive) for the matched ones


def _show(ev: Event | None) -> str | None:
    if ev is None:
        return None
    data = {k: v for k, v in ev.data.items() if k != "link"}
    return f"recv {ev.name} {ev.req_id or '-'}" + (f" {data}" if data else "") + f" at {ev.t_us / 1e6:.6f}s"


def driven_match(log: Sequence[Event], run: Sequence[Event], actor: str, quiet: frozenset[str],
                 tolerance_us: int = TOLERANCE_US, horizon_us: int | None = None,
                 violated: set[str] | None = None, expect: set[str] | None = None,
                 poll_reply: str | None = None) -> DrivenMatch:
    """Compare the scripted side's receives (see the module docstring).

    ``horizon_us``: simulated receives after it are not compared (default: the log's last event
    plus the tolerance). ``expect``/``violated``: the expected and the run's violated contracts.
    ``poll_reply``: also compare the sequence of poll replies (the WP4 status rule).
    """
    want = compared_receives(log, actor, quiet)
    end = horizon_us if horizon_us is not None else (log[-1].t_us + tolerance_us if log else 0)
    got = [e for e in compared_receives(run, actor, quiet) if e.t_us <= end]
    matched, first, pairs = 0, None, []
    for i, w in enumerate(want):
        g = got[i] if i < len(got) else None
        if g is None or line_key(w) != line_key(g) or abs(w.t_us - g.t_us) > tolerance_us:
            first = {"index": i, "line": (w.log or {}).get("line"), "expected": _show(w), "got": _show(g)}
            break
        matched += 1
        pairs.append((w, g))
    if first is None and len(got) > len(want):
        first = {"index": len(want), "line": None, "expected": None, "got": _show(got[len(want)])}
    same = len(want) == len(got) and all(line_key(w) == line_key(g) for w, g in zip(want, got))
    max_dt = max((abs(w.t_us - g.t_us) for w, g in zip(want, got)), default=0) if same else None
    contracts_same = None if expect is None else (violated == expect)
    status_same = None
    if poll_reply is not None:
        status_same = status_sequence(log, actor, poll_reply) == status_sequence(
            [e for e in run if e.t_us <= end], actor, poll_reply)
    ok = same and max_dt is not None and max_dt <= tolerance_us
    reproduced = ok and contracts_same is not False and status_same is not False
    return DrivenMatch(reproduced, matched, len(want), max_dt, contracts_same, status_same, first, tuple(pairs))


def annotate(run: Sequence[Event], m: DrivenMatch) -> list[Event]:
    """The run with each matched simulated receive carrying its log line (``log.line``)."""
    lines = {id(g): (w.log or {}).get("line") for w, g in m.pairs}
    out = []
    for e in run:
        line = lines.get(id(e))
        out.append(replace(e, log={"line": line}) if line is not None else e)
    return out


# -- a driven session: what the reader and the command line use -----------------------------


@dataclass
class DrivenSetup:
    system: System
    log: list[Event]
    until_us: int
    mutants: tuple[str, ...] = ()
    actor: str = "client"
    tolerance_us: int = TOLERANCE_US
    expect: set[str] | None = None
    status_rule: bool = False

    @property
    def horizon_us(self) -> int:
        return (self.log[-1].t_us if self.log else 0) + self.tolerance_us

    def run(self, plan: FaultPlan | Mapping[str, Any], seed: int = DRIVEN_SEED) -> tuple[Trace, DrivenMatch]:
        fp = plan if isinstance(plan, FaultPlan) else FaultPlan.from_dict(dict(plan))
        trace = run_driven(self.system, self.log, fp, self.until_us, self.mutants, self.actor, seed)
        violated = None
        if self.expect is not None:
            violated = {v.contract for v in judge(trace, self.system.contracts(), self.until_us)}
        vocab = self.system.vocabulary
        poll_reply = (vocab.poll_reply if vocab is not None else "STATUS_REPLY") if self.status_rule else None
        m = driven_match(self.log, trace.events, self.actor, self.system.quiet_messages, self.tolerance_us,
                         self.horizon_us, violated, self.expect, poll_reply)
        return trace, m

    def limits(self, max_faults: int = 20) -> Limits:
        p = self.system.profile
        return Limits({"c2s": p.c2s.delay_us, "s2c": p.s2c.delay_us},
                      {"c2s": p.c2s.dup_extra_us, "s2c": p.s2c.dup_extra_us},
                      p.disconnect_duration_us, self.until_us, max_faults)

    def oracle(self, budget: int) -> Callable[[dict[str, Any]], Feedback | None]:
        used = [0]

        def run(plan: dict[str, Any]) -> Feedback | None:
            if used[0] >= budget:
                return None
            used[0] += 1
            trace, m = self.run(plan)
            return Feedback(m.reproduced, m.matched, run_view(trace, self.actor))

        return run


# -- round-trip initialisation ----------------------------------------------------------------


def round_trips(log: Sequence[Event], actor: str, replies: Sequence[str]) -> list[tuple[dict, dict, int]]:
    """``(request key, reply key, round trip us)`` for each logged prompt reply.

    A prompt reply (``replies``, e.g. ``ACK``) is sent by the other side as soon as the request
    arrives, so its receive time minus the request's send time is the request's delay plus the
    reply's. The j-th receive of a reply ``(name, req_id)`` is taken as that reply's ``k = j``,
    answering the j-th send of the request (the other side answers each attempt in turn); if that
    send came after the receive, it answers the latest send before it.
    """
    out = []
    sends: list[Event] = []
    k_send: dict[tuple, int] = {}
    k_recv: dict[tuple, int] = {}
    keys_of: dict[int, dict] = {}
    for e in log:
        if e.actor != actor:
            continue
        if e.kind == "send":
            kk = (e.name, e.req_id)
            keys_of[id(e)] = {"dir": "c2s", "msg": e.name, "req_id": e.req_id, "k": k_send.get(kk, 0)}
            k_send[kk] = k_send.get(kk, 0) + 1
            sends.append(e)
        elif e.kind == "recv" and e.name in replies and e.req_id is not None:
            kk = (e.name, e.req_id)
            j = k_recv.get(kk, 0)
            k_recv[kk] = j + 1
            attempts = [s for s in sends if s.req_id == e.req_id and s.t_us <= e.t_us]
            req = attempts[j] if j < len(attempts) else (attempts[-1] if attempts else None)
            if req is None:
                continue
            out.append((keys_of[id(req)], {"dir": "s2c", "msg": e.name, "req_id": e.req_id, "k": j},
                        e.t_us - req.t_us))
    return out


def rtt_start_plan(log: Sequence[Event], actor: str, limits: Limits, replies: Sequence[str] = ("ACK",),
                   split: float = DEFAULT_SPLIT) -> dict[str, Any]:
    """A ``base: fixed`` plan whose delays split each round trip: ``split`` to the request.

    A request keeps the delay of its first answered round trip. A round trip too short for the
    two minimum delays is skipped; one that would need a delay beyond its range is clamped.
    """
    if not 0.0 <= split <= 1.0:
        raise ValueError(f"split must be between 0 and 1, got {split}")
    plan = empty_plan("fixed")
    seen: set[tuple] = set()
    (clo, chi), (slo, shi) = limits.delay_us["c2s"], limits.delay_us["s2c"]
    for req, rep, rtt in round_trips(log, actor, replies):
        if rtt < clo + slo:
            continue
        rk = (req["msg"], req["req_id"], req["k"])
        if rk in seen:
            c2s = next(d["delay_us"] for d in plan["delays"] if d["dir"] == "c2s"
                       and (d["msg"], d["req_id"], d["k"]) == rk)
        else:
            c2s = min(max(round(rtt * split), clo, rtt - shi), chi, rtt - slo)
            seen.add(rk)
            plan["delays"].append({**req, "delay_us": int(c2s)})
        s2c = rtt - c2s
        if slo <= s2c <= shi:
            plan["delays"].append({**rep, "delay_us": int(s2c)})
    return plan


# -- reconstruction and the split diagnostic ----------------------------------------------------

_KEY = ("dir", "msg", "req_id", "k")


def _same(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return all(a[x] == b[x] for x in _KEY)


def _delay_of(plan: Mapping[str, Any], key: Mapping[str, Any], default: int) -> int:
    return next((d["delay_us"] for d in plan["delays"] if _same(d, key)), default)


def _set_delays(plan: Mapping[str, Any], items: Sequence[tuple[Mapping[str, Any], int]]) -> dict[str, Any]:
    keep = [d for d in plan["delays"] if not any(_same(d, k) for k, _ in items)]
    return {**plan, "delays": keep + [{**{x: k[x] for x in _KEY}, "delay_us": int(v)} for k, v in items]}


def shift_split(plan: Mapping[str, Any], req: Mapping[str, Any], rep: Mapping[str, Any], delta: int,
                limits: Limits, later_replies: bool = False) -> dict[str, Any] | None:
    """Move ``delta`` of a round trip from the reply to the request: the request arrives ``delta``
    later and the prompt reply still comes back at the same time. With ``later_replies``, every
    other reply to the same request id already in the plan (``DONE``, ``ERROR``) gets ``delta``
    less delay too, so its receive time stays put. None when a delay would leave its range."""
    (clo, chi), (slo, shi) = limits.delay_us["c2s"], limits.delay_us["s2c"]
    c2s = _delay_of(plan, req, clo) + delta
    s2c = _delay_of(plan, rep, slo) - delta
    if not (clo <= c2s <= chi and slo <= s2c <= shi):
        return None
    items: list[tuple[Mapping[str, Any], int]] = [(req, c2s), (rep, s2c)]
    if later_replies:
        for d in plan["delays"]:
            if d["dir"] == "s2c" and d["req_id"] == req["req_id"] and d["msg"] != rep["msg"]:
                v = d["delay_us"] - delta
                if not slo <= v <= shi:
                    return None
                items.append((d, v))
    return _set_delays(plan, items)


def split_edits(log: Sequence[Event], actor: str, limits: Limits, replies: Sequence[str] = ("ACK",)):
    """Candidate edits for the reader: shift a round trip's split so a later reply moves (see
    :func:`shift_split`). Used with the round-trip start plan."""
    trips = round_trips(log, actor, replies)
    (clo, chi), (slo, shi) = limits.delay_us["c2s"], limits.delay_us["s2c"]

    def extra(plan: dict[str, Any], g: Event, d: int):
        if g.name in replies:
            return  # the prompt reply itself: its round trip is wrong, not its split
        for req, rep, rtt in trips:
            if req["req_id"] != g.req_id:
                continue
            c2s = _delay_of(plan, req, clo)
            for name, delta in (("by the difference", d), ("to the request's maximum", min(chi, rtt - slo) - c2s),
                                ("to the request's minimum", max(clo, rtt - shi) - c2s)):
                if delta == 0:
                    continue
                new = shift_split(plan, req, rep, delta, limits)
                if new is not None:
                    yield (f"adjust split of {req['msg']} {req['req_id']} k={req['k']} {name} "
                           f"({delta / 1e6:+.3f}s)", new)

    return extra


def driven_reconstruct(setup: DrivenSetup, budget: int = 120, rtt: bool = False, split: float = DEFAULT_SPLIT,
                       replies: Sequence[str] = ("ACK",), max_faults: int = 20, **search: Any) -> Result:
    """The rule-based reader (:mod:`replayspect.reconstruct`) against driven runs.

    The clock is known (the log's times are the run's), only receives are compared, and the
    start plan is ``base: fixed``. Without ``rtt`` it starts empty and the reader is unchanged.
    With ``rtt`` it starts from the round-trip delays (:func:`rtt_start_plan`) and may also shift
    a round trip's split (:func:`split_edits`); the start entries are counted apart from search
    edits.
    """
    limits = setup.limits(max_faults)
    vocab = setup.system.vocabulary
    polls = (vocab.poll_request, vocab.poll_reply) if vocab is not None else ("STATUS", "STATUS_REPLY")
    start = rtt_start_plan(setup.log, setup.actor, limits, replies, split) if rtt else empty_plan("fixed")
    extra = split_edits(setup.log, setup.actor, limits, replies) if rtt else None
    return reconstruct(setup.log, setup.actor, setup.system.quiet_messages, polls, limits, setup.oracle(budget),
                       clock_known=True, start=start, kinds=frozenset({"recv"}), extra=extra, **search)


@dataclass(frozen=True)
class SplitSensitivity:
    pairs: int  # request/prompt-reply pairs with at least one feasible extreme
    sensitive: int  # pairs where an extreme split breaks the reproduction
    keys: tuple[str, ...]  # the sensitive pairs, as "MSG req_id k"


def split_sensitivity(setup: DrivenSetup, plan: Mapping[str, Any], replies: Sequence[str] = ("ACK",)) -> SplitSensitivity:
    """For a reproducing plan: how many round trips the log does not pin down.

    A client-side log shows only a round trip's total. For each logged prompt reply, move the
    split to each extreme (the request's delay at its minimum, then at its maximum) with
    :func:`shift_split`, keeping the prompt reply's and the request's later replies' receive
    times, and run again. If an extreme stops the reproduction, the outcome depends on when the
    request reached the other side, which the log does not say: the pair is sensitive. Two runs
    per pair at most; no budget.
    """
    limits = setup.limits()
    (clo, chi), (slo, shi) = limits.delay_us["c2s"], limits.delay_us["s2c"]
    pairs, sensitive, keys = 0, 0, []
    done: set[tuple] = set()
    for req, rep, rtt in round_trips(setup.log, setup.actor, replies):
        rk = tuple(rep[x] for x in ("msg", "req_id", "k"))
        if rk in done:
            continue
        done.add(rk)
        c2s = _delay_of(plan, req, clo)
        cands = [shift_split(plan, req, rep, target - c2s, limits, later_replies=True)
                 for target in (max(clo, rtt - shi), min(chi, rtt - slo)) if target != c2s]
        cands = [c for c in cands if c is not None]
        if not cands:
            continue
        pairs += 1
        if any(not setup.run(c)[1].reproduced for c in cands):
            sensitive += 1
            keys.append(f"{rep['msg']} {rep['req_id']} k={rep['k']}")
    return SplitSensitivity(pairs, sensitive, tuple(keys))


__all__ = ["DEFAULT_SPLIT", "DRIVEN_SEED", "DrivenError", "DrivenMatch", "DrivenSetup", "ScriptedEndpoint",
           "SplitSensitivity", "annotate", "compared_receives", "driven_match", "driven_reconstruct",
           "round_trips", "rtt_start_plan", "run_driven", "script_events", "shift_split", "split_edits",
           "split_sensitivity"]
