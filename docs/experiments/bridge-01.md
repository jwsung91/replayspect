# Bridge experiment 01 (WP4): reproduce a hidden failing run from a partial log

Operator document. Do not give it to a planner.

Question: given only one participant's log of a failing run, can a planner find a fault scenario
that reproduces the log, and name a cause that the engine confirms by removing it? Random and
Hypothesis plans run the same loop as baselines.

All results are **explored**: a confirmed cause is confirmed in the model, not as the cause of a real
incident (work order, fidelity tags).

## Setup

**Incident.** One hidden failing run: system, mutants (lift) or an implementation variant
(turntable, `--variant`), seed `S`, and an explicit fault plan `P*` (`replayspect.incident/1`,
`src/replayspect/incident.py`).

- `P*` lies inside the planner's plan space: `base: random`, at most 20 faults and disconnects,
  values within the link profile. So an exact answer exists.
- `P*` was made from a random-search run on a seed outside the range used to measure the mutants.
  The run's explicit plan was moved to `base: random`, then reduced by delta debugging over all
  entries (delays, faults, disconnects) while the run still violated exactly the same contracts.
- Incident files, the mutant/variant behind each incident and the seeds stay outside the
  repository until the experiment is published.

**Fixed seed.** Every run of a bridge session uses `S`. The log fixes the environment (when the
client sends what), and only the faults are unknown. With v2's `seed_base + n`, command timing
would change from run to run and no plan could reproduce the log.

**What the planner sees.** Four MCP tools and nothing else: `describe`, `run_plan`, `check_cause`,
`finish` (`python3 -m replayspect.mcp_server --incident FILE`). Client isolation is as in
`docs/experiment-v2.md`.

- `describe` returns the task, the protocol description, the contract file, the plan format, the
  limits, the budget and the **log**.
- The log is a trace file of one participant's events (planner-view rules in
  `docs/trace-schema.md`):
  - header with `seed`, `plan`, `contracts`, `until_us` and `slice.of` null;
  - no `data.link`;
  - `seq` renumbered from 0;
  - for a client-side log, one constant clock offset added to every time, and the note "its clock
    is off from the simulator's by an unknown constant".
- `run_plan` returns the run's timeline and violations (as in v2) and the reproduction result:
  `reproduced`, lines matched `n/m`, and the first mismatch. The expected line is timed in the
  log's clock, the run's line in the run's own clock.
- Not given: `S`, `P*`, mutants or variant and their paths, the hidden trace and its digest, the
  clock offset, and which contracts the incident violated.
- Never in the planner's reach: SUT source, variant files, incident files, session logs, repros,
  tests, and repository documents other than the three public ones. `tests/test_bridge.py` plants
  sentinel strings in a variant file and its directory, and checks that none reaches a tool result.
  It also checks for SUT class and constant names that the public documents do not mention.

## Reproduction judge (temporary; WP6 replaces it with the symptom judge)

`wp4_match` compares the viewed participant's events of a candidate run with the incident's. The
incident is **reproduced** when all four hold:

1. The compared lines are the same, in the same order: kind, name, `req_id`, and data without
   `link`. Compared lines are every event except the poll messages (`STATUS`, `STATUS_REPLY`).
   Polls are shown in the log but not compared.
2. Every compared line is within **250 ms** of the incident's time.
3. With the incident's `status_rule`: the poll replies' data, with consecutive repeats merged, is
   the same sequence. This rule exists for defects that only the poll replies show (see
   Preconditions). It is off for the trial incidents.
4. The run violates the same set of contracts as the incident.

`n/m` counts the compared lines that match from the start, up to the first mismatch. The verdict
at 100 ms, 250 ms, 500 ms and 1 s is recorded in the log as diagnostic columns, so the main
trial's tolerance can be chosen from data. An identical trace digest (exact reproduction) is also
recorded and never shown to the planner.

## Cause check and candidates

- `check_cause(run, entry)` names one entry of a reproducing run's plan (`faults[0]`, `delays[2]`,
  `disconnects[0]`, indexes into the plan as submitted). The engine reruns the plan without it, with
  the same `S`. A removed delay falls back to the message's keyed default delay.
- **Confirmed** when the counterfactual run violates none of the contracts the incident violated.
  A confirmed cause ends the session.
- **Counterfactual confirmation rate** = confirmed / named.
- **Surviving candidates (ambiguity)**: after the session, the engine removes each entry of the
  first reproducing plan in turn, by the same rule. The candidates are the entries whose removal
  makes the failure go away. One means the log points to one cause; several means a single removal
  cannot tell them apart. Not counted in the budget. Alternative scenarios with different faults are
  not counted (WP9).
- **Named a hidden fault** (operator-only): whether the named entry is a fault of `P*`. For faults
  and delays, same message key and kind; for disconnects, overlapping intervals.

