# Changelog

One paragraph per work package of `docs/work-order-v3.md`, newest last.

## WP1: rewind viewer

`replayspect rewind <trace>` reads a trace file (canonical JSON Lines, one
event per line) and nothing else, so it works on simulator traces now and on
log-adapter traces later. By default it prints a two-line summary; `--at`
gives the state after every event up to a virtual time, `--step N` lists the
next N events (negative: the previous ones), `--window T0 T1` (inclusive) and
`--actor` select events, `--ref` reports the first divergence from another
trace and `--contracts` judges the trace, always printing the end time used
for judging first because deadline contracts depend on it (`--end`, default
the last event). Listings are capped by `--limit`; `--full PATH` writes the
whole selection to a new file, never to stdout. A malformed trace file fails
with its file name and line number. `replay --trace-out PATH` writes the
reproduced run as such a trace file. No model, contract or LLM code changed.

## WP2: trace schema

Trace files now have a written schema, `docs/trace-schema.md`, and a JSON
Schema for one line, `schemas/trace-1.schema.json` (version
`replayspect.trace/1`). An optional first line is a header with `schema`,
`system`, `source`, `seed`, `plan` (digest and repro path), `contracts`
(path and digest), `until_us` and `slice`. Every event now carries
`fidelity` (exact | reconstructed) and `source` (sim | adapter:<name>). The
digest still covers only the event core, so existing repro files replay with
the same digest. `replay --trace-out` writes the header. `rewind` takes its
default contract file and end time from the header; a command-line value
overrides it and the output says it differs from the header, and a changed or
missing contract file is reported. `rewind --full` now writes a trace file
that reads back, keeps the original `seq` numbers and records the cut (window,
actors, digest of the full trace) in `slice`. Files without a header read as
before. The new `tracefile` module holds the reader and writer, and
`jsonschema` joins the `dev` extra for the schema tests (they skip without
it). The rule for trace files shown to planners is written down: `seed`,
`plan`, `contracts` and `slice.of` set to null, and no mutant in the file
name. WP4 will enforce it with tests.

## WP3: implementation variants

A system can run an implementation variant loaded from outside the package (`--variant`).

## WP4: bridge experiment harness

An incident file (`replayspect.incident/1`) holds a hidden failing run: system, mutants or variant,
seed and an explicit plan. A bridge session (`replayspect.bridge`, MCP server `--incident`) gives
a planner one participant's log of it and runs every plan on the incident's seed. The log has a
null header, no link metadata, renumbered `seq` and an optional constant clock offset. Each run is
checked with the temporary WP4 match: same compared lines in order, within 250 ms, and the same
contracts violated. Polls are not compared, and an optional status rule compares poll-reply data.
Verdicts at 100 ms, 500 ms and 1 s are kept as diagnostics. `check_cause` reruns a reproducing plan
without one entry and confirms it when the incident's contracts all hold. Random and Hypothesis
plans run the same loop (`incident baseline`). `incident check` runs the two preconditions every
incident must pass: it matches itself, and the correct implementation is told apart by the log
alone. `incident summary` reports reproduction, candidates (entries whose single removal clears
the failure), the counterfactual confirmation rate and diagnostics; `incident verify` reruns a log.
The trial design is in `docs/experiments/bridge-01.md`.

Minimal trial (one incident per system, device and client logs): the LLM reproduced all four
logs in 2 to 6 runs and confirmed a cause in each; no random or Hypothesis session (20 each per
log, 120 runs) reproduced any. Single removals clear the failure for most entries of a
reproducing plan, so the confirmation adds little to the reproduction. Results and departures
from the registration are in `docs/experiments/bridge-01.md`.

Rule-based log reader (`replayspect.reconstruct`, `incident baseline --strategy reconstruct`): the
main baseline of the WP4 main trial, and a step of the WP5 path. It reads only what a planner gets
(the one-sided log, the public limits and, per run, the verdict, lines matched and the visible
participant's events of its own run with their link data, `incident.run_view`), and searches
depth first over edits that improve the first mismatch: adjust an existing entry, delay, drop or
duplicate a message, or a disconnect from a gap in the polls or ending at an unexplained resend,
earliest cause first. It never runs a plan twice and keeps only improvements, so it cannot loop;
it ends reproduced, stuck (no improving edit left; the furthest mismatch is reported), at the edit
cap, or out of budget. No model and no tokens.
