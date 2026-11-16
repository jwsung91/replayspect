"""claim check: whether a candidate contract deserves a person's time (docs/claims.md).

A **candidate** is a contract in the existing language, with ``grade`` and ``source``. It is judged on
**incidents** (trace files or device logs where something went wrong) and on a **normal corpus** (trace
files, device logs, or simulator seeds of the system's implementation with no defect). No model runs
here: the device model's result is read, when given, from a ``replayspect device --out`` report.

Per candidate:
- **on each incident:** its status; if violated, the first violation's request and time, every
  violation, and whether that request is the device model's first mismatch ("not given" without a
  model result);
- **on the normal corpus:** in how many inputs it was exercised, and every violation;
- **verdict:** ``passes`` (violated on every incident, exercised on the normal corpus, no violation
  there), ``fails`` (with the reasons) or ``untested`` (never exercised on the normal corpus: it could
  not have failed there, which is not the same as holding).

With no incident, only the normal corpus is judged (a false-positive check); each result then says
so (``no_incident``, and "no incident: normal corpus only" on its verdict line).

"Exercised" means a status that judged something: violated, ok, or no violation in the slice or in the
keys judged. For ``never_after`` it means more (an ``event`` anywhere would be too weak): a key that has
an ``after`` and something later with the same key by the actor of the ``event`` pattern. A wider count
is reported beside it: anything later with the same key, any actor, any kind.

Same inputs, same bytes: inputs are named as given and read in order, a directory in name order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

from replayspect.contract import ContractSet, judge_report, load_contracts
from replayspect.contract.spec import Contract
from replayspect.devicelog import Completeness, needs_complete, read_device_log
from replayspect.rewind import IN_JUDGED_KEYS, IN_JUDGED_KEYS_IN_SLICE, IN_SLICE, contract_status, fmt_t, judge_setup
from replayspect.trace import Event
from replayspect.tracefile import core_trace, file_sha256, read_trace_file

EXERCISED = ("violated", "ok", IN_SLICE, IN_JUDGED_KEYS, IN_JUDGED_KEYS_IN_SLICE)
TEXT_VIOLATIONS = 20  # normal-corpus violations listed in the text output; all are in the JSON


class ClaimError(ValueError):
    """Bad input to claim check."""


@dataclass
class Input:
    """One trace file, device log or simulator run, ready to judge."""

    name: str  # as given, or "<system> seed <n>"
    kind: str  # "trace", "device log" or "simulator"
    events: list[Event]
    end_us: int
    end_why: str
    cut_start_us: int | None = None
    sha256: str | None = None
    device_kinds: frozenset[str] | None = None  # device logs: the kinds declared complete
    invalid: bool = False
    model: dict[str, Any] | None = None  # incidents: {"path", "sha256", "first_req_id" | "status"}


def _is_trace(path: Path) -> bool:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                return line.lstrip().startswith("{")
    return True


def read_input(path: Path, complete: Completeness) -> Input:
    """A trace file (JSON lines) or a device log (anything else)."""
    sha = file_sha256(path)
    if _is_trace(path):
        tf = read_trace_file(path)
        if tf.header is not None:  # the end time and cut start from the header, not the contracts it names
            tf = replace(tf, header=replace(tf.header, contracts=None))
        js = judge_setup(tf, None, None)
        events = list(tf.trace.events)
        end = js.end_us if js.end_us is not None else (events[-1].t_us if events else 0)
        return Input(str(path), "trace", events, end, js.end_why or "last event", js.cut_start_us, sha)
    log = read_device_log(path.read_text(encoding="utf-8"))
    return Input(str(path), "device log", list(log.events), log.end_us, "end of the device log", None, sha,
                 frozenset(complete.device), not log.valid)


def sim_input(system, seed: int) -> Input:
    trace = system.run(seed, None, (), system.until_us)
    return Input(f"{system.name} seed {seed}", "simulator", list(trace.events), system.until_us, "until_us")


def read_model_result(path: Path) -> dict[str, Any]:
    """The correct model's row of a ``replayspect device --out`` report."""
    try:
        rep = json.loads(path.read_text(encoding="utf-8"))
        row = rep["models"][0]
        first = row["first"]
        status = row["status"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ClaimError(f"{path}: not a 'replayspect device --out' report ({exc})") from None
    if row.get("model") != "correct":
        raise ClaimError(f"{path}: its first model is {row.get('model')!r}, not the correct one")
    out: dict[str, Any] = {"path": str(path), "sha256": file_sha256(path)}
    if first is not None:
        out["first_req_id"] = first["req_id"]
    else:
        out["status"] = status
    return out


def _input_ref(inp: Input) -> dict[str, Any]:
    return {"path": inp.name, "kind": inp.kind, "sha256": inp.sha256}


# -- judging one candidate on one input ---------------------------------------------------------------


def judge_one(c: Contract, cs: ContractSet, inp: Input) -> dict[str, Any]:
    """Status, every violation and, for never_after, the keys tried."""
    one = ContractSet(cs.protocol, cs.transitions, (c,))
    if inp.invalid:
        return {"status": "not judged", "why_not_judged": "invalid log (an error line)", "violations": []}
    if inp.device_kinds is not None:
        missing = needs_complete(c, inp.device_kinds)
        if missing:
            return {"status": "not judged", "needs_complete": missing, "violations": []}
    st = contract_status(inp.events, one, inp.end_us, inp.end_why, inp.cut_start_us)
    status = st.to_dict()[c.id]
    out: dict[str, Any] = {"status": status, "violations": []}
    unjudged = set(st.keys_not_judged.get(c.id, ()))
    if status == "violated":
        found, _ = judge_report(core_trace(inp.events), one, inp.end_us)
        out["violations"] = [{"req_id": v.req_id, "t_us": inp.events[v.seq].t_us if v.seq < len(inp.events)
                              else inp.end_us, "detail": v.detail} for v in found]
    if c.kind == "never_after" and status != "not judged":
        out["tried"] = tried_keys(c, inp.events, unjudged)
    return out


def tried_keys(c: Contract, events: Sequence[Event], unjudged: set) -> dict[str, int]:
    """Keys with an ``after`` and anything later with the same key; and, narrower, something later by the
    ``event`` pattern's actor. Keys not judged are left out."""
    after, actor = c.params["after"], c.params["event"].actor
    first_after: dict[str | None, int] = {}
    for i, e in enumerate(events):
        if e.req_id not in first_after and e.req_id not in unjudged and after.matches(e):
            first_after[e.req_id] = i
    anything, by_actor = set(), set()
    for i, e in enumerate(events):
        k = e.req_id
        if k in first_after and i > first_after[k]:
            anything.add(k)
            if e.actor == actor:
                by_actor.add(k)
    return {"keys_with_after": len(first_after), "after_then_anything": len(anything),
            "after_then_event_actor": len(by_actor)}


def _exercised(r: dict[str, Any]) -> bool:
    if r["status"] not in EXERCISED:
        return False
    return r["status"] == "violated" or "tried" not in r or r["tried"]["after_then_event_actor"] > 0


# -- the check ----------------------------------------------------------------------------------------


def _files(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += sorted((q for q in p.iterdir() if q.is_file() and not q.name.startswith(".")),
                          key=lambda q: q.name)
        else:
            out.append(p)
    return out


def check_claims(candidates: Path, incidents: Sequence[tuple[Path, Path | None]], normal: Sequence[Path],
                 seeds: Iterable[int], system, complete: Sequence[str] = ()) -> dict[str, Any]:
    """The report (module doc). ``incidents``: (path, model result or None); ``normal``: files or directories;
    ``seeds``: simulator seeds of ``system``'s implementation with no defect."""
    cs = load_contracts(Path(candidates))
    if cs.protocol and cs.protocol != system.name:
        raise ClaimError(f"{candidates} is for {cs.protocol}, not {system.name}")
    bare = [c.id for c in cs.contracts if c.grade is None or c.source is None]
    if bare:
        raise ClaimError(f"{', '.join(bare)}: a candidate needs grade and source")
    seeds = list(seeds)
    files = _files([Path(p) for p in normal])
    if not files and not seeds:
        raise ClaimError("give a normal corpus (--normal, --normal-seeds)")
    comp = Completeness.parse(list(complete))

    incs = []
    for path, model in incidents:
        inp = read_input(Path(path), comp)
        inp.model = read_model_result(Path(model)) if model is not None else None
        incs.append(inp)
    norm_files = [read_input(p, comp) for p in files]
    listing = "".join(f"{i.sha256}  {i.name}\n" for i in norm_files)

    results = []
    per_candidate_normal = {c.id: [] for c in cs.contracts}
    for inp in norm_files:
        for c in cs.contracts:
            per_candidate_normal[c.id].append((inp.name, judge_one(c, cs, inp)))
    for seed in seeds:  # one run at a time: a thousand traces are not held at once
        inp = sim_input(system, seed)
        for c in cs.contracts:
            per_candidate_normal[c.id].append((inp.name, judge_one(c, cs, inp)))

    for c in cs.contracts:
        inc_rows = [_incident_row(c, cs, inp) for inp in incs]
        normal_rows = per_candidate_normal[c.id]
        results.append(_result(c, inc_rows, normal_rows))
    return {
        "tool": "replayspect claim check",
        "system": system.name,
        "candidates": {"path": str(candidates), "sha256": file_sha256(candidates)},
        "complete": sorted(f"device {k}" for k in comp.device),
        "incidents": [{"path": i.name, "kind": i.kind, "sha256": i.sha256,
                       "model_result": ({"path": i.model["path"], "sha256": i.model["sha256"]}
                                        if i.model is not None else "not given")} for i in incs],
        "normal": {
            "files": [{"path": i.name, "kind": i.kind, "sha256": i.sha256} for i in norm_files],
            "files_sha256": hashlib.sha256(listing.encode()).hexdigest(),
            "seeds": ({"system": system.name, "first": seeds[0], "last": seeds[-1], "implementation": "correct"}
                      if seeds else None),
            "inputs": len(norm_files) + len(seeds),
        },
        "results": results,
    }


def _incident_row(c: Contract, cs: ContractSet, inp: Input) -> dict[str, Any]:
    r = judge_one(c, cs, inp)
    first = r["violations"][0] if r["violations"] else None
    row = {"input": inp.name, **r, "first_violation": first}
    m = inp.model
    if m is None:
        row["model_first_mismatch"] = "not given"
    elif "first_req_id" in m:
        row["model_first_mismatch"] = m["first_req_id"]
    else:
        row["model_first_mismatch"] = f"model {m['status']}"  # conforms, not checked
    if r["status"] != "violated":
        row["same_request"] = "not violated"
    elif m is None:
        row["same_request"] = "not given"
    elif "first_req_id" in m:
        row["same_request"] = "yes" if first["req_id"] == m["first_req_id"] else "no"
    else:
        row["same_request"] = row["model_first_mismatch"]
    return row


def _result(c: Contract, inc_rows: list[dict[str, Any]], normal_rows: list[tuple[str, dict[str, Any]]]):
    statuses: dict[str, int] = {}
    for _, r in normal_rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    violations = [{"input": name, **v} for name, r in normal_rows for v in r["violations"]]
    violated_inputs = len({v["input"] for v in violations})
    exercised = sum(_exercised(r) for _, r in normal_rows)
    n = len(normal_rows)
    normal: dict[str, Any] = {
        "inputs": n, "exercised": exercised, "statuses": dict(sorted(statuses.items())),
        "not_judged": [name for name, r in normal_rows if r["status"] == "not judged"],
        "violations": violations,
    }
    if c.kind == "never_after":
        tried = {"keys_with_after": 0, "after_then_anything": 0, "after_then_event_actor": 0}
        for _, r in normal_rows:
            for k in tried:
                tried[k] += r.get("tried", {}).get(k, 0)
        normal["tried"] = {**tried, "event_actor": c.params["event"].actor, "measure": "after_then_event_actor",
                           **{f"inputs_{k}": sum(r.get("tried", {}).get(k, 0) > 0 for _, r in normal_rows)
                              for k in ("after_then_anything", "after_then_event_actor")}}
    reasons = [f"not caught on incident {r['input']} ({r['status']})" for r in inc_rows if r["status"] != "violated"]
    if violated_inputs:
        reasons.append(f"violated on {violated_inputs} of {n} normal inputs")
    if reasons:
        verdict = "fails"
    elif exercised == 0:
        verdict, reasons = "untested", [_untested_reason(normal_rows)]
    else:
        verdict = "passes"
    return {"id": c.id, "kind": c.kind, "desc": c.desc, "grade": c.grade, "source": dict(c.source or {}),
            "verdict": verdict, "no_incident": not inc_rows, "reasons": reasons, "incidents": inc_rows,
            "normal": normal}


def _untested_reason(normal_rows: list[tuple[str, dict[str, Any]]]) -> str:
    n = len(normal_rows)
    unjudged = [r for _, r in normal_rows if r["status"] == "not judged"]
    if unjudged and len(unjudged) == n:  # the remedy is a declaration or other inputs, not more of the same
        why = sorted({x for r in unjudged for x in r.get("needs_complete", ())})
        bad = any("why_not_judged" in r for r in unjudged)
        detail = "; ".join(([f"needs {', '.join(why)} declared complete"] if why else [])
                           + (["invalid logs"] if bad else []))
        return f"not judged on any of the {n} normal inputs" + (f" ({detail})" if detail else "")
    if unjudged:
        return f"never exercised on the normal corpus ({n} inputs, {len(unjudged)} of them not judged)"
    return f"never exercised on the normal corpus ({n} inputs)"


# -- text -----------------------------------------------------------------------------------------------


def report_lines(rep: dict[str, Any]) -> list[str]:
    nrm = rep["normal"]
    seeds = nrm["seeds"]
    lines = [f"claim check: {len(rep['results'])} candidate(s), {len(rep['incidents'])} incident(s), "
             f"normal corpus {nrm['inputs']} input(s) ({len(nrm['files'])} file(s)"
             + (f", seeds {seeds['first']}-{seeds['last']} of {seeds['system']}, implementation with no defect"
                if seeds else "") + ")",
             f"candidates: {rep['candidates']['path']} sha256 {rep['candidates']['sha256']}"]
    if rep["complete"]:
        lines.append(f"device logs declared complete for: {', '.join(rep['complete'])}")
    for n, inc in enumerate(rep["incidents"], 1):
        lines.append(f"incident {n}: {inc['path']} ({inc['kind']}) sha256 {inc['sha256']}")
        m = inc["model_result"]
        lines.append("  model result: " + (m if isinstance(m, str) else f"{m['path']} sha256 {m['sha256']}"))
    if nrm["files"]:
        lines.append(f"normal files: {len(nrm['files'])}, sha256 of the list (sha256, two spaces, path; one per "
                     f"line) {nrm['files_sha256']}")
    for r in rep["results"]:
        lines.append("")
        reasons = f": {'; '.join(r['reasons'])}" if r["reasons"] else ""
        scope = " (no incident: normal corpus only)" if r["no_incident"] else ""
        lines.append(f"{r['id']} ({r['kind']}): {r['verdict']}{scope}{reasons}")
        for n, inc in enumerate(r["incidents"], 1):
            fv = inc["first_violation"]
            if fv is None:
                why = (f", needs {', '.join(inc['needs_complete'])} declared complete" if "needs_complete" in inc
                       else f", {inc['why_not_judged']}" if "why_not_judged" in inc else "")
                lines.append(f"  incident {n}: {inc['status']}{why}")
            else:
                lines.append(f"  incident {n}: violated at t={fmt_t(fv['t_us'])} {fv['req_id'] or '-'}: {fv['detail']}"
                             + (f" ({len(inc['violations'])} violations)" if len(inc["violations"]) > 1 else ""))
            if inc["status"] == "violated":
                lines.append(f"    the model's first mismatch: {inc['model_first_mismatch']}; "
                             f"same request as the model's first mismatch: {inc['same_request']}")
        rn = r["normal"]
        lines.append(f"  normal: exercised in {rn['exercised']} of {rn['inputs']}; "
                     + ", ".join(f"{k} {v}" for k, v in rn["statuses"].items()))
        if "tried" in rn:
            t = rn["tried"]
            lines.append(f"    never_after: keys with an after {t['keys_with_after']}, of which with something later "
                         f"by {t['event_actor']} {t['after_then_event_actor']} in {t['inputs_after_then_event_actor']} "
                         f"input(s) (the measure used), with anything later {t['after_then_anything']} in "
                         f"{t['inputs_after_then_anything']}")
        vs = rn["violations"]
        if vs:
            lines.append(f"    violations: {len(vs)} in {len({v['input'] for v in vs})} input(s)")
            for v in vs[:TEXT_VIOLATIONS]:
                lines.append(f"      {v['input']} t={fmt_t(v['t_us'])} {v['req_id'] or '-'}: {v['detail']}")
            if len(vs) > TEXT_VIOLATIONS:
                lines.append(f"      ... {len(vs) - TEXT_VIOLATIONS} more (all in --out)")
    return lines


def to_json(rep: dict[str, Any]) -> str:
    return json.dumps(rep, indent=2, sort_keys=True) + "\n"
