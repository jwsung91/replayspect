"""Fit a client-side log by fixing what it shows (WP5b, second design).

Driven replay (:mod:`replayspect.driven`) scripts the client, so the client never reacts to a
reply. The delay of a reply (s2c) therefore changes nothing on the device: it only sets when the
client receives it. What the device does depends only on when requests arrive (c2s) and on the
disconnects. So a log is fitted in two runs, without search over reply delays:

1. **First run.** Requests arrive at chosen times (an *arrival choice*); the device runs. Its sends,
   with their times, do not depend on reply delays.
2. **Fit.** Each device send is paired with a logged receive of the same reply and request id, in
   time order. Its delay is the logged receive time minus the send time. A device send with no
   logged receive was lost (a drop). A logged receive left over after its send was used is a
   duplicate copy. A logged receive no device send can explain is **unexplained**: the link can
   lose and duplicate what the device sent, not invent it. A send the run would deliver after the
   log ends is left in flight.
3. **Check run.** The plan (arrival delays, reply delays, drops, duplicates, the logged
   disconnects) is run and judged as driven replay judges (:func:`replayspect.driven.driven_match`).

**Disconnects are facts** when the client logged them. Client ``state`` events ``DISCONNECTED``
and ``CONNECTED`` become the plan's disconnects. A client may learn of a disconnect later than it
happened; messages in between are then explained as drops.

**The one unknown is when each request reached the device.** A probe run (every attempt at the
minimum delay) shows how long after an arrival the device sends each reply. Each logged reply then
bounds the arrival; the first choice is the middle of the interval all of them allow. When something stays unexplained, the fitter tries moves,
one at a time, in a fixed order, and keeps the first that improves the score:

* for the request attempts sent before the earliest unexplained receive, latest first and those of
  the same request id first: drop the attempt; let a dropped attempt arrive; drop every
  unanswered attempt of that request; move the arrival to just after a device event inside the
  attempt's delay range; duplicate the attempt with the copy arriving just after a device event.

The score is, in order: unexplained receives (polls left out), whether the check run's lines
match, whether the violated contracts match (when expected), unexplained poll replies, and link
faults (drops plus duplicates). Fewer is better. Poll replies are not judged, but they show the
device's state at an arrival, so they help choose arrivals. The earliest unexplained receive,
poll replies included, is the one the moves aim at.
It stops when the check run reproduces, when no move improves, or at the run cap, and says which.

**Branch points.** For a fitted log, each command attempt's arrival can lie anywhere in an
interval the log allows. The fitter moves it to just after each device event in that interval. If
any such move stops the fit reproducing, the attempt has a branch point: the device's behaviour
depends on an arrival time the log does not fix. That is where a device defect can hide.

**What "explained by loss" does not mean.** A device that fails to send a reply looks exactly like
a reply lost on the link. A log explained with drops is not shown to be free of defects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from replayspect.contract import judge
from replayspect.driven import DrivenMatch, DrivenSetup, driven_match, run_driven
from replayspect.sim.link import DROP_DISCONNECTED, FaultPlan
from replayspect.trace import Event, Trace

#: Client state names that mark the client's view of the connection.
DOWN, UP = "DISCONNECTED", "CONNECTED"
#: Default cap on runs for the fit and, separately, for the branch-point check.
FIT_RUNS = 120
BRANCH_RUNS = 120


@dataclass(frozen=True)
class Ranges:
    """Delay ranges the fit may use. Defaults are the simulator profile's; a real link can be faster."""

    c2s: tuple[int, int]
    s2c: tuple[int, int]
    dup_extra: tuple[int, int]

    @classmethod
    def of(cls, setup: DrivenSetup) -> "Ranges":
        p = setup.system.profile
        return cls(tuple(p.c2s.delay_us), tuple(p.s2c.delay_us), tuple(p.s2c.dup_extra_us))


@dataclass(frozen=True)
class Attempt:
    key: tuple[str, str | None, int]  # (msg, req_id, k)
    t_us: int  # sent

    @property
    def req_id(self) -> str | None:
        return self.key[1]

    def plan_key(self) -> dict[str, Any]:
        return {"dir": "c2s", "msg": self.key[0], "req_id": self.key[1], "k": self.key[2]}


