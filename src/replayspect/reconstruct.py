"""Rule-based reconstruction of a fault plan from one participant's log.

The WP4 main baseline, and a step of the WP5 path: a text-log adapter turns a
real log into a trace file of one participant, and this module looks for a
fault plan that makes the simulator produce that log. No model, no tokens.

Input is only what a planner gets:

* the **log**: one participant's events (a trace file in the planner-view
  form of ``docs/trace-schema.md``: no ``link`` data, ``seq`` renumbered, maybe
  a constant clock offset);
* the public **limits** (delay, duplicate and disconnect ranges, run length,
  fault cap) and the poll message names from the protocol;
* an **oracle** that runs a plan and returns whether it reproduced the log,
  how many compared lines matched from the start, and the visible
  participant's events of that run (:func:`~replayspect.incident.run_view`:
  the run's own link data kept).

The search is depth first. Start from the empty plan. At the first mismatched line
try candidate edits (adjust an entry already in the plan,
delay, drop or duplicate the message on that line, a disconnect from a gap in
the polls or ending at an unexplained resend, then edits on nearby messages
of the same request), adjustments first and then by the earliest moment the
edit touches, so a cause is tried before its effect. Keep the first edit that improves the score: more lines
matched, or the same number with the first mismatched line closer in time,
and continue from it. When a branch has no improving edit left, back up and
try the next edit of the step before. A plan is never run twice, and only
improvements are followed, so the search cannot loop. It ends as

* ``reproduced``;
* ``stuck``: every branch ended with no improving edit (the same mismatch
  keeps coming back), or with every line matched and the run still differing
  in what the log does not show; the reason names the furthest point reached;
* ``cap``: no reproduction, and some branch reached the edit limit;
* ``budget``: the oracle refused (budget used up).

``stuck`` and ``cap`` both count as "not reconstructed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping, Sequence

from replayspect.incident import line_key
from replayspect.trace import Event
from replayspect.tracefile import canonical

#: Edits on one branch before it is abandoned, and candidate runs tried at one step.
MAX_EDITS = 40
MAX_TRIES_PER_LINE = 40
#: A closer first mismatch must gain at least this much to count.
MIN_GAIN_US = 1_000
#: Margin when a message must arrive after (or a disconnect end just before) a time.
MARGIN_US = 50_000


@dataclass(frozen=True)
class Feedback:
    """What the oracle says about one run."""

    reproduced: bool
    matched: int  # compared lines equal from the start, before the first mismatch
    events: Sequence[Event]  # the visible participant's events of the run (run_view)


Oracle = Callable[[dict[str, Any]], "Feedback | None"]  # None: refused, budget used up
#: Extra candidate edits for a mismatched line: (plan, the run's line, time it should move by) ->
#: (name, plan). Names starting with "adjust" are tried before the built-in edits.
Extra = Callable[[dict[str, Any], Event, int], Iterator[tuple[str, dict[str, Any]]]]


@dataclass
class Result:
    status: str  # reproduced | stuck | cap | budget
    reason: str
    runs: int
    plan: dict[str, Any]
    offset_us: int
    edits: list[str] = field(default_factory=list)  # search edits on the branch (MAX_EDITS counts these)
    start_entries: int = 0  # entries of the start plan (e.g. round-trip delays), not search edits

    @property
    def reconstructed(self) -> bool:
        return self.status == "reproduced"


def empty_plan(base: str = "random") -> dict[str, Any]:
    """``base: random`` takes unplanned delays from the run's seed (bridge sessions); ``fixed`` uses
    the profile minimum and needs no seed (driven replay)."""
    return {"base": base, "delays": [], "faults": [], "disconnects": []}


@dataclass(frozen=True)
class Limits:
    delay_us: Mapping[str, tuple[int, int]]
    dup_extra_us: Mapping[str, tuple[int, int]]
    disconnect_us: tuple[int, int]
    run_length_us: int
    max_faults: int

    @classmethod
    def from_describe(cls, limits: Mapping[str, Any]) -> "Limits":
        """From the ``limits`` part of a bridge session's ``describe``."""
        return cls({d: tuple(v) for d, v in limits["delay_us"].items()},
                   {d: tuple(v) for d, v in limits["dup_extra_us"].items()},
                   tuple(limits["disconnect_duration_us"]), limits["run_length_us"],
                   limits["max_faults_and_disconnects"])

    def ok(self, plan: Mapping[str, Any]) -> bool:
        for d in plan["delays"]:
            lo, hi = self.delay_us[d["dir"]]
            if not lo <= d["delay_us"] <= hi:
                return False
        for f in plan["faults"]:
            if "dup_extra_us" in f:
                lo, hi = self.dup_extra_us[f["dir"]]
                if not lo <= f["dup_extra_us"] <= hi:
                    return False
        lo, hi = self.disconnect_us
        for x in plan["disconnects"]:
            if not (lo <= x["duration_us"] <= hi and 0 <= x["t_us"] < self.run_length_us):
                return False
        spans = sorted((x["t_us"], x["t_us"] + x["duration_us"]) for x in plan["disconnects"])
        if any(b[0] <= a[1] for a, b in zip(spans, spans[1:])):
            return False
        return len(plan["faults"]) + len(plan["disconnects"]) <= self.max_faults


