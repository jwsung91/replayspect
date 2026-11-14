# Testbed experiment 05: blind slots on mechanically changed firmware

Operator document. Do not give it to a planner.

This was the first measurement of the rev2 contracts (`contracts/lift.v0.rev2.yaml`, C1–C13), and the
second blind group. The lift firmware was changed by mechanical mutants that the analyst (this agent)
did not know. The 16 slots ran on the testbed-04 hardware. Each slot was judged in two ways, recorded
apart:
- **the device model** (`replayspect device`, stage 1): the correct model conforms to the device log,
  or it gives its first mismatch;
- **the rev2 contracts**, judged on the device log alone.

**Registration:** [testbed-05-preregistration.md](testbed-05-preregistration.md), sha256
`1e1bd267…0641a9f` at main `823b829`. It is not rewritten here. Kept outside the repository: the
client, device and truth logs; the assignment file; the advisor's scoring; the full candidate list.

## Setup

- **Harness:** `40d03fd`. The analysis ran at main `823b829`; `src/`, `contracts/` and
  `examples/testbed-uno/rules/` did not differ from `40d03fd`, as `analyze.py` checks.
- **Files:** the 10 files in the registration's hash table matched before the runs. The testbed folder
  was copied to the Orin after the registration's hash was recorded. Its `MANIFEST` matched on the Orin.
- **Plans:** the pool of 36 plans. P01–P36 took seeds 900–935, in that order.
- **Builds:**
  - All were made from `examples/testbed-uno/firmware` at `823b829`. Its `lift_device.h` (sha256
    `6bd958cb…`) is the same as at `40d03fd`.
  - All were compiled on the Orin with `-DLIFT_DEFECT=0`. The boot line read `build defect=none` in
    all 16 truth files.
  - The unchanged build (b13) compiled to `e08dbae1…`, the same `.hex` as testbed-04's off build.
- **Sessions:** 6 commands, 90 s, `client.py --expect-build none`.

## How it was run

1. **The mutants** were made by the advisor session (also Claude, not this session) with `tools/gen.py`.
   Every mutant changes one token on one line of `lift_device.h`, or deletes one statement:
   - **Operators:** a comparison operator, `&&`/`||`, a removed `!`, `+`/`-`, the constants `PROC_MS`
     and `TRAVEL_MS`, an enum value, the message name (`ACK`/`DONE`/`ERROR`), a variable of the same
     type, a deleted statement.
   - **Lines not changed:** logging, line parsing, the defect switch, loop heads, array indexes, memory
     limits. The motor effect lines are logging, so no rule gives "DONE with no motor".
   - **Sorting:** 143 mutants, each run in the advisor's closed-loop simulator (not replayspect) on 82
     fault scenarios:

     | Class | Mutants |
     | --- | --- |
     | does not compile | 6 |
     | hangs or crashes in the simulator | 16 |
     | writes an error line (run invalid) | 1 |
     | no difference in any scenario | 11 |
     | differs with no fault | 71 |
     | differs only under a fault | 38 |

   - **Excluded from the draw:** 4 mutants equal to a public defect in all 82 scenarios. Nobody checked
     whether replayspect catches a mutant.
   - **Where the list is:** the full list stays outside the repository (sha256 `3dec3047…bfc8c`).
2. **The draw.**
   - The advisor's `tools/draw.py` drew the composition, each slot's plan and build, and the run order.
     Its seed was sha256(registration : candidate list : plan pool).
   - Nobody picked anything by hand. The operator confirmed the draw.
   - The composition: 11 slots with a change that acts under a fault, 2 with a change that should not
     act, 1 with a change that acts with no fault, and 2 unchanged.
   - The assignment file records no replaced build.
3. **Hashes.** The analyst received the assignment's sha256 twice, before any session: before the build
   (`0ab29db1…5517`) and in its final form with the Orin `.hex` hashes (`9e17440c…65b2`). The final
   file's part before the `.hex` hashes hashes to the first. Both matched the file shown at scoring.
4. **Running:** the operator flashed and ran the slots on the Orin. The analyst did not use the Orin
   from before the final hash until the submission was handed over.
