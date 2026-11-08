# replayspect v3 work order — record · replay · judge · vary

Nov 8, 2026 · @마스터

This is the English work order for the coding agent. It restates the Korean design doc (first tab) as scoped work packages with acceptance criteria. Everything that lands in the repository (code, docs, contracts, commit messages) is written in English.

## Goal, non-goals, principles

replayspect records an execution as a trace, replays it deterministically with rewind, judges it against behavioral contracts, and shows "what if" by changing one thing and replaying. Where no record exists, models and an LLM fill in possible scenarios, but fact and reconstruction are always kept apart.

Non-goals for v3: reproducing arbitrary software without a model; generalizing the simulator itself; writing root-cause reports (that is the LLM's guesswork, not the tool's claim); any robot-wide model.

Principles (all five are enforced in code and tests, not just in docs):

1. Only contracts decide pass/fail. Scenario generators (random, Hypothesis, LLM) never judge.
2. Same seed, same trace. A repro file replays identically forever.
3. The LLM only proposes: scenarios, cause hypotheses, contract candidates. The engine judges; a human confirms.
4. Fact and reconstruction are tagged. Every event and every result carries a fidelity tag.
5. Small first. Component-level models (lift, turntable) stay the unit; the robot is composed on top later.

## Architecture

Three layers. The engine owns formats and judgment; it never owns content.

| Layer | Contains | Rule |
| --- | --- | --- |
| Workflows | rewind (incident analysis), vary (fault exploration), LLM as proposer | Call the engine; never bypass the judge |
| Engine (replayspect core) | record (trace schema), replay/rewind, judge (contracts + symptom), vary (counterfactual + minimizer) | Deterministic, no LLM inside, no tokens spent |
| Plugins | SUT models (lift, turntable, robot controller), log adapters (text, rosbag, pcap, wirestead recorder), contract files (contracts/\<module\>/, contracts/system/), LLM providers (api, mcp-tool, mcp-sampling) | Users fill these; lift/turntable are shipped only as examples |

Fidelity tags on every replay result: exact (full record, no model used), reconstructed (partial log fixed, model filled gaps), explored (no record). A result containing any reconstructed event is never reported as a confirmed cause.

Naming: the incident workflow is rewind, the exploration workflow is vary. Do not use the JoJo metaphor in README or code; it belongs in design notes only.

## Work packages 1–5 (no model-writing cost)

Do them in this order. Each is a separate branch and PR. Stop and report after each; do not start the next one on your own.

### WP1 — Rewind viewer

- Deliverable: replayspect rewind \<trace\> [--at \<t\>] [--step] [--window \<t0\> \<t1\>] [--actor \<name\>]. Prints events at a virtual time, steps forward/back, slices a window, filters by participant.
- Default output is a summary (event count, first divergence from a reference trace if given, contract status). Full dump only with --full, written to a file, never to stdout.
- Accepts simulator traces today; the same code must accept adapter output (WP5) without change.
- Done when: works on existing lift and turntable traces; a test replays a trace, rewinds to a time, and gets identical events every run.

### WP2 — Trace schema as a public contract

- Deliverable: docs/trace-schema.md and a versioned JSON schema for the six event kinds (send, recv, handle, effect, state, fault).
- Add two fields to every event: fidelity (exact | reconstructed) and source (sim | adapter name).
- Done when: existing traces validate against the schema; schema version is in every trace header.

### WP3 — Turntable mutants as hidden ground truth

- Implement the user's turntable defects M1–M5 as switches, as for the lift. Show the core code for each and get confirmation before measuring.
- Measure random detection rate over 1,000 seeds; keep only rarely-found ones.
- Do not run the v2 LLM-vs-random campaign on the turntable. These mutants are the hidden answers for WP4.

### WP4 — Bridge experiment (the first real test of v3)

- Setup: pick a hidden failing run (mutant + seed + fault plan unknown to the planner). Give the planner only a partial log: device-side events only, or client-side with skewed clocks.
- Loop: planner proposes a scenario → engine replays → engine checks symptom match and contract violation → planner proposes a cause → engine replays with that single fault removed (counterfactual).
- Record four metrics per run: reproduction success, number of surviving candidates (ambiguity), counterfactual confirmation rate, tokens per incident.
- Reuse the v2 harness (sessions, budgets, registry). Random and Hypothesis run the same loop as baselines.
- Done when: one full loop runs end to end on the lift and the turntable, and a results table is in docs/experiments/bridge-01.md.

### WP5 — Text log adapter

