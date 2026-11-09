# Rules file schema (replayspect.rules/1)

`replayspect ingest LOG --rules RULES --out TRACE` reads a text log and writes a trace file
([trace-schema.md](trace-schema.md)). The rules file says how. It is the only thing that depends
on the log's line format: the same events in another format need only another rules file. No
model is involved.

```bash
python3 -m replayspect ingest client.log --rules client.rules.yaml --out client.jsonl
# ingest client.log with rules lift-client-ros (client.rules.yaml)
# entries 9 (blank lines 1): events 6, ignored 1, unmatched 2 -> client.jsonl.unmatched.txt
# flagged 1: out_of_order 1, out_of_tolerance 0 (tolerance 5000us)
# clock_step suspected 0
# time 0 is 2026-11-10T08:00:00.000000+09:00; events 0.000000s..5.021866s
# trace: 6 events -> client.jsonl
python3 -m replayspect rewind client.jsonl --window 0 10s
```

Two complete examples, one log in two line formats, are in `tests/data/ingest/`.

## Example

Log (ROS 2 style):

```text
[INFO] [1794265200.000000] [lift_client]: TX MOVE_UP req=r-0001
[DEBUG] [1794265201.000000] [lift_client]: TX STATUS req=s-0001
[DEBUG] [1794265202.342059] [lift_client]: RX STATUS_REPLY req=s-0001 state=MOVING_UP
[INFO] [1794265202.338764] [lift_client]: RX ACK req=r-0001
[INFO] [1794265205.021866] [lift_client]: result r-0001 DONE cause=reply
```

Rules:

```yaml
schema: replayspect.rules/1
name: lift-client-ros
system: lift.v0
actor: client
clock:
  format: epoch
  unit: s
  timezone: "+09:00"
  tolerance: 5ms
entry:
  pattern: '^\[(?P<level>[A-Z]+)\] \[(?P<time>[0-9.]+)\] \[(?P<module>[^\]]+)\]: (?P<text>.*)$'
  continuation: '^\s'
rules:
  - name: heartbeat
    match: '^heartbeat'
    ignore: true
  - name: send
    where: {module: lift_client}
    match: '^TX (?P<msg>[A-Z_]+) req=(?P<req>\S+)$'
    event: {kind: send, name: '{msg}', req_id: '{req}'}
  - name: recv
    match: '^RX (?P<msg>[A-Z_]+)(?: req=(?P<req>\S+))?(?: state=(?P<state>[A-Z_]+))?$'
    event: {kind: recv, name: '{msg}', req_id: '{req?}', data: {state: '{state?}'}}
  - name: result
    match: '^result (?P<req>\S+) (?P<res>DONE|ERROR) cause=(?P<cause>\w+)$'
    event: {kind: handle, name: '{res}', req_id: '{req}', data: {cause: '{cause}'}}
```

