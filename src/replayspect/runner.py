"""Running systems under test: random search, repro files and replay.

A **system** couples a runnable integration with its contract file: the
virtual lift (``lift.v0``) and the virtual turntable (``turntable.v0``). A
system can also run an implementation variant loaded from outside the
package (:mod:`replayspect.variant`).

A **repro file** is everything needed to rerun a failure exactly: the
system, seed, mutants, how long the run lasted, and the explicit fault plan.
It also records what the run is expected to produce (trace digest and the
first violation of each contract), so a replay can prove it reproduced the
same execution, not just a similar one.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from replayspect import __version__
from replayspect.contract import (
    ContractSet,
    EventPattern,
    Violation,
    contract_patterns,
    first_violation_details,
    judge,
    load_contracts,
    matched_patterns,
)
from replayspect.sim.link import ChannelProfile, FaultPlan, PlanReport, plan_report
from replayspect.trace import Trace
from replayspect.variant import VariantRef, load_variant, variant_run

REPRO_FORMAT = "replayspect.repro/1"
ROOT = Path(__file__).resolve().parents[2]


# -- systems --------------------------------------------------------------------------

RunFn = Callable[[int, "FaultPlan | None", tuple[str, ...], int], Trace]


@dataclass(frozen=True)
class PlanVocabulary:
    """Message keys a generated plan may target, read off the protocol description.

    Only what a planner can learn from the protocol goes here, never anything
    about mutants: generated plans must start from the same knowledge.
    """

    #: Move commands as ``(req_id, c2s message name)``.
    commands: tuple[tuple[str, str], ...]
    #: Device messages that answer a move command.
    command_replies: tuple[str, ...]
    #: Request ids of periodic polls.
    polls: tuple[str, ...]
    poll_request: str
    poll_reply: str
    #: Largest ``k`` to target. Resends after reconnects can go higher; see the design notes.
    max_k: int


def _lift_vocabulary() -> PlanVocabulary:
    # protocol-lift.md: 6 commands alternating MOVE_UP / MOVE_DOWN from MOVE_UP, ids r-0001...;
    # at most two resends; STATUS every second over a 90 s run, ids s-0001...
    return PlanVocabulary(
        commands=tuple((f"r-{n:04d}", "MOVE_UP" if n % 2 else "MOVE_DOWN") for n in range(1, 7)),
        command_replies=("ACK", "DONE", "ERROR"),
        polls=tuple(f"s-{n:04d}" for n in range(1, 91)),
        poll_request="STATUS",
        poll_reply="STATUS_REPLY",
        max_k=3,
    )


def _turntable_vocabulary() -> PlanVocabulary:
    # protocol-turntable.md: 6 commands in a fixed order, ids r-0001...; at most two resends;
    # STATUS every second over a 90 s run, ids s-0001...
    from replayspect.sut.turntable import SEQUENCE

    return PlanVocabulary(
        commands=tuple((f"r-{n:04d}", cmd) for n, cmd in enumerate(SEQUENCE, start=1)),
        command_replies=("ACK", "DONE", "ERROR"),
        polls=tuple(f"s-{n:04d}" for n in range(1, 91)),
        poll_request="STATUS",
        poll_reply="STATUS_REPLY",
        max_k=3,
    )


@dataclass(frozen=True)
class System:
    name: str
    run: RunFn  # (seed, plan, mutants, until_us) -> trace
    contracts_path: Path
    until_us: int
    profile: ChannelProfile
    #: Message names left out of run summaries (periodic polling and the like).
    quiet_messages: frozenset[str] = frozenset()
    #: Description of the protocol for planners. Must not mention mutants.
    protocol_path: Path | None = None
    #: Message keys for generated plans (the Hypothesis baseline).
    vocabulary: PlanVocabulary | None = None
    #: Set when ``run`` is an implementation variant (see :func:`get_system`).
    variant: VariantRef | None = None
    #: Published defects ``(id, description)``: the mutant list a planner may choose from
    #: (WP4 condition A). Empty when the system's defects are not published.
    published_defects: tuple[tuple[str, str], ...] = ()

    def contracts(self) -> ContractSet:
        return load_contracts(self.contracts_path)


def _run_lift(seed: int, plan: FaultPlan | None, mutants: tuple[str, ...], until_us: int) -> Trace:
    from replayspect.sut.lift import run_lift

    return run_lift(seed, plan=plan, mutants=mutants, until_us=until_us)


def _lift_defects() -> tuple[tuple[str, str], ...]:
    from replayspect.sut.lift import MUTANTS

    return tuple(MUTANTS.items())


def _lift_profile() -> ChannelProfile:
    from replayspect.sut.lift import SEARCH_PROFILE

    return SEARCH_PROFILE


def _run_turntable(seed: int, plan: FaultPlan | None, mutants: tuple[str, ...], until_us: int) -> Trace:
    from replayspect.sut.turntable import run_turntable

    return run_turntable(seed, plan=plan, mutants=mutants, until_us=until_us)


def _turntable_profile() -> ChannelProfile:
    from replayspect.sut.turntable import SEARCH_PROFILE

    return SEARCH_PROFILE


SYSTEMS: dict[str, System] = {
    "lift.v0": System(
        "lift.v0", _run_lift, ROOT / "contracts" / "lift.v0.yaml", 90_000_000,
        _lift_profile(), frozenset({"STATUS", "STATUS_REPLY"}), ROOT / "docs" / "protocol-lift.md",
        _lift_vocabulary(), published_defects=_lift_defects(),
    ),
    "turntable.v0": System(
        "turntable.v0", _run_turntable, ROOT / "contracts" / "turntable.v0.yaml", 90_000_000,
        _turntable_profile(), frozenset({"STATUS", "STATUS_REPLY"}), ROOT / "docs" / "protocol-turntable.md",
        _turntable_vocabulary(),
    ),
}


def get_system(name: str, variant: str | None = None) -> System:
    """The registered system ``name``; with ``variant``, running that implementation instead.

    Only the run function changes. Contracts, protocol description, link
    profile and run length are the registered system's.
    """
    try:
        system = SYSTEMS[name]
    except KeyError:
        raise ValueError(f"unknown system {name!r}; known: {sorted(SYSTEMS)}") from None
    if variant is None:
        return system
    v, ref = load_variant(variant)
    if v.system != name:
        raise ValueError(f"variant {variant} implements {v.system}, not {name}")
    return replace(system, run=variant_run(v, system.profile), variant=ref)


# -- single runs --------------------------------------------------------------------------


@dataclass
class Run:
    system: str
    seed: int
    mutants: tuple[str, ...]
    until_us: int
    plan: FaultPlan | None
    trace: Trace
    violations: list[Violation]
    plan_report: PlanReport | None = None  # set when a plan was given
    variant: VariantRef | None = None  # set when the system ran a variant

    def violated(self) -> set[str]:
        return {v.contract for v in self.violations}

    def first(self) -> list[Violation]:
        return first_violation_details(self.violations)

    def first_of(self, contract: str) -> Violation | None:
        return next((v for v in self.first() if v.contract == contract), None)

    def context(self, seq: int, before: int = 8, after: int = 4) -> list[dict[str, Any]]:
        """Events around ``seq`` (as dicts), for explaining a violation."""
        events = self.trace.events
        lo, hi = max(0, seq - before), min(len(events), seq + after + 1)
        return [e.to_dict() for e in events[lo:hi]]


def run_once(
    system: System,
    seed: int,
    mutants: Iterable[str] = (),
    plan: FaultPlan | None = None,
    contracts: ContractSet | None = None,
    until_us: int | None = None,
) -> Run:
    ms = tuple(sorted(mutants))
    if ms and system.variant is not None:
        raise ValueError("mutants and a variant cannot be combined")
    end = system.until_us if until_us is None else until_us
    trace = system.run(seed, plan, ms, end)
    cs = contracts if contracts is not None else system.contracts()
    report = plan_report(plan, trace) if plan is not None else None
    return Run(system.name, seed, ms, end, plan, trace, judge(trace, cs, end), report, system.variant)


# -- search -------------------------------------------------------------------------------------


@dataclass
class SearchResult:
    runs: int = 0
    hits: dict[str, int] = field(default_factory=dict)        # contract -> runs violating it
    first_seed: dict[str, int] = field(default_factory=dict)  # contract -> first violating seed
    unmatched: set[EventPattern] = field(default_factory=set)
    failures: list[Run] = field(default_factory=list)          # first failing run per contract
    kept: list[Run] = field(default_factory=list)              # failing runs of ``keep_for``


def search(
    system: System,
    seeds: Iterable[int],
    mutants: Iterable[str] = (),
    contracts: ContractSet | None = None,
    keep_for: str | None = None,
    keep: int = 0,
) -> SearchResult:
    """Run random-fault seeds and collect, per contract, how often it failed.

    ``unmatched`` lists contract patterns that matched no event in any run.
    A contract whose pattern never matched could not have failed; a typo in
    a message name looks exactly like "no violations".

    With ``keep_for`` and ``keep``, the first ``keep`` runs violating that
    contract are kept in ``kept`` so they can be shrunk without running the
    same seeds again. Every seed in ``seeds`` is still run.
    """
    cs = contracts if contracts is not None else system.contracts()
    ms = tuple(mutants)
    res = SearchResult(unmatched=set(contract_patterns(cs)))
    for seed in seeds:
        run = run_once(system, seed, ms, None, cs)
        res.runs += 1
        if res.unmatched:
            res.unmatched -= matched_patterns(run.trace, cs)
        violated = run.violated()
        for c in sorted(violated):
            res.hits[c] = res.hits.get(c, 0) + 1
            if c not in res.first_seed:
                res.first_seed[c] = seed
                res.failures.append(run)
        if keep_for in violated and len(res.kept) < keep:
            res.kept.append(run)
    return res


# -- repro files ----------------------------------------------------------------------------------


def harness_version() -> dict[str, Any]:
    """Package version and, when available, the git commit of the checkout."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {"version": __version__, "git": commit}