- Deliverable: replayspect ingest \<log\> --rules \<rules.yaml\> → trace file. Rules map regex captures to trace events (kind, actor, time, payload). No LLM in this path.
- Clock handling: per-source offset and tolerance in the rules file; events outside tolerance are flagged, not dropped.
- Every ingested event is fidelity: exact; gaps between them are left for the model (WP7 later fills them as reconstructed).
- Done when: a sample text log from the user round-trips into a trace that WP1 can rewind, and a bad rules file fails loudly with the line number.

## Work packages 6–9

### WP6 — Symptom oracle and partial-match judge

- A symptom is a second oracle next to contracts: an observed outcome from a log ("robot stopped on the turntable"). Format: a small YAML with the required events in order and a time tolerance; anything not listed is free.
- The LLM may draft a symptom from a log; a human confirms it before use. The engine evaluates it; the LLM never does.
- judge reports both: contract result and symptom match (n/m lines matched, first mismatch).
- Done when: the WP4 loop uses symptom match instead of a hard-coded check.

### WP7 — Contract provenance and the generic library

- Add grade (stated | mined | generic | symptom) and source (doc line, trace count, or log id) to every contract. The violation report's first line prints contract id, grade, and source.
- Ship contracts/generic/: one response per request at most, one effect per retried req_id at most, no state transition never observed in normal runs, no effect from a response arriving after timeout.
- Promotion loop: LLM proposes candidates with a repro seed → engine checks each against N normal traces and drops any that fail there → human confirms → candidate becomes a contract. Contracts are frozen within a round and versioned between rounds.
- Split contracts/\<module\>/ from contracts/system/; interaction rules ("no top-module motion while driving") live only in system/.
- Done when: the lift's existing contracts carry grade: stated; the generic set runs on both SUTs with no false positives on 1,000 normal seeds.

### WP8 — LLM provider interface

- One interface, three implementations: api (replayspect calls the model; owns the loop and the round cap), mcp-tool (an MCP server that wraps the CLI; the host's model calls replayspect), mcp-sampling (server asks the host's model via sampling/createMessage; stub only until a host supports it).
- Build order: engine → CLI → MCP server (thin wrapper, same command vocabulary) → api adapter → sampling stub.
- Session budget lives server-side as state ("N rewinds per session") so it holds even when the host owns the loop.
- Never send raw logs to a model. Inputs to the model are: diff from a normal run, a time window from WP1, the summary line from judge.
- Ship a skill file (skills/replayspect-rewind.md) describing the call order for an agent: ingest → judge summary → propose cause → counterfactual rewind → submit contract candidate. The engine must work with the skill absent.
- Done when: the WP4 loop runs through mcp-tool from Claude Code and through api with identical results for the same seed.

### WP9 — Candidate ranking

- When several causes survive, sort by confidence tier first, severity tier second. Both are computed from engine facts only; a model's self-reported confidence is never an input.
- Confidence inputs: counterfactual confirmed (top tier), fraction of log lines matched, fraction of reconstructed events (lower is better), number of seeds reproducing the same outcome.
- Severity inputs: grade of the violated contract (generic > stated > mined > symptom), a human-set severity attribute on the contract, effect kind (motor action > state transition > wrong reject reason).
- Report line format: candidate id · confidence tier · severity tier · matched log lines · unconstrained parts · counterfactual result.
- Done when: the WP4 results table shows ranked candidates and the ranking is reproducible from the trace alone.

## Constraints, definition of done, later work

Constraints for the agent:

- Do not change the documents the planner reads (protocol, contracts, plan format) while an experiment is in progress; the inputs of earlier rounds must stay comparable.
- Do not rewrite README's purpose statement until WP4 results are in. Then replace it with the goal sentence above.
- Keep lift and turntable as examples under examples/ or sut/; they are not the product.
- Keep tool output short by default; verbose output goes to files. Every tool result may land in a user's context window.
- Mutants, defect forms, and hidden seeds stay outside the repository until the experiment is published.

Definition of done for every WP: tests pass, the CLI help text is updated, the change is one PR with a short English description, and a one-paragraph note is appended to docs/changelog.md.

Later work (not in this order; do not start without a new work order):

- wirestead recorder: the user's own comms library emits trace events directly (full record, fidelity: exact).
- rosbag adapter and pcap adapter: second-phase log sources; pcap raises the device side to exact.
- Model interpolation: fix recorded events, let the model fill gaps, tag them reconstructed.
- Variation vocabulary schema for vary: faults, inputs, event timing, initial state; extend only by adding to the schema.

Open questions for the user:

- [ ] When to run the real ROS nodes under virtual time instead of a controller model.
- [ ] Whether the first MCP host supports sampling/createMessage; if not, mcp-sampling stays a stub.
- [ ] Which text log goes first into WP5 (controller log, device log, or both).
