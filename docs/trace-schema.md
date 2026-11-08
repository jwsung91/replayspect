# Trace file schema (replayspect.trace/1)

A trace file is UTF-8 JSON Lines: an optional header line, then one event per
line. The simulator (`replay --trace-out`) and slices (`rewind --full`) write
this format, and so will log adapters (WP5). Every reader (`rewind`, the
judge, later `ingest` and `vary`) reads only this. Writers emit canonical
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

Writers always write `fidelity` and `source` on every event, so each line
describes itself without the header.

Kind-specific `data` is what the example systems write. Adapters may add keys.

- `state` has `from` and `on`.
- `handle` has `msg_req_id` and `cause`.
- `send` and `recv` have `link {n, k, delay_us, copy?}`.
- `fault` has `dir`, `msg` and `k`, plus either `reason` or `extra_us`/`duration_us`.

## Digest

The trace digest is SHA-256 over the canonical JSON Lines (sorted keys, no
spaces) of the **event core** only: `seq, t_us, actor, kind, name, req_id,
data`. The header, `fidelity` and `source` are not part of it.

- Repro files written before this schema keep their digests (principle 2).
- The digest says *what happened*. Fidelity and source say *how we know it*.

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
  at their original `seq`. A slice holds only part of the run, so contracts
  whose events were cut away show as *not exercised*.

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
mutant. WP4 adds the option that writes such files, together with tests that
enforce both rules. WP2 only records the rule here.

## Versioning

Adding an optional field is a minor change (same major). Changing or removing
a field is a new major (`replayspect.trace/2`, `schemas/trace-2.schema.json`).