# -- plan edits ------------------------------------------------------------------------------


def _mk(link_dir: str, ev: Event, k: int) -> dict[str, Any]:
    return {"dir": link_dir, "msg": ev.name, "req_id": ev.req_id, "k": k}


def _same_key(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return all(a[x] == b[x] for x in ("dir", "msg", "req_id", "k"))


def _without_key(items: list[dict[str, Any]], key: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [x for x in items if not _same_key(x, key)]


def set_delay(plan: Mapping[str, Any], key: Mapping[str, Any], delay_us: int) -> dict[str, Any]:
    return {**plan, "delays": _without_key(plan["delays"], key) + [{**key, "delay_us": int(delay_us)}],
            "faults": _without_key(plan["faults"], key)}


def drop(plan: Mapping[str, Any], key: Mapping[str, Any]) -> dict[str, Any]:
    return {**plan, "delays": _without_key(plan["delays"], key),
            "faults": _without_key(plan["faults"], key) + [{**key, "drop": True}]}


def duplicate(plan: Mapping[str, Any], key: Mapping[str, Any], extra_us: int) -> dict[str, Any]:
    return {**plan, "faults": _without_key(plan["faults"], key) + [{**key, "dup_extra_us": int(extra_us)}]}


def disconnect(plan: Mapping[str, Any], t_us: int, duration_us: int) -> dict[str, Any]:
    return {**plan, "disconnects": sorted(plan["disconnects"] + [{"t_us": int(t_us), "duration_us": int(duration_us)}],
                                          key=lambda x: x["t_us"])}


def _show(ev: Event | None, offset_us: int = 0) -> str:
    if ev is None:
        return "nothing"
    return f"{ev.kind} {ev.name} {ev.req_id or '-'} at {(ev.t_us - offset_us) / 1e6:.3f}s"


# -- the search ------------------------------------------------------------------------------


class _Search:
    def __init__(self, log: Sequence[Event], actor: str, quiet: frozenset[str], polls: tuple[str, str],
                 limits: Limits, oracle: Oracle, clock_known: bool, max_edits: int, max_tries: int,
                 start: dict[str, Any] | None = None, kinds: frozenset[str] | None = None,
                 extra: Extra | None = None) -> None:
        self.actor, self.quiet, self.polls, self.limits = actor, quiet, polls, limits
        self.start, self.kinds, self.extra = start, kinds, extra
        self.oracle, self.clock_known = oracle, clock_known
        self.max_edits, self.max_tries = max_edits, max_tries
        self.log = [e for e in log if e.actor == actor]
        self.want = self.compared(self.log)
        self.runs = 0
        self.offset = 0

    def compared(self, events: Sequence[Event]) -> list[Event]:
        return [e for e in events if e.actor == self.actor and e.name not in self.quiet
                and (self.kinds is None or e.kind in self.kinds)]

    def run(self, plan: dict[str, Any]) -> Feedback | None:
        self.runs += 1
        return self.oracle(plan)

    def estimate_offset(self, got: Sequence[Event]) -> int:
        """Time difference of the first compared line, if it agrees with the run's (times ignored).

        The earliest line is the one least likely to be moved by a fault; later
        leading lines can already be (a late reply), so they are not averaged in.
        """
        if self.want and got and line_key(self.want[0]) == line_key(got[0]):
            return self.want[0].t_us - got[0].t_us
        return 0

    def score(self, fb: Feedback) -> tuple[int, float]:
        got, i = self.compared(fb.events), fb.matched
        if i < len(self.want) and i < len(got) and line_key(self.want[i]) == line_key(got[i]):
            return fb.matched, -abs(self.want[i].t_us - self.offset - got[i].t_us)
        return fb.matched, float("-inf")

    def better(self, new: tuple[int, float], old: tuple[int, float]) -> bool:
        if new[0] != old[0]:
            return new[0] > old[0]
        return new[1] > old[1] + MIN_GAIN_US

    # candidate edits, in the order they are tried

    def candidates(self, plan: dict[str, Any], fb: Feedback) -> Iterator[tuple[str, dict[str, Any]]]:
        got, i = self.compared(fb.events), fb.matched
        e = self.want[i] if i < len(self.want) else None
        g = got[i] if i < len(got) else None
        t_e = e.t_us - self.offset if e is not None else None
        same = e is not None and g is not None and line_key(e) == line_key(g)
        d = t_e - g.t_us if same else None
        events = list(fb.events)

        # 0. caller-supplied adjustments (driven replay: shift a round trip's split), tried first
        if self.extra is not None and same:
            yield from self.extra(plan, g, d)

        # 1. adjust an entry already in the plan by the time difference
        if same:
            for x in plan["delays"]:
                if x["req_id"] == g.req_id:
                    yield f"adjust delay {_desc(x)}", set_delay(plan, x, x["delay_us"] + d)
            for x in plan["faults"]:
                if x["req_id"] == g.req_id and "dup_extra_us" in x:
                    yield f"adjust duplicate {_desc(x)}", duplicate(plan, x, x["dup_extra_us"] + d)
            for n, x in enumerate(plan["disconnects"]):
                rest = {**plan, "disconnects": plan["disconnects"][:n] + plan["disconnects"][n + 1:]}
                yield f"adjust disconnect {n} end", disconnect(rest, x["t_us"], x["duration_us"] + d)
                yield f"adjust disconnect {n} start", disconnect(rest, x["t_us"] + d, x["duration_us"])

        # 2. the message on the mismatched line
        if g is not None and g.kind == "recv" and "sent_us" in g.data.get("link", {}):
            link = g.data["link"]
            key = _mk(link["dir"], g, link["k"])
            if same:
                yield f"delay {_desc(key)} by {d / 1e6:+.3f}s", set_delay(plan, key, link["delay_us"] + d)
                if d > 0:
                    yield f"drop {_desc(key)}", drop(plan, key)
            else:
                yield f"drop {_desc(key)}", drop(plan, key)
                if t_e is not None and t_e > g.t_us:
                    yield (f"delay {_desc(key)} past the expected line",
                           set_delay(plan, key, link["delay_us"] + t_e - g.t_us + MARGIN_US))
            yield from self.disconnects_covering(plan, link["sent_us"])
        if e is not None and e.kind == "recv" and not same:
            yield from self.arrival_edits(plan, events, e, t_e)
        if e is not None and e.kind == "send" and not same:
            yield from self.disconnects_ending(plan, t_e)

        # 3. gaps in the polls before the mismatch
        horizon = max(t for t in (t_e, g.t_us if g is not None else None) if t is not None)
        yield from self.poll_gap_disconnects(plan, events, horizon)

        # 4. nearby messages of the same request
        rids = {x.req_id for x in (e, g) if x is not None and x.req_id is not None}
        for ev in reversed(events):
            if ev.t_us > horizon or ev.req_id not in rids or ev.name in self.quiet:
                continue
            link = ev.data.get("link")
            if link is None or ev.kind not in ("send", "recv"):
                continue
            key = _mk(link["dir"], ev, link["k"])
            yield f"drop {_desc(key)}", drop(plan, key)
            if ev.kind == "recv" and "delay_us" in link:
                yield (f"delay {_desc(key)} past the mismatch",
                       set_delay(plan, key, link["delay_us"] + horizon - ev.t_us + MARGIN_US))
            elif ev.kind == "send" and "delay_us" in link:
                # the other side's answer depends on when this arrives: shift it, or spread over the range
                if same:
                    yield f"delay {_desc(key)} by {d / 1e6:+.3f}s", set_delay(plan, key, link["delay_us"] + d)
                lo, hi = self.limits.delay_us[link["dir"]]
                for frac in (0.25, 0.5, 0.75, 1.0):
                    yield f"delay {_desc(key)} to {frac:.0%} of the range", \
                        set_delay(plan, key, int(lo + (hi - lo) * frac))

    def arrival_edits(self, plan, events, e: Event, t_e: int) -> Iterator[tuple[str, dict[str, Any]]]:
        """``e`` (a received message) is expected here but the run has something else.

        Either a copy of it arrives at another time in the run (move or duplicate
        that copy), or it is an answer the run never gets: the other side answered
        a duplicate of a request this side sent (duplicate that request).
        """
        if not any(ev.kind == "recv" and ev.name == e.name and ev.req_id == e.req_id for ev in events):
            for ev in events:
                link = ev.data.get("link", {})
                if ev.kind != "send" or ev.req_id != e.req_id or "delay_us" not in link or ev.t_us >= t_e:
                    continue
                key = _mk(link["dir"], ev, link["k"])
                lo, hi = self.limits.dup_extra_us[link["dir"]]
                first = ev.t_us + link["delay_us"]
                for back in (50_000, 300_000, 600_000, 1_000_000):
                    extra = min(max(t_e - back - first, lo), hi)
                    yield f"duplicate {_desc(key)} (+{extra / 1e6:.3f}s)", duplicate(plan, key, extra)
        for ev in events:
            if ev.kind != "recv" or ev.name != e.name or ev.req_id != e.req_id:
                continue
            link = ev.data.get("link", {})
            if "sent_us" not in link:
                continue
            key = _mk(link["dir"], ev, link["k"])
            if ev.t_us < t_e:
                yield f"duplicate {_desc(key)}", duplicate(plan, key, t_e - ev.t_us)
            else:
                yield f"delay {_desc(key)} earlier", set_delay(plan, key, link["delay_us"] - (ev.t_us - t_e))

    def disconnects_covering(self, plan, t_us: int) -> Iterator[tuple[str, dict[str, Any]]]:
        lo, hi = self.limits.disconnect_us
        for frac in (0.25, 0.5, 0.75, 1.0):
            dur = int(lo + (hi - lo) * frac)
            yield f"disconnect at {t_us / 1e6:.3f}s for {dur / 1e6:.3f}s", disconnect(plan, t_us - MARGIN_US, dur)

    def disconnects_ending(self, plan, t_us: int) -> Iterator[tuple[str, dict[str, Any]]]:
        """An unexplained send at ``t_us``: a resend on reconnect."""
        lo, hi = self.limits.disconnect_us
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            dur = int(lo + (hi - lo) * frac)
            if t_us - dur >= 0:
                yield f"disconnect ending at {t_us / 1e6:.3f}s for {dur / 1e6:.3f}s", disconnect(plan, t_us - dur, dur)

    def poll_gap_disconnects(self, plan, events, horizon: int) -> Iterator[tuple[str, dict[str, Any]]]:
        """Polls the run has and the log lacks, grouped into gaps; a disconnect over each gap."""
        in_log = {(e.kind, e.name, e.req_id) for e in self.log if e.name in self.polls}
        missing = []
        for ev in events:
            if ev.name not in self.polls or (ev.kind, ev.name, ev.req_id) in in_log:
                continue
            link = ev.data.get("link", {})
            t = link.get("sent_us", ev.t_us)
            if t < horizon:
                missing.append(t)
        gaps: list[list[int]] = []
        for t in sorted(missing):
            if gaps and t - gaps[-1][-1] <= 1_500_000:
                gaps[-1].append(t)
            else:
                gaps.append([t])
        lo, hi = self.limits.disconnect_us
        for gap in reversed(gaps[-2:]):
            a, b = gap[0], gap[-1]
            for back in (0, 300_000, 700_000):
                for ahead in (MARGIN_US, 500_000, 950_000):
                    start, end = a - back, b + ahead
                    dur = min(max(end - start, lo), hi)
                    yield f"disconnect over the poll gap {start / 1e6:.3f}s-{(start + dur) / 1e6:.3f}s", \
                        disconnect(plan, start, dur)

    # the search: depth first over improving edits, backtracking when a branch is stuck

    def search(self) -> Result:
        plan = self.start if self.start is not None else empty_plan()
        n_start = len(plan["delays"]) + len(plan["faults"]) + len(plan["disconnects"])
        res = self._search(plan)
        res.start_entries = n_start
        return res

    def _search(self, plan: dict[str, Any]) -> Result:
        fb = self.run(plan)
        if fb is None:
            return Result("budget", "the oracle refused the first run", self.runs, plan, 0)
        if not self.clock_known:
            self.offset = self.estimate_offset(self.compared(fb.events))
        self.visited = {canonical(plan)}
        self.deepest: tuple[int, str, dict[str, Any], list[str]] = (-1, "", plan, [])
        self.hit_cap = False
        try:
            found = self.dfs(plan, fb, [])
        except _BudgetUsed:
            _, reason, best, edits = self.deepest
            return Result("budget", f"budget used up; furthest: {reason}", self.runs, best, self.offset, edits)
        if found is not None:
            return found
        _, reason, best, edits = self.deepest
        return Result("cap" if self.hit_cap else "stuck", reason, self.runs, best, self.offset, edits)

    @staticmethod
    def send_times(events: Sequence[Event]) -> dict[tuple, int]:
        """When each message the visible participant sent or received was sent, in the run."""
        out: dict[tuple, int] = {}
        for ev in events:
            link = ev.data.get("link")
            if link is None or ev.kind not in ("send", "recv"):
                continue
            t = ev.t_us if ev.kind == "send" else link.get("sent_us")
            if t is not None:
                out.setdefault((link["dir"], ev.name, ev.req_id, link["k"]), t)
        return out

    @staticmethod
    def edit_time(plan: Mapping[str, Any], cand: tuple[str, dict[str, Any]], times: Mapping[tuple, int]) -> float:
        """Order of trial: adjustments first, then by the earliest moment the edit touches.

        An earlier cause (a lost request) is tried before its effect (a missing reply).
        """
        name, new = cand
        if name.startswith("adjust"):
            return float("-inf")
        old = {canonical(x) for sec in ("delays", "faults", "disconnects") for x in plan[sec]}
        ts = []
        for sec in ("delays", "faults", "disconnects"):
            for x in new[sec]:
                if canonical(x) in old:
                    continue
                if sec == "disconnects":
                    ts.append(x["t_us"])
                else:
                    ts.append(times.get((x["dir"], x["msg"], x["req_id"], x["k"]), float("inf")))
        return min(ts, default=float("inf"))

    def note(self, fb: Feedback, plan: dict[str, Any], edits: list[str], reason: str) -> None:
        if fb.matched > self.deepest[0]:
            self.deepest = (fb.matched, reason, plan, edits)

    def dfs(self, plan: dict[str, Any], fb: Feedback, edits: list[str]) -> Result | None:
        if fb.reproduced:
            return Result("reproduced", "", self.runs, plan, self.offset, edits)
        got, i = self.compared(fb.events), fb.matched
        if i >= len(self.want) and len(got) == len(self.want):
            self.note(fb, plan, edits, "every line matches; the run differs in what the log does not show")
            return None
        if len(edits) >= self.max_edits:
            self.hit_cap = True
            self.note(fb, plan, edits, f"{self.max_edits} edits kept without reproducing")
            return None
        base, tried = self.score(fb), 0
        times = self.send_times(fb.events)
        ordered = sorted(self.candidates(plan, fb), key=lambda nc: self.edit_time(plan, nc, times))
        for name, cand in ordered:
            c = canonical(cand)
            if c in self.visited or not self.limits.ok(cand):
                continue
            if tried >= self.max_tries:
                break
            self.visited.add(c)
            tried += 1
            nfb = self.run(cand)
            if nfb is None:
                raise _BudgetUsed
            if nfb.reproduced or self.better(self.score(nfb), base):
                found = self.dfs(cand, nfb, edits + [name])
                if found is not None:
                    return found
        e = self.want[i] if i < len(self.want) else None
        g = got[i] if i < len(got) else None
        self.note(fb, plan, edits, f"no edit improves line {i}: expected {_show(e, self.offset)}, got {_show(g)}")
        return None


class _BudgetUsed(Exception):
    pass


def _desc(key: Mapping[str, Any]) -> str:
    return f"{key['dir']} {key['msg']} {key['req_id']} k={key['k']}"


def reconstruct(log: Sequence[Event], actor: str, quiet: frozenset[str], polls: tuple[str, str], limits: Limits,
                oracle: Oracle, *, clock_known: bool, max_edits: int = MAX_EDITS,
                max_tries: int = MAX_TRIES_PER_LINE, start: dict[str, Any] | None = None,
                kinds: frozenset[str] | None = None, extra: Extra | None = None) -> Result:
    """Look for a plan that reproduces ``log`` (see the module docstring).

    ``clock_known``: the log's clock is the simulator's (no offset to estimate).
    ``start``: the plan to start from (default :func:`empty_plan`); its entries are counted in
    ``Result.start_entries``, apart from search edits, and ``max_edits`` limits search edits only.
    ``kinds``: compare only lines of these kinds (driven replay compares receives only; the
    oracle's ``matched`` must count the same lines).
    ``extra``: more candidate edits for a mismatched line, tried first (see :data:`Extra`).
    """
    return _Search(log, actor, quiet, polls, limits, oracle, clock_known, max_edits, max_tries,
                   start, kinds, extra).search()
