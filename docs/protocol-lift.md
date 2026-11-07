# Lift integration protocol (lift.v0)

This document describes the system under test as its specification says it
should behave. It is given to planners (people or models) that try to break
the behavioural contracts by choosing network faults. It deliberately says
nothing about how the implementation under test might deviate.

## Parties

- **client**: the robot side. It drives the lift.
- **device**: the lift controller.

They exchange messages over a network link with delays, and the link may
lose, duplicate or reorder messages and may disconnect for a while.

## Messages

Every message carries a request id (`req_id`).

| Direction | Message | Fields | Meaning |
| --- | --- | --- | --- |
| client to device | `MOVE_UP` | | move the lift up |
| client to device | `MOVE_DOWN` | | move the lift down |
| client to device | `STATUS` | | ask for the current state |
| device to client | `ACK` | | the request was received |
| device to client | `DONE` | | the move finished |
| device to client | `ERROR` | `reason` | the move was refused |
| device to client | `STATUS_REPLY` | `state` | the device state when the reply was sent |

Move commands use ids `r-0001`, `r-0002`, ... in the order the client issues
them. Status polls use `s-0001`, `s-0002`, ...

## Device

States: `DOWN`, `MOVING_UP`, `UP`, `MOVING_DOWN`. It starts in `DOWN`.

1. On a move request the device first looks the `req_id` up in its result
   table. A known id is answered with the stored result again (`ACK` while the
   move is in progress, `DONE` or `ERROR` once it has finished), and nothing
   else happens. A new id is recorded as in progress, answered with `ACK`, and
   executed 50 ms later.
2. On execution the device checks the current state. `MOVE_UP` is legal only
   in `DOWN`, `MOVE_DOWN` only in `UP`. An illegal command is answered with
   `ERROR` (reason `illegal`). A legal one starts the motor and the state
   becomes `MOVING_UP` or `MOVING_DOWN`; 3 s later the motor stops, the state
   becomes `UP` or `DOWN`, and `DONE` is sent.
3. The result table survives disconnects. After a reconnect the device sends
   nothing on its own.
4. `STATUS` is answered immediately with the current state.

## Client

- It has at most one move command open at a time, alternating `MOVE_UP` and
  `MOVE_DOWN`, starting with `MOVE_UP`. It issues 6 commands in total. After a
  command is closed it waits a think time of 1 to 3 s before the next one.
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

## Link and timing

- Every message has a delivery delay between 10 ms and 1.5 s.
- A message sent while the connection is down is lost. A message in flight
  when the connection drops is lost too.
- A run lasts 90 s of simulated time.
- Each run uses a different environment seed: delays and the client's think
  times differ from run to run, but the structure (ids, retry rules, timeouts)
  is the same.
