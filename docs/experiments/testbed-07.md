# Testbed experiment 07: the generic set's first measurement, on blind turntable slots

Operator document. Do not give it to a planner.

This was the first measurement of the generic contract set (`contracts/generic/`, bound to the turntable by
`contracts/generic/turntable.v0.yaml`), and the fourth blind group. It was also the device comparison's first
blind group on a second system. The turntable firmware was changed by mechanical mutants that the analyst
(this agent) did not know. The 24 slots ran on the turntable board alone. Each slot was judged in two ways,
recorded apart:
- **the device model** (`replayspect device --system turntable.v0`): the correct model conforms to the device
  log, or it gives its first mismatch;
- **the contracts,** on the device log, three ways: the generic set, the turntable's own
  (`contracts/turntable.v0.yaml`, C1–C8), and their union.

**Registration:** [testbed-07-preregistration.md](testbed-07-preregistration.md), sha256
`3e9c1f21…88adca1` at main `2860d70`. It is not rewritten here. Kept outside the repository: the client,
device and truth logs; the assignment file; the scoring output; the advisor's rules and candidate list.

## Setup

- **Harness:** `1356127`. The analysis ran on a working tree whose `src/`, `contracts/` and
  `examples/testbed-uno/rules/` did not differ from `1356127`; `analyze.py` checks this.
- **Testbed folder:** copied to the Orin (`~/replayspect-testbed/testbed-07`) after the registration hash was
  recorded. Its `MANIFEST` (sha256 `fee08258…`) matched there: 53 files, no failure.
- **Plans:** the pool of 48 plans in 12 kinds. P01–P48 took seeds 3000–3047, in that order.
- **Board:** the Arduino UNO Mini `…B182` (`TURNTABLE_PORT` in `boards.env`). The lift board `…B101` stayed
  connected and was not used.