Trace (line 4 was logged 3.3 ms before line 3's time, within the tolerance):

```json
{"contracts":null,"origin":"2026-11-10T08:00:00.000000+09:00","plan":null,"schema":"replayspect.trace/1","seed":null,"slice":null,"source":"adapter:text","system":"lift.v0","type":"header","until_us":null}
{"actor":"client","fidelity":"exact","kind":"send","log":{"line":1},"name":"MOVE_UP","req_id":"r-0001","seq":0,"source":"adapter:text","t_us":0}
{"actor":"client","fidelity":"exact","kind":"send","log":{"line":2},"name":"STATUS","req_id":"s-0001","seq":1,"source":"adapter:text","t_us":1000000}
{"actor":"client","fidelity":"exact","kind":"recv","log":{"flags":["out_of_order"],"line":4},"name":"ACK","req_id":"r-0001","seq":2,"source":"adapter:text","t_us":2338764}
{"actor":"client","data":{"state":"MOVING_UP"},"fidelity":"exact","kind":"recv","log":{"line":3},"name":"STATUS_REPLY","req_id":"s-0001","seq":3,"source":"adapter:text","t_us":2342059}
{"actor":"client","data":{"cause":"reply"},"fidelity":"exact","kind":"handle","log":{"line":5},"name":"DONE","req_id":"r-0001","seq":4,"source":"adapter:text","t_us":5021866}
```

For the lift and the turntable, use the event names and `data` keys their simulated client
writes (`send`/`recv` with the message name, `data.state` on a status reply, `handle` with
`data.cause` for the client's result). Then a later step can compare the log with a simulated run
directly.

## Top level

| Key | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `replayspect.rules/1`. |
| `name` | yes | Name shown in the summary. |
| `system` | no | The trace header's `system` (`lift.v0`). Null when absent. |
| `actor` | no | Default `actor` of every event. Without it, every rule's event names its own actor. |
| `clock` | yes | How to read timestamps; see below. |
| `entry` | yes | How to split a log entry into fields; see below. |
| `rules` | yes | The rules, a non-empty list. The first rule that matches an entry decides it. |

Unknown keys anywhere are an error.

## clock

| Key | Meaning |
| --- | --- |
| `format` | `epoch` (a number), `iso8601` (Python's `datetime.fromisoformat`, with or without an offset), or a strptime pattern such as `"%Y-%m-%d %H:%M:%S.%f"`. |
| `unit` | `epoch` only: `s` (default), `ms`, `us` or `ns`. Times are kept in whole microseconds; finer digits are cut off. |
| `timezone` | A UTC offset (`+09:00`, `Z`) or a time zone name (`Asia/Seoul`). Used for timestamps that carry no offset, and to show times. |
| `tolerance` | How far back a line may step before it is `out_of_tolerance` (see Order). A time: `5ms`, `0.005s`, `5000` (µs). Default 0. |
| `origin` | Optional: the wall-clock time of `t_us = 0`, ISO 8601. Default: the earliest event. An event before it is an error. |

**Ingest never guesses a time zone.** A strptime pattern without `%z` needs `timezone`, or the
rules file is refused. An `iso8601` timestamp without an offset needs `timezone`, or that line is
an error. `epoch` times are absolute.

The trace header's `origin` records the wall-clock time of `t_us = 0`, shown in `timezone` (UTC
when none is given). Ingest does no clock correction: no offset between two logs' clocks, no
drift. That belongs to driven replay (WP5b).

## entry

| Key | Meaning |
| --- | --- |
| `pattern` | A regular expression for one entry, matched from its start. Named groups become fields every rule can use. It must have the timestamp group. A group named `text` is the part the rules' `match` looks at; without one, rules look at the whole entry. |
| `time` | The timestamp group's name. Default `time`. |
| `continuation` | Optional regular expression. A line it matches joins the entry before it (with a newline), for tracebacks and other multi-line entries. The entry's line number is its first line's. Without it, every line is one entry. |

The input is UTF-8; a line that does not decode is an error naming its line number. A trailing
CR is removed from every line, so CRLF logs read the same as LF logs. Blank lines are skipped and
counted.

## rules

Each rule:

| Key | Meaning |
| --- | --- |
| `name` | Required, unique. Errors and nothing else name it. |
| `where` | Optional mapping from `entry.pattern` groups to regular expressions. Each must match its group's whole text. |
| `match` | Optional regular expression, searched in the `text` group (or the whole entry). Its named groups add to the entry's. `^` and `$` match at line ends. Without `match`, the rule takes every entry that passes `where`. |
| `ignore` | `true`: an expected line that is not an event (a heartbeat). Counted as ignored. No `event`. |
| `event` | The event to write; see below. Required unless `ignore`. |

**Priority:** the rules are tried top to bottom, and the first one whose `where` and `match` both
fit decides the entry: it becomes that rule's event, or is ignored. Ignore rules are in the same
list, so their place decides whether they win.

An entry that `entry.pattern` does not match, or that no rule takes, is **unmatched**. Unmatched
entries are counted in the summary and listed, as `line: text` with continuation lines indented,
in `--unmatched PATH` (default `TRACE.unmatched.txt`, written only when there are any). They are
never silently dropped.

### event

| Key | Meaning |
| --- | --- |
| `kind` | Required: `send`, `recv`, `handle`, `effect`, `state` or `fault`. |
| `name` | Required, non-empty. |
| `actor` | Overrides the top-level `actor`. |
| `req_id` | Optional. Left out, or `{g?}` with no match: the event has no request id (null). Inferring a request id from other fields is not ingest's job. |
| `data` | Optional flat mapping of keys to values. `link` is reserved for channel metadata. |

Values are templates over the entry's groups:

- `{g}`: the group's text. Text around placeholders is kept: `'r-{n}'`.
- `{g|int}`, `{g|float}`: the group converted (finite numbers only). The whole value must be the
  placeholder.
- `{g?}`: the whole value; when the group took no part in the match, the field is left out
  (`req_id` becomes null).
- `{{` and `}}`: literal braces.
- A non-string YAML value (`3`, `true`) is written as it is.

**When every `data` value is left out, the event has no `data` field.** A template that names a
group neither `entry.pattern` nor `match` defines is an error in the rules file.

## Order and flags

A trace's times never decrease ([trace-schema.md](trace-schema.md)), but log lines can be written
out of time order (several threads, buffered output, a clock that was set back). Ingest keeps
every event and its logged time:

- Events are sorted by time. The sort is stable: equal times keep log order. `seq` is the sorted
  position; `log.line` is the line in the log.
- An event whose time is earlier than an event logged before it is flagged in `log.flags`:
  `out_of_order` when it is at most `clock.tolerance` earlier, `out_of_tolerance` when it is
  more.
- **Clock step:** a run of at least 3 consecutive `out_of_tolerance` events (in log order) is
  reported in the summary as a suspected clock step, with its line range and how far back it
  went. A lone late line is not. The summary keeps them apart because they mean different things:
  a late line is one event out of place, a step means every line after it is on a shifted clock.
  Ingest does not correct either. A clock that jumps forward only leaves a gap and is not
  detected.

`rewind` shows a flagged event's line and flags (`[log line 4: out_of_order]`) and counts the
flags in its summary.

## Errors

A bad rules file fails before the log is read: unknown key, bad regular expression, unknown
event kind, a template with an unknown group or a misplaced `|int`, `?` or brace, a format that
would need a guessed time zone, a duplicate rule name. The message names the rules file and, for a
rule's problem, the rule.

A matched log line that cannot be converted fails with the log's name, the line number and the
rule: a timestamp the clock format cannot read, a value `|int` cannot convert, an event before
`clock.origin`. `ingest` exits with status 2 and writes nothing.

## Versioning

Adding an optional key is a minor change. Changing or removing one is a new major
(`replayspect.rules/2`).
