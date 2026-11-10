# Driven replay experiment 01: seed-blind reproduction of client-side logs

Operator document. Do not give it to a planner.

The WP4 bridge experiments reproduced each log using the hidden run's seed. Under that seed the
simulated client sent the same commands at the same times as in the log, so the only unknowns were
link faults and most delays. A real log comes with no seed. Driven replay
([driven-replay.md](../driven-replay.md)) needs none: it replays the client's log as a script and
simulates only the device. This experiment asks two questions:

- How many of the client-side logs that the rule-based reader solved with the seed does it solve
  without the seed?
- How much of the gap does a round-trip start close?

No model is involved and nothing was spent. The operator's pre-registration, logs and scripts are
outside the repository. Logs are named here by neutral ids, D01 to D17.

## Setup

- **Logs:** the 19 client-side logs of the WP4 pool, minus the two looked at while tuning the
  reader: 17 logs, 11 lift and 6 turntable. All 17 defects are on the device side.
- **Log text:** each hidden run's client side was written as a ROS-style text log with
  `incident text`, once with microsecond timestamps and once with millisecond timestamps.
  Each log was ingested with `examples/rules/sim-client-ros.yaml`. Every line matched a rule and
  no line was flagged.
- **Harness and budget:**
  - Harness `ec436fe` (main after PR #17).
  - Budget 120 runs per log.
  - The reader's limits are unchanged: 40 search edits, 40 tries per line.
- **Judge:**
  - Only the client's receives are compared, with polls left out.
  - Each receive must fall within 250 ms of its log line.
  - The run ends at 90 s.
  - The violated contracts must equal the incident's.
- **Round-trip start:** each request/ACK round trip is split 0.5 to the request, and the reader may
  also shift a split.
- **Hidden variants:** the turntable defects run as hidden variants. The variant file gained one
  line (`device=`), and its digest change is recorded in the registration.

## Columns

| Column | Oracle | Judge |
| --- | --- | --- |
| Seed, old judge | WP4 bridge oracle with the incident's seed (existing record, reader `93098bc`, not rerun) | every compared client line; clock offset estimated |
| Seed, new judge (control) | the same seeded oracle | as driven replay: receives only, clock known |
| Driven, reader unchanged | driven replay, `base: fixed`, empty start | receives only |
| Driven, round-trip start | driven replay, round-trip start and split shifts | receives only |

The control column separates two effects: the seed's, and the judge's.

## Results

"yes (n)": reproduced, at run n. "budget": the 120 runs were used up. "stuck": no improving edit
was left. Split sensitivity is computed for the log solved by driven replay; see Departures.
Ceiling: the hidden run's own link plan, replayed by driven replay, for the µs and the ms log.

| Log | System | Seed, old judge | Seed, new judge | Driven, unchanged µs | Driven, round-trip µs | Driven, unchanged ms | Driven, round-trip ms | Split sensitivity | Ceiling µs / ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D02 | lift | budget | yes (37) | budget | budget | budget | budget | - | yes / no |
| D03 | lift | yes (91) | yes (34) | budget | yes (118) | budget | yes (118) | 3/4 (fixed: 0/4) | yes / yes |
| D04 | lift | budget | budget | budget | budget | budget | budget | - | yes / yes |
| D06 | lift | budget | budget | budget | budget | budget | budget | - | yes / no |
| D07 | lift | stuck | stuck | budget | budget | budget | budget | - | yes / yes |
| D08 | lift | budget | budget | budget | budget | budget | budget | - | yes / yes |
| D09 | lift | budget | stuck | stuck | stuck | stuck | stuck | - | yes / no |
| D11 | lift | budget | budget | budget | budget | budget | budget | - | yes / no |
| D12 | lift | budget | budget | budget | budget | budget | budget | - | yes / no |
| D14 | lift | yes (42) | yes (74) | budget | budget | budget | budget | - | yes / no |
| D15 | lift | budget | yes (11) | budget | budget | budget | budget | - | yes / no |
| D01 | turntable | yes (19) | yes (20) | budget | budget | budget | budget | - | yes / yes |
| D05 | turntable | yes (79) | stuck | budget | budget | budget | budget | - | yes / yes |
| D10 | turntable | yes (16) | budget | budget | budget | budget | budget | - | yes / no |
| D13 | turntable | budget | budget | budget | budget | budget | budget | - | yes / no |
| D16 | turntable | budget | yes (18) | budget | budget | budget | budget | - | yes / yes |
| D17 | turntable | yes (38) | stuck | stuck | stuck | stuck | stuck | - | yes / yes |

Totals:

| | Seed, old judge | Seed, new judge | Driven, unchanged µs / ms | Driven, round-trip µs / ms | Ceiling µs / ms |
| --- | --- | --- | --- | --- | --- |
| lift (11) | 2 | 4 | 0 / 0 | 1 / 1 | 11 / 4 |
| turntable (6) | 4 | 2 | 0 / 0 | 0 / 0 | 6 / 4 |
| all (17) | 6 | 6 | 0 / 0 | 1 / 1 | 17 / 8 |
| the 6 solved with the seed, old judge | 6 | 3 | 0 / 0 | 1 / 1 | 6 / 4 |

On D03, the one log driven replay solved, the round-trip start used 11 start delays and 14 search
edits. On the other logs the reader ran out of budget before any branch of its search ended, so the
edit counts say nothing and are left out.

## What the results show

- **The seed did most of the work in WP4.**
  - With the seed, the reader solves 6 of 17 under either judge. Without it, the reader unchanged
    solves none, and the round-trip start solves one.
  - The judge changes which logs are solved (3 in common, 3 each only under one judge) but not how
    many. So the drop from 6 to 0 or 1 is the seed's effect, not the judge's.
- **The cost is delays, not faults.**
  - Every log reproduces exactly when the hidden run's own link plan is replayed (ceiling, µs:
    17/17), so driven replay and its judge are sound.
  - Without the seed, every delay that matters starts at the profile minimum. The reader unchanged
    used up its 120 runs on 15 of 17 logs.
  - In 7 logs a search branch ended before the budget ran out. In 5 of them it stopped at a
    `DONE`, 4 times at the first command's `DONE`.
  - With the seed, those delays were already right for every message the plan did not name.
  - The round-trip start fills in the request/ACK delays, but not the delays of later replies.
