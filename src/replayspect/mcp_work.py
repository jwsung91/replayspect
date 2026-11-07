"""MCP server for a developer's own work: ``python3 -m replayspect.mcp_work --repros DIR``.

Three tools over stdio, for using replayspect from an MCP client such as
Claude Code while working on a system:

* ``search``: random-fault seeds, which contracts failed, and (with a
  target) the smallest shrunk failure written as a repro file
* ``shrink``: shrink one failing run, from an explicit plan or a seed's
  random faults, and write the result as a repro file
* ``replay``: rerun a repro file and check it reproduces the recorded run

This is **not** the planning-session server (``replayspect.mcp_server``).
Mutants, seeds and contracts are ordinary arguments here and nothing is
hidden, budgeted or logged; never give these tools to a planner in a trial.
Repro files are read and written only inside ``--repros``, by plain file
name, and never overwritten.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from replayspect.runner import (
    Run,
    get_system,
    make_repro,
    read_repro,
    replay,
    run_once,
    search,
    violation_dict,
    write_repro,
)
from replayspect.shrink import ShrinkResult, best_repro, shrink
from replayspect.sim.link import FaultPlan, check_plan_bounds

INSTRUCTIONS = (
    "replayspect runs a robot-to-lift integration in a deterministic simulator and checks it "
    "against behavioural contracts. search runs random-fault seeds (optionally with seeded bugs, "
    "'mutants') and shrinks failures of a target contract into repro files; shrink minimizes one "
    "failing run; replay reruns a repro file and checks it reproduces exactly."
)

MAX_CANDIDATES = 20


def _error(exc: Exception | str) -> dict[str, Any]:
    return {"status": "error", "error": str(exc)}


@dataclass
class Workspace:
    """The tools' logic, without MCP. ``root`` is the only directory touched."""

    root: Path
    system: str = "lift.v0"
    max_seeds: int = 10_000

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self._system = get_system(self.system)
        self._contracts = self._system.contracts()

    # -- tools ---------------------------------------------------------------------------

    def search(
        self,
        mutants: list[str] | None = None,
        seeds: int = 1000,
        seed_start: int = 0,
        target: str | None = None,
        candidates: int = 5,
    ) -> dict[str, Any]:
        ms = tuple(mutants or ())
        try:
            if not 1 <= seeds <= self.max_seeds:
                raise ValueError(f"seeds must be between 1 and {self.max_seeds}")
            if target is not None:
                self._check_target(target)
                if not 1 <= candidates <= MAX_CANDIDATES:
                    raise ValueError(f"candidates must be between 1 and {MAX_CANDIDATES}")
            res = search(self._system, range(seed_start, seed_start + seeds), ms, self._contracts,
                         keep_for=target, keep=candidates if target else 0)
        except ValueError as exc:
            return _error(exc)
        out: dict[str, Any] = {
            "status": "ok",
            "system": self.system,
            "mutants": sorted(ms),
            "runs": res.runs,
            "hits": {c: {"runs": res.hits[c], "first_seed": res.first_seed[c]}
                     for c in self._contracts.ids() if c in res.hits},
            "never_exercised": sorted(map(str, res.unmatched)),
            "repro": None,
        }
        if target is None:
            return out
        if target not in res.hits:
            out["note"] = f"target {target} was not violated; nothing to shrink"
            return out
        best = best_repro(self._system, res.kept, target, self._contracts)
        assert best is not None
        out["repro"] = self._write(best, extra_runs=res.runs)
        return out

    def shrink(
        self,
        seed: int,
        target: str,
        mutants: list[str] | None = None,
        plan: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        ms = tuple(mutants or ())
        try:
            self._check_target(target)
            if plan is None:
                rnd = run_once(self._system, seed, ms, None, self._contracts)
                self._check_violates(rnd, target)
                best = best_repro(self._system, [rnd], target, self._contracts)
                assert best is not None
            else:
                failing = run_once(self._system, seed, ms, self._parse(plan), self._contracts)
                self._check_violates(failing, target)
                best = shrink(self._system, failing, target, self._contracts)
        except ValueError as exc:
            return _error(exc)
        return {"status": "ok", "repro": self._write(best)}

    def replay(self, name: str) -> dict[str, Any]:
        try:
            path = self._path(name)
            if not path.is_file():
                raise ValueError(f"no repro named {name!r} in the repro directory")
            doc = read_repro(path)
            r = replay(doc, self._contracts if doc.get("system") == self.system else None)
        except (ValueError, KeyError) as exc:
            return _error(exc)
        return {
            "status": "ok",
            "ok": r.ok,
            "digest_ok": r.digest_ok,
            "violations_ok": r.violations_ok,
            "target_ok": r.target_ok,
            "system": doc["system"],
            "seed": doc["seed"],
            "mutants": doc["mutants"],
            "target": doc["target"],
            "first_violations": [violation_dict(v) for v in r.run.first()],
        }

    # -- helpers -------------------------------------------------------------------------

    def _check_target(self, target: str) -> None:
        if target not in self._contracts.ids():
            raise ValueError(f"unknown contract {target!r}; known: {list(self._contracts.ids())}")

    @staticmethod
    def _check_violates(run: Run, target: str) -> None:
        if target not in run.violated():
            got = ", ".join(sorted(run.violated())) or "nothing"
            raise ValueError(f"seed {run.seed} with this plan does not violate {target} (violated: {got})")

    def _parse(self, plan: Mapping[str, Any] | str) -> FaultPlan:
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except json.JSONDecodeError as exc:
                raise ValueError(f"plan is not valid JSON: {exc}") from None
        parsed = FaultPlan.from_dict(plan)
        # Values random search could never draw would make a "bug" that cannot happen.
        check_plan_bounds(parsed, self._system.profile, self._system.until_us)
        return parsed

    def _path(self, name: str) -> Path:
        if not name or Path(name).name != name or name.startswith("."):
            raise ValueError(f"{name!r}: give a plain file name inside the repro directory")
        if not name.endswith(".json"):
            raise ValueError(f"{name!r}: repro files end in .json")
        return self.root / name

    def _write(self, best: ShrinkResult, extra_runs: int = 0) -> dict[str, Any]:
        run, target = best.run, best.target
        doc = make_repro(run, target, best.summary())
        stem = f"{run.system}-{'-'.join(run.mutants) or 'none'}-{target}-seed{run.seed}"
        n = 1
        while True:
            name = f"{stem}.json" if n == 1 else f"{stem}-{n}.json"
            try:
                write_repro(doc, self.root / name, exclusive=True)
                break
            except FileExistsError:
                n += 1
        return {
            "name": name,
            "seed": run.seed,
            "faults_before": best.faults_before,
            "faults_after": best.faults_after,
            "simulations": extra_runs + (best.total_runs or best.runs),
            "violation": doc["explain"]["violation"],
        }


def build_server(workspace: Workspace):
    from replayspect.mcp_server import _server_class

    server = _server_class()("replayspect-work", instructions=INSTRUCTIONS)

    @server.tool()
    def search(
        mutants: list[str] | None = None,
        seeds: int = 1000,
        seed_start: int = 0,
        target: str | None = None,
        candidates: int = 5,
    ) -> dict[str, Any]:
        """Run random-fault seeds seed_start .. seed_start+seeds-1 and report, per contract, how
        many runs violated it and the first violating seed. mutants are seeded bugs to switch on
        (for lift.v0: M1..M8). With target (a contract ID such as C3), shrink up to `candidates`
        failing runs and write the smallest as a repro file; the result gives its name."""
        return workspace.search(mutants, seeds, seed_start, target, candidates)

    @server.tool()
    def shrink(
        seed: int,
        target: str,
        mutants: list[str] | None = None,
        plan: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Shrink one run that violates `target` to a minimal fault plan and write it as a repro
        file. Give a fault plan (JSON object or text, same format as repro files' "plan") to shrink
        that plan at `seed`; omit it to shrink the seed's own random faults."""
        return workspace.shrink(seed, target, mutants, plan)

    @server.tool()
    def replay(name: str) -> dict[str, Any]:
        """Rerun the repro file `name` (a file name from search or shrink) and check that the
        trace digest, the first violations and the target violation all match the recording."""
        return workspace.replay(name)

    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m replayspect.mcp_work")
    ap.add_argument("--repros", required=True, help="directory repro files are read from and written to")
    ap.add_argument("--system", default="lift.v0")
    ap.add_argument("--max-seeds", type=int, default=10_000, help="largest seeds value one search may ask for")
    args = ap.parse_args(argv)
    build_server(Workspace(Path(args.repros), args.system, args.max_seeds)).run()  # stdio
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
