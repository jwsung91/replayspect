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