- **Builds:**
  - All were made from `examples/testbed-uno/firmware` at `1356127`; the unchanged `turntable_device.h` is
    sha256 `0d120d22…`.
  - All were compiled on the Orin. After every flash, the boot check read `READY log=1` and
    `build system=turntable.v0 defect=none` (24 of 24, the operator's run log).
- **Sessions:** 6 commands, 90 s, `client.py --expect-system turntable.v0 --expect-build none`. The 24 slots
  ran from 07:40:46 to 08:20:58 KST on 2026-11-23. Every client log ends with `valid=yes`, and no device log has
  an `error` line.

## How it was run

1. **The mutants** were made by the advisor session (also Claude, not this session).

   **The operator's statement:**

   > The changes are mechanical mutants of turntable_device.h, made by the advisor.
   > - Rules: testbed-06's rules carried over. The same ten operators; the target lines are the
   >   turntable lines that correspond to the lift's target lines, plus the turntable's own
   >   refusal and direction logic, which the lift does not have. testbed-06's generator was not
   >   kept; the rewritten one regenerates testbed-06's 181 lift candidates exactly.
   > - Candidates: 229 mutants. They were sorted on this group's 48 pool plans in the advisor's
   >   closed-loop simulator (testbed-06's 114 scenarios were not kept): 5 do not compile
   >   natively, 19 stop the simulator, 22 change nothing on the pool, 118 act with no fault,
   >   65 act only under a fault.
   > - Two rules were added to testbed-06's. (1) A behaviour is not drawn if any mutant with that
   >   behaviour is the twin of a lift change drawn in testbed-05 or testbed-06, or of a published
   >   lift defect. A twin is the same operator on the same token of the lift line that the
   >   turntable line carries over. (2) At most two drawn changes on one source line.
   >   Both were fixed before the registration was approved (the hashes in it), but the
   >   registration does not describe them.
   > - The draw: the composition ranges are testbed-06's. The seed is the one the registration
   >   defines. A fault-triggered change that should act is paired with a plan on which it acts
   >   in the simulator.
   > - The advisor ran replayspect on no candidate, and on no slot before the submission's hash.
   > - The rules file and the candidate list are not published.

   **Overlap with earlier groups** (the assignment file, as written):
   - By rules.md v3 no drawn change has a behaviour whose lift twin was drawn in testbed-05 or testbed-06, or is a published lift defect.
   - 12 of the 19 drawn changes have a twin in testbed-06's candidate list (the same operator on the lift line the turntable line carries over); 7 of those twins are in testbed-05's list, which the analyst saw when testbed-05 was scored. None of those twins was drawn in testbed-05 or testbed-06.
   - 7 drawn changes are on lines the lift does not have (the turntable's own refusal and direction logic, lines 122 and 181 to 194).
2. **The draw.**
   - The advisor's `tools/draw3.py` drew the composition, each slot's plan and build, and the run order.
   - Its seed is the registered one: sha256(registration : candidate list : plan pool) = `3eb5676b…0740822`.
   - Nobody picked anything by hand.
   - **Composition**, drawn within testbed-06's ranges:

     | Group | Builds | Slots |
     | --- | --- | --- |
     | unchanged (b10) | 1 | 5 |
     | fault-triggered, should act | 6 | 6 |
     | fault-triggered, should not act | 2 | 2 |
     | timing | 3 | 3 |
     | effect | 2 | 2 |
     | order | 2 | 2 |
     | other | 4 | 4 |

   - The ranges gave effect and order three slots each, but only two such changes could be drawn for each.
     The third slot of each went to "other" (the assignment file's note; Departures).
   - No build was replaced.
3. **Hashes.**
   - The advisor's materials (registration, "The draw"): `rules.md` `86958132…`, `candidates.tsv`
     `8c67f609…`, `tools.sha256` `703ba689…`.
   - The final assignment file, with the Orin `.hex` hashes: `5764c45f…57f896fe35`. Its hash reached the analyst
     at 07:40:29 KST (the analyst's session record), 17 s before the step script first started (07:40:46). The
     assignment file itself reached the analyst after scoring (Order, step 7).
   - The assignment can be rebuilt from hashes fixed in the registration: the draw seed is defined by the
     registration's own sha256, `candidates.tsv`'s and `blind-plans.json`'s, and the advisor's materials are
     listed there by hash.
4. **Running:** the operator flashed and ran the slots on the Orin with the advisor's step script
   (`02_run_all.sh`), which calls `blind_flash.sh` and `run_blind.sh`. The analyst's Orin access was not cut
   (Departures).
5. **The submission:**
   - the analyst ran the registered `analyze.py` (sha256 `cbf39459…`) once, on the 24 slots' client and device
     logs;
   - it wrote each slot's one-sentence description, changing nothing else;
   - it gave the operator the file's sha256 (`fb78ef2d…af0d91879`), written at 21:41:00 KST.

   The tool's output before the descriptions is kept with its own hash (`89f169aa…49c5770b7`). The 48 logs were
   hashed on arrival (list `c11fe919…`).
6. **Scoring:**
   - The operator ran the registered `score.py` (sha256 `a5fafccf…`). `scores.txt` names the submission hash
     and the time, 21:44:06 KST, after the submission was written.
   - S2 was judged by hand by the advisor (Totals).
   - The scoring notes were fixed in the assignment file before any run.

### Slots and builds

| Slot | Plan | Seed | Plan kind | Build | Group | Change |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | P10 | 3009 | copy-after-done | b10 | unchanged | – |
| S02 | P31 | 3030 | done-lost | b13 | other | T052 |
| S03 | P36 | 3035 | disconnect-during-turn | b11 | timing | T007 |
| S04 | P48 | 3047 | copy-status/stand-move | b09 | timing | T001 |
| S05 | P02 | 3001 | none | b05 | order | T208 |
| S06 | P26 | 3025 | command-during-turn | b12 | effect | T193 |
| S07 | P41 | 3040 | copy-refused-early | b18 | fault-triggered, acting | T165 |
| S08 | P07 | 3006 | copy-during-turn | b10 | unchanged | – |
| S09 | P25 | 3024 | command-during-turn | b04 | fault-triggered, acting | T173 |
| S10 | P12 | 3011 | copy-after-done | b10 | unchanged | – |
| S11 | P24 | 3023 | refused-repeated | b01 | fault-triggered, not acting | T082 |
| S12 | P22 | 3021 | refused-repeated | b14 | fault-triggered, acting | T137 |
| S13 | P21 | 3020 | refused-repeated | b06 | fault-triggered, acting | T046 |
| S14 | P17 | 3016 | ack-lost-retry-during-turn | b08 | other | T151 |
| S15 | P32 | 3031 | done-lost | b07 | effect | T180 |
| S16 | P45 | 3044 | copy-status/move-move | b02 | other | T111 |
| S17 | P11 | 3010 | copy-after-done | b15 | timing | T191 |
| S18 | P37 | 3036 | copy-next | b10 | unchanged | – |
| S19 | P42 | 3041 | copy-refused-early | b03 | fault-triggered, acting | T139 |
| S20 | P19 | 3018 | ack-lost-retry-during-turn | b20 | order | T214 |
| S21 | P34 | 3033 | disconnect-during-turn | b10 | unchanged | – |
| S22 | P47 | 3046 | copy-status/move-stand | b16 | fault-triggered, not acting | T196 |
| S23 | P05 | 3004 | copy-during-turn | b19 | other | T037 |
| S24 | P23 | 3022 | refused-repeated | b17 | fault-triggered, acting | T175 |

## The changes

Line numbers are those of `turntable_device.h` at `1356127`. The builds' file and `.hex` hashes are in the
assignment file. "Lift twin" is the same operator on the lift line the turntable line carries over, in
testbed-06's candidate list.

| Build | Change | Line | Operator | What it does | Lift twin |
| --- | --- | --- | --- | --- | --- |
| b01 | T082 | 180 | ENUM | A repeat of a finished request is answered `ERROR reason=illegal` instead of `DONE`, and a request refused as illegal is answered `DONE` instead of `ERROR reason=illegal`. | yes (also in testbed-05's list) |
| b02 | T111 | 188 | ENUM | A `TURN_RIGHT` from INITIAL sets the state to LEFT instead of TURNING_TO_RIGHT while it turns (it still arrives at RIGHT). | none |
| b03 | T139 | 190 | LCR | A `TURN_LEFT` is never refused and a `TURN_RIGHT` at RIGHT is accepted: each starts a turn to INITIAL, also during a turn. | none |
| b04 | T173 | 194 | ROR | A command refused during a turn is answered `ERROR reason=limit` instead of `reason=illegal` (and one refused at RIGHT `reason=illegal` instead of `reason=limit`). | none |
| b05 | T208 | 210, 212 | SWAP | On arrival the request is recorded as done and the state changes before the motor-stop effect is logged (same millisecond; `DONE` stays last). | yes |
| b06 | T046 | 122 | VAR | A repeat of a known request is answered with the id of the turning (or last turned) request instead of its own. | none |
| b07 | T180 | 199 | SDL | The motor-start effect is never logged. | yes |
| b08 | T151 | 192 | ENUM | After a turn back to INITIAL the state becomes TURNING_TO_LEFT instead of INITIAL, so every later command is refused as illegal. | none |
| b09 | T001 | 25 | CONST | A new turn starts in the same millisecond as its `ACK` instead of 50 ms later. | yes (also in testbed-05's list) |
| b10 | none | – | – | Unchanged firmware (S01, S08, S10, S18, S21). | – |
| b11 | T007 | 25 | CONST | A new turn starts 53 ms after its `ACK` instead of 50 ms. | yes |
| b12 | T193 | 210 | SDL | The motor-stop effect is never logged. | yes |
| b13 | T052 | 127 | MSG | A new request is answered `DONE` instead of `ACK`, 50 ms before its turn starts; the turn still runs and sends its own `DONE` on arrival. | yes (also in testbed-05's list) |
| b14 | T137 | 190 | LCR | A `TURN_RIGHT` is never refused and a `TURN_LEFT` at LEFT is accepted: each starts a turn to INITIAL, also during a turn. | none |
| b15 | T191 | 205 | VAR | A turn ends 3,000 ms after the previous turn's end time (the first one 3,000 ms after boot) instead of 3,000 ms after it starts: turns are too short, and one that starts after that time ends at once. | yes (also in testbed-05's list) |
| b16 | T196 | 212 | ENUM | A finished request is recorded as refused at the limit, so a repeat after `DONE` is answered `ERROR reason=limit` instead of `DONE`. | yes (also in testbed-05's list) |
| b17 | T175 | 195 | SDL | A refused request is not recorded as refused, so a repeat of it is answered `ACK` instead of `ERROR`. | yes (also in testbed-05's list) |
| b18 | T165 | 194 | ENUM | A command refused at the limit is recorded and answered as `ACK` instead of `ERROR reason=limit`; no turn follows. | none |
| b19 | T037 | 91 | SDL | A new request is acknowledged and then never executed: no turn, no `DONE`, no refusal. | yes (also in testbed-05's list) |
| b20 | T214 | 199, 201 | SWAP | The motor-start effect is logged after the state change instead of before it (same millisecond). | yes |

The firmware's motor effect lines are log lines: the Uno drives no motor. So b05, b07, b12 and b20 change only
what the device logs.

## Per slot

"Truth" is the first difference `fired_points.py --system turntable --reference` printed on the slot's device
log. Times are ms from the device's start. The contract columns give each set's first violations, with the
request class and the time after the first difference.

| Slot | Change | Truth (first difference) | Verdict | S1 | Turntable's own (C1–C8) | Generic |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | none | none | conforms: right | – | none | none |
| S02 | T052 | 5 `DONE r-0001` for `ACK` | differs | yes | C7, C8 (another request, r-0002, 1,523 ms later) | G6, G6b (handled, same ms); G2.final, G3 (another request, r-0002, 1,523 ms later) |
| S03 | T007 | 54 `motor_start r-0001` logged at 57, 3 ms late | differs | yes | none | none |
| S04 | T001 | 54 `motor_start r-0001` logged at 4, 50 ms early | differs | yes | none | none |
| S05 | T208 | 3054 the state line where `motor_stop` is expected (order in one ms) | differs | yes | none | P1 (handled, same ms) |
| S06 | T193 | 3054 the state line where `motor_stop` is expected (the stop never logged) | differs | yes | none | G6 (handled, same ms) |
| S07 | T165 | 14350 `ACK r-0003` for `ERROR reason=limit` | differs | yes | none | G2.ack (handled, same ms) |
| S08 | none | none | conforms: right | – | none | none |
| S09 | T173 | 7350 `ERROR r-0002 reason=limit` for `reason=illegal` | differs | yes | none | none |
| S10 | none | none | conforms: right | – | none | none |
| S11 | T082 | none (did not act) | conforms: right | – | none | none |
| S12 | T137 | 22606 `motor_start r-0005` for `ERROR reason=limit` | differs | yes | C3 (handled, same ms) | none |
| S13 | T046 | 14770 `ERROR r-0002` for `ERROR r-0003` (wrong id) | differs | yes (wrong-id rule) | C7, C8 (id written, same ms) | G2.final, G3 (id written, same ms) |
| S14 | T151 | 8534 state `TURNING_TO_LEFT r-0002` for `INITIAL` on arrival | differs | yes | C3 (handled, same ms) | G6b (handled, same ms) |
| S15 | T180 | 55 the state line where `motor_start` is expected (the start never logged) | differs | yes | none | none |
| S16 | T111 | 10342 state `LEFT r-0003` for `TURNING_TO_RIGHT` | differs | yes | C3 (handled, same ms) | P1 (handled, 3,000 ms later) |
| S17 | T191 | 3000 `motor_stop r-0001`, 54 ms early (the reference has `recv STATUS s-0003` there) | differs | **no** | none | none |
| S18 | none | none | conforms: right | – | none | none |
| S19 | T139 | 21716 `motor_start r-0005` for `ERROR reason=limit` | differs | yes | C3 (handled, same ms) | none |
| S20 | T214 | 54 the state line where `motor_start` is expected (order in one ms) | differs | yes | none | none |
| S21 | none | none | conforms: right | – | none | none |
| S22 | T196 | none (did not act) | conforms: right | – | none | none |
| S23 | T037 | 55 no `motor_start r-0001` (missing; nothing executes) | differs | yes | none | none |
| S24 | T175 | 23376 `ACK r-0005` for `ERROR reason=limit` (a repeat) | differs | yes | none | G5 (handled, same ms) |

- **Request classes** (registered): "handled" is the request being handled, the reference line's id; "id
  written" is the id on the changed line; "another request" is any other.
- **The descriptions** are in the submission file.
- **S17.** The change moved r-0001's arrival from 3054 ms to 3000 ms. In the log, at 3000 ms, the device
  writes `motor_stop`, the state change and `DONE` for r-0001, then receives `STATUS s-0003` and answers
  `state=LEFT`. The tool's first mismatch is in that millisecond, on `s-0003`: the model answers
  `STATUS_REPLY s-0003 state=TURNING_TO_LEFT`. The first difference's request is r-0001, so S1 is no.

## Totals

All numbers are from `scores.json` (sha256 `da331284…`); each was counted again by hand from its per-slot rows,
and each equals the file's summary.

**Model result**
- **Changed build, the change acted:** 17 slots.
  - Verdict `differs` in 17 of 17.
  - **S1 16 of 17,** one of them by the wrong-id rule (S13). S17 is no.
  - The first mismatch is in the first difference's millisecond in 17 of 17 (Δt 0 in each).
- **S2 (content), the advisor's judgement:** the advisor compared the 17 descriptions with the actual changes
  and read none of them as wrong. Two points it raised:
  - S12 and S19 are different changes (b14 and b03), but on these plans each showed only the same behaviour
    (at LEFT, `TURN_LEFT` starts a turn to INITIAL), so the two descriptions are the same;
  - S09's description names only half of what the change does (a refusal during a turn answered `limit`); the
    other half (one at RIGHT answered `illegal`) did not act on this plan.
- **Changed build, the change did not act:** S11 and S22, right.
- **Unchanged build:** 5 of 5 right. **False mismatches: 0 of 7** (the five unchanged slots, S11 and S22).
- **Invalid runs:** none.

**Contract result**

| Set | Caught (of 17) | Slots |
| --- | --- | --- |
| Turntable's own (C1–C8) | **6** | S02, S12, S13, S14, S16, S19 |
| Generic | **8** | S02, S05, S06, S07, S13, S14, S16, S24 |
| Both (union) | **10** | S02, S05, S06, S07, S12, S13, S14, S16, S19, S24 |

- **False violations: 0 for each set** (the five unchanged slots, S11 and S22).
- **Caught by the generic set only:** S05 (P1), S06 (G6), S07 (G2.ack), S24 (G5). **By the turntable's own
  only:** S12 and S19 (C3).
- **Missed by both, 7 of 17:** S03, S04, S09, S15, S17, S20, S23 (below).
- **Each generic rule** (acting slots with a violation): G1 0, G2 3 (S02 and S13 `G2.final`, S07 `G2.ack`),
  G3 2 (S02, S13), G4 0, G5 1 (S24), G6 2 (S02, S06), G6b 2 (S02, S14), P1 2 (S05, S16).
- **The generic contracts that repeat one of the turntable's own** (`G1.motor_start` = C1, `G2.final` = C7,
  `G3` = C8) catch **2** (S02, S13), both also caught by C7 and C8. **Those that do not** catch **7** (S02,
  S05, S06, S07, S14, S16, S24).
- **Where the 20 first violations point:**

  | Set | On the request being handled | On the id written on the reply | On another request |
  | --- | --- | --- | --- |
  | Turntable's own (8) | 4 (C3: S12, S14, S16, S19) | 2 (S13 C7, C8) | 2 (S02 C7, C8, on r-0002) |
  | Generic (12) | 8 (S02 G6, G6b; S05 P1; S06 G6; S07 G2.ack; S14 G6b; S16 P1; S24 G5) | 2 (S13 G2.final, G3) | 2 (S02 G2.final, G3, on r-0002) |

  15 are in the first difference's millisecond, 5 later: S02's four on r-0002 (1,523 ms), S16's P1 (3,000 ms,
  at the turn's end).

**By the group of the change**

| Group | Acting slots | S1 | Turntable's own | Generic | Both |
| --- | --- | --- | --- | --- | --- |
| fault-triggered (S07, S09, S12, S13, S19, S24) | 6 | 6 | 3 | 3 | 5 |
| timing (S03, S04, S17) | 3 | 2 | 0 | 0 | 0 |
| effect (S06, S15) | 2 | 2 | 0 | 1 | 1 |
| order (S05, S20) | 2 | 2 | 0 | 1 | 1 |
| other (S02, S14, S16, S23) | 4 | 4 | 3 | 3 | 3 |
| **All** | **17** | **16** | **6** | **8** | **10** |

The two fault-triggered changes that should not act (S11, S22) did not act; neither had a violation.

**By whether the change has a lift twin**

| Changes | Acting slots | Generic | Turntable's own | Both |
| --- | --- | --- | --- | --- |
| On lines the lift does not have (no twin) | 7 (S07, S09, S12, S13, S14, S16, S19) | 4 (S07, S13, S14, S16) | 5 | 6 |
| With a lift twin | 10 (S02, S03, S04, S05, S06, S15, S17, S20, S23, S24) | 4 (S02, S05, S06, S24) | 1 | 4 |

## Against the predictions

| # | Registered prediction | Result |
| --- | --- | --- |
| 1 | No false mismatch on the unchanged builds | **Held** (5 of 5) |
| 2 | No false violation, for either set, on the unchanged builds or where the change did not act | **Held** (the 5 unchanged slots, S11, S22; 0 for each set) |
| 3 | The count check equals the truth file's losses and copies on every valid unchanged slot | **Held** (5 of 5: S01, S08, S10, S18 one copy of a turn request each; S21 one poll lost). Checked by `score.py` on the truth files at scoring; the analyst has not seen the truth files. |
| 4 | Every unchanged slot valid | **Held** (all 24 slots valid) |
| 5 | Where a change changed a send, a state change or an effect, the first mismatch is on that request (S1 yes) | **Did not hold on S17** (16 of 17) |
| 6 | A change that only moves a time is missed by the generic set | **Held:** S03, S04, S17 (missed by the turntable's own set too) |
| 7 | A change that only takes an undeclared transition is missed by the generic set | **Held on S12 and S19** (caught by C3 only). **Did not hold on S14 and S16:** the generic set caught both (below). |
| 8 | A change that only changes a poll reply is missed by the generic set | No such slot. S17's first mismatch is a poll reply, but its change moves a time. |
| 9 | A change that only drops a reply is missed by the generic set | **Held on S23** (no `DONE` ever; nothing executes, so no effect or state either). S07 drops an `ERROR` but sends a third `ACK` instead, which G2.ack caught: it is not only a dropped reply. |
| 10 | A change that acts only on the client side is missed by the generic set | No such slot. |
| 11 | The 2 ms comparison window | S03 (3 ms late) and S04 (50 ms early) gave a first mismatch at that output, as predicted. **S17** (54 ms early) gave its first mismatch in that output's millisecond but on another request's output, not at that output. No slot fell inside the 2 ms window. |
| 12 | Timer events carry their scheduled times; a schedule change breaks neither set by its timing alone | S03 and S04 showed at the first event whose time moved; S17 in that event's millisecond, on another request. None of the three broke either set. As predicted, apart from S17's request. |
| 13 | Same-millisecond order of a timer and an input | No change made the device take an input first. On the unchanged builds prediction 1 held. |
| 14 | The allow list | S05, S06, S15 and S20 change only the motor effect lines or their order (log lines: the Uno drives no motor). The model saw all four, as what was logged (S1 yes). No slot wrote an `error` line. No slot changed only other lines. |

- **Prediction 5 and S17.** The change acted on r-0001's arrival, and the tool's first mismatch is a poll reply
  in the same millisecond. That is a miss of S1 on the registered rule.
- **Prediction 7, S14 and S16.** Both changes only set a wrong state, and the generic set has no transition
  rule. It caught them through state names it reads: S14's arrival state, `TURNING_TO_LEFT`, is not a resting
  state, so `DONE` came with no resting state before it (G6b). S16's turning state, `LEFT`, is a resting state
  name, so the motor stop came after a resting state (P1). The prediction erred toward a miss.
- **A predicted miss is still a miss.** S03, S04, S17 and S23 are in the totals above as missed, and are listed
  under predictions 6 and 9.

## The seven slots both sets missed

In the form of the [coverage note](../notes/protocol-contract-coverage.md). Line numbers are those of
[docs/protocol-turntable.md](../protocol-turntable.md). "The language can state it" was not checked on any
data.

| Slot | Lines | Sentence | Contract | The language can state it |
| --- | --- | --- | --- | --- |
| S03, S04 | 44–45 | a new id is executed 50 ms later | none | no: the execution is a motor start or an `ERROR`, two kinds one pattern cannot hold (as on the lift). Predicted (6) |
| S17 | 59–60 | 3 s later the motor stops | none (the turntable's own set has no timer contract) | an upper bound yes (like the lift's C9); a stop that comes early, no. Predicted (6) |
| S09 | 56–58 | the reason is `limit` at the end position, `illegal` in every other case | none | no with one comparison: the right reason depends on the state at execution (gap 1). Not predicted |
| S15 | 58 | a legal command starts the motor | none: G1 bounds the start from above, G6 asks for the stop before `DONE` | yes, with `only_after` (for example `motor_stop` only after `motor_start`, per `req_id`). Not predicted |
| S20 | 58–59 | it starts the motor and the state becomes `TURNING_TO_*` (the order) | none: P1 orders the stop and the end state, nothing orders the start and the turning state | yes, with `never_after` as P1 is (`motor_start` never after `state(TURNING_TO_*)`, per `req_id`). Not predicted |
| S23 | 44–45, 60 | a new id is executed; on arrival `DONE` is sent | none: the rules bound replies from above; C2 (the client closes each command within 15 s) was not exercised in any slot | that a reply comes at all, no on the device log (gap 5). Predicted (9) |

The last three columns describe the generic set's gaps; they are candidates only (backlog). The contract files,
the rules and the bindings were not changed.

## What the results show

- **The device model found 16 of the 17 acting changes on their request,** each in the millisecond where the
  change acted, with no false mismatch on 7 quiet slots. The 17th, S17, differs in the right millisecond, on
  another request.
- **The generic set caught 8 of 17,** with no false violation. The turntable's own set caught 6, and the union
  10.
- **The generic set added four slots** the turntable's own set missed (S05, S06, S07, S24), all through rules
  that do not repeat a turntable contract (P1, G6, G2.ack, G5). The turntable's own set added two (S12, S19),
  both by C3.
- **On lines with a lift twin and lines without,** the generic set caught 4 of 10 and 4 of 7.
- **What both missed:** timing (S03, S04, S17) and a missing execution (S23), as predicted; the refusal reason
  (S09), the start-side effect (S15) and the start-side order (S20), not predicted.

## What may be claimed afterwards

The work order's sentences, with this group's limits:
- **The generic set's count on testbed-07's acting slots, 8 of 17, is a measurement:** on one protocol of the
  lift's shape, with mechanical changes, on 17 acting slots of 24. It is not evidence for a protocol of another
  shape.
- **The device comparison's result on the turntable is its first on a second system:** 17 of 17 differ, S1 16
  of 17, no false mismatch on 7 quiet slots.
- **"No false mismatch on the turntable's no-defect logs"** is now measured on this group's 5 unchanged slots
  (and the 2 slots whose change did not act). Stage 1's 24 sessions stay development data.
- **A rev4 contract for the lift and C14 on a changed build are still unmeasured.**

## Departures from the registration

1. **The operator did not cut the analyst's SSH access to the Orin** (Order, steps 3 and 6; Limits). The blind's
   protection rested, from start to end, on the analyst's undertaking and on the session record. **What the
   record shows:** the analyst's last command on the Orin was the one that copied the testbed folder, wrote
   `boards.env` and checked the `MANIFEST`, at 07:14:37 KST on 2026-11-23. This session's transcript, the only
   one for this project from then on, has no command to the Orin after it.
2. **The step script was started twice,** at 07:40:46 and at 07:41:03. The second read S01's log, still being
   written, as a log with no end line, and stopped at once (exit 4). S01 ran once and is valid (its client log
   runs from 07:40:56 to 07:42:26 and ends `valid=yes`). `--past` was not used. The step script had nothing to
   stop a second copy of itself.
3. **Composition.** The ranges gave effect and order three slots each, but two changes of each could be drawn;
   one slot of each went to "other" (the assignment file's note).
4. **Two drawing rules the registration does not describe** (the operator's statement): no behaviour whose
   lift twin was drawn before or is a published defect, and at most two drawn changes on one source line. Both
   were fixed before the registration was approved, inside the hashed materials.
5. **S2 was judged by the advisor,** for the operator.

No other departure is known to the analyst.

## Limits

- **The turntable has the lift's shape with other names.** This is one protocol of that shape
  ([generic-contracts.md](../notes/generic-contracts.md), "What the turntable can and cannot show").
- **Small numbers:** 17 acting slots, 19 changes. Rates are counts, not estimates with error bars.
- **The changes are mechanical.** They come from testbed-06's operators, carried to the turntable's lines.
- **The generic rules were written from the lift.** 12 of the 19 drawn changes have a lift twin in testbed-06's
  candidate list; 7 of those twins are in testbed-05's list, which the analyst saw. By rule, no drawn change has
  a twin that was drawn before or is a published defect.
- **The fault-triggered changes are alike again:** the six that act sit in the refusal logic (lines 190, 194,
  195) and in the repeat's reply (line 122); five of them are on lines the lift does not have.
- **The blind's protection was a commitment** (Departures 1).
- **The client contracts were not exercised.** C2, C4 and C6 are `not_exercised` in all 24 slots, as in the
  dry run. The client side was not judged.
- **The device log is the suspect's statement.** S05, S06, S15 and S20 changed only the motor effect lines, and
  were seen as what was logged.
- **The advisor knows the tool** and wrote the generic rules. It sorted the candidates in its own simulator
  and ran `replayspect` on none of them, and on no slot before the submission's hash (the operator's
  statement).
- **The scoring script ran after the submission hash** (21:44:06 KST, as `scores.txt` records).
