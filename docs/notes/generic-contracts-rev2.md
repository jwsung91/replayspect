# The start side of an action: candidates P2–P4 for the generic set (operator note)

2026-11-25. WP6/7d stage 0b (`docs/work-order-wp67d.md`).

**For the operator's decision:** confirm or drop each candidate, and choose how the generic set changes
(below). Nothing is written under `contracts/` in this PR, and no binding has the new role.

**Every count on a blind slot below is a development check, not a measurement.** The candidates were written
after testbed-07's slots were known (S15 and S20 are where they come from), and after testbed-06's.

## The candidates and their instances

| Candidate | In words | Kind | Turntable instance | Lift instance |
| --- | --- | --- | --- | --- |
| P2 | the effect that ends the action only after the effect that starts it, per request id | `only_after` | `motor_stop` after `motor_start` | the same |
| P3 | no effect that starts the action after the state change that starts it, per request id | `never_after` | no `motor_start` after `state(TURNING_TO_LEFT\|TURNING_TO_RIGHT\|TURNING_TO_INITIAL)` | no `motor_start` after `state(MOVING_UP\|MOVING_DOWN)` |
| P4 | the state change that starts the action only after the effect that starts it, per request id | `only_after` | `state(TURNING_TO_LEFT\|TURNING_TO_RIGHT\|TURNING_TO_INITIAL)` after `motor_start` | `state(MOVING_UP\|MOVING_DOWN)` after `motor_start` |

The six files are in [generic-contracts-rev2/](generic-contracts-rev2/), one per candidate and system, each
with `grade: generic` and a `source` naming the rule and quoting it:

| File | sha256 |
| --- | --- |
| `P2.turntable.v0.yaml` | `d1a86bba…621e` |
| `P2.lift.v0.yaml` | `425619e2…8634` |
| `P3.turntable.v0.yaml` | `527b16d6…f8ef` |
| `P3.lift.v0.yaml` | `4177b43d…90d4` |
| `P4.turntable.v0.yaml` | `33c9421e…42d3` |
| `P4.lift.v0.yaml` | `ce8754b3…6995` |

### The role P3 and P4 need: `progress_states`

P2 uses only the role `action` (`starts`, `ends`) the bindings already have. P3 and P4 need the states of an
action in progress, which no binding names. The proposed name is **`progress_states`**, beside
`rest_states`:

```yaml
progress_states: [TURNING_TO_LEFT, TURNING_TO_RIGHT, TURNING_TO_INITIAL]   # lift: [MOVING_UP, MOVING_DOWN]
```

Written as rules, the three would read:

```yaml
- rule: P2
  contract: {id: P2, kind: only_after, per: req_id,
             event: "device.effect({action.ends})", after: "device.effect({action.starts})"}
- rule: P3
  contract: {id: P3, kind: never_after, per: req_id,
             event: "device.effect({action.starts})", after: "device.state({progress_states})"}
- rule: P4
  contract: {id: P4, kind: only_after, per: req_id,
             event: "device.state({progress_states})", after: "device.effect({action.starts})"}
```

Not added to a binding in this stage. **The loader refuses a rule that names a role its binding lacks**
(`no role 'progress_states'`), so a rule using it and the role in both bindings must land together.

**The refusal reason (S09) stays a recorded gap.** No expression is built for it.

## The checks

At `main` `fc3ff8e` (after stage 0a), with no code change. The script is outside the repository
(`run_checks.sh`), every run with `--complete device:recv,send,state,effect`:

```bash
G=docs/notes/generic-contracts-rev2; C="--complete device:recv,send,state,effect"
# turntable: the two incidents with their model results, and the normal corpus
python3 -m replayspect claim check $G/P4.turntable.v0.yaml --system turntable.v0 $C \
  --incident S15-device.log --model S15-report.json --incident S20-device.log --model S20-report.json \
  --normal <the 24 stage 1 sessions> <the 5 unchanged slots> --normal-seeds 0-999 --out P4-turntable-all.json
# lift: seeds
python3 -m replayspect claim check $G/P4.lift.v0.yaml --system lift.v0 $C --normal-seeds 0-999 --out P4-lift-seeds.json
```

Each corpus was also run alone. The model results are `replayspect device SLOT-device.log --system
turntable.v0 --complete device:recv,send,state,effect --out` at `fc3ff8e`.

### The incidents: testbed-07 S15 and S20

