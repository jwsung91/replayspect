# Testbed experiment 04: the device log against the model, with a blind group

Operator document. Do not give it to a planner.

This is the first hardware measurement of two sources, stage 1 ([device-log.md](../device-log.md)).
The Uno ran the lift with no defect or with one public device defect compiled in. The Orin ran the
client and the fault link with a known plan. The analysis read the device's own log with
`replayspect device`:
- the device model is fed what the device received, at the device's times, and each model either
  conforms or gives its first mismatch;
- with the client log, losses and extra copies are counted per message and request id;
- the lift contracts are judged on the device log alone.

No fit is involved. A blind group followed: firmware the operator changed in ways the agent did not
know.

The questions (as registered):

1. **Main:** on firmware with no defect, how often does the correct model fail to conform (a false
   mismatch)? Does the same-millisecond rule (timers before an input in the same millisecond) cause
   false mismatches on new logs, or hide a defect?
2. (a) Does the method tell M4 from a real loss at the same place? (b) A request copy from an `ACK`
   copy? (d) Is the correct model's first mismatch on the request where the defect fired?
3. Does the count check equal the truth, and does it miss exactly the planned cancellations?
4. Are M1 and M2 told apart where the run repeats a request after `DONE`, and not where it does not?
5. What do partial device logs allow, and what do the contracts alone find?
6. **Blind:** on firmware with a change the agent does not know, does the first mismatch point at
   where the change acted, and does its content match what the change does?

No model is involved and nothing was spent. The registration, client logs, device logs, truth files
and the blind assignment are outside the repository. The plans, seeds and builds are listed here.

## Setup

- **Registration:** written and hashed on 2026-11-14, before any session (sha256
  `08d4892f…b7ceb551`). The plans, run order, analysis script and predictions are as registered.
  Every prediction is the registered analysis applied to simulated logs of the same plan, seed and
  build.
