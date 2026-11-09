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

## Limits

- **Symptoms are written by the operator,** who knows the defects. The rule above and the
  symptom-only control bound the leak; they do not remove it.
- **Condition B scoring is a judgement** against the defect record, made by the operator.
- **The reader is one rule set.** A stronger reader would solve more incidents. "Not solved"
  means not solved by these rules within the budget, not unsolvable.
- **The turntable defects were written with a model's help,** so they may resemble what a model
  planner expects.
