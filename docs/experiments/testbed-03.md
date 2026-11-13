# Testbed experiment 03: a defect in the firmware, judged by fewest faults

Operator document. Do not give it to a planner.

This is stage 3 of the hardware testbed. The Uno ran the lift with or without one public device
defect compiled in (`-DLIFT_DEFECT=N`, [testbed README](../../examples/testbed-uno/README.md)
"Stage 3"). The Orin ran the client and the fault link with a known plan. Given only the client
log, `drive --fit --models` fits the log under the correct device model and under each compared
defect model. It accuses a defect only when that defect needs fewer link faults than the correct
model ([driven-replay.md](../driven-replay.md), "Device models").

The questions:

1. **Main:** on firmware with no defect, how often is a defect accused (a false accusation)?
2. On firmware with a defect, when the plan touches it: is a defect accused, is the real defect in
   the accused set, and how large is the set?
3. When the plan does not touch the defect, or touches it with no visible effect: is the verdict
   "correct model"?
4. With the real defect's model taken out of the candidates (a defect nobody modelled): what does
   the tool say?
5. The fixed fitter's first clean measurement, on the defect-off runs (correct model only).

No model is involved and nothing was spent. The registration, client logs, device logs and truth
files are outside the repository. The plans, seeds and builds are listed here.

## Setup

- **Registration:** written and hashed on 2026-11-13, before any session (sha256 `0c9d2bde…ecb33a`).
  The judging rule, plans, run order, analysis script and predictions are as registered.