- **Harness:** `474432c` (main after #43), unchanged during and after the runs. The analysis
  refuses to run at another commit. Before the analysis, all 27 files in the registration's hash
  table matched.
- **Tool, every run:**
  - `replayspect ingest` on the client log, with `examples/testbed-uno/rules/testbed-client.yaml`;
  - then `replayspect device` with `--models device --contracts contracts/lift.v0.yaml`, the
    completeness declaration of the condition, and `--complete client:send,recv`;
  - the default window: `--late 2ms`, nothing early;
  - five versions of each device log (Results, "Partial device logs").
- **Contracts:** `contracts/lift.v0.yaml` unchanged. It was last changed on 2026-11-07, before any
  real device log existed.
- **Builds:** device log on, compiled on the Orin from `474432c` (arduino-cli 1.6.0, arduino:avr
  1.8.8). Each was flashed from its registered `.hex` after a hash check. Before each build's first
  session, the boot lines said `READY log=1` and `build defect=<build>`.

  | Build | Flag | Flash | RAM | `.hex` sha256 |
  | --- | --- | --- | --- | --- |
  | off | `-DLIFT_DEFECT=0` | 5,334 B | 977 B | `e08dbae1…` |
  | M2 | `-DLIFT_DEFECT=2` | 5,374 B | 975 B | `d8d9a27c…` |
  | M4 | `-DLIFT_DEFECT=4` | 5,366 B | 975 B | `6b1dc32e…` |
  | M10 | `-DLIFT_DEFECT=10` | 5,286 B | 975 B | `365a6f6c…` |

- **Sessions:** 6 commands, 90 s, 115200 baud, `client.py --expect-build <build>`. The registered
  `run_build.sh` ran each build's sessions, detached on the Orin.
- **Seeds:** 500–582 for the 83 registered runs and 700–726 for the blind pool. No earlier
  experiment used them. The 182 earlier real logs are development data.

## Plans and runs

59 plans, run ids `R001`…`R083` in run order: builds off (56), M2 (12), M4 (8), M10 (7), the order
inside a build at random. The plans are listed run by run in the table at the end.

| Group | Build | Runs | Plan |
| --- | --- | --- | --- |
| O-meas | off | 30 | 15 link-fault plans × 2 seeds: delays, drops, copies, disconnects, retries, both directions |
| O-none | off | 4 | no faults |
| A-M4 | M4 | 6 | a request's k0 and k1 lost and k2 2.5 s late, so the next (opposite) command meets the move |
| A-mimic | off | 6 | testbed-03's recipe: k0 and k1 lost, the first `ACK` 2.5 s late, the move's `DONE` lost |
| B-req | off | 6 | a command's request copied 30–500 ms later |
| B-ack | off | 6 | a command's `ACK` copied 30–500 ms later |
| C-cancel | off | 4 | a loss and a copy of the same message: 2 on the request, 2 on the `ACK` |
| D-sep | M2 | 5 | the first `ACK` lost, the retry arrives during the move, and its copy arrives after `DONE` |
| D-nosep | M2 | 5 | a request copied 1 s later, during its move |
| E-M10 | M10 | 5 | the previous command never arrives, so this one is refused; its request copied 500 ms later |
| N-touch | M2, M4, M10 | 6 | plans that do not touch the defect, 2 per build |
| Blind | operator | 8 | 5 slots with the operator's change, 3 unchanged; plans from the blind pool |

**Main denominator:** the 56 off-build runs.

## Results

**Every session was valid** on its first start: no `READY` retry, no invalid run.

| Build | Valid | Invalid | Rerun |
| --- | --- | --- | --- |
| off | 56 | 0 | 0 |
| M2 | 12 | 0 | 0 |
| M4 | 8 | 0 | 0 |
| M10 | 7 | 0 | 0 |

- **Logs:** the 249 logs (83 × client, device, truth) were copied from the Orin to the development
  machine. Their sha256 matched on both sides.
- **Plan realized:** 83 of 83. All 135 planned faults were applied as planned, and the disconnect
  counts match the simulator runs.
- **Firing:** every defect run's device log is reproduced by the harness. The defect fired in the
  21 runs planned to touch it, and in none of the 6 N-touch runs.

### Against the predictions

The registered analysis ran once. Of its 933 score entries, 890 equal the prediction file. The 43
others are 42 time stamps and the same-millisecond count, below.

| | Prediction | Result |
| --- | --- | --- |
| 1 | Main: false mismatches on the off build 0 of 56 | **0 of 56** |
| 1 | Same-millisecond rule: every rule-active off run conforms; no defect run changes between the orders | **Right:** rule-active in 2 (R009, R020), both conform; no defect run changes |
| 2a | M4: correct model differs on the opposite command, conforming set exactly {M4}; mimic: correct model conforms, the `DONE` counted lost | **6 of 6 and 6 of 6** |
| 2b | Request copy and `ACK` copy, each told apart, correct model conforms | **6 of 6 and 6 of 6** |
| 2d | First mismatch on the firing's request 21 of 21; same time in the 11 M4 and M10 runs, 50 ms later in the 10 M2 runs | **21 of 21; 11 at the same time, 10 at +50 ms** |
| 3 | Count check equal to the truth in 79 of 83; the misses are the 4 C-cancel pairs | **79 of 83, the 4 C-cancel pairs exactly** |
| 4 | D-sep {M2} 5 of 5; D-nosep {M1, M2} 5 of 5 | **5 of 5 and 5 of 5** |
| 5 | N-touch: correct model conforms 6 of 6 | **6 of 6** |
| 6 | Partial device logs (table below) | **Every entry as predicted** |
| 7 | Contracts alone (table below) | **Every entry as predicted** |

- **The 42 time stamps** are the firing time and the first-mismatch time in the 21 defect runs.
  They fell 4–22 ms later on hardware than in the simulator. The request and the gap between the
  firing and the first mismatch (0 or 50 ms) are as predicted in every run.
- **The same-millisecond rule.** The simulator predicted no rule-active run, because its timers
  fall on exact milliseconds. The registration expected about 4% on hardware (6 of 155 development
  logs). Two of 56 off-build runs were rule-active. That is the case the limits section warned
  about: an input and a timer in the same millisecond on new hardware logs. Both runs conform with
  timers first, as registered, so neither is a false mismatch.
- **The 2 ms window** was never used: no matched event of the correct model came late (largest
  lateness 0 ms).

### Partial device logs

The device log is filtered to the kept kinds, and only those are declared complete. The client log
stays whole.

| Condition (declared) | Correct model | Main: false mismatch | (a) | (b) | Count check vs truth |
| --- | --- | --- | --- | --- | --- |
| full (recv, send, state, effect) | checked | 0 of 56 | 6/6 + 6/6 | 6/6 + 6/6 | 79 of 83 |
| state and effect only | not checked in 83 | 0 | 0 of 12 (contracts: below) | 0 of 12 | no count; no item in any run |
| sends only | not checked in 83 | 0 | M4 "`DONE` not sent" 6/6, mimic "`DONE` lost" 6/6; no defect identified | `ACK` copies 6/6, request copies 0/6 | s2c: 81 of 83 (the 2 reply cancellations) |
| receives only | not checked in 83 | 0 | 0 of 12 | request copies 6/6, `ACK` copies 0/6 | c2s: 81 of 83 (the 2 request cancellations) |

- **(d)** is available only with the full log.
- **The declaration:** no count item appeared in a direction the condition does not allow, in any
  run.
- **Control** (receives only, with sends wrongly declared complete): the correct model differs in
  83 of 83, and every reply the client logged reads as a copy in 83 of 83. Reported, not scored.

### Contracts alone

The lift contracts are judged on the device log, with no model.

| Condition | Not judged | Not exercised | Off build (56) | M4 touched (6) | M2 touched (10) | M10 touched (5) |
| --- | --- | --- | --- | --- | --- | --- |
| state and effect only | C5 C7 C8 | C2 C4 C6 | 0 violations | C3 in 6 of 6 | none | none |
| whole device log | none | C2 C4 C6 | 0 violations | C3 in 6 of 6 | C8 in 10 of 10 | C8 in 5 of 5 |

The untouched defect runs violated nothing.

## The blind group

### How it was run

1. **The plan pool:** 27 plans in 9 kinds, published in the registration with their command order
   and link faults, each checked in the simulator on the unchanged firmware.
2. **The change and the assignment** were made by the operator alone:
   - two changes, A and B;
   - the slot labels B01–B08;
   - each slot's plan and seed, each slot's build (5 changed, 3 unchanged), and the run order.

   The operator wrote all of it in a file and gave the agent only its sha256
   (`73c76c07…2bf0382f`), before the first blind session.
3. **Flashing and running:** the operator compiled every blind build with `-DLIFT_DEFECT=0` and
   flashed before every slot, unchanged slots included. Each slot ran with
   `run_blind.sh LABEL PLAN SEED`. The build line said `defect=none` in all 8, and all 8 sessions
   were valid on their first start.
4. **What the agent received:** only the client and device logs of the 8 slots.
5. **The submission:**
   - the agent ran the registered `analyze.py blind` once;
   - it wrote each slot's one-sentence description, changing nothing else in the tool's output;
   - it gave the operator the file's sha256 (`ad2a24d0…4d1d2835`), and the file only after the
     operator confirmed the hash.

   The tool's output before the descriptions is kept with its own hash.
6. **Scoring:** the operator scored each slot with `fired_points.py --reference`, then showed the
   assignment. Its hash matched the one given before the runs.

The change and the source were on the Orin, not on a separate computer (Departures 1).

### The changes (the operator's descriptions)

- **A:** when a repeat of the request being executed arrives during its move, the move timer
  starts again.
- **B:** when the lift is at rest and a command asks it to move to where it already is, the device
  answers `DONE` instead of `ERROR`, with no motor movement.

The conforming set was empty in the four slots that differ: no published device defect model
(M1–M11) matched them.

### Per slot

| Slot | Plan (kind) | Build | Submission | First mismatch | Right answer | S1 request | S2 content |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B01 | BP17 (refused repeat) | B | differs | 17985 ms r-0004: model `send ERROR r-0004 reason=illegal` / device `send DONE r-0004` | differs | yes | yes |
| B02 | BP05 (copy during the move) | unchanged | conforms | – | conforms | | |
| B03 | BP13 (`ACK` lost, retry during the move) | A | differs | 7711 ms r-0002: model `effect motor_stop r-0002` / device nothing | differs | yes | yes |
| B04 | BP21 (opposite command during a move) | unchanged | conforms | – | conforms | | |
| B05 | BP06 (copy during the move) | A | differs | 22044 ms r-0005: model `effect motor_stop r-0005` / device nothing | differs | yes | yes |
| B06 | BP20 (opposite command during a move) | B | differs | 20432 ms r-0005: model `send ERROR r-0005 reason=illegal` / device `send DONE r-0005` | differs | yes | yes |
| B07 | BP14 (`ACK` lost, retry during the move) | B | conforms | – | conforms (the change did not act) | | |
| B08 | BP16 (refused repeat) | unchanged | conforms | – | conforms | | |

- **Result:** 8 of 8 verdicts right, with no false mismatch on the 3 unchanged slots.
- **The 4 slots where the change acted:** S1 4 of 4, S2 4 of 4.
- **The changed slot where the change never acted** (B07) conforms, which is the right answer.

The submission's descriptions of the four slots that differ:

- **B01:** "With the lift resting DOWN, MOVE_DOWN r-0004 (a move to the floor it is already at) was
  ACKed and answered DONE 50 ms later with no motor start and no state change, where the correct
  device refuses it with ERROR reason=illegal; its later copy was also answered DONE."
- **B03:** "The retry of MOVE_DOWN r-0002 that arrived during its move (at 6661 ms, 1950 ms into the
  3 s travel) restarted the travel time: motor_stop, the state DOWN and DONE r-0002 came at
  9661 ms, 3 s after the retry, instead of at 7711 ms, 3 s after motor_start."
