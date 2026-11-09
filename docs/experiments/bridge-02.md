# Bridge experiment 02 (WP4 main trial): from a partial log to the defect

Operator document. Do not give it to a planner.

The minimal trial ([bridge-01.md](bridge-01.md)) showed two things. A planner that reads the log
reproduces these incidents, and one that does not read it never does. And confirming a fault-plan
entry by removing it says little, because most entries of a reproducing plan are each necessary.
So this trial changes what is measured:

- **Reproduction** gets a baseline that reads the log without a model: the rule-based reader
  (`replayspect.reconstruct`, `incident baseline --strategy reconstruct`).
- **The question that counts is the defect**, not the plan entry: which defect in the
  implementation caused the failure.
- **The planner gets a symptom**, one line a person on site would report, instead of being left
  to infer which contracts failed.

All results are **explored**: a right answer is right in the model.

## Conditions

- **A (lift):** the defects are published. The planner names one id from the list
  (`name_defect`). An answer is right when that defect, run with the incident's seed and plan,
  reproduces the incident: the log cannot tell such defects apart (`incident.defect_class`). The
  chance level of a guess is the size of that class divided by 11.
- **B (turntable):** the defects are not published, and the run uses `--variant`. The planner
  describes the faulty behaviour (`describe_defect`). The operator scores each description against
  the defect record as right, partly right or wrong, with criteria fixed at registration.

A and B are reported separately and never pooled. Device-side and client-side logs are reported
separately too: on the device side the defect is often visible in the log itself, while on the
client side it has to be inferred.

## Strategies

| Strategy | Mode | Reproduces | Answers the defect | Per-session cap |
| --- | --- | --- | --- | --- |
| LLM alone | `full` | yes | yes | 6 USD |
| Rule-based reader | (baseline) | yes | no | none (no model) |
| Reader + LLM | `answer_only` | no: the reader's first reproducing plan is given | yes | 2 USD |
| Symptom only | `symptom_only` | no log at all | yes | 0.5 USD |
| Random, Hypothesis | (baseline) | yes | no | none |

- **Reader + LLM** runs only on incidents the reader reproduces. It measures the division of labour
  the design proposes: reproduce deterministically, and use a model only for the defect. Its
  tokens sit next to "LLM alone" in the results.
- **Symptom only** is the chance level of the defect answer once the symptom is known. A planner
  that reads the log must beat it to claim it read the defect off the log. Its input is the same
  for both logs of a run, so it runs once per run.
- Random and Hypothesis stay as auxiliary reproduction baselines (20 sessions each per log).

## What the planner sees (changes from bridge-01)

- `describe` adds the **symptom**. With condition A it adds the defect list.
- `run_plan` shows only the **logged participant's side** of the planner's own run, polls left
  out. The run's own link data stays (`k`, and for a received message `sent` and `delay`).
  Violations are given as contract, `req_id` and time, without details. Otherwise the other side's
  behaviour, and with it the defect, could be read off the planner's own runs; the minimal trial's
  defect remarks came from there.
- `check_cause` no longer ends the session. Its result is reported against chance: confirmed, next
  to k/n, where k entries of the n in the first reproducing plan clear the failure alone.
- The session ends at the defect answer or at `finish`. A used-up budget stops runs but leaves the
  answer open.

Session modes and tools (`python3 -m replayspect.mcp_server --incident FILE --mode MODE`):

- `full`: describe, run_plan, check_cause, name_defect or describe_defect, finish.
- `answer-only` (with `--given-plan FILE`, e.g. from `incident plan LOG --out FILE`): describe,
  the defect tool, finish.
- `symptom-only`: describe, the defect tool, finish.

With `--incident`, `--budget` defaults to 120, the registered value. The minimal trial ran on 100
by mistake. The operator's launcher also refuses a configuration whose budget differs from the
registered one.

## Symptom sentences

