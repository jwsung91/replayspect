"""The turntable firmware's state machine (turntable_device.h) against the Python turntable model.

As for the lift (test_testbed_conformance.py): the header is compiled natively with the harness
(``-DHARNESS_TURNTABLE=1``) and fed the same timed message sequences as the model
(src/replayspect/sut/turntable.py). Replies, state changes and motor effects must match. Scripts
avoid an input arriving in the same millisecond as a timer.
"""

import json
import shutil
import subprocess

import pytest
from test_testbed_conformance import FW, _Channel

from replayspect.__main__ import main
from replayspect.sim.link import Message
from replayspect.sim.scheduler import Scheduler
from replayspect.sut.turntable import SEQUENCE, TurntableDevice
from replayspect.trace import Trace

CXX = shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
pytestmark = pytest.mark.skipif(CXX is None, reason="no C++ compiler")

SCRIPTS = {
    # the client's six commands, each after the previous DONE, with polls during the turns
    "sequence_with_polls": [x for n, cmd in enumerate(SEQUENCE) for x in (
        (n * 6000 + 13, f"{cmd} r-{n + 1:04d}"),
        (n * 6000 + 1007, f"STATUS s-{2 * n + 1:04d}"), (n * 6000 + 4007, f"STATUS s-{2 * n + 2:04d}"))]
        + [(40000, "END")],
    "limits_and_repeats": [
        (0, "TURN_LEFT r-0001"), (20, "TURN_LEFT r-0001"),       # repeat while queued: ACK again
        (1500, "TURN_LEFT r-0001"),                               # repeat while turning: ACK again
        (2001, "TURN_RIGHT r-0002"),                              # while turning: illegal
        (4000, "TURN_LEFT r-0001"),                               # repeat after DONE: DONE again
        (4500, "TURN_LEFT r-0003"),                               # at LEFT: limit
        (5200, "TURN_LEFT r-0003"),                               # repeat of a refused id: same reason
        (5300, "TURN_RIGHT r-0002"),                              # repeat of the illegal one: illegal
        (6000, "PING r-0009"),                                    # unknown: ignored
        (7000, "TURN_RIGHT r-0004"), (11000, "TURN_RIGHT r-0005"),  # LEFT -> INITIAL -> RIGHT
        (15000, "TURN_RIGHT r-0006"),                             # at RIGHT: limit
        (15500, "STATUS s-0001"), (16000, "END")],
    "two_new_ids_within_50ms": [(0, "TURN_RIGHT r-0001"), (30, "TURN_LEFT r-0002"), (6000, "END")],
    "right_then_back": [(0, "TURN_RIGHT r-0001"), (4000, "TURN_LEFT r-0002"), (4100, "STATUS s-0001"),
                        (8000, "TURN_LEFT r-0003"), (12000, "END")],
}


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    out = tmp_path_factory.mktemp("fw") / "turntable_harness"
    subprocess.run([CXX, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-O1", "-DHARNESS_TURNTABLE=1",
                    "-o", str(out), str(FW / "harness" / "harness.cpp")], check=True)
    return out


def firmware(harness, script):
    text = "".join(f"{t} {line}\n" if line != "END" else f"END {t}\n" for t, line in script)
    res = subprocess.run([str(harness)], input=text, capture_output=True, text=True, check=True)
    outs, states, effects = [], [], []
    for row in res.stdout.splitlines():
        t, kind, body = row.split(" ", 2)
        words = body.split()
        if kind == "OUT" and not body.startswith("READY"):
            outs.append((int(t), body))
        elif kind == "LOG" and words[0] == "state" and "on=init" not in body:
            states.append((int(t), words[1]))
        elif kind == "LOG" and words[0] == "effect":
            effects.append((int(t), " ".join(words[1:])))
    return outs, states, effects, res.stdout


