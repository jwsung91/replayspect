# Testbed experiment 07: blind slots on changed turntable firmware, the generic set's first measurement (registration draft)

Operator document. Do not give it to a planner.

**Status: draft for review.** It becomes final when the operator approves it. Its sha256 is then recorded,
before the advisor's draw. The results go into a separate document afterwards (`testbed-07.md`); this one is
not rewritten then.

This is stage 2 of [WP6/7c](../work-order-wp67c.md), with its "Amendments after stage 0" (A–F).

## Question

On turntable firmware the operator changed, does the analysis find where the change acted, and which
contracts catch it? On builds with no change, or where the change did not act, does it stay quiet? Each slot
gets separate answers:
- **the device model** (`replayspect device --system turntable.v0`): the correct model conforms to the device
  log, or it gives its first mismatch (request, time, the model's event and the device's). Scored S1 and S2,
  as in testbed-06;
- **the generic set alone:** `contracts/generic/turntable.v0.yaml` (the generic rules of
  `contracts/generic/rules.yaml`, bound to the turntable), judged on the device log alone. **This is its first
  measurement.** Every number for it so far is a development check
  ([generic-contracts.md](../notes/generic-contracts.md));
- **the turntable's own contracts alone:** `contracts/turntable.v0.yaml` (C1–C8);
- **both together:** the union of the two results, computed from them. There is no merged contract file and
  no new option.

This is also the device comparison's first blind group on a second system.

## What the analyst knows

The analyst is this agent session. It wrote the plans, the scripts and the analysis, and it submits the
judgments.

**What it knows of this group's changes** is one sentence, written by the operator:

> **[OPERATOR: one sentence, to be written here before approval.]**

It does not know:
- the rules or the target lines;
- whether the changes stay in `turntable_device.h`;
- the candidate list;
- how many slots carry a change, or how many builds there are.

The advisor session makes the rules, the candidates and the draw script. The advisor is also Claude, but it is
not this session. Its script draws the slots with a recorded seed. The operator confirms the draw, then
builds, flashes and runs. Nobody picks a change by hand.

**What it has seen of earlier groups:**
- **testbed-04, 05 and 06 results**, which are published, with each group's drawn changes
  ([testbed-05.md](testbed-05.md), [testbed-06.md](testbed-06.md), "The changes"). They are lift changes.
- **testbed-05's rules and full candidate list,** seen when testbed-05 was scored (testbed-06's registration
  says so).
- **testbed-06's assignment file and scoring,** given to the analyst after its submission, as that
  registration orders. testbed-06's rules and full candidate list are not published; this session has not
  opened them.
- **The generic rules were written from those groups** (`docs/notes/generic-contracts.md`): from lift
  contracts that came out of testbed-04, 05 and 06, and checked on their 34 acting blind slots. See Limits.

**Not read, at any time:**
- **The Orin's operator and control folders** (`~/blind-op`, `~/blind05-op`, `~/blind`, `~/rs-control`).
  This session listed the Orin's home folder once (the names above), and opened nothing in them.
- **Slot truth files,** before scoring.

**The Orin:** the analyst places the testbed folder there (Order, step 3). After that it does not use the Orin
until it has handed over the submission's hash. In WP6/7c stage 1 and in this draft's dry run it used the Orin
through SSH; both were before the draw, on folders of its own (`~/wp67c-stage1`, `~/wp67c-dryrun`).

## Setup