5. **The submission:**
   - the analyst ran the registered `analyze.py` once, on the 16 slots' client and device logs;
   - it wrote each slot's one-sentence description, changing nothing else;
   - it gave the operator the file's sha256 (`dbef1725…43a2`).

   The tool's output before the descriptions is kept with its own hash (`d33e80c5…097de`). The logs
   received matched the Orin's copies byte for byte.
6. **Scoring:** the advisor scored from the assignment file, `fired_points.py --reference` on each
   slot's real device log, and the submission. The scoring notes were fixed in the assignment file
   before any run. The analyst then checked prediction 3 on the truth files.

## The changes

Line numbers are those of `lift_device.h` at `40d03fd`. The builds' file hashes are in the assignment file.

| Build | Change | Line | Operator | What it does |
| --- | --- | --- | --- | --- |
| b01 | K048 | 156 | MSG | A repeat of a finished request is answered `ACK` instead of `DONE`. |
| b02 | K101 | 255 | MSG | A refused command is answered `ACK reason=illegal` instead of `ERROR reason=illegal`. |
| b03 | K037 | 153 | ROR | A repeat of the first recorded request is not found in the table (`known > 0`), so it is accepted again as new. |
| b04 | K055 | 158 | SDL | A repeat of a refused request gets no answer at all. |
| b05 | K082 | 223 | SDL | A recorded result is never updated after acceptance, so a repeat of a finished request is answered `ACK` instead of `DONE`. |
| b06 | K056 | 158 | VAR | The `ERROR` repeated for a refused request carries the travelling (or last travelled) request's id. |
| b07 | K104 | 255 | VAR | The `ERROR` for a refused command carries the travelling (or last travelled) request's id. |
| b08 | K128 | 271 | ENUM | When a `MOVE_DOWN` arrives, the state becomes `UP` instead of `DOWN`. |
| b09 | K097 | 254 | ENUM | A refused request is recorded as in progress, so its repeat is answered `ACK` instead of `ERROR`. |
| b10 | K045 | 155 | VAR | The `ACK` repeated for a request in progress carries the travelling (or last travelled) request's id. |
| b11 | K041 | 155 | MSG | A repeat of a request in progress is answered `DONE` instead of `ACK`. |
| b12 | K080 | 223 | ROR | The first recorded request's result is never updated (`i > 0`), so a repeat of it after it finished is answered `ACK`. |
| b13 | none | – | – | Unchanged firmware (slots S08 and S14). |
| b14 | K053 | 158 | MSG | A repeat of a refused request is answered `ACK reason=illegal` instead of `ERROR reason=illegal`. |
| b15 | K042 | 155 | MSG | A repeat of a request in progress is answered `ERROR` (no reason) instead of `ACK`. |

## Per slot

"Truth" is the first difference `fired_points.py --reference` printed on the slot's device log. Times
are ms from the device's start.

