"""Command line: ``python3 -m replayspect search|replay|rewind|baseline|session``.

search    Run random-fault seeds against a system, report which contracts
          failed, shrink the failures of one target contract and write the
          smallest one as a repro file.
replay    Rerun a repro file and check it reproduces the recorded execution.
          With --trace-out, also write the run's trace as a trace file.
rewind    Look at a trace file: a summary by default; the state at a virtual
          time (--at), events after or before it (--step), a time window
          (--window), one participant (--actor), the first divergence from a
          reference trace (--ref) and contract status (--contracts). Listings
          are capped; --full writes the whole selection to a new file.
baseline  Random search over the same seeds a planning session uses
          (seed_base, seed_base + 1, ...): how many runs until a violation.
          With --strategy hypothesis, Hypothesis writes the fault plans
          instead (needs the hyp extra), once per Hypothesis seed.
session   Summarize a planning-session log and rerun it to check it replays.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from replayspect.contract import ContractError, load_contracts
from replayspect.rewind import Selection, TraceFileError, parse_time_us, read_trace, view, write_full
from replayspect.runner import get_system, make_repro, read_repro, replay, run_once, search, write_repro
from replayspect.session import environment_diff, summarize_log, verify_log
from replayspect.shrink import best_repro


def _search(args: argparse.Namespace) -> int:
    system = get_system(args.system)
    cs = system.contracts()
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    res = search(system, seeds, args.mutant, cs, keep_for=args.target, keep=args.candidates)
    print(f"{res.runs} runs, system {system.name}, mutants {args.mutant or 'none'}")
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
    name = f"{system.name}-{'-'.join(best.run.mutants) or 'none'}-{args.target}-seed{best.run.seed}.json"
    path = write_repro(doc, Path(args.out) / name)
    print(f"shrunk {args.target}: {best.faults_before} -> {best.faults_after} faults "
          f"(seed {best.run.seed}, {best.runs} runs) -> {path}")
    print(f"simulations: {res.runs} search + {best.total_runs} shrink over {len(res.kept)} candidates")
    print(f"  {doc['explain']['violation']['detail']}")
    return 1


def _replay(args: argparse.Namespace) -> int:
    doc = read_repro(Path(args.repro))
    r = replay(doc)
    print(f"digest {'ok' if r.digest_ok else 'DIFFERENT'}, first violations "
          f"{'ok' if r.violations_ok else 'DIFFERENT'}, target {doc['target']} "
          f"{'violated' if r.target_ok else 'NOT violated'}")
    if args.trace_out:
        out = Path(args.trace_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with out.open("x", encoding="utf-8") as f:
                f.write(r.run.trace.to_jsonl())
        except FileExistsError:
            print(f"{out} exists; not overwriting it", file=sys.stderr)
            return 2
        print(f"trace: {len(r.run.trace)} events -> {out}")
    return 0 if r.ok else 1


def _rewind(args: argparse.Namespace) -> int:
    try:
        trace = read_trace(args.trace)
        ref = read_trace(args.ref) if args.ref else None
        at = parse_time_us(args.at) if args.at is not None else None
        end = parse_time_us(args.end) if args.end is not None else None
        window = (parse_time_us(args.window[0]), parse_time_us(args.window[1])) if args.window else None
        sel = Selection(window, frozenset(args.actor))
        contracts = load_contracts(Path(args.contracts)) if args.contracts else None
        if end is not None and contracts is None:
            raise ValueError("--end is the end time for judging; it needs --contracts")
        if args.limit < 0:
            raise ValueError("--limit must be >= 0")
        v = view(trace, at_us=at, step_n=args.step, sel=sel, ref=ref, contracts=contracts, end_us=end,
                 limit=args.limit)
    except (TraceFileError, ContractError, ValueError, OSError) as exc:
        print(f"rewind: {exc}", file=sys.stderr)
        return 2
    print("\n".join(v.lines))
    if args.full:
        try:
            n = write_full(v.selected, args.full)
        except FileExistsError:
            print(f"rewind: {args.full} exists; not overwriting it", file=sys.stderr)
            return 2
        print(f"full: {n} selected events -> {args.full}")
    return 0


def _baseline(args: argparse.Namespace) -> int:
    if args.strategy == "hypothesis":
        return _baseline_hypothesis(args)
    system = get_system(args.system)
    cs = system.contracts()
    first = None
    for i in range(args.budget):
        if run_once(system, args.seed_base + i, args.mutant, None, cs).violated():
            first = i
            break
    where = f"first violation at run {first} ({first + 1} runs)" if first is not None else "no violation"
    print(f"random search, seeds {args.seed_base}..{args.seed_base + args.budget - 1}, "
          f"mutants {args.mutant or 'none'}: {where}")
    return 0


def _baseline_hypothesis(args: argparse.Namespace) -> int:
    try:
        from replayspect.hyp import HYPOTHESIS_VERSION, hyp_search
    except ImportError:
        print('--strategy hypothesis needs the hypothesis package: pip install -e ".[hyp]"', file=sys.stderr)
        return 2
    seeds = range(args.hyp_seed_start, args.hyp_seed_start + args.hyp_seeds)
    print(f"hypothesis plans {HYPOTHESIS_VERSION}, seeds {args.seed_base}..{args.seed_base + args.budget - 1}, "
          f"mutants {args.mutant or 'none'}, hypothesis seeds {seeds.start}..{seeds.stop - 1}")
    found = []
    for h in seeds:
        r = hyp_search(args.mutant, args.seed_base, args.budget, h, args.system)
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m replayspect")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="random search, then shrink one target contract")
    s.add_argument("--system", default="lift.v0")
    s.add_argument("--mutant", action="append", default=[], help="repeatable, e.g. --mutant M4")
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
                    "whole selection to a new file. Exit status 2 on unreadable input.")
    rw.add_argument("trace", help="trace file (JSON Lines, e.g. from replay --trace-out)")
    rw.add_argument("--at", metavar="T", help="rewind to T: the state after every event with time <= T")
    rw.add_argument("--step", type=int, metavar="N",
                    help="list N selected events after the --at cursor (or the start); negative: before it")
    rw.add_argument("--window", nargs=2, metavar=("T0", "T1"), help="select events with T0 <= time <= T1")
    rw.add_argument("--actor", action="append", default=[], metavar="NAME",
                    help="select one participant's events; repeatable")
    rw.add_argument("--ref", metavar="TRACE", help="reference trace: report the first divergence")
    rw.add_argument("--contracts", metavar="YAML", help="judge the trace against this contract file")
    rw.add_argument("--end", metavar="T",
                    help="end time for judging (default: the last event; always printed)")
    rw.add_argument("--limit", type=int, default=50, help="most events to list (default 50)")
    rw.add_argument("--full", metavar="PATH", help="write every selected event to this new file")
    rw.set_defaults(fn=_rewind)
    b = sub.add_parser("baseline", help="random search over a session's seeds")
    b.add_argument("--system", default="lift.v0")
    b.add_argument("--mutant", action="append", default=[])
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
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
