# Device logs: stage 1 of two sources

`replayspect device` reads a device's own log and checks it against the device model. It uses no
link model and no fit. With the client's log as well, it counts the messages lost on the link and the
extra copies. Code: `src/replayspect/devicelog.py`.

The client-side fit (`drive --fit`, [driven-replay.md](driven-replay.md)) has to guess what the device
received and when. A device log records it. Stage 1 uses that record directly. Stage 2 will merge
the two logs: aligning the clocks, and fixing request arrivals and device sends as observations. It
is not part of this change.

## The device log

Each line holds the receiving host's time, `#`, the device clock in milliseconds (`millis()`), then
an event. This is what the testbed Uno firmware writes (`examples/testbed-uno`):

```
2026-11-13T22:43:05.121410+09:00 # 4 recv MOVE_UP r-0001
2026-11-13T22:43:05.124106+09:00 # 4 send ACK r-0001
2026-11-13T22:43:05.171436+09:00 # 54 effect motor_start r-0001 dir=up
2026-11-13T22:43:05.175833+09:00 # 54 state MOVING_UP r-0001 from=DOWN on=MOVE_UP
```

- **The allow list.** Only `recv`, `send`, `state` and `effect` lines become events. Each event is
  exact, from source `adapter:device-log`, and timed by the device clock.
- **Error lines.** An `error` line marks the log invalid.
- **Every other line is skipped unseen.** It is not counted, named or numbered. So the lines that
  carry the experiment's answer (`build defect=`, `defect fired`) cannot reach a result, and neither
  can a line added later. Tests run the report with and without those lines and require byte-equal
  output, on the native firmware's own logs as well.
- **The host time in front is not read.** It is for stage 2.

## Conformance

The device model runs alone, fed what the device received at the device's times. The correct model
runs, and each defect model given with `--models`. The model's sends, state changes and effects are
then compared with the log.

- **When events match:** a model event matches a logged one with the same kind, name, request id and
  fields that is logged no earlier than the model's time and at most `--late` after it (default
  2 ms).
  - The firmware's timers run on `millis()` and can end late.
  - On the 182 real logs, every match fell in the same millisecond.
- **The order of one request's outputs:** for one request id, the logged events that matched model
  events must keep the model's order. Order is compared only among events with the same request id,
  never across ids: two inputs in one millisecond may be taken in either order. Events with no request
  id are not compared for order.
  - An order difference is a mismatch at the time of the first logged line out of place, on that
    request. The report shows both orders, from the first position that differs to the last.
  - Only matched events are compared, so nothing new is inferred from absence under a partial
    declaration.
  - The order is a switch (`order="ignore"` in `conform`; the tool compares order), so an analysis can
    show what the rule changes. Defect models use the same rule.
  - Before this rule, the comparison matched by time alone and never compared order. testbed-06 S15
    and S19 reorder one request's arrival lines inside one millisecond, and both conformed
    ([testbed-06](experiments/testbed-06.md)).
- **Same-millisecond order:** when an input and a timer fall in the same millisecond, the timer runs
  first, as in the firmware (testbed-uno README, difference 3). Without this rule, 6 of the 155
  no-defect logs gave a false mismatch: a poll answered in the millisecond the move ended.
  - The order is a switch (`same_ms="input-first"` in `conform`; the tool keeps timers-first), so an
    analysis can show what the rule changes.
  - On the 182 real logs it changes the correct model's result only in those 6 logs, and no defect
    run's verdict or first mismatch.
- **The declaration decides what absence means** (`--complete device:...`, default partial):
  - The model is fed only when the device's receives are declared complete. Otherwise every model is
    "not checked".
  - A model event missing from the log is a mismatch only for an output kind (`send`, `state`,
    `effect`) declared complete.
  - A logged event the model does not make is always a mismatch. A device that starts a motor the
    model would not start is caught even with only the receives declared.
  - With nothing that can count (no output line, none declared), the result is "not checked", never
    "conforms".
- **The end of the log:** what the model does after the log ends, minus `--late`, is not compared.
- **The result** for each model is "conforms", "not checked" (with the reason), or the first
  mismatch, the earlier of an unmatched event and an order difference. The JSON's `kind` says which
  (`event` or `order`):
  - the time and the request;
  - what the model does there and what the device did (either may be nothing);
  - the model's state just before;
  - the last input the device received: the last `recv` line before the first mismatch's place in
    the log. The place is the one the tie rule below uses: a logged event's own line, an order
    difference's line, or where a model event stands. A `recv` later in the same millisecond is not the
    last input. Before WP6/7d stage 0a it was the last `recv` up to the first mismatch's time.

  With the correct model, this says where the device first left the model. No defect model is
  needed.
