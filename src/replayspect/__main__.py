"""Command line: ``python3 -m replayspect search|replay|rewind|ingest|drive|baseline|session|incident``.

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
drive     Reproduce a client-side log (e.g. from ingest) by driven replay: the
          log is replayed as a script, the device is simulated, and only
          the client's receives are compared, so no seed is needed. With
          --reconstruct the rule-based log reader searches for the fault plan.
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


def residual_lines(m) -> list[str]:
    """Recorded minus simulated time of each matched receive: overall and by message, in ms."""
    def stats(xs: list[int]) -> str:
        xs = sorted(xs)
        mid = xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
        return f"min {xs[0] / 1000:.3f}, median {mid / 1000:.3f}, max {xs[-1] / 1000:.3f} ms (n={len(xs)})"

    by: dict[str, list[int]] = {}
    for w, g in m.pairs:
        by.setdefault(w.name, []).append(w.t_us - g.t_us)
    if not by:
        return ["residuals (recorded - simulated): no matched receive"]
    out = [f"residuals (recorded - simulated), matched receives: {stats([x for v in by.values() for x in v])}"]
    out += [f"  {name}: {stats(v)}" for name, v in sorted(by.items())]
    return out


def _drive(args: argparse.Namespace) -> int:
    from replayspect.driven import DrivenError, DrivenSetup, annotate, driven_reconstruct, split_sensitivity
    from replayspect.incident import TOLERANCE_US
    from replayspect.sim.link import FaultPlan, LinkError

    for p in (args.trace_out, args.plan_out, args.fit_out):
        if p and Path(p).exists():
            print(f"drive: {p} exists; not overwriting it", file=sys.stderr)
            return 2
    try:
        if args.mutant and args.variant:
            raise ValueError("--mutant and --variant cannot be combined")
        system = get_system(args.system, args.variant)
        if args.link_delay:
            from dataclasses import replace as _replace

            lo, hi = (parse_time_us(x) for x in args.link_delay)
            if lo > hi:
                raise ValueError("--link-delay range starts after it ends")
            p = system.profile
            system = _replace(system, profile=_replace(p, c2s=_replace(p.c2s, delay_us=(lo, hi)),
                                                       s2c=_replace(p.s2c, delay_us=(lo, hi))))
        tf = read_trace_file(args.trace)
        log = list(tf.trace.events)
        if not log:
            raise ValueError("the trace has no events")
        actors = sorted({e.actor for e in log})
        if len(actors) != 1:
            raise ValueError(f"driven replay takes one participant's log; this trace has {', '.join(actors)}")
        tol = parse_time_us(args.tolerance) if args.tolerance else TOLERANCE_US
        until = parse_time_us(args.until) if args.until else log[-1].t_us + tol
        setup = DrivenSetup(system, log, until, tuple(args.mutant), actors[0], tol,
                            set(args.expect) if args.expect else None, args.status_rule)
        fitres = None
        if args.fit:
            from replayspect.fit import Ranges, Usual, fit_log

            if args.plan or args.reconstruct:
                raise ValueError("--fit cannot be combined with --plan or --reconstruct")
            models = []
            if args.models:
                from replayspect.fit import device_models

                if args.mutant or args.variant:
                    raise ValueError("--models compares against the correct model: not with --mutant or --variant")
                offered = device_models(system)
                models = offered if args.models == "device" else [m.strip() for m in args.models.split(",") if m.strip()]
                bad = [m for m in models if m not in offered]
                if bad or not models:
                    raise ValueError(f"--models: {', '.join(bad) or 'none given'} not among the published device "
                                     f"defects ({', '.join(offered) or 'none'}); client defects are not compared, "
                                     "the client is the script")
            r = Ranges.of(setup)
            ranges = Ranges(tuple(parse_time_us(x) for x in args.c2s_delay) if args.c2s_delay else r.c2s,
                            tuple(parse_time_us(x) for x in args.s2c_delay) if args.s2c_delay else r.s2c,
                            tuple(parse_time_us(x) for x in args.dup_extra) if args.dup_extra else r.dup_extra)
            for name, (a, b) in (("c2s", ranges.c2s), ("s2c", ranges.s2c), ("dup", ranges.dup_extra)):
                if a > b:
                    raise ValueError(f"{name} range starts after it ends")
            usual = None
            if args.usual_delay:
                uc, us_ = (parse_time_us(x) for x in args.usual_delay)
                if not (ranges.c2s[0] <= uc <= ranges.c2s[1] and ranges.s2c[0] <= us_ <= ranges.s2c[1]):
                    raise ValueError("--usual-delay must lie inside the delay ranges")
                usual = Usual.given(uc, us_, tol)
            if args.window:
                from replayspect.fit import anomaly_windows

                if args.window == ["auto"]:
                    wins = anomaly_windows(setup.log, setup.actor, system.quiet_messages)
                elif len(args.window) == 2:
                    wins = [(parse_time_us(args.window[0]), parse_time_us(args.window[1]), ["given"])]
                    if wins[0][0] > wins[0][1]:
                        raise ValueError("--window starts after it ends")
                else:
                    raise ValueError("--window takes 'auto' or T0 T1")
                print(f"windows: {len(wins)}" + "".join(f"\n  {a / 1e6:.6f}s..{b / 1e6:.6f}s ({'; '.join(w)})"
                                                        for a, b, w in wins))
                from replayspect.fit import report_lines as _rl

                for a, b, _ in wins:
                    wr = fit_log(setup, ranges, args.fit_runs, branches=args.branches,
                                 branch_cap=args.branch_runs, window=(a, b), usual=usual, plus_one=args.plus_one)
                    print("\n".join(_rl(wr)))
            fitres = fit_log(setup, ranges, args.fit_runs, branches=args.branches, branch_cap=args.branch_runs,
                             usual=usual, plus_one=args.plus_one)
            if args.random_check and fitres.reproduced:
                from replayspect.fit import random_arrivals

                fitres.random_check = random_arrivals(setup, fitres, ranges, fitres.usual, args.random_check)
            if models:
                from dataclasses import replace as _replace

                from replayspect.fit import judge_models, random_arrivals

                others = {}
                for m in models:
                    ms = _replace(setup, mutants=(m,))
                    r_m = fit_log(ms, ranges, args.fit_runs, usual=usual, plus_one=args.plus_one)
                    if args.random_check and r_m.reproduced:
                        r_m.random_check = random_arrivals(ms, r_m, ranges, r_m.usual, args.random_check)
                    others[m] = r_m
                fitres.models = judge_models(fitres, others)
            plan, res = fitres.fit.plan, None
            if args.fit_out:
                with Path(args.fit_out).open("x", encoding="utf-8") as fh:
                    fh.write(json.dumps(fitres.to_dict(), indent=2, sort_keys=True) + "\n")
        elif args.reconstruct:
            if args.plan:
                raise ValueError("--plan and --reconstruct cannot be combined")
            res = driven_reconstruct(setup, args.budget, rtt=args.rtt, split=args.split)
            plan = res.plan
        else:
            plan = json.loads(Path(args.plan).read_text()) if args.plan else {"base": "fixed"}
            res = None
        trace, m = setup.run(plan)
    except (DrivenError, TraceFileError, LinkError, ContractError, ValueError, OSError) as exc:
        print(f"drive: {exc}", file=sys.stderr)
        return 2
    n_send = sum(e.kind == "send" for e in log)
    print(f"drive {args.trace}: {system.name}{' (variant)' if system.variant else ''}, {actors[0]} side scripted "
          f"({len(log)} events, {n_send} sends); {m.total} receives to match, polls left out; "
          f"tolerance {tol / 1000:g}ms; run until {until / 1e6:.6f}s")
    if res is not None:
        start = (f"; {res.start_entries} start delays from round trips (split {args.split:g})"
                 if args.rtt else "")
        print(f"reconstruct: {res.status} after {res.runs} runs, {len(res.edits)} search edits{start}"
              + (f" ({res.reason})" if res.reason else ""))
    if fitres is not None:
        from replayspect.fit import report_lines

        print("\n".join(report_lines(fitres)))
    fp = FaultPlan.from_dict(dict(plan))
    print(f"plan: base {fp.base}, {len(fp.delays)} delays, {len(fp.faults)} faults, {len(fp.disconnects)} disconnects")
    dt = f", largest time difference {m.max_dt_us / 1000:.3f}ms" if m.max_dt_us is not None else ""
    print(f"reproduced: {'yes' if m.reproduced else 'no'}; receives matched {m.matched}/{m.total}{dt}"
          + ("" if m.contracts_same is None else f"; violated contracts same: {'yes' if m.contracts_same else 'no'}")
          + ("" if m.status_same is None else f"; status sequence same: {'yes' if m.status_same else 'no'}"))
    if args.residuals:
        print("\n".join(residual_lines(m)))
    if m.first is not None:
        where = f" (log line {m.first['line']})" if m.first.get("line") else ""
        print(f"first mismatch{where}: expected {m.first['expected'] or 'nothing'}, got {m.first['got'] or 'nothing'}")
    if args.sensitivity:
        if m.reproduced:
            ss = split_sensitivity(setup, plan)
            print(f"split sensitivity: {ss.sensitive} of {ss.pairs} round trips change the outcome at an extreme split"
                  + (f" ({', '.join(ss.keys)})" if ss.keys else ""))
        else:
            print("split sensitivity: not measured (not reproduced)")
    if args.plan_out:
        with Path(args.plan_out).open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        print(f"plan -> {args.plan_out}")
    if args.trace_out:
        header = Header(system=system.name, source="sim", seed=None, plan=None,
                        contracts=contracts_ref(system.contracts_path), until_us=until,
                        origin=tf.header.origin if tf.header else None)
        n = write_trace_file(args.trace_out, annotate(trace.events, m), header)
        print(f"trace: {n} events -> {args.trace_out} (matched receives carry their log line)")
    return 0 if m.reproduced else 1


def _device(args: argparse.Namespace) -> int:
    from replayspect.devicelog import Completeness, DeviceLogError, device_report, read_device_log, report_lines
    from replayspect.fit import device_models

    try:
        system = get_system(args.system)
        offered = device_models(system)
        models = []
        if args.models:
            models = offered if args.models == "device" else [m.strip() for m in args.models.split(",") if m.strip()]
            bad = [m for m in models if m not in offered]
            if bad or not models:
                raise ValueError(f"--models: {', '.join(bad) or 'none given'} not among the published device "
                                 f"defects ({', '.join(offered) or 'none'})")
        complete = Completeness.parse(args.complete)
        if complete.client and not args.client:
            raise ValueError("--complete client:... applies to the count check, which needs --client")
        late = parse_time_us(args.late)
        log = read_device_log(Path(args.log).read_text(encoding="utf-8"))
        if not log.events:
            raise ValueError("the device log has no recv, send, state or effect line")
        client = list(read_trace_file(args.client).trace.events) if args.client else None
        contracts = None
        if args.contracts:
            from replayspect.contract import load_contracts
            contracts = load_contracts(Path(args.contracts))
            if contracts.protocol != system.name:
                raise ValueError(f"--contracts: {args.contracts} is for {contracts.protocol}, not {system.name}")
        rep = device_report(system, log, models, client, complete, late, contracts=contracts)
        if args.out:
            with Path(args.out).open("x", encoding="utf-8") as fh:
                fh.write(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    except (DeviceLogError, TraceFileError, ContractError, ValueError, OSError) as exc:
        print(f"device: {exc}", file=sys.stderr)
        return 2
    print(f"device {args.log}: {system.name}")
    print("\n".join(report_lines(rep)))
    return 0 if rep["valid"] and rep["models"][0]["conforms"] else 1


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
                 end_us=js.end_us, end_why=js.end_why, notes=notes, limit=args.limit,
                 cut_start_us=js.cut_start_us)
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
    if args.action == "text":
        from replayspect.incident import run_incident, text_log

        (f,) = args.files
        inc = read_incident(f)
        system = inc.system_obj()
        vocab = system.vocabulary
        text = text_log(run_incident(inc, system).trace.events, args.actor, ms=args.ms,
                        poll=vocab.poll_request if vocab else "STATUS",
                        poll_reply=vocab.poll_reply if vocab else "STATUS_REPLY")
        try:
            with Path(args.out).open("x", encoding="utf-8") as fh:
                fh.write(text)
        except FileExistsError:
            print(f"{args.out} exists; not overwriting it", file=sys.stderr)
            return 2
        print(f"text: {args.actor}-side log of the hidden run, {'ms' if args.ms else 'us'} timestamps, "
              f"{text.count(chr(10))} lines -> {args.out}")
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
    dr = sub.add_parser(
        "drive", help="reproduce a client-side log by driven replay (no seed)",
        description="The log's participant (the client) is replayed as a script: its recorded sends and "
                    "decisions at their recorded times. The device model answers through a link that follows "
                    "a fault plan (base fixed: unplanned delays are the profile minimum), so nothing depends on "
                    "a seed. Only the client's receives are compared (polls left out): kind, name, request id "
                    "and data without link, in order, each within --tolerance of its log line; with --expect, "
                    "the violated contracts too. --reconstruct searches for a plan with the rule-based reader. "
                    "Exit status 0 reproduced, 1 not, 2 bad input.")
    dr.add_argument("trace", help="one participant's trace (e.g. from ingest)")
    dr.add_argument("--system", default="lift.v0")
    dr.add_argument("--variant", metavar="SPEC", help="an implementation variant with a device (replayspect.variant)")
    dr.add_argument("--mutant", action="append", default=[], help="device mutant, repeatable")
    dr.add_argument("--plan", metavar="JSON", help='fault plan to run (default: {"base": "fixed"})')
    dr.add_argument("--until", metavar="T", help="run end (default: the last log event plus the tolerance)")
    dr.add_argument("--tolerance", metavar="T", help="largest time difference of a matched receive (default 250ms)")
    dr.add_argument("--expect", nargs="+", metavar="C", help="the violated contracts must be exactly these")
    dr.add_argument("--status-rule", action="store_true", help="also compare the sequence of poll replies")
    dr.add_argument("--reconstruct", action="store_true", help="search for a plan with the rule-based reader")
    dr.add_argument("--budget", type=int, default=120, help="reconstruct: most runs (default 120)")
    dr.add_argument("--rtt", action="store_true",
                    help="reconstruct: start from delays split from the logged round trips (request to its ACK) "
                         "and allow shifting a split; start delays are counted apart from search edits")
    dr.add_argument("--split", type=float, default=0.5, help="--rtt: share of a round trip given to the request")
    dr.add_argument("--link-delay", nargs=2, metavar=("LO", "HI"),
                    help="link delay range for this run, both directions, instead of the system's profile: an empty "
                         "plan uses LO, and --fit's default ranges follow it (0 is allowed)")
    dr.add_argument("--residuals", action="store_true",
                    help="print recorded minus simulated time of the matched receives (min, median, max), "
                         "overall and by message")
    dr.add_argument("--fit", action="store_true",
                    help="fit the log by fixing what it shows: reply delays computed from the logged receive times, "
                         "the client's logged disconnects as facts, request arrivals chosen from the interval the "
                         "replies allow (docs/driven-replay.md)")
    dr.add_argument("--c2s-delay", nargs=2, metavar=("LO", "HI"), help="--fit: request delay range "
                    "(default: the system's link profile; a real link can be faster)")
    dr.add_argument("--s2c-delay", nargs=2, metavar=("LO", "HI"), help="--fit: reply delay range (default: profile)")
    dr.add_argument("--dup-extra", nargs=2, metavar=("LO", "HI"), help="--fit: duplicate extra delay range (default: profile)")
    dr.add_argument("--fit-runs", type=int, default=2000, help="--fit: run cap for the fit (default 2000)")
    dr.add_argument("--usual-delay", nargs=2, metavar=("C2S", "S2C"),
                    help="--fit: the usual delay per direction: the default request arrival, and a delay above it "
                         "plus the tolerance is a fault (default: arrivals at the range's low end, and no delay inside "
                         "the range is a fault)")
    dr.add_argument("--plus-one", action="store_true",
                    help="--fit: also collect the explanations with one fault more than the fewest (a diagnostic)")
    dr.add_argument("--fit-out", metavar="PATH", help="--fit: write the explanations as JSON (new file)")
    dr.add_argument("--random-check", type=int, metavar="N",
                    help="--fit, when reproduced: N draws of one command's arrivals at random, off the option points; "
                         "a draw that reproduces with fewer faults than the fewest found is reported (a check, not a proof)")
    dr.add_argument("--models", metavar="M1,M2,...",
                    help="--fit: also fit the log under each listed device defect model (or 'device': every "
                         "published device-side defect) and compare the fewest faults each needs with the correct "
                         "model's; a defect is accused only with fewer faults, and tied defects are named together")
    dr.add_argument("--window", nargs="+", metavar="T",
                    help="--fit: also fit windows, 'auto' (around retries, failures, error replies, repeated "
                         "replies, late ACK or DONE, disconnects) or T0 T1; the whole-log fit is still reported")
    dr.add_argument("--branches", action="store_true",
                    help="--fit, when reproduced: count command attempts whose arrival, moved inside the interval "
                         "the log allows, changes the outcome")
    dr.add_argument("--branch-runs", type=int, default=120, help="--branches: run cap (default 120)")
    dr.add_argument("--sensitivity", action="store_true",
                    help="when reproduced: count round trips whose outcome changes at an extreme split")
    dr.add_argument("--trace-out", metavar="PATH",
                    help="write the run's trace (new file); matched receives carry their log line")
    dr.add_argument("--plan-out", metavar="PATH", help="write the plan (new file)")
    dr.set_defaults(fn=_drive)
    dv = sub.add_parser(
        "device", help="check a device log against the device model (no link, no fit)",
        description="Reads the device's own log (recv, send, state and effect lines with the device clock; "
                    "every other line is skipped unseen, error lines make the log invalid). The device model "
                    "is fed what the device received, at the device's times, and its sends, state changes and "
                    "effects are compared with the log: the correct model and each --models defect, each "
                    "'conforms', its first mismatch, or 'not checked'. Absence is evidence only for what is "
                    "declared --complete: the model is fed only when the device's receives are, and a model "
                    "event missing from the log counts only for a declared kind. With --client, messages lost "
                    "on the link or copied are counted per message and request id, under the same rule. "
                    "Exit status 0 when the log is valid and the correct model conforms, 1 otherwise, 2 bad "
                    "input. See docs/device-log.md.")
    dv.add_argument("log", help="device log (the testbed firmware's '# <millis> ...' lines)")
    dv.add_argument("--system", default="lift.v0")
    dv.add_argument("--models", metavar="M1,M2,...", help="also check these published device defects ('device': all)")
    dv.add_argument("--client", metavar="TRACE", help="the client's trace (from ingest), for the count check")
    dv.add_argument("--complete", action="append", default=[], metavar="SOURCE:KINDS",
                    help="a source that logs these kinds completely: device: any of recv,send,state,effect; "
                         "client:send,recv (repeatable; default: partial, nothing is inferred from absence)")
    dv.add_argument("--contracts", metavar="YAML",
                    help="also judge these contracts on the device log's events alone, with no model; a contract "
                         "that refers to a device kind not declared --complete is not judged")
    dv.add_argument("--late", default="2ms", metavar="TIME",
                    help="how much later than the model a logged event may be (default 2ms)")
    dv.add_argument("--out", metavar="PATH", help="the report as JSON (a new file)")
    dv.set_defaults(fn=_device)
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
                    "one log per run. text: write one side of the hidden run as a text log for ingest "
                    "(examples/rules/sim-client-ros.yaml; the WP5b seed-blind test). "
                    "plan: write the first reproducing plan of a session log (for --mode "
                    "answer-only). summary: the WP4 metrics "
                    "of bridge-session logs. verify: rerun bridge-session logs. Incident files and logs "
                    "hold the answer; keep them away from planners.")
    inc.add_argument("action", choices=["check", "view", "text", "baseline", "plan", "summary", "verify"])
    inc.add_argument("files", nargs="+", help="incident files (check, view, baseline) or session logs")
    inc.add_argument("--out", help="view, text, plan: output path (new file)")
    inc.add_argument("--actor", choices=["client", "device"], default="client",
                     help="text: whose side of the hidden run to write (default client)")
    inc.add_argument("--ms", action="store_true", help="text: cut timestamps to milliseconds")
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
    if args.cmd == "incident" and args.action in ("view", "text", "plan") and not args.out:
        ap.error(f"incident {args.action} needs --out")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
