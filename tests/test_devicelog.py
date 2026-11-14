"""Stage 1 of two sources: the device log read through an allow list and checked against the device
model with no link; the client and device logs counted against each other (replayspect.devicelog)."""

import json
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.devicelog import (INFERRED, OBSERVED_DEVICE, RECONSTRUCTED, Completeness, conform, count_check,
                                   device_report, read_device_log)
from replayspect.ingest import ingest_text, read_rules
from replayspect.runner import get_system

LIFT = get_system("lift.v0")
CLIENT_RULES = Path(__file__).parent.parent / "examples" / "testbed-uno" / "rules" / "testbed-client.yaml"
T = "2026-11-13T22:43:05.116898+09:00"


def dlog(*lines):
    return "".join(f"{T} # {x}\n" for x in lines)


#: A no-defect device: MOVE_UP r-0001 and its move, a poll during it, MOVE_DOWN r-0002 sent during
#: the move (refused 50 ms later), then the arrival.
NORMAL = [
    "0 build defect=none",
    "0 state DOWN from=- on=init",
    "4 recv MOVE_UP r-0001", "4 send ACK r-0001",
    "54 effect motor_start r-0001 dir=up", "54 state MOVING_UP r-0001 from=DOWN on=MOVE_UP",
    "1002 recv STATUS s-0001", "1002 send STATUS_REPLY s-0001 state=MOVING_UP",
    "2000 recv MOVE_DOWN r-0002", "2000 send ACK r-0002", "2050 send ERROR r-0002 reason=illegal",
    "3054 effect motor_stop r-0001", "3054 state UP r-0001 from=MOVING_UP on=arrived", "3054 send DONE r-0001",
    "4002 recv STATUS s-0002", "4002 send STATUS_REPLY s-0002 state=UP",
]
#: The same with M4: the opposite command taken during the move, the first move's DONE never sent.
M4_LOG = NORMAL[:10] + [
    "2050 defect fired M4 r-0002",
    "2050 effect motor_start r-0002 dir=down", "2050 state MOVING_DOWN r-0002 from=MOVING_UP on=MOVE_DOWN",
    "4002 recv STATUS s-0002", "4002 send STATUS_REPLY s-0002 state=MOVING_DOWN",
    "5050 effect motor_stop r-0002", "5050 state DOWN r-0002 from=MOVING_DOWN on=arrived", "5050 send DONE r-0002",
    "6000 recv STATUS s-0003", "6000 send STATUS_REPLY s-0003 state=DOWN",
]


def test_only_recv_send_state_and_effect_lines_become_events():
    text = dlog(*NORMAL, "2051 defect fired M4 r-0002", "2052 something new r-0002", "garbage") + "no hash line\n"
    log = read_device_log(text)
    assert {e.kind for e in log.events} == {"recv", "send", "state", "effect"}
    assert len(log.events) == len(NORMAL) - 1  # the build line is not an event
    assert all(e.actor == "device" and e.source == "adapter:device-log" for e in log.events)
    assert not any("defect" in json.dumps(e.to_dict()) for e in log.events)
    e = log.events[0]
    assert (e.t_us, e.kind, e.name, e.req_id, dict(e.data)) == (0, "state", "DOWN", None, {"from": None, "on": "init"})
    e = log.events[9]
    assert (e.t_us, e.kind, e.name, e.req_id, dict(e.data)) == (2050_000, "send", "ERROR", "r-0002", {"reason": "illegal"})
    assert log.valid


def test_an_error_line_makes_the_log_invalid():
    log = read_device_log(dlog(*NORMAL, "5000 error queue_full r-0003"))
    assert not log.valid and log.errors == ("queue_full r-0003",)
    rep = device_report(LIFT, log)
    assert rep["valid"] is False and rep["errors"] == ["queue_full r-0003"]


def test_a_device_that_follows_the_model_conforms():
    c = conform(LIFT, read_device_log(dlog(*NORMAL)))
    assert c.conforms and c.first is None and c.matched == c.compared == len(NORMAL) - 5  # 4 recv, 1 build


