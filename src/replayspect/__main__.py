"""Command line: ``python3 -m replayspect search|replay``.

search  Run random-fault seeds against a system, report which contracts
        failed, shrink the failures of one target contract and write the
        smallest one as a repro file.
replay  Rerun a repro file and check it reproduces the recorded execution.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from replayspect.runner import get_system, make_repro, read_repro, replay, search, write_repro
from replayspect.shrink import best_repro


def _search(args: argparse.Namespace) -> int:
    system = get_system(args.system)
    cs = system.contracts()
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    res = search(system, seeds, args.mutant, cs)
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
    best, _ = best_repro(system, seeds, args.mutant, args.target, cs, args.candidates)
    assert best is not None
    doc = make_repro(best.run, args.target, best.summary())
    name = f"{system.name}-{'-'.join(best.run.mutants) or 'none'}-{args.target}-seed{best.run.seed}.json"
    path = write_repro(doc, Path(args.out) / name)
    print(f"shrunk {args.target}: {best.faults_before} -> {best.faults_after} faults "
          f"(seed {best.run.seed}, {best.runs} runs) -> {path}")
    return 1


def _replay(args: argparse.Namespace) -> int:
    doc = read_repro(Path(args.repro))
    r = replay(doc)
    print(f"digest {'ok' if r.digest_ok else 'DIFFERENT'}, first violations "
          f"{'ok' if r.violations_ok else 'DIFFERENT'}, target {doc['target']} "
          f"{'violated' if r.target_ok else 'NOT violated'}")
    return 0 if r.ok else 1


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
    r.set_defaults(fn=_replay)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
