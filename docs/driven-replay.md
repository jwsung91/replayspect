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

- **Client side only, one source.** A device-side log, or a log that starts in the middle of an
  operation, needs a start state for the device. The device starts in its initial state at the
  log's first event.
- **A defect in the client becomes a recorded fact.** The script replays what the client did, so
  the simulation cannot contain a client-side defect. Such a defect shows as a contract violation
  on the recorded events. Only device-side defects need the model to differ.
- **The pairing of replies to attempts is a heuristic.** A lost reply shifts it; the search then
  has to correct it.