@dataclass(frozen=True)
class Choice:
    """How each request attempt reaches the device: delay, None (dropped), plus an optional duplicate."""

    delays: tuple[tuple[tuple[str, str | None, int], int | None], ...]
    dups: tuple[tuple[tuple[str, str | None, int], int], ...] = ()

    def delay(self, key) -> int | None:
        return dict(self.delays)[key]

    def with_delay(self, key, d: int | None) -> "Choice":
        return Choice(tuple((k, d if k == key else v) for k, v in self.delays), self.dups)

    def with_dup(self, key, extra: int) -> "Choice":
        return Choice(self.delays, tuple(sorted({**dict(self.dups), key: extra}.items(), key=lambda kv: str(kv[0]))))


@dataclass
class Fit:
    plan: dict[str, Any]
    unexplained: list[Event]  # logged receives no device send explains (polls included)
    drops: int  # link losses used: request attempts and replies
    dups: int
    in_flight: int  # device sends left in flight at the end of the log
    match: DrivenMatch | None = None
    violated: set[str] | None = None

    def score(self, setup: DrivenSetup) -> tuple:
        quiet = setup.system.quiet_messages
        unexpl = sum(1 for e in self.unexplained if e.name not in quiet)
        polls = len(self.unexplained) - unexpl
        lines_bad = 0 if (self.match is not None and self.match.max_dt_us is not None
                          and self.match.max_dt_us <= setup.tolerance_us) else 1
        contracts_bad = 1 if (self.match is not None and self.match.contracts_same is False) else 0
        return (unexpl, lines_bad, contracts_bad, polls, self.drops + self.dups)


@dataclass
class FitResult:
    status: str  # reproduced | unexplained | no_improvement | cap
    runs: int
    fit: Fit
    moves: list[str] = field(default_factory=list)
    receives: int = 0  # logged receives, polls left out
    matched: int = 0  # of them matched in the check run
    disconnects_from_log: int = 0
    quiet: frozenset[str] = frozenset()
    branch_attempts: int | None = None  # command attempts with a branch point
    branch_checked: int | None = None
    branch_runs: int = 0
    branch_capped: bool = False

    @property
    def reproduced(self) -> bool:
        return self.status == "reproduced"


# -- reading the log ------------------------------------------------------------------------


def attempts_of(log: Sequence[Event], actor: str) -> list[Attempt]:
    seen: dict[tuple, int] = {}
    out = []
    for e in log:
        if e.actor == actor and e.kind == "send":
            k = seen.get((e.name, e.req_id), 0)
            seen[(e.name, e.req_id)] = k + 1
            out.append(Attempt((e.name, e.req_id, k), e.t_us))
    return out


def logged_disconnects(log: Sequence[Event], actor: str, until_us: int) -> list[dict[str, int]]:
    """Disconnects from the client's DISCONNECTED/CONNECTED state events (an open one lasts to the end)."""
    out, down = [], None
    for e in log:
        if e.actor != actor or e.kind != "state":
            continue
        if e.name == DOWN and down is None:
            down = e.t_us
        elif e.name == UP and down is not None:
            if e.t_us > down:
                out.append({"t_us": down, "duration_us": e.t_us - down})
            down = None
    if down is not None and until_us > down:
        out.append({"t_us": down, "duration_us": until_us - down})
    return out


# -- the two runs ---------------------------------------------------------------------------


def _first_plan(choice: Choice, disconnects: list[dict[str, int]]) -> dict[str, Any]:
    delays, faults = [], []
    for (msg, rid, k), d in choice.delays:
        key = {"dir": "c2s", "msg": msg, "req_id": rid, "k": k}
        if d is None:
            faults.append({**key, "drop": True})
        else:
            delays.append({**key, "delay_us": int(d)})
    for (msg, rid, k), extra in choice.dups:
        if choice.delay((msg, rid, k)) is not None:
            faults.append({"dir": "c2s", "msg": msg, "req_id": rid, "k": k, "dup_extra_us": int(extra)})
    return {"base": "fixed", "delays": delays, "faults": faults, "disconnects": list(disconnects)}


def _device_sends(trace: Trace) -> list[tuple[Event, dict]]:
    """The device's s2c sends that reached the link (not dropped for a disconnect at send time)."""
    lost = {(e.data.get("dir"), e.data.get("n")) for e in trace.events
            if e.actor == "link" and e.kind == "fault" and e.name == "drop"
            and e.data.get("reason") == DROP_DISCONNECTED}
    out = []
    for e in trace.events:
        link = e.data.get("link")
        if e.kind == "send" and link is not None and link.get("dir") == "s2c" and (link["dir"], link["n"]) not in lost:
            out.append((e, link))
    return out