- **Harness:** `1356127` (main after #66, WP6/7c stage 1). `analyze.py` refuses to run if `src/`,
  `contracts/` or `examples/testbed-uno/rules/` differ from it, or hold an untracked file.
- **The contract files,** frozen for WP6/7c (sha256):
  - `contracts/generic/turntable.v0.yaml` (the binding): `1b3b445b47c05361fa683392f72c92a1716e738d82045a8d2f3f91eabaa8efdc`;
  - `contracts/generic/rules.yaml` (the rules it binds): `fcbfd0af403d2227d6231432d7395e0568c0dee5de06f10b8123f5bd2197a115`;
  - `contracts/turntable.v0.yaml`: `6759966a7a0d19b0bb64f4ec7fbf2487204e490131058782a432110f564d10a4`.
- **The board: one only.** testbed-07 runs on the turntable board alone (WP6/7c amendment 15):
  - an Arduino UNO Mini (ATmega328P, `arduino:avr:uno`), on the Jetson Orin;
  - `/dev/serial/by-id/usb-Arduino__www.arduino.cc__Arduino_UNO_Mini_7513131383235170B182-if00`, which is
    `TURNTABLE_PORT` in `boards.env`;
  - the lift board (`…B101`) stays connected and is not used. Every script names the turntable board by its
    by-id path; a flash to another port is refused, and a board whose build line names another system is
    refused by the client (`wrong_system`) and by the boot check.
- **Testbed:** WP6/7c stage 1's: `turntable_uno` firmware (the timer build: a turn lasts 3 s and lights the
  LED; no motor or sensor), `host/client.py` with the turntable's command list, `host/fault_link.py`,
  `host/board_check.py`. All unchanged since `1356127`.
- **Sessions:** 6 commands (`TURN_LEFT, TURN_RIGHT, TURN_RIGHT, TURN_LEFT, TURN_LEFT, TURN_RIGHT`), 90 s,
  115200 baud, device log on, `client.py --expect-system turntable.v0 --expect-build none`.
- **Slots:** 24, labelled `S01`…`S24`.
- **Builds:**
  - They get neutral names, `b01`, `b02`, …, for changed and unchanged builds alike.
  - Each build is a copy of `examples/testbed-uno/firmware` at `1356127`, changed or not. Its
    `turntable_device.h` is sha256 `0d120d226777c4d2d86a21dc8134d7d37acf7e1f4a550815df05c61cfcfbc953`.
  - Every build line reads `build system=turntable.v0 defect=none` (the turntable has no defect switch).

### The plan pool

`blind-plans.md` and `blind-plans/P01…P48.json` hold 48 plans: 12 kinds, 4 plans each.

**Seeds** are taken from 3000–3199, in order, each used once; the pool uses 3000–3047. That range avoids every
range used before:
- testbed-01 to 05: seeds up to 935;
- testbed-06: 1000–1199 (its pool used 1000–1047);
- simulator sweeps in the repository's checks: 0–999;
- WP6/7c stage 1's development corpus: 7000–7099 (it used 7000–7023), which is kept for development.

A plan takes the first unused seed on which every check below passes. All 48 took the first seed tried.

**The kinds: testbed-06's twelve, carried over to the turntable's messages.** The turntable has the lift's
shape (one action per request, `ACK` then one final answer, polls, a result table), so each kind keeps its
target and link action, with "move" read as "turn":
- no fault;
- a request copied during its turn (the copy 1.5 s after the first arrival);
- a request copied after its `DONE` (4 s after);
- a request copied while it waits to run (20 ms after, within the 50 ms before it executes);
- the `ACK` lost, and the retry arriving during the turn;
- a refused request, repeated (the copy 1 s after its first arrival, after the `ERROR`);
- a command during a turn (testbed-06: "an opposite command during a move"). A request's first two
  attempts are lost and the third is 2.5 s late, so the next command arrives during the late turn. On the
  turntable any command during a turn is refused as `illegal`, so "opposite" is dropped;
