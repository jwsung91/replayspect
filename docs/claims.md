# Claims and `claim check`

## What a claim is

A **claim** says what goes wrong and when: a trigger and an effect, in one sentence. For example, "a
repeated request that arrives after the device answered it is acknowledged again". A claim is checkable
when it can be written as a **candidate contract**: a contract in the existing language
([design-v0.md](design-v0.md), "계약 DSL"), with `grade` and `source` saying where the rule comes from
(`grade: stated` means the protocol document says it; `source` gives the document, its lines and the
sentence).

A candidate does not become a contract by being written down. `claim check` runs before a person
looks at it, and tells whether it deserves that person's time. The person confirms or drops it. Only a
confirmed candidate goes into a contract file.

## The command

```bash
python3 -m replayspect claim check CANDIDATES.yaml \
    --incident S03-device.log --model S03-report.json \
    --incident other-incident.jsonl \
    --normal real-logs/ --normal-seeds 0-999 \
    --complete device:recv,send,state,effect \
    --out claim.json
```

- **Candidates:** a contract file, one or more contracts. Each needs `grade` and `source`. A file whose
  `protocol` is not the `--system` (default `lift.v0`) is refused.
- **Incidents** (`--incident`, repeatable): trace files (JSON lines, for example from `ingest` or
  `replay --trace-out`) or device logs (the testbed firmware's `# <millis> ...` lines). A file whose
  first non-empty line starts with `{` is read as a trace, anything else as a device log. None is
  needed: with no incident, only the normal corpus is judged. That is a false-positive check, and
  `passes` then says only that the candidate was exercised and never violated there.
- **Model result** (`--model`, optional, at most one per incident): the `replayspect device --out` report
  for the `--incident` just before it. Its correct model's first mismatch gives the request to compare
  with. No model runs inside `claim check`.
- **Normal corpus:** inputs where nothing is known to be wrong. One or both of:
  - `--normal`: trace files, device logs, or directories of them. A directory is read in name order,
    without subdirectories or hidden files.
  - `--normal-seeds N-M`: simulator seeds of the system's implementation with no defect, with the
    system's random link profile. Each seed is run and judged in turn.
- **`--complete`:** what the device logs log completely, as for `replayspect device`. It applies to every
  device log given, incidents and normal corpus alike. A candidate that refers to a device kind not
  declared complete is *not judged* on a device log: a missing line would read as an absent event.
- **Output:** text on stdout, and the full report as JSON with `--out` (a new file). Same inputs, same
  bytes. The exit status is 0 when every candidate passes, 1 otherwise, and 2 for bad input.

## What it reports

For each candidate:

- **On each incident:**
  - the status, using the same words as `rewind` and `device` (violated, ok, no violation in the slice,
    no violation in the keys judged, not exercised, not judged);
  - if violated, the first violation's request, time and detail, and every violation.
  - With a model result, it also gives the model's first mismatch (its request id, `model conforms` or
    `model not checked`) and `same_request`:
    - `yes` or `no`: whether the first violation's request is the first mismatch's request;
    - `not given`: no model result was given (it never reads as `no`);
    - `not violated`: the candidate was not violated on this incident.
- **On the normal corpus:**
  - how many inputs there were, and in how many the candidate was exercised;
  - the count of each status;
  - the inputs where it was not judged;
  - every violation (input, request, time, detail). Seeds are named `<system> seed <n>`.
- **The verdict:**
  - **`passes`:** violated on every incident given, exercised on the normal corpus, and no violation
    there.
  - **`fails`:** one or more of these, each given as a reason:
    - not violated on an incident (with its status);
    - violated on any normal input.

    A candidate not judged on an incident did not catch it.
  - **`untested`:** it caught every incident, but it was never exercised on the normal corpus. The
    reason says which: never exercised, or not judged on any normal input (with what was missing, such
    as a device kind not declared complete). The remedies differ. It could
    not have failed there. That is not the same as holding.
- **Every input is named with its sha256:** the candidate file, each incident, each model result and
  each normal file. For the normal files, it also gives the sha256 of the list itself: one line per file,
  `<sha256>  <path>` (two spaces), in the order read. Seeds are named by system and range.

### "Exercised"

A candidate is exercised on an input when its status judged something: violated, ok, no violation in
the slice, or no violation in the keys judged. For most kinds, this means one of its trigger events
occurred.

For `never_after`, a trigger event anywhere is too weak. The contract can only fail on an `event` that
comes after an `after` of its key. A corpus where every key has its `event` before its `after` exercises
the trigger without ever trying the rule. So for `never_after`, an input counts as exercised only if a
key that has an `after` also has **something later with the same key done by the actor of the `event`
pattern**: that actor was active on the request again, so the forbidden `event` had a chance to appear.
The report gives the counts summed over the normal corpus:
- `keys_with_after`;
- `after_then_event_actor`: the measure used for the verdict (`measure` in the report);
- `after_then_anything`: wider, reported beside it and not used for the verdict. It counts keys with
  anything later with the same key, of any actor and any kind.

For each of the two counts, the report also gives the number of inputs where it is above zero
(`inputs_after_then_event_actor`, `inputs_after_then_anything`).

On a device log, which holds only device events, the two counts coincide when the `event` is a device
event. On a simulator trace they do not. On seeds 0–99 of the lift, with the `event` `device.send(ACK)`
and the `after` `device.send(DONE|ERROR)`:
- every one of the 596 keys with an `after` has something later, because the client receives and
  handles the `DONE`. The wider count can never say `untested` on such a trace;
- 215 keys have something later by the device, in 94 of the 100 inputs. For each of them, the device's
  first later event is a `recv` of the request again: the situation where an `ACK` could wrongly appear.

**This measure is conservative.** An `event` nobody asked for needs no trigger. So an input where the
actor did nothing more on a request still showed that nothing unsolicited came, and that input is not
counted. `untested` therefore understates a little what the corpus showed, which is the safe direction.

## What the check proves, and what it does not

- **A candidate that passes is consistent with the data given.** It is not thereby true. The normal
  corpus can lack the situation where a correct device would break the rule. The candidate may also hold
  on these incidents for a reason other than the one the claim states.
- **`untested` is not a weak pass.** The normal corpus never gave the candidate a chance to fail.
- **One violation on a normal input fails the candidate.** The check does not weigh it, and it does not
  ask whether that input was really normal. A normal corpus with a defect in it makes good candidates
  fail.
- **`same_request: yes` connects the candidate to the model's first mismatch on that incident.** It does
  not show that the candidate explains the defect.
- **Not judged is not caught.** On a device log, a candidate needs its device kinds declared complete:
  the same rule as `replayspect device --contracts`, in one function. A log with an `error` line is not
  judged at all.
- **Reordered log lines.** Keys whose order a log adapter could not settle are not judged, as in `rewind`.
  A candidate that is not judged on an incident fails on it.
- **The check reads only the trace or the log.** What the device did but did not log is not seen.