def _cut_by_disconnect(t0: int, t1: int, disconnects: list[dict[str, int]]) -> bool:
    return any(t0 < d["t_us"] <= t1 for d in disconnects)


def fit_replies(setup: DrivenSetup, first: Trace, choice: Choice, disconnects: list[dict[str, int]],
                ranges: Ranges) -> Fit:
    """Pair the first run's device sends with the logged receives and build the plan (see module doc)."""
    plan = _first_plan(choice, disconnects)
    horizon = setup.horizon_us
    lo, hi = ranges.s2c
    dlo, dhi = ranges.dup_extra
    sends: dict[tuple, list[tuple[Event, dict]]] = {}
    for e, link in _device_sends(first):
        sends.setdefault((e.name, e.req_id), []).append((e, link))
    recvs: dict[tuple, list[Event]] = {}
    for e in setup.log:
        if e.actor == setup.actor and e.kind == "recv":
            recvs.setdefault((e.name, e.req_id), []).append(e)
    unexplained: list[Event] = []
    drops = dups = in_flight = 0
    for name_rid in sorted(set(sends) | set(recvs), key=str):
        ss, rs = sends.get(name_rid, []), recvs.get(name_rid, [])
        used = [None] * len(ss)  # receive time each send was given
        dup_done: set[int] = set()
        i = 0
        for r in rs:
            j = next((j for j in range(i, len(ss)) if used[j] is None
                      and lo <= r.t_us - ss[j][0].t_us <= hi
                      and not _cut_by_disconnect(ss[j][0].t_us, r.t_us, disconnects)), None)
            if j is not None:
                for skipped in range(i, j):
                    if used[skipped] is None:
                        used[skipped] = -1  # lost
                used[j] = r.t_us
                i = j + 1
                continue
            # a second copy of a send already received?
            d = next((j for j in range(i - 1, -1, -1) if used[j] not in (None, -1) and j not in dup_done
                      and dlo <= r.t_us - used[j] <= dhi
                      and not _cut_by_disconnect(ss[j][0].t_us, r.t_us, disconnects)), None)
            if d is not None:
                dup_done.add(d)
                link = ss[d][1]
                plan["faults"].append({"dir": "s2c", "msg": name_rid[0], "req_id": name_rid[1], "k": link["k"],
                                       "dup_extra_us": int(r.t_us - used[d])})
                dups += 1
                continue
            unexplained.append(r)
        for j, (e, link) in enumerate(ss):
            key = {"dir": "s2c", "msg": e.name, "req_id": e.req_id, "k": link["k"]}
            if used[j] is None or used[j] == -1:
                if e.t_us + lo > horizon:
                    continue  # arrives after the log ends at any delay
                if used[j] is None and e.t_us + hi > horizon:
                    plan["delays"].append({**key, "delay_us": int(hi)})  # in flight at the end of the log
                    in_flight += 1
                    continue
                plan["faults"].append({**key, "drop": True})
                drops += 1
            else:
                plan["delays"].append({**key, "delay_us": int(used[j] - e.t_us)})
    drops += sum(1 for _, d in choice.delays if d is None)
    dups += sum(1 for k, _ in choice.dups if choice.delay(k) is not None)
    unexplained.sort(key=lambda e: e.t_us)
    return Fit(plan, unexplained, drops, dups, in_flight)


class _Runner:
    def __init__(self, setup: DrivenSetup, ranges: Ranges, disconnects: list[dict[str, int]], cap: int) -> None:
        self.setup, self.ranges, self.disconnects, self.cap = setup, ranges, disconnects, cap
        self.runs = 0
        self.cache: dict[Choice, tuple[Fit, Trace]] = {}

    def evaluate(self, choice: Choice) -> tuple[Fit, Trace] | None:
        """One run, plus the check run when no receive (polls left out) is unexplained."""
        if choice in self.cache:
            return self.cache[choice]
        if self.runs + 1 > self.cap:
            return None
        s = self.setup
        self.runs += 1
        first = run_driven(s.system, s.log, FaultPlan.from_dict(_first_plan(choice, self.disconnects)),
                           s.until_us, s.mutants, s.actor)
        fit = fit_replies(s, first, choice, self.disconnects, self.ranges)
        if any(e.name not in s.system.quiet_messages for e in fit.unexplained):
            self.cache[choice] = (fit, first)
            return fit, first
        if self.runs + 1 > self.cap:
            return None
        self.runs += 1
        check = run_driven(s.system, s.log, FaultPlan.from_dict(fit.plan), s.until_us, s.mutants, s.actor)
        violated = None
        if s.expect is not None:
            violated = {v.contract for v in judge(check, s.system.contracts(), s.until_us)}
        vocab = s.system.vocabulary
        poll_reply = (vocab.poll_reply if vocab is not None else "STATUS_REPLY") if s.status_rule else None
        fit.match = driven_match(s.log, check.events, s.actor, s.system.quiet_messages, s.tolerance_us,
                                 s.horizon_us, violated, s.expect, poll_reply)
        fit.violated = violated
        self.cache[choice] = (fit, first)
        return fit, first