- a `DONE` lost;
- a short disconnect during a turn (1.5 s, starting 1 s after the request is sent);
- a request copied into the next command (`copy-next`; the copy 6 s after the first arrival, after the next
  command's motor start or refusal);
- a request to be refused, copied before the refusal (`copy-refused-early`; the copy 20 ms after the first
  arrival, before the `ERROR` 50 ms after it);
- a `STATUS` poll copied (`copy-status`), one plan for each of the four placements: both arrivals during a
  turn, 20 ms apart; both while the table stands, 20 ms apart; the first during a turn and the copy 1.5 s
  later, after it; the first while it stands and the copy 1.5 s later, during a turn. "During" and "stands"
  keep testbed-06's 100 ms margin. The poll is the first one, from `s-0003` on, that fits.

**Carried over with a difference** (WP6/7c amendment F: carried over, not replaced). In testbed-06 the two
refusal kinds lose "the command before the target", so that the target asks for a move the lift cannot make.
In the turntable's order (L, R, R, L, L, R from `INITIAL`) losing the command just before a target never gets
the target refused. The plans lose an earlier command instead, all three attempts:

| Target | Command lost | Why the target is refused |
| --- | --- | --- |
| `r-0003` (`TURN_RIGHT`) | `r-0001` | `r-0002` turns to `RIGHT`; `r-0003` asks past it: `limit` |
| `r-0005` (`TURN_LEFT`) | `r-0003` | `r-0004` turns to `LEFT`; `r-0005` asks past it: `limit` |
| `r-0005` (`TURN_LEFT`) | `r-0002` | `r-0003` back to `INITIAL`, `r-0004` to `LEFT`; `r-0005`: `limit` |

Each refusal kind has four plans on three recipes; the first recipe is used twice, on different seeds. Both
refusals are `limit`, never `illegal`: the client's order reaches no other refusal with one command lost.

**Targets** of the other kinds (four each, one per plan): `copy-during-turn`, `copy-after-done`,
`command-during-turn` and `copy-next` r-0001, r-0002, r-0004, r-0005; `copy-while-waiting` r-0002, r-0003,
r-0005, r-0006; `ack-lost-retry-during-turn`, `done-lost` r-0001, r-0003, r-0004, r-0006;
`disconnect-during-turn` r-0001, r-0003, r-0005, r-0006.

**The check: every plan, on the unchanged firmware, in the simulator** (48 of 48). The simulator
(`sim07lib.py`) is the repository's `client.py` and `fault_link.py` at `1356127`, with the Python turntable
model behind a fake serial port (1 ms each way); it writes the model's device log in the firmware's format.
Each plan passed:
- the link applied every planned fault as planned, and the run is valid;
- the kind's timing condition holds, read from the device log;
- `replayspect device --system turntable.v0 --complete device:recv,send,state,effect`: the correct model
  conforms, and neither `contracts/turntable.v0.yaml` nor `contracts/generic/turntable.v0.yaml` is violated
  (nothing not judged);
- **the unchanged firmware reproduces the simulated device log:** the log's receives fed to
  `turntable_device.h` itself, compiled natively as in `fired_points.py --system turntable`; every `send`,
  `state` and `effect` line came out in the same millisecond.

The pool maker is deterministic: run again, it writes the same files. The pool file (`blind-plans.json`: plan
id, seed, kind, target, the command lost, what the link does) goes to the operator. Any plan may serve any
build.

### The draw, on the operator's side

This is done as in testbed-06. The advisor's script draws, with a recorded seed:
- which builds carry a change, and which change;
- slot → plan;
- slot → build;
- the run order.

**The operator's folder.** The advisor makes it: `fw/bNN` for each build (a copy of
`examples/testbed-uno/firmware`), `reference-firmware/` for scoring, and `blind_flash.sh`.

**The assignment file.** The operator confirms the draw. Before the first session, the operator keeps on
their side an assignment file. It holds:
- the draw;
- each build's file hashes and `.hex` hash;
- a one-sentence description of each change;
- any scoring note the advisor adds, fixed before any run;
- **new:** a machine-readable part for `score.py`, `assignment.json`:
  `{"slots": {"S01": {"plan": "P07", "build": "b03"}, …}, "builds": {"b03": {"changed": true}, …}}`.

The analyst receives only the file's sha256. The file is shown at scoring.

**Replacements.** A build that cannot run is replaced before any session by the next candidate in the draw
order. That means a build that does not compile for the Uno, or that fails the boot check. Replacements are
listed in the results. A build that resets during a session stays: its run is invalid and reported.

## Order

1. **Registration hash.** The operator writes the sentence above and approves this document, and its sha256
   is recorded.
