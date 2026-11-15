# replayspect work order WP6/7a — contract candidates checked by the engine

2026-11-15

This is an addition to `docs/work-order-v3.md`. All of its principles and constraints apply. It is the first part of WP6/7 ("Verifiable defect claims"), cut down to what testbed-05 asks for. The rest of WP6/7 is listed under "Not in this order".

## Why

testbed-05 measured two tools on 12 firmware changes that acted. The device model found all 12. The rev2 contracts caught 7. The 5 they missed are one kind of thing: a wrong or missing answer to a repeated request (`docs/experiments/testbed-05.md`, "The five slots the contracts missed").

In the field there is often no model of the device, only its protocol document and its logs. Contracts are then the only judge, so what they miss matters.

C9 and C10 came out of the testbed-04 blind by hand: the model showed a mismatch, someone explained it, a person confirmed a rule, and the rule became a contract. This order makes the middle step the engine's: a candidate contract is checked automatically before a person sees it.

## What exists already

- Nine contract kinds, including `only_after`; provenance keys `grade` and `source`.
- `judge_report`, the per-contract statuses (violated, ok, no violation in the slice, no violation in the keys judged, not exercised, not judged), and `replayspect device --contracts`.
- `contracts/lift.v0.rev2.yaml` (C1–C13), measured in testbed-05. **It is frozen.** `contracts/lift.v0.yaml` stays the default and is not changed either.
- The coverage note `docs/notes/protocol-contract-coverage.md`.

## Stage 1 — the kind `never_after`

The mirror of `only_after`: once an `after` with a key has occurred, no `event` with that key may follow.

- Keys: `event`, `after`, `per: req_id`. Trace order decides, as in `only_after`.
- Reported at the first `event` that follows an `after` of its key, once per key.
- Reordered log lines: a key that has an `event` and an `after`, one of them flagged by the log adapter, is not judged. Statuses as for `only_after`.
- A cut start can only hide a violation (the `after` may be before the cut). So it reads "no violation in the slice", not "not judged".
- Device log: judged only with both kinds declared complete.
- The loader rejects a contract whose `event` and `after` are the same pattern. Apply the same check to `only_after` (noted in the #47 review).
- Oracle: add the kind's first use to `tests/lift_oracle.py` by hand and compare on seeds 0–99 for the correct lift and every mutant.
- Tests first. Update `docs/design-v0.md` (the kind table), `docs/trace-schema.md` (the cut-start list), the changelog, and the kind count in `CLAUDE.md` and the README.

Stop and report.

## Stage 2 — `claim check`

A command that takes a candidate and says whether it deserves a person's time. No model is called anywhere in it.

- Inputs: a candidate file (one or more contracts in the existing DSL, with `grade` and `source`), one or more incident traces (trace files or device logs with their completeness declarations), and a normal corpus (a directory of traces or device logs, or simulator seeds of an implementation with no defect).
- For each candidate it reports:
  - **on each incident:** violated or not; if violated, the request and time, and whether that is the request of the device model's first mismatch when a model result is given;
  - **on the normal corpus:** in how many traces it was exercised, and every violation (trace, request, time). One violation on a normal trace fails the candidate;
  - **verdict:** `passes` (violated on every incident given, exercised on the normal corpus, no violation there), `fails` (with the reason), or `untested` (never exercised on the normal corpus: it could not have failed there, which is not the same as holding).
- "Not judged" and "not exercised" keep their meaning. A candidate that is not judged on an incident is not counted as catching it.
- Output: text, and JSON with `--out`. Deterministic: same inputs, same bytes.
- Tests on simulator data only: a known good candidate (C10 against an M10 incident), one that fails on normal traces (the `count_le` form of "DONE only after the stop", which the changelog records as failing on a correct device), and one that is never exercised.
- Document it in a new `docs/claims.md`: what a claim is, what the check proves, and what it does not (a candidate that passes is consistent with the data given; it is not thereby true).

Stop and report.

## Stage 3 — the five missed slots, as candidates

Run the loop on real material: testbed-05's S03, S04, S06, S10 and S16.

- For each slot, draft a claim: trigger and effect in one sentence, and a candidate contract. Draft from what the tools show (the first mismatch, the slot's log read through `rewind`), and cite the protocol document's lines for `source`.
- Run `claim check` with the slot's device log as the incident and, as the normal corpus, the real no-defect device logs (testbed-01 to 04 and testbed-05's S08 and S14) and simulator seeds 0–999 of the correct lift.
- **The advisor's reading, to be checked and not assumed:** S03, S06, S10 and S16 should fall to one contract, "no `ACK` for a request after its `DONE` or `ERROR` was sent" (`never_after`). The protocol document states it (lines 37–39). S04 (no reply at all) needs something the language does not have: each receive answered within a time.
- **Where the language cannot state a claim, do not build a new kind.** Write the claim, say what kind it would take, and stop for the operator's decision. A kind is added only if it would serve another protocol as well; nothing specific to the lift.
- Report in an operator note, `docs/notes/contract-candidates-rev3.md`: each claim, its candidate, the check's output, and a recommendation. **The operator confirms or drops each candidate.** Nothing enters a contract file before that.
- After confirmation: `contracts/lift.v0.rev3.yaml` (rev2 unchanged, plus the confirmed contracts), the oracle, the per-mutant table on seeds 0–999, and the coverage note's rows.
- The whole-file word scan that guards `lift.v0.rev2.yaml` covers every file in `contracts/`.

Stop and report.

## What may be claimed afterwards

- testbed-05's slots are development data from now on. "rev3 catches S03" is a development check, like the rev2 checks before testbed-05. Write it that way everywhere.
- rev3 is measured only on a new blind group (testbed-06), which gets its own registration. Its rules will be wider than testbed-05's and are again the advisor's; the analyst does not see them.

## Not in this order

- The symptom oracle, the necessity check on a reproducing plan's items, the generic library in `contracts/generic/`, module and system contract folders.
- WP8 (provider interface) and WP9 (ranking).
- Any change to the default contract file.

## Constraints

- One stage per branch and PR. No stacking. The operator merges every PR.
- The report goes in the PR body. The advisor reviews on the PR from the code.
- Planner-visible files (the protocol documents, the plan format, every file in `contracts/`) name no defect, mutant, experiment slot or operator note.
- The blind materials of testbed-05 that were not published (the rules, the candidate list, the assignment file, the scoring) are not copied into the repository.
- No new dependency. Tests first. `git diff --check` and the full test suite before each PR.
