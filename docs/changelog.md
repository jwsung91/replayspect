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

`drive --fit`: driven replay fitted by fixing what the client log shows instead of searching
delays (`docs/driven-replay.md`). The client is a script, so reply delays do not change the
device. One run with chosen request arrivals gives every device send's time, and each reply's
delay is the logged receive time minus that. A send with no receive is a loss, an extra receive is
a duplicate, and a receive no send explains is reported as unexplained. The client's logged
disconnects (`incident text` now writes `link down`/`link up`) are facts. Request arrivals start
at the middle of the interval their replies allow, read off a probe run, and change one move at a
time with a run cap. `--branches` counts command attempts whose outcome changes inside that
interval. Delay ranges are parameters. "Unexplained" means every choice in the fitter's choice
space was run (evidence about the device); otherwise the fit is "incomplete" (no improving move,
the run cap, or a space too large to run), a limit of the fitter. Without expected contracts, when
explanations that match every receive differ in the device's violations, all of them are
reported and none is chosen. Development runs on the 17 driven-01 logs reproduce 5; these are not
results.

## WP5c stage 1: hardware testbed (code)

`examples/testbed-uno/` holds the code for the testbed:
- An Arduino Uno runs the `lift.v0` device as `lift_device.h`, plain C++ wrapped by `lift_uno.ino`.
- A Jetson Orin runs the client (`host/client.py`) through a link that passes lines and records
  them (`host/fault_link.py`).
- `rules/testbed-client.yaml` ingests the client's log.

Details:
- **Wire format:** one ASCII line per message at 115200 baud. `READY` carries the build options,
  and `#` device log lines carry `millis()`. The Uno's memory limits and every place the firmware
  differs from the model are listed in the testbed README.
- **Conformance:** a test compiles the header natively and checks its replies and state changes
  against the Python model.
- **Client log:** one wall-clock reading plus monotonic time, with a header line (firmware options,
  think seed, plan id) and a validity line. A device error or a reset makes the run invalid.
- **Tests:** a host test runs the client against a fake board. The log ingests and reproduces with
  an empty plan at the fake link delay.
- **`drive`:** `--link-delay` sets the link delay range for one run (0 allowed), and `--residuals`
  prints the recorded-minus-simulated times.
- **`pyserial`** is an optional extra (`[testbed]`).

The first hardware run is the operator's.

WP5c stage 2 code (for testbed-01):
- **Fault link:** `host/fault_link.py` applies fault plans in the simulator's vocabulary:
  per-message delay, drop or duplicate, and disconnect windows anchored on events. It writes what
  it actually did to a truth file.
- **Client:** logs the `link down` / `link up` it is told of, resends after a reconnect, and
  timestamps in microseconds.
- **Fitter:** `drive --fit --window auto|T0 T1` fits windows chosen from the log alone (around
  retries, failures, error replies, repeated replies, late `ACK` or `DONE`, and disconnects). Only
  the window's receives are judged, and only its attempts change. The enumeration no longer varies
  poll requests, which do not change the device state, so it is complete for command replies.

Hardware experiment testbed-01 (`docs/experiments/testbed-01.md`): 39 real client logs from the
Uno lift with known injected faults (3 controls, 24 single-fault, 8 two-fault, 4 hard), fitted
with `drive --fit` as-is over public ranges of 0–5 s. 37 reproduce (38 at ms), almost all at the
first choice. But only 19 of 46 injected faults are found, and 19 of 105 restored faults are
right. Every missed loss was read as a long delay (12 of 12). A duplicated request reads as a
duplicated `ACK`. A request in flight when a logged disconnect starts is not treated as lost to it
(T12, incomplete). No window was unexplained.

## WP5b fit: minimal explanations (after testbed-01)

`drive --fit` now reports every explanation with the fewest link faults instead of one plan.
A fault is a drop, a duplicate, or a delay above the usual delay plus the tolerance.
- **Usual delay and default arrival.** `--usual-delay C2S S2C` sets the usual delay; without it, on
  simulator logs, no delay inside the profile range is a fault. An arrival the log does not bound
  now defaults to the usual delay, not to the middle of the range.
- **Reply pairing** is a minimum-fault assignment: order may change, and every tied assignment is
  kept. Pairing in time order read a lost `DONE` followed by a normal one as one long delay.
- **Search.** The search runs per anomalous command, in order of how many attempts leave the
  default. A choice is skipped when its request-side faults exceed the best found (the reply side
  only adds faults). The units' sets are recounted and combined on the whole log, and searched
  together if a combination fails.
- **Report.**
  - `f*`, the number of explanations, the faults common to all ("determined") and per request id
    the alternatives ("not determined", e.g. request dup or `ACK` dup).
  - `--plus-one` adds the explanations with one fault more, as a diagnostic.
  - A list of slow round trips observed in the log, kept apart from the fit.
  - `--fit-out` writes it all as JSON.
- **Status.** `minimal shown` says whether the search was complete. `unexplained` now needs every
  choice of a unit run with every earlier unit reproduced.