def test_the_first_mismatch_says_when_in_what_state_on_what_input_device_and_model_differ():
    log = read_device_log(dlog(*M4_LOG))
    c = conform(LIFT, log)
    assert not c.conforms
    assert c.first == {
        "t_us": 2050_000, "req_id": "r-0002",
        "model": {"t_us": 2050_000, "event": "send ERROR r-0002 reason=illegal", "fidelity": RECONSTRUCTED},
        "device": {"t_us": 2050_000, "event": "effect motor_start r-0002 dir=down", "fidelity": OBSERVED_DEVICE},
        "model_state": "MOVING_UP",
        "last_input": {"t_us": 2000_000, "event": "recv MOVE_DOWN r-0002", "fidelity": OBSERVED_DEVICE}}
    assert conform(LIFT, log, ("M4",)).conforms


def test_in_one_millisecond_the_timers_run_before_the_input():
    # The firmware runs the timers due in a millisecond first, then one input line (testbed-uno README,
    # difference 3); its log shows that order. Here the arrival and a poll fall in the same millisecond:
    # the poll sees UP. The model, fed the poll at that millisecond, must do the same.
    lines = NORMAL[:8] + ["3054 effect motor_stop r-0001", "3054 state UP r-0001 from=MOVING_UP on=arrived",
                          "3054 send DONE r-0001", "3054 recv STATUS s-0002", "3054 send STATUS_REPLY s-0002 state=UP"]
    assert conform(LIFT, read_device_log(dlog(*lines))).conforms


def test_an_event_later_than_the_window_is_a_mismatch():
    lines = [x.replace("3054 ", "3057 ") for x in NORMAL]
    c = conform(LIFT, read_device_log(dlog(*lines)))
    assert not c.conforms and c.first["t_us"] == 3054_000
    assert conform(LIFT, read_device_log(dlog(*lines)), late_us=3_000).conforms


def test_the_report_is_the_same_with_or_without_lines_outside_the_allow_list():
    bare = [x for x in M4_LOG if "defect" not in x]
    rep = [json.dumps(device_report(LIFT, read_device_log(dlog(*x)), ["M1", "M2", "M4", "M10"]), sort_keys=True)
           for x in (M4_LOG, bare, bare + ["7000 build defect=M4", "7000 note anything"])]
    assert rep[0] == rep[1] == rep[2]


# -- the count check ----------------------------------------------------------------------------

CLIENT = [
    "# testbed client: firmware log=1; think_seed=306; plan=P40; commands=6; run_s=90; started=x",
    "TX MOVE_UP req=r-0001", "RX ACK req=r-0001", "TX STATUS req=s-0001",
    "TX MOVE_DOWN req=r-0002", "RX ACK req=r-0002", "RX ERROR req=r-0002 reason=illegal", "RX ERROR req=r-0002 reason=illegal",
    "RX DONE req=r-0001", "TX STATUS req=s-0002", "RX STATUS_REPLY req=s-0002 state=UP",
]


def client_events(lines):
    text = "".join(f"2026-11-13T22:43:{5 + i:02d}.000000+09:00 {x}\n" for i, x in enumerate(lines))
    return ingest_text(text.encode(), read_rules(CLIENT_RULES)).events


ALL = Completeness.parse(["device:send,recv", "client:send,recv"])


def test_losses_and_extra_copies_are_counted_per_message_and_request_id():
    # the client polled s-0001 but the device never received it; the ERROR of r-0002 reached the client twice
    log = read_device_log(dlog(*[x for x in NORMAL if "s-0001" not in x]))
    c = count_check(client_events(CLIENT), log, ALL)
    assert c["items"] == [
        {"dir": "c2s", "msg": "STATUS", "req_id": "s-0001", "what": "lost", "n": 1, "exact": True, "fidelity": INFERRED},
        {"dir": "s2c", "msg": "ERROR", "req_id": "r-0002", "what": "extra copy", "n": 1, "exact": True,
         "fidelity": INFERRED}]
    assert c["not_inferred"] == []


def test_nothing_is_inferred_from_absence_on_a_side_not_declared_complete():
    log = read_device_log(dlog(*[x for x in NORMAL if "s-0001" not in x]))
    assert count_check(client_events(CLIENT), log, Completeness())["items"] == []
    c = count_check(client_events(CLIENT), log, Completeness.parse(["device:recv"]))
    # the loss needs only the device's receives complete; the client's sends may be missing some, so
    # the count is a lower bound; the extra copy needs the device's sends complete
    assert c["items"] == [{"dir": "c2s", "msg": "STATUS", "req_id": "s-0001", "what": "lost", "n": 1,
                           "exact": False, "fidelity": INFERRED}]
    assert c["not_inferred"] == ["client send", "client recv", "device send"]
    with pytest.raises(ValueError):
        Completeness.parse(["device:handle"])