- **Harness:** `4ab81e4` (main after #33), unchanged during and after the runs.
- **Fit (every log, every model):** `--usual-delay 4ms 4ms`, `--tolerance 25ms`, ranges 0–5 s
  (`--c2s-delay`, `--s2c-delay`, `--dup-extra`), `--fit-runs 20000`, `--plus-one`,
  `--random-check 100`, `--models M1,M2,M3,M4,M9,M10,M11`. Rules:
  `examples/testbed-uno/rules/testbed-client.yaml`.
- **Builds:** device log on, compiled and flashed on the Orin (arduino-cli 1.6.0, arduino:avr 1.8.8).
  The flash and RAM sizes equal the registered ones. Before each build's first session, the boot
  lines said `READY log=1` and `build defect=<build>`.

  | Build | Flag | Flash | RAM |
  | --- | --- | --- | --- |
  | off | `-DLIFT_DEFECT=0` | 5,426 B | 993 B |
  | M2 | `-DLIFT_DEFECT=2` | 5,462 B | 991 B |
  | M4 | `-DLIFT_DEFECT=4` | 5,472 B | 991 B |
  | M10 | `-DLIFT_DEFECT=10` | 5,408 B | 993 B |

- **Sessions:** 6 commands, 90 s, 115200 baud over USB serial. Each build's sessions were run by
  the registered `run_build.sh`, detached on the Orin. It checks the build line after every session.
- **Files:** the copy on the Orin matched the registered hashes: client, link, firmware, plans and
  run order.

**Defects, chosen by kind** (the rule was fixed before the simulator check):

- (i) a reply that should not exist: **M2**;
- (ii) a reply that should come and does not: **M4**;
- (iii) a reply or state with the wrong content: **M10**.

**(ii) has no pure public defect.** M4 is the only public device defect whose visible effect
includes a missing reply (the interrupted move's `DONE`). It also shows a wrong reply: `DONE` where
`ERROR` was due. No new defect was made for (ii).

**Compared models:**

- M1, M2, M3, M4, M9, M10 and M11: the published device-side defects, minus M5.
- **M5 is left out.** It shows only in the content of poll replies, which the fit does not compare.
- **M3 cannot be built:** on serial the device never sees a disconnect. It stays in the list, so
  every M3 accusation is a false accusation.

**Judging rule (as registered):**

- **Settled fit:** reproduced, minimal set complete, and no random draw with fewer faults than `f*`.
- **Candidates.** A defect model is a candidate when its fit is settled and the correct model's fit
  is either unexplained or settled with more faults.
  - A defect model that ends unexplained is not a candidate.
  - Neither is one that hits the cap without reproducing.
- **Undecided** when the correct model's fit hits the cap or a random draw finds fewer faults than
  its `f*`. Also undecided when a defect model reproduced but its minimal set is not shown or a
  random draw finds fewer.
- **A tie is no accusation.**
- **The accusation is a set:** every candidate with the fewest faults ("M1 or M2").
- **Measured verdict:** the verdict `drive --fit --models` prints (see Departures 1 for two runs
  where it differs from the rule above).

**Scoring by what happened:**

- A defect-on run counts as touched when its device log has a `defect fired` line.
- A run counts as plan realized when every fault that landed in the simulator run of the same plan,
  seed and build was applied as planned, and the number of disconnects matches.
- The measurement (question 5) uses the testbed-02 truth rules. The 29 ms threshold applies, and a
  restored value must fall within the values seen.

## Plans and runs

Plan ids in the client log header are neutral numbers `P01`…`P48`, assigned at random. Run ids are
`R001`…`R095` in run order. Think-time seeds are 300–334 and 400–439; none was used before.

**Defect on (27 runs):**

| Key | Group | Defect | Plan |
| --- | --- | --- | --- |
| t300 | touch | M2 | s2c ACK r-0002 k0 drop |
| t301 | touch | M2 | c2s MOVE_UP r-0003 k0 dup +1000 ms |
| t302 | touch | M2 | s2c ACK r-0004 k0 delay 2500 ms |
| t303 | touch | M2 | c2s MOVE_UP r-0005 k0 dup +30 ms |
| t304 | touch | M2 | s2c ACK r-0003 k0 drop; s2c DONE r-0003 k0 drop |
| t306 | touch | M4 | c2s MOVE_DOWN r-0002 k0, k1 drop; k2 delay 2500 ms |
| t307 | touch | M4 | c2s MOVE_UP r-0003 k0, k1 drop; k2 delay 2500 ms |
| t308 | touch | M4 | c2s MOVE_DOWN r-0004 k0, k1 drop; k2 delay 2500 ms |
| t309 | touch | M4 | c2s MOVE_UP r-0005 k0, k1 drop; k2 delay 2500 ms |
| t310 | touch | M4 | c2s MOVE_UP r-0003 k0, k1 drop; k2 delay 3000 ms |
| t311 | touch | M10 | disconnect over r-0002 (all attempts); c2s MOVE_UP r-0003 k0 dup +500 ms |
| t312 | touch | M10 | disconnect over r-0003; c2s MOVE_DOWN r-0004 k0 dup +500 ms |
| t313 | touch | M10 | disconnect over r-0004; c2s MOVE_UP r-0005 k0 dup +500 ms |
| t314 | touch | M10 | disconnect over r-0003; c2s MOVE_DOWN r-0004 k0 dup +1500 ms |
| t315 | touch | M10 | disconnect over r-0004; s2c ACK r-0005 k0 drop; s2c ERROR r-0005 k0 drop |
| n316 | no touch | M2 | s2c DONE r-0002 k0 drop |
| n318 | no touch | M2 | s2c ACK r-0005 k0 delay 1500 ms (late, no retry) |
| n319 | no touch | M4 | s2c ACK r-0003 k0 drop (retry, no opposite command) |
| n320 | no touch | M4 | c2s MOVE_DOWN r-0004 k0, k1 drop (the move starts late and ends in time) |
| n321 | no touch | M10 | disconnect over r-0003; s2c ERROR r-0004 k0 drop (refusal, no repeat) |
| n322 | no touch | M10 | c2s MOVE_UP r-0005 k0 dup +500 ms (repeat of an accepted id) |
| z330–z332 | no faults | M2, M4, M10 | none |
| i323 | touch, invisible | M2 | s2c ACK r-0003 k0 drop; s2c ERROR r-0003 k0 drop |
| i324 | touch, invisible | M2 | c2s MOVE_UP r-0005 k0 dup +30 ms; s2c ERROR r-0005 k0 drop |
| i325 | touch, invisible | M10 | disconnect over r-0003; c2s MOVE_DOWN r-0004 k0 dup +500 ms; s2c DONE r-0004 k0 drop; s2c ERROR r-0004 k1 drop |

The number in a key is the run's think-time seed.

**Disconnect over r-000N:**

- It is anchored on `s2c DONE` of the previous command and starts 200 ms before command N is sent
  (the seed's think time).
- It lasts 6.7 s, so every attempt is lost and the client has given up before the link returns.

A fault keyed on a message that only one build sends does not land on the other build: the `ERROR`
or `DONE` in i323–i325.

**Defect off (68 runs):**

- **Paired (21):** the 21 touch and no-touch plans above, with the same seeds, on the off build.
- **No faults (3):** seeds 330–332.
- **Mimic (4):** the M4 mimic plan, keys m326–m329, on four commands:
  - r-k k0 and k1 dropped;
  - s2c ACK r-k k0 delayed 2500 ms (the device's first `ACK` for that id);
  - s2c DONE r-k k0 dropped.

  The `DONE` of a move is really lost on the link, and M4 explains exactly that with no fault (the
  next command interrupts the move). The correct model needs 4 faults, M4 needs 3.
  - m326: r-0002 (MOVE_DOWN);
  - m327: r-0003 (MOVE_UP);
  - m328: r-0004 (MOVE_DOWN);
  - m329: r-0005 (MOVE_UP).

  **M3 cannot be mimicked on this link.** The link loses every message held across the start of a
  disconnect, so no link fault can put a `DONE` right after a reconnect.
- **Measurement (40):** 20 plans × seeds 400–419 and 420–439 (keys q01–q20):

| Key | Plan |
| --- | --- |
| q01 | c2s MOVE_UP r-0001 k0 delay 60 ms |
| q02 | s2c ACK r-0003 k0 delay 70 ms |
| q03 | s2c DONE r-0002 k0 delay 150 ms |
| q04 | c2s MOVE_DOWN r-0004 k0 drop |
| q05 | s2c ACK r-0005 k0 drop |
| q06 | s2c DONE r-0003 k0 drop |
| q07 | c2s MOVE_UP r-0005 k0 dup +400 ms |
| q08 | s2c DONE r-0004 k0 dup +200 ms |
| q09 | c2s STATUS s-0007 drop |
| q10 | s2c STATUS_REPLY s-0012 delay 400 ms |
| q11 | disconnect 1.2 s, 500 ms after c2s MOVE_DOWN r-0002 |
| q12 | s2c ACK r-0002 k0 delay 2300 ms (the retry answered first) |
| q13 | c2s MOVE_UP r-0003 k0 drop; s2c ACK r-0003 k0 drop (the retry's `ACK`) |
| q14 | s2c ACK r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 delay 300 ms |
| q15 | disconnect 1 s, 1 s after s2c ACK r-0005; s2c DONE r-0005 dup +100 ms |
| q16 | c2s MOVE_DOWN r-0002 k0 dup +200 ms; s2c ACK r-0002 k0 drop (**not minimal**) |
| q17 | s2c ACK r-0004 k0 delay 200 ms; s2c DONE r-0004 k0 delay 200 ms (**not minimal**) |
| q18 | s2c ACK r-0001 k0 drop; s2c DONE r-0003 k0 delay 80 ms; c2s STATUS s-0020 drop |
| q19 | c2s MOVE_UP r-0005 k0 delay 120 ms; s2c DONE r-0006 k0 drop |
| q20 | disconnect 0.8 s, 1 s after s2c ACK r-0003; s2c ACK r-0006 k0 dup +50 ms |

**Plan ids:**

| Id | Key | Id | Key | Id | Key | Id | Key |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P01 | q20 | P13 | q06 | P25 | q18 | P37 | t310 |
| P02 | q14 | P14 | n322 | P26 | q17 | P38 | t303 |
| P03 | n319 | P15 | q10 | P27 | q13 | P39 | q16 |
| P04 | t309 | P16 | t313 | P28 | n320 | P40 | t306 |
| P05 | q15 | P17 | n316 | P29 | m329 | P41 | t304 |
| P06 | i325 | P18 | t311 | P30 | t314 | P42 | t308 |
| P07 | q19 | P19 | q08 | P31 | q07 | P43 | t312 |
| P08 | q02 | P20 | q09 | P32 | q03 | P44 | m327 |
| P09 | q01 | P21 | i324 | P33 | q12 | P45 | q04 |
| P10 | t300 | P22 | m326 | P34 | n318 | P46 | t302 |
| P11 | m328 | P23 | t307 | P35 | t301 | P47 | q05 |
| P12 | q11 | P24 | n321 | P36 | t315 | P48 | i323 |

**Run order:** by build, so the board was flashed four times: off (68), M2 (10), M4 (8), M10 (9).
Total 95. Inside a build the order was random.

**All 95 sessions were valid on their first start.**

- No session lacked `READY`. No device error line appeared and the board did not reset.
- Every device log named its build.
- Every plan was realized.
- The observed class equals the planned class in 27 of 27 defect-on runs. `defect fired` appeared
  in the 15 touch and 3 invisible runs, and in none of the 9 others.
- No off-build run had a `defect fired` line.

## Results

Every run. Columns `correct` and M1–M11 give each model's `f*`:

- `u`: unexplained;
- `cap`: the run cap ended the fit before anything reproduced.

The other columns:

- **Diff.:** the correct model's `f*` minus the accused set's (`u`: the correct model is
  unexplained).
- **Capped:** the number of the run's 8 fits that the cap ended. It includes fits that reproduced
  but did not complete their minimal set.
- **Fired:** the number of `defect fired` lines in the device log.

| Run | Build | Plan | Group | Seed | Verdict | Diff. | correct | M1 | M2 | M3 | M4 | M9 | M10 | M11 | Capped | Fired |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R001 | off | P09 (q01) | measurement | 400 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R002 | off | P12 (q11) | measurement | 430 | correct model | — | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| R003 | off | P09 (q01) | measurement | 420 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R004 | off | P34 (n318) | paired | 318 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R005 | off | P30 (t314) | paired | 314 | correct model | — | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R006 | off | P22 (m326) | mimic | 326 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 0 |
| R007 | off | P32 (q03) | measurement | 402 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R008 | off | P26 (q17) | measurement | 416 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R009 | off | P12 (q11) | measurement | 410 | correct model | — | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| R010 | off | P27 (q13) | measurement | 412 | correct model | — | 2 | 3 | 3 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R011 | off | P01 (q20) | measurement | 419 | correct model | — | 1 | 2 | 2 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R012 | off | P07 (q19) | measurement | 438 | correct model | — | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R013 | off | P07 (q19) | measurement | 418 | correct model | — | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R014 | off | P40 (t306) | paired | 306 | correct model | — | cap | cap | cap | cap | cap | cap | cap | cap | 8 | 0 |
| R015 | off | P45 (q04) | measurement | 423 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R016 | off | P45 (q04) | measurement | 403 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R017 | off | P16 (t313) | paired | 313 | correct model | — | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R018 | off | P28 (n320) | paired | 320 | correct model | — | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R019 | off | P01 (q20) | measurement | 439 | correct model | — | 1 | 2 | 2 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R020 | off | P36 (t315) | paired | 315 | correct model | — | 2 | 3 | 2 | 3 | 2 | 2 | 3 | 2 | 0 | 0 |
| R021 | off | P24 (n321) | paired | 321 | correct model | — | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R022 | off | P27 (q13) | measurement | 432 | correct model | — | 2 | 3 | 3 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R023 | off | P08 (q02) | measurement | 401 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R024 | off | P31 (q07) | measurement | 406 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R025 | off | P19 (q08) | measurement | 427 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R026 | off | P29 (m329) | mimic | 329 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 0 |
| R027 | off | P17 (n316) | paired | 316 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R028 | off | P32 (q03) | measurement | 422 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R029 | off | P14 (n322) | paired | 322 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R030 | off | P35 (t301) | paired | 301 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R031 | off | P25 (q18) | measurement | 417 | correct model | — | 3 | 4 | 4 | 3 | 3 | 3 | 3 | 3 | 0 | 0 |
| R032 | off | P37 (t310) | paired | 310 | correct model | — | 3 | 3 | 3 | 3 | cap | 3 | 3 | 3 | 1 | 0 |
| R033 | off | P47 (q05) | measurement | 424 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R034 | off | P13 (q06) | measurement | 405 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R035 | off | P43 (t312) | paired | 312 | correct model | — | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R036 | off | P33 (q12) | measurement | 411 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R037 | off | P23 (t307) | paired | 307 | correct model | — | cap | cap | cap | cap | cap | cap | cap | cap | 8 | 0 |
| R038 | off | P15 (q10) | measurement | 409 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R039 | off | none (z332) | paired | 332 | correct model | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R040 | off | P03 (n319) | paired | 319 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R041 | off | P05 (q15) | measurement | 414 | correct model | — | 1 | 2 | 2 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R042 | off | P05 (q15) | measurement | 434 | correct model | — | 1 | 2 | 2 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R043 | off | P15 (q10) | measurement | 429 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R044 | off | P10 (t300) | paired | 300 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R045 | off | P13 (q06) | measurement | 425 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R046 | off | P31 (q07) | measurement | 426 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R047 | off | none (z330) | paired | 330 | correct model | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R048 | off | P02 (q14) | measurement | 433 | correct model | — | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R049 | off | P42 (t308) | paired | 308 | undecided | — | 3 | 3 | 3 | 3 | cap | 3 | 3 | 3 | 8 | 0 |
| R050 | off | P39 (q16) | measurement | 415 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R051 | off | P20 (q09) | measurement | 408 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R052 | off | P08 (q02) | measurement | 421 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R053 | off | P44 (m327) | mimic | 327 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 0 |
| R054 | off | P33 (q12) | measurement | 431 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R055 | off | P04 (t309) | paired | 309 | correct model | — | 3 | 3 | 3 | 3 | u | 3 | 3 | 3 | 0 | 0 |
| R056 | off | P19 (q08) | measurement | 407 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R057 | off | P39 (q16) | measurement | 435 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R058 | off | none (z331) | paired | 331 | correct model | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R059 | off | P47 (q05) | measurement | 404 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R060 | off | P46 (t302) | paired | 302 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R061 | off | P41 (t304) | paired | 304 | correct model | — | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R062 | off | P02 (q14) | measurement | 413 | correct model | — | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R063 | off | P20 (q09) | measurement | 428 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R064 | off | P38 (t303) | paired | 303 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R065 | off | P18 (t311) | paired | 311 | correct model | — | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R066 | off | P11 (m328) | mimic | 328 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 0 |
| R067 | off | P26 (q17) | measurement | 436 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R068 | off | P25 (q18) | measurement | 437 | correct model | — | 3 | 4 | 4 | 3 | 3 | 3 | 3 | 3 | 0 | 0 |
| R069 | M2 | none (z330) | no faults | 330 | correct model | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R070 | M2 | P17 (n316) | no touch | 316 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R071 | M2 | P41 (t304) | touch | 304 | suspected: M1 or M2 | u | u | 2 | 2 | u | u | u | u | u | 0 | 1 |
| R072 | M2 | P10 (t300) | touch | 300 | suspected: M1 or M2 | u | u | 1 | 1 | u | u | u | u | u | 0 | 1 |
| R073 | M2 | P34 (n318) | no touch | 318 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R074 | M2 | P21 (i324) | invisible | 324 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 1 |
| R075 | M2 | P38 (t303) | touch | 303 | suspected: M1 or M2 or M9 | u | u | 1 | 1 | u | u | 1 | u | u | 0 | 1 |
| R076 | M2 | P48 (i323) | invisible | 323 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 1 |
| R077 | M2 | P35 (t301) | touch | 301 | suspected: M1 or M2 | u | u | 1 | 1 | u | u | u | u | u | 0 | 1 |
| R078 | M2 | P46 (t302) | touch | 302 | suspected: M1 or M2 | u | u | 1 | 1 | u | u | u | u | u | 0 | 1 |
| R079 | M4 | P23 (t307) | touch | 307 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 1 |
| R080 | M4 | P42 (t308) | touch | 308 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 1 |
| R081 | M4 | P04 (t309) | touch | 309 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 1 |
| R082 | M4 | P37 (t310) | touch | 310 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 1 |
| R083 | M4 | P28 (n320) | no touch | 320 | correct model | — | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 |
| R084 | M4 | none (z331) | no faults | 331 | correct model | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R085 | M4 | P03 (n319) | no touch | 319 | correct model | — | 1 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| R086 | M4 | P40 (t306) | touch | 306 | suspected: M4 | 1 | 4 | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 0 | 1 |
| R087 | M10 | P06 (i325) | invisible | 325 | correct model | — | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| R088 | M10 | P18 (t311) | touch | 311 | suspected: M10 | u | u | u | u | u | u | u | 1 | u | 0 | 1 |
| R089 | M10 | P24 (n321) | no touch | 321 | correct model | — | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 0 | 0 |
| R090 | M10 | P43 (t312) | touch | 312 | suspected: M10 | u | u | u | u | u | u | u | 1 | u | 0 | 1 |
| R091 | M10 | P36 (t315) | touch | 315 | suspected: M10 | u | u | u | u | u | u | u | 2 | u | 0 | 1 |
| R092 | M10 | P30 (t314) | touch | 314 | suspected: M10 | u | u | u | u | u | u | u | 1 | u | 0 | 1 |
| R093 | M10 | none (z332) | no faults | 332 | correct model | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R094 | M10 | P16 (t313) | touch | 313 | suspected: M10 | u | u | u | u | u | u | u | 1 | u | 0 | 1 |
| R095 | M10 | P14 (n322) | no touch | 322 | correct model | — | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |

**Fits the cap ended** (25 of 760, in 4 runs). All four runs are defect-off runs paired with M4
touch plans, whose third attempt is delayed 2.5–3 s after two drops.

| Run | Plan | What the cap ended |
| --- | --- | --- |
| R014 | t306 | All 8 fits, the correct model's included: none reproduced in 20,000 runs. |
| R037 | t307 | All 8 fits, the same. |
| R049 | t308 | Correct model and M1, M2, M3, M9, M10, M11: reproduced with `f*` 3 (2 explanations) but did not complete the minimal set in 20,000 runs. M4: did not reproduce. |
| R032 | t310 | The M4 fit only. The other 7 settled in 916–1,440 runs. |

The M4 paired run t309 (R055) settled for every model. The M4 model ended unexplained there, so it
was no candidate.

**Measurement** (correct model, the 64 defect-off runs outside the mimic group). The columns follow
testbed-02:

- **Truth:** the number of faults in the truth set.
- **In set:** the truth is one of the minimal explanations.
- **In `f*`/`f*+1`:** the truth is among the `f*` or the `f*+1` explanations.
- **Common real / reported:** the command faults common to every minimal explanation. Poll faults
  are left out.

| Run | Plan | Truth | `f*` | In set | In `f*`/`f*+1` | Common real / reported |
| --- | --- | --- | --- | --- | --- | --- |
| R001 | q01 | 1 | 1 | yes | yes | 1 / 1 |
| R002 | q11 | 0 | 0 | yes | yes | 0 / 0 |
| R003 | q01 | 1 | 1 | yes | yes | 1 / 1 |
| R004 | n318 | 1 | 1 | yes | yes | 1 / 1 |
| R005 | t314 | 1 | 1 | yes | yes | 0 / 0 |
| R007 | q03 | 1 | 1 | yes | yes | 1 / 1 |
| R008 | q17 (not minimal) | 2 | 1 | no | yes | 0 / 1 |
| R009 | q11 | 0 | 0 | yes | yes | 0 / 0 |
| R010 | q13 | 2 | 2 | yes | yes | 2 / 2 |
| R011 | q20 | 1 | 1 | yes | yes | 0 / 0 |
| R012 | q19 | 2 | 2 | yes | yes | 2 / 2 |
| R013 | q19 | 2 | 2 | yes | yes | 2 / 2 |
| R014 | t306 | 3 | cap | no | no | 0 / 0 |
| R015 | q04 | 1 | 1 | yes | yes | 1 / 1 |
| R016 | q04 | 1 | 1 | yes | yes | 1 / 1 |
| R017 | t313 | 1 | 1 | yes | yes | 0 / 0 |
| R018 | n320 | 2 | 2 | yes | yes | 2 / 2 |
| R019 | q20 | 1 | 1 | yes | yes | 0 / 0 |
| R020 | t315 | 2 | 2 | yes | yes | 2 / 2 |
| R021 | n321 | 1 | 1 | yes | yes | 1 / 1 |
| R022 | q13 | 2 | 2 | yes | yes | 2 / 2 |
| R023 | q02 | 1 | 1 | yes | yes | 1 / 1 |
| R024 | q07 | 1 | 1 | yes | yes | 0 / 0 |
| R025 | q08 | 1 | 1 | yes | yes | 0 / 0 |
| R027 | n316 | 1 | 1 | yes | yes | 1 / 1 |
| R028 | q03 | 1 | 1 | yes | yes | 1 / 1 |
| R029 | n322 | 1 | 1 | yes | yes | 0 / 0 |
| R030 | t301 | 1 | 1 | yes | yes | 0 / 0 |
| R031 | q18 | 3 | 3 | yes | yes | 2 / 2 |
| R032 | t310 | 3 | 3 | yes | yes | 3 / 3 |
| R033 | q05 | 1 | 1 | yes | yes | 1 / 1 |
| R034 | q06 | 1 | 1 | yes | yes | 1 / 1 |
| R035 | t312 | 1 | 1 | yes | yes | 0 / 0 |
| R036 | q12 | 1 | 1 | yes | yes | 1 / 1 |
| R037 | t307 | 3 | cap | no | no | 0 / 0 |
| R038 | q10 | 1 | 1 | yes | yes | 0 / 0 |
| R039 | z332 | 0 | 0 | yes | yes | 0 / 0 |
| R040 | n319 | 1 | 1 | yes | yes | 1 / 1 |
| R041 | q15 | 1 | 1 | yes | yes | 0 / 0 |
| R042 | q15 | 1 | 1 | yes | yes | 0 / 0 |
| R043 | q10 | 1 | 1 | yes | yes | 0 / 0 |
| R044 | t300 | 1 | 1 | yes | yes | 1 / 1 |
| R045 | q06 | 1 | 1 | yes | yes | 1 / 1 |
| R046 | q07 | 1 | 1 | yes | yes | 0 / 0 |
| R047 | z330 | 0 | 0 | yes | yes | 0 / 0 |
| R048 | q14 | 2 | 2 | yes | yes | 0 / 0 |
| R049 | t308 | 3 | 3 | yes | yes | 1 / 1 |
| R050 | q16 (not minimal) | 2 | 1 | no | yes | 0 / 1 |
| R051 | q09 | 1 | 1 | yes | yes | 0 / 0 |
| R052 | q02 | 1 | 1 | yes | yes | 1 / 1 |
| R054 | q12 | 1 | 1 | yes | yes | 1 / 1 |
| R055 | t309 | 3 | 3 | yes | yes | 1 / 1 |
| R056 | q08 | 1 | 1 | yes | yes | 0 / 0 |
| R057 | q16 (not minimal) | 2 | 1 | no | yes | 0 / 1 |
| R058 | z331 | 0 | 0 | yes | yes | 0 / 0 |
| R059 | q05 | 1 | 1 | yes | yes | 1 / 1 |
| R060 | t302 | 1 | 1 | yes | yes | 1 / 1 |
| R061 | t304 | 2 | 2 | yes | yes | 1 / 1 |
| R062 | q14 | 2 | 2 | yes | yes | 0 / 0 |
| R063 | q09 | 1 | 1 | yes | yes | 0 / 0 |
| R064 | t303 | 1 | 1 | yes | yes | 0 / 0 |
| R065 | t311 | 1 | 1 | yes | yes | 0 / 0 |
| R067 | q17 (not minimal) | 2 | 1 | no | yes | 0 / 1 |
| R068 | q18 | 3 | 3 | yes | yes | 2 / 2 |

### By analysis

**1. Main: false accusations on the off build (68 runs).**

| Off-build runs | Runs | Accused | Undecided | "Correct model" |
| --- | --- | --- | --- | --- |
| Measurement + paired + no faults | 64 | **0** | 1 (R049) | 63 |
| Mimic (M4) | 4 | 4: "M4", difference 1 each | 0 | 0 |

**The main indicator, two readings.** No false accusation in either, but the denominators differ.

- **By the tool's output** (the registered measure): **0 of 64**.
- **By the rule's wording:** **0 of the 62 runs judged.** 2 runs (R014, R037) were not judged: no
  model, the correct one included, reproduced the log, so no comparison took place. The tool printed
  "correct model" for them (Departures 1). They are no evidence that no defect is accused.

No run accused M3.

**2. Defect on, touched (15 runs).** Every run accused a defect, and the real defect is in the
accused set in 15 of 15.

| Defect | Runs | Accused set | Difference |
| --- | --- | --- | --- |
| M2 | 5 | "M1 or M2" in 4; "M1 or M2 or M9" in 1 (R075, t303: the 30 ms copy is inside M9's 50 ms window) | correct model unexplained |
| M4 | 5 | "M4" in 5 | 1 in 5 (correct 4, M4 3) |
| M10 | 5 | "M10" in 5 | correct model unexplained (M10 `f*` 1 in 4, 2 in R091) |

**3. Not touched and no faults (9 runs):** "correct model" in 9 of 9.

**4. Touched, not visible (3 runs: R074, R076, R087):**

- No accusation in 3 of 3.
- `defect fired` appears in the device log in 3 of 3.
- These runs are reported apart, outside the main denominator.

**5. Diagnostic, the rule unchanged.** Suppose a defect were accused only with a difference of 2 or
more, counting an unexplained correct model as 2 or more.

- **False accusations:** 0. The 4 mimic accusations disappear.
- **Missed defects:** 5, the 5 M4 runs. The M2 and M10 accusations stay.
- **The registered rule:** 4 false accusations, all in the predicted mimic group, and no missed
  defect.

**6. Without the real defect's model** (the same fits, with the real defect taken out of the
candidates):

| Defect | Verdict without the real model | Correct model `f*` vs the paired off run |
| --- | --- | --- |
| M2 | "M1" in 4; "M1 or M9" in 1 (R075) | unexplained in 5 of 5 |
| M10 | "correct model" in 5 of 5 | unexplained in 5 of 5 |
| M4 | "correct model" in 5 of 5 | one more in 3 (R080, R081, R082). No value in 2: R079's and R086's paired off runs (R037, R014) have no correct-model `f*` |

**7. Simulator touch vs hardware:** the simulator class and `defect fired` agree in 27 of 27
defect-on runs.

**8. Fixed fitter measurement** (correct model, 64 defect-off logs):

- **Wrong "unexplained": 0.**
- **Truth in the minimal set where minimal: 58 of 60.** The misses are R014 and R037, where the
  correct model's fit did not reproduce within the cap.
- **Truth in the `f*` or `f*+1` set: 62 of 64.** The misses are the same two.
- **Common command faults real: 42 of 46 (91%).** The 4 false ones are the four runs of the two
  plans that are not minimal by design: q16 (R050, R057) and q17 (R008, R067). Each reads the truth
  as one delay.

## What the results show

**No false accusation on the off build outside the mimic group:** 0 of 64 by the tool's output,
0 of the 62 runs judged by the rule's wording (R014 and R037 were not judged). M3 was never accused,
although it cannot be built. A defect is accused only where a defect is present, or where a link
loss was set up on purpose to look exactly like one.

**When a touched defect is visible in the client log, the tool names a set that holds it: 15 of
15.**

- **M10:** named alone. It answers a repeated refused request with `DONE` instead of the stored
  `ERROR`, a reply no link fault can produce.
- **M2:** always named with M1. M2 records an id only at `DONE`, so a repeat during the move is
  handled as new. M1, with no de-duplication at all, produces the same extra reply in these logs,
  and one log does not separate them. Once M9 joined the set as well: it records a new id 50 ms
  late, and the 30 ms copy fell inside that window.
- **M4:** named alone, but only by a difference of one fault. The mimic runs show the same
  difference on a firmware without a defect. In one log, a device that interrupts a move and never
  sends its `DONE`, and a link that loses that `DONE`, are one fault apart. Fewest faults cannot tell
  them apart. The diagnostic
  makes this concrete: a rule that demands two faults' difference removes the 4 false accusations
  and all 5 true M4 accusations together.

**Without the real model, the three defects behave as predicted.**

- **M2:** turns into a confident accusation of a neighbouring defect (M1). This is the most
  misleading case.
- **M10:** leaves the correct model unexplained with nothing accused. This is the clearest sign of
  an unknown defect.
- **M4:** leaves one more fault than the paired off run, where that run has a value. It would not
  stand out.

**The search is the weak point on the off-build retries.** The three-attempt retries with a
2.5–3 s late third attempt (the off-build pairs of the M4 touch plans) are the hardest logs here.

- **R014 and R037:** no model reproduced in 20,000 runs.
- **R049:** every model but M4 reproduced with `f*` 3 but did not complete the minimal set.

The simulator campaign capped only the M4 model on these plans. The real logs are harder for the
search than the simulator's, and the cause is not diagnosed here (Follow-up). These runs cost the
measurement two of its 60 "truth in the set" and leave R079's and R086's analysis 6 value empty.
They caused no accusation.

## Predictions

Registered before the runs:

| | Prediction | Result |
| --- | --- | --- |
| a | Main: false accusations outside the mimic plans 0 of 64; M3 accusations 0. | **Right:** 0 of 64 by the tool's output; by the rule's wording 0 of the 62 runs judged, with 2 not judged (R014, R037). M3 0. |
| b | Mimic plans: M4 accused in 4 of 4, difference 1 each. | **Right:** 4 of 4, difference 1 each. |
| c | Undecided verdicts: 0. Fits ended by the cap: 4, the M4 model in the paired off runs of 306, 307, 308 and 310; none elsewhere. | **Wrong.** The cap struck in exactly those four runs, but ended 25 fits, not 4. In R014 (306), R037 (307) and R049 (308) it ended the correct model's fit too. Undecided: 1 (R049) by the tool, 3 by the rule's wording (Departures 1). |
| d | Defect on, touched (15): accused 15 of 15; real defect in the set 15 of 15. M2 → "M1 or M2" in 4, "M1 or M2 or M9" in 1 (303); M4 → "M4" in 5 (difference 1); M10 → "M10" in 5 (correct model unexplained). | **Right:** every part. |
| e | Not touched and no faults (9): "correct model" 9 of 9. | **Right:** 9 of 9. |
| f | Touched, not visible (3): no accusation 3 of 3; `defect fired` 3 of 3. | **Right:** 3 of 3 and 3 of 3. |
| g | Diagnostic (difference ≥ 2 only): the M2 and M10 accusations stay; M4 0 of 5; the 4 mimic false accusations disappear. | **Right.** |
| h | Without the real model. M2: M1 accused 5 of 5 (303: "M1 or M9"), the correct model unexplained. M10: no accusation, the correct model unexplained, 5 of 5. M4: no accusation, the correct model's `f*` one more than the paired off run, 5 of 5. | **Right for M2 and M10. Right in part for M4:** no accusation 5 of 5; one more in the 3 runs where the paired off run has an `f*`, and no value in 2 (R079, R086). |
| i | Simulator class and `defect fired` agree in 27 of 27. | **Right:** 27 of 27. |
| j | Fitter measurement on hardware: wrong unexplained 0; truth in the minimal set in at least 54 of 60; in the minimal or `f*+1` set in at least 60 of 64; common command faults real at least 85%. | **Right:** 0; 58 of 60; 62 of 64; 42 of 46 (91%). The simulator figures were 60, 64 and 44 of 48: the two capped runs make the difference. |
| k | 95 of 95 reproduced or judged; no run invalid. | **Right in part:** no run invalid. 93 of 95 reproduced or judged. In R014 and R037 no model reproduced, and the printed "correct model" is not a judgment of a fit. |

The wrong and partial results come from the same place: the search did not finish on three
off-build retry logs. Every prediction about accusations (a, b, d–g, and h for M2 and M10) came out
as written.

## Departures from the registration

1. **The tool printed "correct model" for runs it did not judge.** This is a defect of the tool,
   and the registered `analyze.py`'s copy of the rule had the same gap.
   - **What happened.** The registration says the verdict is undecided when the correct model's fit
     hits the cap. In R014 and R037 the cap ended every fit, the correct model's included, and the
     tool printed "correct model". The cap list was named in full.
   - **Why.** `judge_models` marks a run undecided only through a defect model that reproduced. When
     nothing reproduced, it falls through to "correct model". #33 made sure the cap is not reported
     as innocence for a defect model, but missed the case where the correct model itself is capped.
   - **Why the checks missed it.** The registered analysis checks its own copy of the rule against
     the tool on every run, and that copy has the same gap. So the dry run could not show it. The
     simulator never capped the correct model either.
   - **How it is counted.** Per the registration, the measured verdict is the printed one: 0 false
     accusations of 64. Under the rule's wording, 62 of the 64 runs were judged (0 false
     accusations), and R014 and R037 were not judged. With R049, the off build then has 3 undecided
     runs and 61 "correct model".
2. **Flashing approvals.** The registration says the next build is flashed only after the operator
   approves. The operator approved the off and M2 builds one at a time. After M2's flash the
   operator approved M4 and M10 together, with stop conditions:
   - stop on a build-line mismatch;
   - stop on any invalid or retried run.

   Neither condition occurred. The agent flashed every build, as the registration allows after
   asking.
3. **Read after the analysis, not registered:** the `--fit-out` model rows of the four capped runs
   (status, runs and explanation count, in the table above). They are outputs of the registered run;
   nothing was fitted again.

No other departure: no session was restarted, no file in the registration's hash table changed,
and the analysis ran once. After the last build the board was flashed back to the off build
(`READY log=1`, `build defect=none`).

## Limits

- **One log, one fault apart.**
  - A device that skips a reply looks exactly like a lost reply in one log (M4 and the mimic group).
  - Telling them apart needs repetition over runs: a defect fails the same way every time, a loss
    does not. This experiment does not measure that.
- **A defect nobody modelled is never accused.** Without its model, M2 was reported as M1. M4 was
  not noticed. Only M10 left a clear sign (an unexplained correct model).
- **The cap.**
  - The search did not finish on three of the 64 off-build logs.
  - A defect model that hits the cap without reproducing is no candidate. That is not proven: more
    runs might reproduce it with fewer faults.
  - When nothing reproduces, the tool prints "correct model" (Departures 1).
- **Poll-reply content is not compared,** so a defect seen only there (M5) is invisible.
- **M3 exists neither as a build nor as a mimic on this link.** It stays among the compared models,
  and any M3 accusation is false. None happened.
- **The mimic group has one kind only** (M4: a lost `DONE` of an interrupted move). False
  accusations of other kinds were not provoked on purpose. The 62 judged off-build runs outside the
  mimic group and the 87 development logs are the only evidence about them.
- **Value ranges** are what was seen in the explanations found, not every possible value.
- **Hardware timing:**
  - The plans were chosen with the simulator. Every planned class held on hardware (27 of 27).
  - A defect-on build writes a `defect fired` line on the serial link where the defect fires, so
    its replies there come a few milliseconds later than on the off build.
- **Defects by kind:** three, one run per plan and seed. Rates are counts out of small groups (15
  touched, 64 off-build), not estimates with error bars.
