# Contract candidate for rev4 (operator note)

2026-11-15. WP6/7b stage 2 (`docs/work-order-wp67b.md`).

**The operator's decision** (2026-11-15, after the #60 review): **A1 is confirmed.** The operator reads
`docs/protocol-lift.md` lines 45–46 as stating the order motor stop → state change → `DONE`.
- **`grade: stated` rests on the operator's reading.** The sentence has no word of order ("then",
  "after"); it lists the three steps in that order.
- **A1 was written after the changes behind S15 and S19 were known.** That it catches the two incidents is
  a development check.
- **A1 is unmeasured until a new blind group.**
- No contract file is written in this PR (below, "After the operator's decision").

The rest of this note is the record as it was written for that decision.

testbed-06's slots are development data from now on. Every "catches" below is a **development check**, not
a measurement. The candidate comes from testbed-06's "Proposals", written after scoring: the changes behind
S15 and S19 (Q158 and Q163, the arrival lines in another order) were known when it was drafted. A rev4
contract, if confirmed, stays unmeasured until a new blind group, and none is planned.

## The two slots, as the tools show them

Material:
- the slots' device logs. Their sha256 equal those recorded at the blind
  (`~/rs-control/testbed-06/blind-logs.sha256`);
- the correct device model's report on each, remade at `5eaa9df` (main after #59, with stage 1's order
  rule): `replayspect device --complete device:recv,send,state,effect --out`.

| Slot | First mismatch (stage 1, device clock) | The device's arrival lines, on all six arrivals | rev3 contracts |
| --- | --- | --- | --- |
| S19 | 3055 ms, `r-0001`, order difference: model `state UP …`, then `send DONE`; device `send DONE`, then `state UP …` | `motor_stop`, `DONE`, state change | none violated |
| S15 | 3054 ms, `r-0001`, order difference: model `motor_stop`, state change, `DONE`; device `DONE`, `motor_stop`, state change | `DONE`, `motor_stop`, state change | C10 (`DONE` before `motor_stop`) |

The client cannot see either change: the three lines are the device's, inside one millisecond, and the
`DONE` reaches the client as on an unchanged build.

## Claim and candidate

| Claim | Slots | Trigger and effect | Candidate |
| --- | --- | --- | --- |
| D | S19, S15 | On arrival, the device sends `DONE` before the state becomes `UP` or `DOWN`. | **A1**: `DONE` for a `req_id` only after the state became `UP` or `DOWN` for that `req_id` |

The candidate file is [contract-candidates-rev4/A1.yaml](contract-candidates-rev4/A1.yaml):
- one `only_after` contract: `event: device.send(DONE)`, `after: device.state(UP|DOWN)`, `per: req_id`;
- `grade: stated`;
- a `source` citing `docs/protocol-lift.md` lines 45–46: "3 s later the motor stops, the state becomes `UP`
  or `DOWN`, and `DONE` is sent."

The state lines carry the request's id (`state UP r-0001 from=MOVING_UP on=arrived`), so the key is the
request.

**Whether the sentence states an order is the operator's reading.** It lists three things in the order the
firmware does them. It does not say "then" or "after". C10 already reads the same sentence as an order
(`DONE` after the motor stop) with `grade: stated`. A1 reads the second half of it the same way.

**The motor's direction (S06) stays a recorded gap** (coverage note, lines 44–45). No expression is built
for it.

**A gap A1 leaves:** the order motor stop → state change is covered by neither A1 nor C10. A state change
before the motor stop, with `DONE` after both, breaks neither. The coverage note's row is updated in the
rev4 PR.

## The check

At `5eaa9df`. A1 was run with both incidents, each with its stage-1 model result, on three normal corpora:
- `real`: the 218 real no-defect device logs;
- `sim`: seeds 0–999 of the correct lift;
- `all`: both. This is the corpus the work order names, and the official run.

The script is `~/rs-control/wp67b-stage2/run_checks.sh`. Its core:

