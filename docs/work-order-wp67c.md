# replayspect work order WP6/7c — the generic set's first measurement, on a turntable testbed

2026-11-22

This is an addition to `docs/work-order-v3.md`, after `docs/work-order-wp67b.md`. All of their principles and constraints apply. It has four stages, in this order: publish what is local (stage 0), bring the turntable up on the board with unchanged firmware (stage 1), register a blind group (stage 2), run and score it (stage 3).

**This order was written without sight of the two local branches** (`feat/testbed-travel-sensor`, `feat/testbed-turntable-firmware`). Where it conflicts with what they contain, say so in the stage 0 report, before any stage 1 work.

## Why

WP6/7b left one claim open (`docs/work-order-wp67b.md`, "What may be claimed afterwards"): the generic set's catching power on a system other than the lift is unknown.

- **Every number so far is a development check.** The generic rules caught 21 of 34 acting blind slots (`docs/notes/generic-contracts.md`), but the rules were written after those slots were known, and all 34 are lift slots.
- **The library is for a protocol that has few contracts of its own.** On the lift most generic rules repeat a lift contract. Its use is on a new protocol, so that is where it has to be measured.
- **The turntable is the only other system.** Its binding is merged (`contracts/generic/turntable.v0.yaml`), its own contracts are the original eight, and it has no defects of any kind, in the simulator or in firmware.

The device comparison (`replayspect device`) has also never run on a second system's real logs. This order measures that too.

## What exists already

- `contracts/generic/`: `rules.yaml`, the two bindings, the loader's expansion (#62). **The rules file and both bindings are frozen for this order.**
- `contracts/turntable.v0.yaml` (C1–C8). **Frozen**, like every file in `contracts/`.
- `turntable.v0`: the Python model with a device model (`System.device`), the protocol document, no mutants. `replayspect device --system turntable.v0` takes any system with a device model.
- `examples/testbed-uno/`: the lift's firmware, host (`client.py`, `fault_link.py`), ingest rules, the native harness and `fired_points.py`.
- The blind procedure of testbed-05 and testbed-06 (`docs/experiments/testbed-06-preregistration.md`): the roles, the draw, the hashes, the scoring rules.
- Two local branches, not on the remote: `feat/testbed-travel-sensor`, `feat/testbed-turntable-firmware`.

## Stage 0 — publish what is local

No new work in this stage.

- Push the two branches and open one PR each, not stacked. If one depends on the other, say which and open the first only.
- Each PR body reports, in the usual form: what the branch does, what was run, what was not, and what is unfinished.
- For the turntable firmware, say plainly which of these exist and which do not:
  - the device as a plain C++ header, compiled natively by a harness (as `lift_device.h` is);
  - a conformance test against the Python turntable model;
  - a host client for the turntable's command list, and ingest rules for its client log;
  - device log lines (`recv`, `send`, `state`, `effect`) in the lift's format;
  - a scoring tool that prints the first output where a changed and the unchanged header differ on a log's inputs (the turntable's `fired_points.py`).
- For the travel sensor: say what it changes and whether the turntable work depends on it. This order does not use it otherwise.
- Ask the operator which board runs the turntable. Do not choose one.
- Replace the "다음" line of `CLAUDE.md` with this order.

Stop and report. The advisor reviews both PRs. The operator merges.

## Stage 1 — the turntable on the board, unchanged firmware

Make the turntable testbed complete, and find out whether the tool is quiet on its real logs before anything is changed.

- **Finish what stage 0 listed as missing.** Tests first. The native conformance test must pass before any flashing.
- **Sessions:** as on the lift. 6 commands, 90 s, 115200 baud, device log on.
- **A development corpus of real no-defect logs.** About 24 sessions on the unchanged firmware: every plan kind the blind pool will use, at least twice. The kinds are testbed-06's twelve, carried over to the turntable's messages. A kind with no turntable counterpart is dropped and named in the report; do not invent a replacement. Use seeds the blind pool will not use.
- **Checks on every session,** as commands:
  - the run is valid and the link applied every planned fault;
  - `replayspect device --system turntable.v0 --complete device:recv,send,state,effect`: the correct model conforms;
  - the same command with `--contracts contracts/turntable.v0.yaml`: no violation;
  - the same command with `--contracts contracts/generic/turntable.v0.yaml`: no violation, and say for each contract whether it was exercised.
