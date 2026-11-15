# Testbed experiment 06: the rev3 contracts on new blind slots

Operator document. Do not give it to a planner.

This was the first measurement of the rev3 contracts (`contracts/lift.v0.rev3.yaml`, C1–C14), and the
third blind group. As in testbed-05, the lift firmware was changed by mechanical mutants that the analyst
(this agent) did not know. This time they came from wider rules. The 24 slots ran on the testbed-04 and
testbed-05 hardware. Each slot was judged in two ways, recorded apart:
- **the device model** (`replayspect device`, stage 1): the correct model conforms to the device log,
  or it gives its first mismatch;
- **the rev3 contracts**, judged on the device log alone.

**Registration:** [testbed-06-preregistration.md](testbed-06-preregistration.md), sha256
`c44258c1…2b4bf` at main `b986872`. It is not rewritten here. Kept outside the repository: the
client, device and truth logs; the assignment file; the advisor's scoring; the full candidate list.

## Setup

- **Harness:** `d5757b6`. The analysis ran at main `b986872`. `src/`, `contracts/` and
  `examples/testbed-uno/rules/` did not differ from `d5757b6`; `analyze.py` checks this.
- **Testbed folder:** copied to the Orin after the registration hash was recorded. Its `MANIFEST` matched
  there.
- **Plans:** the pool of 48 plans in 12 kinds. P01–P48 took seeds 1000–1047, in that order.
- **Builds:**
  - All were made from `examples/testbed-uno/firmware` at `d5757b6`. Its `lift_device.h` (sha256
    `6bd958cb…`) is the same as at `40d03fd`.
  - All were compiled on the Orin with `-DLIFT_DEFECT=0`. The boot line read `build defect=none` in all 24
    truth files.
  - The unchanged build (b09) compiled to `e08dbae1…`, the same `.hex` as in testbed-04 and testbed-05.
- **Sessions:** 6 commands, 90 s, `client.py --expect-build none`. The 24 slots ran from 14:19 to 15:00
  KST on 2026-11-15. Every client log has its end line with `valid=yes`.

## How it was run

1. **The mutants** were made by the advisor session (also Claude, not this session). The operator's
   statement:
   - **Rules:** testbed-05's rules, plus three families:
     - the two motor effect lines (omitted, or with another id or direction);
     - two statements of one straight-line block changing places;
     - finer timing constants.
   - **Count:** 181 mutants were generated, and 131 act on the advisor's closed-loop simulator.
   - **The list** is not published (sha256 `f4064241…5b466`).
   - **What the wider rules gave:** only changes that act with no fault. Every fault-triggered change in
     this group comes from testbed-05's candidate list.
2. **The draw.**
   - The advisor's `tools/draw2.py` drew the composition, each slot's plan and build, and the run order.
     Its seed was sha256(registration : candidate list : plan pool) = `3313e271…724b`.
   - Nobody picked anything by hand.
   - **Composition**, drawn within fixed ranges:

     | Group | Builds |
     | --- | --- |
     | unchanged (b09, on 5 slots) | 5 slots |
     | a change that acts under a fault | 11 |
     | a change that should not act | 1 |
     | timing | 2 |
     | effect | 2 |
     | order | 2 |
     | other | 1 |

   - No build was replaced.
3. **Hashes.**
   - The analyst received one assignment hash before any session: `fd7f073d…6d7e75`.
   - It recorded that hash under the name of the pre-build hash. It is the final file's hash, with the Orin
     `.hex` hashes. The advisor checked it against the file, and the record was corrected before scoring.
   - The pre-build hash is `65743b44…04ca`. The final file's part before the `.hex` hashes hashes to it,
     with one trailing newline. The analyst checked this at scoring.
4. **Running:** the operator flashed and ran the slots on the Orin. The analyst did not use the Orin from
   the copy of the testbed folder until the submission hash was handed over.
5. **The submission:**
   - the analyst ran the registered `analyze.py` once, on the 24 slots' client and device logs;
   - it wrote each slot's one-sentence description, changing nothing else;
   - it gave the operator the file's sha256 (`ed3631cf…81a2cc`).

   The tool's output before the descriptions is kept with its own hash (`019e7b89…a18e61`). The 48 logs
   were hashed on arrival (list `756a1c2d…`).