2. **The advisor's draw and the operator's assignment** (above).
3. **Placing the testbed on the Orin.**
   - The analyst copies `deploy/` to `~/replayspect-testbed/testbed-07` on the Orin: `host/` (from
     `1356127`), `run_blind.sh` and the pool, with a `MANIFEST`. It writes `boards.env` there (the two
     by-id paths of WP6/7c stage 1).
   - It checks the `MANIFEST` there (`sha256sum -c MANIFEST`).
   - From then on it does not use the Orin.
   - `blind_flash.sh` goes into the operator's folder.
4. **The final assignment hash.** The operator builds every `fw/bNN` with `bash blind_flash.sh build-all` and
   writes the hashes into the assignment file. The analyst receives the final file's sha256, before any
   session.
5. **Running,** on the Orin, by the operator. For each slot, in the drawn order:
   - `bash blind_flash.sh flash bNN SHA`:
     - before the upload it checks the `.hex` against its hash, and that the port is `TURNTABLE_PORT` in
       `boards.env`, a by-id path that is present. It does not look at the firmware on the board;
     - after the upload it reads the boot lines: `READY log=1` and `build system=turntable.v0 defect=none`
       (with `host/board_check.py`'s check). Otherwise it exits 3.
   - `bash run_blind.sh SLOT PLAN` runs the slot. The script:
     - takes the seed from the pool file;
     - refuses a slot that already has a log (exit 3);
     - retries once with the same seed when there is no `READY`;
     - runs the client with `--expect-system turntable.v0 --expect-build none`;
     - exits 4 when the client log has no end line, both right after the run and when the slot is given
       again. Such a slot is invalid and is not run again;
     - **new:** writes `blind/SLOT.done` with its exit status when it returns, so the end of a session is
       known from a file, not from the process list.
   - The operator then copies only `blind/SLOT-client.log` and `blind/SLOT-device.log` to the development
     machine, and keeps the truth files.
6. **The submission hash.**
   - The analyst runs `analyze.py` once, on all slots.
   - It writes each line's `description`.
   - It gives the operator the file's sha256.
   - The tool's output before the descriptions is kept with its own hash (`analyze.py` prints it).
7. **Scoring.** `score.py` runs only after the operator has the submission's hash. The scoring output and the
   assignment file go to the analyst only after that.

## Analysis

`python3 analyze.py REPO BLIND_DIR blind-submission.jsonl` is run once, after the last slot. For each slot it
runs the tool as commands:
- `replayspect ingest SLOT-client.log --rules examples/testbed-uno/rules/testbed-client-turntable.yaml`;
- `replayspect device SLOT-device.log --system turntable.v0 --client TRACE --contracts SET --complete device:recv,send,state,effect --complete client:send,recv`,
  once with SET = `contracts/turntable.v0.yaml` and once with `contracts/generic/turntable.v0.yaml`. The
  model result must be the same in both runs (checked).

`--models` is not given: the turntable has no published defect models. A slot is `invalid` when its client
log has no end line or says `valid=no`, or its device log has an `error` line.

**Submission line.** testbed-06's format, with one contract result per set and their union. For each violated
contract, `first_violations` gives its first violation's request (the `req_id` on the device event that shows
it), its time and the detail.

```json
{"slot": "S02", "verdict": "differs",
 "first_mismatch": {"t_ms": 10946, "req_id": "r-0002", "kind": "event", "model": "effect motor_stop r-0002",
                    "device": null, "model_state": "TURNING_TO_RIGHT", "last_input": "recv STATUS s-0010"},
 "count_check": [{"dir": "c2s", "msg": "TURN_LEFT", "req_id": "r-0001", "what": "lost", "n": 3},
                 {"dir": "c2s", "msg": "TURN_RIGHT", "req_id": "r-0003", "what": "extra copy", "n": 1}],
 "contracts": {"turntable": {"file": "contracts/turntable.v0.yaml", "violated": [], "first_violations": [],
                             "not_exercised": ["C2", "C4", "C6"], "not_judged": [], "no_violation_in_keys_judged": []},
               "generic": {"file": "contracts/generic/turntable.v0.yaml", "violated": [], "first_violations": [],
                           "not_exercised": [], "not_judged": [], "no_violation_in_keys_judged": []},
               "both": {"violated": []}},
 "description": "One sentence: what the device did differently, in protocol terms."}
```

