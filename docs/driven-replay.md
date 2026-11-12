# Driven replay (WP5b): reproduce a client-side log without a seed

`ingest` turns a text log into a trace ([rules-schema.md](rules-schema.md)) that `rewind` can
read. `drive` makes that trace reproducible. The WP4 bridge experiments reproduced logs with the
hidden run's seed. There, the simulated client's schedule matched the log only because both came
from the same seed, and a real log has no such seed. Driven replay needs none: the log's
participant drives the simulation.

```bash
python3 -m replayspect ingest client.log --rules examples/rules/sim-client-ros.yaml --out client.jsonl
python3 -m replayspect drive client.jsonl --system lift.v0 --until 90s --reconstruct --rtt --sensitivity --trace-out run.jsonl
# drive client.jsonl: lift.v0, client side scripted (205 events, 98 sends); 14 receives to match, polls left out; ...
# reconstruct: reproduced after 46 runs, 8 search edits; 16 start delays from round trips (split 0.5)
# plan: base fixed, 18 delays, 0 faults, 0 disconnects
# reproduced: yes; receives matched 14/14, largest time difference 152.928ms
# split sensitivity: 5 of 8 round trips change the outcome at an extreme split (ACK r-0001 k=0, ...)
# trace: 432 events -> run.jsonl (matched receives carry their log line)
python3 -m replayspect rewind run.jsonl --actor client --window 2s 5s
#   #15 2.123398s client recv ACK r-0001 k=0 [matches log line 5]
```

The scope is **one source, the client side**. The log's times are then the simulation's times,
so there is no clock to estimate. Merging a controller log with a device log, and estimating the
clock between them, is later work. So is a device-side log alone, where the client's schedule
would have to be inferred.

## How a run is built

- **The script** takes the client's place on the channel (`Channel.attach`).
  - It sends every recorded message at its recorded time, with the recorded fields.
  - It records the client's own decisions (`handle`, `state`, `effect`) at their times.
  - Its message and connection callbacks do nothing, because retries and resends are already in
    the log as facts.
  - Recorded receives are not scheduled: producing them is the simulation's job.
- **Order within an instant.** A recorded event runs after everything already due at its
  instant. A client usually acts on something at that instant, such as a reconnect it resends on
  or a reply it closes a command on, and its action must not overtake the cause. The log does not
  show the cause.
- **The device** is the system's model (`System.device`; a variant gives one with `device`). It
  runs on the package's scheduler and channel.
- **The link** follows a fault plan. With `base: fixed`, an unplanned delay is the profile
  minimum. No part of the run draws from a seed:
  - the device models draw no random numbers;
  - the script replaces the only participant that did;
  - the scheduler's seed is fixed and unused, and the tests check that another seed gives the
    same digest.
- **Fidelity:** the script's sends and decisions are `exact`. Everything the models produced is
  `reconstructed`: the device, the link, and the client's receives.

A sanity check in the tests: with the plan that `FaultPlan.from_trace` takes from the original
run, the driven run produces every client receive at exactly its original time.

## Link delay for a run, and residuals

- **`--link-delay LO HI`** replaces the system profile's delay range, in both directions, for one
  `drive`. An empty plan uses LO, and `--fit`'s default ranges follow it. 0 is allowed.
- **`--residuals`** prints recorded minus simulated time for every matched receive, overall and by
  message (min, median, max).

With `--link-delay 0 0`, the residuals of a fault-free log are the real total delay of each round
trip plus the model's timing error. Do not use `--fit` for this measurement: it computes each reply
delay from the log, so the residuals are 0 by construction.

## The judge

Only the client's receives are compared, with polls left out, in order. Two receives match when
they have the same kind, name, request id and data without `link`, and their times differ by at
most the tolerance (default 250 ms, as in WP4).

- The script's sends and decisions are in both traces by construction, so comparing them would
  prove nothing.
- Receives after the log's last event plus the tolerance are not compared.
- With `--expect`, the run's violated contracts must be exactly the given ones. Existing
  incidents have such an expectation; a real log does not. WP6/7's symptom judge takes that place.
- `--status-rule` also compares the sequence of poll replies, as in WP4.

`--trace-out` writes the run. Each matched receive carries the log line it matched (`log.line`),
which `rewind` shows as `[matches log line N]`.

## The reader

`drive --reconstruct` runs the rule-based reader ([`replayspect.reconstruct`](../src/replayspect/reconstruct.py))
against driven runs. The clock is known, so no offset is estimated. Only receives are compared,
and the plan's base is `fixed`.

