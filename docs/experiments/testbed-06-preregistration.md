# Testbed experiment 06: blind slots on mechanically changed firmware, the rev3 contracts (registration draft)

Operator document. Do not give it to a planner.

**Status: draft for review.** It becomes final when the operator approves it. Its sha256 is then recorded,
before the operator's draw. The results go into a separate document afterwards; this one is not rewritten
then.

## Question

The question is the same as in [testbed-05](testbed-05.md), on new changes. On lift firmware the operator
changed, does the analysis find where the change acted? Which rev3 contracts catch it? On builds with no
change, or where the change did not act, does it stay quiet? Each slot gets two separate answers:
- **the device model** (`replayspect device`): the correct model conforms to the device log, or it gives
  its first mismatch (request, time, the model's event and the device's);
- **the rev3 contracts** (`contracts/lift.v0.rev3.yaml`, C1–C14), judged on the device log alone. This is
  their first measurement:
  - C14 (`never_after`: no `ACK` for a request after its `DONE` or `ERROR`) was written from the five
    testbed-05 slots that rev2 missed;
  - every rev3 number so far is a development check
    ([protocol-contract-coverage.md](../notes/protocol-contract-coverage.md), "rev3").

## What the analyst knows

The analyst is this agent session. It wrote the plans, the scripts and the analysis, and it submits the
judgments.

**What it knows of this group's changes** is one sentence: **mechanical mutants, made with rules wider than
testbed-05's.** It does not know:
- the mutation rules or the target lines;
- whether the changes stay in `lift_device.h`;
- the candidate list;
- how many slots carry a change, or how many builds there are.

The advisor session made the rules and the candidates. The advisor is also Claude, but it is not this
session. Its script draws the slots with a recorded seed. The operator confirms the draw, then builds,
flashes and runs. Nobody picks a change by hand.

**What it knows from testbed-05:**
- **That experiment's rules and full candidate list.** The analyst saw them when testbed-05 was scored.
  Copies are in its scoring folder (`~/rs-control/testbed-05/scoring/`: `rules.md`, `candidates.tsv`). They
  were not opened while preparing this group. Whether this group's candidates overlap that list is for the
  operator to say after scoring.
- **The assignment file's scoring notes.** To carry the two scoring rules over (Scoring), the analyst read
  that section of testbed-05's assignment file again. The line above it, which names four testbed-05
  candidates, was printed with it.
- **The 15 testbed-05 changes and their results,** which are published ([testbed-05.md](testbed-05.md)).
  C14 was written to catch four of the slots rev2 missed there. If this group's changes resemble those,
  rev3 has an advantage that comes from its development data (Limits).

**Not read, at any time:**
- **The operator's folder on the Orin** (`~/blind-op`).
- **Slot truth files,** before scoring.

**The Orin:** the analyst copies the testbed folder there (Order, step 3). After that it does not use the
Orin until it has handed over the submission's hash.

## Setup

