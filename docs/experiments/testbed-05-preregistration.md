# Testbed experiment 05: blind slots on mechanically changed firmware (registration draft)

Operator document. Do not give it to a planner.

**Status: draft for review.** It is final when the operator approves it. Its sha256 is then recorded,
before the operator's assignment file exists. The results go into a separate document afterwards;
this one is not rewritten then.

## Question

On the lift firmware the operator changed, does the analysis find where the change acted, and which
rev2 contracts catch it? On builds with no change, does it stay quiet? Two tools answer this
separately for each slot:
- **the device model** (`replayspect device`, stage 1): the correct model conforms to the device log,
  or it gives its first mismatch (request, time, the model's event and the device's);
- **the rev2 contracts** (`contracts/lift.v0.rev2.yaml`, C1–C13): judged on the device log alone. This
  is their first measurement. Until now they were checked only on development data
  ([protocol-contract-coverage.md](../notes/protocol-contract-coverage.md), "Development check").

## What the analyst knows

The analyst is this agent session. It wrote the plans, the scripts and the analysis, and it submits the
judgments. All it knows of the changes is this: **mechanical mutants prepared by the operator.** It does
not know:
- the mutation rules;
- the target lines;
- the list of candidates;
- how many mutants there are, or how many slots carry one.

The rules and their samples were made by the advisor session, and the operator chose from them. The
advisor is also Claude, but it is not this session. This session saw neither the rules nor the
samples.

- **The operator's folder on the Orin** (`~/blind-op`): the analyst does not read it, at any time. It
  does not use the Orin at all from when it receives the assignment's hash until it hands over the
  submission.
- **Truth files:** the analyst never opens a slot's truth file.

## Setup

