# Note: the lift protocol's sentences and the contracts that cover them

Operator note, as of the rev2 contracts (`contracts/lift.v0.rev2.yaml`). It is not given to planners. It
lists every normative sentence of [docs/protocol-lift.md](../protocol-lift.md), the contract that covers
it, and whether the contract language can state it. It also records how each rev2 contract was found.
The contract file itself names no defect or experiment slot: it is shown to planners.

- **Contracts:**
  - C1–C8 are `contracts/lift.v0.yaml`, the default file and the reference of past experiments.
  - C9–C13 are new in `contracts/lift.v0.rev2.yaml`, which also holds C1–C8 unchanged. It is used by
    giving its path.
- **"The contract language can state it"** means with the nine contract kinds (eight, plus
  `only_after`) and a condition of one comparison ([design-v0.md](../design-v0.md), "계약 DSL").
- **Line numbers** are those of `docs/protocol-lift.md` when this note was written.

## Device

| Lines | Sentence | Contract | The language can state it |
| --- | --- | --- | --- |
| 28, 49 | `STATUS_REPLY` carries the state when it is sent | C5 | yes |
| 35 | four states, starting in `DOWN` | C3 | yes |
| 37–39 | a known id is answered with its stored result again (`ACK` while in progress) | none | no: nothing ties a repeated receive to its reply |
| 38–39 | a finished id's result does not change (`DONE` or `ERROR`) | C8 | yes |
| 39–40 | nothing else happens for a known id | C1 (no second motor start), C9 (no second stop), in part | in part |
| 40 | a new id is answered with `ACK` | none | no: a repeat in progress is answered `ACK` too, which breaks `exactly_once` |
| 40–41 | it is executed after its `ACK` | none | yes, with `only_after` (`motor_start` after `ACK`); not added |
| 41 | it is executed 50 ms later | none | no: the execution is a motor start or an `ERROR`, two kinds one pattern cannot hold |
| 42–44 | `MOVE_UP` only in `DOWN`, `MOVE_DOWN` only in `UP` | C3 (no undeclared transition) | yes |
| 43–44 | an illegal command is answered with `ERROR`, not `DONE` | **C10** | yes, with `only_after` |
| 44 | the `ERROR` reason is `illegal` | **C11** | yes |
| 44–45 | a legal command starts the motor and the state becomes `MOVING_*` | C3 (the state) | the state yes; tying the motor start to it, no |
| 45 | 3 s later the motor stops | **C9** | yes (an upper bound; a stop that comes early is not seen) |
| 45–46 | on arrival the state becomes `UP` or `DOWN` | C3 | yes |
| 46 | on arrival `DONE` is sent | **C10** (no `DONE` without a stop) | that a `DONE` comes at all, no: the `DONE` repeated for a copy breaks `exactly_once` |
| 47 | the result table survives disconnects | C1, C8, indirectly | no: the device has no reconnect event |
| 47–48 | after a reconnect the device sends nothing on its own | C7 (`DONE`/`ERROR`), **C12** (`ACK`), **C13** (`STATUS_REPLY`) | yes |
| 49 | `STATUS` is answered immediately | none | no: a copy of a poll is answered too, which breaks `exactly_once` |

## Client

| Lines | Sentence | Contract | The language can state it |
| --- | --- | --- | --- |
| 30–31 | ids `r-0001`… in order, polls `s-0001`… | none | no |
| 53 | at most one move command open | C6 | yes |
| 53–54 | `MOVE_UP` and `MOVE_DOWN` in turn, starting with `MOVE_UP` | none | the first command only; not added |
| 54 | 6 commands in all | none | no |
| 54–55 | a think time of 1–3 s after a close | none | no: a time between two keys |
| 56–57 | no `ACK` within 2 s: resend with the same id, at most twice | none | no: no "at most N" |
| 57–58 | still no `ACK`: closed as failed (`ack_timeout`) | C2, in part | in part |
| 59–60 | no `DONE` or `ERROR` within 15 s of the first send: closed as failed | C2 | yes |
| 61–62 | only a `DONE`/`ERROR` with the open command's id closes it | C4 (`DONE` only) | `ERROR` no: a timeout's `msg_req_id` is null, so it takes two conditions |
| 63–64 | after a reconnect the open command is resent with the same id | none | no |
| 65 | `STATUS` every second; the replies are not acted on | none | no |