- **Harness:** `d5757b6` (main after #55, the rev3 contracts). `analyze.py` refuses to run if `src/`,
  `contracts/` or `examples/testbed-uno/rules/` differ from it.
- **Testbed:** the testbed-04 and testbed-05 hardware and host. The Uno runs the lift; the Orin runs the
  client and the fault link. `host/client.py` and `host/fault_link.py` have not changed since testbed-04.
- **Sessions:** 6 commands, 90 s, 115200 baud, `client.py --expect-build none`. Every build is compiled with
  `-DLIFT_DEFECT=0`, so every build line reads `defect=none`.
- **Slots:** 24, labelled `S01`…`S24`.
- **Builds:**
  - They get neutral names, `b01`, `b02`, …, for changed and unchanged builds alike.
  - Each build is a copy of `examples/testbed-uno/firmware` at `d5757b6`, changed or not. Its
    `lift_device.h` (sha256 `6bd958cb…`) is the same as at testbed-05's `40d03fd`.

### The plan pool

`blind-plans.md` and `blind-plans/P01…P48.json` hold 48 plans: 12 kinds, 4 plans each, with new seeds.

**Seeds** are taken from 1000–1199, a range no earlier experiment used (testbed-01 to 05 used seeds up to
935). They are taken in order, each used once. Where a kind needs a timing condition, a plan takes the first
unused seed for which the simulator shows that condition. The seeds are listed in the pool file and
published with the results.

**The nine testbed-05 kinds** keep the same targets and link actions:
- no fault;
- a request copied during its move;
- a request copied after its `DONE`;
- a request copied while it waits to run;
- the `ACK` lost, and the retry arriving during the move;
- a refused request, repeated;
- an opposite command during a move;
- a `DONE` lost;
- a short disconnect during a move.

**Three new kinds:**
- **A request copied into the next command** (`copy-next`; targets r-0001, r-0002, r-0004, r-0005). The
  copy arrives 6 s after the first arrival, after the next command has started. The condition is that
  the copy arrives after the next command's motor start or refusal.
- **A request to be refused, copied before the refusal** (`copy-refused-early`; targets r-0002, r-0003,
  r-0005, r-0006). The command before the target never reaches the device (all three attempts are lost), so
  the target asks for a move the lift cannot make. The target's copy arrives 20 ms after its first arrival.
  The condition is that the device sends the `ERROR` and that the copy arrives before it. The refusal comes
  when the request executes, 50 ms after its `ACK`.
- **A `STATUS` poll copied** (`copy-status`). A poll arrives twice, in one of four placements:
  - both arrivals during a move, 20 ms apart;
  - both while the lift stands, 20 ms apart;
  - the first during a move and the copy 1.5 s later, after the move has ended;
  - the first while the lift stands and the copy 1.5 s later, during a move.

  "During a move" means between the motor's start and its stop, at least 100 ms from either. "Stands"
  means at least 100 ms outside every move. The poll is the first one, from `s-0003` on, that fits the
  placement on the seed's run.

**What the new kinds try:**
- a repeat that arrives during a later command;
- a repeat that arrives before its request's result exists;
- a repeated poll, answered from the state at that moment.

Together with "copied after its `DONE`", the "copy into the next command" plans try C14's `DONE` side. On
hardware, that side has never been tried (coverage note, row C14). Whether such a plan lands on an
unchanged build depends on the draw.

**The check: every plan, on the unchanged firmware, in the simulator** (48 of 48). The simulator is
`dev/sim06lib.py`: the real client and fault link, with the Python lift model on a fake port. Each plan
passed four checks:
- the link applied every planned fault as planned;
- the run is valid, the correct model conforms, and no rev3 contract is violated;
- the plan's timing condition holds, where its kind has one;
- **the unchanged firmware reproduces the simulated device log.** This check is new. It feeds the log's
  receives to `lift_device.h` itself, compiled natively as in `fired_points.py`. Every `send`, `state`
  and `effect` line came out in the same millisecond, and no defect point fired.

The pool file (`blind-plans.json`: plan id, seed, kind, what the link does) goes to the operator. Any plan
may serve any build.

### The draw, on the operator's side

This is done as in testbed-05. The advisor's script draws, with a recorded seed:
- which builds carry a change, and which change;
- slot → plan;
- slot → build;
- the run order.

**The operator's folder.** The advisor makes it: `fw/bNN` for each build, and `reference-firmware/` for
scoring.

**The assignment file.** The operator confirms the draw. Before the first session, the operator keeps on
their side an assignment file. It holds:
- the draw;
- each build's file hashes and `.hex` hash;
- a one-sentence description of each change;
- any scoring note the advisor adds, fixed before any run.

The analyst receives only the file's sha256. The file is shown at scoring.

**Replacements.** A build that cannot run is replaced before any session by the next candidate in the draw
order. That means a build that does not compile for the Uno, or that fails the boot check. Replacements are
listed in the results. A build that resets during a session stays: its run is invalid and reported.

## Order

1. **Registration hash.** The operator approves this document, and its sha256 is recorded.
2. **The operator's draw and assignment** (above).
3. **Placing the testbed on the Orin.**
   - The analyst copies `deploy/` to `~/replayspect-testbed/testbed-06` on the Orin. That is `host/`,
     `run_blind.sh` and the pool, with a `MANIFEST`.
   - It checks the `MANIFEST` there.
   - From then on it does not use the Orin.
   - `blind_flash.sh` goes into the operator's folder.
4. **The final assignment hash.** The operator builds every `fw/bNN` with `bash blind_flash.sh build-all`
   and writes the hashes into the assignment file. The analyst receives the final file's sha256, before
   any session.
5. **Running,** on the Orin, by the operator. For each slot, in the drawn order:
   - `bash blind_flash.sh flash bNN SHA` checks the `.hex` against its hash and flashes it. It then checks
     the port and the boot lines (`READY log=1`, `build defect=none`).
   - `bash run_blind.sh SLOT PLAN` runs the slot. The script:
     - takes the seed from the pool file;
     - refuses a slot that already has a log;
     - retries once with the same seed when there is no `READY`.

     **New:** a client log with no end line exits 4, and says the run did not finish. This holds both
     right after the run and when the slot is given again. Such a slot is invalid and is not run again.
     This guards against what happened to testbed-05's S05, whose unfinished log was taken as finished.
   - The operator then copies only `blind/SLOT-client.log` and `blind/SLOT-device.log` to the
     development machine, and keeps the truth files.
6. **The submission hash.**
   - The analyst runs `analyze.py` once, on all slots.
   - It writes each line's `description`.
   - It gives the operator the file's sha256.
   - The tool's output before the descriptions is kept with its own hash.
7. **Scoring.** The scoring script runs only after the operator has the submission's hash. The scoring
   output and the assignment file go to the analyst only after that.

## Analysis

`python3 analyze.py BLIND_DIR blind-submission.jsonl` is run once, after the last slot. For each slot it
runs the tool as a command:
- `replayspect ingest SLOT-client.log --rules examples/testbed-uno/rules/testbed-client.yaml`;
- `replayspect device SLOT-device.log --models device --client TRACE --contracts contracts/lift.v0.rev3.yaml --complete device:recv,send,state,effect --complete client:send,recv`.

**Submission line.** It uses testbed-05's format, judged with rev3. The model result and the contract
result are separate fields. For each violated contract, `first_violations` gives:
- its first violation's request: the `req_id` on the device event that shows it;
- its time;
- the detail.

`no_violation_in_keys_judged` is new. It lists contracts that were judged only on some keys, because a
log adapter could not settle the order of the others. On a device log it is expected to be empty.

```json
{"slot": "S03", "verdict": "conforms | differs | invalid",
 "first_mismatch": {"t_ms": 6004, "req_id": "r-0001", "model": "send DONE r-0001", "device": "send ACK r-0001",
                    "model_state": "MOVING_DOWN", "last_input": "recv MOVE_UP r-0001"},
 "conforming_models": ["M1", "M11"],
 "count_check": [{"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "what": "extra copy", "n": 1}],
 "contracts": {"file": "contracts/lift.v0.rev3.yaml", "violated": ["C14", "C8"],
               "first_violations": [{"contract": "C14", "req_id": "r-0001", "t_ms": 6004,
                                     "detail": "ACK after device.send(DONE|ERROR)"},
                                    {"contract": "C8", "req_id": "r-0001", "t_ms": 6054,
                                     "detail": "both device.send(DONE) and device.send(ERROR)"}],
               "not_exercised": ["C2", "C4", "C6"], "not_judged": [], "no_violation_in_keys_judged": []},
 "description": "One sentence: what the device did differently, in protocol terms."}
```

The example is not a real slot. It is a dry-run line: plan P37 (copy into the next command) on the public
defect M11, simulated.

## Scoring (the operator)

**The answer for each slot.** The operator runs, from the build's changed copy:
`python3 harness/fired_points.py blind/SLOT-device.log --reference reference-firmware`. It prints the first
output where the changed and the unchanged firmware differ on that log's inputs, or `{"difference": null}`
if there is none. The answer is what it prints on the slot's real device log, not a prediction.

### Rules fixed before the draw

The first two rules are carried over from testbed-05's assignment file, where they were fixed before any
run. Here they are written as general rules, without naming any change.

- **A wrong id.** Sometimes the first difference is one reply whose id is wrong: the same message, sent at
  the same time, with another `req_id`. Then:
  - `fired_points.py` names the id on the changed line;
  - the request being handled is the id on the reference line;
  - S1 is yes when the first mismatch is that reply, at the same time, whichever of the two ids its
    `req_id` holds.
- **A missing reply.** Sometimes the first difference is a reference line with no changed line. Its request
  is the reference line's id.
- **An extra line** (new in this registration). Sometimes the first
  difference is a changed line with no reference line. Its request is the changed line's id. testbed-05 had
  no such case.

### Model result

This is scored as in testbed-05.

| Slot | Right answer | Scored |
| --- | --- | --- |
| Changed build, the change acted (a first difference exists) | `differs` | **S1 request:** the first mismatch's `req_id` equals the first difference's request (yes/no, by the rules above). **S2 content:** the model and device events, and the description, match what the change does (yes/no, with a one-line reason). The time difference is reported, not scored. |
| Changed build, the change did not act | `conforms` | right / wrong |
| Unchanged build | `conforms` | right / wrong (a `differs` is a false mismatch) |

### Contract result

This is scored apart from the model result.

| Slot | Scored |
| --- | --- |
| Unchanged build, or a changed build whose change did not act | Any rev3 violation is a **false violation**. |
| Changed build, the change acted | **Caught:** at least one rev3 violation (yes/no), with the contracts. |

**Groups of contracts.** These are listed apart:
- C14;
- C9–C13;
- C1–C8.

The count with rev2 alone (C1–C13) is given beside the rev3 count.

**Where each violation points.** Each violation is counted in exactly one of three classes:
- **on the request being handled:** its `req_id` is the first difference's request. When the change
  writes a wrong id, that is the reference line's id;
- **on the id written on the reply:** its `req_id` is the changed line's id, which differs from the request
  being handled. This happens only with a wrong id;
- **on another request.**

For each violation, the time from the first difference is also given (same millisecond, or how much later).

**How often C14 was tried on unchanged builds.** This is a count reported after scoring, not a prediction.
It covers the valid slots of unchanged builds:
- **the requests the device heard of again after their final answer.** This is the conservative measure of
  [claims.md](../claims.md), "Exercised": a request with something later from the device after its final
  answer. They are counted apart by the final answer, `DONE` or `ERROR`;
- **C14's violations among them.**

The coverage note records that C14's `DONE` side was never tried on hardware. This count says how often it
was tried here, whatever the draw gives.

### Slots outside the scores

- **Not scorable for S1 and S2:** a slot whose device log the changed harness does not reproduce. This
  includes a change outside `lift_device.h`, which the harness does not include. Such slots are listed
  apart. Their model and contract results are still reported.
- **Invalid runs:** a changed build that resets, stops logging or breaks its boot lines makes the run
  invalid (`verdict: invalid`). So does a run with no end line. It is reported, not scored.

## Predictions

These predictions do not depend on what the changes are.

1. **No false mismatch:** on every valid slot of an unchanged build, the correct model conforms.
2. **No false contract violation:** no rev3 violation on any valid slot of an unchanged build, nor on a
   changed build whose change did not act.
3. **Count check:** on every valid slot of an unchanged build, the count check equals the truth file's
   losses and copies. No pool plan loses and copies the same message. A copied poll counts as one extra
   copy of its `STATUS`.
4. **Validity:** every slot of an unchanged build is valid.
5. **Claim of the method** (as in testbed-04 and 05): where a change acted on a slot's inputs and changed a
   send, a state change or an effect, the correct model's first mismatch is on that request (S1 yes, by
   the rules above).