Written by the operator, one per hidden run, and the same sentence for both logs of a run. A
symptom states an outcome someone on site would see ("the lift moved twice", "the command never
completed"), never a mechanism ("after a retry", "a duplicate", "after refusing"). A mechanism is a
defect description, and in condition A it would let a planner pick from the list by the sentence
alone. The symptom-only sessions measure how far a sentence narrows the answer anyway.

The operator writes from a neutral field summary of each run: final states, commands that did not
finish or finished oddly, and their times, with no defect names. The summaries and sentences stay
outside the repository until publication; their digests are registered.

## Incident selection

- **Pool:** the hidden runs of the mutant measurement (seeds outside the 0–999 range), each with a
  device-side and a client-side log.
- **Reader result:** the reader is frozen at a commit before counting, and run once on the pool
  with budget 120. Its development set was kept apart, at other seeds. Incidents looked at while
  tuning it are excluded from selection.
- **Cells:** condition × side × (reader solves it, or not). Two logs per cell, by a seeded shuffle,
  so each condition has eight logs: four the reader solves and four it does not.
- **Filling a cell:** if a cell has too few logs, more runs are taken from the hidden seed range in
  listed order. If that is still not enough, the cell takes fewer logs, and the registration says
  so.

## Pre-registration

Before any model call, the operator's record fixes:

- the selected incidents and their digests;
- the symptom sentences and their digests;
- the `describe` digests per mode;
- the equivalence classes (condition A) and the scoring criteria (condition B);
- model ID, client, Python and MCP versions, and the harness commit;
- the caps above, and 120 USD for the whole trial.

## Results

Run 2026-11-10. 35 LLM sessions counted (36 registered; one invalid and rerun, see Departures),
Claude Code 2.1.319, model `claude-opus-5-5`, Python 3.14.4, mcp 2.3.0, hypothesis 6.170.15.
Harness `02686ca` for the first 20 sessions and `215775c` (one line, Departures) after that; every
`describe` digest is the registered one. Every counted session passed the transcript audit and
`incident verify`. Baselines per log: the reader once (frozen at `93098bc`; same results at the
harness commits), random and Hypothesis 20 sessions each, budget 120.

Logs are named by run (R01-R12, neutral ids from the operator's field summaries) and side; the two
logs of a run share its symptom. Condition B names the turntable defect only as X or Y. Seeds,
incident files and the defect records stay outside the repository.

### Condition A: lift (published defects)

| Log | Side | Reader @120 | LLM alone: reproduced (runs) | LLM alone: defect | Reader+LLM: defect | Symptom only: defect | Chance (class) | check_cause confirmed/named vs k/n | Tokens in/out, USD: alone / reader+LLM / symptom | Random | Hypothesis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R03 | client | yes (91) | no (3 calls) | M4 ✓ | M4 ✓ | M4 ✓ | 1/11 (M4) | - | 132k/2.4k, 0.32 / 63k/0.7k, 0.25 / 15k/1.2k, 0.06 | 0/20 | 0/20 |
| R06 | client | yes (42) | yes (3) | M11 ✓ | M11 ✓ | M1 ✗ | 1/11 (M11) | - | 177k/4.8k, 0.40 / 64k/1.3k, 0.26 / 16k/2.7k, 0.10 | 0/20 | 0/20 |
| R07 | client | no | yes (2) | M10 ✓ | - | M10 ✓ | 1/11 (M10) | - | 147k/9.2k, 0.51 / - / 15k/1.3k, 0.06 | 0/20 | 0/20 |
| R08 | client | no | yes (2) | M4 ✓ | - | M4 ✓ | 1/11 (M4) | - | 138k/3.7k, 0.36 / - / 14k/0.8k, 0.05 | 0/20 | 0/20 |
| R01 | device | no | yes (1) | M10 ✓ | - | M10 ✓ | 1/11 (M10) | - | 99k/2.1k, 0.30 / - / 14k/0.9k, 0.05 | 0/20 | 0/20 |
| R02 | device | yes (58) | no (2 calls) | M9 ✓ | M9 ✓ | M2 ✓ | 2/11 (M2,M9) | - | 101k/2.3k, 0.33 / 67k/1.7k, 0.30 / 15k/1.6k, 0.07 | 0/20 | 0/20 |
| R04 | device | yes (114) | yes (6) | M11 ✓ | M11 ✓ | M2 ✗ | 1/11 (M11) | - | 299k/6.2k, 0.50 / 67k/0.9k, 0.27 / 15k/1.9k, 0.08 | 0/20 | 0/20 |
| R05 | device | no | no (2 calls) | M9 ✓ | - | M9 ✓ | 1/11 (M9) | - | 102k/4.5k, 0.36 / - / 15k/2.0k, 0.08 | 0/20 | 0/20 |

### Condition B: turntable (unpublished defects)

| Log | Side | Reader @120 | LLM alone: reproduced (runs) | LLM alone: defect | Reader+LLM: defect | Symptom only: defect | check_cause confirmed/named vs k/n | Tokens in/out, USD: alone / reader+LLM / symptom | Random | Hypothesis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R09 (X) | client | yes (79) | yes (2) | right | right | partly | - | 131k/2.7k, 0.32 / 64k/1.4k, 0.26 / 19k/4.8k, 0.16 | 0/20 | 0/20 |
| R10 (Y) | client | no | no (4 calls) | right | - | partly | - | 192k/8.7k, 0.52 / - / 16k/1.5k, 0.07 | 0/20 | 0/20 |
| R11 (X) | client | yes (38) | yes (1) | right | right | partly | - | 98k/1.7k, 0.29 / 65k/1.5k, 0.27 / 18k/3.5k, 0.13 | 0/20 | 0/20 |
| R12 (Y) | client | no | yes (3) | right | - | partly | - | 186k/6.2k, 0.45 / - / 15k/1.0k, 0.06 | 0/20 | 0/20 |
| R09 (X) | device | no | no (2 calls) | right | - | partly | - | 101k/1.5k, 0.29 / - / 19k/4.8k, 0.16 | 0/20 | 0/20 |
| R10 (Y) | device | yes (13) | yes (2) | right | partly | partly | 0/1 vs 2/7 | 192k/6.2k, 0.46 / 69k/1.5k, 0.29 / 16k/1.5k, 0.07 | 0/20 | 0/20 |
| R11 (X) | device | no | yes (1) | right | - | partly | - | 103k/1.4k, 0.29 / - / 18k/3.5k, 0.13 | 0/20 | 14/20 (median 55.0) |
| R12 (Y) | device | yes (6) | yes (2) | right | right | partly | - | 148k/3.0k, 0.37 / 70k/1.0k, 0.28 / 15k/1.0k, 0.06 | 0/20 | 1/20 (median 108) |

How to read the columns:

- **Reader @120:** the rule-based reader, once per log; runs to the first reproduction.
- **Defect (A):** the named id; ✓ when it is in the incident's equivalence class (Chance column:
  class size of 11, and the class).
- **Defect (B):** blind score against the defect record by the registered criteria: right, partly
  (partly right), wrong, no answer. "Partly right" is reachable from the symptom; "right" needs the
  trigger, which only the log gives (registered interpretation rule).
- **check_cause** "confirmed/named vs k/n": k entries of the n in the first reproducing plan clear
  the failure alone, the chance of confirming by naming one at random.
- **Tokens:** input counts cache reads and writes; the transcript's result event. Reader, random
  and Hypothesis use no tokens.
- Random and Hypothesis: sessions that reproduced, of 20, with the median runs to reproduction.

### What the results show

**Condition A.**

- Defect: LLM alone 8/8, reader + LLM 4/4, symptom only 6/8, against a chance level of 1/11 (2/11
  on R02). The symptom sentence and the published defect list nearly decide the answer without the
  log. The log changed the answer only on the two M11 runs (R04, R06), where the symptom-only
  session named another defect. Condition A therefore shows reading the defect off the log on two
  logs at most.
- Reproduction: LLM alone 5/8 in 1 to 6 runs; the reader 4/8 in 42 to 114 runs; random and
  Hypothesis 0 of 20 on every log.
- Three LLM-alone sessions answered without reproducing (R03, R02, R05). All three answers are
  right, and the symptom-only session was right on the same runs.

**Condition B.**

- Defect: symptom only partly right on all 4 runs (8 logs); LLM alone right on 8/8; reader + LLM
  right on 3/4 and partly right on 1 (R10 device, where the answer took an entry of the given plan
  as the trigger). This is the outcome the registered interpretation rule predicts: the symptom
  gives the faulty outcome, and the trigger came from the log. With the two boundary scores (see
  Limits) counted as wrong instead, the outcome is the same.
- Reproduction: LLM alone 6/8 in 1 to 3 runs; the reader 4/8 in 6 to 79 runs. Hypothesis reproduced
  R11 device in 14 of 20 sessions (median 55 runs) and R12 device in 1 of 20; random 0 everywhere.
- LLM alone answered right on both logs it did not reproduce (R10 client, R09 device).

**Both conditions.**

- Reproduction: the LLM reproduced 11 of 16 logs, the reader 8 (half, by selection). Both: 6; the
  LLM only: 5; the reader only: 2 (R03 client, R02 device); neither: 3. The reader is not a
  replacement for the model, and the two solve partly different logs.
- Division of labour: on the logs the reader reproduces, reader + LLM answered as well as LLM alone
  in condition A (4/4) and on 3 of 4 in condition B, at 0.25 to 0.30 USD a session against 0.29 to
  0.50 USD for LLM alone on the same logs. In condition A two of those four answers were also
  reachable from the symptom alone (R02, R03).
- `check_cause` was called once in 16 full sessions (R10 device: not confirmed, 0/1, against 2/7).
  With a defect question to answer, the counterfactual check was left out. A design that requires
  the check before naming a cause has to run it itself, not leave it to the planner.
- Cost: 9.25 USD for the sessions (including the invalid one, 0.04 USD) and 0.65 USD for isolation
  and limit checks, 9.90 USD of the 120 USD cap. No session reached its cap.

### Departures from the registration

The operator's record lists each one in full; in short:

1. **One session invalid: input truncated by the client.** Its `describe` (52,169 characters)
   exceeded Claude Code's MCP output limit; the client replaced it with a notice, and the session
   ended with no answer. The run of sessions stopped as registered.
2. Raising `MAX_MCP_OUTPUT_TOKENS` alone did not help: the client saves any MCP text result over
   50,000 characters to a file whatever the variable says (check session).
3. **The harness changed by one line** (PR #11, `215775c`): the bridge `describe` tool declares
   `anthropic/maxResultSizeChars: 200000`. All 36 registered `describe` digests are unchanged, and a
   check session received the full text.
4. Settings by session: the first 20 sessions on `02686ca` with the client's default limits (each
   received `describe` in full); the rest on `215775c` with `MAX_MCP_OUTPUT_TOKENS=100000`.
5. The invalid session was rerun as the last session, same incident, mode, given plan and cap.
6. One session was flagged by the audit for the word "reasoned" (a test plan's name matched without
   case); nothing hidden was in the transcript. Recorded as an audit false positive, session valid,
   result used.
7. Three audit words that also occur in plain English were made exact matches (that plan name, the
   incident file name pattern and the incidents path). All earlier sessions pass the new list,
   except the invalid one. The seed, digest, defect id and file name checks did not change.
8. The blinding script was fixed before use (it now leaves out the invalid session; a helper was
   defined after its first use). The procedure did not change.
9. **Who scored condition B.** The design says the operator scores. The scores are by the
   operator's AI advisor, who did not know the conditions or the mapping and saw only the blinded
   answers and the criteria. The operator reviewed all 16 scores and adopted them.

## Limits

- **Symptoms are written by the operator,** who knows the defects. The rule above and the
  symptom-only control bound the leak; they do not remove it.
- **Condition A was too easy for the defect question.** The symptom sentence with the published
  one-line defect list gave 6 of 8 answers without the log. The operator's sentences were fairly
  specific, which is part of it. The defect result in condition A rests on two logs.
- **Symptom sentences group by defect.** The two runs of a defect read alike, so the symptom-only
  answers reflect that grouping, not eight independent guesses.
- **The defect descriptions were scored by an AI.** The condition B scores are the AI advisor's
  blind scores, adopted by the operator after review: one model's answers judged by another.
- **Condition B scoring is a judgement** against the defect record, by registered criteria. Two
  scores sit on a boundary, both symptom-only answers. R09: one sentence meets both elements, but
  the answer's first claim contradicts the trigger; scored partly right by the first-candidate rule.
  R12: matches the registered example of "partly right" word for word, but in spirit points at
  another mechanism and is close to wrong; scored partly right by the letter. Neither changes the
  outcome.
- **The style of an answer may give the condition away.** Blinding hides the condition, but
  symptom-only answers tend to be shorter and more general.
- **Answers without reproduction.** Five LLM-alone sessions answered without reproducing the
  incident. All five answers were right, and in condition A the symptom alone gave the same three.
  An answer is not checked against a reproduction in this trial.
- **The reader is one rule set.** A stronger reader would solve more incidents. "Not solved"
  means not solved by these rules within the budget, not unsolvable.
- **Small samples.** 8 logs per condition, one LLM session per log and strategy; reader + LLM on 4
  logs per condition.
- **The turntable defects were written with a model's help,** so they may resemble what a model
  planner expects.