- **Disconnects.** A request in flight when a logged disconnect begins is lost with it, not a fault
  (testbed-01 T12). A cut log's horizon is its cut (`DrivenSetup.end_us`).
- **Removed.** The hill-climbing moves and the separate enumeration are gone, and the default run
  cap is 2000.
- **Tests.**
  - On short synthetic logs, brute force over the same option space gives the same minimal and
    one-more sets.
  - The reply pairing equals an exhaustive assignment search on random small keys.
  - Random off-grid arrivals never explain a short log with fewer faults; this is not a proof.
- **testbed-01.** The 39 logs are now development material, not a measurement. The measurement is
  testbed-02, registered separately.

Hardware experiment testbed-02 (`docs/experiments/testbed-02.md`): 48 real client logs from the
Uno lift (3 controls, 34 single, 5 retry, 3 deliberately non-minimal, 3 mixed), fitted with the
minimal-explanation fit at `20cb5a0`, unchanged during and after the runs. All 48 reproduce with
the minimal set complete, and no log is called unexplained (the main indicator). Where the truth
was not predicted to miss, it is in the set in 36 of 37. Determined command faults are real in
17 of 21; poll-request faults read as reply faults, as expected. In R04 the search missed a
1-fault explanation that lies between its arrival points and reported `f*` 2. The `f*+1` level is
searched only inside anomalous commands. Slow round trips list the 40 ms delays that the minimal
set absorbs.

## WP5b fit: fixes after testbed-02

Four changes to `drive --fit`, from what testbed-02 showed. The 87 testbed logs are development
material for them, not a measurement.
- **Arrival points from any reply pairing (R04).** For each logged reply of its request, an attempt
  may also arrive at the time nearest the usual delay where both its delay and that reply's delay
  are within the limit, whichever send the reply is paired with. A retry answered before the first
  attempt is now one late reply, not two faults.
- **Lost polls are not decided.** A poll with a fault in the default is a search unit. A poll does
  not change the device, so a lost request and a lost reply tie and both are reported (likewise a
  late or repeated request and reply). An explanation that leaves a logged reply of the unit
  unexplained is not taken, because poll replies are left out of the match. A poll the option
  space cannot explain keeps the default, as before.
- **`f*+1` outside the units (S03).** With `--plus-one`, every command outside the units with no
  fault is searched for one fault more on the whole log, so a log the default explains still has
  an `f*+1` set.
- **`--random-check N`.** The random-arrival test as a check on any log, real ones included: draws
  of one command's arrivals off the option points, reporting any that reproduce with fewer faults
  than `f*` (`random_arrivals`). It is a check, not a proof.
- **Tests.** The brute-force control now covers every command and the polls with a fault, and
  synthetic logs of the R04, S03 and lost-poll shapes are added.

## WP5b fit: value ranges and names

- **Value ranges (R04).** Explanations with the same faults are merged, as before. The values they
  differ in (another reply pairing, another arrival point) are now kept as a range per fault, each
  end found on the whole log. Up to 4 other arrival choices with the same faults are run on the
  whole log for this. In R04 the truth (`ACK` k0 2.5 s, k1 40 ms) has the same faults as an `f*+1`
  explanation reported with the other pairing's values; its range now holds both pairings. Faults
  outside the search units are merged by faults too: before, two pairings that differed only in
  values counted as two explanations.
- **Names.** "determined" is now "common to every minimal explanation", and "not determined" is
  "alternatives (the minimal explanations differ)". A common fault is not shown to be true: in the
  five development logs where one was wrong, the real faults were not the fewest. In
  `--fit-out`, `determined`/`undetermined` are now `common`/`alternatives`, and each fault's
  `value_us` is now `value_range_us` (`[lowest, highest]`, or null for a drop). The methods are
  `FitResult.common()` and `FitResult.alternatives()`. Published experiment documents keep the
  names they were written with.

## Stage 3 code: device models and the firmware defect switch

- **`drive --fit --models M1,M2,...`** (or `--models device`) fits the log under each published
  device defect model as well, with the same settings, and compares the fewest faults (see
  `docs/driven-replay.md`). A defect is accused only when its model needs fewer faults than the
  correct model, or the correct model cannot explain the log. A tie is no accusation. Defects tied
  at the fewest are named together ("M1 or M2"). A comparison with an incomplete or unsettled fit
  is undecided. Client defects are not offered. `judge_models`, `model_lines`, `device_models`.
- **Firmware defect switch.** `-DLIFT_DEFECT=N` builds the model's device defect MN (1, 2, 4, 5,
  9, 10, 11; M3 needs disconnects the device never sees on serial). The conformance test runs
  every script under every switch against the model's mutant.
- **Where it fired.** The device log says `defect fired MN REQ_ID` where the defect's own branch
  changes what the device does, and `build defect=...` at boot.
- **The answer stays out of the client log.** `READY` no longer carries `defect=none`, and the
  client drops any `defect=` field from its header.
- **Seen ranges.** The value ranges of #29 are named for what they are: the values seen in the
  minimal explanations found, not every value that would fit. The report says so, and the JSON key
  is `seen_range_us`.
