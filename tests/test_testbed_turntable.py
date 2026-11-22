"""The turntable firmware's state machine (turntable_device.h) against the Python turntable model.

As for the lift (test_testbed_conformance.py): the header is compiled natively with the harness
(``-DHARNESS_TURNTABLE=1``) and fed the same timed message sequences as the model
(src/replayspect/sut/turntable.py). Replies, state changes and motor effects must match. Scripts
avoid an input arriving in the same millisecond as a timer.
"""

import shutil
import subprocess

import pytest
from test_testbed_conformance import FW, _Channel

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
    assert "0 LOG build defect=none" in raw.splitlines()