def test_a_loss_and_an_extra_copy_of_the_same_message_cancel_out():
    # A limit, not a wish (testbed-02 R03: MOVE_DOWN r-0004 lost once and copied once): sent twice,
    # received twice, nothing to see by count.
    # The client sent MOVE_DOWN r-0002 twice (a retry); the first was lost, the second copied.
    client = ["TX MOVE_UP req=r-0001", "RX ACK req=r-0001", "TX STATUS req=s-0001",
              "RX STATUS_REPLY req=s-0001 state=MOVING_UP", "TX MOVE_DOWN req=r-0002", "TX MOVE_DOWN req=r-0002",
              "RX ACK req=r-0002", "RX ACK req=r-0002", "RX ERROR req=r-0002 reason=illegal", "RX DONE req=r-0001",
              "TX STATUS req=s-0002", "RX STATUS_REPLY req=s-0002 state=UP"]
    lines = NORMAL[:10] + ["2010 recv MOVE_DOWN r-0002", "2010 send ACK r-0002"] + NORMAL[10:]
    assert count_check(client_events(client), read_device_log(dlog(*lines)), ALL)["items"] == []


def test_the_client_log_header_never_reaches_the_result():
    # the testbed client's first line names the plan and the seed; ingest skips it as a comment
    with_header, without = client_events(CLIENT), client_events(CLIENT[1:])
    assert [e.to_dict() for e in with_header] == [e.to_dict() for e in without]
    assert not any("P40" in json.dumps(e.to_dict()) or "306" in json.dumps(e.to_dict()) for e in with_header)
    log = read_device_log(dlog(*NORMAL))
    a, b = (json.dumps(device_report(LIFT, log, ["M4"], c, ALL), sort_keys=True) for c in (with_header, without))
    assert a == b


def test_every_report_item_says_how_it_is_known():
    log = read_device_log(dlog(*M4_LOG))
    rep = device_report(LIFT, log, ["M4"], client_events(CLIENT), ALL)
    assert rep["fidelity"] == OBSERVED_DEVICE
    first = rep["models"][0]["first"]
    assert first["model"]["fidelity"] == RECONSTRUCTED and first["device"]["fidelity"] == OBSERVED_DEVICE
    assert all(x["fidelity"] == INFERRED for x in rep["counts"]["items"])
    assert rep["conforming"] == ["M4"]


# -- the command line ---------------------------------------------------------------------------


def test_cli_device(tmp_path, capsys):
    dev = tmp_path / "device.log"
    dev.write_text(dlog(*M4_LOG))
    cl = tmp_path / "client.log"
    cl.write_text("".join(f"2026-11-13T22:43:{5 + i:02d}.000000+09:00 {x}\n" for i, x in enumerate(CLIENT)))
    trace = tmp_path / "client.jsonl"
    assert main(["ingest", str(cl), "--rules", str(CLIENT_RULES), "--out", str(trace)]) == 0
    capsys.readouterr()
    out = tmp_path / "rep.json"
    code = main(["device", str(dev), "--models", "M2,M4", "--client", str(trace), "--complete", "device:send,recv",
                 "--complete", "client:send,recv", "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 1  # the correct model does not conform
    assert "correct: first mismatch at 2.050s (r-0002): model send ERROR r-0002 reason=illegal, device effect " \
           "motor_start r-0002 dir=down; model state MOVING_UP, last input recv MOVE_DOWN r-0002" in text
    assert "M4: conforms" in text and "conforming models: M4" in text
    assert "count check (inferred: count" in text
    rep = json.loads(out.read_text())
    assert rep["conforming"] == ["M4"] and [m["model"] for m in rep["models"]] == ["correct", "M2", "M4"]
    dev.write_text(dlog(*NORMAL))
    assert main(["device", str(dev)]) == 0
    assert "correct: conforms" in capsys.readouterr().out
    assert main(["device", str(dev), "--models", "M6"]) == 2  # a client defect is not a device model
    assert main(["device", str(dev), "--complete", "device:recv"]) == 2  # no --client
    dev.write_text("nothing here\n")
    assert main(["device", str(dev)]) == 2
