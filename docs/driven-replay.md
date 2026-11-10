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

`drive --fit` replaces search over delays with arithmetic. The script never reacts to a reply, so
a reply's delay changes nothing on the device: it only sets when the client receives it. What the
device does depends only on when requests arrive and on the disconnects. So:

1. **First run.** Requests arrive at chosen times; the device runs. Its sends and their times do
   not depend on reply delays.
2. **Fit.** Each device send is paired with a logged receive of the same reply and request id, in
   time order. Its delay is the logged receive time minus the send time.
   - A device send with no logged receive was lost (a drop).
   - A receive left over after its send was used is a duplicate copy.
   - A receive no device send can explain is **unexplained**: the link can lose and copy what the
     device sent, not invent it.
   - A send that would arrive after the log ends is left in flight.
3. **Check run.** The plan is run and judged like any driven replay.

**Disconnects are facts.** `incident text` writes the link's disconnects and reconnects as
`link down` / `link up` lines, and the rules turn them into client `state` events
(`DISCONNECTED`, `CONNECTED`). The fit uses them as the plan's disconnects. A resend logged in the
same millisecond as the reconnect runs after it.

**Request arrivals are the one unknown.**

- **First choice.** A probe run, with every attempt at the minimum delay, shows how long after an
  arrival the device sends each reply. Each logged reply bounds the arrival
  (`receive − delay max − lag ≤ arrival ≤ receive − delay min − lag`). Replies are numbered by the
  device sends that reached the link. The first choice is the middle of the interval all bounds
  allow.
- **Moves.** When something stays unexplained, the fit tries one move at a time, in a fixed order:
  1. drop an attempt, or let a dropped one arrive;
  2. drop every attempt of a request before the mismatch;
  3. move an arrival to just after a device event inside the attempt's delay range;
  4. duplicate an attempt, with the copy arriving just after a device event.

  The moves aim at the earliest unexplained receive, poll replies included. Attempts of the same
  request id come first, latest first. When everything is explained but the contracts differ,
  command attempts are tried earliest first.
- **Score.** The first move that lowers the score is kept. The score compares, in order:
  1. unexplained receives, polls left out;
  2. whether the check run's lines match;
  3. whether the violated contracts match;
  4. unexplained poll replies;
  5. link faults.

  Poll replies are not judged, but they show the device's state at an arrival.
- **Determinism.** The same log gives the same fit: candidates come in a fixed order and the first
  improvement wins.

**Ranges are parameters.** `--c2s-delay`, `--s2c-delay` and `--dup-extra` default to the system's
link profile, which suits simulator logs. A real serial link can answer in a few milliseconds,
below the profile's 10 ms minimum.

**Caps.** `--fit-runs` (default 120) caps the fit, and `--branch-runs` caps the branch check. The
report says when a cap was reached. A move evaluation costs one run, plus the check run when
nothing is unexplained.

**Report:**

- receives fitted;
- explained by loss: link faults. A device that does not send a reply looks the same as a lost
  reply, so this line is not evidence that there is no defect;
- explained by duplicate;
- in flight at the end of the log;
- unexplained, with poll replies counted apart and each log line named;
- with `--branches`, attempts with a branch point;
- runs used.

**Branch points** (`--branches`, for a reproduced fit): each arriving command attempt is moved to
just after every device event inside the interval its replies allow. If some move stops the fit
reproducing, the device's behaviour depends on an arrival time the log does not fix. That is
where a device defect can hide. This replaces `--sensitivity`. `--rtt` and `--sensitivity` stay
until the fit passes a measurement.

**Unexplained as evidence.** With a correct device model, a receive the model sends under no
arrival choice is evidence of a device defect, without naming one.

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
- **The fit changes one thing at a time.** A log that needs two arrivals or drops changed together
  can end unexplained or at the cap.

- **Client side only, one source.** A device-side log, or a log that starts in the middle of an
  operation, needs a start state for the device. The device starts in its initial state at the
  log's first event.
- **A defect in the client becomes a recorded fact.** The script replays what the client did, so
  the simulation cannot contain a client-side defect. Such a defect shows as a contract violation
  on the recorded events. Only device-side defects need the model to differ.
- **The pairing of replies to attempts is a heuristic.** A lost reply shifts it; the search then
  has to correct it.
