# Trace file schema (replayspect.trace/1)

A trace file is UTF-8 JSON Lines: an optional header line, then one event per
line. The simulator (`replay --trace-out`), slices (`rewind --full`) and the
text log adapter (`ingest`, [rules-schema.md](rules-schema.md)) write this
format. Every reader (`rewind`, the judge, later `vary`) reads only this. Writers emit canonical
lines: keys sorted, no spaces. Readers accept any JSON formatting.

The machine-readable form is [`schemas/trace-1.schema.json`](../schemas/trace-1.schema.json)
(JSON Schema 2020-12, one line at a time). The rules that span lines are
listed under [Reading rules](#reading-rules).

## Header (optional first line)

```json
{"type": "header", "schema": "replayspect.trace/1", "system": "lift.v0", "source": "sim",
 "seed": 65, "plan": {"sha256": "fec97e…", "repro": "repros/lift.v0-M4-C3-seed65.json"},
 "contracts": {"path": "contracts/lift.v0.yaml", "sha256": "ca461e…"}, "until_us": 90000000,
 "slice": null}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `type` | `"header"` | Marks the line as the header. Event lines have no `type`. Required. |
| `schema` | string | `replayspect.trace/<major>`. A reader rejects a major version it does not know. Required. |
| `system` | string or null | The model the trace belongs to (`lift.v0`). Null when no model is known. |
| `source` | string | `sim`, or `adapter:<name>` (for example `adapter:text`). The default `source` of every event. Default `sim`. |
| `seed` | integer ≥ 0 or null | Simulator seed. Null for adapter output. |
| `plan` | object or null | `{"sha256": <digest of the canonical plan JSON>, "repro": <path as given, or null>}`. Identifies the fault plan without inlining it. Null for adapter output and for runs without a plan. |
| `contracts` | object or null | `{"path": <path>, "sha256": <file digest>}`. Default contract file for judging. The digest records which version of the file. Writers give the path relative to the working directory when the file is under it, otherwise absolute. Readers resolve a relative path against the working directory. |
| `until_us` | integer ≥ 0 or null | End of the run, and the default end time for judging. Null when unknown; judging then ends at the last event. Never before the last event. |
| `origin` | string, optional | Wall-clock time of `t_us = 0`, ISO 8601 with a UTC offset (`2026-11-10T08:00:00.000000+09:00`). Written by log adapters, so the log's own times can be recovered and two logs aligned later. Absent in simulator output. |
| `slice` | object or null | Set when the file is a cut of another trace: `{"window": [t0, t1] or null, "actors": [names] or null, "of": <digest of the full trace> or null}`. The window is inclusive and `t0 <= t1`. Null for a full trace. |

Mutants and implementation variants (`--variant`) are never in the header.
They are the hidden answers of the WP4 experiment. See
[Output meant for planners](#output-meant-for-planners).

Unknown header fields are ignored (minor additions). Unknown `schema` majors
are rejected.

## Events

```json
{"seq": 88, "t_us": 15677267, "actor": "device", "kind": "state", "name": "MOVING_UP",
 "req_id": "r-0003", "data": {"from": "MOVING_DOWN", "on": "MOVE_UP"},
 "fidelity": "exact", "source": "sim"}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `seq` | integer ≥ 0 | Position in the full trace. In a full trace: 0, 1, 2… in order. In a slice: the original positions, strictly increasing. |
| `t_us` | integer ≥ 0 | Virtual time in microseconds. Never decreases. |
| `actor` | non-empty string | Participant. Dotted names (`base.drive`, `turntable.device`) are reserved for composed systems (`contracts/system/`). |
| `kind` | one of six | `send`, `recv`, `handle`, `effect`, `state`, `fault`. |
| `name` | non-empty string | Message, effect, state or fault name. |
| `req_id` | string, optional | The request the event belongs to. |
| `data` | object, optional | Plain JSON (no NaN, string keys). Reserved key: `link` (channel metadata). |
| `fidelity` | `exact` or `reconstructed` | `exact`: recorded by the simulator or read from a log. `reconstructed`: filled in by a model (WP7). Default `exact`. |
| `source` | string | Who produced this event: `sim` or `adapter:<name>`. Defaults to the header's `source`, else `sim`. |
| `log` | object, optional | Where a log adapter read the event: `{"line": n}`, the log line (1-based), plus `"flags"` when the event was logged out of time order: `out_of_order` (within the rules' tolerance) or `out_of_tolerance`. On a `reconstructed` event written by driven replay (`drive --trace-out`), `log.line` is the log line the event was matched to. Absent in simulator output. |

Writers always write `fidelity` and `source` on every event, so each line
describes itself without the header. Adapters also write `log`.

An adapter keeps every event's logged time. Times in a file never decrease, so
events logged out of time order are sorted (stably) and flagged in `log.flags`,
not dropped or corrected ([rules-schema.md](rules-schema.md#order-and-flags)).

Kind-specific `data` is what the example systems write. Adapters may add keys.

- `state` has `from` and `on`.
- `handle` has `msg_req_id` and `cause`.
- `send` and `recv` have `link {n, k, delay_us, copy?}`.
- `fault` has `dir`, `msg` and `k`, plus either `reason` or `extra_us`/`duration_us`.

## Digest

The trace digest is SHA-256 over the canonical JSON Lines (sorted keys, no
spaces) of the **event core** only: `seq, t_us, actor, kind, name, req_id,
data`. The header, `fidelity`, `source` and `log` are not part of it.

- Repro files written before this schema keep their digests (principle 2).
- The digest says *what happened*. Fidelity, source and log say *how we know
  it*: a comment line added to a log moves line numbers but not the digest.

## Reading rules

- **No header:** the file reads exactly as before. `source` defaults to
  `sim`, `fidelity` defaults to `exact`, and there are no contract or end-time
  defaults.
- **Header present:** `rewind` takes its `--contracts` and `--end` defaults
  from the header.
  - A command-line value overrides the header's value. The output then says
    so, for example `judged until t=95.000000s (given; differs from header: 90.000000s)`
    or `contracts file: x.yaml (given; differs from header: contracts/lift.v0.yaml)`.
  - If the header's contract file has changed since the trace was written, or
    is missing, the output says that too. A missing file means the trace is
    not judged.
- **Where the header may appear:** only on line 1. A `type` other than
  `header` is an error.
- **Order:** times never decrease. `seq` is 0, 1, 2… unless the header has a
  `slice`; in a slice `seq` must strictly increase.
- **Errors** name the file and the line number.
- **Judging a slice:** the judge renumbers the events and reports violations
  at their original `seq`. A slice holds only part of the run:
  - **The end time.** A slice cut with a window is judged until the window's
    end when that is earlier than the header's `until_us`, and the output
    says so: `judged until t=60.000000s (slice window end; the run went on to
    90.000000s)`. Events after the window were cut, not missing, so a
    deadline past the window's end is not judged as passed. `--end` still
    overrides it.
  - **A cut start.** A window that starts after time 0 may have cut earlier
    events. Four things can then report a violation that did not happen:
    `state_machine` (the first state event's `from` meets no previous state),
    `count_le` (the bound events before the cut are not counted),
    `only_after` (the earlier `after` may be before the cut) and any
    contract that reads `last(...)` (null where the event was cut). Such
    contracts are *not judged* on that slice, and the output names them.
  - **Every other kind** is judged on the events kept. A cut can hide one of
    its violations but never make one, so the verdict is not symmetric:
    - a violation found in the slice is reported as a violation;
    - `at_most_once`, `exactly_once`, `at_most_one_open` and
      `mutually_exclusive` carry state from earlier events. On a slice with a
      cut start they can miss a violation whose proof is in the slice: the
      first occurrence, the first `start`, an earlier open or the other
      pattern was cut. When they find none, the status is *no violation in
      the slice (earlier events not seen)*, not *ok*;
    - `forbid` and `consistent` without `last(...)` look at one event at a
      time, so *ok* means no event in the slice breaks them.
  - **The window's end** needs no such status. Judging stops there, as at a
    rewind time, and the first line says so. A violation that only events
    after the window would prove is outside the slice.
  - A window that covers the whole trace (starting at time 0) cuts nothing
    at the start, and its verdicts read as for a full trace.
  - A contract none of whose trigger events is left shows as *not exercised*.
  - **Not handled yet:** a slice cut by actor only, when it removes a
    contract's other actor. No lift or turntable contract spans two actors
    today.

## Slices

`rewind --full PATH` writes the selected events (`--window`, `--actor`) as a
trace file. Its header is a copy of the source header with `slice` set to
the selection and `of` set to the digest of the full trace. Slicing a slice
narrows the recorded window and actors to their intersection and keeps `of`.
A selection that does not overlap the earlier cut is an error.

## Output meant for planners

The WP4 experiment gives a planner a partial log of a hidden failing run.
Several header fields would give the answer away:

- `seed`, `plan` and `contracts` identify the run and its fault plan.
- `slice.of` would let a planner check its own scenario's digest against the
  hidden trace, and so know whether it reproduced the run exactly. The engine's
  symptom judge must be the only judge of that.
- File names written by `search` carry the mutant and contract
  (`lift.v0-M4-C3-seed65.json`), and `plan.repro` repeats them.

So every trace file shown to a planner has a header with `seed`, `plan`,
`contracts` and `slice.of` set to null. Its file name must not mention a
mutant.

WP4 writes these files (`incident view`, and the `log` field of a bridge
session's `describe`; see [docs/experiments/bridge-01.md](experiments/bridge-01.md)).
A planner view also differs from an ordinary slice in four ways:

- `until_us` is null: with a clock offset, the run's end in the view's clock
  would give the offset away.
- `data.link` is removed from every event. It records `k`, the delay and
  whether a message is a duplicate copy, which a participant's own log does
  not know.
- `seq` is renumbered from 0. The original positions would show how many
  events of other participants happened in between.
- A view may add one constant clock offset to every time: one offset per
  view, never per event.

`incident view` refuses a file name that mentions the incident's mutant or
variant. Tests check both header rules and that no hidden value reaches the
planner.

The planner's **own runs** are shown by the same participant rule
(`incident.run_view`): only the logged participant's events, polls left out,
in the run's own clock. Here `data.link` is kept (shown as `k`, and on a
received message `sent` and `delay`), because it describes the planner's own
run, not the hidden one, and it is what turns "this line came 0.3 s early"
into a plan entry. The other participant's events and the link's fault events
are not shown, and violations are given as contract, `req_id` and time
without their details: otherwise the other side's behaviour, and with it the
defect, would be read off the planner's own runs.

## Versioning

Adding an optional field is a minor change (same major). Changing or removing
a field is a new major (`replayspect.trace/2`, `schemas/trace-2.schema.json`).

Minor changes so far:

- WP5a (text log ingest): the header field `origin` and the event field `log`.
  Readers that do not know them ignore them; simulator output does not write
  them, so its files and digests are unchanged.
