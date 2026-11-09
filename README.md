# replayspect

**Replay protocol failures exactly, then inspect them against a contract.**

Device integrations (a robot talking to a lift, a door, a charger) rarely break
on the happy path. They break on the edges: a retry that arrives after the
original, a late reply after a timeout, a duplicate after a reconnect. Those
bugs are hard to trigger on real hardware, and what you cannot reproduce you
cannot prove fixed.

replayspect runs both sides of an integration in a deterministic simulation,
injects network faults from a seed, and judges the resulting trace against a
declared behavioural contract, such as *"a retried request id moves the motor at
most once."* Any violation is shrunk to a minimal scenario that replays the
same way every time.

## Principles

- **The contract is the only oracle.** Scenarios say what happens; contracts say
  what must hold. Whatever generates scenarios (random search today, an LLM
  later) never decides whether a run passed.
- **Same seed, same trace.** Virtual time, no threads, no wall clock, one seeded
  RNG. A trace serialises to canonical JSONL with a SHA-256 digest; a replay with
  a different digest is a bug in replayspect.
- **Small before smart.** v0 has no LLM. It must find seeded bugs with plain
  random search first, so any later AI gets measured against a real baseline.

## Status

Pre-alpha. v0 is being built in this order:

- [x] Virtual-time scheduler
- [x] Trace event model and digest
- [x] Link model: delay, loss, duplication, disconnects, replayable fault plans
- [x] Virtual lift device and client, with seeded bugs (mutants)
- [x] Contract YAML and checkers
- [x] Scenario runner, repro files, shrinking
- [x] Planning sessions, MCP server, run summaries and baseline comparison
- [x] First v2 trials: LLM planner vs random search on one mutant (`docs/experiment-v2.md`)
- [x] Second v2 trials on a mutant that random search finds quickly: roughly a tie
- [x] v1 baseline: Hypothesis writes fault plans in the planner's plan space (`docs/design-v0.md`)
- [x] Third v2 trials on three new mutants that random search rarely finds (`docs/experiment-v2.md`)
- [x] Work-mode MCP tools: search, shrink and replay from an MCP client
- [x] Second system: virtual turntable (`turntable.v0`), no mutants yet (`docs/protocol-turntable.md`)
- [x] v3 WP1: `rewind` viewer for trace files, `replay --trace-out` (`docs/work-order-v3.md`)
- [x] v3 WP2: trace schema with header, fidelity and source (`docs/trace-schema.md`, `schemas/trace-1.schema.json`)
- [x] v3 WP3: run an implementation variant loaded from outside the package (`--variant`)
- [x] v3 WP4: bridge experiment, reproduce a hidden run from a partial log (minimal trial done; main trial registered separately, `docs/experiments/bridge-01.md`)

## Usage

```bash
# random search against the virtual lift with seeded bug M4, then shrink the C3 failure
python3 -m replayspect search --mutant M4 --target C3 --out repros
# 1000 runs, system lift.v0, mutants ['M4']
#   C3: violated in 19 runs, first at seed 58
# shrunk C3: 56 -> 3 faults (seed 65, 30 runs) -> repros/lift.v0-M4-C3-seed65.json
# simulations: 1000 search + 153 shrink over 5 candidates
#   MOVING_DOWN --MOVE_UP--> MOVING_UP is not declared

python3 -m replayspect replay repros/lift.v0-M4-C3-seed65.json
# digest ok, first violations ok, target C3 violated
```

`search` exits with 1 when any contract was violated, like a failing test.

### Rewind a trace

`replay --trace-out` writes the reproduced run as a trace file
([docs/trace-schema.md](docs/trace-schema.md)): JSON Lines with a header
naming the system, seed, plan, contract file and end time. `rewind` reads
trace files only, so it does not need the system that made them. It prints a
short summary; add `--at` to see the state at a virtual time, `--step N` for
the next N events (negative: the previous ones), `--window T0 T1` and
`--actor` to select events, and `--ref` for the first divergence from another
trace. It judges the trace against the header's contract file until the
header's end time; `--contracts` and `--end` override them and the output
says so. Times are microseconds or have a unit (`15.6s`, `500ms`). Listings
stop at `--limit` (default 50); `--full PATH` writes every selected event to
a new trace file whose header records the cut.