## Baselines, budget, end

- **Budget:** as in v2, 120 runs per session. `run_plan` and `check_cause` each use one, rejected
  calls included. At most 20 faults and disconnects per plan.
- **End:** the session ends at the first confirmed cause, at `finish`, or when the budget is used up.
- **Random:** plans drawn uniformly from the plan vocabulary. This differs from v2: with a fixed
  seed, the profile's random faults would give the same run every time. Message keys follow the
  Hypothesis strategy's distribution (half command traffic, half polls). Counts are uniform: faults
  `0..20`, disconnects in what is left, delays `0..10`.
- **Hypothesis:** `replayspect.hyp.plans`, as in v1.
- **Baseline cause naming:** the entries of the first reproducing plan in random order, one
  `check_cause` each, until one is confirmed. This gives the chance-level confirmation rate.
- Commands: `python3 -m replayspect incident baseline FILE --strategy random|hypothesis --runs 20
  --log-dir DIR`, then `incident summary LOG...` and `incident verify LOG...`.

## Preconditions

Each incident must pass two checks, run with `incident check`, before any trial:

- **Self-match:** the incident reproduces itself.
- **Correct implementation:** the correct implementation with the same `S` and `P*` does not
  reproduce it, and is told apart **by the log alone**. Matching contracts are not enough: the
  lines or the status sequence must differ.

A combination that fails the log check either gets a comparison rule that can show the defect, or
is left out. The tests show the case on the lift's published M5. It changes only what
`STATUS_REPLY` says, so with polls left out the correct implementation matches every line; the
status rule brings the defect back.

| Incident | Log | Self-match | Correct implementation: reproduces / told apart by log (lines matched) |
| --- | --- | --- | --- |
| A-1 | device | yes | no / yes (21/40) |
| A-2 | client | yes | no / yes (15/26) |
| B-1 | device | yes | no / yes (25/44) |
| B-2 | client | yes | no / yes (22/29) |

## Trial scope and pre-registration

Minimal trial, meant to show that the loop runs end to end on both systems:

- **Incidents:** one per system, each with two logs (device side, client side).
- **Per incident:** one LLM session; random and Hypothesis 20 runs each. Baselines cost seconds,
  so 20 runs give a distribution to place each LLM result on, not a single chance number.
- **Choice rule:** per system, the mutant or variant with the lowest random detection rate on the
  hidden-seed range, and its first listed seed. Fixed before any trial.
- **Fixed values:** tolerance 250 ms; polls not compared; `status_rule` off; budget 120; at most
  20 faults and disconnects. Client clock offsets were drawn once per log from 1–5 s with a fixed
  seed.

The operator's record fixes the rest before the first model call:

- incident files and their digests;
- the `describe` text digest per incident (`hashes.describe` in the session log header);
- model ID, client, Python and MCP versions;
- harness commit;
- cost cap: `--max-budget-usd 25` per session, 100 USD for the whole minimal trial.

The main trial (every incident and both logs) is registered separately, after this one.

LLM task text:

```
You have an MCP server named replayspect. Call describe first: it includes a partial log of a
recorded failing run. Use run_plan to find a fault plan that reproduces the log, using as few runs
as possible. Then use check_cause to name the plan entry that caused the failure. Use no other
tools. Call finish if you decide to stop without a confirmed cause.
```

## Results

Condition A (lift): the mutant list is published, and the run uses `--mutant`. Condition B
(turntable): the defect is not published, and the run uses `--variant`. The two are reported
separately and never pooled.

### Condition A: lift (published mutants)

| Incident | Log | Strategy | Reproduced (runs to first) | Candidates | Confirmed / named | Tokens in/out, USD | Named a hidden fault | Exact | Reproduced at 100 / 500 / 1000 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A-1 | device | LLM | yes (3) | 3 of 3 | 1 / 1 | 190k / 6.7k, 0.48 | yes | no | yes / yes / yes |
| A-1 | device | random ×20 | 0 of 20 sessions | – | 0 / 0 | 0 | – | 0 | 0 / 0 / 0 |
| A-1 | device | Hypothesis ×20 | 0 of 20 sessions | – | 0 / 0 | 0 | – | 0 | 0 / 0 / 0 |
| A-2 | client | LLM | yes (6) | 4 of 5 | 1 / 1 | 373k / 20.0k, 0.93 | yes | no | yes / yes / yes |
| A-2 | client | random ×20 | 0 of 20 sessions | – | 0 / 0 | 0 | – | 0 | 0 / 0 / 0 |
| A-2 | client | Hypothesis ×20 | 0 of 20 sessions | – | 0 / 0 | 0 | – | 0 | 0 / 0 / 0 |

### Condition B: turntable (unpublished defects)

