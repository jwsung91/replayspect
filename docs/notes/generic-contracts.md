# The generic rules, as plain contracts (operator note)

2026-11-15. WP6/7b stage 3 (`docs/work-order-wp67b.md`).

**The operator's decision** (2026-11-15, after the #61 review):
- **To stage 4:** G1, G2 (three roles), G3, G4, G5, G6 and G6b.
- **P1:** rewritten as `never_after` (`event: device.effect(motor_stop)`, `after: device.state(<rest
  states>)`, `per: req_id`) and checked like the others. With no false positive it goes to stage 4; with
  one it is reported and stays. **Result: no false positive, so P1 goes to stage 4** (below, "G6b, and the
  order motor stop → state change"). The `only_after` form that failed is kept in this note.
- **G7 and G8 do not go on.** G7's declared form needs the protocol's own transition table, so it is that
  protocol's contract (C3 on the lift), not a generic one. G8 cannot be stated (below).
- **The proposals outside the list** (a poll reply carries the state; the client rules) are not added this
  time. They stay here as a record, so the generic set's limits include M5 and M6–M8 (below, "Limits").
- **The form is approved:** `grade: generic` with `source` (`rule`, optional `quote`), and the shape of the
  `roles` section. Where the roles file lives and how a session asks for the generic set are proposed in
  the stage 4 PR.
- **A1 is folded into G6b.** No rev4 file is written. The tests the rev4 note asks for (the two traces
  that tell A1 and C10 apart; not judged where the state lines are not declared complete or a key carries
  a reorder mark) go into stage 4, for G6 and G6b.

Nothing is written under `contracts/` in this PR.

The record below was written for that decision; the P1 section, the limits and the stage 4 list were
updated after it.

This note checks which rules that do not depend on the lift survive when written by hand, in the existing
language, for the lift and for the turntable. No mechanism is built: no roles section, no expansion, no
`contracts/generic/`.

**The blind-slot numbers below are a development check, not a measurement.** The rules were written after
the slots of testbed-04, 05 and 06 were known.

## The rules and their instances

The list G1–G8 is fixed by the work order. G6b was added by the operator's decision (2026-11-15) and is
checked like the others. P1 is a proposal of this note (below), rewritten after the review.

| Rule | In words | Lift and turntable instance | Kind | Lift contract it generalizes |
| --- | --- | --- | --- | --- |
| G1 | at most one effect of each name per request id | G1a: `motor_start`; G1b: `motor_stop` | `at_most_once` (one per effect name) | C1 |
| G2 | per request id and reply role (acknowledgement, final answer, poll reply), no more replies than requests received | G2a: `ACK` against the requests; G2b: `DONE\|ERROR` against the requests; G2c: `STATUS_REPLY` against `STATUS` | `count_le` | C12, C7, C13 |
| G3 | the two final answers exclude each other, per request id | `DONE` and `ERROR` | `mutually_exclusive` | C8 |
| G4 | the device sends nothing for a request id it has not received | `device.send` only after `device.recv`, both without names | `only_after` | none |
| G5 | no acknowledgement for a request id after its final answer | `ACK` after `DONE\|ERROR` | `never_after` | C14 |
| G6 | the final answer of success only after the effect that ends the action | `DONE` after `motor_stop` | `only_after` | C10 |
| G6b | the final answer of success only after the state change that ends the action | `DONE` after the rest states (lift `UP\|DOWN`; turntable `LEFT\|RIGHT\|INITIAL`) | `only_after` | A1 (rev4, confirmed, not yet in a file) |
| G7 | the state changes only along transitions seen in normal runs | written here with the **declared** transitions, as a stand-in | `state_machine` | C3 |
| G8 | no effect from a reply that arrives after the client gave up | not written (below) | – | none |

The files are [generic-contracts/lift.v0.yaml](generic-contracts/lift.v0.yaml) and
[generic-contracts/turntable.v0.yaml](generic-contracts/turntable.v0.yaml). The two differ only in the request
names, the rest states and the transitions. Each contract has `grade: generic` and a `source` that names its
rule.

**Two rules need more than one contract.**
- **G1:** the language keys only by `req_id`. A pattern without names (`device.effect`) would count a
  request's `motor_start` and `motor_stop` together, so there is one contract per effect name.
- **G2:** one contract per reply role.

### The `source` form (decided in this PR)

```yaml
grade: generic
source:
  rule: G1
  quote: "at most one effect of each name per request id"
```

- **The loader** (`src/replayspect/contract/spec.py`) now accepts `grade: generic`.
  - A generic contract must have a `source` with `rule`.
  - Its source may hold only `rule` and `quote`.
  - `rule` is refused in any other grade's source.
- **Tests first** (`tests/test_contract.py`).
- **The form passes the whole-file word scan of `contracts/`:** it names the rule and nothing else, with no
  `found`, no notes path, and no experiment, defect or operator word. The scan's regular expression finds
  nothing in either candidate file.

### `claim check` with no incident (a missing parameter)

`claim check` refused to run without an `--incident`. The turntable has no incident, and the work order
asks for its check with `claim check --system`.
- **The change:** that one refusal is removed. With no incident, only the normal corpus is judged: a
  false-positive check, where `passes` says only that the candidate was exercised and never violated there.
- **Covered by** a test (`tests/test_claim.py`), `docs/claims.md` and the module documentation.
- **After the review,** each verdict says so: its line reads `<id> (<kind>): <verdict> (no incident: normal
  corpus only)`, and each result in the JSON has `"no_incident": true` beside the verdict (`false` with
  incidents). Tests first. The outputs of the checks below were remade with it; apart from that key they
  are byte for byte the first run's (kept in `out/01c43d5/`).
- Nothing else in `claim check` changed.

## The checks

At this branch: main `ec01c74` plus the two changes above. The script is `~/rs-control/wp67b-stage3/run_checks.sh`:

```bash
G=docs/notes/generic-contracts; C="--complete device:recv,send,state,effect"
python3 -m replayspect claim check $G/lift.v0.yaml --normal normal --normal-seeds 0-999 $C --out out/lift-all.json
python3 -m replayspect claim check $G/turntable.v0.yaml --system turntable.v0 --normal-seeds 0-999 --out out/turntable-sim.json
```

The lift was also run on the real logs alone and on the seeds alone. The real corpus is the 218 no-defect
device logs of the rev4 note (list sha256 `2e155b05…2d38`).

### No false positive

| Rule | Lift, 218 real logs | Lift, seeds 0–999 | Turntable, seeds 0–999 | Verdict (all three) |
| --- | --- | --- | --- | --- |
| G1a | 0 violations, exercised 218 | 0, exercised 1000 | 0, exercised 1000 | passes |
| G1b | 0, 218 | 0, 1000 | 0, 1000 | passes |
| G2a | 0, 218 | 0, 1000 | 0, 1000 | passes |
| G2b | 0, 218 | 0, 1000 | 0, 1000 | passes |
| G2c | 0, 218 | 0, 1000 | 0, 1000 | passes |
| G3 | 0, 218 | 0, 1000 | 0, 1000 | passes |
| G4 | 0, 218 | 0, 1000 | 0, 1000 | passes |
| G5 | 0, exercised 8 (8 of 1301 keys tried) | 0, 917 (2052 of 5964) | 0, 922 (2022 of 5957) | passes |
| G6 | 0, 218 | 0, 1000 | 0, 1000 | passes |
| G6b | 0, 218 | 0, 1000 | 0, 1000 | passes |
| G7 (declared) | 0, 218 | 0, 1000 | 0, 1000 | passes |

- **No rule had a false positive** on any of the 2218 normal inputs. No input was not judged.
- **"Exercised"** is `claim check`'s measure. For G5 (`never_after`) it is the conservative one: a request the
  device heard of again after its final answer. On the real logs that happened 8 times: testbed-03's five
  after `ERROR`, and testbed-06's three after `DONE`.

Candidate file sha256: lift `77c02bde…c260`, turntable `a02479fb…aca0`.

### What each rule catches: the lift's mutants, seeds 0–999

Seeds (of 1000) on which each rule is violated. Development check script:
`~/rs-control/wp67b-stage3/dev_check.py`.

| Mutant | G1a | G1b | G2a | G2b | G2c | G3 | G4 | G5 | G6 | G6b | G7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| correct | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| M1 (no duplicate detection) | 0 | 0 | 0 | 0 | 0 | 995 | 0 | 891 | 0 | 0 | 0 |
| M2 (id recorded at `DONE`) | 0 | 0 | 0 | 0 | 0 | 959 | 0 | 0 | 0 | 0 | 0 |
| M3 (resends `DONE` after a reconnect) | 0 | 0 | 0 | 996 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| M4 (opposite move taken) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 19 |
| M5 (`STATUS` reports the old state) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| M6, M7, M8 (client) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| M9 (id recorded at execution) | 0 | 0 | 0 | 0 | 0 | 22 | 0 | 0 | 0 | 0 | 0 |
| M10 (`DONE` for a refused repeat) | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 24 | 24 | 0 |
| M11 (remembers one id) | 0 | 0 | 0 | 0 | 0 | 23 | 0 | 22 | 0 | 0 | 0 |

- **Seven of the eight device mutants are caught by some generic rule;** M4 only by G7 in its declared
  form. M5 is caught by none: it breaks C5 ("a poll reply carries the current state"), which is not in the
  list (proposal below).
- **The client mutants (M6–M8)** break client contracts (C2, C4, C6), and the list has no client rule.
- **Five rules catch no mutant:** G1a, G1b, G2a, G2c and G4. Each holds on every input and is exercised on
  every input, but no fault in the simulator breaks them. G2a catches real changes on the blind slots
  (below).

### The generic set alone on the blind slots (development check, not a measurement)

The acting slots of testbed-04 (4), testbed-05 (12) and testbed-06 (18). "Generic" is G1–G6b with no lift
contract. G7 is shown apart, because in its declared form it is C3.

| Group | Acting slots | Generic (G1–G6b) | Generic + G7 (declared) | The group's own lift contracts | rev3 (C1–C14) |
| --- | --- | --- | --- | --- | --- |
| testbed-04 | 4 | 2 (B01, B06) | 2 | 0 (`lift.v0.yaml`) | 4 |
| testbed-05 | 12 | 10 | 11 (+S07) | 7 (rev2) | 11 |
| testbed-06 | 18 | 9 | 10 (+S03) | 11 (rev3) | 11 |
| **All** | **34** | **21** | **23** | 18 | 26 |

- **What the generic set misses that rev3 catches** (6 slots without G7, 4 with it):
  - C9 (the move timer, a lift constant): testbed-04 B03 and B05, testbed-06 S11 and S23;
  - C3 (the declared transitions): testbed-05 S07, testbed-06 S03. G7's declared form catches both.
- **What it catches that rev3 does not:** testbed-06 S19, by G6b.
- **The lift contracts' own counts** are those of each group's results: 0 of 4, 7 of 12, 11 of 18. The
  rev3 column is a development check for testbed-04 and 05.
- Per slot (the rules violated):
  - testbed-04: B01 and B06 G6, G6b.
  - testbed-05: S02 G2a, G5. S03, S06, S10 and S16 G5. S09 G6, G6b. S11 and S15 G2b, G3. S12 G2a. S13 G3.
    S07 G7 only. S04 none.
  - testbed-06: S01 and S15 G6, G6b. S02 G2a. S09, S14, S16 and S17 G3. S19 G6b. S21 G2b, G6, G6b. S03 G7
    only. S04, S06, S07, S10, S11, S12, S18 and S23 none.

## G7 and G8: what the language can state

- **G7, "transitions seen in normal runs".**
  - The language can state a transition table: `state_machine` with the file's `transitions`. That is C3,
    written here as a stand-in.
  - "Seen in normal runs" needs the table to come from the normal corpus, which takes a miner: read the
    `device.state` events of normal inputs, and keep each `[from, on, to]` seen.
  - **Not built,** as the order says. The judge would not change, but every `on` value seen (including
    `init` and `arrived`) would become a transition, and a transition rare in normal runs would be a false
    positive waiting to happen.
- **G8, "no effect from a reply that arrives after the client gave up".** Not written, for two reasons.
  - **The client has no effect kind.** In both systems, the client only sends, receives and closes
    (`client.handle(DONE|ERROR)` with a `cause`). Its only response to a late reply would be closing again,
    which C2 (`exactly_once`) already forbids.
  - **"Gave up" is a close with `cause: ack_timeout` or `done_timeout`.** A `never_after` cannot condition
    its `after` on a field: the `after` would match every close, including a normal one.
  - **What it would take:** a client effect kind in the protocol (what the robot does on `DONE`), and a
    field condition on `after` patterns. Neither exists. Recommendation: needs something the language and
    these systems lack.

## G6b, and the order "motor stop → state change" (proposal P1)

- **G6b passes everywhere** (above). On the lift it is A1. It catches M10 exactly where G6 does, and on the
  blind slots it adds testbed-06 S19 to G6.
- **P1 covers the gap A1 and C10 leave** (rev4 note): the state change that ends the action before the
  effect that ends it.

### P1 as `only_after` (the first form, failed)

Written for the first review, at `01c43d5`:

```yaml
kind: only_after
per: req_id
event: device.state(UP|DOWN)        # turntable: LEFT|RIGHT|INITIAL
after: device.effect(motor_stop)
```

"The state change that ends the action only after the effect that ends it."
- **It failed:** violated on 1218 of 1218 lift inputs and 1000 of 1000 turntable seeds.
- **Every violation is one line:** the initial state at 0 ms (`state DOWN from=- on=init`, or `INITIAL`).
  It has no request id and no motor stop before it.
- Leaving that line aside, it is violated nowhere: not on the normal corpus, and not for any mutant on
  seeds 0–999.
- **Reported as it failed, not bent to pass.** The outputs are kept as
  `~/rs-control/wp67b-stage3/out/01c43d5/P1-only-after-*`.

### P1 as `never_after` (after the review)

The advisor's suggestion, the operator's order: the same order, stated as its mirror.

```yaml
kind: never_after
per: req_id
event: device.effect(motor_stop)
after: device.state(UP|DOWN)        # turntable: LEFT|RIGHT|INITIAL
```

"No stop of the action's effect after the state change that ends it." The files are
[P1.lift.v0.yaml](generic-contracts/P1.lift.v0.yaml) (sha256 `90d02904…bcf9`) and
[P1.turntable.v0.yaml](generic-contracts/P1.turntable.v0.yaml) (`65a35693…8c52`). The initial state has no
request id, and no motor stop follows it under that key.

**No false positive.** `claim check` with the device's four kinds declared complete:

| Corpus | Verdict | Exercised | Keys tried (conservative measure) | Violations |
| --- | --- | --- | --- | --- |
| lift, 218 real logs | passes | 218 of 218 | 1285 of 1503 | 0 |
| lift, seeds 0–999 | passes | 1000 of 1000 | 5902 of 6902 | 0 |
| lift, both | passes | 1218 of 1218 | 7187 of 8405 | 0 |
| turntable, seeds 0–999 | passes | 1000 of 1000 | 5916 of 6916 | 0 |

- **The measure is wide and says little.** A request is "tried" when the device does anything for it
  after its rest state, and the device always sends `DONE` there. The keys never tried are one per input:
  the initial state's, which has no request id.
- **By the operator's rule, P1 goes to stage 4.**

**Development check** (`~/rs-control/wp67b-stage3/dev_check_p1.py`, output `dev-p1.json`):
- **Mutants M1–M11, seeds 0–999:** P1 is violated on no seed of any mutant. No fault in the simulator
  stops the motor after the rest state.
- **Blind slots** (the 34 acting slots of testbed-04, 05 and 06): violated on none, `ok` on all 34. It adds
  no slot to the generic set or to rev3.
- **Hand-made logs** (seed 0 of the correct lift, written in the device-log format, the first arrival's
  three lines at 4003 ms, `r-0001`, changed by hand; files in `~/rs-control/wp67b-stage3/hand/`):

  | The arrival's lines | P1 | G6 | G6b | rev3 |
  | --- | --- | --- | --- | --- |
  | stop, state, `DONE` (unchanged) | ok | – | – | none |
  | state, stop, `DONE` | violated, `r-0001` at 4003 ms | – | – | none |
  | state, `DONE`, stop | violated, `r-0001` at 4003 ms | violated | – | C10 |
  | stop, `DONE`, state | ok | – | violated | none |
  | `DONE`, stop, state | ok | violated | violated | C10 |
  | state, `DONE`, no stop | ok | violated | – | C9, C10 |

  The second row is the gap: no G rule and no rev3 contract is violated there; P1 is. (The stage 1 device
  model also shows it, as an order difference.)

**What P1 does not say: that a stop comes at all.** A state change with no motor stop for that request
breaks no `never_after` (last row: P1 is `ok`). That is a rule about presence, not order. On the lift C9
(the move timer) holds it, and G6 catches the `DONE` with no stop before it; a
generic rule for it is not in this set.

## Recommendations, rule by rule

| Rule | Recommendation | Why |
| --- | --- | --- |
| G1 | keep | no false positive; it is C1's safety rule. It caught nothing here, and it needs the effect names declared (one contract per name) |
| G2 | keep, as three roles | no false positive; G2b caught M3 and three blind slots, G2a three blind slots |
| G3 | keep | the widest catcher: five mutants and seven blind slots |
| G4 | keep, with a note | no false positive and exercised everywhere, but no fault here broke it; it is the cheapest "nothing from nowhere" rule |
| G5 | keep | M1, M11 and the four testbed-05 slots C14 was drafted from; still untried on a changed build in a blind |
| G6 | keep | M10 and six blind slots |
| G6b | keep, decide with A1 | G6's catches plus S19; the rev4 note's plan is to fold A1 into it, or to put the two in one file |
| G7 | needs something the language lacks (a miner) | its declared form is C3 and caught M4 and two blind slots |
| G8 | needs something the language and the systems lack | a client effect kind and a field condition on `after` |

The operator's decision (top) follows this table for G1–G6b; G7 and G8 do not go on, and P1 goes on after
its `never_after` check.

**Proposals outside the list, kept as a record** (not added, by the operator's decision):
- **A poll reply carries the state at that moment** (C5's form, `consistent`). It is the only rule here
  that catches M5. It needs the poll reply's state field and the state events declared.
- **Client rules:** each command closed exactly once within a time (C2), at most one open (C6), and closed
  only by a reply with its own id (C4). They catch M6–M8 in the lift's contracts.

## Limits of the generic set

What the set going to stage 4 (G1–G6b and P1) does not catch, in these checks:
- **M5** (`STATUS` reports the old state): only the poll-reply rule above catches it, and it is not added.
- **The client mutants M6–M8:** the set has no client rule.
- **M4** (the opposite move taken): only G7's declared form caught it, and G7 does not go on. On the lift
  C3 still does.
- **On the blind slots,** the C9 slots (testbed-04 B03 and B05, testbed-06 S11 and S23) and the C3 slots
  (testbed-05 S07, testbed-06 S03). P1 adds none.
- **A missing motor stop:** P1 states an order, not a presence (above).

The protocol's own contracts are what cover these. The generic set is meant to go beside them, not to
replace them.

## What a system must declare

The rules can be written once if each system names its roles. A proposed form: a `roles` section per
protocol, expanded into contracts of the existing kinds. No new kind, and the judge unchanged.

```yaml
roles:
  requests: [MOVE_UP, MOVE_DOWN]          # turntable: [TURN_LEFT, TURN_RIGHT]
  acknowledgement: ACK
  final_success: DONE
  final_failure: ERROR
  polls: {STATUS: STATUS_REPLY}           # request -> reply
  effects: [motor_start, motor_stop]      # G1: one contract per name
  action: {starts: motor_start, ends: motor_stop}
  rest_states: [UP, DOWN]                 # G6b; turntable: [LEFT, RIGHT, INITIAL]
```

The expansion is mechanical:
- G1 gives one `at_most_once` per effect;
- G2 gives one `count_le` per role;
- G3 gives a `mutually_exclusive` of the two final answers;
- G4 gives an `only_after` with name-less patterns, so it needs no role;
- G5 gives a `never_after`;
- G6 and G6b give an `only_after` each;
- P1 gives a `never_after` (`action.ends` after `rest_states`).

The instances in this note are exactly what such an expansion would produce for the two systems. Stage 4's
test (same first violations as these hand-written files) would hold them to it.

## What the turntable can and cannot show

- **It has the lift's shape with other names:**
  - requests with ids;
  - `ACK`, then one final answer (`DONE` or `ERROR`);
  - polls with `STATUS_REPLY`;
  - one motor effect pair per action;
  - a result table.
- **Passing on both is weak evidence** that a rule is generic. It shows that the rule does not depend on
  the lift's names or its two-state geometry, not that it fits another kind of protocol. The turntable has
  no mutants, so its check is false positives only.
- **A protocol of a different shape would test more.** For example:
  - **no acknowledgement** (the final answer is the only reply): G2a and G5 vanish, and G2b must still hold;
  - **a session** (open, many requests, close): requests keyed by session and id, and replies after close;
  - **a heartbeat** (messages with no request id, sent unasked): G4 as written would fail on every heartbeat.
    The heartbeat must be declared, which tests whether "sends nothing it was not asked for" survives;
  - **several effects per action, or effects that repeat** (a motor that stops and restarts within one
    request): G1 as "one per name" would fail;
  - **a final answer that comes before its effect ends by design** (fire and forget): G6 does not apply.
- This is a proposal only. No new system is written.

## Reproducing the simulator part from the repository alone

At the repository root:

```python
from pathlib import Path
from replayspect.claim import judge_one, sim_input
from replayspect.contract import load_contracts
from replayspect.runner import get_system

for name in ("lift.v0", "turntable.v0"):
    system, cs = get_system(name), load_contracts(Path(f"docs/notes/generic-contracts/{name}.yaml"))
    bad = {c.id: 0 for c in cs.contracts}
    for seed in range(1000):
        inp = sim_input(system, seed)
        for c in cs.contracts:
            bad[c.id] += len(judge_one(c, cs, inp)["violations"])
    print(name, bad)  # expected: every count 0
```

## Stage 4 (after this PR is merged, not done here)

For G1, G2 (three roles), G3, G4, G5, G6, G6b and P1:
- `contracts/generic/`, with the roles bound per system;
- the expansion into existing kinds in the loader;
- the equivalence test against these files on seeds 0–99;
- the slow no-false-positive test on seeds 0–999;
- the word scan extended to `contracts/generic/`;
- the tests the rev4 note asked for A1, for G6 and G6b: the two hand traces that tell G6b (A1) and G6
  (C10) apart, and not judged where the state lines are not declared complete or the key carries a reorder
  mark;
- proposed in its PR: where the roles file lives, and how a session asks for the generic set.

No rev4 file: A1 is folded into G6b.