- **Millisecond timestamps lose information the reader needs.**
  - The reader's results were the same at ms as at µs.
  - Replaying the true plan, however, reproduces only 8 of 17 ms logs.
  - A resend the client made at a reconnect is logged up to 1 ms early. Before a reconnect at
    microsecond precision, that is while the link is still down, so the resend is lost.
  - A plan that fits millisecond times exists: it would end the disconnect up to 1 ms earlier.
    But real logs at ms precision will need it.
- **Two logs are stuck with and without the seed (D09, D17).** The first command's replies are all
  missing from the log. Explaining that takes losing all three attempts together, and each single
  edit improves nothing, so the search never takes the first step.

## Predictions

Registered before the runs:

| Prediction | Result |
| --- | --- |
| (a) The reader unchanged solves fewer than with the seed (6/17). | **Right**: 0/17. |
| (b) With the round-trip start it solves 6/17 or more. | **Wrong**: 1/17. |
| (c) The ms columns equal the µs columns or are one lower. | **Right**: equal (0 and 1). |
| (d) Logs with split sensitivity k > 0 are those whose defect depends on when a command reaches the device. | **Not decidable.** The registered column has one log with k > 0 (D03, 3/4), and by the registered criterion that is wrong: two of its sensitive round trips belong to other requests. But that value came from a defect in the diagnostic (Departures 2). With the defect fixed, D03 has k = 0, and no log is left to judge. |

(b) is the instructive one. The round-trip start fixes a request's delay from its `ACK`. But what
the reader failed to fit was mostly later: a command's `DONE`, retries after a lost reply, and
disconnects. Starting delays well is not the same as the seed handing over all of them.

## Departures from the registration

1. **Ceiling check, added after the runs.** It is not a registered column. Each log was replayed
   with its hidden run's own link plan: 17/17 µs logs reproduce exactly, 8/17 ms logs reproduce.
2. **The split sensitivity diagnostic had a defect.**
   - When a split moved, a later reply (`DONE`, `ERROR`) at the base delay was not held in place.
     Its receive time moved with the request, and the round trip counted as sensitive.
   - The registered column stands as computed: D03 3/4.
   - Recomputed with the fix (PR #19) on the same plan: D03 0/4.

## Limits

- **The logs are simulator output written as text,** not real logs. Every line is complete, and
  there is no clock jitter beyond the ms truncation.
- **Pairing round trips by attempt number can be wrong.** It pairs the j-th `ACK` with the j-th
  attempt, so when an earlier attempt's `ACK` was lost the pairing is off. The search may correct
  it, within its budget.
- **One reader, one budget.** A reader that places later replies' delays from the device's
  timing, or that tries multi-message edits, could solve more. "Not solved" means not solved by
  these rules in 120 runs.
- **Client side only, one source.** All 17 defects are on the device side.
- **Split sensitivity measures one log here (D03),** so it gives no picture of ambiguity across
  logs yet.
