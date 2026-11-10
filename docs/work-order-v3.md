# replayspect work order v3.1 — after bridge-01 and bridge-02

2026-11-10

This revision replaces v3 in full. The goal, principles, architecture, and standing constraints are carried over from v3; WP1–WP4 are recorded as done; WP5 onward is rewritten from the experiment results. Replace `docs/work-order-v3.md` with this text in one PR; the planner never reads this file, so past experiments stay comparable.

Everything that lands in the repository (code, docs, contracts, commit messages) is written in English.

## Goal, non-goals, principles

replayspect records an execution as a trace, replays it deterministically with rewind, judges it against behavioral contracts, and shows "what if" by changing one thing and replaying. Where no record exists, models and an LLM fill in possible scenarios, but fact and reconstruction are always kept apart.

Non-goals: reproducing arbitrary software without a model; generalizing the simulator itself; writing root-cause reports (that is the LLM's guesswork, not the tool's claim); any robot-wide model.

Principles (all five are enforced in code and tests, not just in docs):

1. Only contracts decide pass/fail. Scenario generators (random, Hypothesis, LLM) never judge.
2. Same seed, same trace. A repro file replays identically forever.
3. The LLM only proposes: scenarios, defect claims, contract candidates. The engine judges; a human confirms.
4. Fact and reconstruction are tagged. Every event and every result carries a fidelity tag.
5. Small first. Component-level models (lift, turntable) stay the unit; the robot is composed on top later.

## Architecture

Three layers. The engine owns formats and judgment; it never owns content.

| Layer | Contains | Rule |
| --- | --- | --- |
| Workflows | `rewind` (incident analysis), `vary` (fault exploration), LLM as proposer | Call the engine; never bypass the judge |
| Engine (`replayspect` core) | record (trace schema), replay/rewind, judge (contracts + symptom), vary (counterfactual + minimizer) | Deterministic, no LLM inside, no tokens spent |
| Plugins | SUT models (lift, turntable, robot controller), log adapters (text, rosbag, pcap, wirestead recorder), contract files (`contracts/<module>/`, `contracts/system/`), LLM providers (api, mcp-tool, mcp-sampling) | Users fill these; lift/turntable are shipped only as examples |

Fidelity tags on every replay result: `exact` (full record, no model used), `reconstructed` (partial log fixed, model filled gaps), `explored` (no record). A result containing any reconstructed event is never reported as a confirmed cause.

Naming: the incident workflow is `rewind`, the exploration workflow is `vary`. Do not use the JoJo metaphor in README or code; it belongs in design notes only.

## Status and what the experiments changed