- **One false mismatch or one false violation stops the stage.** Report the log and the line. Do not widen a comparison rule, change a contract or edit the model to pass. The same-millisecond rule, the 2 ms window and the per-request order were all set on lift logs; whether they hold here is what this stage finds out.
- **Report in** `examples/testbed-uno/README.md` (a turntable section) and the PR body. The real logs stay outside the repository; list them by sha256.

Stop and report. **The operator decides whether the testbed is fit for a blind group.**

## Stage 2 — the registration of testbed-07

A draft registration, `docs/experiments/testbed-07-preregistration.md`, in testbed-06's form. No session is run in this stage.

- **Question.** On turntable firmware the operator changed, does the analysis find where the change acted, and which contracts catch it? Each slot gets separate answers:
  - **the device model:** conforms, or its first mismatch (scored S1 and S2 as in testbed-06);
  - **the generic set alone:** `contracts/generic/turntable.v0.yaml`, judged on the device log alone. This is its first measurement;
  - **the turntable's own contracts alone:** `contracts/turntable.v0.yaml`;
  - **both together:** the union of the two results, computed from them. No merged file and no new option.
- **Listed apart in the contract result:**
  - each generic rule's count;
  - the generic rules that repeat one of the turntable's own contracts (G1 for `motor_start`, G2 for the final answer, G3) and those that do not;
  - false violations on unchanged builds and on changed builds whose change did not act, for each set.
- **What the analyst knows of the changes** is one sentence, written by the operator into the draft. The advisor makes the rules, the candidates and the draw script; nobody picks a change by hand. The analyst lists what it has seen of earlier groups' rules and candidates, as testbed-06's registration does.
- **Size:** testbed-06's (24 slots, a pool of four plans per kind), unless the operator says otherwise.
- **The plan pool,** with new seeds from a range no earlier experiment used, and testbed-06's check on every plan: on the unchanged firmware in the simulator, the link applies every fault, the run is valid, the correct model conforms, neither contract set is violated, and the unchanged header compiled natively reproduces the simulated device log.
- **Harness:** pinned to one commit. `analyze.py` refuses to run if `src/`, `contracts/` or the testbed's rules differ from it. The registration lists the sha256 of the binding file and of `rules.yaml`, both.
- **Predictions** that do not depend on what the changes are:
  - no false mismatch and no false violation (either set) on unchanged builds;
  - the claim of the method (the first mismatch is on the request the change acted on);
  - **the generic set's documented gaps,** from `docs/notes/generic-contracts.md` ("Limits of the generic set"), each as a predicted miss: a change that only moves a time, only takes an undeclared transition, only changes what a poll reply says, only drops a reply, or acts only on the client side;
  - testbed-06's predictions 6–9, where they apply to the turntable.
  A predicted miss still counts as a miss in the totals.
- **Limits,** stated in the draft. At least these:
  - the turntable has the lift's shape with other names, so a good result is weak evidence that the rules are generic (`docs/notes/generic-contracts.md`, "What the turntable can and cannot show");
  - the generic rules were written from lift contracts that came out of testbed-04, 05 and 06. If this group's changes resemble those groups', the generic set's count is flattered by its own development data. The operator's statement on the overlap is reported with the results;
  - the advisor wrote the generic rule list and makes this group's changes;
  - the comparison's timing rules were set on lift logs.
- **A dry run,** development only: one change the analyst makes itself in a scratch copy outside the repository, run in the simulator, to produce an example submission line and to try the scoring tool. It is not kept as a candidate and is described in the draft.
- **Scripts** (`run_blind.sh`, `blind_flash.sh`, `analyze.py`, the pool maker) live outside the repository, as before, and are listed with their hashes.

Stop and report. **The operator approves the registration.** Its sha256 is recorded before the draw.

## Stage 3 — the run, the submission and the results

After the registration hash, in testbed-06's order.

1. The advisor's draw and the operator's assignment file. The analyst receives only hashes.
2. The testbed folder is placed on the Orin. From then on the analyst does not use the Orin until it has handed over the submission's hash.
3. The operator builds, flashes and runs each slot in the drawn order, and copies only the client and device logs to the development machine.
4. The analyst runs `analyze.py` once on all slots, writes the descriptions, and gives the operator the submission's sha256.
5. Scoring runs only after that hash. The scoring output and the assignment file go to the analyst afterwards.
6. **Results:** `docs/experiments/testbed-07.md`, in testbed-06's form. This document does not rewrite the registration. Every difference from the registration is listed.
7. **Afterwards, as records only:** the slots each set missed, in the coverage note's form; `docs/backlog.md` rows for anything found and not fixed; the changelog, `CLAUDE.md` and the README status.