- **Harness:** `40d03fd` (main after #48). `analyze.py` refuses to run if `src/`, `contracts/` or
  `examples/testbed-uno/rules/` differ from it.
- **Testbed:** the testbed-04 hardware and host. The Uno runs the lift; the Orin runs the client and
  the fault link. `host/client.py` and `host/fault_link.py` are unchanged since testbed-04.
- **Sessions:** 6 commands, 90 s, 115200 baud, `client.py --expect-build none`. Every build is
  compiled with `-DLIFT_DEFECT=0`, so every build line reads `defect=none`.
- **Slots:** 16, labelled `S01`…`S16`. The operator tells the analyst if the number changes.
- **Builds:** neutral names `b01`, `b02`, …, for changed and unchanged builds alike. Each build is a
  copy of `examples/testbed-uno/firmware` at `40d03fd`, changed or not.

### The plan pool

`blind-plans.md` and `blind-plans/P01…P36.json` hold 36 plans: the nine kinds of the testbed-04 blind
pool, with 4 plans each and new seeds. The seeds come from a range no other experiment used. They are
listed in the pool file and published with the results. The kinds are:
- no fault;
- a request copied during its move;
- a request copied after its `DONE`;
- a request copied while it waits to run;
- the `ACK` lost, and the retry arriving during the move;
- a refused request, repeated;
- an opposite command during a move;
- a `DONE` lost;
- a short disconnect during a move.

Each plan was checked in the simulator on the unchanged firmware: the run is valid, the correct model
conforms, and no rev2 contract is violated (36 of 36). The pool file (`blind-plans.json`: plan id,
seed, kind, what the link does) goes to the operator. Any plan may serve any build.

### The operator decides, alone

- which builds carry a change, and what the change is;
- slot → plan;
- slot → build;
- the run order.

Before the first session, the operator writes all of this into a file on their side, with each build's
file and `.hex` hashes and a one-sentence description of each change. The analyst receives only the
file's sha256. The file is shown at scoring.

### Running

All on the Orin, by the operator:
- **Build:** `bash blind_flash.sh build-all` compiles every `fw/bNN/lift_uno` into `hex/bNN` and prints
  flash and RAM use and the sha256 hashes.
- **Flash, before every slot:** `bash blind_flash.sh flash bNN SHA` checks the `.hex` against its hash,
  flashes it, then checks the port and the boot lines (`READY log=1`, `build defect=none`). Builds with
  no change are flashed the same way.
- **One slot:** `bash run_blind.sh SLOT PLAN`, from `~/replayspect-testbed/testbed-05`. The script takes
  the seed from the pool file and refuses a slot that already has a log. With no `READY` it retries once
  with the same seed.
- **Afterwards:** the operator copies only `blind/SLOT-client.log` and `blind/SLOT-device.log` to the
  development machine and keeps the truth files.

## Analysis

`python3 analyze.py BLIND_DIR blind-submission.jsonl`, run once, after the last slot. For each slot it
runs the tool as a command:
- `replayspect ingest SLOT-client.log --rules examples/testbed-uno/rules/testbed-client.yaml`;
- `replayspect device SLOT-device.log --models device --client TRACE --contracts contracts/lift.v0.rev2.yaml --complete device:recv,send,state,effect --complete client:send,recv`.

The analyst then writes each line's one-sentence `description` and gives the operator the file's
sha256. Only then does it receive the scores.

**Submission line.** The testbed-04 format, with `contracts` judged under rev2. The model result and
the contract result are separate fields:

```json
{"slot": "S07", "verdict": "conforms | differs | invalid",
 "first_mismatch": {"t_ms": 14132, "req_id": "r-0003", "model": "send ERROR r-0003 reason=illegal",
                    "device": "send DONE r-0003", "model_state": "UP", "last_input": "recv MOVE_UP r-0003"},
 "conforming_models": ["M10"], "count_check": [...],
 "contracts": {"file": "contracts/lift.v0.rev2.yaml", "violated": ["C10", "C8"],
               "first_violations": [{"contract": "C10", "req_id": "r-0003", "t_ms": 14132,
                                     "detail": "DONE with no earlier device.effect(motor_stop)"},
                                    {"contract": "C8", "req_id": "r-0003", "t_ms": 14132,
                                     "detail": "both device.send(DONE) and device.send(ERROR)"}],
               "not_exercised": ["C2", "C4", "C6"], "not_judged": []},
 "description": "One sentence: what the device did differently, in protocol terms."}
```

`first_violations` is new. It holds each violated contract's first violation (request, time,
detail). The example is a dry run on a simulated log: plan P22 on the public defect M10, not a real slot.

## Scoring (the operator)

For each slot the operator runs, from the build's changed copy:
`python3 harness/fired_points.py blind/SLOT-device.log --reference reference-firmware`.
It prints the first output where the changed and the unchanged firmware differ on that log's
inputs, or `{"difference": null}` if there is none.

**Model result**, as in testbed-04:

| Slot | Right answer | Scored |
| --- | --- | --- |
| Changed build, the change acted (a first difference exists) | `differs` | **S1 request:** the first mismatch's `req_id` equals the first difference's request (yes/no). **S2 content:** the model and device events, and the description, match what the change does (yes/no, with a one-line reason). The time difference is reported, not scored. |
| Changed build, the change did not act | `conforms` | right / wrong |
| Unchanged build | `conforms` | right / wrong (a `differs` is a false mismatch) |

**Contract result**, scored apart:

| Slot | Scored |
| --- | --- |
| Unchanged build, or a changed build whose change did not act | Any rev2 violation is a **false violation**. |
| Changed build, the change acted | **Caught:** at least one rev2 violation (yes/no), with the contracts. For each violation, whether its request is the first difference's request. A violation of C9–C13 is listed apart from one of C1–C8. |

- **Not scorable for S1 and S2:** a slot whose device log the changed harness does not reproduce.
  It is listed apart.
- **Invalid runs:** a changed build that resets, stops logging or breaks its boot lines makes the run
  invalid (`verdict: invalid`). It is reported, not scored.

## Predictions

