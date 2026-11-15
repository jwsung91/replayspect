"""The order of one request's outputs in the device comparison (WP6/7b stage 1).

The logs are made by the lift simulator (correct device) and written in the device-log format, then
changed by hand: the arrival lines of one request put in another order, a poll of another request moved
inside the same millisecond, an event removed."""

import itertools

import pytest

from replayspect.devicelog import (OBSERVED_DEVICE, RECONSTRUCTED, Completeness, conform, device_report,
                                   read_device_log, report_lines)
from replayspect.runner import get_system

LIFT = get_system("lift.v0")
ALL = Completeness.parse(["device:recv,send,state,effect"])
T = "2026-11-15T17:00:00.000000+09:00"
SEED = 0


def line(e) -> str:
    """One simulator device event as the testbed firmware logs it (ms, kind, name, id, fields)."""
    fields = " ".join(f"{k}={'-' if v is None else v}" for k, v in e.data.items() if k != "link")
    return " ".join(x for x in (str(e.t_us // 1000), e.kind, e.name, e.req_id or "", fields) if x)


def sim_lines(seed=SEED, mutants=()):
    trace = LIFT.run(seed, None, tuple(mutants), LIFT.until_us)
    return [line(e) for e in trace.events if e.actor == "device"]


def text(lines):
    return "".join(f"{T} # {x}\n" for x in lines)


def arrival(lines, nth=0):
    """Index of the nth arrival's three lines (motor stop, state, DONE) and its request id."""
    starts = [i for i, x in enumerate(lines) if " effect motor_stop " in x]
    i = starts[nth]
    rid = lines[i].split()[3]
    assert [lines[i + j].split()[1:4] for j in range(3)] == [
        ["effect", "motor_stop", rid], ["state", lines[i + 1].split()[2], rid], ["send", "DONE", rid]]
    return i, rid


def test_a_simulator_made_log_conforms():
    lines = sim_lines()
    c = conform(LIFT, read_device_log(text(lines)), complete=ALL)
    assert c.conforms and c.order_differences == 0
    assert arrival(lines)  # the seed has an arrival to reorder


WRONG_ORDERS = [p for p in itertools.permutations(range(3)) if p != (0, 1, 2)]


@pytest.mark.parametrize("perm", WRONG_ORDERS, ids=lambda p: "".join("SXD"[i] for i in p))
def test_the_three_arrival_lines_in_any_other_order_differ(perm):
    lines = sim_lines()
    i, rid = arrival(lines)
    ms = int(lines[i].split()[0]) * 1000
    block = lines[i:i + 3]
    changed = lines[:i] + [block[j] for j in perm] + lines[i + 3:]
    c = conform(LIFT, read_device_log(text(changed)), complete=ALL)
    assert c.status == "differs" and c.mismatches == 0 and c.order_differences == 1
    f = c.first
    assert (f["kind"], f["t_us"], f["req_id"]) == ("order", ms, rid)
    # the first logged line out of place, and the model's event at its position
    k = next(n for n in range(3) if perm[n] != n)
    assert f["device"] == {"t_us": ms, "event": " ".join(block[perm[k]].split()[1:]), "fidelity": OBSERVED_DEVICE}
    assert f["model"] == {"t_us": ms, "event": " ".join(block[k].split()[1:]), "fidelity": RECONSTRUCTED}
    # both orders, from the first line out of place to the last
    last = max(n for n in range(3) if perm[n] != n)
    assert [x["event"] for x in f["model_order"]] == [" ".join(block[n].split()[1:]) for n in range(k, last + 1)]
    assert [x["event"] for x in f["device_order"]] == [" ".join(block[perm[n]].split()[1:])
                                                      for n in range(k, last + 1)]


def test_another_request_reordered_in_the_same_millisecond_is_no_mismatch():
    # A poll that falls in the arrival's millisecond: the firmware runs the timer first, so the reply says
    # UP. Logged before the arrival lines, it is out of the model's order, but on another request id.
    lines = sim_lines()
    i, rid = arrival(lines)
    ms = lines[i].split()[0]
    state = lines[i + 1].split()[2]
    poll = [f"{ms} recv STATUS s-9001", f"{ms} send STATUS_REPLY s-9001 state={state}"]
    c = conform(LIFT, read_device_log(text(lines[:i] + poll + lines[i:])), complete=ALL)
    assert c.conforms and c.order_differences == 0


def test_when_both_kinds_occur_the_earlier_is_reported():
    lines = sim_lines()
    i, rid = arrival(lines, 0)
    j, rid2 = arrival(lines, 1)
    ms, ms2 = (int(lines[x].split()[0]) * 1000 for x in (i, j))
    assert ms < ms2
    swapped = lines[:i] + [lines[i + 2], lines[i], lines[i + 1]] + lines[i + 3:]  # DONE first, at ms
    # order earlier, an unmatched event later: the second arrival's DONE is missing
    first_order = [x for n, x in enumerate(swapped) if n != j + 2]
    c = conform(LIFT, read_device_log(text(first_order)), complete=ALL)
    assert (c.first["kind"], c.first["t_us"], c.first["req_id"]) == ("order", ms, rid)
    assert c.mismatches == 1 and c.order_differences == 1
    # an unmatched event earlier, the order later
    late = lines[:j] + [lines[j + 2], lines[j], lines[j + 1]] + lines[j + 3:]
    first_event = [x for n, x in enumerate(late) if n != i + 2]
    c = conform(LIFT, read_device_log(text(first_event)), complete=ALL)
    assert (c.first["kind"], c.first["t_us"], c.first["req_id"]) == ("event", ms, rid)
    assert c.first["model"]["event"] == f"send DONE {rid}" and c.first["device"] is None
    assert c.mismatches == 1 and c.order_differences == 1


def test_order_is_a_switch():
    lines = sim_lines()
    i, _ = arrival(lines)
    log = read_device_log(text(lines[:i] + [lines[i + 2], lines[i], lines[i + 1]] + lines[i + 3:]))
    assert conform(LIFT, log, complete=ALL).status == "differs"
    c = conform(LIFT, log, complete=ALL, order="ignore")
    assert c.conforms and c.order_differences == 0
    with pytest.raises(ValueError):
        conform(LIFT, log, complete=ALL, order="sometimes")


def test_defect_models_use_the_same_rule():
    # M4: the opposite command taken during a move. On a log that shows it, M4 conforms; with one of its
    # arrivals reordered, M4 differs on that order as the correct model would.
    seed = next(s for s in range(200) if conform(LIFT, read_device_log(text(sim_lines(s, ["M4"]))), ("M4",),
                                                   complete=ALL).conforms
                and not conform(LIFT, read_device_log(text(sim_lines(s, ["M4"]))), complete=ALL).conforms)
    lines = sim_lines(seed, ["M4"])
    i, rid = arrival(lines)
    changed = lines[:i] + [lines[i + 2], lines[i], lines[i + 1]] + lines[i + 3:]
    c = conform(LIFT, read_device_log(text(changed)), ("M4",), complete=ALL)
    assert c.status == "differs" and c.first["kind"] == "order" and c.first["req_id"] == rid


def test_only_matched_events_are_compared_for_order():
    # State lines not logged and not declared complete: nothing is inferred from their absence, and the
    # matched events (the stop and DONE) are still compared for order.
    lines = [x for x in sim_lines() if x.split()[1] != "state"]
    partial = Completeness.parse(["device:recv,send,effect"])
    assert conform(LIFT, read_device_log(text(lines)), complete=partial).conforms
    i = next(n for n, x in enumerate(lines) if " effect motor_stop " in x)
    rid = lines[i].split()[3]
    assert lines[i + 1].split()[1:4] == ["send", "DONE", rid]
    swapped = lines[:i] + [lines[i + 1], lines[i]] + lines[i + 2:]
    c = conform(LIFT, read_device_log(text(swapped)), complete=partial)
    assert c.status == "differs" and c.first["kind"] == "order" and c.mismatches == 0


def test_the_report_tells_the_two_kinds_apart():
    lines = sim_lines()
    i, rid = arrival(lines)
    log = read_device_log(text(lines[:i] + [lines[i + 2], lines[i], lines[i + 1]] + lines[i + 3:]))
    rep = device_report(LIFT, log, complete=ALL)
    row = rep["models"][0]
    assert row["first"]["kind"] == "order" and row["order_differences"] == 1
    out = "\n".join(report_lines(rep))
    assert "order difference" in out
    assert f"model order: effect motor_stop {rid}" in out and f"device order: send DONE {rid}" in out
    # an unmatched event keeps its wording, with the kind in the JSON
    missing = read_device_log(text([x for n, x in enumerate(lines) if n != i + 2]))
    rep = device_report(LIFT, missing, complete=ALL)
    assert rep["models"][0]["first"]["kind"] == "event"
    assert "order difference" not in "\n".join(report_lines(rep))


def repeat_of(lines, rid, ms):
    """A repeat of request ``rid`` arriving in millisecond ``ms`` and the DONE it is answered with."""
    cmd = next(x.split()[2] for x in lines if x.split()[1:2] == ["recv"] and x.split()[3:4] == [rid])
    return [f"{ms} recv {cmd} {rid}", f"{ms} send DONE {rid}"]


def test_a_repeat_in_the_arrival_millisecond_logged_after_the_arrival_conforms():
    # The firmware runs the arrival (a timer) before the input of the same millisecond: the repeat finds the
    # request finished and is answered DONE, after the arrival's own DONE.
    lines = sim_lines()
    i, rid = arrival(lines)
    ms = lines[i].split()[0]
    changed = lines[:i + 3] + repeat_of(lines, rid, ms) + lines[i + 3:]
    c = conform(LIFT, read_device_log(text(changed)), complete=ALL)
    assert c.conforms and c.order_differences == 0


def test_a_repeat_in_the_arrival_millisecond_logged_before_the_motor_stop_is_an_order_difference():
    lines = sim_lines()
    i, rid = arrival(lines)
    ms = lines[i].split()[0]
    changed = lines[:i] + repeat_of(lines, rid, ms) + lines[i:]
    c = conform(LIFT, read_device_log(text(changed)), complete=ALL)
    assert c.status == "differs" and c.mismatches == 0
    f = c.first
    assert (f["kind"], f["t_us"], f["req_id"]) == ("order", int(ms) * 1000, rid)
    assert f["model"]["event"] == f"effect motor_stop {rid}" and f["device"]["event"] == f"send DONE {rid}"
