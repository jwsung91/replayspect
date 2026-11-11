# Testbed experiment 01: fitting real-hardware client logs with known injected faults

Operator document. Do not give it to a planner.

The lift device ran on an Arduino Uno with no defect. A Jetson Orin ran the client and a fault link
between them. The link applied a known fault plan and wrote down what it actually did (the truth
file). Given only the client's log, the fit (`drive --fit`, [driven-replay.md](../driven-replay.md))
had to reproduce the log, and its plan was compared with the truth file. This experiment asks two
questions:

- How many real logs does the fit reproduce?
- How much of the injected plan does its explanation recover?

No model is involved and nothing was spent. The registration, client logs, device logs and truth
files are outside the repository. The plans are listed here.

## Setup

- **Harness:** `efd9535` (main after PR #24). Firmware and host code are in
  [`examples/testbed-uno`](../../examples/testbed-uno/README.md). The Uno kept the stage-1 build with
  the device log on (`READY log=1 defect=none`).
- **Sessions:** 6 move commands each, 90 s, at 115200 baud over USB serial.
- **Logs:** the client log has µs timestamps. Each log was analyzed as written and as a copy cut
  to ms.
- **Fit:** used as-is, with no new moves.
  - Public link ranges: c2s and s2c delay 0–5 s, duplicate extra delay 0–5 s. These were set
    without looking at the plans.
  - Tolerance: 25 ms is the main setting; 10 ms and 250 ms ran beside it.
  - Caps: 120 fit runs, 120 branch runs.
  - Window fits used the registered window rule (see [driven-replay.md](../driven-replay.md)),
    which includes late `DONE`.
- **Reference columns:** as in driven-01, the reader unchanged and the reader with a round-trip
  start (µs, 25 ms, 120 runs).

**Comparison with the truth file.** A restored fault is one of three things: a drop, a duplicate,
or a delay above the physical range plus the tolerance (10 ms + 25 ms). Stage 1 measured at most
10 ms of physical delay.

- An injected fault is found when the restored plan has the same kind on the same
  `(dir, msg, req_id, k)`.
  - A duplicate must also match the extra delay within the tolerance.
  - A delay must fall within [injected − tol, injected + 10 ms + tol].
- A message that a logged disconnect explains is not a fault, on either side. This rule was set
  before the runs.

## Plans and runs

39 runs:

- 3 controls with no plan.
- 12 single-fault plans, each run with two think-time seeds (24 runs, suffixes a and b).
- 8 runs with two faults.
- 4 hard runs.

| Plan | Faults |
| --- | --- |
| T01 | c2s MOVE_UP r-0001 k0 delay 2500 ms |
| T02 | s2c ACK r-0003 k0 delay 2500 ms |
| T03 | s2c DONE r-0002 k0 delay 1000 ms |
| T04 | c2s MOVE_UP r-0003 k0 drop |
| T05 | s2c ACK r-0002 k0 drop |
| T06 | s2c DONE r-0004 k0 drop |
| T07 | c2s MOVE_DOWN r-0002 k0 dup +300 ms |
| T08 | s2c ACK r-0005 k0 dup +200 ms |
| T09 | s2c DONE r-0003 k0 dup +500 ms |
| T10 | disconnect 1500 ms, 800 ms after c2s MOVE_UP r-0003 k0 (while moving) |
| T11 | disconnect 1500 ms, 300 ms after s2c DONE r-0004 k0 (idle) |
| T12 | disconnect 1500 ms, 0 ms after c2s MOVE_UP r-0005 k0 (overlaps a send) |
| T13 | s2c ACK r-0002 k0 drop; s2c DONE r-0002 k0 delay 1000 ms |
| T14 | c2s MOVE_UP r-0003 k0 dup +300 ms; s2c ACK r-0003 k0 drop |
| T15 | s2c DONE r-0004 k0 dup +500 ms; disconnect 1500 ms, 800 ms after c2s MOVE_DOWN r-0004 k0 |
| T16 | c2s MOVE_DOWN r-0002 k0 delay 2500 ms; s2c DONE r-0002 k0 drop |
| T17 | c2s MOVE_UP r-0001 k0 drop; s2c ACK r-0001 k0 dup +200 ms |
| T18 | s2c ACK r-0005 k0 delay 2500 ms; disconnect 1500 ms, 800 ms after c2s MOVE_UP r-0003 k0 |
| T19 | s2c DONE r-0003 k0 drop; c2s MOVE_DOWN r-0004 k0 dup +300 ms |
| T20 | s2c ACK r-0002 k0 delay 2500 ms; c2s MOVE_DOWN r-0002 k1 drop |
| T21 (hard) | s2c ACK r-0002 k0 drop; s2c DONE r-0005 k0 dup +400 ms; disconnect 1500 ms, 500 ms after c2s MOVE_UP r-0001 k0; disconnect 1200 ms, 900 ms after c2s MOVE_DOWN r-0004 k0 |
| T22 (hard) | c2s MOVE_UP r-0003 k0, k1, k2 drop (every attempt of one command) |
| T23 (hard) | c2s MOVE_UP r-0001 k0 drop; s2c DONE r-0002 k0 drop; s2c ACK r-0004 k0 drop; c2s MOVE_UP r-0005 k0 drop |
| T24 (hard) | c2s MOVE_DOWN r-0002 k0 dup +300 ms; s2c ACK r-0003 k0 dup +200 ms; s2c DONE r-0004 k0 dup +600 ms; s2c ACK r-0005 k0 delay 2500 ms; c2s MOVE_DOWN r-0006 k0 delay 1200 ms |

All 39 runs were valid. No device error line appeared and the board did not reset. Every fault
in the plans was applied (truth file: 46). Disconnects are in the log and are not counted as
injected faults, so T15 and T18 show one injected fault each.

## Results

Each fit cell gives the status and, in brackets, the number of runs (120 is the cap).

- **Found / injected:** injected faults the restored plan matches.
- **Correct / restored:** restored faults that are injected ones.
- **Exact:** both counts are complete.
- **Loss read as delay:** injected drops the plan restored as a delay on the same message.

Every column is at 25 ms.

| Run | Group | Plan | Fit µs | Found / injected | Correct / restored | Exact | Loss read as delay | Fit ms | Windows µs | Reader / round-trip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T00a | control | - | yes (4) | 0/0 | 0/0 | yes | 0 | yes (4) | - | yes / yes |
| T00b | control | - | yes (4) | 0/0 | 0/0 | yes | 0 | yes (4) | - | yes / yes |
| T00c | control | - | yes (4) | 0/0 | 0/0 | yes | 0 | yes (4) | - | yes / yes |
| T01a | single | T01 | yes (4) | 0/1 | 0/5 | no | 0 | yes (4) | yes (4) | yes / yes |
| T01b | single | T01 | yes (4) | 0/1 | 0/5 | no | 0 | yes (4) | yes (4) | yes / yes |
| T02a | single | T02 | yes (4) | 0/1 | 0/3 | no | 0 | yes (4) | yes (4) | yes / yes |
| T02b | single | T02 | yes (4) | 0/1 | 0/3 | no | 0 | yes (4) | yes (4) | yes / yes |
| T03a | single | T03 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T03b | single | T03 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T04a | single | T04 | yes (4) | 0/1 | 0/5 | no | 1 | yes (4) | yes (4) | yes / yes |
| T04b | single | T04 | yes (4) | 0/1 | 0/5 | no | 1 | yes (4) | yes (4) | yes / yes |
| T05a | single | T05 | yes (4) | 0/1 | 0/3 | no | 1 | yes (4) | yes (4) | budget / yes |
| T05b | single | T05 | yes (4) | 0/1 | 0/3 | no | 1 | yes (4) | yes (4) | budget / yes |
| T06a | single | T06 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T06b | single | T06 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T07a | single | T07 | yes (4) | 0/1 | 0/1 | no | 0 | yes (4) | yes (4) | yes / yes |
| T07b | single | T07 | yes (4) | 0/1 | 0/1 | no | 0 | yes (4) | yes (4) | yes / yes |
| T08a | single | T08 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T08b | single | T08 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T09a | single | T09 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T09b | single | T09 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T10a | single | T10 | yes (4) | 0/0 | 0/0 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T10b | single | T10 | yes (4) | 0/0 | 0/0 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T11a | single | T11 | yes (4) | 0/0 | 0/0 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T11b | single | T11 | yes (4) | 0/0 | 0/0 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T12a | single | T12 | incomplete (cap) (120) | 0/0 | 0/4 | no | 0 | incomplete (cap) (120) | inc. (29) | yes / yes |
| T12b | single | T12 | incomplete (cap) (120) | 0/0 | 0/4 | no | 0 | yes (4) | inc. (24) | yes / yes |
| T13 | double | T13 | yes (4) | 0/2 | 0/5 | no | 1 | yes (4) | yes (4) | yes / yes |
| T14 | double | T14 | yes (4) | 0/2 | 0/1 | no | 1 | yes (4) | yes (4) | yes / yes |
| T15 | double | T15 | yes (4) | 1/1 | 1/1 | yes | 0 | yes (4) | yes (4) | yes / yes |
| T16 | double | T16 | yes (4) | 1/2 | 1/5 | no | 0 | yes (4) | yes (4) | yes / yes |
| T17 | double | T17 | yes (4) | 0/2 | 0/5 | no | 1 | yes (4) | yes (4) | yes / yes |
| T18 | double | T18 | yes (4) | 0/1 | 0/3 | no | 0 | yes (4) | yes (4), yes (4) | budget / yes |
| T19 | double | T19 | yes (4) | 1/2 | 1/2 | no | 0 | yes (4) | yes (4) | yes / yes |
| T20 | double | T20 | yes (4) | 1/2 | 1/3 | no | 1 | yes (4) | yes (4) | budget / yes |
| T21 | hard | T21 | yes (4) | 1/2 | 1/4 | no | 1 | yes (4) | yes (4), yes (4), yes (4), yes (4) | budget / yes |
| T22 | hard | T22 | yes (27) | 3/3 | 3/3 | yes | 0 | yes (27) | yes (36) | stuck / stuck |
| T23 | hard | T23 | yes (4) | 1/4 | 1/14 | no | 3 | yes (4) | yes (4), yes (4) | budget / yes |
| T24 | hard | T24 | yes (4) | 2/5 | 2/9 | no | 0 | yes (4) | yes (4), yes (4), yes (4) | budget / yes |

**Columns that are the same in every run:**
- The 10 ms and 250 ms fits have the same status as the 25 ms fit in every run, µs and ms.
- No run had more than one fitting outcome. 34 runs fit with no violation and 5 with C2: T06a/b,
  T16, T19 and T23, the runs where a `DONE` was lost.
- Branch points (`--branches`, µs): 0 in every run. 5 to 9 attempts were checked per run, and two
  runs hit the 120-run cap. T12 has no branch count because its fit did not reproduce.
- The other reference result: delay read as loss and request loss read as reply loss are both 0 in
  every run.

Totals (µs, 25 ms):

| Group | Runs | Reproduced µs / ms | Exact | Found / injected | Correct / restored | Loss read as delay | Delay read as loss | Request ↔ reply loss |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | 3 | 3 / 3 | 3 | 0/0 | 0/0 | 0 | 0 | 0 |
| single | 24 | 22 / 23 | 12 | 8/18 | 8/50 | 4 | 0 | 0 |
| two faults | 8 | 8 / 8 | 1 | 4/14 | 4/25 | 4 | 0 | 0 |
| hard | 4 | 4 / 4 | 1 | 7/14 | 7/30 | 4 | 0 | 0 |
| all | 39 | 37 / 38 | 17 | 19/46 | 19/105 | 12 | 0 | 0 |

By kind (µs, 25 ms; counted after the runs, see Departures):

| Injected kind | Injected | Found |
| --- | --- | --- |
| drop | 20 | 8 |
| delay | 12 | 3 |
| duplicate | 14 | 8 |

Other totals:

- **Window fits:** 43 windows at µs: 41 reproduced and 2 incomplete (`space`, both T12). 43 at ms:
  42 reproduced and 1 incomplete. None was unexplained.
- **Reference columns:** the reader unchanged reproduced 31 runs (budget 7, stuck 1). With a
  round-trip start it reproduced 38 (stuck 1, T22).

## What the results show

- **The fit reproduces almost every real log, but what it reproduces with is mostly not what
  happened.**
  - 37 of 39 logs reproduce (38 at ms). 36 of them reproduce at the fit's first choice (4 runs).
  - Only 19 of the 46 injected faults are found, and 19 of the 105 restored faults are right.
  - The plan is exact in 17 runs. 7 of those had nothing to find: the 3 controls and the 4
    disconnect-only runs T10 and T11.
  - The fit stops at the first plan that reproduces the log, and the client log allows many. The
    found count measures that first plan.
- **Every missed loss was read as a long delay (12 of 12).**
  - With a 0–5 s range, a lost request or reply can always be replaced by one that arrives late.
  - A lost `ACK` became an `ACK` 1.5–2 s late (T05, T13, T21, T23).
  - A lost request became a late request. In T04, T17 and T23 the request and its `ACK` were each
    about 1 s late. In T20 the lost retry became 2.5 s late.
  - The cost goes further. When a retry's arrival is not bounded by the log, the fit puts it at
    the middle of the range (2.5 s; 12 restored delays have that value). The retry then reaches
    the device after the move ended, and the device answers it with `DONE`. That `DONE` is not in
    the log, so the plan adds a drop.
  - 10 of the 22 restored drops are such inventions. In T04, T05, T13, T20, T21 and T23 there is a
    lost `DONE` of attempt k1.
  - This is the price of the wide range that the registration asked to measure.
- **A delay is found only where the log fixes where it goes.**
  - A `DONE` delay (T03a/b) was found exactly. The device's 3 s travel after the `ACK` leaves one
    place to put it. The `ACK` delay in T20 was found too.
  - A 2.5 s request delay (T01, T16) was read as about 1.0 s on the request and 1.0 s on its
    `ACK`, plus 0.25 s each way for the retry.
  - A 2.5 s `ACK` delay (T02, T18, T24) was read as a 2.0 s `ACK` plus 0.25 s each way for the
    retry.
  - T24's 1.2 s request delay was read as 0.6 s on the request and 0.6 s on its `ACK`.
  - In T13 the `ACK` was lost as well, and the 1.0 s `DONE` delay was split: 0.5 s on the request
    and 0.5 s on the `DONE`.
  - The client log gives the round trip, not how it splits.
- **A duplicated request reads as a duplicated `ACK`.** This was not a registered column.
  - 4 of 5 duplicated requests (T07a/b, T19, T24) were restored as a duplicate `ACK` with the same
    extra delay.
  - In T14 the duplicate request's `ACK` stood in for the lost `ACK`, and the plan has one 300 ms
    `ACK` delay instead.
  - From the client side the two are the same: the client receives a second `ACK` either way. Only
    the device log tells them apart.
- **T12 found a gap in the fit: a request in flight when a logged disconnect starts.**
  - The link applies the plan inside the send. The client stamps the `TX` line with the time its
    loop step began, and the `link down` line when it is told. So the request is stamped 25–47 µs
    before the disconnect.
  - On the wire the request was in flight at the start and was lost with the disconnect (the
    truth file says `lost_in_disconnect`).
  - The fit counts only sends made during a disconnect as lost to it. It treats this one as a live
    attempt, so it pairs the reconnect resend's `ACK` and `DONE` wrongly and cannot explain them in
    120 runs.
  - The ms copy of T12b reproduces because both lines fall in the same millisecond.
  - The fake-board check before registration did not show this. The fake link has no physical
    delay, so the two stamps were equal there.
  - The fit was used as-is, so this is reported and not fixed.
- **No window was unexplained, and the window rule found every faulted command.**
  - Each run with a fault had at least one window. The controls had none.
  - The window fits mostly took the same 4 runs as the whole-log fit, because the first choice
    already reproduces.
  - The firmware has no defect, so "unexplained" was not expected. Its absence says the fit does
    not invent defects on these logs; it does not test whether the fit finds real ones.
- **Tolerance and timestamp precision changed nothing here.** The real link's delays are a few ms
  and the injected faults are hundreds of ms, so 10, 25 and 250 ms give the same statuses. The ms
  copy differs only in T12b.

## Predictions

Registered before the runs (the agent's predictions):

| Prediction | Result |
| --- | --- |
| (a) Of the 32 single- and two-fault runs, the whole-log fit (µs, 25 ms) reproduces 26 or more. | **Right:** 30/32. |
| (b) Of the 24 single-fault runs, the restored plan matches the truth exactly in 20 or more. | **Wrong:** 12/24. Four of the 12 had nothing to find. |
| (c) Request-loss / reply-loss confusions: 0–1. | **Right:** 0. |
| (d) The ms copy gives the same statuses as µs (difference 0–1 runs). | **Right:** 1 run (T12b). |
| (e) 10 ms and 25 ms give the same results; 250 ms gives more runs with several fitting outcomes. | **Half right:** 10 and 25 ms are the same, but no run had several outcomes at any tolerance. |
| (f) No window fit is unexplained. | **Right:** 0 of 86. |
| (g) Most hard runs (3 or more of 4) are incomplete. | **Wrong:** all 4 reproduced; T22 took 27 runs. |
| (h) All 3 controls are reproduced, with 0 restored faults. | **Right.** |
| (i) Window fits use fewer runs than the whole-log fit of the same log. | **Wrong:** 2 of 43 windows did (both T12); 41 used the same 4 runs. |
| (j) Most missed injected drops are read as long delays (at least half). | **Right:** 12 of 12. Written after the fake-board checks showed this in T04 and T05. |

(b) and (g) are the instructive ones. (g) expected hard plans to be hard to reproduce. They were
not, because the wide ranges let the fit reproduce almost anything at its first choice. (b)
expected reproducing to mean recovering. It did not, for the same reason. The difficulty moved
from finding a plan to choosing among plans.

## Departures from the registration

1. **Sessions that got no READY: a general rule, added during the run.**
   - Rule: a session that receives no `READY` within 10 s has not started. It is run again with
     the same seed, and each such session is recorded with how the board was recovered.
   - The first attempt (2026-11-11) got no `READY` in T00a, T00b and T00c. All files were empty,
     so no measured data existed. The loop was stopped by hand and the empty files deleted.
   - The board enumerated on USB but sent nothing.
   - ModemManager was running and treated the port as a modem candidate. The operator added a
     udev rule so it ignores the board (`ID_MM_DEVICE_IGNORE=1`) and replugged the board. The
     board then answered (`READY log=1 defect=none`) and was not reflashed. Whether the USB bridge
     or ModemManager caused the silence is not known.
   - All 39 runs then ran from T00a with the registered seeds, and each got `READY` on its first
     start.
2. **The run script changed: it stops at the first session that gets no READY.** It deletes that
   session's empty files and stops, instead of going on. Run order, seeds and client arguments are
   unchanged.
3. **Counted after the runs, not registered:**
   - the by-kind table;
   - the request-duplicate observation;
   - the invented-drop count;
   - the T12 diagnosis.

   All four come from rerunning the same deterministic whole-log fit (µs, 25 ms) and listing its
   plan next to the truth file. Every registered column above comes from the registered analysis
   unchanged.

## Limits

- **No defect in the firmware.** "Unexplained = evidence of a defect" is not tested here; that is
  stage 3.
- **Disconnects are announced by the link at once.** A real TCP link detects them late.
- **Plan keys use the first attempt.** Under another think time the same plan can land in a
  different device state; the truth file is the reference.
- **Timestamps are µs, but USB serial is coarser than that.**
- **The count of fitting explanations is not their likelihood.** Here no run had more than one
  outcome, yet the plans were often wrong. Several plans give the same outcome, and the outcome
  count cannot see that.
- **One fitter, one cap, one range.** A narrower public range, or a fit that prefers fewer faults,
  would read these logs differently. "Found" means found in the first plan that reproduces.