| Slot | Plan (kind) | Build | Change | Truth (first difference) | Verdict | S1 request | S2 content | Contracts violated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | P02 (no fault) | b03 | K037 | none (did not act) | conforms: right | – | – | none |
| S02 | P13 (copy while waiting) | b10 | K045 | 5161 `ACK r-0001` for `ACK r-0002` | differs | yes (wrong-id rule) | yes | C12 (r-0001, 5161) |
| S03 | P24 (refused repeat) | b14 | K053 | 28694 `ACK r-0006 reason=illegal` for `ERROR` | differs | yes | yes | none |
| S04 | P23 (refused repeat) | b04 | K055 | 24395 no reply for `ERROR r-0005` | differs | yes | yes | none |
| S05 | P26 (opposite during a move) | b12 | K080 | none on what was logged | invalid | not scored | not scored | none on what was logged |
| S06 | P21 (refused repeat) | b09 | K097 | 8745 `ACK r-0002` for `ERROR` | differs | yes | yes | none |
| S07 | P03 (no fault) | b08 | K128 | 7673 state `UP` for `DOWN` (r-0002) | differs | yes | yes | C3 (r-0002, 7673) |
| S08 | P01 (no fault) | b13 | none | none | conforms: right | – | – | none |
| S09 | P14 (copy while waiting) | b11 | K041 | 8371 `DONE r-0003` for `ACK` | differs | yes | yes | C10 (r-0003, 8371) |
| S10 | P11 (copy after `DONE`) | b01 | K048 | 19144 `ACK r-0004` for `DONE` | differs | yes | yes | none |
| S11 | P22 (refused repeat) | b06 | K056 | 14137 `ERROR r-0001` for `ERROR r-0003` | differs | yes (wrong-id rule) | yes | C7, C8 (r-0001, 14137) |
| S12 | P27 (opposite during a move) | b02 | K101 | 23430 `ACK r-0005 reason=illegal` for `ERROR` | differs | yes | yes | C12 (r-0005, 23430) |
| S13 | P05 (copy during the move) | b15 | K042 | 1007 `ERROR r-0001` for `ACK` | differs | yes | yes | C11 (r-0001, 1007), C8 (3055) |
| S14 | P30 (`DONE` lost) | b13 | none | none | conforms: right | – | – | none |
| S15 | P28 (opposite during a move) | b07 | K104 | 28789 `ERROR r-0005` for `ERROR r-0006` | differs | yes (wrong-id rule) | yes | C7, C8 (r-0005, 29451) |
| S16 | P12 (copy after `DONE`) | b05 | K082 | 30646 `ACK r-0006` for `DONE` | differs | yes | yes | none |

- **Wrong-id rule** (fixed before any run): for K045, K056 and K104 the first difference is one reply
  with a wrong id. S1 is yes when the first mismatch is that reply, at the same time, whichever of the
  two ids its `req_id` holds.
- **The conforming set** was empty in all 12 slots that differ. No published device defect model
  (M1–M11) matched them.
- **The submission's descriptions** are in the submission file. The scoring quotes each one with its
  S2 "yes", for example S02 "ACK carrying the previous request's id" and S04 "got no reply
  at all".

## Totals

**Model result**
- **Changed build, the change acted:** 12 slots.
  - Verdict `differs` in 12 of 12.
  - S1 12 of 12, three of them by the wrong-id rule (S02, S11, S15).
  - S2 12 of 12.
  - The first mismatch was in the same millisecond as the first difference in all 12.
- **Changed build, the change did not act:** S01 right. S05 invalid (stopped on the host side), not scored.
- **Unchanged build:** S08 and S14 right. False mismatches: 0 of 2.

**Contract result** (rev2, C1–C13)
- **Caught 7 of 12:** S02 (C12), S07 (C3), S09 (C10), S11 (C7, C8), S12 (C12), S13 (C11, C8), S15 (C7, C8).
- **Not caught, 5 of 12:** S03, S04, S06, S10, S16.
- **New contracts (C9–C13)** fire in 4 slots: S02, S09 and S12 (only new contracts), and S13 (C11 at the
  first difference, C8 two seconds later). With C1–C8 alone, the count would be 4 of 12 (S07, S11, S13,
  S15).
- **Where the violation points:**
  - on the request being handled, in its millisecond, in 4 of 7 (S07, S09, S12, and S13 by C11);
  - S02 and S11: on the id written on the wrong reply, in the same millisecond;
  - S15: 662 ms later, on the id written on the wrong reply.
  - **This count was corrected after scoring.** The advisor's first scoring said 5 of 7, counting S02
    with the first group. The analyst found it when checking the scoring against `scores.txt`. By the
    note fixed before the runs, the request being handled is the id on the reference line (r-0002 in
    S02), and S02's C12 violation is on r-0001. The advisor corrected `scoring.md` (new sha256
    `50287a37…`); no other number changed.
