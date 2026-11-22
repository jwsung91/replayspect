# Hardware testbed: Arduino Uno lift + Jetson Orin client (WP5c)

Real firmware, a real serial link and a real clock, producing a client log that replayspect
ingests and reproduces. The work order is
[`docs/work-order-wp5c-testbed.md`](../../docs/work-order-wp5c-testbed.md).

| Part | Runs on | Files |
| --- | --- | --- |
| Device: the `lift.v0` state machine, no defect unless built with one (stage 3) | Arduino Uno | `firmware/lift_uno/` (`lift_device.h` is plain C++; `lift_uno.ino` wraps serial I/O and `millis()`) |
| Device: the `turntable.v0` state machine (firmware only, checked against the model; no client or hardware run yet) | Arduino Uno | `firmware/turntable_uno/` (`turntable_device.h`, `turntable_uno.ino`) |
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

With the travel sensor build (below), a servo and two end sensors as well: servo signal to pin 9,
the down sensor to pin 2, the up sensor to pin 3. Each sensor pulls its pin to GND when active
(a hall sensor such as the A3144 with a magnet on the servo horn, or a switch); the pins use the
internal pull-ups. Power the servo from its own 5 V supply, with a 470 µF capacitor across it and
its GND joined to the Uno's: a servo drawing current from the Uno's 5 V can reset the board, and a
reset makes the run invalid.

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

## Travel sensor build (servo and end sensors)

`-DLIFT_TRAVEL_SENSOR=1` ends a move when the sensor at its end reads active, not after 3 s: the
up sensor for `MOVE_UP`, the down sensor for `MOVE_DOWN`, for `LIFT_SENSOR_HITS` (3) samples in a
row, read every 5 ms, so a bouncing switch does not end it early. While the lift moves, the servo
turns one degree toward the move's end every 3000 / 90 ms, so a free move takes about 3 s, as in
the model. Hold the servo horn and the sensor never reads active: the move never ends and the
device sends no `DONE` (the protocol has no stall error), so the client closes the command after
15 s (`done_timeout`). The default build is unchanged.

```bash
arduino-cli compile --fqbn arduino:avr:uno examples/testbed-uno/firmware/lift_uno \
  --build-property "compiler.cpp.extra_flags=-DLIFT_TRAVEL_SENSOR=1"
```

Calibrate on the rig: `DOWN_DEG` and `UP_DEG` in `lift_uno.ino` (servo angles at the two ends;
the sensors must sit where the servo arrives) and `LIFT_SENSOR_HITS`. The device log records the
setting after the build line (`# 0 config travel=sensor hits=3`) and each arrival after its
`DONE` (`# 4015 sensor arrive r-0001`). Both lines are outside the device log allow list, so they
never reach a result. The `config` line goes to the device log, not the truth file.

What this build adds to the differences above:

- **Travel time is real.** A move ends when its sensor reads active: near 3 s when free, earlier
  or later depending on where the sensor sits, later or never when held. `device` and `drive`
  report the move's end as a timing difference, and C9 in the rev2 and rev3 contracts (motor stop within 3002 ms of its
  start) fails whenever a move takes longer. Both are expected here, not defects.
- **A move that starts with its end sensor already active ends after about 15 ms** (three
  samples): the device trusts the sensor, not the angle.
- **The servo library uses Timer1 interrupts** (on the Uno), a few µs each, and turns off PWM on
  pins 9 and 10. The firmware uses no PWM.
- **`harness/fired_points.py` does not know when a move ended** in this build, so its points are
  wrong after the first arrival. Use this build without a defect.

The native harness takes a sensor sample as `T_MS @pos UP DOWN` (each 0 or 1). The conformance
test checks the run of samples, a bounce, the wrong sensor, a move that never ends, and that the
3 s timer is off.

