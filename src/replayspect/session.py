"""Planning sessions: the rules of a planning experiment, enforced in one place.

A planner (a person, a model behind an MCP client, or a test) explores a
system by submitting fault plans. Within one session, this API enforces
the seed schedule, budget and bounds. Operators must separately isolate
the planner from hidden configuration and register all trials:

* **Hidden configuration.** Mutants are fixed by whoever starts the session
  and never appear in anything returned to the planner.
* **Seed schedule.** The n-th run (counting from 0) uses environment seed
  ``seed_base + n``, the same seeds random search uses for its n-th run. The
  planner never chooses or sees seeds.
* **Budget.** Every call to :meth:`Session.run_plan` counts, including plans
  rejected for bad format or out-of-range values. When the budget is used
  up, further calls are refused without counting.
* **Bounds.** Plans must use ``base: "random"``, stay within the system's
  link profile and contain at most ``max_faults`` faults and disconnects.
* **Log.** Every call is appended to a JSON Lines log, which is enough to
  rerun the session exactly (:func:`verify_log`). Keep the log outside any
  directory the planner can read: it names the mutants. A log path is
  reserved by exclusive creation; restarting with that path is refused.
  Interrupted trials must be reported as interrupted, not restarted.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from replayspect.runner import (
    get_system,
    harness_version,
    run_once,
    run_summary,
)
from replayspect.sim.link import FaultPlan, LinkError, check_plan_bounds

PLAN_FORMAT_PATH = Path(__file__).resolve().parents[2] / "docs" / "plan-format.md"
LOG_FORMAT = "replayspect.session/1"


@dataclass(frozen=True)
class SessionConfig:
    system: str = "lift.v0"
    mutants: tuple[str, ...] = ()
    seed_base: int = 0
    budget: int = 100
    max_faults: int = 20


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Session:
    config: SessionConfig
    log_path: Path | None = None
    used: int = 0
    first_violation_run: int | None = None
    last_record: dict[str, Any] | None = None  # what the last run_plan call logged
    _texts: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.system = get_system(self.config.system)
        self.contracts = self.system.contracts()
        if self.system.protocol_path is None:
            raise ValueError(f"system {self.system.name} has no protocol description for planners")
        self._texts = {
            "protocol": self.system.protocol_path.read_text(encoding="utf-8"),
            "contracts": self.system.contracts_path.read_text(encoding="utf-8"),
            "plan_format": PLAN_FORMAT_PATH.read_text(encoding="utf-8"),
        }
        self._log({
            "type": "session",
            "format": LOG_FORMAT,
            "config": {**asdict(self.config), "mutants": list(self.config.mutants)},
            "until_us": self.system.until_us,
            "hashes": {k: _sha(v) for k, v in self._texts.items()},
            "harness": harness_version(),
            "python": platform.python_version(),
        })

    # -- what the planner sees ---------------------------------------------------------

    def limits(self) -> dict[str, Any]:
        p = self.system.profile
        return {
            "delay_us": {"c2s": list(p.c2s.delay_us), "s2c": list(p.s2c.delay_us)},
            "dup_extra_us": {"c2s": list(p.c2s.dup_extra_us), "s2c": list(p.s2c.dup_extra_us)},
            "disconnect_duration_us": list(p.disconnect_duration_us),
            "run_length_us": self.system.until_us,
            "max_faults_and_disconnects": self.config.max_faults,
        }

    def budget(self) -> dict[str, int]:
        return {"total": self.config.budget, "used": self.used, "left": self.config.budget - self.used}

    def describe(self) -> dict[str, Any]:
        """Everything a planner needs, and nothing about the hidden configuration."""
        return {
            "system": self.system.name,
            "task": (
                "Choose network faults that make the system violate at least one of its "
                "contracts. Submit plans with run_plan; each run uses a new environment seed."
            ),
            "protocol": self._texts["protocol"],
            "contracts": self._texts["contracts"],
            "plan_format": self._texts["plan_format"],
            "limits": self.limits(),
            "budget": self.budget(),
        }

    # -- running -------------------------------------------------------------------------

    def run_plan(self, plan: Mapping[str, Any] | str) -> dict[str, Any]:
        """Run one plan, or explain why it was rejected. Counts against the budget."""
        if self.used >= self.config.budget:
            return {"status": "budget_exhausted", "budget": self.budget()}
        run_index = self.used
        self.used += 1
        seed = self.config.seed_base + run_index
        record: dict[str, Any] = {"type": "run", "run": run_index, "seed": seed, "plan": plan}
        try:
            parsed = self._parse(plan)
        except LinkError as exc:
            record.update(status="rejected", error=str(exc))
            self._log(record)
            return {"status": "rejected", "run": run_index, "error": str(exc), "budget": self.budget()}

        run = run_once(self.system, seed, self.config.mutants, parsed, self.contracts)
        violations = [
            {"contract": v.contract, "req_id": v.req_id, "detail": v.detail,
             "at_s": round(run.trace[v.seq].t_us / 1e6, 3) if v.seq < len(run.trace) else None}
            for v in run.first()
        ]
        if violations and self.first_violation_run is None:
            self.first_violation_run = run_index
        report = run.plan_report.to_dict() if run.plan_report else {}
        record.update(
            status="ok", violated=sorted(run.violated()), digest=run.trace.digest(),
            no_effect={k: len(v) for k, v in report.items()},
        )
        self._log(record)
        return {
            "status": "ok",
            "run": run_index,
            "violations": violations,
            "no_effect": report,
            "timeline": run_summary(run, self.system),
            "budget": self.budget(),
        }

    def _parse(self, plan: Mapping[str, Any] | str) -> FaultPlan:
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except json.JSONDecodeError as exc:
                raise LinkError(f"plan is not valid JSON: {exc}") from None
        parsed = FaultPlan.from_dict(plan)
        if parsed.base != "random":
            raise LinkError('plans must set "base": "random"')
        check_plan_bounds(parsed, self.system.profile, self.system.until_us, self.config.max_faults)
        return parsed

    # -- log ------------------------------------------------------------------------------

    def _log(self, record: dict[str, Any]) -> None:
        if record.get("type") == "run":
            self.last_record = record
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also prevents two server processes from starting
        # independent budgets in the same log. Never truncate or reuse a log.
        mode = "x" if record.get("type") == "session" else "a"
        with self.log_path.open(mode, encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def read_log(path: Path) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records or not isinstance(records[0], dict) or records[0].get("format") != LOG_FORMAT:
        raise ValueError(f"{path}: not a {LOG_FORMAT} log")
    if records[0].get("type") != "session" or any(
        isinstance(r, dict) and r.get("type") == "session" for r in records[1:]
    ):
        raise ValueError(f"{path}: expected exactly one session header at the start")
    cfg = records[0].get("config", {})
    if not isinstance(cfg, dict) or any(type(cfg.get(k)) is not int for k in ("budget", "seed_base")):
        raise ValueError(f"{path}: invalid session configuration")
    if cfg["budget"] < 0 or len(records) - 1 > cfg["budget"]:
        raise ValueError(f"{path}: run count exceeds session budget")
    for i, r in enumerate(records[1:]):
        if (
            not isinstance(r, dict) or r.get("type") != "run"
            or type(r.get("run")) is not int or r["run"] != i
            or type(r.get("seed")) is not int or r["seed"] != cfg["seed_base"] + i
            or r.get("status") not in ("ok", "rejected") or "plan" not in r
        ):
            raise ValueError(f"{path}: invalid run record at index {i}")
    return records


def summarize_log(path: Path) -> dict[str, Any]:
    """How the session went: runs used, rejections, and the first violating run."""
    records = read_log(path)
    head, runs = records[0], [r for r in records[1:] if r.get("type") == "run"]
    first = next((r["run"] for r in runs if r.get("status") == "ok" and r.get("violated")), None)
    return {
        "config": head["config"],
        "runs": len(runs),
        "rejected": sum(1 for r in runs if r["status"] == "rejected"),
        "first_violation_run": first,
        "runs_to_first_violation": None if first is None else first + 1,
        "violated": sorted({c for r in runs for c in r.get("violated", [])}),
        "with_no_effect_entries": sum(1 for r in runs if any(r.get("no_effect", {}).values())),
    }


def _current_texts(system_name: str) -> dict[str, str]:
    system = get_system(system_name)
    paths = {"protocol": system.protocol_path, "contracts": system.contracts_path, "plan_format": PLAN_FORMAT_PATH}
    return {k: v.read_text(encoding="utf-8") for k, v in paths.items() if v is not None}


def environment_diff(path: Path) -> list[str]:
    """How the current environment differs from the one a log recorded, one line per difference.

    Separate from :func:`verify_log`: a replay can still match on a newer harness, and a
    mismatching replay is easier to diagnose when the environment differences are known.
    """
    head = read_log(path)[0]
    system = get_system(head["config"].get("system", "lift.v0"))
    texts = _current_texts(system.name)
    now: dict[str, tuple[Any, Any]] = {
        "harness version": (head.get("harness", {}).get("version"), harness_version()["version"]),
        "harness git": (head.get("harness", {}).get("git"), harness_version()["git"]),
        "python": (head.get("python"), platform.python_version()),
        "until_us": (head.get("until_us"), system.until_us),
    }
    for name, text in texts.items():
        now[f"{name} sha256"] = (head.get("hashes", {}).get(name), _sha(text))

    def show(v: Any) -> str:
        if v is None:
            return "not recorded"
        return v[:12] if isinstance(v, str) and len(v) >= 40 else str(v)

    return [f"{name}: log {show(was)}, now {show(cur)}" for name, (was, cur) in now.items() if was != cur]


def verify_log(path: Path) -> list[int]:
    """Rerun every accepted plan of a log; return the run numbers that came out different."""
    records = read_log(path)
    cfg = SessionConfig(**{**records[0]["config"], "mutants": tuple(records[0]["config"]["mutants"])})
    session = Session(cfg)
    bad = []
    for r in records[1:]:
        if r.get("type") != "run":
            continue
        session.run_plan(r["plan"])
        got = session.last_record or {}
        same = got.get("status") == r["status"] and got.get("seed") == r["seed"]
        if same and r["status"] == "ok":
            same = got.get("digest") == r["digest"] and got.get("violated") == r["violated"]
        if not same:
            bad.append(r["run"])
    return bad