- **B05:** "The copy of MOVE_UP r-0005 that arrived during its move (at 19994 ms, 950 ms into the
  3 s travel) restarted the travel time: motor_stop, the state UP and DONE r-0005 came at 22994 ms,
  3 s after the copy, instead of at 22044 ms, 3 s after motor_start."
- **B06:** "With the lift resting UP, MOVE_UP r-0005 (a move to the floor it is already at) was
  ACKed and answered DONE 50 ms later with no motor start and no state change, where the correct
  device refuses it with ERROR reason=illegal; the earlier MOVE_DOWN r-0004 that arrived during a
  move was refused correctly."

### What the blind slots show

- **The contracts caught neither change.** No contract was violated in any of the 8 slots; C2, C4
  and C6 were not exercised in any. The model comparison caught both changes.
  - A only moves a timer: every transition is declared, and each id still gets one `DONE`.
  - B answers `DONE` with no transition and no motor effect. No contract ties `DONE` to a move.
- **One change acted where its plan was not aimed.** BP20 aims an opposite command at a move. In
  B06 that command was refused as it should be, and B acted on the next command, which found the
  lift already at its floor.
- **One plan never reached its change.** BP14's retry arrives during a move. B acts only on a lift
  at rest, so B07 shows nothing, and the method says so.