- **False violations: 0** (S01, S08, S14; none on S05's partial log).

## Against the predictions

| # | Registered prediction | Result |
| --- | --- | --- |
| 1 | No false mismatch on the unchanged builds | **Held** (2 of 2) |
| 2 | No false contract violation on the unchanged builds or where the change did not act | **Held** (S01, S08, S14) |
| 3 | The count check equals the truth file's losses and copies on every valid unchanged slot | **Held** (S08 nothing; S14 one `DONE` of r-0002 lost). Checked by the analyst on the truth files after scoring. It held on all 16 slots, S05's partial log included. |
| 4 | Every unchanged slot valid | **Held** |
| 5 | Where a change acted, the first mismatch is on that request (S1 yes) | **Held** (12 of 12) |

## The five slots the contracts missed

All five are a wrong answer to a repeated request:
- **S03, S06, S10, S16:** an `ACK` went out where the stored `ERROR` or `DONE` belonged.
  - The request was received twice and two `ACK`s went out, so C12's bound (no more `ACK` than
    receives per id) holds.
  - This is the "in part" C12 has for lines 47–48 in the
    [coverage note](../notes/protocol-contract-coverage.md#device): "an unsolicited send hides under a
    repeat that was answered with the other message".
  - It is also the row for lines 37–39, "a known id is answered with its stored result again", whose
    contract is "none": nothing in the contract language ties a repeated receive to its reply.
- **S04:** no reply to a repeat. No contract requires a reply. This is the same lines 37–39 row.

The contracts that did catch a repeat's wrong answer caught it only through what the answer did:
- S02: an `ACK` with another id, against C12 on that id;
- S09: a `DONE` before the move, C10;
- S11: an `ERROR` with another id, C7 and C8 on that id;
- S13: an `ERROR` with no reason, C11.

The contract language was not changed for this result.

## What the results show

- **The device model found every acting change** (12 of 12): on the request and in the millisecond
  where the change acted, with the content right. No false mismatch.
- **The rev2 contracts caught 7 of 12,** with no false violation. The new contracts made the
  difference in 3 slots (S02, S09, S12): with C1–C8 alone, 4 of 12.
- **What the contracts miss is one row of the coverage note:** a wrong or missing answer to a repeated
  request (lines 37–39).
- **What this does not show:** the changes are alike (Limits). 11 of the 12 acting changes are in the
  reply to a known id or in the refusal, and none changes timing.

## Limits

- **S05 is invalid: stopped on the host side; what stopped it is not recorded.** The operator
  confirmed the following from their Orin records and memory.
  - **The stop:** the session stopped at 01:01:11 KST, 49 s after its start. The device answered polls
    up to the last line, and the client log and the device log stopped at the same moment. The stop
    was on the host side.
  - **The rerun was skipped:** the operator's run script started again about 2.5 minutes later (S06
    began about 01:04:15 and ended at 01:05:45). The restarted script skipped S05 because its client
    log already existed. That is a defect of the advisor's `02_run_all.sh`: it takes a log with no
    end line as finished.
  - **What is recorded:** the Orin's `run_all.log` starts at S06; the first run's log is not kept. The
    operator also remembers the run being cut short, but no record says what cut it.
  - **The build:** no evidence points at the build (K080). As the registration requires, S05 was not
    run again.
- **The analyst knew an old slot composition.** After the registration, the analyst learned the old
  composition (the counts) from a paste by the operator. That composition was discarded before the
  draw; the drawn one differs.
- **The changes are alike.**
  - 11 of the 12 acting changes are in the reply to a known id or in the refusal (lines 155–158, 223,
    254–255): the rules put the fault-triggered behaviour there.
  - One change acts with no fault (S07). No timing change was drawn.
- **Two unchanged slots only** (the draw's minimum).
- **Scheduled-time logs.** As in testbed-04, the device log's timer events carry their scheduled
  times.
- **The scoring script ran before the submission hash** (operator confirmed). Per the advisor's
  conversation record, its output was pasted at 01:31 KST and the submission hash reached the operator
  at 01:34. The operator confirms that neither the scoring output nor the assignment file was given to
  the analyst before the submission hash.
- **The advisor knows the tool** (registration, Limits). It wrote the rules and made the draw.
- **The device log is the suspect's statement.** No drawn change acted only on logging; the rules
  exclude logging lines.
- **Small numbers:** 12 acting slots, 12 changes. Rates are counts, not estimates with error bars.