# -- the arrival choice ---------------------------------------------------------------------


def _prompt_pairs(first: Trace) -> dict[tuple, int]:
    """For each request attempt the device received: the time of a reply it sent at that same instant."""
    out: dict[tuple, int] = {}
    events = first.events
    for i, e in enumerate(events):
        link = e.data.get("link")
        if e.actor != "device" or e.kind != "recv" or link is None or link.get("copy"):
            continue
        for f in events[i + 1:]:
            if f.t_us != e.t_us:
                break
            fl = f.data.get("link")
            if f.actor == "device" and f.kind == "send" and fl is not None and f.req_id == e.req_id:
                out[(e.name, e.req_id, link["k"])] = (f.name, fl["k"])
                break
    return out


def _arrival_bounds(setup: DrivenSetup, attempts: list[Attempt], probe: Trace, ranges: Ranges) -> dict[tuple, tuple[int, int]]:
    """For each attempt, the arrival interval its replies allow, using the probe run's device timing.

    The probe tells, for the attempt that arrived first for its request, how long after that
    arrival the device sent each reply (``ACK`` at once, ``DONE`` after the move...). Each logged
    receive of such a reply then bounds the arrival: ``recv - delay_max - lag <= arrival <=
    recv - delay_min - lag``. Retries get the bound of their own prompt reply only.
    """
    lo, hi = ranges.c2s
    slo, shi = ranges.s2c
    recv_times: dict[tuple, list[int]] = {}
    for e in setup.log:
        if e.actor == setup.actor and e.kind == "recv":
            recv_times.setdefault((e.name, e.req_id), []).append(e.t_us)
    first_arrival: dict[str | None, tuple[tuple, int]] = {}
    arrivals: dict[str | None, set[int]] = {}
    sends: dict[str | None, list[tuple[str, int, int]]] = {}
    for e in probe.events:
        link = e.data.get("link")
        if e.actor != "device" or link is None:
            continue
        if e.kind == "recv":
            if not link.get("copy") and e.req_id not in first_arrival:
                first_arrival[e.req_id] = ((e.name, e.req_id, link["k"]), e.t_us)
            else:
                arrivals.setdefault(e.req_id, set()).add(e.t_us)  # a later attempt or a copy
        elif e.kind == "send":
            sends.setdefault(e.req_id, []).append((e.name, link["k"], e.t_us))
    prompt = _prompt_pairs(probe)
    # A device send lost at the instant it was made (link down) never reaches the log: number each
    # reply by the sends that reached the link, which is what the log's receives count.
    index: dict[tuple, int] = {}
    counter: dict[tuple, int] = {}
    for e, link in _device_sends(probe):
        n = counter.get((e.name, e.req_id), 0)
        index[(e.name, e.req_id, link["k"])] = n
        counter[(e.name, e.req_id)] = n + 1
    out = {}
    for a in attempts:
        a_lo, a_hi = a.t_us + lo, a.t_us + hi
        replies: list[tuple[str, int, int]] = []  # (reply name, which receive, lag after arrival)
        fa = first_arrival.get(a.req_id)
        if fa is not None and fa[0] == a.key:
            # replies the first arrival caused: not those sent at the instant another attempt arrived
            others = arrivals.get(a.req_id, set())
            replies = [(n, k, t - fa[1]) for n, k, t in sends.get(a.req_id, [])
                       if t >= fa[1] and (t == fa[1] or t not in others)]
        elif a.key in prompt:
            replies = [(prompt[a.key][0], prompt[a.key][1], 0)]
        for name, k, lag in replies:
            j = index.get((name, a.req_id, k))
            times = recv_times.get((name, a.req_id), [])
            if j is not None and j < len(times):
                a_lo = max(a_lo, times[j] - shi - lag)
                a_hi = min(a_hi, times[j] - slo - lag)
        out[a.key] = (a_lo, a_hi)
    return out


