"""Incidents: a hidden failing run, the partial log a planner gets of it, and the WP4 match.

An **incident** is one failing run kept from the planner: system, mutants or
an implementation variant, seed, an explicit fault plan, and which side's log
the planner sees. Incident files hold the answer; keep them where the planner
cannot read them.

The planner sees a **view**: one participant's events of the hidden run,
with channel metadata (``data.link``) removed, ``seq`` renumbered from 0 and,
optionally, a constant clock offset added to every time. One offset per view:
the participant's clock is off by an unknown constant, not jittered.

:func:`wp4_match` is the temporary reproduction judge of the WP4 experiment.
WP6 replaces it with the symptom judge. A candidate run reproduces the
incident when, on the viewed participant:

1. the compared lines (every event except the periodic poll messages) are the
   same, in the same order: kind, name, req_id and data without ``link``;
2. every compared line happens within the tolerance of the incident's time;
3. with ``status_rule``, the poll replies show the same sequence of data once
   consecutive repeats are merged (the only trace of the other side's state
   in some views);
4. the run violates the same set of contracts as the incident.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from replayspect.runner import Run, System, get_system, run_once
from replayspect.sim.link import FaultPlan
from replayspect.trace import Event, Trace
from replayspect.tracefile import Header, Slice, canonical, trace_file_text

INCIDENT_FORMAT = "replayspect.incident/1"
#: Tolerance used for the reproduction verdict, and the ones recorded alongside it.
TOLERANCE_US = 250_000
DIAGNOSTIC_TOLERANCES_US = (100_000, 250_000, 500_000, 1_000_000)


@dataclass(frozen=True)
class Incident:
    system: str
    seed: int
    plan: FaultPlan
    until_us: int
    #: Participant whose log the planner sees, e.g. ``"device"``.
    actor: str
    clock_offset_us: int = 0
    mutants: tuple[str, ...] = ()
    variant: str | None = None
    status_rule: bool = False
    tolerance_us: int = TOLERANCE_US
    #: What the hidden run produced: ``{"digest": ..., "violated": [...]}``.
    expect: Mapping[str, Any] = field(default_factory=dict)
    #: One line a person on site would report, written by the operator; given to planners.
    symptom: str | None = None

    def __post_init__(self) -> None:
        if self.mutants and self.variant is not None:
            raise ValueError("mutants and a variant cannot be combined")
        if self.clock_offset_us < 0:
            raise ValueError("clock_offset_us must be >= 0 (trace times are never negative)")
        if self.symptom is not None and (not self.symptom.strip() or "\n" in self.symptom):
            raise ValueError("symptom must be one non-empty line")

    def system_obj(self) -> System:
        return get_system(self.system, self.variant)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": INCIDENT_FORMAT, "system": self.system, "seed": self.seed, "plan": self.plan.to_dict(),
            "until_us": self.until_us, "actor": self.actor, "clock_offset_us": self.clock_offset_us,
            "mutants": list(self.mutants), "variant": self.variant, "status_rule": self.status_rule,
            "tolerance_us": self.tolerance_us, "expect": dict(self.expect),
            **({"symptom": self.symptom} if self.symptom is not None else {}),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Incident":
        if d.get("format") != INCIDENT_FORMAT:
            raise ValueError(f"not a {INCIDENT_FORMAT} document")
        return cls(
            d["system"], d["seed"], FaultPlan.from_dict(d["plan"]), d["until_us"], d["actor"],
            d.get("clock_offset_us", 0), tuple(d.get("mutants", ())), d.get("variant"),
            d.get("status_rule", False), d.get("tolerance_us", TOLERANCE_US), d.get("expect", {}),
            d.get("symptom"),
        )


def read_incident(path: Path | str) -> Incident:
    return Incident.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_incident(inc: Incident, path: Path | str) -> Path:
    """Write ``inc`` as a new file (never overwrites)."""
    path = Path(path)
    with path.open("x", encoding="utf-8") as f:
        f.write(json.dumps(inc.to_dict(), indent=2, sort_keys=True) + "\n")
    return path


def run_incident(inc: Incident, system: System | None = None) -> Run:
    """Run the hidden run (on ``system``, by default the incident's own)."""
    s = system if system is not None else inc.system_obj()
    return run_once(s, inc.seed, inc.mutants if s.variant is None else (), inc.plan, None, inc.until_us)


def with_expect(inc: Incident) -> Incident:
    """``inc`` with ``expect`` filled from its hidden run."""
    run = run_incident(inc)
    return replace(inc, expect={"digest": run.trace.digest(), "violated": sorted(run.violated())})


# -- the planner's view ----------------------------------------------------------------------


def view_events(trace: Trace | Sequence[Event], actor: str, clock_offset_us: int = 0) -> list[Event]:
    """One participant's events as the planner sees them."""
    out = []
    for ev in trace:
        if ev.actor != actor:
            continue
        data = {k: v for k, v in ev.data.items() if k != "link"}
        out.append(Event(len(out), ev.t_us + clock_offset_us, ev.actor, ev.kind, ev.name, ev.req_id, data,
                         ev.fidelity, ev.source))
    return out


def run_view(trace: Trace | Sequence[Event], actor: str) -> list[Event]:
    """One participant's events of a planner's **own** run.

    Like :func:`view_events` (one actor, ``seq`` renumbered), but channel
    metadata stays: it describes the planner's own run, not the hidden one.
    Each received copy also gets ``link.sent_us`` and ``link.delay_us``, the
    send time and drawn delay of the message, taken from the matching send.
    This is what lets a planner (or :mod:`replayspect.reconstruct`) turn
    "this line came 0.3 s too early" into a plan entry.
    """
    sends: dict[tuple, tuple[int, int]] = {}
    out = []
    for ev in trace:
        link = ev.data.get("link")
        if ev.kind == "send" and link is not None:
            sends[(link["dir"], ev.name, ev.req_id, link["k"])] = (ev.t_us, link["delay_us"])
        if ev.actor != actor:
            continue
        data = dict(ev.data)
        if ev.kind == "recv" and link is not None:
            sent = sends.get((link["dir"], ev.name, ev.req_id, link["k"]))
            if sent is not None:
                data["link"] = {**link, "sent_us": sent[0], "delay_us": sent[1]}
        out.append(Event(len(out), ev.t_us, ev.actor, ev.kind, ev.name, ev.req_id, data, ev.fidelity, ev.source))
    return out


def view_header(inc: Incident) -> Header:
    """Header of a planner view: nothing that identifies the run, plan, contracts or full trace.

    ``until_us`` is null too: with a clock offset, the run's end in the view's
    clock would give the offset away.
    """
    return Header(system=inc.system, source="sim", seed=None, plan=None, contracts=None, until_us=None,
                  slice=Slice(window=None, actors=(inc.actor,), of=None))


def view_text(inc: Incident, run: Run | None = None) -> str:
    run = run if run is not None else run_incident(inc)
    return trace_file_text(view_events(run.trace, inc.actor, inc.clock_offset_us), view_header(inc))


# -- text log export (WP5b seed-blind test) ---------------------------------------------------

#: Epoch seconds of t = 0 in exported text logs: 2026-11-10T08:00:00+09:00.
TEXT_EPOCH_S = 1794265200


def text_log(events: Sequence[Event], actor: str, ms: bool = False, poll: str = "STATUS",
             poll_reply: str = "STATUS_REPLY") -> str:
    """One participant's events as a ROS 2 style text log (``examples/rules/sim-client-ros.yaml``).

    ``[LEVEL] [epoch.frac] [actor]: ...`` with ``TX``/``RX`` lines for messages (data as
    ``key=value``) and ``result`` lines for the participant's decisions. Times are microseconds,
    or with ``ms`` cut to milliseconds, as many real logs are. Channel metadata is not written: a
    real participant does not know it.
    """
    lines = []
    for e in events:
        if e.actor != actor:
            continue
        sec, frac = TEXT_EPOCH_S + e.t_us // 1_000_000, e.t_us % 1_000_000
        stamp = f"{sec}.{frac // 1000:03d}" if ms else f"{sec}.{frac:06d}"
        level = "DEBUG" if e.name in (poll, poll_reply) else "INFO"
        data = {k: v for k, v in e.data.items() if k != "link"}
        req = f" req={e.req_id}" if e.req_id is not None else ""
        if e.kind in ("send", "recv"):
            kv = "".join(f" {k}={v}" for k, v in sorted(data.items()) if v is not None)
            text = f"{'TX' if e.kind == 'send' else 'RX'} {e.name}{req}{kv}"
        elif e.kind == "handle":
            reply = f" reply={data['msg_req_id']}" if data.get("msg_req_id") is not None else ""
            text = f"result {e.req_id or '-'} {e.name} cause={data.get('cause')}{reply}"
        else:
            kv = "".join(f" {k}={v}" for k, v in sorted(data.items()) if v is not None)
            text = f"{e.kind} {e.name}{req}{kv}"
        lines.append(f"[{level}] [{stamp}] [{actor}]: {text}\n")
    return "".join(lines)


# -- the WP4 match (replaced by the symptom judge in WP6) -------------------------------------


def line_key(ev: Event) -> tuple:
    """What two compared lines must share: kind, name, req_id and data without ``link``."""
    return (ev.kind, ev.name, ev.req_id, canonical({k: v for k, v in ev.data.items() if k != "link"}))


def _show(ev: Event) -> str:
    data = {k: v for k, v in ev.data.items() if k != "link"}
    rid = ev.req_id or "-"
    return f"{ev.kind} {ev.name} {rid}" + (f" {canonical(data)}" if data else "")


def compared_lines(trace: Trace | Sequence[Event], actor: str, quiet: frozenset[str]) -> list[Event]:
    return [e for e in trace if e.actor == actor and e.name not in quiet]


def status_sequence(trace: Trace | Sequence[Event], actor: str, poll_reply: str) -> list[str]:
    """The data of the poll replies on ``actor``, with consecutive repeats merged."""
    seq: list[str] = []
    for e in trace:
        if e.actor == actor and e.name == poll_reply:
            d = canonical({k: v for k, v in e.data.items() if k != "link"})
            if not seq or seq[-1] != d:
                seq.append(d)
    return seq


@dataclass(frozen=True)
class Match:
    reproduced: bool
    matched: int  # compared lines equal from the start, before the first mismatch
    total: int  # compared lines in the incident
    lines_same: bool  # same lines in the same order (times not considered)
    max_dt_us: int | None  # largest time difference over the lines, when lines_same
    status_same: bool | None  # None when the status rule is off
    contracts_same: bool
    within: dict[int, bool]  # tolerance -> verdict with that tolerance (diagnostic)
    digest_same: bool  # exact reproduction (diagnostic; never shown to a planner)
    first_mismatch: dict[str, Any] | None = None

    def for_planner(self, offset_us: int) -> dict[str, Any]:
        """What a planner is told.

        The incident's line is timed in the log's clock and the run's line in
        the run's own clock (the clock of its timeline). Shifting both would
        give the offset away next to the timeline.
        """
        d: dict[str, Any] = {"reproduced": self.reproduced, "lines_matched": f"{self.matched}/{self.total}"}
        if self.first_mismatch is not None:
            fm = self.first_mismatch
            exp_t = fm["expected_t_s"]
            d["first_mismatch"] = {
                "line": fm["line"],
                "expected": fm["expected"],
                "expected_t_s_log_clock": None if exp_t is None else round(exp_t + offset_us / 1e6, 6),
                "got": fm["got"],
                "got_t_s_run_clock": fm["got_t_s"],
            }
        elif not self.reproduced:
            d["note"] = "every log line matched in order and time; the run differs in what the log does not show"
        return d


def wp4_match(inc: Incident, hidden: Run, candidate: Run, system: System) -> Match:
    quiet = system.quiet_messages
    want = compared_lines(hidden.trace, inc.actor, quiet)
    got = compared_lines(candidate.trace, inc.actor, quiet)
    matched, first = 0, None
    for i, w in enumerate(want):
        if i >= len(got):
            first = {"line": i, "expected": _show(w), "expected_t_s": w.t_us / 1e6, "got": None, "got_t_s": None}
            break
        g = got[i]
        if line_key(w) != line_key(g) or abs(w.t_us - g.t_us) > inc.tolerance_us:
            first = {"line": i, "expected": _show(w), "expected_t_s": w.t_us / 1e6,
                     "got": _show(g), "got_t_s": g.t_us / 1e6}
            break
        matched += 1
    if first is None and len(got) > len(want):
        g = got[len(want)]
        first = {"line": len(want), "expected": None, "expected_t_s": None, "got": _show(g), "got_t_s": g.t_us / 1e6}
    lines_same = len(want) == len(got) and all(line_key(w) == line_key(g) for w, g in zip(want, got))
    max_dt = max((abs(w.t_us - g.t_us) for w, g in zip(want, got)), default=0) if lines_same else None
    status_same = None
    if inc.status_rule:
        vocab = system.vocabulary
        reply = vocab.poll_reply if vocab is not None else "STATUS_REPLY"
        status_same = status_sequence(hidden.trace, inc.actor, reply) == status_sequence(
            candidate.trace, inc.actor, reply)
    contracts_same = hidden.violated() == candidate.violated()
    base_ok = lines_same and status_same is not False and contracts_same
    within = {t: base_ok and max_dt is not None and max_dt <= t for t in DIAGNOSTIC_TOLERANCES_US}
    reproduced = base_ok and max_dt is not None and max_dt <= inc.tolerance_us
    return Match(reproduced, matched, len(want), lines_same, max_dt, status_same, contracts_same, within,
                 hidden.trace.digest() == candidate.trace.digest(), first)


# -- preconditions ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Preconditions:
    """Checks every incident must pass before a trial.

    * ``self_match``: the hidden run matches itself.
    * ``correct_differs``: the correct implementation, with the same seed and
      plan, does not reproduce the incident.
    * ``correct_log_differs``: and it is told apart by the log alone (lines or
      status sequence), not only by the contract verdict. Without it the view
      cannot show the defect.
    """

    self_match: bool
    correct_differs: bool
    correct_log_differs: bool
    correct_match: Match

    @property
    def ok(self) -> bool:
        return self.self_match and self.correct_differs and self.correct_log_differs


def check_preconditions(inc: Incident) -> Preconditions:
    system = inc.system_obj()
    hidden = run_incident(inc, system)
    if inc.expect and hidden.trace.digest() != inc.expect.get("digest"):
        raise ValueError("the hidden run no longer has the recorded digest")
    me = wp4_match(inc, hidden, hidden, system)
    correct_system = get_system(inc.system)
    correct = run_once(correct_system, inc.seed, (), inc.plan, None, inc.until_us)
    cm = wp4_match(inc, hidden, correct, correct_system)
    log_differs = not cm.lines_same or cm.status_same is False or (cm.max_dt_us or 0) > inc.tolerance_us
    return Preconditions(me.reproduced, not cm.reproduced, log_differs, cm)


# -- defect answers (operator side) ----------------------------------------------------------


def defect_class(inc: Incident) -> list[str] | None:
    """Published defects that reproduce the incident with its seed and plan.

    Any of them is a right answer to "which defect": the log cannot tell them
    apart. The chance of a right guess is ``len(class) / len(published)``.
    None when the system's defects are not published or the incident runs a
    variant.
    """
    system = get_system(inc.system)
    if not system.published_defects or inc.variant is not None:
        return None
    hidden = run_incident(inc)
    out = []
    for m, _ in system.published_defects:
        run = run_once(system, inc.seed, (m,), inc.plan, None, inc.until_us)
        if wp4_match(inc, hidden, run, system).reproduced:
            out.append(m)
    return out