No contract, rule or binding is changed in this order, whatever the result. A slot the generic set missed is a row in the results, not a new rule.

Stop and report.

## Amendments after stage 0

2026-11-22, from the advisor after the stage 0 PRs (#63, #64, #65) were merged. They apply to stage 1
unless marked otherwise.

**A. Fix main first.**
1. `harness.cpp` did not compile with `-DHARNESS_TURNTABLE=1`: #63's `dev.on_position` does not exist on
   the turntable `Device`, so the six tests in `tests/test_testbed_turntable.py` errored. The `@pos`
   input is compiled in the lift build only, and the full suite is run again on main. This fix is the
   first commit of the stage 1 branch, on its own.
2. From now on, when more than one PR is opened from the same main, the second is rebased onto main
   and the full suite run again before it is merged.

**B. Boards.**
3. Two Unos are connected to the Orin, one for the lift and one for the turntable only. Which is which
   is fixed by its `/dev/serial/by-id/` path; scripts and documents do not use `/dev/ttyACM0`.
4. A session or a flash refuses a board that does not carry the expected system. Today the two
   firmwares' boot lines are the same. The method is reported and confirmed before it is implemented
   (for example, the system name added to the turntable's build line and checked by the client). The
   lift firmware's output does not change. Other items go on while this waits.
5. The run's records (the truth file and the like) name the board's by-id path.
6. The turntable uses the timer build only. Servo and sensor parts are not present and are outside
   this order.

**C. Host and tools.**
7. No new client: `client.py` takes a command list. With the default (the lift) its client log is
   byte-for-byte what it was, fixed by a test. A reason to change `fault_link.py` is reported first.
8. The turntable gets its own ingest rules file (`system: turntable.v0`). The existing rules file does
   not change.
9. `fired_points.py` needs only the `--reference` comparison for the turntable header. The turntable has
   no defect switch.
10. A test that `replayspect device --system turntable.v0` reads a harness-made turntable device log: the
    model conforms, neither contract set is violated, and whether each generic contract was exercised.

**D. Runs on the boards.**
11. After `client.py` is changed, one no-defect session on the lift board, and `replayspect device`
    conforms (a development check).
12. On the turntable board, the development corpus of about 24 sessions as above. A single false
    mismatch or false violation stops the stage; the log and the line are reported. No comparison rule,
    contract or model is changed to pass.

**E. Documents.**
13. A to E are written here, as this section.
14. The "Travel sensor build" section of `examples/testbed-uno/README.md` says that build has been
    through the harness tests only and has never run on a board with a servo and sensors attached.
15. **Stage 2:** testbed-07 runs on the turntable board alone. The draft registration says so.

## What may be claimed afterwards

- The generic set's count on testbed-07's acting slots is a measurement, on one protocol of the lift's shape, with mechanical changes, on 24 slots. It is not evidence for a protocol of another shape.
- The device comparison's result on the turntable is its first on a second system.
- Stage 1's corpus is development data. "No false mismatch on the turntable's no-defect logs" is a development check until the blind group's unchanged slots are scored.
- A rev4 contract for the lift and C14 on a changed build are still unmeasured.

## Not in this order

- Any change to a file in `contracts/`, to the rules file or to a binding.
- A new rule, a turntable contract revision, or a candidate note. Those come from the results, in a later order, through `claim check`.
- A third system, or a protocol of another shape; roles that can be left out (backlog, #62 review (a)).
- The session option for the generic set, and the trace header's record of the rules file (backlog, #62 review (b)).
- Turntable mutants in the Python model; published turntable defects.
- A new blind group on the lift.
- A motor, a table or any mechanism. The testbed is the board, the serial link and the clock.
- The symptom oracle, WP8 (provider interface) and WP9 (ranking).

## Constraints

- One stage per branch and PR. No stacking. The operator merges every PR.
- The report goes in the PR body. The advisor reviews on the PR from the code.
- Planner-visible files (the protocol documents, the plan format, every file in `contracts/`) name no defect, mutant, experiment slot or operator note.
- The blind materials (the rules, the candidate lists, the assignment files, the scoring) are not copied into the repository. Real logs stay outside it.
- A result that was not checked is never reported as checked. Where the data is missing, say so and stop.
- No new dependency. Tests first. `git diff --check` and the full test suite before each PR.