**How the tool answers at its stated limits.** These are general predictions about cases that may or may
not occur. Each is scored only if such a slot occurs.

6. **The comparison window** ([device-log.md](../device-log.md), "Conformance"). A change whose only
   effect is to log an output at most 2 ms later than the model gives no mismatch: it is missed. One that
   moves an output more than 2 ms later, or any earlier, gives a first mismatch at that output.
7. **Timer events carry their scheduled times** (device-log.md, "Limits"). A change to a scheduled time
   shows at the first event whose time moved. That can be the processing delay or the travel time. On the
   contracts:
   - a motor stop more than 3,002 ms after its start violates C9;
   - a schedule that stays within 3,002 ms breaks no contract by its timing alone.
8. **Same-millisecond order.** The tool runs a timer before an input that falls in the same millisecond, as
   the unchanged firmware does.
   - On unchanged builds, a poll answered in the millisecond a move ends is matched (part of prediction 1).
   - Suppose a change makes the device take the input first, and that order changes an output. The tool
     then gives a mismatch in that millisecond.
9. **The allow list.** Only `recv`, `send`, `state` and `effect` lines are read.
   - A change whose only effect is on other lines gives no mismatch and no violation.
   - A change that makes the device write an `error` line makes the run invalid.
   - A change where the device does one thing and logs another is seen only as what it logged.
