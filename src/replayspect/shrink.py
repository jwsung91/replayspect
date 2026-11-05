"""Shrinking: the smallest fault plan that still breaks the same contract.

Starting from a failing run's explicit plan, faults (message drops,
duplicates, disconnects) are removed while the **target contract is still
violated**. Baseline delays are never removed: they are the timing of the
original run, not faults.

"Still violated" means the target contract ID appears among the run's
violations. It deliberately does not compare the first violation's ``seq``
or ``req_id``: removing any fault changes how many events come before the
failure (and, when retries change, which ids later commands get), so those
values move even when the same bug fires. ``seq`` and the trace digest are
for checking that a *given* plan replays exactly, see
:func:`replayspect.runner.replay`.

Removal is delta-debugging style: try dropping large chunks first, then
halve the chunk size, and finish with single items until no single removal
keeps the failure (the result is 1-minimal).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from replayspect.contract import ContractSet
from replayspect.runner import Run, System, run_once
from replayspect.sim.link import Disconnect, FaultPlan, MessageFault, MsgKey

Item = Union[MessageFault, Disconnect]


@dataclass
class ShrinkResult:
    run: Run                  # the final run, with the minimal plan
    plan: FaultPlan
    target: str
    faults_before: int        # message faults + disconnects in the starting plan
    faults_after: int
    runs: int                 # simulations spent while shrinking
    default_delay_sends: int  # sends in the final run with no delay entry in the plan

    def summary(self) -> dict[str, int]:
        return {
            "faults_before": self.faults_before,
            "faults_after": self.faults_after,
            "runs": self.runs,
            "default_delay_sends": self.default_delay_sends,
        }


def _items(plan: FaultPlan) -> list[Item]:
    disc = sorted(plan.disconnects, key=lambda d: d.t_us)
    faults = sorted(plan.faults, key=lambda f: f.key.sort_key())
    return [*disc, *faults]


def _plan(base: FaultPlan, keep: list[Item]) -> FaultPlan:
    return FaultPlan(
        base.delays,
        tuple(i for i in keep if isinstance(i, MessageFault)),
        tuple(i for i in keep if isinstance(i, Disconnect)),
    )


def default_delay_sends(run: Run) -> int:
    """Sends whose delay came from the profile minimum because the plan had no entry.

    After shrinking, messages that did not exist in the original run (for
    example the answer to a request that used to be dropped) have no
    recorded delay. A large count means the shrunk run's timing has drifted
    further from the original.
    """
    if run.plan is None:
        return 0
    n = 0
    for ev in run.trace:
        if ev.kind == "send" and "link" in ev.data:
            link = ev.data["link"]
            if run.plan.delay(MsgKey(link["dir"], ev.name, ev.req_id, link["k"])) is None:
                n += 1
    return n


def shrink(
    system: System,
    failing: Run,
    target: str,
    contracts: ContractSet | None = None,
    max_runs: int = 5_000,
) -> ShrinkResult:
    """Shrink ``failing`` (whose plan must violate ``target``) to a 1-minimal plan."""
    if failing.plan is None:
        raise ValueError("shrink needs a run with an explicit plan")
    cs = contracts if contracts is not None else system.contracts()
    base = failing.plan
    items = _items(base)
    before = len(items)
    runs = 0
    best = failing

    def fails(keep: list[Item]) -> Run | None:
        nonlocal runs
        runs += 1
        r = run_once(system, failing.seed, failing.mutants, _plan(base, keep), cs, failing.until_us)
        return r if target in r.violated() else None

    # Trying with no faults at all first: some bugs need none.
    if items:
        r = fails([])
        if r is not None:
            items, best = [], r

    chunk = max(1, len(items) // 2)
    while items and runs < max_runs:
        removed = False
        i = 0
        while i < len(items) and runs < max_runs:
            candidate = items[:i] + items[i + chunk:]
            r = fails(candidate)
            if r is not None:
                items, best, removed = candidate, r, True
            else:
                i += chunk
        if chunk == 1 and not removed:
            break
        if not removed:
            chunk = max(1, chunk // 2)

    plan = _plan(base, items)
    if best.plan != plan:  # the starting run, nothing removed
        best = run_once(system, failing.seed, failing.mutants, plan, cs, failing.until_us)
        runs += 1
    return ShrinkResult(best, plan, target, before, len(items), runs, default_delay_sends(best))


def best_repro(
    system: System,
    seeds,
    mutants=(),
    target: str = "",
    contracts: ContractSet | None = None,
    candidates: int = 5,
) -> tuple[ShrinkResult | None, int]:
    """Shrink up to ``candidates`` failing seeds and keep the smallest result.

    How small a failure shrinks depends on the seed: the same bug may need
    two faults in one run and six in another. Returns the smallest result
    (ties go to the earlier seed) and the number of seeds tried, or
    ``(None, tried)`` if no seed violated ``target``.
    """
    cs = contracts if contracts is not None else system.contracts()
    best: ShrinkResult | None = None
    found = tried = 0
    for seed in seeds:
        tried += 1
        rnd = run_once(system, seed, mutants, None, cs)
        if target not in rnd.violated():
            continue
        explicit = run_once(system, seed, mutants, FaultPlan.from_trace(rnd.trace), cs)
        if explicit.trace.digest() != rnd.trace.digest():
            raise RuntimeError(f"seed {seed}: explicit plan did not replay the random run")
        r = shrink(system, explicit, target, cs)
        if best is None or r.faults_after < best.faults_after:
            best = r
        found += 1
        if found >= candidates:
            break
    return best, tried
