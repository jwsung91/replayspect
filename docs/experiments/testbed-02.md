# Testbed experiment 02: minimal explanations on real-hardware logs

Operator document. Do not give it to a planner.

As in [testbed-01](testbed-01.md), the lift device ran on an Arduino Uno with no defect, and a
Jetson Orin ran the client and a fault link that applied a known plan and wrote a truth file. The
fit is now the minimal-explanation fit of PR #26 (`drive --fit`, [driven-replay.md](../driven-replay.md)).
Given only the client log, it returns every explanation with the fewest link faults (`f*`), the
faults common to all of them ("determined"), the alternatives ("not determined"), the explanations
with one fault more (`f*+1`), and a list of slow round trips read from the log alone.

*Note added later:* "determined" is now called "common to every minimal explanation" and "not
determined" "alternatives"; this document keeps the names it was written with.

The questions:

1. Is the truth in the set?
2. How large is the set?
3. How often is a determined fault real?

The **main indicator** was the number of wrong "unexplained" verdicts. The firmware has no
defect, so any `unexplained` would be a limit of the fitter reported as evidence about the
device. Whether stage 3 (a real defect) can start depends on this number being 0.

No model is involved and nothing was spent. The registration, client logs, device logs, truth
files and seeds are outside the repository. The plans are listed here.

## Setup