10. **The contracts' documented gaps** (coverage note, lines 37–39 and gap 5). A change whose only effect is
    one of the following is caught by no rev3 contract, while the model sees it:
    - no reply to a received request;
    - a wrong final reply to a repeat other than `ACK`, unless that reply also breaks another rule. For
      example, C8 is broken when both `DONE` and `ERROR` go out for one id.

    An `ACK` sent for an id after its `DONE` or `ERROR` violates C14 at that `ACK`, on that `ACK`'s id.

**A predicted miss is still a miss.** A slot missed in the way one of predictions 6–10 says still counts as
missed in the totals, for the model result and for the contract result. It is also listed under its
prediction. Nothing is taken out of the totals because it was predicted.

There is **no prediction** of how many slots differ, or of which contracts catch a change. The analyst does
not know the changes.

**Grounds:**
- the simulator check of the 48 plans, with the unchanged `lift_device.h` reproducing each log;
- development data:
  - the 213 real no-defect device logs (testbed-01 to 04, and testbed-05's S08 and S14): no rev3
    violation (#55);
  - the correct model conforms on testbed-04's 56 off-build runs and on testbed-05's S08 and S14;
  - the blind slots of testbed-04 (8) and testbed-05 (16).

## Limits

- **rev3 was written from testbed-05.**
  - C14 came from four of the five slots rev2 missed there.
  - The analyst has seen testbed-05's rules, candidates and results.
  - If this group's changes are like testbed-05's, rev3's catch rate is flattered by its own development
    data. The operator's statement on the overlap is reported with the results.
- **The advisor chose the new plan kinds and made the rules.** The three new kinds came with the operator's
  order, from the advisor, who also wrote this group's rules. The pool may therefore be suited to making
  the changes act. That affects how many changes act, not how a slot is scored.
- **The analyst chose the details:**
  - the targets;
  - the four poll placements and their 100 ms margin;
  - the 1.5 s poll copy delay;
  - the seed rule.
- **The device log is the suspect's statement.** A change that acts only on logging, or makes the device do
  one thing and log another, is not seen. Such slots are scored, and predicted missed (prediction 9).
- **Contracts find only what a declared rule forbids.** A change that breaks no rule passes them, even when
  the model sees it (prediction 10).
- **Mechanical changes can stop a run.**
  - A build that fails to compile or fails its boot check is replaced before any session.
  - A build that resets during a session gives an invalid slot, which carries no evidence about the method.
- **The harness covers `lift_device.h` only** (`harness.cpp` includes it). With wider rules, a change
  elsewhere in the firmware is possible. `fired_points.py` does not reproduce it, and its slot is not
  scorable for S1 and S2.
- **Timing.**
  - Timer events carry their scheduled times (prediction 7).
  - The same-millisecond rule and the 2 ms window were set on development logs. On new logs they can still
    give false mismatches.
- **The blind's protection is a commitment.**
  - The analyst could read the Orin. It undertakes not to, and the session transcript can be audited for
    it.
  - The analyst knows each slot's plan from the client log header. That says nothing about the build.
  - The analyst wrote the scripts the operator runs.
- **Who made the changes:** the advisor (also Claude) wrote the rules. A bias in which changes an LLM thinks
  of cannot be ruled out.
- **The advisor knows the tool.**
  - It has read the tool's code and the rev2 and rev3 contracts (it reviewed #47–#55). So the rules were
    written by someone who knows what the tool checks.
  - Against this: the draw is random among the candidates. Also, the advisor runs `replayspect` on no
    candidate and no slot before the submission's hash is recorded.
- **Small numbers:** 24 slots. Rates are counts, not estimates with error bars.

## Changes from testbed-05

- **Size:** 24 slots instead of 16; 48 plans in 12 kinds instead of 36 in 9.
- **Contracts:** rev3 (C1–C14) instead of rev2, at harness `d5757b6`.
- **The plan check:** it now also runs the unchanged `lift_device.h` natively on each simulated log, and
  requires that every planned fault landed.
- **`run_blind.sh`:** slots `S01–S24`, plans `P01–P48`. A client log with no end line now exits 4.
- **`analyze.py`:** rev3, and the new `no_violation_in_keys_judged` field.
- **Order:**
  - the testbed folder goes to the Orin after the draw;
  - the analyst receives the final assignment hash after that;
  - the scoring script runs only after the submission hash. In testbed-05, it ran three minutes before the
    hash.
- **Scoring:**
  - the wrong-id and missing-reply rules are registered in advance;
  - the extra-line rule is added;
  - a violation's request is counted in three classes;
  - C14 is listed apart;
  - C14's tries on unchanged builds are counted after scoring.

## Files

All files are outside the repository, in `~/rs-control/testbed-06/`. The hashes below are the draft's; the
final registration repeats them.

| File | sha256 |
| --- | --- |
| `make_blind_plans.py` | `fd2feafd02cc165f0e286b5d720bf9a6a5c22a426fee383362e7b6ba91913dd5` |
| `dev/sim06lib.py` (testbed-05's `sim05lib.py`, first line changed) | `3b9dcc6f52845eb8dbeaf5c6166ae753e7e9618192a44ba6a11d43f4cc4ea3f8` |
| `dev/make_dry.py` (the dry run, development only) | `67b592d05f77886d2798acefd8aa3c9aa4f05acd829e8c23f578cef7a76b6421` |
| `blind-plans.json` (the pool file) | `d94ce9471b9a9c45f1f174893634d7f0fa87c2d96bb7d8f56f3b36e399bf43bb` |
| `blind-plans.md` | `f4b96235829a53487b79e4747740871f18754b604e3e720eaf9cf736a238ce30` |
| `blind-plans/P01…P48.json` (concatenated in name order) | `8435e4bd0f1bac6ee0ccd8bb8a3b24ad5e4fbbdae967f3741973243dae403ddf` |
| `run_blind.sh` | `39eef515e42b241c9d63d2d11fdf504de68ff3437269c3c097ef8e78d0be1b89` |
| `blind_flash.sh` | `f4ac0023efa2e8740be61d3615dcf7f56ee3d4bbfee8db7142d8bb86b74a9c0d` |
| `analyze.py` | `68ad3129e05efd3f4b4ca875169fd962d69a69a147407bc3bf59bb897363c682` |
| `host/client.py` (unchanged since testbed-04) | `1cda89190c5d2fc42856c4141994c8e8b53f9e65b5ff11f379aba2dc805b01c3` |
| `host/fault_link.py` (unchanged since testbed-04) | `1f18adbd01b330275fe887363b61b8133df74ea9104b6d446f09d61646ddf1b6` |
| `deploy/MANIFEST` | `9e03764feb9950b107b0223ba860072296f49caed9fdf3b923ff08d8f1beb0de` |