| Incident | Log | Strategy | Reproduced (runs to first) | Candidates | Confirmed / named | Tokens in/out, USD | Named a hidden fault | Exact | Reproduced at 100 / 500 / 1000 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B-1 | device | LLM | yes (3) | 4 of 5 | 1 / 1 | 194k / 4.7k, 0.44 | yes | no | yes / yes / yes |
| B-1 | device | random ×20 | 0 of 20 sessions | – | 0 / 0 | 0 | – | 0 | 0 / 0 / 0 |
| B-1 | device | Hypothesis ×20 | 0 of 20 sessions | – | 0 / 0 | 0 | – | 0 | 0 / 0 / 0 |
| B-2 | client | LLM | yes (2) | 4 of 8 | 1 / 2 | 196k / 8.3k, 0.52 | yes | no | yes / yes / yes |
| B-2 | client | random ×20 | 0 of 20 sessions | – | 0 / 0 | 0 | – | 0 | 0 / 0 / 0 |
| B-2 | client | Hypothesis ×20 | 0 of 20 sessions | – | 0 / 0 | 0 | – | 0 | 0 / 0 / 0 |

Run on harness commit `6ac2191` (main after the WP4 merge), Claude Code 2.1.319, model
`claude-opus-5-5`, Python 3.14.4, mcp 2.3.0. Every LLM session passed the transcript audit (the four
bridge tools and one MCP server only, no skills, no hidden words) and `incident verify` (every
call replays). A separate isolation check session ran first and is not counted.

How to read the columns:

- **Candidates** "k of n": k entries of the first reproducing plan clear the failure when removed
  alone, out of n entries in that plan. k/n is the chance of confirming by naming an entry at
  random. Here it is 3/3, 4/5, 4/5 and 4/8, so a confirmed cause says little beyond the
  reproduction itself.
- **Tokens:** input counts cache reads and writes; the result event of the transcript.
- **Exact:** no session reproduced the trace digest. Every reproducing run matched the log's lines
  within 1 ms, so the tolerance did not decide any verdict (all four columns agree).

Where each LLM session falls in the baseline distribution. No baseline session reproduced any
incident within 120 runs (160 sessions, 19,200 runs), so every LLM session (2 to 6 runs) lies
outside the baseline distribution. As a measure of closeness, the best `n/m` a baseline session
reached (lines matched from the start, before the first mismatch):

| Incident | Random: best n/m, median (max) | Hypothesis: best n/m, median (max) | LLM: n/m per run |
| --- | --- | --- | --- |
| A-1 | 15 (33) / 40 | 15 (15) / 40 | 15, 15, **40** |
| A-2 | 11 (12) / 26 | 9 (10) / 26 | 9, 12, 26†, 12, 16, **26** |
| B-1 | 15 (15) / 44 | 8 (15) / 44 | 8, 15, **44** |
| B-2 | 10 (12) / 29 | 5 (10) / 29 | 12, **29** |

Bold: reproduced. †: every line matched but the run's contracts differed, and the planner was
told so ("the run differs in what the log does not show"). This is the indirect contract leak in
Limits; the session used it.

### Departures from the registration

- **LLM budget 100, not 120.** The MCP server's `--budget` default is 100, and the trial's server
  configuration did not set it. The baselines ran with 120. The `describe` text differs from the
  registered digest only in the budget field (checked for all four incidents). No LLM session came
  close to either limit: the most calls used was 7.
- **Cost:** the four sessions cost 2.38 USD (2.66 USD with the isolation check), far below the
  100 USD cap.

## Limits

- **Indirect contract leak.** The incident's contracts are not given. But a run whose log lines
  all match (`n = m`) and that still does not reproduce tells the planner its contracts differ. WP6
  replaces this with a symptom statement.
- **The clock offset is easy to recover.** In both systems the client sends its first command at
  time 0 and polls every second, which the protocol description states. So the offset can be read
  off the client-side log alone. The client-side log hides the device but does not make timing hard.
  Kept as is for this trial: cutting the log's start would change the design and the preconditions.
  Clock drift and irregular polling belong to WP5 (text log adapter).
- **What the logs give away.** Every message attempt is a line with its time: the device log shows
  when each resend arrived, the client log when each was sent and answered. With the protocol's
  fixed retry schedule, a missing or late attempt points to a drop, a delay or a disconnect
  directly. The LLM sessions read the plan off the log this way. Random and Hypothesis plans do
  not read the log, and matching 26 to 44 lines by chance is hopeless, so the gap measures reading
  the log, not reasoning about the defect.
- **Candidates** count single removals in the first reproducing plan only. Other fault combinations
  that give the same log are not explored.
- **Small samples.** One incident per system and one LLM session per log: this shows the loop
  works and gives first numbers, nothing more. The 20 baseline runs per incident place each LLM
  session against a chance distribution; they do not make one session a sample.
- **Turntable defects** were written with an AI model's help, so they may resemble what a model
  planner expects.