- **Harness:** `20cb5a0` (main after PR #26), unchanged during and after the runs. Firmware, host
  code and rules are the testbed-01 files (same hashes). The Uno kept the stage-1 build with the
  device log on (`READY log=1 defect=none`).
- **Sessions:** 6 move commands each, 90 s, at 115200 baud over USB serial.
- **Fit:** `--usual-delay 4000 4000`, tolerance 25 ms, ranges 0–5 s (c2s, s2c, dup extra), cap
  20,000 runs per log, `--plus-one`. Each log was fitted as written (µs) and as a copy cut to ms.
- **Reference column:** the testbed-01 fitter (`efd9535`, cap 120, 25 ms, µs) on the same logs,
  with the same truth set.
- **Development data:** testbed-01's 39 logs. The fitter was fixed on them once (T22, in #26).
  Before registration they were run with the new fitter and compared with the memo's predictions
  (not a score); the predictions for this experiment were then revised once, and the revision is
  part of the registration.

**Comparison with the truth file.**

- **Threshold:** usual 4 ms + tol 25 ms = 29 ms.
  - An injected delay of 29 ms or more is a fault.
  - An injected delay of 19 ms or less (29 ms minus 10 ms of physical delay) is not a fault, and
    a fault restored on its key counts as false.
  - Nothing was injected in between.
- **A restored fault is real** when the truth has the same kind on the same
  `(dir, msg, req_id, k)`.
  - A dup's extra delay must match within the tolerance.
  - A delay's value must fall within [injected − tol, injected + 10 ms + tol].
- **Not faults:** messages lost to a logged disconnect (truth entries `lost_in_disconnect`).
- **"Truth in the set"** means that one explanation is exactly the truth set.
- **Poll faults** are counted in their own rows. The search does not vary poll requests, so a
  poll-request fault can only be read on the reply side; this was expected.

## Plans and runs

48 runs:

- 3 controls (C00a–c);
- 17 single plans × 2 think-time seeds (S01a … S17b);
- 5 retry plans (R01–R05);
- 3 plans whose truth is not minimal on purpose (N01–N03);
- 3 mixed plans (M01–M03).

No seed was reused from testbed-01.

| Plan | Faults |
| --- | --- |
| S01 | c2s MOVE_UP r-0003 k0 delay 15 ms (below the threshold) |
| S02 | s2c ACK r-0002 k0 delay 15 ms (below the threshold) |
| S03 | c2s MOVE_DOWN r-0004 k0 delay 40 ms |
| S04 | s2c ACK r-0005 k0 delay 40 ms |
| S05 | s2c DONE r-0003 k0 delay 40 ms |
| S06 | c2s MOVE_UP r-0001 k0 delay 100 ms |
| S07 | s2c ACK r-0004 k0 delay 100 ms |
| S08 | s2c DONE r-0002 k0 delay 100 ms |
| S09 | disconnect 1000 ms, 500 ms after c2s MOVE_UP r-0003 k0; s2c ACK r-0003 k1 drop (the reply to the resend after reconnect) |
| S10 | disconnect 1000 ms, 500 ms after c2s MOVE_DOWN r-0004 k0; c2s MOVE_DOWN r-0004 k1 delay 100 ms |
| S11 | c2s STATUS s-0005 k0 drop |
| S12 | s2c STATUS_REPLY s-0008 k0 drop |
| S13 | s2c STATUS_REPLY s-0012 k0 delay 100 ms |
| S14 | c2s STATUS s-0015 k0 dup +300 ms |
| S15 | c2s MOVE_DOWN r-0002 k0 drop |
| S16 | c2s MOVE_UP r-0005 k0 dup +200 ms |
| S17 | disconnect 1500 ms, 0 ms after c2s MOVE_DOWN r-0002 k0 (T12 shape, no link fault) |
| R01 | c2s MOVE_UP r-0003 k0 drop; c2s MOVE_UP r-0003 k1 delay 100 ms |
| R02 | s2c ACK r-0002 k0 drop; s2c ACK r-0002 k1 drop |
| R03 | c2s MOVE_DOWN r-0004 k0 drop; c2s MOVE_DOWN r-0004 k1 dup +300 ms |
| R04 | s2c ACK r-0005 k0 delay 2500 ms; s2c ACK r-0005 k1 delay 40 ms |
| R05 | c2s MOVE_UP r-0001 k0 drop; s2c ACK r-0001 k0 drop (the reply to k1, so k2 follows) |
| N01 | c2s MOVE_UP r-0003 k0 dup +300 ms; s2c ACK r-0003 k0 drop (T14 shape) |
| N02 | s2c ACK r-0002 k0 delay 300 ms; s2c DONE r-0002 k0 delay 300 ms |
| N03 | c2s MOVE_UP r-0005 k0 dup +100 ms; s2c ACK r-0005 k1 drop (the copy's reply) |
| M01 | c2s MOVE_UP r-0001 k0 drop; s2c ACK r-0001 k0 delay 40 ms; s2c STATUS_REPLY s-0020 k0 drop; s2c DONE r-0004 k0 delay 100 ms |
| M02 | disconnect 1500 ms, 0 ms after c2s MOVE_DOWN r-0002 k0; c2s MOVE_UP r-0003 k0 dup +200 ms; s2c ACK r-0005 k0 drop; c2s MOVE_UP r-0005 k1 delay 100 ms |
| M03 | c2s STATUS s-0006 k0 drop; c2s MOVE_DOWN r-0004 k0 delay 15 ms; s2c DONE r-0006 k0 dup +500 ms; s2c ACK r-0003 k0 delay 2500 ms |

**N labels checked before registration.** Before registration, the N plans were run on the
simulator: the fake port of `tests/test_testbed_host.py`, with the lift model and 3 ms each way.
Each label held (`f*` 1, 1 and 0, each below the truth's 2), so no plan was replaced.

All 48 runs were valid on their first start. No device error line appeared, the board did not
reset, and every session got `READY`. Every planned fault was applied. The truth set has 54
faults: 44 on commands and 10 on polls.

## Results

Columns are µs at 25 ms.

- **Set:** the number of explanations at `f*`.
- **In set:** the truth is one of them.
- **In `f*`/`f*+1`:** the truth is among the `f*` or the `f*+1` explanations.
- **Determined:** real ones / reported (poll faults included).
- **Slow round trips:** the request id, the attempt, and the excess over the log's median
  request→`ACK` gap. They are from the log, not the fit.

| Run | Status | Runs | `f*` | Truth | Set | In set | In `f*`/`f*+1` | Determined real / reported | Slow round trips | Reference found / injected, correct / restored |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C00a | reproduced | 4 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 0 |
| C00b | reproduced | 4 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 0 |
| C00c | reproduced | 4 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 0 |
| S01a | reproduced | 4 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 0 |
| S01b | reproduced | 4 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 0 |
| S02a | reproduced | 4 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 0 |
| S02b | reproduced | 4 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 0 |
| S03a | reproduced | 4 | 0 | 1 | 1 | no | no | 0 / 0 | r-0004 k0 +40 ms | 0 / 1, 0 / 0 |
| S03b | reproduced | 4 | 0 | 1 | 1 | no | no | 0 / 0 | r-0004 k0 +41 ms | 0 / 1, 0 / 0 |
| S04a | reproduced | 4 | 1 | 1 | 1 | yes | yes | 1 / 1 | r-0005 k0 +40 ms | 1 / 1, 1 / 1 |
| S04b | reproduced | 4 | 1 | 1 | 1 | yes | yes | 1 / 1 | r-0005 k0 +40 ms | 1 / 1, 1 / 1 |
| S05a | reproduced | 4 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 1 / 1, 1 / 1 |
| S05b | reproduced | 4 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 1 / 1, 1 / 1 |
| S06a | reproduced | 26 | 1 | 1 | 1 | yes | yes | 1 / 1 | r-0001 k0 +100 ms | 0 / 1, 0 / 3 |
| S06b | reproduced | 24 | 1 | 1 | 1 | yes | yes | 1 / 1 | r-0001 k0 +100 ms | 0 / 1, 0 / 3 |
| S07a | reproduced | 26 | 1 | 1 | 1 | yes | yes | 1 / 1 | r-0004 k0 +101 ms | 1 / 1, 1 / 1 |
| S07b | reproduced | 24 | 1 | 1 | 1 | yes | yes | 1 / 1 | r-0004 k0 +101 ms | 1 / 1, 1 / 1 |
| S08a | reproduced | 23 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 1 / 1, 1 / 1 |
| S08b | reproduced | 23 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 1 / 1, 1 / 1 |
| S09a | reproduced | 212 | 1 | 1 | 2 | yes | yes | 0 / 0 | — | 0 / 1, 0 / 2 |
| S09b | reproduced | 181 | 1 | 1 | 2 | yes | yes | 0 / 0 | — | 0 / 1, 0 / 2 |
| S10a | reproduced | 219 | 1 | 1 | 2 | yes | yes | 0 / 0 | r-0004 k1 +101 ms | 0 / 1, 0 / 2 |
| S10b | reproduced | 241 | 1 | 1 | 2 | yes | yes | 0 / 0 | r-0004 k1 +100 ms | 0 / 1, 0 / 2 |
| S11a | reproduced | 4 | 1 | 1 | 1 | no | no | 0 / 1 | — | 0 / 1, 0 / 2 |
| S11b | reproduced | 4 | 1 | 1 | 1 | no | no | 0 / 1 | — | 0 / 1, 0 / 2 |
| S12a | reproduced | 4 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 1 / 1, 1 / 2 |
| S12b | reproduced | 4 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 1 / 1, 1 / 2 |
| S13a | reproduced | 4 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 0 / 1, 0 / 2 |
| S13b | reproduced | 4 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 0 / 1, 0 / 2 |
| S14a | reproduced | 4 | 1 | 1 | 1 | no | no | 0 / 1 | — | 0 / 1, 0 / 1 |
| S14b | reproduced | 4 | 1 | 1 | 1 | no | no | 0 / 1 | — | 0 / 1, 0 / 1 |
| S15a | reproduced | 226 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 0 / 1, 0 / 5 |
| S15b | reproduced | 226 | 1 | 1 | 1 | yes | yes | 1 / 1 | — | 0 / 1, 0 / 5 |
| S16a | reproduced | 26 | 1 | 1 | 2 | yes | yes | 0 / 0 | — | 0 / 1, 0 / 1 |
| S16b | reproduced | 25 | 1 | 1 | 2 | yes | yes | 0 / 0 | — | 0 / 1, 0 / 1 |
| S17a | reproduced | 146 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 1 |
| S17b | reproduced | 146 | 0 | 0 | 1 | yes | yes | 0 / 0 | — | 0 / 0, 0 / 1 |
| R01 | reproduced | 305 | 2 | 2 | 2 | yes | yes | 0 / 0 | r-0003 k1 +100 ms | 0 / 2, 0 / 5 |
| R02 | reproduced | 187 | 2 | 2 | 2 | yes | yes | 1 / 1 | — | 1 / 2, 1 / 3 |
| R03 | reproduced | 351 | 1 | 2 | 1 | no | yes | 0 / 1 | — | 0 / 2, 0 / 5 |
| R04 | reproduced | 415 | 2 | 2 | 2 | no | no | 0 / 1 | r-0005 k1 +40 ms | 0 / 2, 0 / 3 |
| R05 | reproduced | 5347 | 2 | 2 | 1 | yes | yes | 2 / 2 | — | 0 / 2, 0 / 7 |
| N01 | reproduced | 26 | 1 | 2 | 1 | no | yes | 0 / 1 | r-0003 k0 +300 ms | 0 / 2, 0 / 1 |
| N02 | reproduced | 24 | 1 | 2 | 1 | no | yes | 0 / 1 | r-0002 k0 +301 ms | 0 / 2, 0 / 3 |
| N03 | reproduced | 4 | 0 | 2 | 1 | no | no | 0 / 0 | — | 0 / 2, 0 / 0 |
| M01 | reproduced | 340 | 4 | 4 | 2 | yes | yes | 2 / 2 | r-0001 k1 +47 ms | 2 / 4, 2 / 8 |
| M02 | reproduced | 458 | 3 | 3 | 8 | yes | yes | 0 / 0 | r-0005 k1 +100 ms | 0 / 3, 0 / 5 |
| M03 | reproduced | 404 | 3 | 3 | 2 | no | no | 1 / 2 | — | 1 / 3, 1 / 6 |

**Every run:**
- All 48 were reproduced, with the minimal set and the `f*+1` level complete (`minimal_shown`,
  `plus_one_shown`). No run hit the cap; the most runs a log needed was 5,347 (R05).
- **Wrong "unexplained": 0.** `incomplete`: 0.
- **ms copy:** all 48 reproduced, with the same `f*` and the same "truth in the set" as µs.
- **Set size:** 1 in 36 runs, 2 in 11, and 8 in one (M02).

**By group** (determined faults without polls):

| Group | Runs | Truth in set | Determined real / reported |
| --- | --- | --- | --- |
| control | 3 | 3 | 0 / 0 |
| single | 34 | 28 | 12 / 12 |
| retry | 5 | 3 | 3 / 5 |
| not minimal | 3 | 0 | 0 / 2 |
| mixed | 3 | 2 | 2 / 2 |

**By kind** (injected faults: determined / among the alternatives / absent):

| Kind | Injected | Determined | Alternative | Absent |
| --- | --- | --- | --- | --- |
| drop c2s | 6 | 3 | 2 | 1 |
| drop s2c | 8 | 2 | 4 | 2 |
| dup c2s | 6 | 0 | 3 | 3 |
| dup s2c | 1 | 0 | 1 | 0 |
| delay c2s | 8 | 2 | 4 | 2 |
| delay s2c | 15 | 10 | 2 | 3 |
| poll drop c2s | 3 | 0 | 0 | 3 |
| poll dup c2s | 2 | 0 | 0 | 2 |
| poll drop s2c | 3 | 3 | 0 | 0 |
| poll delay s2c | 2 | 2 | 0 | 0 |

**Determined precision:**
- **Commands:** 17 of 21 (81%). The false ones are R03, N01 and N02 (a non-minimal truth read as
  one delay) and R04 (see below).
- **Polls:** 5 of 10. The false ones are S11a/b, S14a/b and M03's: poll-request faults read as
  reply drops or reply dups, as expected.
- **Loss read as delay** (testbed-01's rule): 2. Delay read as loss and request loss read as reply
  loss: 0.

**Reference** (testbed-01 fitter):
- reproduced 48;
- found 14 of 54 injected faults;
- 14 of its 96 restored faults are real.

The new fit's determined faults found 22, with 9 not real.

## What the results show

**The main indicator is 0.** No log was called unexplained.

- Every run reproduced and its minimal set was complete.
- This includes the T12 shape (S17a/b) and disconnects followed by retries (S09, S10, M02).

**The truth is in the set where it is minimal.**
- **The 37 runs not predicted to miss:** the truth is in the set in 36. The miss is M03, whose
  poll-request drop is read on the reply side.
- **Where the truth is not minimal:** N01–N03, R03, S03 and R04's 40 ms retry `ACK`. The set holds
  a smaller explanation, as designed.
- **Where one record cannot decide:** the set holds both alternatives. Examples:
  - request dup or `ACK` dup (S16a/b, M02 r-0003);
  - request or reply after a reconnect (S09, S10);
  - which attempt was lost and which was late (R01, M01, M02 r-0005).

**R04: the reported `f*` is not the minimum.** The fit reported `f*` 2: a determined `ACK` k0
delay of 2.04 s (false), plus the retry's `ACK` delayed 502 ms or the retry delayed 42 ms.

- **A 1-fault explanation exists.** A post-hoc check (not registered; the fitter's own evaluation,
  on the same log) shows it. If the retry arrives 16.9–28.9 ms after its send, the whole log
  reproduces with one fault: `ACK` k0 delayed 2.50 s, which is the injected value.
- **Why the search missed it.** The fitter offers each attempt a few arrival points:
  - the default (4 ms);
  - 0 and just after 4 ms;
  - the point where the logged `ACK` sits at the usual delay (41.9 ms);
  - points much later.

  None of them lies in that window. The window comes from pairing the replies out of order: k0's
  `ACK` with the second receive (2.5 s late), and the retry's `ACK` with the first. The default
  arrival's bounds pair them in order, so the retry gets an empty bound and falls back to
  send + 4 ms. The reply pairing does consider the reversed order, but only for arrivals already
  offered, and none of those is in the window.
- **What it means.** This is the "all minimal holds only within the option points" limit of the
  registration, seen on a real log. The A2 brute-force control and the A5 random-arrival test did
  not catch it. A2 uses the same points. A5 draws arrivals for short synthetic logs, not this
  reordered-reply shape.
- Per the registration, the fitter was not changed. The fix goes to the next piece of work.

**S03: the `f*+1` level is empty when nothing is anomalous.**
- S03's 40 ms request delay is absorbed: `f*` is 0, as predicted, and it is listed among the slow
  round trips (2 of 2).
- The fit searches `f*+1` only inside units, which are the anomalous commands. A log the default
  explains has no unit, so its `f*+1` set is empty, and the predicted "truth in the `f*+1` set"
  could not happen. N03 is empty for the same reason, as predicted.

**Slow round trips catch what the minimal set absorbs.** 16 runs list one slow round trip, each
on a request with an injected fault:
- the S03 and R04 40 ms delays explained without a fault;
- the 100 ms request delays;
- reply delays on `ACK`;
- N01's copy, and N02's 300 ms reply delay.

No run lists one on a request without an injected fault or a disconnect.

**Request dups:** the minimal ones (S16a/b, M02 r-0003) always come out as "request dup or `ACK`
dup". The ones not in the set (R03, N01, N03) are non-minimal by design. Nothing here points at the
one-time dup copy limit.

## Predictions

Registered before the runs (the agent's predictions, revised once after the development results):

| Prediction | Result |
| --- | --- |
| (a) Controls and S17a/b: reproduced, `f*` 0 (5 of 5). | **Right:** 5/5. |
| (b) Below threshold (S01, S02, M03's 15 ms): no fault restored on those keys (5 of 5). | **Right:** 5/5. |
| (c) 100 ms delays (S06–S08): determined and real in at least 5 of 6. | **Right:** 6/6. |
| (d) S03: `f*` 0 and the truth in the `f*+1` set (2 of 2). | **Wrong:** `f*` 0 in 2/2, but the `f*+1` set is empty (0/2). |
| (d) S04: the 40 ms `ACK` delay found in at least 1 of 2. | **Right:** 2/2. |
| (d) S05: the 40 ms `DONE` delay found (2 of 2). | **Right:** 2/2. |
| (d) R04: `f*` below the truth's 2. | **Wrong:** `f*` 2. A 1-fault explanation exists off the option points (see above). |
| (e) S09, S10: the truth in a set of size 2 (4 of 4). | **Right:** 4/4. |
| (f) Poll-request faults (S11, S14) not in the set (4 of 4); poll-reply faults (S12, S13) determined and real (4 of 4). | **Right:** 4/4 and 4/4. |
| (g) N01–N03: truth not in the `f*` set (3 of 3); in the `f*+1` set for N01 and N02, not N03. | **Right:** 3/3 and 3/3. |
| (h) The 37 runs not predicted to miss: truth in the set in at least 32. | **Right:** 36/37. |
| (i) Determined precision without polls: at least 80%. False ones expected: N01, N02, R03. | **Right, at the margin:** 17/21 (needed 17). The fourth false one is R04. |
| (j) 48/48 reproduced, `minimal_shown` in all, no cap hit. | **Right.** |
| (k) The reference finds fewer injected faults and restores more that are not real. | **Right:** found 14 vs 22; not real 82 vs 9. |
| (l) Slow round trips list S03 (2/2), R04's retry (1/1), S06a/b, R01 and S10a/b, and none on a request with no injected fault or disconnect. | **Right:** 8/8; 0 without a cause. |
| (m) Main indicator: wrong "unexplained" 0. | **Right:** 0. |
| (n) Request dups (S16a/b, M02 r-0003) not determined, with both alternatives (3 of 3). | **Right:** 3/3. |

The two wrong ones point at the search, not at the truth. R04 is a minimum the search missed, and
S03 is a level the search does not run. (i) holds only at its threshold, because of R04.

## Departures from the registration

1. **Counted after the runs, not registered:**
   - the R04 diagnosis (a hand-run check of the retry's arrival times and of the default
     arrival's bounds, with the fitter's own functions);
   - the S03 explanation of the empty `f*+1` set.

   Every registered column and prediction check above comes from the registered analysis,
   unchanged and run once.

No other departure: no session needed a restart, and no file in the registration's hash table
changed.

## Limits

- **No defect in the firmware.** This is not stage 3. "Unexplained = evidence of a defect" is
  still untested on hardware.
- **"Minimal" holds only within the option points.**
  - R04 shows a real log where the reported `f*` is one too high.
  - A dup copy is placed at one time only. No test checks whether that restriction misses a
    minimal explanation either.
- **`f*+1` is searched only inside anomalous commands.**
- **Polls are fixed in the search.** A poll-request fault reads as a reply fault.
- **Per-direction threshold.**
  - A request delayed by up to about 50 ms over the usual round trip is no fault (S03, R04's
    retry). The slow round-trip list reports it from the log.
  - The threshold rests on the 4 ms usual delay from stage 1.
- **The link announces disconnects at once.** A real TCP link detects them late.
- **One fitter version, one tolerance, one range.** The harness was not changed during or after
  the runs.
