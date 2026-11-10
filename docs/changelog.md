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

Defect questions for the main trial (`docs/experiments/bridge-02.md`). A bridge session now asks
which defect caused the failure: with a published defect list the planner names one id
(`name_defect`, condition A), otherwise it describes the faulty behaviour (`describe_defect`,
condition B). One answer, recorded and not judged in the session. `summary` scores condition A
against the defects that reproduce the incident with its seed and plan (`incident.defect_class`,
also printed by `incident check`), with that class's share of the list as the chance level. An
incident can carry a one-line `symptom`, given in `describe` and hashed in the log. Modes: `full`;
`answer_only`, which gives a reproducing plan (`incident plan LOG --out FILE`) and asks only for the
defect; `symptom_only`, with no log, the chance level of the answer (`mcp_server --mode`,
`--given-plan`). `run_plan` now shows only the logged participant's side of the planner's own run,
keeping its link data, and violations without details. `check_cause` no longer ends the session;
the defect answer or `finish` does, and a used-up budget leaves the answer open. With `--incident`
the MCP server's budget defaults to 120.

Main trial (`docs/experiments/bridge-02.md`), 35 LLM sessions on 16 logs. Condition A (lift,
published defects): LLM alone named a right defect on 8 of 8 logs, but the symptom sentence alone
did on 6 of 8, so the log decided only two. Condition B (turntable, blind scoring): the symptom
alone gave partly right answers on every run, and the answers that saw the log were right on 11 of
12. The LLM reproduced 11 of 16 logs in 1 to 6 runs, the rule-based reader 8 in 6 to 114, and the
two overlap on 6. `check_cause` was called once in 16 sessions. The bridge `describe` tool now
declares a 200,000-character result size, because the client cut off one session's input at
50,000 characters.

## WP5a: text log ingest

`replayspect ingest LOG --rules RULES --out TRACE` turns a text log into a trace file
(`source: adapter:text`, every event `exact`). The rules file (`replayspect.rules/1`,
`docs/rules-schema.md`) is the only part that depends on the line format. It splits an entry into
fields with one regular expression, reads the timestamp (epoch, ISO 8601 or a strptime pattern),
and maps entries to events with an ordered list of rules where the first match wins, ignore rules
included. Templates fill an event's fields from the regex groups, with `|int`, `|float` and
optional groups. A time zone is never guessed. Multi-line entries join by a continuation pattern.
The input must be UTF-8, and CRLF line ends are accepted. Nothing is dropped silently: entries no
rule matches are counted and listed in a file. Events logged out of time order are sorted stably
and flagged (`out_of_order` within the tolerance, `out_of_tolerance` beyond it), and a run of
`out_of_tolerance` events is reported as a suspected clock step. Nothing is corrected here. Clock
estimation, driven replay and the reader belong to WP5b. Two minor additions to the trace schema
carry this. The event field `log` holds the log line and flags, and is outside the digest like
`fidelity` and `source`. The header field `origin` holds the wall-clock time of `t_us = 0`.
`rewind` shows both. The tests ingest the same log in two line formats with only the rules file
changed, and get the same trace.

## WP5b: driven replay

`replayspect drive TRACE` reproduces a client-side log without a seed (`docs/driven-replay.md`).
The log's participant is replayed as a script on the channel: its recorded sends and decisions
at their recorded times, each after whatever else is due at that instant. The device model
(`System.device`, or a variant's optional `device`) answers through a link that follows a fault
plan with `base: fixed`, so nothing draws from a seed, and the tests check that the seed does not
change the digest. The judge compares only the client's receives, with polls left out, in order
and within a tolerance. With `--expect` it also compares the violated contracts. Matched receives
carry their log line, which `rewind` shows. `--reconstruct` runs the rule-based reader against
driven runs; `--rtt` starts it from delays split from the logged request/ACK round trips and lets
it shift a split. The reader takes a start plan, compared kinds and extra candidate edits; start
entries are counted apart from search edits. `--sensitivity` counts the round trips whose outcome
changes when their split moves to an extreme: the part a client-side log does not decide.
`incident text` writes one side of a hidden run as a text log, with
`examples/rules/sim-client-ros.yaml` to ingest it, for the seed-blind test. Scope is one source:
merging two logs and estimating their clocks is later work.

Seed-blind experiment (`docs/experiments/driven-01.md`): 17 client-side logs from the WP4 pool.
With the hidden run's seed, the rule-based reader reproduced 6 of them, under the old judge and
under the driven-replay judge alike. Without the seed, by driven replay, it reproduced none; with
the round-trip start, one. With each hidden run's own link plan, all 17 microsecond logs reproduce
exactly. With timestamps cut to milliseconds, 8 do: a resend made at a reconnect is logged before
the reconnect. The seed had been handing over every delay the plan did not name.