## What the results show

- **With a complete device log, these defects are not hard.** Fed the device's receives, the
  correct model:
  - conformed on every no-defect log (0 of 56);
  - found every defect that acted, on the request where it acted (21 of 21);
  - found both unknown changes where they acted (4 of 4), with the content right.
- **The rules set on development logs held on new logs.** The 2 ms window was never needed. The
  same-millisecond rule was needed twice, and both times gave the right verdict.
- **Two ambiguities of the client log are settled by the device log:**
  - M4 against a real loss at the same place, 12 of 12 (in testbed-03 the four real losses were all
    accused as M4);
  - a request copy against an `ACK` copy, 12 of 12.
- **The stated limits showed as predicted:**
  - the count check missed exactly the four planned cancellations;
  - M1 and M2 were told apart only where the run had a repeat after `DONE`.
- **Contracts alone:** they caught the three public defects with no false violation. They missed
  both unknown changes, because no declared rule forbids what A and B do.
- **What this does not show:**
  - the registered runs used public defects the agent knew, a complete device log and one device;
  - the claim "an unknown defect is found" rests on 4 acting slots, 2 changes of kinds the method
    can see (a send and an effect), chosen by one operator.

## Departures from the registration

1. **The blind source was on the Orin.** The registration says the changed source never exists on
   a machine the agent can reach. The operator had no other computer, so the operator used the Orin.
   - **What the operator kept on the Orin:** the change, the compiled builds, the assignment file
     and the truth files.
   - **The protection became a commitment.** The agent did not use the Orin from before the
     assignment's hash was given until after the submission was handed over. Its last command on
     the Orin set up the operator's folder (item 2), before the operator wrote the change. The
     session transcript can be audited for this.
2. **The agent prepared the operator's folder and a helper script** on the Orin (`~/blind-op`). It
   holds two copies of `examples/testbed-uno/firmware` from `474432c` (hashes matching the
   registration) and `blind_flash.sh`. The script:
   - compiles a copy with `-DLIFT_DEFECT=0`;
   - flashes a build;
   - checks the port, the ModemManager ignore flag, `READY log=1` and `build defect=none`.

   It knows nothing about any change. The unchanged copy compiled byte for byte to the registered
   off `.hex`.
3. **The agent knew the number of changes** (two). The operator said so before the runs. The
   registration allows one or two changes, and the agent knew nothing else about them.
4. **Plan realized was checked after the analysis.** `analyze.py` does not compute it. It was
   checked once, with the registered yardstick (`expected.json` and the simulator library's
   `landed`), on the truth files: 135 of 135 faults as planned.
5. **Flashing approvals.** The registration says the agent flashes each registered build only after
   asking. The operator approved all four in one instruction, with a stop on any invalid or rerun
   run. Neither occurred, and the agent flashed the builds in order.

No other departure:
- no session was restarted;
- no file in the registration's hash table changed;
- the registered analysis ran once, and the blind analysis once.

## Limits

- **Public defects, complete logs, one device.** The registered runs used the public defects. They
  had every receive, send, state and effect in the device log, and one device.
- **The device log is the suspect's statement.** A defect in logging, or one where action and log
  differ, is not seen. Neither blind change was of that kind.
- **The count check misses a loss and a copy of the same message** (the four C-cancel runs).
- **No delays:** which way a message was delayed, and by how much, is stage 2.
- **Contracts find only what a declared rule forbids;** both blind changes passed them.
- **The blind protection for the source and the truth was a commitment, not physical**
  (Departures 1). The agent also knew each slot's plan (it is in the client log's header) and the
  number of changes.
- **Small numbers:** 4 acting blind slots and 2 changes. Rates are counts out of small groups, not
  estimates with error bars.

## Per run

Correct model on the full device log; the count check with its equality to the truth; contracts
violated with state and effect lines only and with the whole log; where the defect fired
(`fired_points.py --defect`); the same-millisecond rule where active.

