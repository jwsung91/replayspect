"""Command line: ``python3 -m replayspect search|replay|rewind|ingest|baseline|session|incident``.

search    Run random-fault seeds against a system, report which contracts
          failed, shrink the failures of one target contract and write the
          smallest one as a repro file.
replay    Rerun a repro file and check it reproduces the recorded execution.
          With --trace-out, also write the run's trace as a trace file
          (docs/trace-schema.md), with a header naming the system, seed,
          plan, contract file and end time.
rewind    Look at a trace file: a summary by default; the state at a virtual
          time (--at), events after or before it (--step), a time window
          (--window), one participant (--actor), the first divergence from a
          reference trace (--ref) and contract status (--contracts, or the
          header's contract file). Listings are capped; --full writes the
          whole selection to a new trace file that records how it was cut.
baseline  Random search over the same seeds a planning session uses
          (seed_base, seed_base + 1, ...): how many runs until a violation.
          With --strategy hypothesis, Hypothesis writes the fault plans
          instead (needs the hyp extra), once per Hypothesis seed.
session   Summarize a planning-session log and rerun it to check it replays.
ingest    Read a text log with a rules file (docs/rules-schema.md) and write
          a trace file (source adapter:text, every event exact, with the log
          line it came from). Entries no rule matches are counted and listed
          in a file; events logged out of time order are sorted and flagged,
          never dropped or corrected.
incident  WP4 bridge experiment, operator side: check an incident's
          preconditions, write the partial log a planner gets, run the random
          and Hypothesis baselines and the rule-based log reader
          (replayspect.reconstruct) through the same loop, and summarize or
          rerun bridge-session logs (replayspect.bridge).

search and baseline take --variant SPEC: run an implementation of the system
loaded from outside the package (path/to/file.py:NAME or package.module:NAME;
see replayspect.variant) instead of the registered one. A repro made with a
variant records it, and replay loads it again.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from replayspect.contract import ContractError
from replayspect.rewind import Selection, judge_setup, parse_time_us, read_trace, view, write_full
from replayspect.runner import System, get_system, make_repro, read_repro, replay, run_once, search, write_repro
from replayspect.session import environment_diff, summarize_log, verify_log
from replayspect.shrink import best_repro
from replayspect.tracefile import Header, TraceFileError, contracts_ref, plan_ref, read_trace_file, write_trace_file


def _system(args: argparse.Namespace) -> System | None:
    """The system to run, with ``--variant`` if given; None (after a message) when it cannot be set up."""
    if args.variant and args.mutant:
        print("--mutant and --variant cannot be combined", file=sys.stderr)
        return None
    try:
        return get_system(args.system, args.variant)
    except ValueError as exc:
        print(f"{args.cmd}: {exc}", file=sys.stderr)
        return None


def _runs_what(args: argparse.Namespace) -> str:
    return f"variant {args.variant}" if args.variant else f"mutants {args.mutant or 'none'}"


def _search(args: argparse.Namespace) -> int:
    system = _system(args)
    if system is None:
        return 2
    cs = system.contracts()
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    res = search(system, seeds, args.mutant, cs, keep_for=args.target, keep=args.candidates)
    print(f"{res.runs} runs, system {system.name}, {_runs_what(args)}")
    for c in cs.ids():
        if c in res.hits:
            print(f"  {c}: violated in {res.hits[c]} runs, first at seed {res.first_seed[c]}")
    if not res.hits:
        print("  no contract violated")
    for p in sorted(map(str, res.unmatched)):
        print(f"  warning: pattern {p} matched no event in any run; its contract was never exercised")
    if not args.target:
        return 1 if res.hits else 0
    if args.target not in res.hits:
        print(f"target {args.target} was not violated; nothing to shrink")
        return 0
    best = best_repro(system, res.kept, args.target, cs)
    assert best is not None
    doc = make_repro(best.run, args.target, best.summary())
    # The variant spec stays out of the file name, like the plan details.
    what = "variant" if system.variant else "-".join(best.run.mutants) or "none"
    name = f"{system.name}-{what}-{args.target}-seed{best.run.seed}.json"
    path = write_repro(doc, Path(args.out) / name)
    print(f"shrunk {args.target}: {best.faults_before} -> {best.faults_after} faults "
          f"(seed {best.run.seed}, {best.runs} runs) -> {path}")
    print(f"simulations: {res.runs} search + {best.total_runs} shrink over {len(res.kept)} candidates")
    print(f"  {doc['explain']['violation']['detail']}")
    return 1


def _replay(args: argparse.Namespace) -> int:
    doc = read_repro(Path(args.repro))
    try:
        r = replay(doc)
    except ValueError as exc:  # unknown system, or a variant that cannot be loaded
        print(f"replay: {exc}", file=sys.stderr)
        return 2
    if r.variant_note:
        print(f"note: {r.variant_note} (the digest decides whether the run is the same)")
    print(f"digest {'ok' if r.digest_ok else 'DIFFERENT'}, first violations "
          f"{'ok' if r.violations_ok else 'DIFFERENT'}, target {doc['target']} "
          f"{'violated' if r.target_ok else 'NOT violated'}")
    if args.trace_out:
        out = Path(args.trace_out)
        run = r.run
        header = Header(system=run.system, source="sim", seed=run.seed, plan=plan_ref(doc["plan"], args.repro),
                        contracts=contracts_ref(get_system(run.system).contracts_path), until_us=run.until_us)
        try:
            write_trace_file(out, run.trace.events, header)
        except FileExistsError:
            print(f"{out} exists; not overwriting it", file=sys.stderr)
            return 2
        print(f"trace: {len(r.run.trace)} events -> {out}")
    return 0 if r.ok else 1


def _ingest(args: argparse.Namespace) -> int:
    from replayspect.ingest import IngestError, RulesError, ingest_text, read_rules, unmatched_text

    out = Path(args.out)
    unmatched_path = Path(args.unmatched) if args.unmatched else Path(f"{out}.unmatched.txt")
    for p in (out, unmatched_path):
        if p.exists():
            print(f"ingest: {p} exists; not overwriting it", file=sys.stderr)
            return 2
    try:
        rules = read_rules(args.rules)
        data = Path(args.log).read_bytes()
        contracts = contracts_ref(args.contracts) if args.contracts else None
        res = ingest_text(data, rules, args.log, contracts)
    except (RulesError, IngestError) as exc:
        print(f"ingest: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ingest: {exc.filename or ''}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    write_trace_file(out, res.events, res.header)
    if res.unmatched:
        unmatched_path.parent.mkdir(parents=True, exist_ok=True)
        with unmatched_path.open("x", encoding="utf-8") as f:
            f.write(unmatched_text(res.unmatched))
    print("\n".join(res.summary(args.log, str(out), str(unmatched_path))))
    return 0


def _rewind(args: argparse.Namespace) -> int:
    try:
        tf = read_trace_file(args.trace)
        ref = read_trace(args.ref) if args.ref else None
        at = parse_time_us(args.at) if args.at is not None else None
        end = parse_time_us(args.end) if args.end is not None else None
        window = (parse_time_us(args.window[0]), parse_time_us(args.window[1])) if args.window else None
        sel = Selection(window, frozenset(args.actor))
        js = judge_setup(tf, args.contracts, end)
        if args.limit < 0:
            raise ValueError("--limit must be >= 0")
        notes = list(js.notes)
        if tf.header is not None and tf.header.origin is not None:
            notes.append(f"time 0 is {tf.header.origin} (header origin)")
        v = view(tf.trace, at_us=at, step_n=args.step, sel=sel, ref=ref, contracts=js.contracts,
                 end_us=js.end_us, end_why=js.end_why, notes=notes, limit=args.limit)
    except (TraceFileError, ContractError, ValueError, OSError) as exc:
        print(f"rewind: {exc}", file=sys.stderr)
        return 2
    print("\n".join(v.lines))
    if args.full:
        try:
            n = write_full(tf, sel, args.full)
        except FileExistsError:
            print(f"rewind: {args.full} exists; not overwriting it", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"rewind: {exc}", file=sys.stderr)
            return 2
        print(f"full: {n} selected events -> {args.full}")
    return 0


def _baseline(args: argparse.Namespace) -> int:
    if args.strategy == "hypothesis":
        return _baseline_hypothesis(args)
    system = _system(args)
    if system is None:
        return 2
    cs = system.contracts()
    first = None
    for i in range(args.budget):
        if run_once(system, args.seed_base + i, args.mutant, None, cs).violated():
            first = i
            break
    where = f"first violation at run {first} ({first + 1} runs)" if first is not None else "no violation"
    print(f"random search, seeds {args.seed_base}..{args.seed_base + args.budget - 1}, "
          f"{_runs_what(args)}: {where}")
    return 0


def _baseline_hypothesis(args: argparse.Namespace) -> int:
    try:
        from replayspect.hyp import HYPOTHESIS_VERSION, hyp_search
    except ImportError:
        print('--strategy hypothesis needs the hypothesis package: pip install -e ".[hyp]"', file=sys.stderr)
        return 2
    if _system(args) is None:
        return 2
    seeds = range(args.hyp_seed_start, args.hyp_seed_start + args.hyp_seeds)
    print(f"hypothesis plans {HYPOTHESIS_VERSION}, seeds {args.seed_base}..{args.seed_base + args.budget - 1}, "
          f"{_runs_what(args)}, hypothesis seeds {seeds.start}..{seeds.stop - 1}")
    found = []
    for h in seeds:
        r = hyp_search(args.mutant, args.seed_base, args.budget, h, args.system, variant=args.variant)
        where = (f"first violation at run {r.first_violation_run} ({r.runs_to_first_violation} runs), "
                 f"violated {', '.join(r.violated)}" if r.first_violation_run is not None else "no violation")
        print(f"  hypothesis seed {h}: {where}; rejected {r.rejected}, "
              f"no-effect entries {r.no_effect_entries}/{r.entries}")
        if r.runs_to_first_violation is not None:
            found.append(r.runs_to_first_violation)
    line = f"detected {len(found)}/{len(seeds)}"
    if found:
        found.sort()
        mid = len(found) // 2
        median = found[mid] if len(found) % 2 else (found[mid - 1] + found[mid]) / 2
        line += f"; runs to first violation when detected: median {median}, min {found[0]}, max {found[-1]}"
    print(line)
    return 0


def _session(args: argparse.Namespace) -> int:
    s = summarize_log(Path(args.log))
    print(f"runs {s['runs']} (rejected {s['rejected']}, with no-effect entries {s['with_no_effect_entries']})")
    if s["runs_to_first_violation"] is None:
        print("no violation")
    else:
        print(f"first violation at run {s['first_violation_run']} ({s['runs_to_first_violation']} runs), "
              f"violated {', '.join(s['violated'])}")
    if args.verify:
        bad = verify_log(Path(args.log))
        print("replay: ok" if not bad else f"replay: runs {bad} came out different")
        diff = environment_diff(Path(args.log))
        print("environment: same as the log" if not diff else
              "environment differs from the log:\n" + "\n".join(f"  {line}" for line in diff))
        return 0 if not bad else 1
    return 0


def _incident(args: argparse.Namespace) -> int:
    from replayspect import bridge
    from replayspect.incident import check_preconditions, defect_class, read_incident, view_text

    if args.action == "check":
        bad = 0
        for f in args.files:
            inc = read_incident(f)
            p = check_preconditions(inc)
            cm = p.correct_match
            cls = defect_class(inc)
            eq = "" if cls is None else f"; equivalent published defects {', '.join(cls) or 'none'}"
            print(f"{f}: {'ok' if p.ok else 'FAILS'}; matches itself {'yes' if p.self_match else 'NO'}; "
                  f"correct implementation reproduces it {'no' if p.correct_differs else 'YES'}, "
                  f"told apart by the log {'yes' if p.correct_log_differs else 'NO'} "
                  f"(lines {cm.matched}/{cm.total}){eq}")
            bad += not p.ok
        return 1 if bad else 0
    if args.action == "view":
        (f,) = args.files
        inc = read_incident(f)
        out = Path(args.out)
        hidden = [*inc.mutants, *([inc.variant.rpartition(":")[2]] if inc.variant else [])]
        if any(h and h.lower() in out.name.lower() for h in hidden):
            print("incident view: the file name must not mention a mutant or variant", file=sys.stderr)
            return 2
        try:
            with out.open("x", encoding="utf-8") as fh:
                fh.write(view_text(inc))
        except FileExistsError:
            print(f"{out} exists; not overwriting it", file=sys.stderr)
            return 2
        print(f"view: {inc.actor}-side log -> {out}")
        return 0
    if args.action == "baseline":
        (f,) = args.files
        cfg = bridge.BridgeConfig(f, args.budget, args.max_faults)
        log_dir = Path(args.log_dir)
        if args.strategy == "reconstruct":  # deterministic: one session
            log = log_dir / "reconstruct.jsonl"
            _, result = bridge.reconstruct_baseline(cfg, log)
            print(f"reconstruct: {result.status} after {result.runs} runs"
                  + (f" ({result.reason})" if result.reason else "")
                  + f"; {_bridge_line(bridge.summarize_log(log))} -> {log}")
            return 0
        for i in range(args.start, args.start + args.runs):
            log = log_dir / f"{args.strategy}-{i}.jsonl"
            if args.strategy == "random":
                bridge.random_baseline(cfg, i, log)
            else:
                bridge.hypothesis_baseline(cfg, i, log)
            print(f"{args.strategy} {i}: {_bridge_line(bridge.summarize_log(log))} -> {log}")
        return 0
    if args.action == "plan":
        (f,) = args.files
        recs = bridge.read_log(Path(f))
        first = next((r for r in recs[1:] if r["type"] == "run" and r.get("match", {}).get("reproduced")), None)
        if first is None:
            print(f"{f}: no run reproduced the incident", file=sys.stderr)
            return 1
        plan = json.loads(first["plan"]) if isinstance(first["plan"], str) else first["plan"]
        try:
            with Path(args.out).open("x", encoding="utf-8") as fh:
                fh.write(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        except FileExistsError:
            print(f"{args.out} exists; not overwriting it", file=sys.stderr)
            return 2
        print(f"plan of run {first['run']} (first reproducing run) -> {args.out}")
        return 0
    if args.action == "summary":
        for f in args.files:
            print(f"{f}: {_bridge_line(bridge.summarize_log(Path(f)))}")
        return 0
    bad = {f: bridge.verify_log(Path(f)) for f in args.files}
    for f, runs in bad.items():
        print(f"{f}: replay {'ok' if not runs else f'runs {runs} came out different'}")
    return 1 if any(bad.values()) else 0


def _bridge_line(s: dict) -> str:
    rep = f"reproduced at run {s['runs_to_reproduction']}" if s["reproduced"] else "not reproduced"
    return (f"{s['calls']} calls, {rep}, candidates {s['candidates']}, "
            f"confirmed {s['confirmed']}/{s['nominations']}, hidden fault named {s['nominated_hidden_fault']}, "
            f"by tolerance {s['runs_to_reproduction_by_tolerance']}, exact {'yes' if s['exact_reproduction'] else 'no'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m replayspect")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="random search, then shrink one target contract")
    s.add_argument("--system", default="lift.v0")
    s.add_argument("--mutant", action="append", default=[], help="repeatable, e.g. --mutant M4")
    s.add_argument("--variant", metavar="SPEC",
                   help="run this implementation of the system instead of the registered one: "
                        "path/to/file.py:NAME or package.module:NAME (runs that code; trusted files only). "
                        "Not with --mutant")
    s.add_argument("--seeds", type=int, default=1000)
    s.add_argument("--seed-start", type=int, default=0)
    s.add_argument("--target", help="contract to shrink, e.g. C3")
    s.add_argument("--candidates", type=int, default=5, help="failing seeds to shrink before keeping the smallest")
    s.add_argument("--out", default="repros")
    s.set_defaults(fn=_search)
    r = sub.add_parser("replay", help="rerun a repro file")
    r.add_argument("repro")
    r.add_argument("--trace-out", metavar="PATH", help="also write the run's trace here (a new file)")
    r.set_defaults(fn=_replay)
    rw = sub.add_parser(
        "rewind", help="look at a trace file at a time, step through it, slice it",
        description="Times are microseconds (1500000) or have a unit (1.5s, 1500ms, 1500000us). "
                    "Output is a summary; listings are capped by --limit and --full writes the "
                    "whole selection to a new trace file. A trace header, when present, gives the "
                    "default --contracts and --end; values given here override it and the output "
                    "says so. Exit status 2 on unreadable input.")
    rw.add_argument("trace", help="trace file (docs/trace-schema.md; e.g. from replay --trace-out)")
    rw.add_argument("--at", metavar="T", help="rewind to T: the state after every event with time <= T")
    rw.add_argument("--step", type=int, metavar="N",
                    help="list N selected events after the --at cursor (or the start); negative: before it")
    rw.add_argument("--window", nargs=2, metavar=("T0", "T1"), help="select events with T0 <= time <= T1")
    rw.add_argument("--actor", action="append", default=[], metavar="NAME",
                    help="select one participant's events; repeatable")
    rw.add_argument("--ref", metavar="TRACE", help="reference trace: report the first divergence")
    rw.add_argument("--contracts", metavar="YAML",
                    help="judge the trace against this contract file (default: the header's, if any)")
    rw.add_argument("--end", metavar="T",
                    help="end time for judging (default: the header's until_us, else the last event; "
                         "always printed)")
    rw.add_argument("--limit", type=int, default=50, help="most events to list (default 50)")
    rw.add_argument("--full", metavar="PATH",
                    help="write every selected event to this new trace file; its header records the cut")
    rw.set_defaults(fn=_rewind)
    ig = sub.add_parser(
        "ingest", help="read a text log with a rules file and write a trace file",
        description="The rules file (docs/rules-schema.md) splits each log entry, reads its timestamp and "
                    "maps entries to trace events; the first matching rule wins. Every event is exact, "
                    "with source adapter:text and the log line it came from. Entries no rule matches are "
                    "counted in the summary and listed in a file. Events logged out of time order are "
                    "sorted by time and flagged (out_of_order within clock.tolerance, out_of_tolerance "
                    "beyond it; runs of out_of_tolerance are reported as a suspected clock step); nothing "
                    "is dropped or corrected. Exit status 2 on a bad rules file or log line, which the "
                    "message names.")
    ig.add_argument("log", help="text log (UTF-8; CRLF line ends are accepted)")
    ig.add_argument("--rules", required=True, metavar="YAML", help="rules file (replayspect.rules/1)")
    ig.add_argument("--out", required=True, metavar="PATH", help="trace file to write (a new file)")
    ig.add_argument("--unmatched", metavar="PATH",
                    help="where to list unmatched entries (new file; default OUT.unmatched.txt; "
                         "written only when there are any)")
    ig.add_argument("--contracts", metavar="YAML",
                    help="contract file to record in the trace header, the default for rewind")
    ig.set_defaults(fn=_ingest)
    b = sub.add_parser("baseline", help="random search over a session's seeds")
    b.add_argument("--system", default="lift.v0")
    b.add_argument("--mutant", action="append", default=[])
    b.add_argument("--variant", metavar="SPEC",
                   help="run this implementation of the system instead of the registered one: "
                        "path/to/file.py:NAME or package.module:NAME (runs that code; trusted files only). "
                        "Not with --mutant")
    b.add_argument("--seed-base", type=int, default=0)
    b.add_argument("--budget", type=int, default=100)
    b.add_argument("--strategy", choices=["random", "hypothesis"], default="random")
    b.add_argument("--hyp-seeds", type=int, default=20, help="hypothesis strategy: how many Hypothesis seeds")
    b.add_argument("--hyp-seed-start", type=int, default=0)
    b.set_defaults(fn=_baseline)
    se = sub.add_parser("session", help="summarize a planning-session log")
    se.add_argument("log")
    se.add_argument("--verify", action="store_true", help="rerun every plan and compare")
    se.set_defaults(fn=_session)
    inc = sub.add_parser(
        "incident", help="WP4 bridge experiment: incidents, planner logs, baselines, session logs",
        description="check: preconditions of incident files. view: write the partial log a planner gets "
                    "(new file; its name must not mention the mutant or variant). baseline: run random or "
                    "Hypothesis plans, or the rule-based log reader (reconstruct), through the bridge loop, "
                    "one log per run. plan: write the first reproducing plan of a session log (for --mode "
                    "answer-only). summary: the WP4 metrics "
                    "of bridge-session logs. verify: rerun bridge-session logs. Incident files and logs "
                    "hold the answer; keep them away from planners.")
    inc.add_argument("action", choices=["check", "view", "baseline", "plan", "summary", "verify"])
    inc.add_argument("files", nargs="+", help="incident files (check, view, baseline) or session logs")
    inc.add_argument("--out", help="view, plan: output path (new file)")
    inc.add_argument("--strategy", choices=["random", "hypothesis", "reconstruct"], default="random",
                     help="baseline: random or Hypothesis plans, or the rule-based log reader (deterministic, "
                          "one session, no model)")
    inc.add_argument("--runs", type=int, default=3,
                     help="baseline: how many runs (seeds start..start+runs-1); not used by reconstruct")
    inc.add_argument("--start", type=int, default=0, help="baseline: first random or Hypothesis seed")
    inc.add_argument("--budget", type=int, default=120)
    inc.add_argument("--max-faults", type=int, default=20)
    inc.add_argument("--log-dir", default=".", help="baseline: directory for the session logs")
    inc.set_defaults(fn=_incident)
    args = ap.parse_args(argv)
    if args.cmd == "incident" and args.action in ("view", "plan") and not args.out:
        ap.error(f"incident {args.action} needs --out")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
