"""WP5c: the Uno firmware's state machine (lift_device.h) against the Python lift model.

The header is compiled natively with the harness and fed the same timed message sequences as the
model (src/replayspect/sut/lift.py). Replies and state changes must match, with no defect and with
each defect switch (``-DLIFT_DEFECT=N`` against the model's mutant MN, stage 3). Scripts avoid an
input arriving in the same millisecond as a timer: there the firmware runs timers first and the
model runs what it scheduled first (a documented difference).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from replayspect.sim.link import Message
from replayspect.sim.scheduler import Scheduler
from replayspect.sut.lift import LiftDevice
from replayspect.trace import Trace

FW = Path(__file__).parent.parent / "examples" / "testbed-uno" / "firmware"
CXX = shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
pytestmark = pytest.mark.skipif(CXX is None, reason="no C++ compiler")

SCRIPTS = {
    "basic": [(0, "MOVE_UP r-0001"), (1000, "STATUS s-0001"), (5000, "MOVE_DOWN r-0002"), (12000, "END")],
    "retries_and_repeats": [
        (0, "MOVE_UP r-0001"), (20, "MOVE_UP r-0001"),          # repeat while queued: ACK again
        (1500, "MOVE_UP r-0001"),                                # repeat while moving: ACK again
        (2001, "STATUS s-0001"),                                 # during the move
        (4000, "MOVE_UP r-0001"),                                # repeat after DONE: DONE again
        (4500, "MOVE_UP r-0002"),                                # illegal in UP: ERROR
        (5200, "MOVE_UP r-0002"),                                # repeat of a refused id: ERROR again
        (6000, "PING r-0009"),                                   # unknown: ignored
        (7000, "MOVE_DOWN r-0003"), (8000, "MOVE_UP r-0004"),    # opposite while moving: illegal
        (9001, "STATUS s-0002"), (15000, "END")],
    "two_new_ids_within_50ms": [(0, "MOVE_UP r-0001"), (30, "MOVE_UP r-0002"), (6000, "END")],
    "old_ids_again": [(0, "MOVE_UP r-0001"), (4000, "MOVE_DOWN r-0002"), (8000, "MOVE_UP r-0001"),
                      (8500, "MOVE_DOWN r-0002"), (9000, "MOVE_UP r-0003"), (13000, "END")],
    "six_commands_with_polls": [x for n in range(6) for x in (
        (n * 7000 + 13, f"{'MOVE_UP' if n % 2 == 0 else 'MOVE_DOWN'} r-{n + 1:04d}"),
        (n * 7000 + 1007, f"STATUS s-{3 * n + 1:04d}"), (n * 7000 + 2507, f"STATUS s-{3 * n + 2:04d}"),
        (n * 7000 + 4007, f"STATUS s-{3 * n + 3:04d}"))] + [(45000, "END")],
}


#: The defect switches: the public device-side lift defects (M3 needs disconnects, which serial lacks).
DEFECTS = (1, 2, 4, 5, 9, 10, 11)


@pytest.fixture(scope="module")
def build(tmp_path_factory):
    """The harness built with ``-DLIFT_DEFECT=n`` (0: none), compiled once per defect."""
    d, built = tmp_path_factory.mktemp("fw"), {}

    def get(n=0):
        if n not in built:
            out = d / f"harness{n}"
            subprocess.run([CXX, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-O1", f"-DLIFT_DEFECT={n}", "-o",
                            str(out), str(FW / "harness" / "harness.cpp")], check=True)
            built[n] = out
        return built[n]
    return get


@pytest.fixture(scope="module")
def harness(build):
    return build(0)


def firmware(harness, script):
    text = "".join(f"{t} {line}\n" if line != "END" else f"END {t}\n" for t, line in script)
    res = subprocess.run([str(harness)], input=text, capture_output=True, text=True, check=True)
    outs, states = [], []
    for row in res.stdout.splitlines():
        t, kind, body = row.split(" ", 2)
        if kind == "OUT" and not body.startswith("READY"):
            outs.append((int(t), body))
        elif kind == "LOG" and body.startswith("state ") and "on=init" not in body:
            states.append((int(t), body.split()[1]))
    return outs, states, res.stdout


class _Channel:
    def __init__(self, sched, outs):
        self.sched, self.outs = sched, outs

    def attach(self, endpoint, on_message, on_connection=None):
        self.on_message = on_message

    def send(self, sender, msg):
        fields = "".join(f" {k}={v}" for k, v in sorted(msg.fields.items()))
        self.outs.append((self.sched.now_us // 1000, f"{msg.name} {msg.req_id}{fields}"))


def model(script, mutants=frozenset()):
    sched = Scheduler(0)
    trace = Trace(lambda: sched.now_us)
    outs = []
    ch = _Channel(sched, outs)
    LiftDevice(sched, trace, ch, mutants)
    end = 0
    for t, line in script:
        if line == "END":
            end = t
            continue
        name, rid = line.split()
        sched.at_us(t * 1000, lambda n=name, r=rid: ch.on_message(Message(n, r, {})))
    sched.run_until_us(end * 1000)
    states = [(e.t_us // 1000, e.name) for e in trace.events if e.kind == "state" and e.data.get("on") != "init"]
    return outs, states


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_firmware_matches_the_model(harness, name):
    fw_outs, fw_states, _ = firmware(harness, SCRIPTS[name])
    m_outs, m_states = model(SCRIPTS[name])
    assert fw_outs == m_outs
    assert fw_states == m_states


@pytest.mark.parametrize("n", DEFECTS)
@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_each_defect_switch_matches_the_model_mutant(build, n, name):
    fw_outs, fw_states, _ = firmware(build(n), SCRIPTS[name])
    m_outs, m_states = model(SCRIPTS[name], frozenset({f"M{n}"}))
    assert fw_outs == m_outs
    assert fw_states == m_states


#: Where each defect's own branch changes what the device does, by script: (time ms, request id) of
#: "defect fired". Later effects of an earlier firing (a stored result it caused) are not marked.
FIRED = {
    (1, "retries_and_repeats"): [(20, "r-0001"), (1500, "r-0001"), (4000, "r-0001"), (5200, "r-0002")],
    # not recorded until DONE or ERROR: the repeat runs again and its ERROR is stored, so the
    # repeat at 1500 is answered ERROR from the table; a later effect, not the defect's branch again
    (2, "retries_and_repeats"): [(20, "r-0001")],
    (4, "retries_and_repeats"): [(8050, "r-0004")],  # MOVE_UP taken while moving down
    (5, "retries_and_repeats"): [(2001, "s-0001"), (9001, "s-0002")],  # STATUS during a move
    (9, "retries_and_repeats"): [(20, "r-0001")],  # within the 50 ms before execution
    (10, "retries_and_repeats"): [(5200, "r-0002")],  # a refused id again: DONE
    (11, "retries_and_repeats"): [],  # every repeat is of the most recent id
    (11, "old_ids_again"): [(8000, "r-0001"), (8500, "r-0002")],
    (1, "old_ids_again"): [(8000, "r-0001"), (8500, "r-0002")],
    (2, "basic"): [], (4, "basic"): [], (10, "six_commands_with_polls"): [],
}


@pytest.mark.parametrize("n,name", sorted(FIRED))
def test_the_device_log_says_where_the_defect_fired(build, n, name):
    _, _, raw = firmware(build(n), SCRIPTS[name])
    lines = raw.splitlines()
    assert lines[1] == f"0 LOG build defect=M{n}"
    got = [(int(t), body.split()[-1]) for t, kind, body in (x.split(" ", 2) for x in lines)
           if kind == "LOG" and body.startswith("defect fired ")]
    assert got == FIRED[(n, name)]
    assert all(f"LOG defect fired M{n} " in x for x in lines if "defect fired" in x)


def test_no_defect_build_never_fires(harness):
    for name in SCRIPTS:
        assert "defect" not in firmware(harness, SCRIPTS[name])[2].split("\n", 2)[2]


def test_defect_3_and_unknown_numbers_do_not_build(tmp_path):
    for n in (3, 6, 12):
        res = subprocess.run([CXX, "-std=c++11", f"-DLIFT_DEFECT={n}", "-o", str(tmp_path / "x"),
                              str(FW / "harness" / "harness.cpp")], capture_output=True, text=True)
        assert res.returncode != 0 and "LIFT_DEFECT" in res.stderr


def test_firmware_says_ready_with_its_build_options_and_logs_its_side(harness):
    _, _, raw = firmware(harness, SCRIPTS["basic"])
    lines = raw.splitlines()
    assert lines[0] == "0 OUT READY log=1"  # never the defect: READY reaches the client log
    assert lines[1] == "0 LOG build defect=none"
    assert "0 LOG recv MOVE_UP r-0001" in lines and "50 LOG effect motor_start r-0001 dir=up" in lines
    assert "3050 LOG state UP r-0001 from=MOVING_UP on=arrived" in lines


def test_table_overflow_is_logged_as_an_error(harness):
    script = [(n * 4000, f"{'MOVE_UP' if n % 2 == 0 else 'MOVE_DOWN'} r-{n + 1:04d}") for n in range(9)] + [(40000, "END")]
    _, _, raw = firmware(harness, script)
    assert "LOG error table_full r-0009" in raw
    assert raw.count("OUT ACK r-0009") == 1  # still answered, but not recorded


def test_bad_input_is_an_error_line(harness):
    _, _, raw = firmware(harness, [(0, "MOVE_UP r-000000000000000001"), (10, "MOVE_UP"), (20, "END")])
    assert "LOG error id_too_long" in raw and "LOG error no_req_id MOVE_UP" in raw
    assert " OUT " not in raw.split("\n", 1)[1]


def test_log_off_build_keeps_replies_and_errors(tmp_path):
    exe = tmp_path / "harness0"
    subprocess.run([CXX, "-std=c++11", "-DLIFT_DEVICE_LOG=0", "-o", str(exe), str(FW / "harness" / "harness.cpp")],
                   check=True)
    raw = subprocess.run([str(exe)], input="0 MOVE_UP r-0001\n10 MOVE_UP\nEND 4000\n", capture_output=True,
                         text=True, check=True).stdout.splitlines()
    assert raw[0] == "0 OUT READY log=0"
    assert [r for r in raw if " LOG " in r] == ["0 LOG build defect=none", "10 LOG error no_req_id MOVE_UP"]
    assert "3050 OUT DONE r-0001" in raw
