# Hardware testbed: Arduino Uno lift + Jetson Orin client (WP5c)

Real firmware, a real serial link and a real clock, producing a client log that replayspect
ingests and reproduces. The work order is
[`docs/work-order-wp5c-testbed.md`](../../docs/work-order-wp5c-testbed.md).

| Part | Runs on | Files |
| --- | --- | --- |
| Device: the `lift.v0` state machine, no defect unless built with one (stage 3) | Arduino Uno | `firmware/lift_uno/` (`lift_device.h` is plain C++; `lift_uno.ino` wraps serial I/O and `millis()`) |
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
| boot (device) | `READY log=1`: once after reset, with the device log option. It never names a defect: `READY` reaches the client log |
| boot, build line | `# 0 build defect=none` (or `defect=M4`): the build's defect switch, written whether or not the device log is on. The link files it in the truth file, not the device log |
| device log (device) | `# 12395 state MOVING_UP r-0001 from=DOWN on=MOVE_UP`: the device clock (`millis()`), then a trace-like event |
| defect fired, harness only | `8050 LOG defect fired M4 r-0004`: the defect's own branch changed what the device did. Only a build with `-DLIFT_FIRED_LOG=1` (the native harness) writes it, never the Uno build |

Opening the port resets the Uno, so every run starts in `DOWN`. The client sends nothing before
`READY`. The link sends `#` lines to the device log file, with the Orin receive time in front, and
never passes them to the client. The build line, and a `defect fired` line from an older build, go to
the truth file instead (`"action": "build"` / `"defect_fired"`): the device log is an input to the
analysis (`replayspect device`), and these lines are the experiment's answer.

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
   so the two behave the same. For the same reason there is no switch for M3 (resend the last
   `DONE` after a reconnect).

The conformance test (`tests/test_testbed_conformance.py`) compiles `lift_device.h` natively and
checks that its replies and state changes equal the Python model's. The scripts cover retries,
repeats after `DONE` and after a refusal, polls during a move, an opposite command while moving,
two new ids within 50 ms, repeats of older ids, unknown messages, and six commands with polls. It
runs every script with no defect and with each defect switch against the model's mutant, and
checks where each defect fired (`-DLIFT_FIRED_LOG=1`). It needs only a C++ compiler, not the board.

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

## Stage 1 result (2026-11-11)

Hardware: an Arduino UNO Mini (ATmega328P, `arduino:avr:uno`) on a Jetson Orin (Ubuntu, aarch64,
Python 3.10, pyserial 3.5, arduino-cli 1.6.0, arduino:avr 1.8.8). Two 90 s runs with think seed 0
and no faults: the first with the device log off, the second with it on.

| | device log off | device log on |
| --- | --- | --- |
| firmware (flash / RAM) | 4,256 B / 719 B (35%) | 5,166 B / 841 B (41%) |
| run valid (no device error, no reset) | yes | yes |
| ingest: events, unmatched, flagged | 202, 0, 0 | 202, 0, 0 |
| `drive --link-delay 0 0 --status-rule`: reproduced at 250 ms | yes, 12/12 receives, status sequence same | yes, 12/12 receives, status sequence same |
| residual, all matched receives (min / median / max) | 2 / 3 / 3 ms | 5 / 7.5 / 10 ms |
| residual, `ACK` | 2 / 3 / 3 ms | 5 / 5 / 6 ms |
| residual, `DONE` | 2 / 3 / 3 ms | 9 / 9.5 / 10 ms |
| residual, `STATUS_REPLY` (polls, not judged; n = 89) | 4 / 4 / 5 ms | 6 / 7 / 8 ms |

Residual = recorded minus simulated receive time, with no link delay in the model. It is the real
total delay of the round trip plus the firmware's timing error, measured with the client's 1 ms
timestamps.

- **Device log off:** about 3 ms per round trip. `DONE` is no later than `ACK`, so the firmware's
  50 ms and 3 s timers show no error at this resolution.
- **Device log on:** `ACK` takes 2–3 ms longer and `DONE` 6–7 ms longer. Each `#` line goes out on
  the same serial line as the replies, so watching the device costs a few milliseconds per reply.
  It is the most for `DONE`, which is followed and preceded by several log lines.
- **The first real-hardware problem:** the Uno sent two NUL bytes before `READY` after the port
  opened. The link now drops NUL bytes.


## Stage 2: fault plans (experiment testbed-01)

`host/client.py --plan PLAN.json` makes the link apply a fault plan. Plans use the simulator's
vocabulary:

```json
{"id": "T05", "faults": [{"dir": "s2c", "msg": "ACK", "req_id": "r-0002", "k": 0, "drop": true}],
 "disconnects": [{"after": "c2s MOVE_UP r-0003 0", "offset_ms": 800, "duration_ms": 1500}]}
```

- **A fault** names one message by `(dir, msg, req_id, k)`, where `k` counts sends of the same
  message and id. It gives exactly one of `delay_ms` (on top of the physical link), `drop`, or
  `dup_extra_ms` (a second copy that much later).
