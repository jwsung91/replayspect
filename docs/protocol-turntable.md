# Turntable integration protocol (turntable.v0)

This document describes the system under test as its specification says it
should behave. It is given to planners (people or models) that try to break
the behavioural contracts by choosing network faults. It deliberately says
nothing about how the implementation under test might deviate.

## Parties

- **client**: the robot side. It drives the turntable.
- **device**: the turntable controller.

They exchange messages over a network link with delays, and the link may
lose, duplicate or reorder messages and may disconnect for a while.

## Messages

Every message carries a request id (`req_id`).

| Direction | Message | Fields | Meaning |
| --- | --- | --- | --- |
| client to device | `TURN_LEFT` | | turn the table 90 degrees to the left |
| client to device | `TURN_RIGHT` | | turn the table 90 degrees to the right |
| client to device | `STATUS` | | ask for the current state |
| device to client | `ACK` | | the request was received |
| device to client | `DONE` | | the turn finished |
| device to client | `ERROR` | `reason` | the turn was refused |
| device to client | `STATUS_REPLY` | `state` | the device state when the reply was sent |

Turn commands use ids `r-0001`, `r-0002`, ... in the order the client issues
them. Status polls use `s-0001`, `s-0002`, ...

## Device

The table has a position sensor every 90 degrees and three stop positions:
`LEFT` (-90), `INITIAL` (0) and `RIGHT` (+90). While it turns, the state
names the position it is heading for. States: `INITIAL`, `LEFT`, `RIGHT`,
`TURNING_TO_LEFT`, `TURNING_TO_INITIAL`, `TURNING_TO_RIGHT`. It starts in
`INITIAL`.

1. On a turn request the device first looks the `req_id` up in its result
   table. A known id is answered with the stored result again (`ACK` while the
   turn is in progress, `DONE` or `ERROR` with the same `reason` once it has
   finished), and nothing else happens. A new id is recorded as in progress,
   answered with `ACK`, and executed 50 ms later.
2. On execution the device checks the current state. A turn moves the table
   exactly one 90-degree step:

   | Current state | `TURN_LEFT` | `TURN_RIGHT` |
   | --- | --- | --- |
   | `INITIAL` | `TURNING_TO_LEFT`, then `LEFT` | `TURNING_TO_RIGHT`, then `RIGHT` |
   | `LEFT` | refused, reason `limit` | `TURNING_TO_INITIAL`, then `INITIAL` |
   | `RIGHT` | `TURNING_TO_INITIAL`, then `INITIAL` | refused, reason `limit` |
   | any `TURNING_TO_*` | refused, reason `illegal` | refused, reason `illegal` |

   A refused command is answered with `ERROR` carrying the reason: `limit`
   when the table is already at the end position in that direction,
   `illegal` in every other case. A legal one starts the motor and the state
   becomes the `TURNING_TO_*` state from the table; 3 s later the motor stops
   at the next sensor, the state becomes the target position, and `DONE` is
   sent.
3. The result table survives disconnects. After a reconnect the device sends
   nothing on its own.
4. `STATUS` is answered immediately with the current state.

## Client

- It has at most one turn command open at a time. It issues 6 commands in
  total, in this fixed order:
  `TURN_LEFT`, `TURN_RIGHT`, `TURN_RIGHT`, `TURN_LEFT`, `TURN_LEFT`, `TURN_RIGHT`.
  Starting from `INITIAL`, that visits
  `LEFT`, `INITIAL`, `RIGHT`, `INITIAL`, `LEFT`, `INITIAL`.
  After a command is closed it waits a think time of 1 to 3 s before the next
  one.
- If no `ACK` arrives within 2 s, it resends the same command with the same
  `req_id`, at most twice. If there is still no `ACK`, it closes the command
  as failed (cause `ack_timeout`).
- If neither `DONE` nor `ERROR` arrives within 15 s of the first send, it
  closes the command as failed (cause `done_timeout`).
- A `DONE` or `ERROR` closes the command only if its `req_id` is the open
  command's id; anything else is ignored.
- After a reconnect it resends the open command, if any, with the same
  `req_id`.
- It sends `STATUS` every second and does not act on the replies.
- A command that fails does not change the order: the next command is the
  next one in the list.

## Link and timing

- Every message has a delivery delay between 10 ms and 1.5 s.
- A message sent while the connection is down is lost. A message in flight
  when the connection drops is lost too.
- A run lasts 90 s of simulated time.
- Each run uses a different environment seed: delays and the client's think
  times differ from run to run, but the structure (ids, retry rules, timeouts)
  is the same.