def _initial_choice(setup: DrivenSetup, attempts: list[Attempt], runner: _Runner) -> Choice:
    """Each attempt arrives at the middle of the interval its replies allow (:func:`_arrival_bounds`),
    read off a probe run where every attempt arrives at the minimum delay. An empty interval falls
    back to the attempt's own delay range, clamped."""
    lo, hi = runner.ranges.c2s
    base = Choice(tuple((a.key, lo) for a in attempts))
    probe = runner.evaluate(base)
    if probe is None:
        return base
    bounds = _arrival_bounds(setup, attempts, probe[1], runner.ranges)
    delays = []
    for a in attempts:
        b_lo, b_hi = bounds[a.key]
        if b_lo > b_hi:
            b_lo, b_hi = (b_hi, b_hi) if b_hi >= a.t_us + lo else (a.t_us + lo, a.t_us + lo)
        d = (b_lo + b_hi) // 2 - a.t_us
        delays.append((a.key, min(max(d, lo), hi)))
    return Choice(tuple(delays))


def _cut_points(first: Trace, t0: int, t1: int, quiet: frozenset[str] = frozenset()) -> list[int]:
    """Times of the device's events strictly inside (t0, t1), polls left out: the instants where an
    arrival moving past them can change what the device does."""
    return sorted({e.t_us for e in first.events if e.actor == "device" and t0 < e.t_us < t1 and e.name not in quiet})


def _moves(choice: Choice, fit: Fit, first: Trace, attempts: list[Attempt], ranges: Ranges,
           quiet: frozenset[str] = frozenset()):
    lo, hi = ranges.c2s
    dlo, dhi = ranges.dup_extra
    target = fit.unexplained[0].t_us if fit.unexplained else None
    target_rid = fit.unexplained[0].req_id if fit.unexplained else None
    cands = [a for a in attempts if target is None or a.t_us <= target]
    if target is None:  # every receive explained, the contracts differ: causes first, commands only
        cands = [a for a in cands if a.key[0] not in quiet]
        cands.sort(key=lambda a: a.t_us)
    else:
        cands.sort(key=lambda a: (a.req_id != target_rid, -a.t_us))
    for a in cands:
        d = choice.delay(a.key)
        if d is not None:
            yield f"drop {a.key[0]} {a.req_id} k={a.key[2]}", choice.with_delay(a.key, None)
        else:
            yield f"let {a.key[0]} {a.req_id} k={a.key[2]} arrive", choice.with_delay(a.key, lo)
        same = [b for b in attempts if b.req_id == a.req_id and b.req_id is not None
                and (target is None or b.t_us <= target) and choice.delay(b.key) is not None]
        if len(same) > 1:
            c = choice
            for b in same:
                c = c.with_delay(b.key, None)
            yield f"drop every attempt of {a.req_id} before the mismatch", c
        if d is not None:
            for t in _cut_points(first, a.t_us + lo, a.t_us + hi, quiet):
                nd = t + 1 - a.t_us
                if nd != d:
                    yield f"{a.key[0]} {a.req_id} k={a.key[2]} arrives at {(t + 1) / 1e6:.6f}s", choice.with_delay(a.key, nd)
            if a.key not in dict(choice.dups):
                arr = a.t_us + d
                for t in _cut_points(first, arr + dlo, arr + dhi, quiet):
                    yield (f"duplicate {a.key[0]} {a.req_id} k={a.key[2]}, copy at {(t + 1) / 1e6:.6f}s",
                           choice.with_dup(a.key, t + 1 - arr))