def violation_dict(v: Violation) -> dict[str, Any]:
    return {"contract": v.contract, "seq": v.seq, "req_id": v.req_id, "detail": v.detail}


def explain(run: Run, target: str, before: int = 8, after: int = 4) -> dict[str, Any]:
    """The target's first violation and the events around it, for a human reader.

    Not compared on replay; it is there to make a repro understandable.
    """
    v = run.first_of(target)
    if v is None:
        raise ValueError(f"run does not violate {target}")
    key_events = [e.to_dict() for e in run.trace if v.req_id is not None and e.req_id == v.req_id]
    return {
        "violation": violation_dict(v),
        "events": run.context(v.seq, before, after),
        "key_events": key_events[:40],  # everything that happened to the violating req_id
    }


def make_repro(run: Run, target: str, shrink: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a repro document for ``run``. The run must have an explicit plan."""
    if run.plan is None:
        raise ValueError("a repro needs an explicit plan; use FaultPlan.from_trace(run.trace)")
    if target not in run.violated():
        raise ValueError(f"run does not violate {target}")
    doc: dict[str, Any] = {
        "format": REPRO_FORMAT,
        "system": run.system,
        "harness": harness_version(),
        "seed": run.seed,
        "mutants": list(run.mutants),
        "until_us": run.until_us,
        "target": target,
        "plan": run.plan.to_dict(),
        "expect": {
            "digest": run.trace.digest(),
            "first_violations": [violation_dict(v) for v in run.first()],
        },
        "explain": explain(run, target),
    }
    if run.variant is not None:
        doc["variant"] = run.variant.to_dict()
    if shrink is not None:
        doc["shrink"] = dict(shrink)
    return doc


def write_repro(doc: Mapping[str, Any], path: Path, exclusive: bool = False) -> Path:
    """Write ``doc`` as JSON. With ``exclusive``, raise FileExistsError instead of overwriting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("x" if exclusive else "w", encoding="utf-8") as f:
        f.write(text)
    return path


def read_repro(path: Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("format") != REPRO_FORMAT:
        raise ValueError(f"{path}: not a {REPRO_FORMAT} file")
    return doc


@dataclass
class ReplayResult:
    run: Run
    digest_ok: bool
    violations_ok: bool
    target_ok: bool
    #: Set when the repro names a variant whose file changed since the repro was written.
    #: Not a failure by itself: the digest decides whether the run is the same.
    variant_note: str | None = None

    @property
    def ok(self) -> bool:
        return self.digest_ok and self.violations_ok and self.target_ok


def replay(doc: Mapping[str, Any], contracts: ContractSet | None = None) -> ReplayResult:
    """Rerun a repro and check it produced exactly the recorded execution."""
    recorded = doc.get("variant")
    system = get_system(doc["system"], recorded["spec"] if recorded else None)
    note = None
    if recorded and system.variant is not None and system.variant.sha256 != recorded.get("sha256"):
        note = f"variant file changed since the repro was written: {recorded['spec']}"
    plan = FaultPlan.from_dict(doc["plan"])
    run = run_once(system, doc["seed"], doc["mutants"], plan, contracts, doc["until_us"])
    expect = doc["expect"]
    return ReplayResult(
        run,
        digest_ok=run.trace.digest() == expect["digest"],
        violations_ok=[violation_dict(v) for v in run.first()] == expect["first_violations"],
        target_ok=doc["target"] in run.violated(),
        variant_note=note,
    )


# -- summaries for planners -------------------------------------------------------------------


def _s(us: int) -> str:
    return f"{us / 1_000_000:.3f}"


def summary_line(ev: Any) -> str:
    """One compact, human- and model-readable line per event."""
    d, rid = ev.data, ev.req_id or "-"
    head = f"{_s(ev.t_us)}s {ev.actor} {ev.kind} {ev.name} {rid}"
    if ev.kind == "send" and "link" in d:
        return f"{head} k={d['link']['k']} delay={_s(d['link']['delay_us'])}s"
    if ev.kind == "recv" and "link" in d:
        extra = " (duplicate copy)" if d["link"].get("copy") else ""
        return f"{head} k={d['link']['k']}{extra}"
    if ev.kind == "state":
        return f"{head} (from {d.get('from')} on {d.get('on')})"
    if ev.kind == "handle":
        return f"{head} (cause {d.get('cause')}, message {d.get('msg_req_id')})"
    if ev.kind == "fault" and ev.name in ("drop", "duplicate"):
        what = d.get("reason") if ev.name == "drop" else f"extra={_s(d.get('extra_us', 0))}s"
        return f"{_s(ev.t_us)}s link {ev.name} {d.get('dir')} {d.get('msg')} {rid} k={d.get('k')} {what}"
    if ev.kind == "fault" and ev.name == "disconnect":
        return f"{_s(ev.t_us)}s link disconnect for {_s(d.get('duration_us', 0))}s"
    if ev.kind == "fault":
        return f"{_s(ev.t_us)}s link {ev.name}"
    return head


def run_summary(run: Run, system: System, max_lines: int = 250) -> list[str]:
    """The run's timeline without quiet messages, one line per event.

    Gives a planner the message keys (``msg``, ``req_id``, ``k``) and timing it
    needs to target faults, whether or not anything was violated.
    """
    quiet = system.quiet_messages
    lines = []
    for ev in run.trace:
        if ev.name in quiet or (ev.kind == "fault" and ev.data.get("msg") in quiet):
            continue
        lines.append(summary_line(ev))
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... {len(lines) - max_lines} more lines omitted"]
    return lines