These predictions do not depend on what the changes are:
1. **No false mismatch:** on every valid slot of an unchanged build, the correct model conforms.
2. **No false contract violation:** no rev2 violation on any valid slot of an unchanged build, nor on
   a changed build whose change did not act.
3. **Count check:** on every valid slot of an unchanged build, the count check equals the truth file's
   losses and copies. No pool plan loses and copies the same message.
4. **Validity:** every slot of an unchanged build is valid.
5. **Claim of the method** (as in testbed-04): where a change acted on a slot's inputs and changed a
   send, a state change or an effect, the correct model's first mismatch is on that request (S1 yes).

There is **no prediction** of how many slots differ, or of which contracts catch a change. The analyst
does not know the changes.

**Grounds:**
- the simulator check of the 36 plans;
- development data:
  - the 211 real no-defect device logs of testbed-01 to 04: no rev2 violation, and the correct model
    conforms on testbed-04's 56 off-build runs;
  - testbed-04's 8 blind slots.

## Limits

- **The device log is the suspect's statement.** A change that acts only on logging, or makes the
  device do one thing and log another, is not seen. Such slots are scored, and predicted missed.
- **Contracts find only what a declared rule forbids.** A change that breaks no rule passes them,
  even when the model sees it.
- **Mechanical changes can stop a run.** A changed build may fail to compile, fail its boot check, or
  reset during a session. Such slots carry no evidence about the method.
- **The harness covers `lift_device.h` only** (`harness.cpp` includes it). A change elsewhere in the
  firmware is not reproduced by `fired_points.py`, and its slot is not scorable for S1 and S2.
- **The blind's protection is a commitment:**
  - The analyst could read the Orin; it undertakes not to, and the session transcript can be audited
    for it.
  - The analyst knows each slot's plan from the client log header; that says nothing about the build.
  - The analyst wrote the scripts the operator runs.
- **Who made the changes:** the advisor (also Claude) made the rules and samples. A bias in which
  changes an LLM thinks of cannot be ruled out.
- **Small numbers:** 16 slots. Rates are counts, not estimates with error bars.
- **Timing rules:** the same-millisecond rule (timers before an input) and the 2 ms window were set on
  development logs. On new logs they can still produce false mismatches.

## Files

All files are outside the repository, in `~/rs-control/testbed-05/`. The hashes below are the
draft's; the final registration repeats them.

| File | sha256 |
| --- | --- |
| `make_blind_plans.py` | `455bb649464145b684b30db9b9e78ca36cfc9584256d2b2447472c775e2f7621` |
| `dev/sim05lib.py` (testbed-04's `sim04lib.py`, first line changed) | `33686155e944925ac2980856962cb76b164b2b3c3a2bd86cc7a83c560dad3038` |
| `blind-plans.json` (the pool file) | `283cf7a43a10ab4fcc76989058c542bbe01449a8046926ab117aba6d5e539350` |
| `blind-plans.md` | `b7a6f3b4cabeb75f0d302032c6b4a9d9af973d84dd405e0c3ab3797bb1494482` |
| `blind-plans/P01…P36.json` (concatenated in name order) | `0d32fee89bacfb45c83dccc62abf0510e7e3d482aca7d9858b6b46eaece22d71` |
| `run_blind.sh` | `1b66d5b763b8e0857b0bf845a0bd5d2c1e421166b596a47f6ef10c83356cd847` |
| `blind_flash.sh` | `09895f808c2dc1194a1284cc0e673d5b6f9968a9fb096e31590ec9e97a825d48` |
| `analyze.py` | `d868c1cc57867da3f0e796d93bb2934f40baaaff5b666c3b47db99e8826cf03c` |
| `host/client.py` (unchanged since testbed-04) | `1cda89190c5d2fc42856c4141994c8e8b53f9e65b5ff11f379aba2dc805b01c3` |
| `host/fault_link.py` (unchanged since testbed-04) | `1f18adbd01b330275fe887363b61b8133df74ea9104b6d446f09d61646ddf1b6` |
