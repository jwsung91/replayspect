# Fault plan format

A plan is a JSON object that says which network faults happen in one run.
Only the faults in the plan happen; there are no other faults. Every
message's delay is drawn at random from the allowed range unless the plan
sets it.

```json
{
  "base": "random",
  "delays": [
    {"dir": "s2c", "msg": "ACK", "req_id": "r-0001", "k": 0, "delay_us": 1400000}
  ],
  "faults": [
    {"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-0001", "k": 0, "drop": true},
    {"dir": "s2c", "msg": "DONE", "req_id": "r-0002", "k": 0, "dup_extra_us": 2500000}
  ],
  "disconnects": [
    {"t_us": 12000000, "duration_us": 1500000}
  ]
}
```

## Fields

- `base`: must be `"random"`.
- A message is identified by four fields:
  - `dir`: `"c2s"` (client to device) or `"s2c"` (device to client)
  - `msg`: the message name, for example `"MOVE_UP"` or `"ACK"`
  - `req_id`: the request id, for example `"r-0003"`
  - `k`: which send of this `(dir, msg, req_id)` it is, starting at 0. A
    resend of the same command is `k: 1`, the next one `k: 2`. A device that
    answers the same request again also counts up.
- `delays`: set the delivery delay of a message, in microseconds.
- `faults`: each entry is either a drop (`"drop": true`) or a duplicate
  (`"dup_extra_us"`: the copy arrives that much later than the original).
- `disconnects`: the connection goes down at `t_us` (microseconds from the
  start of the run) for `duration_us`.

All numbers are integers in microseconds. Unknown fields, missing fields and
wrong types are rejected. The allowed ranges and the maximum number of
faults per plan are returned by `describe`.

## What you get back

For every run: the timeline of the run (without status polling), the
contracts that were violated with details, and which plan entries had no
effect (for example a fault on a message that was never sent, or a fault on a
message that was lost anyway because the connection was down). A rejected
plan still uses up one run of the budget.