def model(script):
    sched = Scheduler(0)
    trace = Trace(lambda: sched.now_us)
    outs = []
    ch = _Channel(sched, outs)
    TurntableDevice(sched, trace, ch, frozenset())
    end = 0
    for t, line in script:
        if line == "END":
            end = t
            continue
        name, rid = line.split()
        sched.at_us(t * 1000, lambda n=name, r=rid: ch.on_message(Message(n, r, {})))
    sched.run_until_us(end * 1000)
    ms = [e for e in trace.events if e.t_us <= end * 1000]
    states = [(e.t_us // 1000, e.name) for e in ms if e.kind == "state" and e.data.get("on") != "init"]
    effects = [(e.t_us // 1000, f"{e.name} {e.req_id}" + (f" dir={e.data['dir']}" if e.data.get("dir") else ""))
               for e in ms if e.kind == "effect"]
    return outs, states, effects


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_turntable_firmware_matches_the_model(harness, name):
    fw_outs, fw_states, fw_effects, _ = firmware(harness, SCRIPTS[name])
    m_outs, m_states, m_effects = model(SCRIPTS[name])
    assert fw_outs == m_outs
    assert fw_states == m_states
    assert fw_effects == m_effects


def test_turntable_scripts_reach_every_reply_and_state(harness):
    """The scripts exercise both refusal reasons and every state, so the match above means something."""
    seen = set()
    for script in SCRIPTS.values():
        outs, states, _, _ = firmware(harness, script)
        seen |= {body.split()[0] + (" " + body.split()[2] if body.startswith("ERROR") else "") for _, body in outs}
        seen |= {s for _, s in states}
    assert {"ACK", "DONE", "ERROR reason=limit", "ERROR reason=illegal", "STATUS_REPLY",
            "LEFT", "RIGHT", "INITIAL", "TURNING_TO_LEFT", "TURNING_TO_RIGHT", "TURNING_TO_INITIAL"} <= seen


def test_turntable_build_line_names_no_defect(harness):
    _, _, _, raw = firmware(harness, [(0, "STATUS s-0001"), (10, "END")])
    assert "0 OUT READY log=1" in raw.splitlines()
    assert "0 LOG build system=turntable.v0 defect=none" in raw.splitlines()


# -- the harness's device log read by `replayspect device` (WP6/7c stage 1) ------------------------

ROOT = FW.parents[2]
STAMP = "2026-11-22T10:00:00.000000+09:00"


def device_log(raw: str) -> str:
    """The harness's LOG lines in the device log's form (the link writes '<stamp> # <ms> <body>'); the
    build line goes to the truth file, as on the board."""
    return "".join(f"{STAMP} # {t} {body}\n" for t, kind, body in (r.split(" ", 2) for r in raw.splitlines())
                   if kind == "LOG" and not body.startswith("build"))


def device_check(tmp_path, harness, name, contracts=None):
    dev = tmp_path / f"{name}.log"
    dev.write_text(device_log(firmware(harness, SCRIPTS[name])[3]))
    out = tmp_path / f"{name}-{bool(contracts)}-{len(list(tmp_path.iterdir()))}.json"
    args = ["device", str(dev), "--system", "turntable.v0", "--complete", "device:recv,send,state,effect",
            "--out", str(out)]
    code = main(args + (["--contracts", str(contracts)] if contracts else []))
    return code, json.loads(out.read_text())


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_device_reads_the_harness_log_and_the_model_conforms(tmp_path, harness, name):
    for contracts in (None, ROOT / "contracts" / "turntable.v0.yaml", ROOT / "contracts" / "generic" / "turntable.v0.yaml"):
        code, rep = device_check(tmp_path, harness, name, contracts)
        assert code == 0 and rep["conforming"] == ["correct"]
        if contracts:
            k = rep["contracts"]
            assert k["violated"] == [] and k["not_judged"] == [], (contracts.name, k)


def test_which_contracts_the_harness_logs_exercise(tmp_path, harness):
    """Recorded, not a goal: the union over the scripts of the contracts each set exercised. C2, C4 and C6
    are the client's, never exercised on a device log alone."""
    seen = {}
    for path in (ROOT / "contracts" / "turntable.v0.yaml", ROOT / "contracts" / "generic" / "turntable.v0.yaml"):
        ok, idle = set(), set()
        for name in SCRIPTS:
            k = device_check(tmp_path, harness, name, path)[1]["contracts"]
            ok |= set(k["ok"])
            idle |= set(k["not_exercised"])
        seen[path.parent.name] = (sorted(ok), sorted(idle - ok))
    assert seen == {
        "contracts": (["C1", "C3", "C5", "C7", "C8"], ["C2", "C4", "C6"]),
        "generic": (["G1.motor_start", "G1.motor_stop", "G2.ack", "G2.final", "G2.poll.STATUS", "G3", "G4", "G5",
                     "G6", "G6b", "P1"], []),
    }, seen


def test_fired_points_compares_a_changed_turntable_header_with_an_unchanged_one(tmp_path):
    # As the lift's operator workflow (test_testbed_conformance.py), on turntable_device.h: a turn runs
    # 60 ms after its ACK, not 50. The turntable has no defect switch, so only --reference is offered.
    import sys
    changed_dir, ref_dir = tmp_path / "changed", tmp_path / "reference"
    shutil.copytree(FW, changed_dir)
    shutil.copytree(FW, ref_dir)
    h = changed_dir / "turntable_uno" / "turntable_device.h"
    src = h.read_text()
    assert "const uint32_t PROC_MS = 50;" in src
    h.write_text(src.replace("const uint32_t PROC_MS = 50;", "const uint32_t PROC_MS = 60;"))
    exe = tmp_path / "board"
    subprocess.run([CXX, "-std=c++11", "-O1", "-DHARNESS_TURNTABLE=1", "-o", str(exe),
                    str(changed_dir / "harness" / "harness.cpp")], check=True)
    tool = [sys.executable, str(changed_dir / "harness" / "fired_points.py")]
    log = tmp_path / "device.log"
    log.write_text(device_log(firmware(exe, SCRIPTS["right_then_back"])[3]))
    out = subprocess.run(tool + [str(log), "--system", "turntable", "--reference", str(ref_dir)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"t_ms": 50, "req_id": "r-0001",
                                      "changed": "60 LOG effect motor_start r-0001 dir=right",
                                      "reference": "50 LOG effect motor_start r-0001 dir=right"}
    quiet = tmp_path / "quiet.log"
    quiet.write_text(device_log(firmware(exe, [(0, "STATUS s-0001"), (100, "END")])[3]))
    out = subprocess.run(tool + [str(quiet), "--system", "turntable", "--reference", str(ref_dir)],
                         capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout) == {"difference": None}
    # the lift's harness does not reproduce a turntable log; --defect has no meaning here
    assert subprocess.run(tool + [str(log), "--reference", str(ref_dir)], capture_output=True).returncode == 1
    assert subprocess.run(tool + [str(log), "--system", "turntable", "--defect", "0"], capture_output=True).returncode == 2