def fit_log(setup: DrivenSetup, ranges: Ranges | None = None, cap: int = FIT_RUNS, branches: bool = False,
            branch_cap: int = BRANCH_RUNS) -> FitResult:
    """Fit ``setup.log`` (see the module docstring)."""
    ranges = ranges or Ranges.of(setup)
    attempts = attempts_of(setup.log, setup.actor)
    disconnects = logged_disconnects(setup.log, setup.actor, setup.until_us)
    runner = _Runner(setup, ranges, disconnects, cap)
    choice = _initial_choice(setup, attempts, runner)
    cur = runner.evaluate(choice)
    quiet = setup.system.quiet_messages
    n_recv = sum(1 for e in setup.log if e.actor == setup.actor and e.kind == "recv" and e.name not in quiet)
    if cur is None:
        empty = Fit(_first_plan(choice, disconnects), [], 0, 0, 0)
        return FitResult("cap", runner.runs, empty, receives=n_recv, disconnects_from_log=len(disconnects),
                         quiet=quiet)
    moves: list[str] = []
    status = None
    while True:
        fit, first = cur
        if fit.match is not None and fit.match.reproduced:
            status = "reproduced"
            break
        base = fit.score(setup)
        better = None
        for name, cand in _moves(choice, fit, first, attempts, ranges, quiet):
            res = runner.evaluate(cand)
            if res is None:
                status = "cap"
                break
            if res[0].score(setup) < base:
                better = (name, cand, res)
                break
        if status == "cap":
            break
        if better is None:
            status = "unexplained" if fit.unexplained else "no_improvement"
            break
        moves.append(better[0])
        choice, cur = better[1], better[2]
    fit, first = cur
    out = FitResult(status, runner.runs, fit, moves, n_recv, fit.match.matched if fit.match else 0, len(disconnects),
                    quiet)
    if branches and out.reproduced:
        _branch_points(setup, out, choice, first, attempts, ranges, disconnects, branch_cap)
    return out


def _branch_points(setup: DrivenSetup, out: FitResult, choice: Choice, first: Trace, attempts: list[Attempt],
                   ranges: Ranges, disconnects: list[dict[str, int]], cap: int) -> None:
    """Move each arriving command attempt to just after every device event inside the interval its
    replies allow (:func:`_arrival_bounds`, from the fitted run) and count the attempts where some
    move stops the fit reproducing."""
    quiet = setup.system.quiet_messages
    bounds = _arrival_bounds(setup, attempts, first, ranges)
    runner = _Runner(setup, ranges, disconnects, cap)
    checked = with_branch = 0
    for a in attempts:
        d = choice.delay(a.key)
        if d is None or a.key[0] in quiet:
            continue
        b_lo, b_hi = bounds[a.key]
        cuts = [t for t in _cut_points(first, max(b_lo, a.t_us + ranges.c2s[0]) - 1, b_hi, quiet)
                if t + 1 - a.t_us != d]
        if not cuts:
            continue
        checked += 1
        for t in cuts:
            res = runner.evaluate(choice.with_delay(a.key, t + 1 - a.t_us))
            if res is None:
                out.branch_capped = True
                break
            if not (res[0].match is not None and res[0].match.reproduced):
                with_branch += 1
                break
        if out.branch_capped:
            break
    out.branch_attempts, out.branch_checked, out.branch_runs = with_branch, checked, runner.runs


def report_lines(res: FitResult) -> list[str]:
    f = res.fit
    lines = [
        f"fit: {res.status} after {res.runs} runs" + (f" ({len(res.moves)} moves: {'; '.join(res.moves)})" if res.moves else ""),
        f"receives fitted: {res.matched}/{res.receives} (polls left out); disconnects from the log: {res.disconnects_from_log}",
        f"explained by loss: {f.drops} link faults (a device that does not send a reply looks the same as a lost "
        "reply, so this is not evidence that there is no defect)",
        f"explained by duplicate: {f.dups}; in flight at the end of the log: {f.in_flight}",
        f"unexplained: {len(f.unexplained)}, poll replies {sum(e.name in res.quiet for e in f.unexplained)}"
        + (" (no device send explains: " + ", ".join(
            f"{e.name} {e.req_id or '-'} at {e.t_us / 1e6:.6f}s" + (f" log line {e.log['line']}" if e.log else "")
            for e in f.unexplained[:5]) + (" ..." if len(f.unexplained) > 5 else "") + ")" if f.unexplained else ""),
    ]
    if res.branch_checked is not None:
        lines.append(f"attempts with a branch point: {res.branch_attempts} of {res.branch_checked} checked "
                     f"({res.branch_runs} runs" + ("; run cap reached" if res.branch_capped else "") + ")")
    return lines


__all__ = ["BRANCH_RUNS", "DOWN", "FIT_RUNS", "Fit", "FitResult", "Ranges", "UP", "attempts_of", "fit_log",
           "fit_replies", "logged_disconnects", "report_lines"]