6. **Scoring:**
   - The advisor scored from three files:
     - the assignment file;
     - `scores.txt`, the output of `fired_points.py --reference` on each slot's real device log;
     - the submission.
   - `scores.txt` names the submission hash and the time, 15:21:58 KST. The submission file was written at
     15:19:49, so the scoring script ran after the hash.
   - The scoring notes were fixed in the assignment file before any run.
   - The analyst then checked prediction 3 on the truth files and made the C14 count below.

### Slots and builds

| Slot | Plan | Seed | Plan kind | Build | Group | Change |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | P25 | 1024 | opposite-moving | b07 | acts under a fault | Q109 |
| S02 | P41 | 1040 | copy-refused-early | b15 | acts under a fault | Q064 |
| S03 | P27 | 1026 | opposite-moving | b13 | acts under a fault | Q102 |
| S04 | P42 | 1041 | copy-refused-early | b17 | acts under a fault | Q110 |
| S05 | P09 | 1008 | copy-done | b09 | unchanged | – |
| S06 | P46 | 1045 | copy-status | b11 | effect | Q115 |
| S07 | P44 | 1043 | copy-refused-early | b03 | acts under a fault | Q047 |
| S08 | P17 | 1016 | retry-moving | b12 | should not act | Q112 |
| S09 | P12 | 1011 | copy-done | b19 | acts under a fault | Q053 |
| S10 | P45 | 1044 | copy-status | b16 | other | Q070 |
| S11 | P21 | 1020 | refused-repeat | b04 | timing | Q011 |
| S12 | P43 | 1042 | copy-refused-early | b20 | acts under a fault | Q046 |
| S13 | P10 | 1009 | copy-done | b09 | unchanged | – |
| S14 | P34 | 1033 | disconnect-moving | b14 | acts under a fault | Q066 |
| S15 | P15 | 1014 | copy-queued | b10 | order | Q158 |
| S16 | P37 | 1036 | copy-next | b06 | acts under a fault | Q056 |
| S17 | P07 | 1006 | copy-moving | b02 | acts under a fault | Q050 |
| S18 | P30 | 1029 | done-lost | b01 | timing | Q005 |
| S19 | P18 | 1017 | retry-moving | b08 | order | Q163 |
| S20 | P11 | 1010 | copy-done | b09 | unchanged | – |
| S21 | P38 | 1037 | copy-next | b18 | acts under a fault | Q059 |
| S22 | P32 | 1031 | done-lost | b09 | unchanged | – |
| S23 | P36 | 1035 | disconnect-moving | b05 | effect | Q114 |
| S24 | P33 | 1032 | disconnect-moving | b09 | unchanged | – |

## The changes

Line numbers are those of `lift_device.h` at `d5757b6`. The builds' file hashes are in the assignment file.

| Build | Change | Line | Operator | What it does | In testbed-05's list |
| --- | --- | --- | --- | --- | --- |
| b01 | Q005 | 48 | CONST | A new move starts 47 ms after its `ACK` instead of 50 ms. | no |
| b02 | Q050 | 155 | ROR | A repeat of a request still in progress is answered `ERROR reason=illegal` instead of `ACK`. | yes, K043 |
| b03 | Q047 | 155 | ENUM | A repeat of a request still in progress is answered `ERROR reason=illegal` instead of `ACK` (and a repeat of a refused one `ACK`). | yes, K040 |
| b04 | Q011 | 49 | CONST | A move takes 6,000 ms instead of 3,000 ms. | yes, K008 |
| b05 | Q114 | 258 | VAR | The motor-start effect is logged with the travelling request's id from before this move (empty on the first move), not the command's id. | no |
| b06 | Q056 | 156 | MSG | A repeat of a finished request is answered `ERROR` (no reason) instead of `DONE`. | yes, K049 |
| b07 | Q109 | 255 | MSG | A refused command is answered `DONE reason=illegal` instead of `ERROR reason=illegal`. | yes, K102 |
| b08 | Q163 | 271, 273 | SWAP | On arrival `DONE` is sent before the state change (same millisecond; the motor stop stays first). | no |
| b09 | none | – | – | Unchanged firmware (S05, S13, S20, S22, S24). | – |
| b10 | Q158 | 269, 273 | SWAP | On arrival `DONE` is sent first, before the motor stop and the state change (same millisecond). | no |
| b11 | Q115 | 258 | VAR | The motor-start effect is logged with the direction of the previous move's command. | no |
| b12 | Q112 | 256 | SDL | A refused command sends `ERROR` and is then started anyway (the `return` after the refusal is gone). | yes, K105 |
| b13 | Q102 | 248 | VAR | Whether a move is legal is decided from the last resting state, so an opposite command during a move is accepted and started. | yes, K095 |
| b14 | Q066 | 164 | ENUM | A new request is recorded as refused, so a repeat while it runs is answered `ERROR reason=illegal` instead of `ACK`. | yes, K059 |
| b15 | Q064 | 159 | SDL | After answering a repeat of a known request, the device goes on and accepts it again as new (the `return` is gone). | yes, K057 |
| b16 | Q070 | 167 | SDL | A new request gets no `ACK`. | yes, K063 |
| b17 | Q110 | 255 | SDL | A refused command gets no `ERROR` at all. | yes, K103 |
| b18 | Q059 | 156 | VAR | The `DONE` repeated for a finished request carries the travelling (or last travelled) request's id, not the request's own. | yes, K052 |
| b19 | Q053 | 156 | ENUM | A repeat of a finished request is answered `ERROR reason=illegal` instead of `DONE` (and a repeat in progress `DONE`). | yes, K046 |
| b20 | Q046 | 155 | ENUM | A repeat of a request still in progress is answered `ERROR reason=illegal` instead of `ACK` (and a repeat of a finished one `ACK`). | yes, K039 |