```bash
python3 -m replayspect replay repros/lift.v0-M4-C3-seed65.json --trace-out traces/m4.jsonl
# digest ok, first violations ok, target C3 violated
# trace: 431 events -> traces/m4.jsonl

python3 -m replayspect rewind traces/m4.jsonl --at 15.6s --step 4 --actor device
# judged until t=90.000000s (header until_us)
#   C3 violated at #88 15.677267s r-0003: MOVING_DOWN --MOVE_UP--> MOVING_UP is not declared
# contracts (lift.v0): 1 violated, 7 ok (C1, C2, C4, C5, C6, C7, C8)
# contracts file: contracts/lift.v0.yaml (from header)
# trace: 431 events, 0.000000s..90.000000s; actors: client 206, device 222, link 3
# selection (actor device): 222 events; kinds: effect 11, recv 97, send 102, state 12
# at t=15.600000s: 85 of 431 events have happened; next #85 at 15.627267s
#   device: state MOVING_DOWN (since 13.103042s); last event #81 14.497674s device send STATUS_REPLY s-0013 k=0 {"state":"MOVING_DOWN"}
#   judged until t=15.600000s (the rewind time)
#   contracts so far: 0 violated, 8 ok (C1, C2, C3, C4, C5, C6, C7, C8)
# step 4: selected events after t=15.600000s (4):
#   #85 15.627267s device recv MOVE_UP r-0003 k=0
#   #86 15.627267s device send ACK r-0003 k=0
#   #87 15.677267s device effect motor_start r-0003 {"dir":"up"}
#   #88 15.677267s device state MOVING_UP r-0003 {"from":"MOVING_DOWN","on":"MOVE_UP"}

python3 -m replayspect rewind traces/m4.jsonl --end 95s --window 15s 16s --actor device --full traces/m4-device.jsonl
# judged until t=95.000000s (given; differs from header: 90.000000s)
# ...
# full: 4 selected events -> traces/m4-device.jsonl
```

Deadline contracts (C2: closed within 15 s) depend on the end time, so the
first line always says where judging stopped. A contract none of whose
trigger events occurred is reported as *not exercised*, not as ok.

### Hypothesis baseline

Hypothesis can write the fault plans instead, in the same plan space a planner
uses and over the same seeds, once per Hypothesis seed:

```bash
pip install -e ".[hyp]"
python3 -m replayspect baseline --mutant M4 --seed-base 1000 --budget 120 --strategy hypothesis --hyp-seeds 20
# hypothesis plans 6.170.15, seeds 1000..1119, mutants ['M4'], hypothesis seeds 0..19
#   hypothesis seed 0: first violation at run 13 (14 runs), violated C3; rejected 0, no-effect entries 15/29
#   ...
# detected 19/20; runs to first violation when detected: median 41, min 14, max 88
```

Generated plans depend on the Hypothesis version as well as its seed, so the
version is printed with the results.

### Implementation variants

`search` and `baseline` take `--variant path/to/file.py:NAME` (or
`package.module:NAME`): the system runs that implementation instead of the
registered one, with the same contracts, link profile and run length. A
variant builds its run from the package's scheduler, channel and trace and
uses the link profile it is given (`src/replayspect/variant.py`), so its
digests compare with the system's. A repro made with a variant records the
spec and the file's digest, and `replay` loads it again; if the file has
changed since, the first line of the output says so and the digest decides.
Variants never appear in trace headers or in anything a planner sees.
Loading a variant runs its code, so load only files you trust.

### Planning sessions over MCP

A planner (a person, or a model behind an MCP client) can drive the simulator
itself: it reads the protocol, contracts and plan format, submits fault plans,
and gets back each run's timeline and violations. The session hides which bug
is seeded, assigns seeds, counts every call against a budget and logs
everything so the session can be rerun exactly.

```bash
pip install -e ".[mcp]"
python3 -m replayspect.mcp_server --mutant M4 --seed-base 1000 --budget 120 --log /tmp/m4.jsonl
python3 -m replayspect session /tmp/m4.jsonl --verify        # after the session
python3 -m replayspect baseline --mutant M4 --seed-base 1000 --budget 120
```

Each session requires a new log path; an existing path is refused to prevent
restarts from resetting the run budget. See `docs/experiment-v2.md` for isolated
trials and the limits of the comparison with random search.

### Work tools over MCP

For your own work from an MCP client (for example Claude Code), a separate
server offers the same search, shrink and replay as the command line:

```bash
claude mcp add replayspect-work -- python3 -m replayspect.mcp_work --repros repros
```

- `search`: random-fault seeds; with a target contract, the smallest shrunk
  failure is written to the repro directory and its file name returned.
- `shrink`: shrink one failing run, from a fault plan you give (for example
  one a planning session found) or from a seed's random faults.
- `replay`: rerun a repro file by name and check it reproduces exactly.

Nothing is hidden or budgeted here: mutants and seeds are plain arguments.
Never give this server to a planner in a trial. Repro files are only read
and written inside `--repros`, by plain file name, and never overwritten.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest          # fast tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -m ""    # everything, including slow seed sweeps
```

replayspect uses no pytest plugins, so disabling plugin autoload is safe. It
matters in a sourced ROS 2 shell: ROS puts its own pytest plugins (such as
`launch_testing`) on `PYTHONPATH`, and they can fail during test collection.

## About the name

*replay* + *inspect*, with a *spec* in the middle, because every replay is
inspected against one. Readers of a certain manga may also recognise a Stand
that rewinds the past and plays it back so a detective can study it. That is
roughly the job description.