| WP | Scope | State |
| --- | --- | --- |
| WP1 | `rewind` (non-interactive step, `--ref`, `--contracts`, `--full` as JSONL), `replay --trace-out`, "not exercised" status | Done (PR #1) |
| WP2 | Trace schema v1, header line, `fidelity` and `source` per event, `slice` | Done (PR #2) |
| WP3 | External SUT variant loader (`--variant`); hidden variants kept outside the repository | Done |
| WP4 | Bridge experiments 01 and 02, rule-based reader (`--strategy reconstruct`), defect questions, symptom input | Done (results in `docs/experiments/`) |
| WP5a | Text log ingest (`ingest`, rules file `replayspect.rules/1`), event `log` and header `origin` | Done (PR #15) |

The experiments confirmed two claims and corrected four. The rest of this document is written to the corrected version.

- Confirmed: a log from one side is enough to reproduce an incident, but only for a solver that reads the log. Reading the log is also what moves a defect answer from "partly right" to "right".
- Corrected: reproduction is not purely a rule-based job. The reader and the LLM solve overlapping but different sets. Order of attempts is reader first (free, deterministic), LLM when the reader is stuck.
- Corrected: a plan handed from the reader to the LLM must be minimized first. One wrong answer came from a superfluous plan item taken for the trigger.
- Corrected: the cause question is "which defect", stated as trigger and effect, not "which fault item". Removing a fault item is confirmed at close to chance level.
- Corrected: the counterfactual check is an automatic engine step. In bridge-02, where it was an optional tool available in full mode only, it was called in 1 of 16 sessions. (In bridge-01 it was the tool that ended a session, so all 4 sessions called it.)
- New fact: reproduction in WP4 relied on a fixed seed. The simulated client's schedule matched the incident because both came from the same seed. A real log has no such seed, so ingest alone does not make a log reproducible (see WP5b).
- New fact: one task description exceeded 50,000 characters and hit a client limit. Most input tokens were that one text accumulating in context.

## WP5a — Text log ingest

- Deliverable: `replayspect ingest <log> --rules <rules.yaml>` writes a trace file with a header (`source: adapter:text`). Rules map regex captures to trace events (kind, actor, time, name, req_id, data). No LLM in this path.
- Every ingested event is `fidelity: exact`. Lines no rule matches are counted and listed, never silently dropped.
- Clock fields in the rules file: timestamp format, timezone, and a per-source tolerance. Events that are out of order or outside the tolerance are flagged, not dropped. Ingest does no clock correction; that belongs to WP5b.
- Done when: a sample log round-trips into a trace that `rewind` reads unchanged; a bad rules file fails with the rule name and log line number; the unmatched-line report is in the summary.

## WP5b — Driven replay (seed-blind reproduction)

Ingest gives a trace that can be rewound but not reproduced. This package makes it reproducible by letting the recorded side drive the simulation.

- Scripted actor: on the recorded side, replace the model with a player that emits exactly the recorded sends at the recorded times. The other side stays a model. Nothing on the scripted side depends on a seed.
- Start with client-side (controller) logs. There the sends are known and the unknowns are link faults and device behaviour. Device-side-only logs come later; they need the client's schedule to be inferred.
- Retries are replayed as recorded. The scripted client does not decide retries; they are facts in the log.
- One source only: a client-side log. Its times are the simulation's times, so there is no clock to estimate. Polls are replayed at their recorded times; no fixed period is assumed.
- Fidelity: recorded events stay `exact`, model-produced events are `reconstructed`, and any result built this way is reported as `reconstructed`.
- The reader and the match judge run against the driven simulation. The judge compares recorded receives with simulated receives.
- Acceptance, seed-blind: take the client side of existing bridge incidents, write them out as text logs in a realistic line format, ingest them with a rules file, and reproduce them without the seed. Report how many of the logs the reader solved with the seed it still solves without it. Incident material stays outside the repository. The table puts the reader unchanged next to the reader with a round-trip start (delays split from request/ACK round trips), at µs and at ms timestamps, and reports for each solved log how many round trips change the outcome when their split moves to an extreme.
- Only after that passes: run the same path on the operator's real sample log.
- Done when: the seed-blind table is in `docs/experiments/`, and at least one real-format log goes ingest → driven replay → `rewind` end to end.

## WP6/7 — Verifiable defect claims

v3 had the symptom oracle (WP6) and contract provenance (WP7) as separate packages. They are merged because the open design task from the experiments spans both: a defect description must arrive in a form the engine can check.

- Symptom oracle: a small YAML with the required events in order and a time tolerance; anything not listed is free. The LLM may draft a symptom from a log; a human confirms it before use and keeps it at outcome level (what was seen on the floor), with no mechanism and no contract vocabulary. The engine evaluates it; the LLM never does. It replaces the "same violated contract set" condition of the WP4 match.
- `judge` reports both results: the contract result and the symptom match (n/m lines matched, first mismatch).
- Defect claim: the LLM states a defect as trigger and effect, and also drafts it as a contract candidate in the existing DSL. Prose alone is not accepted as a result.
- Engine check of a claim, automatic on submission: the candidate must be violated by the incident trace and must hold on N normal traces. The engine also removes each item of the minimized reproducing plan in turn and reports which ones are necessary. Neither step is a tool the planner chooses to call.
- Promotion: a claim that passes both checks goes to a human, who confirms or drops it. Confirmed candidates become contracts; contracts are frozen within a round and versioned between rounds.
- Provenance: `grade` (`stated` | `mined` | `generic` | `symptom`) and `source` (doc line, trace count, or log id) on every contract; the violation report's first line prints contract id, grade, and source.
- Generic library in `contracts/generic/`: one response per request at most; one effect per retried req_id at most; no state transition never observed in normal runs; no effect from a response arriving after timeout.
- Module contracts in `contracts/<module>/`; interaction rules ("no top-module motion while driving") live only in `contracts/system/`.
- First candidate for the loop: the contract gap recorded in the operator's private WP3 notes. It is not described in the repository.
- Done when, all three: the lift's existing contracts carry `grade: stated`; the generic set runs on both SUTs with no false positives on 1,000 normal seeds; one bridge incident runs log → symptom → reproduction → claim → both engine checks → human confirmation, and the confirmed contract catches the same incident on replay.

## WP8 — Provider interface and a task description in pieces

- One interface, three implementations: `api` (replayspect calls the model; owns the loop and the round cap), `mcp-tool` (an MCP server that wraps the CLI; the host's model calls replayspect; built first), `mcp-sampling` (server asks the host's model via `sampling/createMessage`; stub only until a host supports it). Same command vocabulary for all three.
- Build order: engine → CLI → MCP server (thin wrapper) → api adapter → sampling stub.
- Never send a raw log file to a model. The model's inputs are the diff from a normal run, a time window read through `rewind`, and the summary line from `judge`. The bridge experiments handed the planner a whole one-sided log in one piece; this package replaces that.
- Split the task description. No single tool result exceeds 20,000 characters. Protocol, contracts, and plan format are separate reads.
- Session budget lives server-side as state ("N rewinds per session") so it holds even when the host owns the loop. Report input and output tokens per session in every experiment table.
- Skill file `skills/replayspect-rewind.md` gives the call order: ingest → symptom → reader → (LLM if stuck) → minimize → claim → engine checks → candidate. The engine works with the skill absent.
- Done when: a bridge incident runs through `mcp-tool` with every tool result under the size limit and the input tokens per session reported against the WP4 figures; the same incident through `api` gives identical engine results.

## WP9 — Candidate ranking

- When several candidates survive, sort by confidence tier first, severity tier second. Both are computed from engine facts only; a model's self-reported confidence is never an input.
- Confidence inputs: both engine checks of WP6/7 passed (top tier), fraction of log lines matched, fraction of reconstructed events (lower is better), and for simulator incidents the number of seeds reproducing the same outcome.
- Severity inputs: grade of the violated contract (generic > stated > mined > symptom), a human-set `severity` attribute on the contract, effect kind (motor action > state transition > wrong reject reason).
- Report line format: `candidate id · confidence tier · severity tier · matched log lines · unconstrained parts · counterfactual result`.
- It depends on WP6/7: the top confidence tier is the two automatic checks.
- Done when: ranked candidates appear in an experiment table and the ranking is reproducible from the trace alone.

## Later work

Not in this order; do not start any of these without a new work order.

- wirestead recorder: the operator's own comms library emits trace events directly (full record, `fidelity: exact`).
- rosbag adapter and pcap adapter: second-phase log sources; pcap raises the device side to `exact`.
- Driven replay from device-side-only logs: the client's schedule has to be inferred.
- Two sources: a controller log and a device log together, with clock offset and linear drift estimated per source from request/response pairs, and the residual reported.
- Variation vocabulary schema for `vary`: faults, inputs, event timing, initial state; extend only by adding to the schema.
- Real ROS nodes under virtual time in place of a controller model.

Model interpolation, listed here in v3, is now part of WP5b.

## Constraints, definition of done, open questions

Constraints (carried over from v3, with two additions):

- Keep lift and turntable as examples under `examples/` or `sut/`; they are not the product.
- Do not rewrite the README purpose statement without an instruction. Status lines are updated in the PR of the WP that changes them, and say only what is implemented.
- One WP per branch and PR. Stop and report after each WP. Do not start the next one without an instruction.
- The operator merges every PR. Never merge without an explicit instruction that names the PR; if the number is missing, ask.
- Do not change the documents the planner reads (protocol, contracts, plan format) while an experiment is registered or running; the inputs of earlier rounds must stay comparable.
- Hidden variants, incident files, seeds, defect forms, and scoring keys stay outside the repository until the experiment is published.
- Hidden variants are reserved as hidden answers for bridge-style experiments. Do not run a planner campaign (v2-style LLM versus random) against them until they are published.
- Every experiment that reports an LLM result runs its baselines through the same loop, incidents, and budget: the rule-based reader, random, and Hypothesis.
- Experiments are preregistered. Anything that differs from the registration, however small, goes into "Departures from the registration" with session IDs.
- Tool output is short by default; detail goes to files. Added: no tool result above 20,000 characters.
- Added: no result is called a cause unless the engine checks in WP6/7 have run on it. Until then it is a hypothesis and is labelled so.

Definition of done for every WP: tests pass, CLI help is updated, one PR with a short English description, and one paragraph in `docs/changelog.md`.

Order: WP5a → WP5b → WP6/7 → WP8 → WP9.

Open questions for the operator:

- [ ] The real text log sample for WP5a and which side it comes from. Controller-side logs fit WP5b first.
- [ ] The design of the next experiment. It should use ingested text logs, and the public-defect condition must not be solvable from the symptom sentence alone.
- [ ] When to run real ROS nodes under virtual time instead of a controller model.
- [ ] Whether the first MCP host supports `sampling/createMessage`.