The example is not a slot. It is the dry run's line (below): plan P21 on the analyst's own change, on the
board.

## Scoring (the operator)

`python3 score.py assignment.json blind-submission.jsonl BLIND_DIR OPERATOR_DIR OUT` writes the scores
(`OUT.json`, `OUT.md`). S2 is filled by hand.

**The answer for each slot.** For a changed build, `score.py` runs, from the build's changed copy:
`python3 harness/fired_points.py blind/SLOT-device.log --system turntable --reference reference-firmware`. It
prints the first output where the changed and the unchanged firmware differ on that log's inputs, or
`{"difference": null}`. The answer is what it prints on the slot's real device log, not a prediction.

### Rules fixed before the draw

testbed-06's three rules, unchanged:
- **A wrong id:** the first difference is one reply whose id is wrong (the same message at the same time,
  another `req_id`). The request being handled is the id on the reference line. S1 is yes when the first
  mismatch is that reply, at the same time, whichever of the two ids its `req_id` holds.
- **A missing reply:** a reference line with no changed line. Its request is the reference line's id.
- **An extra line:** a changed line with no reference line. Its request is the changed line's id.

### Model result

As in testbed-06.

| Slot | Right answer | Scored |
| --- | --- | --- |
| Changed build, the change acted (a first difference exists) | `differs` | **S1 request:** the first mismatch's `req_id` equals the first difference's request (by the rules above). **S2 content:** the model and device events, and the description, match what the change does (yes/no, with a one-line reason). The time difference is reported, not scored. |
| Changed build, the change did not act | `conforms` | right / wrong |
| Unchanged build | `conforms` | right / wrong (a `differs` is a false mismatch) |

### Contract result

Scored apart from the model result, **for each of the three: the generic set, the turntable's own, both.**

| Slot | Scored |
| --- | --- |
| Unchanged build, or a changed build whose change did not act | Any violation is a **false violation** of that set. |
| Changed build, the change acted | **Caught:** at least one violation of that set (yes/no), with the contracts. |

**Listed apart:**
- **each generic rule's count:** on how many acting slots each rule (G1, G2, G3, G4, G5, G6, G6b, P1) has a
  violation;
- **the generic contracts that repeat one of the turntable's own** — `G1.motor_start` (C1), `G2.final` (C7),
  `G3` (C8) — **and those that do not** (`G1.motor_stop`, `G2.ack`, `G2.poll.STATUS`, `G4`, `G5`, `G6`, `G6b`,
  `P1`): on how many acting slots each group catches;
- **false violations,** for each set, on unchanged builds and on changed builds whose change did not act.

**Where each violation points.** Each contract's first violation is counted in exactly one of three classes,
as in testbed-06: on the request being handled; on the id written on the reply (wrong id only); on another
request. The time from the first difference is also given.

### Slots outside the scores

- **Not scorable for S1 and S2:** a slot whose device log the changed harness does not reproduce, including a
  change outside `turntable_device.h`. Listed apart; its model and contract results are still reported.
- **Invalid runs:** a run with no end line, `valid=no` (a reset, a device `error` line, a wrong build or
  board), or a broken device log. Reported, not scored.

## Predictions

These do not depend on what the changes are.

1. **No false mismatch:** on every valid slot of an unchanged build, the correct model conforms.
2. **No false violation, for either set:** no violation of `contracts/generic/turntable.v0.yaml` nor of
   `contracts/turntable.v0.yaml` on any valid slot of an unchanged build, nor on a changed build whose change
   did not act.
3. **Count check:** on every valid slot of an unchanged build, the count check equals the truth file's losses
   and copies (records with no message, such as the port line, are not counted). No pool plan loses and copies
   the same message. A copied poll counts as one extra copy of its `STATUS`.