| Run | Build | Group | Plan | Seed | Faults | Correct model (first mismatch) | Conforming | Count check (= truth) | Contracts: state+effect / full | Fired | Same-ms rule |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R001 | off | C-cancel | P51 | 561 | s2c ACK r-0005 k0 drop; s2c ACK r-0005 k1 copy +100 | conforms | correct, M3, M4, M9, M10, M11 | - (no) | - / - | - | - |
| R002 | off | A-mimic | P36 | 543 | c2s MOVE_UP r-0005 k0 drop; c2s MOVE_UP r-0005 k1 drop; s2c ACK r-0005 k0 delay 2500; s2c DONE r-0005 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0005 lost x2; s2c DONE r-0005 lost x1 (yes) | - / - | - | - |
| R003 | off | B-req | P38 | 549 | c2s MOVE_DOWN r-0004 k0 copy +250 | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_DOWN r-0004 extra copy x1 (yes) | - / - | - | - |
| R004 | off | O-meas | P44 | 529 | s2c DONE r-0004 k0 delay 100; down 900 ms from 1000 ms after s2c ACK r-0004 0 | conforms | correct, M3, M4, M9, M10, M11 | c2s STATUS s-0017 lost x1 (yes) | - / - | - | - |
| R005 | off | C-cancel | P08 | 558 | c2s MOVE_DOWN r-0002 k0 drop; c2s MOVE_DOWN r-0002 k1 copy +200 | conforms | correct, M3, M4, M9, M10, M11 | - (no) | - / - | - | - |
| R006 | off | B-ack | P39 | 555 | s2c ACK r-0004 k0 copy +250 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c ACK r-0004 extra copy x1 (yes) | - / - | - | - |
| R007 | off | C-cancel | P20 | 560 | s2c ACK r-0003 k0 drop; s2c ACK r-0003 k1 copy +100 | conforms | correct, M3, M4, M9, M10, M11 | - (no) | - / - | - | - |
| R008 | off | A-mimic | P30 | 545 | c2s MOVE_DOWN r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 drop; s2c ACK r-0004 k0 delay 2500; s2c DONE r-0004 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s MOVE_DOWN r-0004 lost x2; s2c DONE r-0004 lost x1 (yes) | - / - | - | - |
| R009 | off | O-meas | P45 | 510 | s2c DONE r-0003 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c DONE r-0003 lost x1 (yes) | - / - | - | active |
| R010 | off | B-req | P17 | 551 | c2s MOVE_DOWN r-0006 k0 copy +500 | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_DOWN r-0006 extra copy x1 (yes) | - / - | - | - |
| R011 | off | O-meas | P16 | 526 | s2c ACK r-0006 k0 copy +40; c2s STATUS s-0015 k0 copy +100 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s STATUS s-0015 extra copy x1; s2c ACK r-0006 extra copy x1 (yes) | - / - | - | - |
| R012 | off | O-meas | P45 | 511 | s2c DONE r-0003 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c DONE r-0003 lost x1 (yes) | - / - | - | - |
| R013 | off | O-meas | P04 | 519 | s2c STATUS_REPLY s-0011 k0 delay 300 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R014 | off | O-meas | P15 | 523 | s2c ACK r-0002 k0 delay 2300 | conforms | correct, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R015 | off | O-meas | P07 | 517 | c2s STATUS s-0008 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s STATUS s-0008 lost x1 (yes) | - / - | - | - |
| R016 | off | O-meas | P43 | 505 | s2c DONE r-0002 k0 delay 200 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R017 | off | A-mimic | P30 | 542 | c2s MOVE_DOWN r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 drop; s2c ACK r-0004 k0 delay 2500; s2c DONE r-0004 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s MOVE_DOWN r-0004 lost x2; s2c DONE r-0004 lost x1 (yes) | - / - | - | - |
| R018 | off | O-meas | P09 | 520 | down 1500 ms from 400 ms after c2s MOVE_DOWN r-0002 0 | conforms | correct, M3, M4, M9, M10, M11 | c2s STATUS s-0005 lost x1 (yes) | - / - | - | - |
| R019 | off | A-mimic | P58 | 541 | c2s MOVE_UP r-0003 k0 drop; c2s MOVE_UP r-0003 k1 drop; s2c ACK r-0003 k0 delay 2500; s2c DONE r-0003 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0003 lost x2; s2c DONE r-0003 lost x1 (yes) | - / - | - | - |
| R020 | off | C-cancel | P26 | 559 | c2s MOVE_DOWN r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 copy +200 | conforms | correct, M3, M4, M9, M10, M11 | - (no) | - / - | - | active |
| R021 | off | O-meas | P37 | 506 | c2s MOVE_DOWN r-0004 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s MOVE_DOWN r-0004 lost x1 (yes) | - / - | - | - |
| R022 | off | O-meas | P18 | 502 | s2c ACK r-0003 k0 delay 60 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R023 | off | A-mimic | P55 | 540 | c2s MOVE_DOWN r-0002 k0 drop; c2s MOVE_DOWN r-0002 k1 drop; s2c ACK r-0002 k0 delay 2500; s2c DONE r-0002 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s MOVE_DOWN r-0002 lost x2; s2c DONE r-0002 lost x1 (yes) | - / - | - | - |
| R024 | off | O-meas | P33 | 508 | s2c ACK r-0005 k0 drop | conforms | correct, M3, M4, M9, M10, M11 | s2c ACK r-0005 lost x1 (yes) | - / - | - | - |
| R025 | off | B-ack | P29 | 552 | s2c ACK r-0001 k0 copy +30 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c ACK r-0001 extra copy x1 (yes) | - / - | - | - |
| R026 | off | B-req | P47 | 546 | c2s MOVE_UP r-0001 k0 copy +30 | conforms | correct, M3, M4, M10, M11 | c2s MOVE_UP r-0001 extra copy x1 (yes) | - / - | - | - |
| R027 | off | O-meas | P33 | 509 | s2c ACK r-0005 k0 drop | conforms | correct, M3, M4, M9, M10, M11 | s2c ACK r-0005 lost x1 (yes) | - / - | - | - |
| R028 | off | B-ack | P48 | 557 | s2c ACK r-0006 k0 copy +500 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c ACK r-0006 extra copy x1 (yes) | - / - | - | - |
| R029 | off | O-meas | P04 | 518 | s2c STATUS_REPLY s-0011 k0 delay 300 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R030 | off | O-meas | P07 | 516 | c2s STATUS s-0008 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s STATUS s-0008 lost x1 (yes) | - / - | - | - |
| R031 | off | O-meas | P16 | 527 | s2c ACK r-0006 k0 copy +40; c2s STATUS s-0015 k0 copy +100 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s STATUS s-0015 extra copy x1; s2c ACK r-0006 extra copy x1 (yes) | - / - | - | - |
| R032 | off | O-none | none | 533 | none | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R033 | off | O-meas | P37 | 507 | c2s MOVE_DOWN r-0004 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s MOVE_DOWN r-0004 lost x1 (yes) | - / - | - | - |
| R034 | off | O-meas | P50 | 512 | c2s MOVE_UP r-0005 k0 copy +300 | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0005 extra copy x1 (yes) | - / - | - | - |
| R035 | off | O-meas | P43 | 504 | s2c DONE r-0002 k0 delay 200 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R036 | off | B-ack | P21 | 553 | s2c ACK r-0002 k0 copy +80 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c ACK r-0002 extra copy x1 (yes) | - / - | - | - |
| R037 | off | O-meas | P42 | 514 | s2c DONE r-0004 k0 copy +150 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c DONE r-0004 extra copy x1 (yes) | - / - | - | - |
| R038 | off | O-meas | P09 | 521 | down 1500 ms from 400 ms after c2s MOVE_DOWN r-0002 0 | conforms | correct, M3, M4, M9, M10, M11 | c2s STATUS s-0005 lost x1; c2s STATUS s-0006 lost x1 (yes) | - / - | - | - |
| R039 | off | B-req | P31 | 547 | c2s MOVE_DOWN r-0002 k0 copy +80 | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_DOWN r-0002 extra copy x1 (yes) | - / - | - | - |
| R040 | off | B-ack | P57 | 554 | s2c ACK r-0003 k0 copy +150 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c ACK r-0003 extra copy x1 (yes) | - / - | - | - |
| R041 | off | O-meas | P42 | 515 | s2c DONE r-0004 k0 copy +150 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c DONE r-0004 extra copy x1 (yes) | - / - | - | - |
| R042 | off | O-meas | P50 | 513 | c2s MOVE_UP r-0005 k0 copy +300 | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0005 extra copy x1 (yes) | - / - | - | - |
| R043 | off | A-mimic | P58 | 544 | c2s MOVE_UP r-0003 k0 drop; c2s MOVE_UP r-0003 k1 drop; s2c ACK r-0003 k0 delay 2500; s2c DONE r-0003 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0003 lost x2; s2c DONE r-0003 lost x1 (yes) | - / - | - | - |
| R044 | off | B-req | P13 | 548 | c2s MOVE_UP r-0003 k0 copy +150 | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0003 extra copy x1 (yes) | - / - | - | - |
| R045 | off | O-meas | P53 | 524 | c2s MOVE_UP r-0003 k0 drop; s2c ACK r-0003 k0 drop | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0003 lost x1; s2c ACK r-0003 lost x1 (yes) | - / - | - | - |
| R046 | off | O-meas | P25 | 500 | c2s MOVE_UP r-0001 k0 delay 80 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R047 | off | O-meas | P44 | 528 | s2c DONE r-0004 k0 delay 100; down 900 ms from 1000 ms after s2c ACK r-0004 0 | conforms | correct, M3, M4, M9, M10, M11 | c2s STATUS s-0017 lost x1 (yes) | - / - | - | - |
| R048 | off | O-meas | P25 | 501 | c2s MOVE_UP r-0001 k0 delay 80 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R049 | off | O-meas | P53 | 525 | c2s MOVE_UP r-0003 k0 drop; s2c ACK r-0003 k0 drop | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0003 lost x1; s2c ACK r-0003 lost x1 (yes) | - / - | - | - |
| R050 | off | O-meas | P18 | 503 | s2c ACK r-0003 k0 delay 60 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R051 | off | B-ack | P01 | 556 | s2c ACK r-0005 k0 copy +400 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | s2c ACK r-0005 extra copy x1 (yes) | - / - | - | - |
| R052 | off | O-none | none | 532 | none | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R053 | off | O-none | none | 531 | none | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R054 | off | O-meas | P15 | 522 | s2c ACK r-0002 k0 delay 2300 | conforms | correct, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R055 | off | B-req | P41 | 550 | c2s MOVE_UP r-0005 k0 copy +400 | conforms | correct, M3, M4, M9, M10, M11 | c2s MOVE_UP r-0005 extra copy x1 (yes) | - / - | - | - |
| R056 | off | O-none | none | 530 | none | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | - | - |
| R057 | M2 | D-nosep | P10 | 570 | c2s MOVE_UP r-0005 k0 copy +1000 | 18570 ms r-0005: model nothing / device send ERROR r-0005 reason=illegal | M1, M2 | c2s MOVE_UP r-0005 extra copy x1 (yes) | - / C8 | 18520 ms r-0005 | - |
| R058 | M2 | D-sep | P28 | 562 | s2c ACK r-0002 k0 drop; c2s MOVE_DOWN r-0002 k1 copy +2000 | 7621 ms r-0002: model nothing / device send ERROR r-0002 reason=illegal | M2 | c2s MOVE_DOWN r-0002 extra copy x1; s2c ACK r-0002 lost x1 (yes) | - / C8 | 7571 ms r-0002 | - |
| R059 | M2 | D-sep | P54 | 565 | s2c ACK r-0005 k0 drop; c2s MOVE_UP r-0005 k1 copy +2000 | 24751 ms r-0005: model nothing / device send ERROR r-0005 reason=illegal | M2 | c2s MOVE_UP r-0005 extra copy x1; s2c ACK r-0005 lost x1 (yes) | - / C8 | 24701 ms r-0005 | - |
| R060 | M2 | D-sep | P46 | 566 | s2c ACK r-0006 k0 drop; c2s MOVE_DOWN r-0006 k1 copy +2000 | 29944 ms r-0006: model nothing / device send ERROR r-0006 reason=illegal | M2 | c2s MOVE_DOWN r-0006 extra copy x1; s2c ACK r-0006 lost x1 (yes) | - / C8 | 29894 ms r-0006 | - |
| R061 | M2 | D-nosep | P56 | 567 | c2s MOVE_DOWN r-0002 k0 copy +1000 | 5406 ms r-0002: model nothing / device send ERROR r-0002 reason=illegal | M1, M2 | c2s MOVE_DOWN r-0002 extra copy x1 (yes) | - / C8 | 5356 ms r-0002 | - |
| R062 | M2 | D-sep | P49 | 563 | s2c ACK r-0003 k0 drop; c2s MOVE_UP r-0003 k1 copy +2000 | 12749 ms r-0003: model nothing / device send ERROR r-0003 reason=illegal | M2 | c2s MOVE_UP r-0003 extra copy x1; s2c ACK r-0003 lost x1 (yes) | - / C8 | 12699 ms r-0003 | - |
| R063 | M2 | N-touch | P23 | 578 | c2s MOVE_DOWN r-0004 k0 delay 50 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | none | - |
| R064 | M2 | D-nosep | P32 | 571 | c2s MOVE_DOWN r-0006 k0 copy +1000 | 25470 ms r-0006: model nothing / device send ERROR r-0006 reason=illegal | M1, M2 | c2s MOVE_DOWN r-0006 extra copy x1 (yes) | - / C8 | 25420 ms r-0006 | - |
| R065 | M2 | D-nosep | P11 | 568 | c2s MOVE_UP r-0003 k0 copy +1000 | 9454 ms r-0003: model nothing / device send ERROR r-0003 reason=illegal | M1, M2 | c2s MOVE_UP r-0003 extra copy x1 (yes) | - / C8 | 9404 ms r-0003 | - |
| R066 | M2 | D-sep | P14 | 564 | s2c ACK r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 copy +2000 | 17131 ms r-0004: model nothing / device send ERROR r-0004 reason=illegal | M2 | c2s MOVE_DOWN r-0004 extra copy x1; s2c ACK r-0004 lost x1 (yes) | - / C8 | 17081 ms r-0004 | - |
| R067 | M2 | D-nosep | P52 | 569 | c2s MOVE_DOWN r-0004 k0 copy +1000 | 18158 ms r-0004: model nothing / device send ERROR r-0004 reason=illegal | M1, M2 | c2s MOVE_DOWN r-0004 extra copy x1 (yes) | - / C8 | 18108 ms r-0004 | - |
| R068 | M2 | N-touch | P05 | 577 | s2c DONE r-0003 k0 delay 100 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | none | - |
| R069 | M4 | A-M4 | P03 | 538 | c2s MOVE_UP r-0003 k0 drop; c2s MOVE_UP r-0003 k1 drop; c2s MOVE_UP r-0003 k2 delay 2500 | 16436 ms r-0004: model send ERROR r-0004 reason=illegal / device effect motor_start r-0004 dir=down | M4 | c2s MOVE_UP r-0003 lost x2 (yes) | C3 / C3 | 16436 ms r-0004 | - |
| R070 | M4 | A-M4 | P22 | 539 | c2s MOVE_DOWN r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 drop; c2s MOVE_DOWN r-0004 k2 delay 2500 | 22908 ms r-0005: model send ERROR r-0005 reason=illegal / device effect motor_start r-0005 dir=up | M4 | c2s MOVE_DOWN r-0004 lost x2 (yes) | C3 / C3 | 22908 ms r-0005 | - |
| R071 | M4 | A-M4 | P22 | 536 | c2s MOVE_DOWN r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 drop; c2s MOVE_DOWN r-0004 k2 delay 2500 | 23529 ms r-0005: model send ERROR r-0005 reason=illegal / device effect motor_start r-0005 dir=up | M4 | c2s MOVE_DOWN r-0004 lost x2 (yes) | C3 / C3 | 23529 ms r-0005 | - |
| R072 | M4 | N-touch | P06 | 580 | c2s STATUS s-0009 k0 drop | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | c2s STATUS s-0009 lost x1 (yes) | - / - | none | - |
| R073 | M4 | A-M4 | P34 | 534 | c2s MOVE_DOWN r-0002 k0 drop; c2s MOVE_DOWN r-0002 k1 drop; c2s MOVE_DOWN r-0002 k2 delay 2500 | 13799 ms r-0003: model send ERROR r-0003 reason=illegal / device effect motor_start r-0003 dir=up | M4 | c2s MOVE_DOWN r-0002 lost x2 (yes) | C3 / C3 | 13799 ms r-0003 | - |
| R074 | M4 | A-M4 | P03 | 535 | c2s MOVE_UP r-0003 k0 drop; c2s MOVE_UP r-0003 k1 drop; c2s MOVE_UP r-0003 k2 delay 2500 | 18091 ms r-0004: model send ERROR r-0004 reason=illegal / device effect motor_start r-0004 dir=down | M4 | c2s MOVE_UP r-0003 lost x2 (yes) | C3 / C3 | 18091 ms r-0004 | - |
| R075 | M4 | A-M4 | P40 | 537 | c2s MOVE_UP r-0005 k0 drop; c2s MOVE_UP r-0005 k1 drop; c2s MOVE_UP r-0005 k2 delay 2500 | 26743 ms r-0006: model send ERROR r-0006 reason=illegal / device effect motor_start r-0006 dir=down | M4 | c2s MOVE_UP r-0005 lost x2 (yes) | C3 / C3 | 26743 ms r-0006 | - |
| R076 | M4 | N-touch | P12 | 579 | s2c ACK r-0002 k0 delay 100 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | none | - |
| R077 | M10 | E-M10 | P02 | 572 | c2s MOVE_DOWN r-0002 k0 drop; c2s MOVE_DOWN r-0002 k1 drop; c2s MOVE_DOWN r-0002 k2 drop; c2s MOVE_UP r-0003 k0 copy +500 | 13936 ms r-0003: model send ERROR r-0003 reason=illegal / device send DONE r-0003 | M10 | c2s MOVE_DOWN r-0002 lost x3; c2s MOVE_UP r-0003 extra copy x1 (yes) | - / C8 | 13936 ms r-0003 | - |
| R078 | M10 | E-M10 | P24 | 573 | c2s MOVE_UP r-0003 k0 drop; c2s MOVE_UP r-0003 k1 drop; c2s MOVE_UP r-0003 k2 drop; c2s MOVE_DOWN r-0004 k0 copy +500 | 19871 ms r-0004: model send ERROR r-0004 reason=illegal / device send DONE r-0004 | M10 | c2s MOVE_UP r-0003 lost x3; c2s MOVE_DOWN r-0004 extra copy x1 (yes) | - / C8 | 19871 ms r-0004 | - |
| R079 | M10 | E-M10 | P27 | 574 | c2s MOVE_DOWN r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 drop; c2s MOVE_DOWN r-0004 k2 drop; c2s MOVE_UP r-0005 k0 copy +500 | 22821 ms r-0005: model send ERROR r-0005 reason=illegal / device send DONE r-0005 | M10 | c2s MOVE_DOWN r-0004 lost x3; c2s MOVE_UP r-0005 extra copy x1 (yes) | - / C8 | 22821 ms r-0005 | - |
| R080 | M10 | E-M10 | P02 | 576 | c2s MOVE_DOWN r-0002 k0 drop; c2s MOVE_DOWN r-0002 k1 drop; c2s MOVE_DOWN r-0002 k2 drop; c2s MOVE_UP r-0003 k0 copy +500 | 14538 ms r-0003: model send ERROR r-0003 reason=illegal / device send DONE r-0003 | M10 | c2s MOVE_DOWN r-0002 lost x3; c2s MOVE_UP r-0003 extra copy x1 (yes) | - / C8 | 14538 ms r-0003 | - |
| R081 | M10 | N-touch | P59 | 581 | s2c ACK r-0005 k0 delay 100 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | none | - |
| R082 | M10 | E-M10 | P35 | 575 | c2s MOVE_UP r-0005 k0 drop; c2s MOVE_UP r-0005 k1 drop; c2s MOVE_UP r-0005 k2 drop; c2s MOVE_DOWN r-0006 k0 copy +500 | 30790 ms r-0006: model send ERROR r-0006 reason=illegal / device send DONE r-0006 | M10 | c2s MOVE_UP r-0005 lost x3; c2s MOVE_DOWN r-0006 extra copy x1 (yes) | - / C8 | 30790 ms r-0006 | - |
| R083 | M10 | N-touch | P19 | 582 | s2c DONE r-0002 k0 delay 60 | conforms | correct, M1, M2, M3, M4, M9, M10, M11 | - (yes) | - / - | none | - |
