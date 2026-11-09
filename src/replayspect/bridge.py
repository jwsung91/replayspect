"""Bridge sessions (WP4): reproduce a hidden incident from a partial log, then name its cause.

A planner (a model behind MCP, or a baseline) gets one participant's log of a
hidden failing run (:mod:`replayspect.incident`) and the usual public
documents. It submits fault plans; every run uses the **incident's seed**, so
the log fixes the environment and only the faults are unknown. Each run is
checked against the incident with :func:`~replayspect.incident.wp4_match`.
Once a run reproduces the incident, the planner can name one entry of its
plan as the cause: the engine reruns the plan without that entry and the
cause is **confirmed** when none of the contracts the incident violated is
violated any more. The question that counts is the **defect**: with a
published defect list (condition A) the planner names one id with
``name_defect``; without one (condition B) it describes the faulty behaviour
with ``describe_defect``. One answer, recorded and not judged here.

Modes (:data:`MODES`):

* ``full``: log, symptom, runs, cause checks, defect answer.
* ``answer_only``: log, symptom and a reproducing plan given by the operator
  (e.g. the rule-based reader's) with the logged side of its run; defect
  answer only. Measures "reproduce deterministically, infer the defect with
  a model".
* ``symptom_only``: the symptom and no log; defect answer only. The chance
  level of the defect answer.

Rules enforced here, as in :mod:`replayspect.session`:

* **Budget.** ``run_plan`` and ``check_cause`` each use one run, rejected
  calls included. When the budget is used up, calls are refused without
  counting.
* **End.** The session ends at the defect answer or at ``finish``. A used-up
  budget refuses further runs and cause checks but leaves the defect answer
  open. Calls after the end are refused without counting.
* **Own runs.** ``run_plan`` shows only the logged participant's side of the
  planner's run (:func:`~replayspect.incident.run_view`: the run's own link
  data kept) and the contracts it violated, without their details.
* **Hidden.** Seed, plan, mutants or variant, the incident's contracts and
  digest, the clock offset and every path stay out of what the planner gets.
* **Log.** Every call is appended to a JSON Lines log opened by exclusive
  creation; :func:`verify_log` reruns it. Keep it away from the planner.

All results are *explored*: a confirmed cause is confirmed in the model, not
as the cause of a real incident.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from replayspect.incident import (
    DIAGNOSTIC_TOLERANCES_US,
    Incident,
    Match,
    read_incident,
    defect_class,
    run_incident,
    run_view,
    view_text,
    wp4_match,
)
from replayspect.runner import get_system, harness_version, run_once, summary_line
from replayspect.session import PLAN_FORMAT_PATH
from replayspect.sim.link import Disconnect, FaultPlan, LinkError, check_plan_bounds
from replayspect.tracefile import canonical

LOG_FORMAT = "replayspect.bridge/1"
SECTIONS = ("delays", "faults", "disconnects")

MODES = ("full", "answer_only", "symptom_only")
#: Longest accepted describe_defect answer.
MAX_DESCRIPTION = 2000
QUESTION = {
    "name": "which defect in the implementation caused the failure: call name_defect with one id from the "
            "defect list. One answer.",
    "describe": "what defect in the implementation caused the failure: call describe_defect with a short "
                "description of the faulty behaviour. One answer.",
}
TASKS = {
    "full": (
        "A failing run of this system was recorded. You get one participant's log of it and a one-line symptom "
        "report. Find a fault plan that reproduces the log: run_plan reports whether your run matches the log "
        "line by line, and shows you only the logged participant's side of your run. Every run uses the same "
        "environment as the recorded one, so only the faults you choose differ. Then answer {question} Your "
        "answer ends the session. You may name the plan entry you think triggered the failure with check_cause: "
        "the run is repeated without that entry, and it is confirmed if the failure goes away. The session ends "
        "at your answer or when you call finish; when the budget runs out you can still answer."
    ),
    "answer_only": (
        "A failing run of this system was recorded. You get one participant's log of it, a one-line symptom "
        "report, and a fault plan that reproduces the log, with the logged participant's side of that run. "
        "Answer {question} Your answer ends the session."
    ),
    "symptom_only": (
        "A failing run of this system was reported with the one-line symptom below. There is no log. "
        "Answer {question} Your answer ends the session."
    ),
}
VIEW_NOTES = {
    0: "The log is {actor}-side only; its clock is the simulator's.",
    1: "The log is {actor}-side only; its clock is off from the simulator's by an unknown constant.",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry(entry: str) -> tuple[str, int]:
    """``"faults[2]"`` -> ("faults", 2)."""
    name, _, rest = entry.partition("[")
    if name not in SECTIONS or not rest.endswith("]") or not rest[:-1].isdigit():
        raise LinkError(f"entry must look like faults[0], delays[1] or disconnects[0], got {entry!r}")
    return name, int(rest[:-1])


def without_entry(plan: Mapping[str, Any], entry: str) -> dict[str, Any]:
    """The plan as submitted, minus one entry."""
    name, i = _entry(entry)
    items = list(plan.get(name, []))
    if i >= len(items):
        raise LinkError(f"{entry}: the plan has {len(items)} {name}")
    return {**plan, name: items[:i] + items[i + 1:]}


def plan_entries(plan: Mapping[str, Any]) -> list[str]:
    return [f"{s}[{i}]" for s in SECTIONS for i in range(len(plan.get(s, [])))]


@dataclass(frozen=True)
class BridgeConfig:
    incident: str  # path of the incident file
    budget: int = 120
    max_faults: int = 20
    mode: str = "full"
    #: answer_only: the reproducing plan given to the planner.
    given_plan: Mapping[str, Any] | None = None

    @classmethod
    def from_log(cls, cfg: Mapping[str, Any]) -> "BridgeConfig":
        return cls(cfg["incident"], cfg["budget"], cfg["max_faults"], cfg.get("mode", "full"), cfg.get("given_plan"))


class BridgeSession:
    def __init__(self, config: BridgeConfig, log_path: Path | None = None) -> None:
        self.config, self.log_path = config, log_path
        if config.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {config.mode!r}")
        if (config.mode == "answer_only") != (config.given_plan is not None):
            raise ValueError("a given plan goes with mode answer_only, and only with it")
        self.incident: Incident = read_incident(config.incident)
        self.system = self.incident.system_obj()
        if self.system.protocol_path is None:
            raise ValueError(f"system {self.system.name} has no protocol description for planners")
        if config.mode != "full" and self.incident.symptom is None:
            raise ValueError(f"mode {config.mode} needs an incident with a symptom")
        published = get_system(self.incident.system).published_defects
        self.defects: dict[str, str] = dict(published) if published and self.incident.variant is None else {}
        self.question = "name" if self.defects else "describe"
        self.hidden = run_incident(self.incident, self.system)
        if self.incident.expect and self.hidden.trace.digest() != self.incident.expect.get("digest"):
            raise ValueError("the incident's hidden run no longer has its recorded digest")
        self.used = 0
        self.ended: str | None = None
        self.runs: dict[int, dict[str, Any]] = {}  # run index -> {"plan": dict, "reproduced": bool}
        self.last_record: dict[str, Any] | None = None
        self.last_run = None  # the Run of the last accepted run_plan (baselines read its own view)
        self.given: dict[str, Any] | None = None
        if config.given_plan is not None:
            raw, parsed = self._parse(config.given_plan)
            run = self._run(parsed)
            m = wp4_match(self.incident, self.hidden, run, self.system)
            if not m.reproduced:
                raise ValueError("the given plan does not reproduce the incident")
            self.given = {"plan": raw, **self._own_report(run, m)}
        self._texts = {
            "protocol": self.system.protocol_path.read_text(encoding="utf-8"),
            "contracts": self.system.contracts_path.read_text(encoding="utf-8"),
            "plan_format": PLAN_FORMAT_PATH.read_text(encoding="utf-8"),
            "log": view_text(self.incident, self.hidden),
        }
        if self.incident.symptom is not None:
            self._texts["symptom"] = self.incident.symptom
        head: dict[str, Any] = {
            "type": "session", "format": LOG_FORMAT, "config": {**vars_of(config)}, "question": self.question,
            "incident_sha256": hashlib.sha256(Path(config.incident).read_bytes()).hexdigest(),
            "hashes": {**{k: _sha(v) for k, v in self._texts.items()}, "describe": self.describe_sha256()},
            "harness": harness_version(), "python": platform.python_version(),
        }
        if self.system.variant is not None:
            head["variant"] = self.system.variant.to_dict()
        self._log(head)

    # -- what the planner sees -------------------------------------------------------------

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

    def _describe(self, budget: dict[str, int]) -> dict[str, Any]:
        mode = self.config.mode
        d: dict[str, Any] = {"system": self.system.name,
                             "task": TASKS[mode].format(question=QUESTION[self.question])}
        if self.incident.symptom is not None:
            d["symptom"] = self.incident.symptom
        if mode != "symptom_only":
            d["log_note"] = VIEW_NOTES[1 if self.incident.clock_offset_us else 0].format(actor=self.incident.actor)
            d["log"] = self._texts["log"]
        d["protocol"] = self._texts["protocol"]
        d["contracts"] = self._texts["contracts"]
        if self.defects:
            d["defects"] = dict(self.defects)
        if mode != "symptom_only":
            d["plan_format"] = self._texts["plan_format"]
        if mode == "full":
            d["limits"] = self.limits()
            d["budget"] = budget
        if mode == "answer_only":
            d["reproducing_plan"] = self.given["plan"]
            d["reproducing_run"] = {k: v for k, v in self.given.items() if k != "plan"}
        return d

    def describe(self) -> dict[str, Any]:
        """Everything a planner gets, and nothing about the hidden run."""
        return self._describe(self.budget())

    def describe_sha256(self) -> str:
        """Digest of the describe text with a fresh budget (for pre-registration)."""
        return _sha(canonical(self._describe({"total": self.config.budget, "used": 0,
                                              "left": self.config.budget})))

    # -- calls ---------------------------------------------------------------------------------

    def _refuse(self) -> dict[str, Any] | None:
        if self.ended is not None:
            return {"status": "session_ended", "reason": self.ended, "budget": self.budget()}
        if self.config.mode != "full":
            return {"status": "not_available", "error": f"no runs in mode {self.config.mode}"}
        if self.used >= self.config.budget:
            return {"status": "budget_exhausted", "budget": self.budget()}
        return None

    def can_run(self) -> bool:
        """Runs are still accepted (baseline loops stop when this turns false)."""
        return self.ended is None and self.config.mode == "full" and self.used < self.config.budget

    def own_timeline(self, run) -> list[str]:
        """The logged participant's side of a planner's run, polls left out, in the run's clock."""
        lines = []
        for ev in run_view(run.trace, self.incident.actor):
            if ev.name in self.system.quiet_messages:
                continue
            link = ev.data.get("link", {})
            line = summary_line(ev)
            if ev.kind == "recv" and "sent_us" in link:
                line += f" sent={link['sent_us'] / 1e6:.3f}s delay={link['delay_us'] / 1e6:.3f}s"
            lines.append(line)
        return lines

    def _own_report(self, run, m: Match) -> dict[str, Any]:
        return {
            "reproduction": m.for_planner(self.incident.clock_offset_us),
            "violations": [{"contract": v.contract, "req_id": v.req_id,
                            "at_s": round(run.trace[v.seq].t_us / 1e6, 3) if v.seq < len(run.trace) else None}
                           for v in run.first()],
            "timeline": self.own_timeline(run),
        }

    def _parse(self, plan: Mapping[str, Any] | str) -> tuple[dict[str, Any], FaultPlan]:
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except json.JSONDecodeError as exc:
                raise LinkError(f"plan is not valid JSON: {exc}") from None
        parsed = FaultPlan.from_dict(plan)
        if parsed.base != "random":
            raise LinkError('plans must set "base": "random"')
        check_plan_bounds(parsed, self.system.profile, self.system.until_us, self.config.max_faults)
        return dict(plan), parsed

    def _run(self, parsed: FaultPlan):
        inc = self.incident
        return run_once(self.system, inc.seed, inc.mutants if self.system.variant is None else (), parsed, None,
                        inc.until_us)

    def run_plan(self, plan: Mapping[str, Any] | str) -> dict[str, Any]:
        """Run one plan in the incident's environment and compare it with the log."""
        refused = self._refuse()
        if refused:
            return refused
        idx = self.used
        self.used += 1
        record: dict[str, Any] = {"type": "run", "run": idx, "plan": plan}
        try:
            raw, parsed = self._parse(plan)
        except LinkError as exc:
            record.update(status="rejected", error=str(exc))
            self._log(record)
            return {"status": "rejected", "run": idx, "error": str(exc), "budget": self._after()}
        run = self._run(parsed)
        m = wp4_match(self.incident, self.hidden, run, self.system)
        self.last_run = run
        self.runs[idx] = {"plan": raw, "reproduced": m.reproduced}
        report = run.plan_report.to_dict() if run.plan_report else {}
        record.update(status="ok", violated=sorted(run.violated()), digest=run.trace.digest(),
                      no_effect={k: len(v) for k, v in report.items()}, match=match_record(m))
        self._log(record)
        own = self._own_report(run, m)
        return {
            "status": "ok", "run": idx,
            "reproduction": own["reproduction"],
            "violations": own["violations"],
            "no_effect": report,
            "timeline": own["timeline"],
            "budget": self._after(),
        }

    def check_cause(self, run: int, entry: str) -> dict[str, Any]:
        """Rerun a reproducing run's plan without one entry; confirmed if the failure goes away."""
        refused = self._refuse()
        if refused:
            return refused
        idx = self.used
        self.used += 1
        record: dict[str, Any] = {"type": "cause", "run": idx, "of_run": run, "entry": entry}
        try:
            if type(run) is not int or run not in self.runs:
                raise LinkError(f"run {run!r} is not an accepted run of this session")
            if not self.runs[run]["reproduced"]:
                raise LinkError(f"run {run} did not reproduce the log; name a cause only in a reproducing run")
            raw = without_entry(self.runs[run]["plan"], entry)
            _, parsed = self._parse(raw)
        except LinkError as exc:
            record.update(status="rejected", error=str(exc))
            self._log(record)
            return {"status": "rejected", "run": idx, "error": str(exc), "budget": self._after()}
        cf = self._run(parsed)
        confirmed = not (self.hidden.violated() & cf.violated())
        record.update(status="ok", confirmed=confirmed, violated=sorted(cf.violated()), digest=cf.trace.digest())
        self._log(record)
        return {"status": "ok", "run": idx, "confirmed": confirmed,
                "violations": sorted(cf.violated()), "budget": self._after()}

    def _answer(self, question: str, answer: str) -> dict[str, Any]:
        if self.ended is not None:
            return {"status": "session_ended", "reason": self.ended, "budget": self.budget()}
        if question != self.question:
            other = "name_defect" if self.question == "name" else "describe_defect"
            return {"status": "rejected", "error": f"this session asks for {other}"}
        self.ended = "defect answered"
        self._log({"type": "defect", "question": question, "answer": answer, "after_runs": self.used})
        return {"status": "ok", "recorded": answer, "session": "ended"}

    def name_defect(self, defect_id: str) -> dict[str, Any]:
        """Condition A: the answer is one id from the published defect list. Ends the session."""
        if self.question == "name" and self.ended is None and defect_id not in self.defects:
            return {"status": "rejected", "error": f"not an id from the defect list: {defect_id!r}"}
        return self._answer("name", defect_id)

    def describe_defect(self, text: str) -> dict[str, Any]:
        """Condition B: the answer is a short description of the faulty behaviour. Ends the session."""
        if self.question == "describe" and self.ended is None:
            if not isinstance(text, str) or not text.strip():
                return {"status": "rejected", "error": "the description is empty"}
            if len(text) > MAX_DESCRIPTION:
                return {"status": "rejected", "error": f"keep the description under {MAX_DESCRIPTION} characters"}
        return self._answer("describe", text.strip() if isinstance(text, str) else text)

    def finish(self, note: str = "") -> dict[str, Any]:
        """End the session. Does not use the budget."""
        if self.ended is None:
            self.ended = "finished by the planner"
            self._log({"type": "finish", "after_runs": self.used, "note": note})
        return {"status": "session_ended", "reason": self.ended, "budget": self.budget()}

    def _after(self) -> dict[str, int]:
        return self.budget()

    def _log(self, record: dict[str, Any]) -> None:
        if record.get("type") in ("run", "cause"):
            self.last_record = record
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "x" if record.get("type") == "session" else "a"
        with self.log_path.open(mode, encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def vars_of(config: BridgeConfig) -> dict[str, Any]:
    d = {"incident": config.incident, "budget": config.budget, "max_faults": config.max_faults, "mode": config.mode}
    if config.given_plan is not None:
        d["given_plan"] = dict(config.given_plan)
    return d


def match_record(m: Match) -> dict[str, Any]:
    return {"reproduced": m.reproduced, "matched": m.matched, "total": m.total, "lines_same": m.lines_same,
            "max_dt_us": m.max_dt_us, "status_same": m.status_same, "contracts_same": m.contracts_same,
            "within": {str(k): v for k, v in m.within.items()}, "digest_same": m.digest_same}


# -- logs -----------------------------------------------------------------------------------


def read_log(path: Path) -> list[dict[str, Any]]:
    records = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    if not records or records[0].get("type") != "session" or records[0].get("format") != LOG_FORMAT:
        raise ValueError(f"{path}: not a {LOG_FORMAT} log")
    return records


def verify_log(path: Path) -> list[int]:
    """Rerun every call of a log; return the run numbers that came out different."""
    records = read_log(path)
    s = BridgeSession(BridgeConfig.from_log(records[0]["config"]))
    bad = []
    for r in records[1:]:
        if r["type"] == "run":
            s.run_plan(r["plan"])
        elif r["type"] == "cause":
            s.check_cause(r["of_run"], r["entry"])
        elif r["type"] == "defect":
            (s.name_defect if r["question"] == "name" else s.describe_defect)(r["answer"])
            continue
        else:
            s.finish(r.get("note", ""))
            continue
        got = s.last_record or {}
        keys = ("status", "violated", "digest", "confirmed", "match")
        if any(got.get(k) != r.get(k) for k in keys):
            bad.append(r["run"])
    return bad


def _same_fault(inc: Incident, section: str, item: Mapping[str, Any]) -> bool:
    """Operator-only: does a nominated entry name a fault the hidden plan has?"""
    if section == "disconnects":
        a0, a1 = item["t_us"], item["t_us"] + item["duration_us"]
        return any(a0 < d.t_us + d.duration_us and d.t_us < a1 for d in inc.plan.disconnects)
    key = (item["dir"], item["msg"], item.get("req_id"), item["k"])
    if section == "delays":
        return any((d.key.dir, d.key.msg, d.key.req_id, d.key.k) == key for d in inc.plan.delays)
    drop = bool(item.get("drop", False))
    return any((f.key.dir, f.key.msg, f.key.req_id, f.key.k) == key and f.drop == drop for f in inc.plan.faults)


def necessary_entries(session: BridgeSession, plan: Mapping[str, Any]) -> list[str]:
    """Entries of a reproducing plan whose removal makes every incident contract hold (the candidates)."""
    out = []
    for e in plan_entries(plan):
        cf = session._run(FaultPlan.from_dict(without_entry(plan, e)))
        if not (session.hidden.violated() & cf.violated()):
            out.append(e)
    return out


def summarize_log(path: Path) -> dict[str, Any]:
    """The four WP4 metrics of one session, plus diagnostics. Operator-only (reads the incident)."""
    records = read_log(path)
    s = BridgeSession(BridgeConfig.from_log(records[0]["config"]))
    runs = [r for r in records[1:] if r["type"] == "run" and r["status"] == "ok"]
    causes = [r for r in records[1:] if r["type"] == "cause" and r["status"] == "ok"]
    first = next((r for r in runs if r["match"]["reproduced"]), None)
    plans = {r["run"]: r["plan"] for r in runs}
    candidates = necessary_entries(s, plans[first["run"]]) if first else []
    hit_hidden = []
    for c in causes:
        sec, i = _entry(c["entry"])
        plan = plans[c["of_run"]]
        plan = json.loads(plan) if isinstance(plan, str) else plan
        hit_hidden.append(_same_fault(s.incident, sec, plan[sec][i]))
    by_tol = {}
    for t in DIAGNOSTIC_TOLERANCES_US:
        hit = next((r["run"] for r in runs if r["match"]["within"][str(t)]), None)
        by_tol[t] = None if hit is None else hit + 1
    answer = next((r for r in records[1:] if r["type"] == "defect"), None)
    defect: dict[str, Any] = {"question": s.question, "answer": None if answer is None else answer["answer"]}
    if s.question == "name":
        cls = defect_class(s.incident) or []
        defect.update(equivalent=cls, chance=len(cls) / len(s.defects),
                      correct=None if answer is None else answer["answer"] in cls)
    return {
        "mode": s.config.mode,
        "defect": defect,
        "calls": len(records) - 1,
        "reproduced": first is not None,
        "runs_to_reproduction": None if first is None else first["run"] + 1,
        "candidates": len(candidates),
        "candidate_entries": candidates,
        "plan_entries": 0 if first is None else len(plan_entries(plans[first["run"]])),
        "nominations": len(causes),
        "confirmed": sum(1 for c in causes if c["confirmed"]),
        "nominated_hidden_fault": sum(hit_hidden),
        "runs_to_reproduction_by_tolerance": by_tol,
        "exact_reproduction": any(r["match"]["digest_same"] for r in runs),
        "ended": next((r.get("note") for r in records if r["type"] == "finish"), None),
    }


# -- baselines -------------------------------------------------------------------------------

#: Delays do not count against ``max_faults``; this caps them, as for Hypothesis plans.
MAX_DELAYS = 10
MAX_DISCONNECT_GAP_US = 30_000_000


def random_plan(rng: random.Random, session: BridgeSession) -> dict[str, Any]:
    """A plan drawn uniformly from the planner's plan space (the random baseline).

    The message-key distribution matches :func:`replayspect.hyp.message_keys`:
    half command traffic, half polls. Counts are uniform: faults in
    ``0..max_faults``, disconnects in what is left, delays in ``0..MAX_DELAYS``.
    """
    system, n_max = session.system, session.config.max_faults
    vocab, p = system.vocabulary, system.profile
    if vocab is None:
        raise ValueError(f"system {system.name} has no plan vocabulary")

    def key() -> dict[str, Any]:
        direction = rng.choice(["c2s", "s2c"])
        if rng.random() < 0.5:
            req_id, request = rng.choice(vocab.commands)
            msg = request if direction == "c2s" else rng.choice(vocab.command_replies)
        else:
            req_id = rng.choice(vocab.polls)
            msg = vocab.poll_request if direction == "c2s" else vocab.poll_reply
        return {"dir": direction, "msg": msg, "req_id": req_id, "k": rng.randint(0, vocab.max_k)}

    def unique(n: int, make) -> list[dict[str, Any]]:
        out, seen = [], set()
        for _ in range(n):
            x = make()
            k = (x["dir"], x["msg"], x["req_id"], x["k"])
            if k not in seen:
                seen.add(k)
                out.append(x)
        return out

    def fault() -> dict[str, Any]:
        k = key()
        if rng.random() < 0.5:
            return {**k, "drop": True}
        return {**k, "dup_extra_us": rng.randint(*getattr(p, k["dir"]).dup_extra_us)}

    def delay() -> dict[str, Any]:
        k = key()
        return {**k, "delay_us": rng.randint(*getattr(p, k["dir"]).delay_us)}

    faults = unique(rng.randint(0, n_max), fault)
    disconnects, t = [], 0
    for _ in range(rng.randint(0, n_max - len(faults))):
        t += rng.randint(1, MAX_DISCONNECT_GAP_US)
        if t >= system.until_us:
            break
        d = rng.randint(*p.disconnect_duration_us)
        disconnects.append({"t_us": t, "duration_us": d})
        t += d
    return {"base": "random", "delays": unique(rng.randint(0, MAX_DELAYS), delay), "faults": faults,
            "disconnects": disconnects}


def name_causes(session: BridgeSession, rng: random.Random, run: int) -> None:
    """Baseline cause naming: the entries of a reproducing plan in random order, until one is confirmed."""
    entries = plan_entries(session.runs[run]["plan"])
    rng.shuffle(entries)
    for e in entries:
        if not session.can_run():
            return
        if session.check_cause(run, e).get("confirmed"):
            return


def random_baseline(config: BridgeConfig, seed: int, log_path: Path | None = None) -> BridgeSession:
    """Random plans until a run reproduces, then random cause naming; same budget and end rules."""
    s = BridgeSession(config, log_path)
    rng = random.Random(f"bridge-random-{seed}")
    while s.can_run():
        out = s.run_plan(random_plan(rng, s))
        if out.get("reproduction", {}).get("reproduced"):
            name_causes(s, rng, out["run"])
    return s


def hypothesis_baseline(config: BridgeConfig, hyp_seed: int, log_path: Path | None = None) -> BridgeSession:
    """Hypothesis-written plans (:func:`replayspect.hyp.plans`) in the same loop. Needs the hyp extra."""
    from hypothesis import HealthCheck, Phase, given, settings
    from hypothesis import seed as hyp_seed_decorator

    from replayspect.hyp import no_local_constants, plans

    s = BridgeSession(config, log_path)
    rng = random.Random(f"bridge-hypothesis-{hyp_seed}")

    @hyp_seed_decorator(hyp_seed)
    @settings(max_examples=config.budget, phases=[Phase.generate], database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(plans(s.system, config.max_faults))
    def run(plan: dict[str, Any]) -> None:
        if not s.can_run():
            return
        out = s.run_plan(plan)
        if out.get("reproduction", {}).get("reproduced"):
            name_causes(s, rng, out["run"])

    with no_local_constants():
        run()
    return s


def reconstruct_baseline(config: BridgeConfig, log_path: Path | None = None, **search: Any):
    """The rule-based reconstructor (:mod:`replayspect.reconstruct`) in the same loop.

    It reads only what a planner gets: the describe log and limits, and for each
    run the reproduction verdict, lines matched and the visible participant's
    events of that run. A reproducing plan's causes are then named in seeded
    random order, as for the other baselines. If it does not reproduce, the
    session is finished with the reconstructor's status and reason as the note.
    ``search`` goes to :func:`~replayspect.reconstruct.reconstruct` (``max_edits``,
    ``max_tries``). Returns ``(session, result)``.
    """
    from replayspect.reconstruct import Feedback, Limits, reconstruct
    from replayspect.tracefile import parse_trace_file

    s = BridgeSession(config, log_path)
    d = s.describe()
    tf = parse_trace_file(d["log"], "log")
    log = tf.trace
    actor = tf.header.slice.actors[0]
    vocab = s.system.vocabulary
    if vocab is None:
        raise ValueError(f"system {s.system.name} has no plan vocabulary")
    reproducing: list[int] = []

    def oracle(plan: dict[str, Any]) -> Feedback | None:
        out = s.run_plan(plan)
        if out.get("status") != "ok":
            return None
        rep = out["reproduction"]
        if rep["reproduced"]:
            reproducing.append(out["run"])
        return Feedback(rep["reproduced"], int(rep["lines_matched"].split("/")[0]), run_view(s.last_run.trace, actor))

    result = reconstruct(log, actor, s.system.quiet_messages, (vocab.poll_request, vocab.poll_reply),
                         Limits.from_describe(d["limits"]), oracle,
                         clock_known="off from the simulator's" not in d["log_note"], **search)
    if reproducing and s.can_run():
        name_causes(s, random.Random("bridge-reconstruct"), reproducing[0])
    if s.ended is None:
        s.finish(f"reconstruct: {result.status}: {result.reason}")
    return s, result
