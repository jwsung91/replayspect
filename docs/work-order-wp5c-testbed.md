# replayspect work order WP5c — hardware testbed (Arduino Uno + Jetson Orin)

2026-11-10

This is an addition to `docs/work-order-v3.md`. All of its principles and constraints apply. It gives WP5b its second done criterion (a real-format log going ingest → driven replay → `rewind`) and prepares the next experiment on real logs.

## Why

Every log so far came from the simulator. This testbed produces logs from real firmware, a real link, and two real clocks, with no company data involved. The device is an Arduino Uno; the client is a program on a Jetson Orin; they talk over USB serial.

## Roles

| Part | Role | Stands for |
| --- | --- | --- |
| Arduino Uno | Device: the `lift.v0` state machine | Top module mounted on the robot |
| Orin program | Client: command sequence, polling, retry and timeout rules | Robot main controller |
| Fault link (on the Orin) | Delays, drops, duplicates, disconnect windows from a plan file | The network between them |

No motor is needed. A move is a 3,000 ms timer in firmware; an LED may show the state.

## Layout

Everything lives under `examples/testbed-uno/`. The host programs depend only on the Python standard library and `pyserial`, so they run on the Orin without installing replayspect. Logs are copied to wherever replayspect runs.

- `firmware/lift_device.h` — the device state machine in plain C++ with no Arduino headers.
- `firmware/lift_uno/lift_uno.ino` — serial I/O and timing around that header.
- `host/client.py` — the client.
- `host/fault_link.py` — wraps the serial port and applies a fault plan.
- `rules/testbed-client.yaml` — rules file for the client log.
- `README.md` — wiring (one USB cable), flashing with `arduino-cli`, running.

`pyserial` is approved as an optional extra (`[testbed]`). No other new dependency without asking.

## Before any code: show the wire mapping

The protocol document defines messages, not bytes. Propose the mapping first and wait for confirmation:

- One message per line, ASCII, newline-terminated, 115200 baud. Name, req_id, then `key=value` fields.
- A boot line (`READY`) after reset. Opening the port resets the Uno, so every run starts from the initial state; the client waits for `READY` before its first command.
- Device log lines share the link, marked by a leading `#` and carrying the device clock (`millis()`). The fault link passes protocol lines and tees `#` lines to a device log file with the Orin receive time added.
- Memory limits of the Uno (2 KB RAM): maximum req_id length, line length, and the size of the result table used for retried req_ids. The table must be large enough that no entry is evicted during one run; say what happens if it would be.
- Every place where the firmware cannot follow the device model exactly. List them; do not hide them.

## Stage 1 — conformance without hardware, then a clean run on hardware

- Host conformance test: compile `lift_device.h` natively and feed it the same message sequences as the Python device model, including retries and messages arriving during a move. Replies and state changes must match. This runs in CI without a board.
- Firmware: non-blocking loop, no `delay()`. Defects are off.
- Client: the fixed command sequence, think time, 2 retries, 2 s ACK timeout, 15 s DONE timeout, resend after reconnect, 1 s polling. Text log with wall-clock timestamps at millisecond precision, one line per send, receive, and result.
- The client also logs every link-down and link-up it observes, at the time it observes it. Driven replay pins disconnect windows from these lines, so they are required, not optional.
- Link delay bounds for the fit are parameters of the run, not the simulator's link profile. A serial link's real delays are a few milliseconds and may be below the simulator's minimum.
- Operator runs it on the hardware with no faults and returns the client log.
- Then: `ingest` with `rules/testbed-client.yaml` → `drive` → `rewind`.
- Report: whether the clean run reproduces at 250 ms tolerance with an empty plan, and the distribution of time differences between recorded and simulated receives (min, median, max). That distribution is the first measurement of real jitter plus model timing error.
- Done when: the conformance test passes; one real log goes ingest → drive → `rewind` end to end; the residual table is in the report. This closes WP5b's second done criterion.

Stop and report after stage 1. Stages 2 and 3 are an experiment and need their own instruction and registration.

## Stage 2 — injected faults (experiment `testbed-01`, preregistered)

- `fault_link.py` applies a plan in the same vocabulary as the simulator's fault plans: per-message delay, drop, duplicate, and disconnect windows. A disconnect on serial is emulated: nothing passes in the window and the client is told the link went down and came back.
- The link writes what it actually did to a ground-truth file. That file is the hidden answer and is stored outside the repository.
- The reader gets only the client log. Columns follow `driven-01`: reader unchanged, reader with round-trip start, split sensitivity. Add one column: how the restored plan compares with the ground truth (same faults, same messages).
- Plans, number of runs, tolerance, and predictions are fixed in the registration before any run.

## Stage 3 — a defect in firmware

- Compile-time flag selects one device-side defect. In the repository the flag covers only the public lift mutants. Hidden firmware variants, if any, stay outside the repository like the hidden simulator variants.
- Expected chain for one incident: log → driven replay against the correct model fails to reproduce → driven replay against the model with the matching mutant reproduces. Report both.
- This is the first run of "which defect" on real hardware. Baselines and registration rules from the work order apply.

## Later, not now

- The device log (`#` lines with `millis()`) and the client log as two sources, with clock offset and drift estimated. This is the "Two sources" item in Later work; the testbed only has to record the data from stage 1 on.
- Turntable firmware.
- TCP instead of serial (needs a different board).

## Hardware steps are the operator's

The agent writes code, host tests, and scripts (`arduino-cli` compile and upload commands, one command to run a session). The operator flashes the board, runs sessions, and returns log files. If the agent's machine has the board attached, it still asks before flashing or opening the port.

## Open questions for the operator

- [ ] Which machine runs replayspect, and how logs get from the Orin to it.
- [ ] Whether the Orin client should later be rebuilt on the operator's own comms library (ties into the recorder in Later work).