- **Unchanged reader** (no `--rtt`): it starts from the empty plan. Without the seed, every
  message that matters needs its delay found by search. On a real log this is the normal case,
  not an exception.
- **`--rtt` (round-trip start):**
  - A prompt reply (`ACK`) leaves the device as soon as the request arrives. Its receive time
    minus the request's send time is therefore the request's delay plus the reply's.
  - The reader starts from a plan that splits each such round trip, `--split` to the request
    (default 0.5), within the delay ranges.
  - The j-th `ACK` of a request is paired with the request's j-th attempt.
  - The reader may also shift a round trip's split, which moves when the request arrived without
    moving its `ACK`.
  - Start delays are counted apart from search edits. The edit limit (`MAX_EDITS`) applies to
    search edits only.

## Fitting by fixing what the log shows (`--fit`)

`drive --fit` explains a client log with the fewest link faults. It reports every explanation
with that many faults, and which faults all of them share.

### The two runs

The script never reacts to a reply, so a reply's delay changes nothing on the device: it only sets
when the client receives it. What the device does depends only on when requests arrive and on the
disconnects. So for each **arrival choice** (when each request attempt reaches the device, or that
it is lost, plus an optional duplicate):

1. **First run.** Requests arrive as chosen; the device runs. Its sends and their times do not
   depend on reply delays.
2. **Reply pairing.** For each reply name and request id, the device's sends are paired with the
   logged receives by a **minimum-fault assignment**.
   - A receive is either the first copy of a send or a duplicate of a send already received.
   - The order may change, because each message has its own delay.
   - A send with no receive was lost.
   - Every assignment that ties for the fewest faults is kept.
   - A receive no device send can explain is **unexplained**: the link can lose and copy what the
     device sent, not invent it.
   - Pairing in time order instead would read a lost `DONE` followed by a normal one as one long
     delay.
   - A key with more than 6 sends or receives is paired in order (counted in the result).
3. **Check run.** Each plan is run and judged like any driven replay. There is one check run per
   tied pairing, at most 8 per choice.

