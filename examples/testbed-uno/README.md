# Hardware testbed: Arduino Uno lift + Jetson Orin client (WP5c)

Real firmware, a real serial link and a real clock, producing a client log that replayspect
ingests and reproduces. The work order is
[`docs/work-order-wp5c-testbed.md`](../../docs/work-order-wp5c-testbed.md).

| Part | Runs on | Files |
| --- | --- | --- |
| Device: the `lift.v0` state machine, no defect | Arduino Uno | `firmware/lift_uno/` (`lift_device.h` is plain C++; `lift_uno.ino` wraps serial I/O and `millis()`) |
| Client: commands, retries, timeouts, polling, the log | Jetson Orin | `host/client.py` |
| Link: passes lines through (stage 1) and records what it did | Jetson Orin | `host/fault_link.py` |
| Rules to ingest the client log | development machine | `rules/testbed-client.yaml` |

The Orin runs only `host/`: the Python standard library and `pyserial`. The logs are copied to the
development machine, and replayspect runs there.

The Arduino build compiles only the sketch folder, so the header sits there, next to the sketch
(`firmware/lift_uno/lift_device.h`). The native conformance harness includes it from there
(`firmware/harness/harness.cpp`).

## Wiring

One USB cable from the Uno to the Orin. No motor: a move is a 3 s timer. The on-board LED (pin 13)
is lit while the lift moves.

## Wire format

115200 baud. One ASCII line per message, ending in `\n`.

| Line | Example |
| --- | --- |
| request (client to device) | `MOVE_UP r-0001`, `STATUS s-0003` |
| reply (device to client) | `ACK r-0001`, `DONE r-0001`, `ERROR r-0002 reason=illegal`, `STATUS_REPLY s-0003 state=MOVING_UP` |
| boot (device) | `READY log=1 defect=none`: once after reset, with the build options |
| device log (device) | `# 12395 state MOVING_UP r-0001 from=DOWN on=MOVE_UP`: the device clock (`millis()`), then a trace-like event |

Opening the port resets the Uno, so every run starts in `DOWN`. The client sends nothing before
`READY`. The link sends `#` lines to the device log file, with the Orin receive time in front, and
never passes them to the client.

## Limits and where the firmware differs from the model

Uno memory (2 KB RAM):

| Limit | Value | When exceeded |
| --- | --- | --- |
| req_id | 15 characters | line dropped, `# error id_too_long` |
| line | 63 characters plus `\n` | line dropped, `# error line_too_long` |
| result table (move ids) | 8 entries; a run uses 6 | answered but not recorded, `# error table_full r-…` |
| execution queue (the 50 ms wait) | 4 | not accepted (no `ACK`), `# error queue_full r-…` |

Where the firmware cannot follow the model exactly:

1. **Time granularity.** Timers run on `millis()`, in 1 ms steps; the model runs in µs. Execution
   (50 ms) and travel (3 s) can end up to about 1–2 ms late, counting loop latency.
2. **Serial output can block.** The Uno's transmit buffer holds 64 bytes. When it is full,
   `Serial.print` waits, so device log lines can delay replies. A reply is always written before
   its log line, and the device log can be compiled out (`LIFT_DEVICE_LOG=0`).
3. **Order within one millisecond.** Each loop runs the due timers first, then at most one input
   line. The model runs what it scheduled first. Where the two coincide in the same millisecond,
   the order can differ.
4. **Transmission time.** About 0.09 ms per byte, so roughly 2 ms for a typical line. It is part of
   the link delay.
5. **The result table and the queue are bounded** (table above). Overflow is always logged.
6. **No connection on the device side.** Disconnects are emulated by the link (stage 2), and the
   device keeps running. The model's device also does nothing on reconnect when no defect is on,
   so the two behave the same.

The conformance test (`tests/test_testbed_conformance.py`) compiles `lift_device.h` natively and
checks that its replies and state changes equal the Python model's. The scripts cover retries,
repeats after `DONE` and after a refusal, polls during a move, an opposite command while moving,
two new ids within 50 ms, unknown messages, and six commands with polls. It needs only a C++
compiler, not the board.

## A run is invalid when

- the device wrote any `# ... error` line, or
- `READY` came again during the run (the board reset).

The client log's last line says which: `# end valid=yes`, or `# end valid=no reasons=...`.

## Stage 1: steps for the operator

On the development machine (or anywhere with `arduino-cli`):

```bash
arduino-cli core update-index
arduino-cli core install arduino:avr
# device log on (the default)
arduino-cli compile --fqbn arduino:avr:uno examples/testbed-uno/firmware/lift_uno
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno examples/testbed-uno/firmware/lift_uno
```

For the run with the device log off, compile with
`--build-property "compiler.cpp.extra_flags=-DLIFT_DEVICE_LOG=0"` and upload again. `READY` then
says `log=0`, and the client log's header records it.

On the Orin (copy `examples/testbed-uno/host/` there; `pip install pyserial`):

```bash
# run 1: firmware with the device log OFF
python3 host/client.py --port /dev/ttyACM0 --seed 0 \
  --log logoff-client.log --device-log logoff-device.log --truth logoff-truth.log
# reflash with the device log ON, then run 2 with the same seed
python3 host/client.py --port /dev/ttyACM0 --seed 0 \
  --log logon-client.log --device-log logon-device.log --truth logon-truth.log
```

Each run takes 90 s and ends with `run valid: ...` or `run INVALID: ...`. Send back the six files:
two runs, each with a client log, a device log and a truth file.

On the development machine, for each client log:

```bash
python3 -m replayspect ingest logon-client.log --rules examples/testbed-uno/rules/testbed-client.yaml --out logon.jsonl
python3 -m replayspect drive logon.jsonl --link-delay 0 0 --status-rule --residuals --trace-out logon-run.jsonl
python3 -m replayspect rewind logon-run.jsonl --actor client --window 0 10s
```

`--link-delay 0 0` runs the empty plan with no link delay, so each residual (recorded minus
simulated receive time) is the real total delay of that round trip plus the firmware's timing
error. Do not use `--fit` for this measurement: it computes each reply delay from the log, so the
residuals would be 0 by construction.

## Not yet

- **Stage 2:** fault plans in the link; the client then logs the `link down` / `link up` it observes.
- **Stage 3:** a firmware defect switch.
- **Two sources:** the client log and the device log together, with the clock between them estimated.