| | P2 | P3 | P4 |
| --- | --- | --- | --- |
| S15 (`motor_start` never logged; truth: 55 ms, r-0001) | violated, r-0001 at 3055 ms (`motor_stop` with no earlier start; 3,000 ms after the truth) | not exercised (no `motor_start` to come after the state) | **violated, r-0001 at 55 ms** (the turning state with no earlier start) |
| S20 (`motor_start` logged after the state, same ms; truth: 54 ms, r-0001) | ok | **violated, r-0001 at 54 ms** | **violated, r-0001 at 54 ms** |
| Same request as the model's first mismatch | yes (S15) | yes (S20) | yes (both) |

- Each incident has 6 violations for the candidate that catches it: one per turn of the plan.
- **`claim check`'s verdict** asks for every incident given. With both incidents, P2 and P3 read `fails`,
  each for the incident it does not catch (`ok` or `not exercised`); P4 reads `passes`. The table is the
  per-incident result.

### No false positive

| Corpus | P2 | P3 | P4 |
| --- | --- | --- | --- |
| turntable, seeds 0–999 | 0 violations, exercised 1000 | 0, 1000 (keys tried 5916 of 5916) | 0, 1000 |
| turntable, WP6/7c stage 1's 24 sessions | 0, 24 | 0, 24 (133 of 133) | 0, 24 |
| turntable, testbed-07's 5 unchanged slots | 0, 5 | 0, 5 (30 of 30) | 0, 5 |
| turntable, all 1029 together (list sha256 of the 29 files `14fc1ccb…df57`) | 0, 1029 | 0, 1029 | 0, 1029 |
| lift, seeds 0–999 | 0, 1000 | 0, 1000 (5902 of 5902) | 0, 1000 |
| **lift, the 218 real no-defect logs** | **not run** | **not run** | **not run** |

- **Reported apart:** testbed-07's 2 slots whose change did not act (S11, S22): 0 violations for each
  candidate, exercised on both (P3: 10 of 10 keys tried).
- **The lift's 218 real logs are not on the development machine,** so the lift's real-log check is not run.
  Their list sha256 (`2e155b05…2d38`, `docs/notes/generic-contracts.md`) is checked first when they arrive.
- **Lift real logs that are on the machine,** reported apart and not under the 218's name: testbed-06's five
  unchanged slots (S05, S13, S20, S22, S24; part of the 218) and WP6/7c stage 1's lift session. 0 violations
  for each candidate, exercised on all six.
- No input was not judged.

### What each candidate catches (development check)

Script `dev_check.py`, outside the repository. "Generic" is the bound set (`contracts/generic/<protocol>.yaml`,
G1–G6b and P1); "own" is the protocol's own file (`contracts/turntable.v0.yaml`; for the lift
`contracts/lift.v0.rev3.yaml`, C1–C14). Their columns say whether any of their contracts is violated anywhere
on the slot.

**testbed-07, the 17 acting slots.** Truth is the first difference of the results' per-slot table.

| Slot | Truth | P2 | P3 | P4 | Generic | Own |
| --- | --- | --- | --- | --- | --- | --- |
| S15 | 55, r-0001 | r-0001 at 3055 (request yes, 3,000 ms later) | not exercised | **r-0001 at 55 (request yes, same ms)** | none | none |
| S20 | 54, r-0001 | ok | **r-0001 at 54 (yes, same ms)** | **r-0001 at 54 (yes, same ms)** | none | none |
| S23 (nothing executes) | 55, r-0001 | not exercised | not exercised | not exercised | none | none |
| S06 (`motor_stop` never logged) | 3054, r-0001 | not exercised | ok | ok | G6 | none |
| the other 13 | | ok | ok | ok | as in the results | as in the results |

- **On testbed-07 the three add two slots to the generic set's 8 of 17:** S15 (P2, P4) and S20 (P3, P4). P4
  alone adds both, each at the truth's request and millisecond.
- **Still missed by both sets and the candidates:** S03, S04, S09, S17, S23.
- The generic and own columns agree with the results' table on all 17 slots.

**testbed-06, the 18 acting lift slots.**

| Slot | P2 | P3 | P4 | Generic | Own (rev3) |
| --- | --- | --- | --- | --- | --- |
| S23 (`motor_start` logged with the previous command's id, empty for r-0001; truth 55 ms, r-0001) | r-0001 at 3055 | r-0001 at 5672 (the next move's start, logged with r-0001) | **r-0001 at 55** | none | C9 |
| the other 17 | ok | ok | ok | | |

- **The candidates add one slot to the generic set on testbed-06** (9 of 18, `docs/notes/generic-contracts.md`):
  S23, which rev3 catches only by C9, at the end of the run.