The firmware's motor effect lines are log lines: the Uno drives no motor. So b05 (Q114) and b11 (Q115)
change only what the device logs.

## Per slot

"Truth" is the first difference `fired_points.py --reference` printed on the slot's device log. Times are
ms from the device's start. The last column gives each violation's request class and its time after the
first difference.

| Slot | Plan kind | Change | Truth (first difference) | Verdict | S1 | S2 | Contracts violated (request class, time after the first difference) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | opposite-moving | Q109 | 8687 `DONE r-0002 reason=illegal` for `ERROR` | differs | yes | yes: "answered with DONE carrying reason=illegal instead of ERROR" | C10 (handled, same ms) |
| S02 | copy-refused-early | Q064 | 7649 a second `ACK r-0002` (extra line) | differs | yes | yes: "acknowledged twice … instead of once" | C12 (handled, same ms) |
| S03 | opposite-moving | Q102 | 24605 `effect motor_start r-0006` for `ERROR` | differs | yes | yes: "accepted a second MOVE_DOWN … instead of refusing it" | C3 (handled, same ms); C9 (another request, r-0004, end of run) |
| S04 | copy-refused-early | Q110 | 12351 no `ERROR r-0003` (missing reply) | differs | yes | yes: "no ERROR is ever sent for r-0003" | none |
| S05 | copy-done | none | none | conforms: right | – | – | none |
| S06 | copy-status | Q115 | 5998 `effect motor_start r-0002 dir=up` for `dir=down` | differs | yes | yes: "every motor_start runs the opposite way to the command" from r-0002 on | none |
| S07 | copy-refused-early | Q047 | 28781 `ERROR r-0006` for `ACK` | differs | yes | yes: "answered at once with ERROR instead of ACK" | none |
| S08 | retry-moving | Q112 | none (did not act) | conforms: right | – | – | none |
| S09 | copy-done | Q053 | 26346 `ERROR r-0006 reason=illegal` for `DONE` | differs | yes | yes: "ERROR reason=illegal instead of repeating DONE" | C8 (handled, same ms) |
| S10 | copy-status | Q070 | 4 no `ACK r-0001` (missing reply) | differs | yes | yes: "executed without an ACK" | none |
| S11 | refused-repeat | Q011 | 11389 no `motor_stop r-0003` at 3 s | differs | yes | yes: "Every travel takes 6000 ms instead of 3000 ms" | C9 (handled, 3,000 ms later) |
| S12 | copy-refused-early | Q046 | 20853 `ERROR r-0005` for `ACK` | differs | yes | yes: "answered at once with ERROR instead of ACK" | none |
| S13 | copy-done | none | none | conforms: right | – | – | none |
| S14 | disconnect-moving | Q066 | 13415 `ERROR r-0003` for `ACK` | differs | yes | yes: "answered with ERROR reason=illegal instead of ACK" | C8 (handled, 1,044 ms later) |
| S15 | copy-queued | Q158 | 3054 `DONE r-0001` before `motor_stop` (order in one ms) | **conforms: wrong** | no | no (the description names the change, but the tool's verdict is conforms) | C10 (handled, same ms) |
| S16 | copy-next | Q056 | 6006 `ERROR r-0001` for `DONE` | differs | yes | yes: "ERROR r-0001 with no reason instead of repeating DONE" | C11, C8 (handled, same ms) |
| S17 | copy-moving | Q050 | 14476 `ERROR r-0004` for `ACK` | differs | yes | yes: "answered with ERROR reason=illegal instead of ACK" | C8 (handled, 2,049 ms later) |
| S18 | done-lost | Q005 | 51 `motor_start r-0001`, 3 ms early | differs | yes | yes: "47 ms after its ACK instead of 50 ms" | none |
| S19 | retry-moving | Q163 | 3055 `DONE r-0001` before the state change (order in one ms) | **conforms: wrong** | no | no | none |
| S20 | copy-done | none | none | conforms: right | – | – | none |
| S21 | copy-next | Q059 | 10236 `DONE r-0003` for `DONE r-0002` (wrong id) | differs | yes (wrong-id rule) | yes: "DONE carrying the id r-0003 instead of r-0002" | C10 (id written, same ms); C7 (id written, 2,011 ms later) |
| S22 | done-lost | none | none | conforms: right | – | – | none |
| S23 | disconnect-moving | Q114 | 55 `effect motor_start` with no id for `r-0001` | differs | yes | yes: "logged with the previous command's request id (empty for r-0001 …)" | C9 (the line's empty id, end of run) |
| S24 | disconnect-moving | none | none | conforms: right | – | – | none |

- **Request classes** (registered): "handled" is the request being handled, the reference line's id; "id
  written" is the id on the changed line; "another request" is any other.
- **The conforming set** was empty in all 16 slots that differ: no published device defect model (M1–M11)
  matched them.
- **The descriptions** are in the submission file. The S2 column quotes them.

## Totals

**Model result**
- **Changed build, the change acted:** 18 slots.
  - Verdict `differs` in 16 of 18.
  - S1 16 of 18, one of them by the wrong-id rule (S21).
  - S2 16 of 18.
  - Where it differs, the first mismatch is in the first difference's millisecond in 16 of 16.
- **The two misses, S15 and S19,** are the two slots whose change only reorders two outputs inside one
  millisecond. The tool answered `conforms` on both. No registered prediction covers this case.
- **Changed build, the change did not act:** S08, right.
- **Unchanged build:** 5 of 5 right. False mismatches: 0.
- **S23:** its changed effect line has no id. The tool read the device log and gave a mismatch on the right
  request.

**Contract result** (rev3, C1–C14)
- **Caught 11 of 18:** S01, S02, S03, S09, S11, S14, S15, S16, S17, S21, S23.
- **Not caught, 7 of 18:** S04, S06, S07, S10, S12, S18, S19.
- **C14 fired in no slot.** With rev2 alone (C1–C13) the count is the same, 11 of 18.
- **C9–C13** fire in 8 slots (S01, S02, S03, S11, S15, S16, S21, S23). In 5 of them no C1–C8 contract fires
  (S01, S02, S11, S15, S23). With C1–C8 alone the count would be 6 of 18 (S03, S09, S14, S16, S17, S21).
- **False violations: 0** (the five unchanged slots and S08).
- **S15: a contract caught what the model missed.** C10 flags the `DONE` sent before the motor stop. The
  model accepted the reordered millisecond.
- **Where the 14 violations point:**
  - 10 on the request being handled;
  - 3 on the id written on the changed line: S21 twice, and S23, where that id is empty;
  - 1 on another request: S03's C9, on the move that never stopped.

  8 are in the first difference's millisecond, 6 later.

## Against the predictions

| # | Registered prediction | Result |
| --- | --- | --- |
| 1 | No false mismatch on the unchanged builds | **Held** (5 of 5) |
| 2 | No false contract violation on the unchanged builds or where the change did not act | **Held** (the 5 unchanged slots and S08) |
| 3 | The count check equals the truth file's losses and copies on every valid unchanged slot | **Held** (5 of 5: S05, S13, S20 one copy of a move request; S22 one `DONE` lost; S24 two polls lost). Checked by the analyst on the truth files after scoring. It held on all 24 slots. |
| 4 | Every unchanged slot valid | **Held** |
| 5 | Where a change changed a send, a state change or an effect, the first mismatch is on that request (S1 yes) | **Did not hold on S15 and S19** (16 of 18) |
| 6 | The 2 ms comparison window | S18 moved an output 3 ms earlier and gave a mismatch at that output, as predicted. No slot fell inside the 2 ms window. |
| 7 | Timer events carry their scheduled times | S11 showed at the first event whose time moved and violated C9. S18 broke no contract. As predicted. |
| 8 | Same-millisecond order of a timer and an input | No such slot occurred. |
| 9 | The allow list | No such slot occurred. |
| 10 | The contracts' documented gaps | S04, S10, S07 and S12 were caught by no contract while the model saw them, as predicted. S09 and S16, a wrong final answer that also breaks C8, were caught, as the exception says. No slot sent an `ACK` after a final answer, so the C14 clause was not tried on a changed build. |

- **Prediction 5 and S15, S19.** Both changes alter only the order of outputs in one millisecond. Whether
  that is "changing" an output is a matter of wording. The registered scoring calls these slots
  differences, so they are counted as misses.
- **A predicted miss is still a miss.** S04, S07, S10, S12 and S18 are in the totals above: missed by the
  contracts, and listed under predictions 6, 7 and 10.

## The seven slots the contracts missed

- **No answer:**
  - S04: no `ERROR` for a refused command;
  - S10: no `ACK` for a new request.

  Predicted (prediction 10; coverage note, gap 5).
- **A wrong answer to a repeat that is not an `ACK` and breaks no other rule:** S07 and S12, an `ERROR` for
  a repeat still in progress. Predicted (prediction 10).
- **A timer moved 3 ms earlier:** S18. Predicted (prediction 7: a schedule within 3,002 ms breaks no
  contract).
- **The motor's direction:** S06. Not predicted. No contract ties the direction of `motor_start` to the
  command. The protocol document says "starts the motor" and does not write the direction.
- **The order of `DONE` and the state change inside one millisecond:** S19. Not predicted. C10 orders
  `DONE` after the motor stop, which stays first in S19. No contract orders `DONE` after the state change.

The [coverage note](../notes/protocol-contract-coverage.md#device) gains a row for each of the last two.
The contract file and the contract language were not changed.

## S15 and S19: what accepted the two logs

This section records an observation. The tool was not changed.

**The comparison rule.** [device-log.md](../device-log.md), "Conformance", "When events match": a model
event matches a logged one with the same kind, name, request id and fields, logged no earlier than the
model's time and at most `--late` after it (default 2 ms). In the code (`conform` in
`src/replayspect/devicelog.py`), each model event takes the earliest free logged event with the same
signature in that window. Where the logged event sits among the lines of its millisecond is not
compared. The device log gives every line a whole millisecond, so the three arrival lines share one time.

**S15** (Q158, `DONE` first). On every arrival the model makes `motor_stop`, the state change and `DONE`,
in that order. The log has `DONE`, `motor_stop` and the state change, in the same millisecond, on all six
arrivals. Each model event found its logged counterpart at the same time. Nothing was left unmatched, so
the verdict was `conforms`.

**S19** (Q163, `DONE` before the state change). The log has `motor_stop`, `DONE` and the state change,
in the same millisecond, on all six arrivals. Each matched in the same way, and the verdict was
`conforms`.

**What the device-log document says.** The rule "Same-millisecond order" is about how the model is fed: a
timer runs before an input in the same millisecond. It does not say whether outputs within one
millisecond are compared in order. The unchanged firmware writes the arrival lines in one fixed order:
motor stop, state change, `DONE`.

**The contracts read the log in line order.** In S15, C10 (`DONE` only after `motor_stop` for that id)
saw the `DONE` before the stop, at 3054 ms, on r-0001. In S19 the stop stays first, and no rev3 contract
orders `DONE` and the state change.

**S2 on S15.** The description says "the device sends DONE before motor_stop and the state change in the
same ms". That names the change, but the verdict is `conforms`, so S2 is no as well.

## C14 on the unchanged builds (counted after scoring)

Registered as a count after scoring, not a prediction. The measure is `claim check`'s "tried" for a
`never_after` contract ([claims.md](../claims.md)): a request with an `after` (`DONE` or `ERROR`) that has
something later with the same id by the device. On a device log that is the conservative measure: the
device heard of the request again after its final answer. Counted with `tried_keys` in
`src/replayspect/claim.py`, split by the final answer.

| Slot | Requests with a `DONE` | of them tried | Requests with an `ERROR` | of them tried | C14 violations |
| --- | --- | --- | --- | --- | --- |
| S05 | 6 | 1 (r-0001, copy at 3505 ms) | 0 | 0 | 0 |
| S13 | 6 | 1 (r-0003, copy at 12017 ms) | 0 | 0 | 0 |
| S20 | 6 | 1 (r-0004, copy at 20047 ms) | 0 | 0 | 0 |
| S22 | 6 | 0 | 0 | 0 | 0 |
| S24 | 6 | 0 | 0 | 0 | 0 |
| **All** | **30** | **3** | **0** | **0** | **0** |

- **The `DONE` side was tried on hardware for the first time:** three times, each a copy of a move request
  arriving after its `DONE` (the `copy-done` plans). Each copy was answered `DONE` again, in the
  millisecond it arrived, with no `ACK`.
- **The `ERROR` side was not tried here.** No command was refused on the unchanged slots.

## What the results show

- **The device model found 16 of the 18 acting changes,** each on the request and in the millisecond where
  the change acted, with the content right. No false mismatch.
- **The two it missed reorder outputs inside one millisecond.** The comparison matches events by time
  within a 2 ms window and does not compare order. A contract caught one of the two (S15, C10).
- **The rev3 contracts caught 11 of 18,** with no false violation. That is the same as rev2 here: C14
  fired nowhere, because no drawn change sends an `ACK` after a final answer.
- **What the contracts missed:**
  - five slots where predicted gaps apply (S04, S07, S10, S12, S18);
  - two slots the predictions did not foresee: the motor's direction (S06) and the order of `DONE` and the
    state change (S19).
- **Changes on the log line only were seen:** S06 and S23 change only what the device logs about the motor.
  The model saw both, as what was logged.

## Proposals (not adopted)

Recorded for the operator to decide. Nothing here is in a contract file.

- **A contract for S19:** `DONE` for a `req_id` only after the arrival state for that `req_id`. With
  `only_after`: `event: device.send(DONE)`, `after: device.state(UP|DOWN)`, `per: req_id`. The language can
  state it. The state lines carry the request's id. It has not been checked on any data. Whether the
  document's "the state becomes UP or DOWN, and DONE is sent" states an order is the operator's reading.
- **The motor's direction (S06).** It cannot be said with one comparison. The effect's `dir` holds `up` or
  `down`, the command `MOVE_UP` or `MOVE_DOWN`, the state `UP` or `DOWN`. Tying them needs a new expression
  that maps one value to another, or two conditions at once (gap 1). The protocol document would also have
  to state the direction.

## Limits

- **C14 was not tried on a changed build.** No drawn change sends an `ACK` after a final answer. This group
  says nothing for or against C14's power to catch. It does say that rev3 caught no more than rev2 here:
  11 of 18 for both.
- **A predicted miss is still a miss.** S04, S07, S10, S12 and S18 were predicted missed by the contracts
  and are counted as missed.
- **Two misses were not predicted:** S06 (the motor's direction) and S19 (the order within one millisecond).
- **Overlap with testbed-05's candidate list.**
  - 14 of the 19 drawn changes are in testbed-05's candidate list, which the analyst saw when testbed-05 was
    scored. None of them was drawn in testbed-05.
  - Every fault-triggered change in this group comes from that list.
  - The fault-triggered changes are alike again: all 12 sit in the reply and refusal lines (155–159, 164,
    248, 255–256).
- **The four candidate ids printed to the analyst while it prepared this group were all drawn:** K043
  (S17), K049 (S16), K103 (S04), K105 (S08). Only the ids were printed.
- **The final assignment hash was recorded under the name of the pre-build hash** and corrected before
  scoring. The analyst held the final hash before any session, as registered. It received it before it
  copied the testbed folder to the Orin, so steps 3 and 4 of the registered order ran in the other order.
  Both came before any session.
- **The scoring script ran after the submission hash** (15:21:58 KST, as `scores.txt` records).
- **The operator started the run script once before the testbed folder was on the Orin.** It stopped at
  once with a message and ran nothing.
- **The device log is the suspect's statement.** The motor effect lines are log lines. S06 and S23 changed
  only them, and were seen as what was logged.
- **Scheduled-time logs.** As in testbed-04 and 05, the device log's timer events carry their scheduled
  times.
- **The advisor knows the tool** (registration, Limits). It wrote the rules and made the draw.
- **Small numbers:** 18 acting slots, 19 changes. Rates are counts, not estimates with error bars.
