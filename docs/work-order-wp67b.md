# replayspect work order WP6/7b — output order in the device comparison, one candidate, and the generic set

2026-11-15

This is an addition to `docs/work-order-v3.md`, after `docs/work-order-wp67a.md`. All of their principles and constraints apply. It has two parts, in this order: part A closes what testbed-06 showed (stages 1 and 2); part B starts the generic contract set of WP6/7 (stages 3 and 4).

## Why

testbed-06 (`docs/experiments/testbed-06.md`) left three things open.

- **The device comparison missed two changes** (S15, S19). Both reorder the outputs of one request inside one millisecond. `conform` matches a model event to a logged event with the same signature inside a time window and never compares order. Prediction 5, the claim of the method, did not hold on these two slots.
- **One of the two has a contract candidate** the language can already state: `DONE` only after the arrival state (the document's "Proposals").
- **The lift contracts keep gaining lift-specific rows.** Three blind groups gave 0 of 4, 7 of 12 and 11 of 18 for the contracts alone, and each group found one or two more gaps of this one protocol. Before another revision or another blind group on the same firmware, the question is which rules do not depend on the lift at all. `docs/work-order-v3.md` already names them: the generic library.

## What exists already

- `replayspect device` and `conform` (`src/replayspect/devicelog.py`), with the same-millisecond switch for a timer and an input (`same_ms`).
- Ten contract kinds, provenance keys, `claim check` (`docs/claims.md`), with `--system`.
- `contracts/lift.v0.yaml`, `lift.v0.rev2.yaml`, `lift.v0.rev3.yaml` and `contracts/turntable.v0.yaml`. **All four are frozen.**
- An event pattern without names (`device.send`) matches any name.
- Real device logs on the development machine: 218 with no defect (the 213 of #55 and testbed-06's five unchanged slots), the defect runs of testbed-03 and 04, and the blind slots of testbed-04, 05 and 06. All of testbed-06 is development data from now on.

## Stage 1 — the order of one request's outputs

Make the device comparison see what S15 and S19 did.

- **The rule.** For one request id, the logged events that matched model events keep the model's order. Compare order only among events with the same `req_id`. Do not compare order across request ids: two inputs in one millisecond may be taken in either order, and the module documentation says so.
- **The first mismatch.** An order difference is a mismatch at the time of the first logged line that is out of place, on that request. The first mismatch of a log is the earliest of the two kinds (an unmatched event, or an order difference). The text output says it is an order difference and shows both orders; the JSON tells the two kinds apart.
- **A switch,** as for `same_ms`: `conform` can be told to ignore order, so an analysis can show what the rule changes. The tool compares order by default.
- **Defect models** (`--models`) use the same rule.
- **Partial declarations:** only matched events are compared for order. Nothing new is inferred from absence.
- **Tests first,** on simulator-made device logs: the three arrival lines in each wrong order, a reordered pair on another request in the same millisecond (no mismatch), and a log where both kinds of mismatch occur (the earlier one is reported).
- **Development check on the real logs,** reported in the PR:
  - no mismatch on any of the 218 no-defect logs. If there is one, do not widen the rule to hide it; report the log and stop;
  - S15 and S19 now differ, with the first mismatch at the truth's time and request (3054 ms and 3055 ms, r-0001);
  - no verdict and no first mismatch changes on any other real log (testbed-03 and 04 defect runs, the blind slots of testbed-04, 05 and 06). List every change, if any.
- **Documents:** `docs/device-log.md` ("When events match"; Limits), the module documentation, the changelog, `CLAUDE.md` and the README status. The result documents of past experiments are not rewritten.

Stop and report.

## Stage 2 — the candidate "DONE only after the arrival state"

Run the existing loop once more. No new code.

- **The candidate:** `only_after`, `event: device.send(DONE)`, `after: device.state(UP|DOWN)`, `per: req_id`, with `grade` and a `source` citing the protocol document's lines.
- **`claim check`:**
  - incidents: testbed-06's S19 and S15 device logs, with the stage-1 model result;
  - normal corpus: the 218 real no-defect logs and simulator seeds 0–999 of the correct lift.
- **Also report,** as a development check: on which other blind slots (testbed-04, 05, 06) and for which simulator mutants (seeds 0–999) it fires, and whether it ever fires where C10 does not.
- **The motor's direction (S06)** stays a recorded gap. Do not build an expression for it.
- Report in an operator note, `docs/notes/contract-candidates-rev4.md`, in the form of the rev3 note. **The operator confirms or drops the candidate.** Whether the document's sentence states an order is the operator's reading.
- **After confirmation only,** in its own PR: `contracts/lift.v0.rev4.yaml` (rev3 unchanged, plus the contract), the oracle, the per-mutant table on seeds 0–999, and the coverage note's row.

Stop and report.

## Stage 3 — the generic rules, as plain contracts first

Before any mechanism, find out which rules survive. Write each rule by hand for the lift and for the turntable, in the existing language, and check them.

**The rules.** This list is fixed here. Add a rule only as a proposal in the note.

| Rule | In words | Lift contract it generalizes |
| --- | --- | --- |
| G1 | at most one effect of each name per request id | C1 |
| G2 | per request id and reply role (acknowledgement, final answer, poll reply), the device sends no more replies than it received requests | C7, C12, C13 |
| G3 | the two final answers exclude each other, per request id | C8 |
| G4 | the device sends nothing for a request id it has not received | none |
| G5 | no acknowledgement for a request id after its final answer | C14 |
| G6 | the final answer of success only after the effect that ends the action | C10 |
| G7 | the state changes only along transitions seen in normal runs | C3 (declared, not mined) |
| G8 | no effect from a reply that arrives after the client gave up | none |

- **G7 and G8:** say in the note whether the language can state them and what it would take. Do not build a miner or a new kind.
- **Candidate files** go under `docs/notes/generic-contracts/`, not under `contracts/`: one file per system. They need a grade: add `generic` to the loader's grades, with a `source` that names the rule. Decide the `source` form in the PR and document it. It must still pass the word scan of `contracts/` when the rule moves there in stage 4: that scan forbids `found`, the notes path and any experiment, defect or operator word, so the source names the rule and nothing else.
- **Checks,** with `claim check` (`--system` for the turntable):
  - **no false positive:** simulator seeds 0–999 of the correct lift and of the correct turntable, and the 218 real no-defect lift logs. One violation there fails the rule as written; report it and do not bend the rule to pass;
  - **what each rule catches:** for the lift's simulator mutants M1–M11 on seeds 0–999, a table of rule by mutant;
  - **the generic set alone on the blind slots:** of the acting slots of testbed-04 (4), testbed-05 (12) and testbed-06 (18), how many the generic rules catch with no lift contract, beside the lift contracts' count on the same slots. This is a development check, not a measurement: the rules were written after the slots were known. Write it that way everywhere.
- **Report in an operator note,** `docs/notes/generic-contracts.md`:
  - each rule: its two instances, the checks' output, and a recommendation (keep, drop, or needs something the language lacks);
  - **what a system must declare** for the rules to be written once: which messages are requests, acknowledgements, final answers of success and of failure, polls and their replies, and which effects start and end an action. Propose the form (a roles section per protocol, expanded into the existing kinds; no new kind; the judge unchanged);
  - **what the turntable can and cannot show.** Its protocol has the lift's shape, with other names. Passing on both is weak evidence that a rule is generic. Say what a protocol of a different shape would have to be to test it (for example no acknowledgement, a session, a heartbeat). A proposal only: do not write a new system.
- `claim check` may be extended only where a parameter is missing. Anything larger: stop and ask.

Stop and report. **The operator decides which rules go on and approves the form.**

## Stage 4 — the generic library

After the operator's decision, and only for the rules kept.

- `contracts/generic/`: the rules written once, against roles. Each system binds the roles. The loader expands them into contracts of the existing kinds, with `grade: generic`.
- **The judge does not change.** The proof is a test: on seeds 0–99, for the correct systems and every lift mutant, the expanded contracts give the same first violations as the hand-written instances of stage 3.
- **No false positive** on seeds 0–999 of both correct systems, as a slow test.
- The whole-file word scan of `contracts/` is extended to cover `contracts/generic/`. Today it reads each entry of `contracts/` as a file and would fail on a folder. The files name no defect, mutant, experiment slot or operator note.
- The existing contract files and the documents shown to planners are not changed. A session that does not ask for the generic set sees exactly what it saw before.
- Documents: `docs/design-v0.md` (the contract section), a short `contracts/generic/README.md`, the changelog, `CLAUDE.md` and the README status.

Stop and report.

## What may be claimed afterwards

- Stage 1 is checked on development data. "The comparison now sees S15 and S19" is a development check.
- A rev4 contract, if confirmed, is unmeasured until a new blind group. None is planned in this order.
- The generic set's count on the blind slots is a development check. Its catching power on a system other than the lift is unknown: the turntable has no mutants.
- C14 is still untried on a changed build.

## Not in this order

- A new blind group, and any rule for its draw.
- The symptom oracle, the necessity check on a reproducing plan's items, module and system contract folders.
- `answered_within`, an expression that maps the motor's direction, a transition miner.
- Turntable mutants, turntable hardware, a third system.
- WP8 (provider interface) and WP9 (ranking).
- Any change to an existing contract file.

## Constraints

- One stage per branch and PR. No stacking. The operator merges every PR.
- The report goes in the PR body. The advisor reviews on the PR from the code.
- Planner-visible files (the protocol documents, the plan format, every file in `contracts/`) name no defect, mutant, experiment slot or operator note.
- The blind materials that were not published (the rules, the candidate lists, the assignment files, the scoring) are not copied into the repository. Real logs stay outside it.
- A result that was not checked is never reported as checked. Where the data is missing, say so and stop.
- No new dependency. Tests first. `git diff --check` and the full test suite before each PR.