- **Candidates at exactly the same time** (WP6/7d stage 0a):
  - **On different requests, the order of the log's lines decides,** not which side an event is on.
    The first mismatch is on the request the log shows first.
  - **A model event has no line.** It stands right after the last line, in that millisecond, of a
    receive fed to the model or a matched output that came before it in the model's run: where the
    device would have written it. With none before it, it stands at the start of the millisecond: a timer
    runs before the inputs of its millisecond, as in the firmware. A missing poll reply, for example,
    stands right after the poll's `recv` line.
  - **On the same request,** a model event and a logged one are shown together, and an unmatched event is
    reported before an order difference, as before.
  - **Only an exact tie** is decided this way. Candidates at different times, even inside the `--late`
    window, are decided by time: the earlier one is reported.
  - Before this rule, an exact tie on different requests went to the model's event.
    testbed-07 S17 ends a turn early, and in that millisecond answers a poll of another request with the
    new state. The device's `motor_stop r-0001` is first in the log, but the model's `STATUS_REPLY s-0003`
    was reported ([testbed-07](experiments/testbed-07.md)).
- **When the first mismatch comes after the defect's branch:** the first mismatch is the first place
  the outputs differ. A repeated request that a defect takes as new is answered `ACK` either way, so
  the difference shows when the request executes, 50 ms later.
- **Poll replies are compared,** so a defect seen only there (M5) is visible here. In the client-side
  fit it is not.

## The count check

With `--client` (the client's trace from `ingest`), messages are counted per message and request
id:
- the client's sends against the device's receives;
- the device's sends against the client's receives.

A difference is a message lost on the link, or an extra copy. No clock is needed.

- **Completeness:** each source declares which kinds it logs completely with `--complete`, for
  example `device:recv,send,state,effect` and `client:send,recv`. The default is partial, and
  nothing is inferred from absence.
  - A loss needs the receiving side complete.
  - An extra copy needs the sending side complete.
  - A count is a lower bound ("at least") unless the other side is complete too.
- **Polls** are counted like any message.
- **Losses in a logged disconnect** count as losses. The count does not tell them apart from drops.

## Contracts alone

With `--contracts contracts/lift.v0.yaml`, the system's contracts are judged on the device log's
events, with no model at all. Each contract is:
- **violated**, with the request and the time;
- **ok**;
- **not exercised:** none of its trigger events occurred, so it could not fail;
- **not judged:** it refers to a device kind not declared complete. A contract that counts or
  compares would read an unlogged kind as absent: C7, "no more `DONE`/`ERROR` than requests
  received", would fail on a log without receives. An `only_after` or `never_after` contract
  needs both of its kinds: "`DONE` only after the motor stopped" is judged only with sends and
  effects declared.

Contracts about client events (lift C2, C4, C6) are not exercised, because no client event is given.

**Development check** (the 182 real logs; the contracts as written before any real log, not
changed):

| Condition | No-defect builds (155) | M4 fired (5) | M2 fired (7) | M10 fired (6) | Defect builds, not fired (9) |
| --- | --- | --- | --- | --- | --- |
| state and effect lines (`device:state,effect`) | no violation | C3 in 5 (`MOVING_UP --MOVE_DOWN--> MOVING_DOWN is not declared`) | none | none | none |
| whole device log (all four kinds) | no violation | C3 in 5 | C8 in 7 (`DONE` and `ERROR` for one id) | C8 in 6 | none |

- **With state and effect lines only,** C5, C7 and C8 are not judged.
- **What this says about logging:** a defect that changes the device's state shows in its state
  lines. A defect that changes only its replies needs its send lines.

## Fidelity

Every item in the report says how it is known:

| Label | Meaning |
| --- | --- |
| `observed: device` | read from the device log |
| `observed: client` | read from the client log |
| `inferred: count` | the count check |
| `reconstructed` | what the model does |

Without a device log, nothing changes. `drive` and `drive --fit` are untouched.

## Development check (the real logs, development data)

| Check | Result |
| --- | --- |
| Correct model on the no-defect logs (testbed-01 39, testbed-02 48, testbed-03 off build 68) | conforms in 155 of 155 |
| Defect builds where the defect fired (testbed-03: M2 7, M4 5, M10 6) | the correct model never conforms; the build's own model always conforms |
| Defect builds where the defect did not fire (9) | the correct model conforms in 9 of 9 |
| The correct model's first mismatch against the `defect fired` line, read by the check script, not the tool | same request in 18 of 18; same time in 11 of 18 (M4 and M10); 50 ms later in the 7 M2 runs (a repeat answered `ACK` either way, refused when it executes) |
| The three runs the client log could not show (R074, R076, R087) | the correct model does not conform in 3 of 3 |
| M1 against M2 | not separated: both conform in all 7 M2 runs (no repeat after `DONE` happened). M9 conforms too in 2 |
| Count check against the truth files (losses, losses in disconnects, extra copies) | 95 of 95 (testbed-03), 39 of 39 (testbed-01), 47 of 48 (testbed-02; R03 below) |
| Per-request order (WP6/7b stage 1), every model on every log, against `order="ignore"` | no mismatch on the 218 no-defect logs (the 213 of the rev3 note and testbed-06's five unchanged slots); S15 and S19 now differ, on r-0001 at 3054 and 3055 ms, the first line out of place being `DONE`; no other verdict or first mismatch changed (testbed-03 and 04 defect runs, 27 each; the blind slots of testbed-04, 05 and 06) |
| Same-time candidates by line order (WP6/7d stage 0a), the correct model, against the rule before it | run on testbed-07's 24 blind slots, WP6/7c stage 1's 24 turntable sessions and its lift session, testbed-07's 3 dry-run logs, and testbed-06's 24 blind slots (list sha256 `756a1c2d…`, as recorded) and 8 dry-run logs: S17's first mismatch is now `motor_stop r-0001` at 3000 ms (was `STATUS_REPLY s-0003`); no other first mismatch, verdict or count changed. **Run afterwards** (2026-11-25, on the machine that holds the lift's logs; `61257aa`, the commit before the rule, against `388554d`): the lift's 218 no-defect logs (list sha256 `2e155b05…2d38`, as recorded), testbed-03 and 04 defect runs (27 each; testbed-03's split by the device log's build line, testbed-04's by its truth files, the same 27 as `docs/experiments/testbed-04.md`), and the blind slots of testbed-04 (8) and 05 (16): 296 logs, no first mismatch, last input, verdict or count changed (218 conform; defect runs 18 and 21 differ; blind slots 4 and 12 differ) |
| The last input at the first mismatch's place in the log (WP6/7d stage 0a), the correct model, against the last `recv` up to its time | on the same 84 logs: only testbed-07 S17 changes, its last input now `recv STATUS s-0002` at 2002 ms (was `recv STATUS s-0003` at 3000 ms, after the device's `motor_stop r-0001` in the log); no verdict, count, or first mismatch's request or event changed. On the 296 logs run afterwards (row above): no last input changed |
| Native firmware (`tests/test_testbed_conformance.py`) | every script conforms with no defect; with each defect switch, the correct model's first mismatch is on the request where the defect fired, at the same time or 50 ms later (M1, M2 and M9 on a repeat while queued), and the defect's own model conforms |