- **testbed-04 and testbed-05's acting slots: not run** (the logs are not on the development machine).

**The lift's mutants, seeds 0–999** (seeds violated, of 1000; "alone" is where no generic rule and no rev3
contract is violated on that seed):

| Mutant | P2 | P3 | P4 |
| --- | --- | --- | --- |
| correct | 0 | 0 | 0 |
| M1–M11 (each) | 0 | 0 | 0 |

- **No candidate is violated on any seed of any lift mutant.** No fault in the simulator touches the start
  of the action, so "alone" is 0 everywhere. The candidates' catches here are the changed firmware's (S15,
  S20, testbed-06 S23), not the simulator's.

## The order P3 and P4 rely on, in the protocol documents

Whether these sentences state an order is the operator's reading. The lines:

`docs/protocol-turntable.md`, lines 57–61:

> A refused command is answered with `ERROR` carrying the reason: `limit`
> when the table is already at the end position in that direction,
> `illegal` in every other case. A legal one starts the motor and the state
> becomes the `TURNING_TO_*` state from the table; 3 s later the motor stops
> at the next sensor, the state becomes the target position, and `DONE` is
> sent.

`docs/protocol-lift.md`, lines 44–46:

> `ERROR` (reason `illegal`). A legal one starts the motor and the state
> becomes `MOVING_UP` or `MOVING_DOWN`; 3 s later the motor stops, the state
> becomes `UP` or `DOWN`, and `DONE` is sent.

- The sentence names the start of the motor first and the state change second, joined by "and". P1 rests
  on the same kind of sentence for the end of the action ("the motor stops, the state becomes …").
- P2 (stop after start) rests on "starts the motor … 3 s later the motor stops".
- Neither document mentions the device log or its effect lines. The order inside one millisecond is the
  firmware's (the motor start logged before the state change), which the documents do not describe.

## How the generic set changes when a rule is added

`rules.yaml` has no revision. Reports name it by sha256: testbed-07's registration names `fcbfd0af…a115`
(`rules.yaml`) and the two bindings, and `claim check` prints the rules file's sha256 when given a binding.

| | A. A new rules file beside the old | B. The old file changed in place |
| --- | --- | --- |
| Files | `contracts/generic/rules.rev2.yaml` (the old rules and the new), and bindings `lift.v0.rev2.yaml`, `turntable.v0.rev2.yaml` naming it, with `progress_states`. The old three stay as they are | `rules.yaml` gains the rules; both bindings gain `progress_states` |
| testbed-07's numbers | reproduce from `main` with the registered files and hashes (`fcbfd0af…`, and the bindings') | reproduce only from the commit before the change (`git show 9c87f4e:contracts/generic/rules.yaml`); on `main` the same binding path gives more contracts and another sha256 |
| A report names | which set by path and sha256, as today | the set by sha256 only; the path no longer tells the revisions apart |
| Cost | two sets on `main`; a session names the one it uses. The lift's own contracts already work this way (`lift.v0.yaml`, `.rev2`, `.rev3`) | one set; every earlier report's path now means another file |

**Recommendation: A.** It follows the lift's own files, keeps every registered hash true on `main`, and the
stage 4 tests can say "the rules already there expand to the same contracts as before" by loading both
bindings. The old set stays the one testbed-07 measured; the next blind group registers the rev2 set by its
hashes.

## Recommendations

| Candidate | Recommendation | Why |
| --- | --- | --- |
| P4 | **keep** | no false positive on the corpora run; catches S15 and S20 at the truth's request and millisecond, and testbed-06 S23 at 55 ms, where no generic rule fires |
| P3 | covered by P4 on these checks | every catch here (S20) is also P4's, at the same time. It would add a start logged twice with the second after the state (testbed-06 S23 at 5672 shows that shape, after P4 already fired). Keep only if that case matters on its own |
| P2 | covered by P4 on these checks | its catches (S15, testbed-06 S23) are P4's, 3,000 ms later. It would add a stop with no start where no turning state was logged either; no input here has that shape |

- **The lift's real no-defect logs are not run.** P4's "no false positive" holds on the seeds and the real
  logs that are here (turntable 29, lift 6), not on the 218.
- **What P4 does not say:** that the state change comes at all. A start with no turning state breaks no
  `only_after` of the state. That is a rule about presence, like P1's limit.

**The operator confirms or drops each candidate and decides the form.** After that, in its own PR: the rules,
the role in both bindings, the stage 4 tests, `contracts/generic/README.md`, the changelog, `CLAUDE.md`, the
README status and the backlog row.
