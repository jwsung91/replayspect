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