**This build has been through the harness tests only.** It has never run on a board with a servo
and sensors attached; the calibration values above are untried.

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
arduino-cli upload -p "$LIFT_PORT" --fqbn arduino:avr:uno examples/testbed-uno/firmware/lift_uno
```

For the run with the device log off, compile with
`--build-property "compiler.cpp.extra_flags=-DLIFT_DEVICE_LOG=0"` and upload again. `READY` then
says `log=0`, and the client log's header records it.

On the Orin (copy `examples/testbed-uno/host/` there; `pip install pyserial`):

```bash
# run 1: firmware with the device log OFF
python3 host/client.py --port "$LIFT_PORT" --seed 0 \
  --log logoff-client.log --device-log logoff-device.log --truth logoff-truth.log
# reflash with the device log ON, then run 2 with the same seed
python3 host/client.py --port "$LIFT_PORT" --seed 0 \
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

## Blind runs: a firmware change the analyst does not know

The analyst (the agent) reads only the logs. The operator makes the change on a computer the analyst
cannot reach, flashes it there, and moves the board to the Orin. So the changed source never exists
on the development machine or the Orin.

**On the operator's computer.** You need:
- arduino-cli 1.6.0 with the core arduino:avr 1.8.8;
- for scoring, a C++ compiler and Python 3;
- from the repository at the registered commit, the folder `examples/testbed-uno/firmware`:
  - `lift_uno/lift_uno.ino`, `lift_uno/lift_device.h`;
  - `harness/harness.cpp`, `harness/fired_points.py`.

```bash
arduino-cli core update-index && arduino-cli core install arduino:avr@1.8.8
cp -r firmware reference-firmware            # an unchanged copy, kept as it is
# edit firmware/lift_uno/lift_device.h. Keep the wire format, the device log's line format, the
# build line and the device log switch as they are, and add no log line.
arduino-cli compile --fqbn arduino:avr:uno --output-dir build-blind \
  --build-property "compiler.cpp.extra_flags=-DLIFT_DEFECT=0" firmware/lift_uno
#   note "Sketch uses ..." and "Global variables use ...": keep RAM at about 1,000 B or less
ls -l /dev/serial/by-id/                     # each board's fixed path (see "Two boards" below)
arduino-cli upload -p PORT --fqbn arduino:avr:uno --input-dir build-blind firmware/lift_uno
arduino-cli monitor -p PORT -c baudrate=115200
#   expect "READY log=1", "# 0 build defect=none", "# 0 state DOWN from=- on=init"; close the monitor
sha256sum firmware/lift_uno/lift_device.h build-blind/lift_uno.ino.hex   # keep with your assignment
```

- **Compile every blind build with `-DLIFT_DEFECT=0`,** so its build line says `defect=none` like
  every other run.
- **An unchanged slot** takes the same commands on `reference-firmware`, from the same computer.
  Flash before every slot, unchanged slots included, so the replugs and flashes look the same for
  every slot.

**On the Orin.** Plug the board into the hub port and run one session with the build expected to be
`none`:

```bash
python3 host/client.py --port "$LIFT_PORT" --seed SEED --plan PLAN.json --expect-build none \
  --log blind/LABEL-client.log --device-log blind/LABEL-device.log --truth blind/LABEL-truth.log
```

- **`--expect-build`:** the client checks the build record the link files in the truth file. A
  mismatch makes the run invalid (`wrong_build`, or `no_build_line`) and exits 3. It never names a
  build in the client log.
- **What the analyst receives:** only the client and device logs. Keep the truth files.

**Scoring, after the analyst has submitted.** On the operator's computer, for each slot, run the copy
of the script in your changed tree:

```bash
python3 firmware/harness/fired_points.py blind/LABEL-device.log --reference reference-firmware
```

It checks that your changed firmware reproduces the device log. Then it prints the first output line
where your firmware and the unchanged one differ on that log's inputs, with the request id, or
`{"difference": null}` when your change never acted. This first output difference is what the
analyst's conformance check looks for too. It can come after the change's own branch: with M2 it
came 50 ms later, when the repeat executed.

**Result:** [docs/experiments/testbed-04.md](../../docs/experiments/testbed-04.md) (83 runs with the
device log against the model, and 8 blind slots). The operator had no second computer and made,
compiled and flashed the change on the Orin, which the analyst did not use from before the
assignment's hash until after the submission.