## Limits

- **The device log is the suspect's own statement.** The firmware that may be defective writes it.
  This method cannot see a defect in the logging itself, or a defect where what the device does and
  what it logs differ. In these experiments the defects logged their transitions as they happened.
- **A loss and an extra copy of the same message cancel out in the count.** testbed-02 R03 is an
  example: `MOVE_DOWN r-0004` was lost once and copied once, so the count check saw nothing. The
  match with the truth files means no such pair occurred in those plans. It does not mean the count
  check always sees every fault.
- **The count check says nothing about delays.** Telling which way a message was delayed, and by how
  much, needs the clocks aligned (stage 2).
- **A partial device log:**
  - Without receives, the model cannot be fed, so the result is "not checked".
  - With receives but without sends, the model's sends cannot be checked here. Comparing them with
    the client's receives would go through the link (stage 2).
  - With state and effect lines alone, nothing is checked. An impossible transition (such as M4's
    reversal) could be seen from them only with the inputs, or with a transition table the device
    model does not publish.
  - Without a declared complete side, nothing is inferred from absence.
- **The comparison window allows only the firmware's documented timing differences.** A defect whose
  only effect is a delay of a millisecond or two would pass.
- **Order is compared within one request only.** A defect that changes the order of two requests'
  outputs inside one millisecond, and nothing else, passes: the rule cannot tell it from two inputs
  taken in either order. The order rule was set after testbed-06's S15 and S19 were known; that it
  sees them is a development check.
- **Timer events carry their scheduled time, not the time they happened.** The testbed firmware logs a
  move's arrival at the time it was due (`arrive(travel_due_)`), and an execution at its due time
  (`execute(..., p.due)`). That is why every completed move on the real logs took exactly 3,000 ms.
  So what C9 (`contracts/lift.v0.rev2.yaml`, "the motor stops within 3 s of its start") checks on these
  logs is the firmware's schedule, not the physical travel time. A fault where the schedule is right but
  the motor really stops late is not seen.
- **Logging costs time on the device:** each line takes serial time. A run with the device log on is
  not the same run as one with it off.