4. **Validity:** every slot of an unchanged build is valid.
5. **Claim of the method:** where a change acted on a slot's inputs and changed a send, a state change or an
   effect, the correct model's first mismatch is on that request (S1 yes, by the rules above).

**The generic set's documented gaps** ([generic-contracts.md](../notes/generic-contracts.md), "Limits of the
generic set", and WP6/7c stage 2). A change whose only effect is one of these is predicted **missed by the
generic set**:

6. it only moves a time (a turn's length, the processing delay);
7. it only takes an undeclared transition (a turn from a state the table does not allow, or to the wrong
   position): the generic set has no transition rule. C3 is the turntable's own contract for it;
8. it only changes what a poll reply says (`STATUS_REPLY` with another state). C5 is the turntable's own;
9. it only drops a reply (no `ACK`, no `DONE` or `ERROR`): the rules bound counts from above and order
   replies, and say nothing of a reply that never comes;
10. it acts only on the client side: the set has no client rule.

**How the tool answers at its stated limits** (testbed-06's predictions 6–9, carried over). Each is scored
only if such a slot occurs.

11. **The comparison window.** A change whose only effect is to log an output at most 2 ms later than the model
    gives no mismatch: it is missed. One that moves an output more than 2 ms later, or any earlier, gives a
    first mismatch at that output.
12. **Timer events carry their scheduled times.** A change to a scheduled time shows at the first event whose
    time moved (the 50 ms processing delay or the 3 s turn). The turntable's own contracts have no timing
    contract (testbed-06's C9 is a lift contract), so a schedule change breaks neither set by its timing alone.
13. **Same-millisecond order.** The tool runs a timer before an input in the same millisecond, as the
    unchanged firmware does. On unchanged builds, a poll answered in the millisecond a turn ends is matched
    (part of prediction 1). A change that makes the device take the input first, where that order changes an
    output, gives a mismatch in that millisecond.
14. **The allow list.** Only `recv`, `send`, `state` and `effect` lines are read. A change whose only effect
    is on other lines gives no mismatch and no violation; one that makes the device write an `error` line makes
    the run invalid; one where the device does one thing and logs another is seen only as what it logged.

**A predicted miss is still a miss.** A slot missed in the way one of predictions 6–14 says still counts as
missed in the totals, for the model result and for each contract result. It is also listed under its
prediction. Nothing is taken out of the totals because it was predicted.

There is **no prediction** of how many slots differ, or of which contracts catch a change.

**Grounds:**
- the simulator check of the 48 plans, with the unchanged `turntable_device.h` reproducing each log;
- **development data, a development check, not a measurement:**
  - WP6/7c stage 1's 24 real no-defect turntable sessions (seeds 7000–7023, testbed-06's kinds, two each,
    on the board `…B182`): all valid; the correct model conforms on 24 of 24 with no event later than the
    model; no violation of either set; every generic contract exercised; each timing condition held
    (`examples/testbed-uno/README.md`, "WP6/7c stage 1"). These plans were made by the analyst, and the runs
    used unchanged firmware only;
  - the harness-made turntable device logs of `tests/test_testbed_turntable.py`;
  - the lift's 218 real no-defect device logs and blind slots, on which the generic rules were developed.

## Limits

- **The turntable has the lift's shape with other names.** A good result is weak evidence that the rules are
  generic ([generic-contracts.md](../notes/generic-contracts.md), "What the turntable can and cannot show").
  It is a measurement on one protocol of the lift's shape, and says nothing of a protocol of another shape.
- **The generic rules were written from the lift**, from contracts that came out of testbed-04, 05 and 06,
  and checked on their acting slots. If this group's changes resemble those groups', the generic set's count
  is flattered by its own development data. The operator's statement on the overlap is reported with the
  results.
- **The advisor wrote the generic rule list and makes this group's changes.** It knows the tool and the rules
  it is measuring. Against this: the draw is random among the candidates, and the advisor runs `replayspect`
  on no candidate and no slot before the submission's hash is recorded.
- **The comparison's timing rules were set on lift logs.** The same-millisecond rule and the 2 ms window held
  on stage 1's 24 turntable logs (the window was never used), which is development data.
- **The analyst chose the plan details:** the targets, the copy delays (1.5 s, 4 s, 20 ms, 6 s, 1 s), the
  disconnect's offset and length, the poll placements and their 100 ms margin, the seed rule, and the
  refusal kinds' carried-over recipes (above).
- **The analyst wrote every script anew** (Files). testbed-06's scripts were not found; these follow its
  registration's text, not its code. Where the text did not fix a detail, the analyst chose it.
- **The device log is the suspect's statement.** A change that acts only on logging, or makes the device do one
  thing and log another, is not seen (prediction 14).
- **Contracts find only what a declared rule forbids** (predictions 6–10).
- **Mechanical changes can stop a run.** A build that fails to compile or fails its boot check is replaced
  before any session; one that resets during a session gives an invalid slot.
- **The harness covers `turntable_device.h` only.** A change elsewhere is not reproduced by
  `fired_points.py`, and its slot is not scorable for S1 and S2.
- **One board.** Every slot runs on `…B182`. A fault of that board, its USB link or its clock touches every
  slot alike.
- **The blind's protection is a commitment.** The analyst could read the Orin. It undertakes not to after
  placing the testbed folder, and the session transcript can be audited for it. The analyst knows each slot's
  plan from the client log header; that says nothing about the build.
- **Small numbers:** 24 slots. Rates are counts, not estimates with error bars.

## The dry run (development only)

Run before this draft, with the operator's scripts as they are, on the Orin and the turntable board, in
folders of the analyst's own (`~/wp67c-dryrun/testbed` as the testbed folder, `~/wp67c-dryrun/op` as the
operator's). Two builds: `b01` unchanged, `b02` the analyst's own change in a scratch copy outside the
repository (`TURN_MS` 3000 → 3100 in `turntable_device.h`: every turn 100 ms longer). It is not a candidate,
and the board was flashed back to `b01` afterwards. Logs: outside the repository.

| Step | What happened |
| --- | --- |
| `sha256sum -c MANIFEST` on the Orin | ok |
| `blind_flash.sh build-all` | both built; hashes printed |
| `blind_flash.sh flash b01 0000` (wrong hash) | refused before the upload, exit 3 |
| `blind_flash.sh flash b01 SHA` | uploaded; `ok: READY log=1 seen; build turntable.v0 defect=none` |
| `board_check.py --expect-system lift.v0` on the turntable board | `WRONG: turntable.v0 defect=none`, exit 3 |
| `board_check.py --expect-system turntable.v0 --expect-build M1` | `WRONG`, exit 3 |
| `board_check.py --expect-system turntable.v0` | `ok`, exit 0 |
| `run_blind.sh S25 P01` | usage, exit 2 |
| `run_blind.sh S01 P05` on `b01` | valid; `blind/S01.done` = 0; the truth file's first line is the port record (`…B182-if00`) |
| `run_blind.sh S01 P05` again | refused, exit 3 |
| `run_blind.sh S02 P21` on `b02` | valid; `S02.done` = 0 |
| `run_blind.sh S04 P01`, its client killed (SIGKILL) after 8 s | the script noticed by itself: "no end line", exit 4, `S04.done` = 4 |
| `run_blind.sh S04 P01` again | exit 4, not run |
| `run_blind.sh S03 P02` with a client log cut before its end line | exit 4, not run |
| `analyze.py` with an untracked file under `src/` | refused |
| `analyze.py` on S01–S04 | S01 `conforms`; S02 `differs` at r-0002 10946 ms (the first turn's motor stop; r-0001 was lost by the plan); S03, S04 `invalid` (no end line); no violation of either set |
| `score.py` (a dry assignment: S02 on `b02`, the rest on `b01`) | S02: acted, first difference `10946 LOG effect motor_stop r-0002`, S1 yes, Δt 0; caught by neither set (prediction 6); S01: right, count check equals the truth file, port line skipped; S03, S04 not scored |

**The port line:** `analyze.py` reads no truth file; `score.py` reads truth files only for the count check and
skips every record with no message (port, build, disconnect, reconnect). The port record's action is `port`,
so it could not be counted as a loss or a copy in any case; S01's count check, with the port line first in its
truth file, equals the truth. WP6/7c stage 1's `check_dev.py` skips it too.

**What the dry run found and changed:** `analyze.py` first named a killed run "device: bad input", because the
killed client's device log was empty. It now checks the client log's end line first and names that.

**A difference from WP6/7c stage 2's text,** which has the dry-run change "run in the simulator": the
turntable has no defect models, and the simulator runs the Python model, not a C++ change, so the change ran on
the board through the operator's scripts instead (amendment F's item 5 asks for those scripts end to end). The
48 pool plans were checked in the simulator as stated.

## Changes from testbed-06

- **The system:** the turntable, on its own board, instead of the lift. One board.
- **Contracts:** three results per slot — the generic set, the turntable's own, their union — instead of rev3.
- **The pool:** the twelve kinds carried over; the two refusal kinds lose an earlier command; seeds 3000–3047.
- **Scripts:** all written anew (testbed-06's were not found). `run_blind.sh` writes a `.done` file;
  `blind_flash.sh` checks the port against `boards.env` before the upload and the system and build after;
  `score.py` is new as a script; `analyze.py` runs two contract sets.
- **The assignment file** has a machine-readable part for `score.py`.
- **Scoring:** per set and for their union; each generic rule's count; the generic contracts that repeat the
  turntable's own, apart. testbed-06's C14 count has no counterpart here.

## Files

Outside the repository, in `testbed-07/` beside the repository folder on the development machine. **All
scripts were written anew for testbed-07,** from testbed-06's registration text; testbed-06's scripts were not
found. The hashes below are the draft's; the final registration repeats them.

| File | sha256 |
| --- | --- |
| `sim07lib.py` (the simulator, the kinds, the timing conditions) | `379cab0402839637c8cc32d66ac70414368cc3198def26a4a034ffd7dbd28e76` |
| `make_blind_plans.py` (the pool maker) | `56bae1cddb628452976b03944eb9a210395189c1a3073eee9ef75139ace9438b` |
| `blind-plans.json` (the pool file) | `46058413900a052f46adac4448ab215f89b5058a355bc20895c43c83a80f1575` |
| `blind-plans.md` | `4df2bbc00b9cb225dfdb8ee18068c94f8b60ecad26098afd349558efca788ef5` |
| `blind-plans/P01…P48.json` (concatenated in name order) | `07867a21be5d35f19c8279f5a28645045e4a41f9fa3f691dadc003643d8476e1` |
| `run_blind.sh` | `7003e78932c5e7c204f885f13ced58a9b74788d7392cb144abf234f56aa0cf1e` |
| `blind_flash.sh` | `3d7395a100bb5de6ceaa6713ed87f367e88e2d87bed37acafde0a8292f3f2691` |
| `analyze.py` | `cbf3945942ae7ce39f8e9b135576144adbd61d55d3085118bbb683ddf9d7edc4` |
| `score.py` | `a5fafccf2e50344d3305a1fdf003640134adf83aad4468efdf977e982fa9eba9` |
| `deploy/MANIFEST` | `fee082585b2ead38696b2abc4378d4133ba6e023ab059b280e0ec7c641c5321a` |
| `host/client.py` (at `1356127`) | `04db713effbb01188c39a6195c4891524b7b626256420cc687653ecc070bcb12` |
| `host/fault_link.py` (at `1356127`) | `570f6942106e05bdd038b7e4adb023b0df3e0f96fc8f2bd28f84041074eb0f26` |
| `host/board_check.py` (at `1356127`) | `1b9e6461fab36748fb6941233598435886f1f1a7254ef67505599e159651652f` |