```bash
python3 -m replayspect claim check docs/notes/contract-candidates-rev4/A1.yaml \
    --incident incidents/S19-device.log --model models/S19-device-report.json \
    --incident incidents/S15-device.log --model models/S15-device-report.json \
    --normal normal --normal-seeds 0-999 --complete device:recv,send,state,effect --out out/A1-all.json
```

(The `real` and `sim` runs drop `--normal-seeds` or `--normal`.)

**The real corpus.** It has 218 device logs: the 213 of the rev3 note (same files, list sha256 `7342eff0…`)
and testbed-06's five unchanged slots, S05, S13, S20, S22 and S24 (as `normal/tb06-<slot>-device.log`). The
sha256 of the list is `2e155b05bdcd9310de0dd9999d69ba5d97c1834582071738d928e7eee15b2d38`, in the rev3
note's form (`LC_ALL=C sha256sum normal/* | sha256sum`). The logs hold 1288 `DONE` sends.

These logs are outside the repository, so the real-corpus numbers can be reproduced on one machine only. The
simulator part can be reproduced from the repository alone (below).

### Results

| Candidate | Incidents (first violation; same request as the model's first mismatch) | Corpus | Verdict | Exercised | Normal violations |
| --- | --- | --- | --- | --- | --- |
| A1 | S19 `r-0001` at 3055 ms, yes; S15 `r-0001` at 3054 ms, yes | real | passes | 218 of 218 | 0 |
| | | sim | passes | 1000 of 1000 | 0 |
| | | **all** | **passes** | 1218 of 1218 | 0 |

Every normal input's status was `ok`. No input was not judged. On each incident A1 is violated on all six
arrivals (r-0001 to r-0006); the first is reported.

The text output of the official run (from the check folder, which links `docs` to the repository's, so no
local path is quoted):

```text
claim check: 1 candidate(s), 2 incident(s), normal corpus 1218 input(s) (218 file(s), seeds 0-999 of lift.v0, implementation with no defect)
candidates: docs/notes/contract-candidates-rev4/A1.yaml sha256 1bb1035012073a7e3b5d4155280c8f17454cfe756e0fc5e3e25deff4dc0384e7
device logs declared complete for: device effect, device recv, device send, device state
incident 1: incidents/S19-device.log (device log) sha256 64e1e2dfb13378be97d429895c0a8b718b3b59193d6d8bba80065b7a596cca83
  model result: models/S19-device-report.json sha256 5ee3b28b9385c5103fd5896cd98cb0913428cd2eefd2478035bbd596718219a6
incident 2: incidents/S15-device.log (device log) sha256 f58f4d421b4f57e132a9871dee68935a11d950d34e9d263b9c9fb8d2c19ff3e5
  model result: models/S15-device-report.json sha256 0153adba7c10aefa1e0b3184b01d7a3971505a140d6fc6d96b9240bd9af9f4bf
normal files: 218, sha256 of the list (sha256, two spaces, path; one per line) 2e155b05bdcd9310de0dd9999d69ba5d97c1834582071738d928e7eee15b2d38

A1 (only_after): passes
  incident 1: violated at t=3.055000s r-0001: DONE with no earlier device.state(DOWN|UP) (6 violations)
    the model's first mismatch: r-0001; same request as the model's first mismatch: yes
  incident 2: violated at t=3.054000s r-0001: DONE with no earlier device.state(DOWN|UP) (6 violations)
    the model's first mismatch: r-0001; same request as the model's first mismatch: yes
  normal: exercised in 1218 of 1218; ok 1218
```

**The simulator part from the repository alone** (run at the repository root):

```python
from pathlib import Path
from replayspect.claim import judge_one, sim_input
from replayspect.contract import load_contracts
from replayspect.runner import get_system

system = get_system("lift.v0")
cs = load_contracts(Path("docs/notes/contract-candidates-rev4/A1.yaml"))
rows = {"exercised": 0, "violations": 0}
for seed in range(1000):
    r = judge_one(cs.contracts[0], cs, sim_input(system, seed))
    rows["violations"] += len(r["violations"])
    rows["exercised"] += r["status"] in ("ok", "violated")
print(rows)  # expected: {'exercised': 1000, 'violations': 0}
```

### Beside the check: other blind slots and the simulator mutants

Also a development check (the script is `~/rs-control/wp67b-stage2/dev_check.py`). A1 and rev3's C10 were
judged side by side, with the device's four kinds declared complete.

**Blind slots** (testbed-04 B01–B08, testbed-05 S01–S16, testbed-06 S01–S24). A1 fires on seven slots:

| Slot | A1 (first violation) | C10 (first violation) |
| --- | --- | --- |
| testbed-04 B01 | `r-0004`, 17985 ms | same |
| testbed-04 B06 | `r-0005`, 20432 ms | same |
| testbed-05 S09 | `r-0003`, 8371 ms | same |
| testbed-06 S01 | `r-0002`, 8687 ms | same |
| testbed-06 S15 | `r-0001`, 3054 ms | same |
| testbed-06 S19 | `r-0001`, 3055 ms | **not violated** |
| testbed-06 S21 | `r-0003`, 10236 ms | same |

C10 fires on no slot where A1 does not.

**Simulator, seeds 0–999.** The correct lift: 0 for both. Of the mutants M1–M11, only M10 violates either:
A1 on 24 seeds, C10 on the same 24, with the same first violation on all 24. A1 never fires where C10 does
not.

## What the numbers say

- **Both incidents fall to A1,** on the request and at the time of the device model's first mismatch. This
  is a development check on the slots it was drafted from.
- **No violation in the normal corpus:** not on the 218 real logs (1288 `DONE` sends), and not on the 1000
  seeds.
- **What A1 adds to rev3 is one case:** a `DONE` sent after the motor stop but before the state change
  (S19). Everywhere else it fired, on hardware and in the simulator, C10 fired too, with the same first
  violation. That is expected: on arrival the firmware stops the motor before it changes the state, so a
  `DONE` that breaks A1 breaks C10 too, unless it falls between the stop and the state change.
- **Its exercise is wide but shallow.** Every input with a `DONE` exercises it ("exercised" for
  `only_after` is that its `event` occurred). No unchanged build, real or simulated, sent a `DONE` before
  the state change.

## Recommendation

- **The operator's call, with one point each way:**
  - **For confirming A1:** it is stated by the same sentence C10 cites, it caught both incidents on the
    right request, and it passed on 1218 normal inputs with no violation.
  - **Against:** it adds exactly one case to C10, an order inside one millisecond. Since stage 1 the device
    model sees that case on its own (S15 and S19 now differ), so A1 matters only where the contracts are
    used without the model, or where the receives are not logged.
- **If A1 is confirmed,** a limit to record: like C10, it reads the log's line order. A device that logs
  the arrival lines in another order than it acts would be caught for what it logged (the device log is
  the suspect's statement).

## After the operator's decision (not done here)

**When:** the rev4 PR opens after the operator's decision on stage 3 (the generic rules).
- If stage 3 gives a generic rule that holds the order of the state change, A1 is folded into it, or the
  two go into one file.
- rev4 is merged before testbed-07 is registered.

**What the rev4 PR holds:**
- `contracts/lift.v0.rev4.yaml`: rev3 unchanged, plus the contract, with a planner-neutral id and wording;
- the oracle in `tests/lift_oracle.py`;
- the per-mutant table on seeds 0–999;
- the coverage note's rows: lines 45–46, "on arrival `DONE` comes after the state change", and the gap
  above (motor stop → state change).

**Tests for the rev4 PR:**
- (a) **Hand-written traces that tell A1 and C10 apart:**
  - motor stop → `DONE` → state change: A1 is violated, C10 is not;
  - state change → `DONE` → motor stop: C10 is violated, A1 is not.
- (b) **Not judged, not violated:** on a device log whose state lines are not declared complete, and on a
  key with a reorder mark, A1 is not judged.