- **A disconnect** is anchored on an event, so it falls in the same phase whatever the think-time
  seed:
  - `after` is a c2s or s2c key; the window starts `offset_ms` (≥ 0) after that message passes
    the link.
  - Nothing passes in the window. A message sent in it, or held across its start, is lost.
  - The client is told at the window's start and end, logs `link down` and `link up`, and
    resends its open command after the reconnect.
- **The truth file** (`--truth`, a JSON line per message and per window event, kept outside the
  repository) records what the link actually did: `pass`, `drop`, `delay`, `dup`,
  `lost_in_disconnect`, `disconnect` and `reconnect`, with times in µs since the client's start.

**Timestamps.** Client log times are written in microseconds. The accuracy is coarser: USB serial
delivers bytes in bursts, and the client loop polls about every half millisecond.

**Results:** [docs/experiments/testbed-01.md](../../docs/experiments/testbed-01.md) (39 runs) and
[docs/experiments/testbed-02.md](../../docs/experiments/testbed-02.md) (48 runs, the minimal-explanation fit).
**Operator note:** on Ubuntu, ModemManager probes new `ttyACM` devices. During testbed-01 the
board was silent until a udev rule told ModemManager to ignore it:

```
ATTRS{idVendor}=="2341", ATTRS{idProduct}=="0062", ENV{ID_MM_DEVICE_IGNORE}="1"
```

Put it in `/etc/udev/rules.d/`, reload udev and replug the board. Use your board's vendor and
product ids from `lsusb`.

## Stage 3: the defect switch

`-DLIFT_DEFECT=N` builds the public device-side lift defect MN of the model
(`src/replayspect/sut/lift.py`): 1, 2, 4, 5, 9, 10 or 11. The default 0 is no defect; any other number
does not compile. Compile it like the device log option:

```bash
arduino-cli compile --fqbn arduino:avr:uno \
  --build-property "compiler.cpp.extra_flags=-DLIFT_DEFECT=4" examples/testbed-uno/firmware/lift_uno
```

- **The answer stays out of the client log and the device log.** `READY` does not name the defect.
  The build names it only in its build line (`build defect=M4`), which the link files in the truth
  file. The client also leaves out any `defect=` field from an older build's `READY` when it writes
  its header.
- **Where it fired is computed afterwards.** The Uno build does not write `defect fired`. On the
  serial line that line delayed the replies after it by about 2 ms, exactly where the defect fired
  (testbed-03), so the timing showed it even with the line removed. Instead,
  `firmware/harness/fired_points.py DEVICE_LOG --defect N` feeds the device log's receives to the
  native harness built with the same defect and `-DLIFT_FIRED_LOG=1`, and prints each firing
  (`{"t_ms", "defect", "req_id"}`). It first checks that the harness reproduces every send, state
  change and effect of the log, millisecond by millisecond, and refuses otherwise. Each time the
  defect's own branch changes what the device does is one firing. Later effects of an earlier
  firing, such as a stored result it caused, are not marked again. Run it outside the repository,
  after the analysis it scores.
  - **Checked on the 182 real device logs** (development data): the harness reproduced every log.
    On the 27 defect-build logs of testbed-03, the computed firings equal the `defect fired` lines
    those builds still wrote, 18 of 18.
- **A change nobody named:** `fired_points.py DEVICE_LOG --reference DIR`. Run the copy of the script
  that sits in the changed firmware tree, with `DIR` an unchanged copy of
  `examples/testbed-uno/firmware`. It runs both firmwares on the log's inputs, after checking that
  the changed one reproduces the log. It prints the first output line where they differ
  (`{"t_ms", "req_id", "changed", "reference"}`), or `{"difference": null}` when the change never
  acted on those inputs. Build lines are left out of the comparison.
  - **What the first difference is:** the first place the outputs differ, which can come after the
    change's own branch. On testbed-03, with the defect switch as the change, it fell on the firing's
    request in 18 of 18 runs: at the same millisecond for M4 and M10, and 50 ms later for M2. It
    found no difference in the 9 runs where the defect did not fire.
- **The build line is written even with the device log off,** like error lines.
- **Memory** (compiled on the Orin, arduino-cli 1.6.0, arduino:avr 1.8.8, device log on, not
  flashed): the testbed-02 build used 5,166 B flash and 841 B RAM. With the switch:

  | Build | Flash (testbed-03) | RAM (testbed-03) | Flash (no fired line) | RAM (no fired line) |
  | --- | --- | --- | --- | --- |
  | no defect | 5,426 B | 993 B (48%) | 5,334 B | 977 B (47%) |
  | M2 | 5,462 B | 991 B | 5,374 B | 975 B |
  | M4 | 5,472 B | 991 B | 5,366 B | 975 B |
  | M10 | 5,408 B | 993 B | 5,286 B | 975 B |

  The testbed-03 builds needed about 152 B more RAM than testbed-02: the 8-entry table of the ids a
  correct device would know (128 B), and the new log strings, which sit in RAM on the Uno. Without
  the fired line, the builds use about 16 B less RAM again, leaving 1,071 B for the stack. The four
  compiled binaries contain no `defect fired` string.

**Result:** [docs/experiments/testbed-03.md](../../docs/experiments/testbed-03.md) (95 runs: no
defect, M2, M4, M10).

## Not yet

- **Two sources:** the client log and the device log together, with the clock between them estimated.