**Disconnects are facts.** `incident text` writes the link's disconnects and reconnects as `link
down` / `link up` lines. The rules turn them into client `state` events (`DISCONNECTED`,
`CONNECTED`), and the fit uses them as the plan's disconnects.
- A resend logged in the same millisecond as the reconnect runs after it.
- A request sent just before a logged disconnect is lost with it, because the link drops what is
  in flight. This is not a fault.

### Faults and the usual delay

**What counts as a fault:** a drop, a duplicate, or a delay above the **limit** (in either
direction).

**What does not count:**
- a message lost in a logged disconnect, when the delay it needs is within the limit;
- a reply still in flight at the end of the log.

**Identity.** A fault is identified by its kind and `(dir, msg, req_id, k)`. Its value (the delay,
or the extra delay of a duplicate) is not part of the identity. Two explanations with the same
faults are the same explanation.
- The values they differ in (another reply pairing, another arrival point) are kept as the range
  seen per fault, lowest to highest, for example `delay s2c ACK r-0001 k0 2.035-2.510s`. The value
  is part of what the log leaves open.
- **The range is what was seen, not what is possible.** It spans the values in the minimal
  explanations found, at the option points tried. A value outside it is not shown to be
  impossible, and neither is one between the points.
- Each end of a range is a value that reproduced the whole log. Up to 4 other arrival choices
  with the same faults are run on the whole log for this.
- The range is per fault. The ends of two faults need not go together: the low end of one may
  come from another pairing than the low end of the other.

**`--usual-delay C2S S2C`** sets the usual delay per direction. A delay above it plus the tolerance
is a fault. For example, the hardware testbed uses 4 ms each (stage 1); with a 25 ms tolerance the
limit is 29 ms.

**Without `--usual-delay`** (simulator logs):
- arrivals default to the range's low end (10 ms for the lift and the turntable);
- the limit is the range's high end (1,500 ms for both);
- so any delay inside the range is normal, and only drops and duplicates are faults.

**Default arrival.** Each attempt arrives at the time closest to `send + usual` at which:
- its own delay is within the limit, and
- the delays of the replies it caused are within the limit.

The interval comes from a probe run with every attempt at the minimum delay. Replies are numbered
by the device sends that reached the link.
- If no such time exists, the attempt arrives at `send + usual`.
- An attempt sent while the link was down is lost at once.
- The ranges (`--c2s-delay`, `--s2c-delay`, `--dup-extra`, default the link profile) stay as wide
  as given. The default arrival is the usual value, not the middle of the range: with a 0–5 s range
  the middle put retries after the move had ended, and invented `DONE` drops.

### The search

**Units.** The search units are the anomalous commands, plus any command with a receive the default
leaves unexplained. A command is anomalous when it:
- was sent more than once;
- closed with `ERROR`, or got an `ERROR` reply;
- got the same reply twice;
- got its `ACK` more than 50 ms after the send;
- had an `ACK`→`DONE` gap more than 50 ms over the log's median gap.

**Polls with a fault are units too.** A poll whose reply the default reads as lost or repeated, or
leaves unexplained, is searched like a command. A poll does not change the device, so a lost request
and a lost reply look the same from the client. The search finds both and reports the poll among
the alternatives: `s-0008: drop c2s STATUS k0 | drop s2c STATUS_REPLY k0`. A repeated reply ties with a
repeated request when the device state is the same at both times.
- Poll replies are left out of the match, so an explanation that leaves a logged reply of the unit
  unexplained is not taken: a lost request does not explain a reply that was received.
- A poll the option space cannot explain keeps the default, as all polls did before, and its
  unexplained reply is reported apart.

Attempts of other commands, and the other polls, keep the default.

**Options per attempt:**
- the default;
- dropped;
- arriving at its minimum delay;
- arriving just after a device event in its delay range;
- arriving at an **anchored** time, where a logged reply of its request would have the usual delay
  (using the device's lag after an arrival, read off the run);
- for each logged reply of its request, arriving at the time nearest the usual delay at which both
  the attempt's delay and that reply's delay are within the limit. This holds whichever send the
  reply is paired with, so it covers a retry answered before the first attempt (testbed-02 R04);
- arriving just after a logged disconnect begins;
- duplicated, with the copy at an anchored time.

**How a unit is searched:**
- **Order.** Choices run in order of how many attempts leave the default.
- **Skipping.** A choice whose request-side faults alone exceed the fewest faults found so far is
  skipped. The reply side can only add faults, so the skipped choices cannot tie.
- **What "minimal" means.** When the unit's choices are exhausted, every explanation with the
  fewest faults in this option space has been run.
- **`--plus-one`.** The search continues to one fault more, as a diagnostic. After the fit, every
  command outside the units (with no fault in the minimal explanations) is also searched for one
  fault more, on the whole log, with the units at their first explanation. So a log the default
  explains (no unit) still has an `f*+1` set. Polls without a fault are not searched for it.
- **Judging.** Each unit is judged:
  - from a quiet point before its first send;
  - up to the next unit's first send, or the end of the log; the cut log's horizon is the cut;
  - with the earlier units fixed at their first minimal explanation.
- **Arrivals after the cut** are not offered. What they cause would not be seen, so they would
  look free of reply faults.

**Combining the units:**
- Each unit's explanations are recounted on the whole log, with the other units at their first
  explanation.
- The combinations of the units' sets are run on the whole log: all of them when there are at most
  50, otherwise the first.
- If a unit or a combination fails, the units are searched together on the whole log.

**Caps.** `--fit-runs` (default 2000) caps the fit. Each unit gets a fair share of what is left,
with some kept for the whole-log runs. A choice costs one run plus its check runs. `--branch-runs`
caps the branch check.

**Determinism.** The same log gives the same result: options and choices come in a fixed order.

### Result

- **Reproduced:** at least one explanation reproduces every receive.
  - `minimal shown` holds when every unit's choices were exhausted and every combination run
    reproduced. Otherwise the set is the best found and the report says so.
  - With `--plus-one`, the count at one fault more is shown as complete or not.
- **Unexplained:** a receive no choice explains. Only this kind can be read as evidence about the
  device. It is reported in two cases:
  - nothing with that request id was ever sent;
  - every choice of a unit was run, every earlier unit reproduced, and the receive stays
    unexplained. A unit that started from a state no explanation of the earlier commands gives
    proves nothing.
- **Incomplete** (`cap`): nothing reproduced within the cap. What stays unexplained is a limit of
  the fitter, not evidence about the device.

**Report:**
- the fewest faults `f*`, and the number of explanations with that many (and with `--plus-one`, with
  one more);
- **common to every minimal explanation:** faults in every explanation with `f*` faults, each with
  its value range. Common is not the same as true: when the real faults are not the fewest, a
  common fault can be wrong (testbed-01 T14 and T17, testbed-02 N01, N02 and R03);
- **alternatives (the minimal explanations differ):** per request id, the alternatives, e.g.
  `r-0002: dup c2s MOVE_DOWN k0 | dup s2c ACK k0`;
- receives fitted;
- explained by loss: link faults. A device that does not send a reply looks the same as a lost
  reply, so this line is not evidence that there is no defect;
- duplicates, late messages, losses to logged disconnects, in flight at the end;
- unexplained receives, with poll replies counted apart and each log line named;
- **observed slow round trips** (from the log, not the fit; see below);
- explanations matching every receive, by violated contracts;
- with `--branches`, attempts with a branch point;
- with `--random-check N`, the random-arrival check (below);
- runs used.

`--fit-out PATH` writes all of this as JSON, with every unit's explanations. Fault lists are under
`common` and `alternatives`; each fault has `seen_range_us` (`[lowest, highest]` as seen in the
explanations found, or null for a drop).

**Observed slow round trips.** For each request attempt (polls left out), the fit looks at the gap
from its send to the first `ACK` of that id received before the next attempt.
- A gap longer than the log's median gap by more than the limit is listed, with the request id and
  the excess.
- This is computed from the log alone and kept apart from the common faults and the alternatives.
- It exists because the limit applies per direction. A request about 40 ms late can be split into
  a request and an `ACK` that are each within a 29 ms limit, so it is no fault. Its round trip is
  still 40 ms over the median.

**Random-arrival check (`--random-check N`, for a reproduced fit).** N draws, each redrawing one
command's attempts at random: dropped, near the fitted arrival (±60 ms), inside the interval its
replies allow, or anywhere in the range, sometimes with a duplicate. The other attempts keep the
reported plan's arrivals. A draw that reproduces the log with fewer faults than `f*` means the option
points missed a smaller explanation, and the report counts such draws. It works on any log, real
ones included. It is a check, not a proof: no draw finding fewer does not show `f*` is the minimum.

**Device models (`--models M1,M2,...` or `--models device`).** The log is also fitted under each
listed device defect model of the system (its published defects whose description starts with
`device:`), with the same settings, and the fewest faults each needs is compared with the correct
model's. Client defects are not offered: in driven replay the client is the script.
- **A defect model explains with fewer faults** when its fit is settled (reproduced, minimal set
  complete, and with `--random-check` no draw found fewer) and the correct model's fit is
  unexplained, or settled with more faults.
- **A tie is no accusation.** A defect is a heavier claim than a link fault.
- **The accusation is a set.** Every defect model with the fewest faults among those that explain
  with fewer is named: `defect suspected: M1 or M2`. The log does not choose between them, as with
  alternative faults.
- **A defect model that does not reproduce is not a candidate:** neither one that ends
  `unexplained`, nor one the run cap ends before anything reproduced. The second is a practical rule,
  not a proof: more runs might reproduce it with fewer faults. The report names every fit the cap
  ended (`ended by the run cap: ...`), so a reader sees what a "no accusation" rests on.
- **Undecided:** a defect model that reproduced but is not settled (its minimal set is not shown, or a
  random draw found fewer faults), or one that reproduced while the correct model's fit is not
  settled (and not unexplained). Undecided is not an accusation. With no accusation and an
  undecided model, the verdict is `undecided`.
- The report gives each model's `f*` (or status), the verdict, the difference in faults (none when
  the correct model is unexplained) and the fits the cap ended. `--fit-out` adds `models`, with
  `capped` and `capped_count` and each model's whole fit under `fits`.
- **What it does not see:** a defect that shows only in the content of poll replies (for the lift,
  M5) never changes the fewest faults, because poll replies are not compared.
- **What one log cannot tell:** a device that skips a reply once looks exactly like a lost reply. The
  defect model needs one fault fewer, and a real loss at that place gives the same log. Telling them
  apart needs repeated runs (a defect fails the same way every time, a loss does not), which this
  comparison does not do.

**More than one violation outcome.** A client log may fit explanations that differ inside the
device: one with a contract violation and one without. Two development logs did exactly that.
- Without `--expect` the fit does not choose between them: "more than one violation outcome fits
  the log: none is chosen".
- **The number of matching explanations is not their likelihood.**

**Branch points** (`--branches`, for a reproduced fit): each arriving command attempt is moved to
just after every device event inside the interval its replies allow. If some move stops the fit
reproducing, the device's behaviour depends on an arrival time the log does not fix. That is where
a device defect can hide.

**Windows (`--window auto` or `--window T0 T1`).** A window is also fitted on its own.
- The script stops at the window's end, and receives before its start are not judged.
- Only commands first sent inside the window are searched.
- `auto` picks windows around the anomalous commands above and around logged disconnects. Each
  window runs from 1 s before to 1 s after, and overlapping windows are merged.

**What "minimal" does not mean:**
- **The fewest faults is a choice, not the truth.** A log whose real faults are not the fewest is
  always misread. One example is a request duplicate plus a lost `ACK`, which reads as one late
  `ACK`.
- **"Every minimal explanation" holds within the option points above.** It is not a statement over
  every real-valued timing. A test draws random arrivals off those points and checks that none
  explains a short log with fewer faults, and `--random-check` does the same on any log; that is
  not a proof.
- **Copies are anchored only.** A duplicate copy is placed only at anchored times, on the reasoning
  that a copy matters through the reply it causes. A device whose copies change state would need
  more points.
- **Polls without a fault keep the default.** A poll with a fault is a unit, and its lost request
  and lost reply are both reported.

**Unexplained as evidence.** With a correct device model, a receive the model sends under no
arrival choice is evidence of a device defect, without naming one.

## Development record of `--fit` (not a result)

The record below is for the first design, which used moves and a midpoint first choice. The
minimal-explanation design replaced it after testbed-01.

This was tuned on the 17 driven-01 logs, which are now development material. None of these numbers
is a measurement.

- **Predicted before the runs:** 10–13 reproduced at the first choice, 15–17 with moves.
- **Observed:** 0 at the first choice and 5 with moves (5/17 at µs and at ms). All 5 also matched
  the expected contracts. Of the rest, 7 stopped with no improving move and 5 reached the run cap.
- **For comparison:** synthetic lift runs with frequent drops, duplicates and disconnects
  reproduced 5 of 6, two of them at the first choice.
- **What holds:** with the hidden run's true request arrivals, the computed reply delays reproduce
  every receive exactly (tested). The reply side is solved; what remains is choosing whether and
  when requests arrived.
- **Four bugs were found and fixed on these logs:**
  1. Poll replies were left out of the score, which threw away evidence about arrivals.
  2. The arrival interval lacked the lower bound that a `DONE` gives.
  3. An `ACK` caused by another attempt was counted in the first attempt's bounds.
  4. Device sends lost while the link was down were counted when numbering logged receives.
- **Two hypotheses for the remaining failures:**
  1. Single moves stall when several attempts' arrivals or losses must change together.
  2. A client log can fit explanations that differ inside the device: two logs first fitted
     without the expected violation.
- **The pool logs are adversarial.** They were picked because they reach rarely-hit mutants, and
  hold up to 18 faults in 90 s. Field incidents usually hold one or two. The next step is real logs
  from the testbed, not more tuning on these.
- **Not tried yet (held until real logs are seen):** build the device's state trajectory from the
  poll replies first, and work request arrivals back from it, instead of moving arrivals one at a
  time.

## What a client-side log does not decide

A client-side log shows a round trip's total, not its split. A device-side defect, however, can
show or hide depending on when a command reached the device. `--sensitivity` measures this for a
reproducing plan:

1. For each logged `ACK`, move the split to each extreme: the request's delay at its minimum, then
   at its maximum.
2. Keep the `ACK`'s receive time and the receive times of the request's later replies (`DONE`,
   `ERROR`) unchanged, then run again.
3. If an extreme stops the reproduction, the outcome depends on something the log does not say,
   and the round trip counts as sensitive.

The count is a first, concrete measure of how ambiguous a log is.

## Limits

- **The client's view of a disconnect can come late.** A real client may learn of it only after a
  timeout, so its logged `link down` is later than the real one. Messages in between are then
  explained as losses.
- **The fit's units are searched one after another.** A log whose commands interact beyond what
  the combination check catches is searched jointly, which costs runs; a long, faulty log can end at
  the cap with the minimal set not shown.

- **Client side only, one source.** A device-side log, or a log that starts in the middle of an
  operation, needs a start state for the device. The device starts in its initial state at the
  log's first event.
- **A defect in the client becomes a recorded fact.** The script replays what the client did, so
  the simulation cannot contain a client-side defect. Such a defect shows as a contract violation
  on the recorded events. Only device-side defects need the model to differ.
- **Reply pairing is searched only for small keys.** A reply key with more than 6 sends or
  receives is paired in time order.