**Result:** [docs/experiments/testbed-05.md](../../docs/experiments/testbed-05.md) (16 blind slots on
mechanically mutated firmware, with the rev2 contracts). The builds, flashing and runs were on the Orin,
with the scripts `blind_flash.sh` and `run_blind.sh` kept with the registration outside the repository.

## Two boards

Two Unos are plugged into the Orin: one runs the lift, one the turntable. Each is named by its
`/dev/serial/by-id/` path, which stays with the board whichever USB port it is in; `/dev/ttyACM0`
is not used in scripts or commands, since its number follows the order the boards were plugged in.
On the Orin, a file `boards.env` (outside the repository) fixes them:

```bash
LIFT_PORT=/dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_<serial>-if00
TURNTABLE_PORT=/dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_<serial>-if00
```

`client.py` records the path it was given, and what it resolves to, in the truth file's first line
(`{"action": "port", ...}`), and warns when the path is not a by-id one. The past records above used
`/dev/ttyACM0` with one board.

**The wrong board is refused.**
- **A session:** `client.py --expect-system lift.v0|turntable.v0` (default `lift.v0`). When the
  build line names another system, the client stops sending at once. The run is invalid
  (`reasons=wrong_system`) and the exit status is 3.
- **A flash:** before the upload, the script checks only that the port is that system's path in
  `boards.env`. It does not look at the firmware on the board: on its first flash, the turntable
  board does not carry the turntable firmware yet.
- **After the upload:** `host/board_check.py --port PORT --expect-system SYSTEM` reads the boot
  lines and checks the system and the build. Exit status 0 on a match, 3 when the line names
  another system or build, 4 when no build line comes.

## Turntable firmware

`firmware/turntable_uno/` is the `turntable.v0` device (docs/protocol-turntable.md) in the same
shape as the lift: `turntable_device.h` is plain C++, `turntable_uno.ino` the same serial loop.
Wire format, device log lines, timer order, limits and error lines are the lift's. The model has
no defects, so there is no defect switch and the build line is always
`build system=turntable.v0 defect=none`. The lift's build line has no `system=` field and is read as
`lift.v0`; its output is unchanged.
The turntable uses the timer build only: a turn lasts 3 s and lights the LED; no motor or sensor.

- **Conformance:** `tests/test_testbed_turntable.py` compiles the harness with `-DHARNESS_TURNTABLE=1`
  and compares replies, state changes and motor effects with the Python model.
- **Host:** the lift's `host/client.py` with the turntable's commands
  (`--sequence TURN_LEFT,TURN_RIGHT,TURN_RIGHT,TURN_LEFT,TURN_LEFT,TURN_RIGHT`); `host/fault_link.py`
  unchanged. Without `--sequence` the client log is byte-for-byte the lift's from before
  (`tests/test_testbed_host.py`, two golden files).
- **Ingest rules:** `rules/testbed-client-turntable.yaml` (`system: turntable.v0`), the lift's file
  with the turntable's system and name.
