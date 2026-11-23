# replayspect work order WP6/7d — the symptom judge, a claim's two checks, and one incident end to end

2026-11-23

This is an addition to `docs/work-order-v3.md`, after `docs/work-order-wp67c.md`. All of their principles and constraints apply. It has two parts, in this order: part A closes what testbed-07 showed (stages 0a and 0b); part B builds the last piece of WP6/7 and runs it once (stages 1 to 3).

**This order was written from `main` at `9c87f4e`.** Where it conflicts with what the code does, say so in the report of the stage concerned, before any work on it. It was amended once before stage 0a, after the first reading (#69): the candidates' names, two cases of stage 0a, the real logs, a turntable incident in stage 1's tests, and `check_cause`'s budget.

## Why

- **The loop of WP6/7 has never run.** Three blind groups in a row (testbed-05, 06, 07) measured what the contracts and the device comparison catch. The use the tool was planned for is another path: log → symptom → reproduction → claim → both engine checks → a person's confirmation. `docs/work-order-v3.md` makes one run of it the third "done when" of WP6/7, and WP8 and WP9 wait on it.
- **Today an incident needs a violated contract to be judged.**
  - `incident.wp4_match` asks for the same set of violated contracts. Its module documentation says the symptom judge replaces that.
  - `BridgeSession.check_cause` confirms an entry when the counterfactual run violates none of the incident's contracts. When the incident violates none, every entry is confirmed. `bridge.necessary_entries` has the same rule.
  - The first candidate v3 names for the loop is an incident of that kind: a defect no contract catches.
- **A claim is still prose.** `describe_defect` records a text and ends the session. `claim check` exists (`docs/claims.md`) but nothing submits to it, and the second check of v3 (which items of the reproducing plan are necessary) is computed after a session, by the contract rule above.
- **testbed-07 left two things open** (`docs/backlog.md`): the first mismatch chosen inside one millisecond (S17), and three gap candidates of the generic set (S15, S20, S09).

## What exists already

- `incident.py`: the incident file (with a one-line `symptom` sentence written by the operator), the planner's view, `wp4_match`, `check_preconditions`.
- `bridge.py` and `mcp_server.py`: `BridgeSession` with `describe`, `run_plan`, `check_cause`, `name_defect` or `describe_defect`, `finish`; the modes `full`, `answer_only`, `symptom_only`; the baselines (`incident baseline --strategy random|hypothesis|reconstruct`).
- `shrink.py`: removal of plan items while one target contract is still violated.
- `claim.py`: `claim check` on traces and device logs, with a normal corpus of files and simulator seeds.
- `contracts/generic/`: G1, G2 (three contracts), G3, G4, G5, G6, G6b, P1, and the two bindings. `contracts/turntable.v0.yaml` and the lift files. **All of them stay as they are until a stage below says otherwise.**
- **Real device logs.** All of testbed-07 is development data from now on: its 24 slots, and the 24 turntable sessions of WP6/7c stage 1. These are on the development machine. The lift's logs (testbed-01 to 06, the defect runs, the 218 no-defect logs) are not there today; the operator provides them (see "The real logs" below).

## Stage 0a — the first mismatch inside one millisecond

Make the device comparison report S17's first mismatch on the request the log shows first.

- **What happens today** (`devicelog.conform`): the earliest unmatched model event and the earliest unmatched device event are taken by time. When the two are at the same time and on different requests, the model's side is reported and the device's is dropped. In S17 both were at 3000 ms: the device's `motor_stop r-0001`, first in the log, and the model's `STATUS_REPLY s-0003`.
- **The rule to reach:** inside one millisecond, the first mismatch is decided by the order of the log's lines, not by which side an event is on. A model event with no logged line in that millisecond has no place in that order; say in the PR where the rule puts it and why.
- **Only an exact tie changes.** Two candidates at different times, also inside the 2 ms window, are decided by time as today.
- **An order difference and an unmatched event at the same time:** on the same request, the unmatched event is reported, as today. On different requests, the order of the log's lines decides, as for any other tie.
- **Nothing else changes.** Verdicts (`conforms`, `differs`) and the count of unmatched events stay the same on every log.
- **Tests first,** on simulator-made device logs:
  - S17's shape (an early output of one request, and in the same millisecond a changed poll reply of another);
  - the same with the two lines in the other order in the log;
  - an output missing on one request while another request has an extra line in the same millisecond.
- **Development check on the real logs,** reported in the PR:
  - S17's first mismatch is now on r-0001;
  - every other real log (the no-defect logs of both boards, the defect runs of testbed-03 and 04, the blind slots of testbed-04 to 07): list every first mismatch whose request or shown event changes. If there is none, say that it was run and found none.
- Documents: `docs/device-log.md`, the changelog, `CLAUDE.md`, and the backlog row (removed, with the PR number in the changelog).

Stop and report.

## Stage 0b — the start side of an action: candidates for the generic set

Run the candidate loop of WP6/7b stage 3 once more. No new code, no new kind.

**The candidates.** Write each by hand for the turntable and for the lift, under `docs/notes/generic-contracts-rev2/`, with `grade: generic` and a `source` that names the rule.

| Candidate | In words | Kind |
| --- | --- | --- |
| P2 | the effect that ends the action only after the effect that starts it, per request id | `only_after` |
| P3 | no effect that starts the action after the state change that starts it, per request id | `never_after` |
| P4 | the state change that starts the action only after the effect that starts it, per request id | `only_after` |

- The names follow P1, the proposal of the first note. S1 and S2 are taken: they are the scoring's names.
- P2 and P3 are the backlog's two examples. P4 is one rule for the same ground: it would speak at the start of the action, where P2 can only speak when the action ends, 3 s later.
- **P3 and P4 need a role the bindings do not have:** the states of an action in progress (`TURNING_TO_*`; `MOVING_UP`, `MOVING_DOWN`). Name it in the note. Do not add it to a binding in this stage.
- **The refusal reason (S09) stays a recorded gap.** Do not build an expression for it.

**Checks,** with `claim check`:

- **Incidents:** testbed-07's S15 and S20 device logs, each with its model result (`device --out`, after stage 0a).
- **No false positive:**
  - simulator seeds 0–999 of the correct turntable and of the correct lift;
  - the real no-defect logs: the lift's 218, the turntable's 24 development sessions and testbed-07's five unchanged slots;
  - testbed-07's two slots whose change did not act, reported apart.
  - One violation there fails the candidate as written. Report it and do not bend the candidate to pass.
- **What each candidate catches,** as a development check:
  - of testbed-07's 17 acting slots: which, at what time, and whether on the request and at the time of the truth;
  - of the lift's acting blind slots (testbed-04, 05, 06) and the lift's simulator mutants on seeds 0–999: which;
  - for each of these, whether an existing generic rule or a contract of the protocol's own file already fires there.

**Report in an operator note,** `docs/notes/generic-contracts-rev2.md`, in the form of `docs/notes/generic-contracts.md`:

- each candidate: its two instances, the checks' output, and a recommendation (keep, drop, or covered by another candidate);
- whether the protocol documents state the order P3 and P4 rely on. Quote the lines. Whether a sentence states an order is the operator's reading;
- **how the generic set changes when a rule is added.** `rules.yaml` has no revision today, and reports name it by sha256. Give the choices (a new rules file beside the old one, or the old one changed in place) and what each does to the reproduction of testbed-07's numbers. Recommend one.

**The operator confirms or drops each candidate and decides the form.** After that only, in its own PR: the rules, the role in both bindings, the tests of WP6/7b stage 4 (the rules already there expand to the same contracts as before; no false positive on seeds 0–999 of both systems), `contracts/generic/README.md`, the changelog, `CLAUDE.md`, the README status and the backlog row.

Stop and report.

## Stage 1 — the symptom file and its judge

A symptom says what was seen, in a form the engine can judge. It replaces "the same set of violated contracts" wherever a run is compared with an incident.

**The file** (`replayspect.symptom/1`, YAML; `docs/symptom.md` describes it):

- **`events`:** the events that must occur, in this order. Other events may come between them. An item is an event pattern in the contract language's form (`client.recv(DONE)`), with optional `req_id`, optional `data` fields that must be equal, and an optional time in the log's clock.
- **`absent`:** events that must not occur. An item is a pattern with optional `req_id`, and optionally the listed events it lies between (after one, before another). With no bound it covers the whole run. v3's text has required events only. The symptom sentences of bridge-02 are mostly about something that did not come, so absence is in the file.
- **`tolerance`:** for the times given. Default: the incident's tolerance.
- **Outcome level, as far as a loader can hold it:** an item may name the client's events and the device's `effect` events, nothing else (what the controller logged and what a person saw move). The loader refuses the device's `recv`, `send` and `state`, the link's events, any contract id and any unknown key.
- Anything not listed is free.

**The judge** (the engine; no model takes part):

- A trace matches when every listed event can be assigned to an event of the trace in order, each given time within the tolerance, and no `absent` item occurs inside its bounds. Decide whether an assignment exists; do not stop at the earliest candidate.
- It reports: matched or not, n of m listed events matched, the first item not matched, and each `absent` item that occurred, with the event.
- Same inputs, same bytes.

**Where it is used:**

- **A command:** `replayspect symptom check SYMPTOM TRACE` (text, and JSON with `--out`), with the clock offset as an option.
- **The incident file** may carry a symptom file's content, so that the incident's sha256 covers it. The one-line sentence stays.
- **For an incident with a symptom file:**
  - a run reproduces the incident when the compared lines, their times and the status rule hold as today, and the run matches the symptom. The contract sets are still reported, and no longer decide;
  - `check_preconditions` also asks that the hidden run matches its symptom and that the correct implementation, with the same seed and plan, does not;
  - `check_cause` confirms an entry when the counterfactual run no longer matches the symptom. `necessary_entries` follows the same rule;
  - `run_plan` tells the planner both results: the contracts its run violated, and the symptom match (n of m, the first item not matched). The planner is shown the symptom file beside the sentence.
- **For an incident without one, nothing changes:** the same verdicts, the same `describe` text and digest, and a session log written before this stage verifies as before. Tests hold each of these.

**Tests first:** the loader's refusals; order, times and absence, each alone and together; a case where the earliest candidate is the wrong assignment; one simulator incident per published lift mutant with a hand-written symptom (the hidden run matches it, the correct implementation does not); one incident that violates no contract (a variant kept under `tests/`), where `check_cause` now tells a necessary entry from a superfluous one. **Make that one a turntable incident,** and run it through a bridge session and through the reader as well: no test has a turntable incident today, and stage 3 must not be the first use.

Documents: `docs/symptom.md`, `docs/trace-schema.md` (where it names the symptom judge), `docs/design-v0.md`, the changelog, `CLAUDE.md`, the README status.

Stop and report.

## Stage 2 — a claim is submitted, and the engine checks it

The answer to "which defect" becomes a claim with a candidate contract. Both checks run on submission. Neither is a tool the planner chooses to call.

- **A new call, `submit_claim`,** in a session configured for claims (modes `full` and `answer_only`). It takes:
  - the claim: trigger and effect, in one sentence;
  - one candidate contract in the existing language, with `grade` and `source` as `claim check` asks;
  - in `full`, the index of a reproducing run of the session. In `answer_only` the given plan is used.
- **Check 1, the candidate against the data** (the rules of `claim check`, in the same words):
  - incidents: the hidden run's trace and the reproducing run's trace;
  - normal corpus: simulator seeds of the correct implementation, 0–999 unless the session's configuration says otherwise. The same corpus for every claim of a session.
- **Check 2, the plan's items:**
  - the engine first reduces the reproducing plan to one from which no single entry can be removed while the run still matches the symptom;
  - then it removes each entry of that plan in turn and reruns;
  - for each entry it reports whether the symptom still matches and whether the candidate is still violated, and on which request;
  - an entry is **necessary** when the symptom no longer matches without it.
  - This check reports. It gives no verdict: an entry's removal can move the failure to another request, and then the symptom stops matching while a right candidate is still violated.
  - For an incident without a symptom file, "matches the symptom" reads "violates one of the incident's contracts", as today.
- **Neither check uses the planner's budget.** Claims are limited instead: `max_claims`, default 3. The session ends at the first claim that passes check 1, or when the claims are used up. `check_cause` stays a call the planner chooses, and still uses one run of the budget.
- **What the planner is told:** the verdict of check 1 with its reasons, and the table of check 2. About the hidden run it is told one status word and nothing else: no time, no request, no event. Its own runs are reported in full. The session log holds everything.
- **A candidate that cannot be loaded:** say in the PR whether it uses a claim, and hold it with a test.
- **A session not configured for claims is unchanged:** the same tools, the same `describe` text and digest.
- **Baselines** (reader, random, Hypothesis) submit no claim.
- `incident summary` gains: claims submitted, the claim that passed if any, and the number of necessary entries.
- **Tests first,** including the isolation test: with a marked variant, no output of `submit_claim` contains the mark, the seed, the hidden plan or a time that is not in the view.

Documents: `docs/claims.md` (a section on submission and check 2), `docs/symptom.md`, the changelog, `CLAUDE.md`, the README status.

Stop and report.

## Stage 3 — loop-01: one incident, from the log to a confirmed contract

One incident, one planner session. This is a check that the path holds together. It is not a measurement.

**Preparation,** by the experimenter, in the operator's directory outside the repository:

- **The incident:** a hidden run of the turntable variant whose gap is recorded in the operator's private WP3 notes (v3, WP6/7, "First candidate for the loop"). It is not described in the repository before the result is published.
  - a new seed, outside 0–999 and outside the seeds used before;
  - a plan inside the planner's plan space;
  - the view that passes `check_preconditions`.
- **Can the claim be stated at all?** Check privately that one or more candidates in the existing language pass check 1 on this incident. If none does, stop and tell the operator, outside the repository. The operator then names another incident or ends the stage. Do not add a kind.
- **The symptom** is written by the operator from a listing of the hidden run's client events and device effects, and nothing else of that run. The experimenter makes the listing and does not write the symptom. The advisor checks it against the listing.
- **Registration,** `docs/experiments/loop-01-preregistration.md`, before any session, short:
  - the harness commit, and the sha256 of the incident file, the symptom file and the `describe` text;
  - the budget (120), `max_claims` (3), the normal seeds (0–999), the model, and the isolation procedure of bridge-02;
  - the order below, and what is reported.

**The order,** as registered:

1. The rule-based reader runs first (`incident baseline --strategy reconstruct`). Random and Hypothesis run with the same budget. The three report reproduction only.
2. If the reader reproduces the incident, the planner session is `answer_only` with the reader's plan, reduced as in check 2. If not, it is `full`.
3. One isolated planner session, configured for claims.
4. The session log goes to the operator: the claim, check 1, check 2. **The operator confirms or drops the claim.**
5. If confirmed, in its own PR: `contracts/turntable.v0.rev2.yaml` (v0 unchanged, plus the contract with its `grade` and `source`), the oracle, and no false positive on seeds 0–999 and on the turntable's real no-defect logs.
6. **The last step of the path:** the hidden run, replayed with the rev2 file, violates the new contract. Report the request and the time, beside the symptom's.

**Results,** `docs/experiments/loop-01.md`:

- one row per step of the path: what went in, what came out, who or what decided;
- the session's input and output tokens, and the cost;
- the baselines' reproduction;
- departures from the registration, with the session id;
- whether the variant is published with the result is the operator's decision. Until then the result names no mechanism.

**If no claim passes,** that is the result. A candidate written afterwards by the operator or the advisor is reported as that, and not as the loop's.

Stop and report.

## The real logs

- **The operator provides the lift's real logs,** or says that they are lost. Do not search the Orin for them.
- **A corpus is named by its list sha256** wherever an earlier note recorded one (the 218 no-defect logs: `docs/notes/contract-candidates-rev4.md`, `docs/notes/generic-contracts.md`). Check a provided corpus against it and report the result.
- **Work may start without them.** Tests are made from simulator logs, and the checks run on what is there.
- **A check on a corpus that is not there is reported as not run,** by name, in the PR body and in the note. It is never left out silently and never replaced by another corpus under the same name.
- **The operator decides** whether a PR whose check is incomplete waits for the logs or goes on without them.

## What may be claimed afterwards

- Stage 0a is checked on development data.
- A rule added by stage 0b is unmeasured until a new blind group. Its counts on testbed-07's slots are a development check: the candidates were written after the slots were known.
- loop-01 is one incident and one session. "The path ran once, with these results at each step" may be claimed. No rate may be claimed.
- A contract confirmed in loop-01 catches the incident it was written from. What else it catches is unknown.

## What is left of WP6/7 after this order

- `grade: stated` on C1–C8 of `contracts/lift.v0.yaml` and `contracts/turntable.v0.yaml` (the first "done when" of WP6/7), and the grades `mined` and `symptom`.
- The contract id, grade and source on the first line of a violation report.
- A symptom drafted by a model from a log. In loop-01 the operator writes it.
- The loop on a real log. loop-01 is a simulator incident.
- Module and system contract folders.

## Not in this order

- A new blind group, and any rule for its draw.
- WP8 (the provider interface, the task description in pieces) and WP9 (ranking).
- A third system, new mutants, new firmware, any run on the boards.
- A new contract kind, a new grade, `answered_within`, an expression for the refusal reason, a transition miner.
- Any change to `contracts/` outside the two PRs named in stages 0b and 3.

## Constraints

- One stage per branch and PR. No stacking. The operator merges every PR.
- The report goes in the PR body. The advisor reviews on the PR from the code.
- Planner-visible files (the protocol documents, the plan format, every file in `contracts/`) name no defect, mutant, experiment slot or operator note.
- Hidden variants, incident files, seeds and session logs stay outside the repository until the operator publishes them. The blind materials of testbed-05, 06 and 07 that were not published are not copied into it. Real logs stay outside it.
- A result that was not checked is never reported as checked. Where the data is missing, say so and stop.
- No new dependency. Tests first. `git diff --check` and the full test suite before each PR.