Lines 69–75 (link and timing) describe the environment, not behaviour, and are left out.

## What no contract covers

- **Device sentences:** model conformance covers the device sentences no contract states. `replayspect
  device` feeds the device model what the device received and compares its sends, state changes and
  effects with the device log ([device-log.md](../device-log.md)). A wrong reply, a missing `ACK`, a
  wrong delay or an immediate-answer failure is a first mismatch there. This needs the device's
  receives in the log.
- **Client sentences:** these are encoded in the simulator's client model. No tool yet checks a real
  client log against a client model: `drive` replays the client log as a script, and its fit explains the
  log through the link.

## What the contract language cannot say

Four gaps come back in the tables above. They are recorded, not planned:
1. **Two conditions at once** (and). Example: a `DONE` or `ERROR` with another command's id, but not a
   timeout.
2. **At most N times.** Example: a command resent at most twice.
3. **A time between two different keys.** Example: the think time between one command's close and the
   next one's send.
4. **One pattern over two event kinds.** Example: the execution, which is a motor start or an `ERROR`.

## How the rev2 contracts were found

| Contract | Found by | Evidence |
| --- | --- | --- |
| C9 | testbed-04 blind change A: a repeat of the request being executed, arriving during its move, starts the move timer again | Slots B03 (`ACK` lost, retry during the move) and B05 (a copy during the move). The lift contracts caught neither, and the device model's first mismatch did ([testbed-04](../experiments/testbed-04.md)). |
| C10 | testbed-04 blind change B: at rest, a command to move where the lift already is answered `DONE`, not `ERROR`, with no motor | Slots B01 and B06. No contract tied `DONE` to a move, and stating it needed a new kind (`only_after`). |
| C11, C12, C13 | Document check: going through this table, sentences the eight kinds could already state and no contract did | None from an experiment. |

The rev2 contracts are checked here only on development data. They will be measured with a new blind
change.

**Development check** (no measurement):

| | C9 | C10 | C11 | C12 | C13 |
| --- | --- | --- | --- | --- | --- |
| Real device logs, no defect (211: testbed-01 39, 02 48, 03 68, 04 56) | 0 violations | 0 | 0 (exercised in 12) | 0 | 0 |
| Real device logs, M2 (22), M4 (16), M10 (16) | M4: the 11 runs where it fired | M10: the 11 runs where it fired | 0 | 0 | 0 |
| testbed-04 blind slots (8) | B03, B05 | B01, B06 | 0 | 0 | 0 |
| Simulator, seeds 0–999, correct lift | 0 | 0 | 0 | 0 | 0 |
| Simulator, seeds 0–999, the 11 mutants | M4: 19 (as C3) | M10: 24 (as C8) | 0 | 0 | 0 |

- **C9 on real logs.** Every completed move took exactly 3,000 ms (1,528 moves). The firmware logs a
  timer event at its scheduled time, so C9 checks the schedule, not the physical travel
  ([device-log.md](../device-log.md), "Limits").
- **C9 and M4.** C9 reports M4 at the end of the run, on the request of the interrupted move, not on the
  opposite command.
- **C10 and M10.** On M10 logs, C10 and C8 point at the same `DONE` in all 11 runs.
- **The blind slots.** In the four slots where a change acted, C9 and C10 point at the request and time
  of the model's first mismatch:
  - B01 and B06 at the same event;
  - B03 and B05 at the late stop, after the first mismatch's time.