- **Device log:** `replayspect device --system turntable.v0` reads the harness's turntable logs: the
  correct model conforms, neither `contracts/turntable.v0.yaml` nor `contracts/generic/turntable.v0.yaml`
  is violated, and over the test scripts every generic contract and C1, C3, C5, C7, C8 are exercised
  (C2, C4, C6 are the client's).
- **Scoring:** `harness/fired_points.py DEVICE_LOG --system turntable --reference DIR` (no defect switch,
  so `--reference` only).

```bash
arduino-cli compile --fqbn arduino:avr:uno examples/testbed-uno/firmware/turntable_uno
arduino-cli upload -p "$TURNTABLE_PORT" --fqbn arduino:avr:uno examples/testbed-uno/firmware/turntable_uno
python3 host/board_check.py --port "$TURNTABLE_PORT" --expect-system turntable.v0
python3 host/client.py --port "$TURNTABLE_PORT" --seed SEED --plan PLAN.json --expect-build none \
  --expect-system turntable.v0 --sequence TURN_LEFT,TURN_RIGHT,TURN_RIGHT,TURN_LEFT,TURN_LEFT,TURN_RIGHT \
  --log client.log --device-log device.log --truth truth.jsonl
```

### WP6/7c stage 1: development sessions on the unchanged firmware

About 24 sessions on the turntable board, testbed-06's twelve plan kinds carried over, two plans each,
seeds 7000–7023 (the range 7000–7099 is kept for development; no blind pool takes it). The plans,
the plan maker, the Orin run script and the checks live outside the repository
(`testbed-turntable-dev/`: `make_plans.py`, `flash.sh`, `run_dev.sh`, `check_dev.py`, `dry_run.py`).
Carried over:

- `refused-repeated` and `copy-refused-early` are adapted: in the turntable's order losing the command
  just before a target never makes it refused, so the command two before is lost
  (r-0001 for r-0003, r-0003 for r-0005);
- `copy-status` has one plan for each of two placements (both during a turn; standing, then during a turn).

**Result (2026-11-22, development data):** the boards were flashed at `54a6553` (this branch), on the Orin.
The lift board is `…B101`, the turntable board `…B182` (Arduino UNO Mini); the sessions ran from 19:28 to 20:06.

- **Boards:** `flash.sh` refused the turntable firmware on the lift board's port (exit 3). After each
  upload, `board_check.py` printed `ok: lift.v0 defect=none` and `ok: turntable.v0 defect=none`. A lift
  session aimed at the turntable board stopped with `wrong_system` (exit 3) about 4 ms after `READY`,
  after one `MOVE_UP`, which the turntable ignores (the start order was left unchanged in review).
- **D11, one lift session** (seed 0, no plan) after the client change: valid; `replayspect device`:
  `correct: conforms` (126 of 126 device events).
- **D12, 24 turntable sessions** (D01–D24, seeds 7000–7023):
  - All 24 are valid, and the link applied every planned fault. The board path is recorded in each
    truth file.
  - Each plan's timing condition held on the board, computed from its device log (24 of 24).
  - `replayspect device --system turntable.v0 --complete device:recv,send,state,effect`: the correct
    model conforms in **24 of 24**, with every device event at most 0 ms after the model. The 2 ms
    window was never used.
  - **No violation** of `contracts/turntable.v0.yaml` or `contracts/generic/turntable.v0.yaml` in any
    session, and nothing went unjudged.
  - Exercised in all 24 sessions: every generic contract (G1.motor_start, G1.motor_stop, G2.ack,
    G2.final, G2.poll.STATUS, G3, G4, G5, G6, G6b, P1), and C1, C3, C5, C7, C8. C2, C4 and C6 are client
    contracts and are never exercised on a device log.
  - **No false mismatch and no false violation.** This is a development check, not a measurement: the
    turntable has the lift's timing, and these plans were made by the analyst.

The logs stay outside the repository; by sha256:

<details><summary>75 files</summary>

```
be27b37124c9ac8cec478ec18db1c13c95b96cb95ec365db2a26ac69f6bdb1cb  lift-client.log
18fbf1697fce4d43ffe7bf14a68c36e1d5fd36c030cb4cecef7e853edd9aa83d  lift-device.log
6cfb6f6fd72e4581a2c66f9f9d3bb3aac45b761b528452a0a5c44acff26688b0  lift-truth.jsonl
9034aed59fcf1fb9714b94873a0238c4fe086c2be9ce61d491a47c9c0a1b3e3a  D01/client.log
e7b008bf0a4fb6b38d35771367298188495de99827494c80da8e2c62ed619260  D01/device.log
026679737cfdb9b052f546fba74e6ae6ff6d298a1cb741217818344644b1a7cb  D01/truth.jsonl
b6d9ab89ce9924dee4b2c8046985c704a55b9965f3ddbb4af787191c50ee069e  D02/client.log
693e77932e9c35737deefe2a2aa2f74d608f2c406e72c628d6416ee128cd5d71  D02/device.log
085739449bd455488781e9f9a3c9b5f406cd25b0b1d0c793260f449c7ba330f5  D02/truth.jsonl
e575ee90055bafcf16912046331e33baba61d831e1b1edf554ef799a5e822d59  D03/client.log
e129a3c29ec2272dc8151f9aaccaeaf7801f2862be31ec7558cda97ba7cd8a98  D03/device.log
92e34bb0a130b83158a01ab95877f27c997c2ebebf46975e067f8e33edbef734  D03/truth.jsonl
cd0190cdb6e8a5d6fd27f84cec533e3f56f65e7f29207b4d27d83c93b10374c4  D04/client.log
747a25cfa1463a0c568233ed073d783eddc20f051e0a5300fb595ab69d4e86fd  D04/device.log
7cd4f770f722e6098c17b50352334eedd4174e52231200682e5c2ae09c2c46f2  D04/truth.jsonl
c97877098d4a264a35be842f1ea042d3ecd30ec45866ffac0f065706d2739770  D05/client.log
878da8fb3d406c895bbf83bcfd3037c90c16ef170e5ceb16c7f06461899dafaf  D05/device.log
586bd1342474aadc029c35642812119514a2db708597b351982fcaf64bb91d8e  D05/truth.jsonl
9a3b4384a65cc95924a0e383162b396b8ee713326d9828677222f28d196c6d90  D06/client.log
b8b138d1c0ebd899de7cb8509220b7a141a086ef92eff07b252b49f5d5a081d2  D06/device.log
d5b149de25090e23a9531460fcf4fdaee86955c1471a2f4bf3d6edef447a18bb  D06/truth.jsonl
49d8eaee9cee9b16be2f4b6c2df3bb571d8babf61066d040e953889657198680  D07/client.log
1f1a37051ce3c93c0d4830d16335deebd3662fad0260e9904abe236f73784ad2  D07/device.log
bbacfbebba07b86441e5fbd0b623885de599c33a448021103e37fa05dbb33e22  D07/truth.jsonl
f5c1a4b81bc4fb90222aaabb2f31b5bf4a7c83f1d91213e20c2130e3461ce3ac  D08/client.log
fbfbf25ab8937984f9b3b82224ef33cc884bfb5a06d41c7860227be6e5705ced  D08/device.log
d407c3ca76e19944a40a43aba8a4fb728f07694f3f2a5955e00063787a55032a  D08/truth.jsonl
d0906e2ed8a17e27c649ac91596b1cdc4424a101b8602f2e6d2f4c42db4154d7  D09/client.log
287ba2eedf90176cc79cd43b49fa06a52879867c411538ad4349b0c65dc54aea  D09/device.log
0403b9d50a83c53b8f7bcb9c4fd201b9234cc541e860e4ce73442822a0c6ec5e  D09/truth.jsonl
feabff30ad1eb3c5e5027385b84979560fca1af74764aa578128737895f90aa4  D10/client.log
844f23dadbb329a8124d453e6c132c0f41828704b62485e244c1cfcb26087c86  D10/device.log
cd41e32976528c448375a591c41a93a7c8b42e17afca430239f7e0855e11814f  D10/truth.jsonl
f4374f83a1fb7119ba045330facf4cd1e4f266930911250595ccae29d1834c44  D11/client.log
d1c302ada523f25a83b54fe431996945c848314d36caa61ef54d302d47e9839c  D11/device.log
ed0e9a3f02b2c557c67930780052104e7f82b0d2470f65f17c307158d7734086  D11/truth.jsonl
07d1daa8c02af4aadcc13c265f14c7bb7123faf9f50f29277437773c6f67bb1f  D12/client.log
73ae2d5c1c1127fdd050d079c5fa3aa381703683ef595504917592165232b754  D12/device.log
727fec52ffbfa5bb385b0f6accea1eaf153a77eada433f07bd4d306c8d6743dc  D12/truth.jsonl
e329ca67e792962e8df0165efbf22face54f02aa6fcdda6c185eb599dcf14efb  D13/client.log
42cd441e04018c6cde601ac5c893a453abac5cb660aad66f3e615e8fa0fbf86e  D13/device.log
989a6ddf910cededbb66c5a3734aeab122e5f05a5a0411be73413bab74ecbd8f  D13/truth.jsonl
0f5d408d1cea40fc59194b90e54b102a8abd1be86f0d770366b5a49415e675ed  D14/client.log
a01327e89e5f271701e6b918fd04a2391aec3de53c751744cb5c058fb4b435c8  D14/device.log
0bd836b627902ffde441aec2b0bc05f2326f59ec5f00cf37721bf2b6d3e36bbd  D14/truth.jsonl
5940d78eafec3d9e12986c474acbadbabbbb69eb6f8ce9bd64cf204f4f9ea0d4  D15/client.log
da6a295e75114b45d5c23a49418aa383201f6f62c363065afdaa20c3fe6f896b  D15/device.log
ea8aff62fb329b478c1b3fa546a20be718bc8d12d819b916f63c9df2251157e6  D15/truth.jsonl
af70d5056315d576cfce7c699104bcb96392039c91fb9e763fa5647a452d1287  D16/client.log
a07bfd4d9e3d17bd1672e10e16ea460b1f88a0e665957e6bd825509244848834  D16/device.log
9ecbe65e1b7c3da322bdda857d4ba34155039747176df75f2a5cc281fc85af5f  D16/truth.jsonl
89ba6e350b91038993d91a15b0bbdfc48e5f8a620b40d92b714300d7a41320e4  D17/client.log
0b54a2b3583a2c4ae6d1d4500bfd10f307e5c1a205c66629c620444ba343f456  D17/device.log
f863b64ee4bb0e24311def4d2dde52b4d4a98bb2a7b76da52d0c8403f4a721db  D17/truth.jsonl
232d2c9d20b2f726066fb7eb3cf40fb97b90e6bb8fd5f7ef04fcb68f7abd204c  D18/client.log
6401a8215c992c13dd55dd42519bf83e4c2cf057e416791ae3e6919a243ee607  D18/device.log
157a0a9ef79951d2373fae469fa6c280cd2de8dc23ad8e5d6810298c79999b64  D18/truth.jsonl
54c63b58ff2de25e50bd60a0aef98d5aeabba041f60fd860e5e885d97f7da17e  D19/client.log
353197909bba9751b4a0e9ff722899287d4ccb08bbdb2cc36b9f66d7a5c8780c  D19/device.log
0e866382489f7f8f3804eca1fb2593cf21b9f2fcce61bc029ff3043e30fa0bad  D19/truth.jsonl
f36f14a92d0c4b5970dfafa45f1f41fb8d5ffcfc7482e0d45bdd6989d0b46b98  D20/client.log
5d8ef42f404fff632c9f7104b388fe187bd8b3461f3ccf2ca7991437f8df3c00  D20/device.log
9b544b4a4529939a799aa6c52ca1c23a31cac2c7b66b930a32bc5a222b778fca  D20/truth.jsonl
d29aaf6dcfe1b0ed91c5721a1d25991442a98be369571cd881aa103f5c0c7bdd  D21/client.log
17f5524c347c10812cdf55bf7c116d65172d44d577b8ee6517ba87aa16e2ac0f  D21/device.log
e2c0cf3483edaff9ac99ec385a052d1c68c5d2a48f2343e94115ededfdd46934  D21/truth.jsonl
37f8cb93042a148c308a102473677ddbbbecf6e3e84d4333b244834afad14533  D22/client.log
f38f872518a22ce1a670b8a0bdc309f508ac9f27990f9cab98794a0c23e35e60  D22/device.log
836ed953f4572d31d5997d183c03bac19fa3454733a09bd844683604709c3ae8  D22/truth.jsonl
b8ec2f42401386d03d026d549908805ef2f53b9b1d8fca93186b576c6cf1aaf4  D23/client.log
ba6add36c54826a2430ebef3cd1395151cfcf65e27f009e49b4020e1610d0c03  D23/device.log
15a2ab0895db936de791dad05b0908d635d8417486acc8ad11dd582d54bfa802  D23/truth.jsonl
ecb9af5c6d6892ad9954351c41d8e10662899994e5639ebf9cdb797a15c6b498  D24/client.log
3d3e0fe2f203e73bcead5404279de320912e10e2621ddf026953ce02c481f8a1  D24/device.log
31b2d59b3b719a9578d58ae2907ecfbd797af1b61c7da978aed05f2369c19073  D24/truth.jsonl
```

</details>

## Not yet
## Not yet

- **Two sources:** the client log and the device log together, with the clock between them estimated.
