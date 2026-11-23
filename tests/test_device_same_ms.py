"""The first mismatch inside one millisecond (WP6/7d stage 0a).

When the earliest unmatched model event and the earliest unmatched logged event are at exactly the same
time and on different requests, the order of the log's lines decides which is reported, not the side. A
model event has no line; it is placed right after the last line, in that millisecond, of what the model did
or received before it (nothing before it: the start of the millisecond). An order difference and an
unmatched event at the same time follow the same rule on different requests; on the same request the
unmatched event is reported, as before.

The logs are made by the turntable simulator (correct device), written in the device-log format, then changed
by hand. testbed-07 S17 is the first case: a turn that ends early, and in that millisecond a poll of another
request answered with the new state."""

import pytest

from replayspect.devicelog import Completeness, conform, read_device_log
from replayspect.runner import get_system

TT = get_system("turntable.v0")
ALL = Completeness.parse(["device:recv,send,state,effect"])
T = "2026-11-23T07:00:00.000000+09:00"
SEED = 0


def line(e) -> str:
    fields = " ".join(f"{k}={'-' if v is None else v}" for k, v in e.data.items() if k != "link")
    return " ".join(x for x in (str(e.t_us // 1000), e.kind, e.name, e.req_id or "", fields) if x)


def sim_lines(seed=SEED):
    trace = TT.run(seed, None, (), TT.until_us)
    return [line(e) for e in trace.events if e.actor == "device" and e.kind in ("recv", "send", "state", "effect")]


def text(lines):
    return "".join(f"{T} # {x}\n" for x in lines)


def first(lines, order="per-request"):
    c = conform(TT, read_device_log(text(lines)), complete=ALL, order=order)
    assert c.status == "differs"
    return c


def ms(x):
    return int(x.split()[0])


def poll_in_turn(lines):
    """A turn (its request, start ms, the indexes of its three arrival lines) and a poll during it whose
    id occurs once: the index of the poll's recv line, its id and ms."""
    for i, x in enumerate(lines):
        f = x.split()
        if f[1:3] != ["effect", "motor_start"]:
            continue
        rid, start = f[3], int(f[0])
        stop = next(j for j in range(i, len(lines)) if lines[j].split()[1:4] == ["effect", "motor_stop", rid])
        for k in range(i, stop):
            g = lines[k].split()
            if g[1:3] == ["recv", "STATUS"] and ms(lines[k]) > start + 100 and ms(lines[stop]) - ms(lines[k]) > 100:
                sid = g[3]
                if sum(1 for y in lines if y.split()[1:4] == ["recv", "STATUS", sid]) == 1:
                    assert lines[k + 1].split()[1:4] == ["send", "STATUS_REPLY", sid]
                    return rid, (stop, stop + 1, stop + 2), k, sid
    raise AssertionError("no poll during a turn in this seed")


def early_arrival(lines, before_poll: bool):
    """S17's shape: the turn's three arrival lines moved into the poll's millisecond (before or after the
    poll's two lines), and the poll answered with the arrived state."""
    rid, arr, k, sid = poll_in_turn(lines)
    p = ms(lines[k])
    moved = [" ".join([str(p)] + lines[j].split()[1:]) for j in arr]
    target = lines[arr[1]].split()[2]
    reply = f"{p} send STATUS_REPLY {sid} state={target}"
    rest = [x for j, x in enumerate(lines) if j not in arr and j not in (k, k + 1)]
    at = rest.index(next(x for x in rest if ms(x) > p))
    poll = [lines[k], reply]
    block = moved + poll if before_poll else poll + moved
    return rest[:at] + block + rest[at:], rid, sid, p


def test_the_simulator_log_conforms():
    assert conform(TT, read_device_log(text(sim_lines())), complete=ALL).conforms


def test_s17_shape_an_early_output_first_in_the_log_is_reported():
    lines, rid, sid, p = early_arrival(sim_lines(), before_poll=True)
    c = first(lines)
    assert (c.first["t_us"], c.first["req_id"]) == (p * 1000, rid)
    assert c.first["model"] is None and c.first["device"]["event"] == f"effect motor_stop {rid}"


def test_the_same_with_the_poll_first_in_the_log_reports_the_poll():
    lines, rid, sid, p = early_arrival(sim_lines(), before_poll=False)
    c = first(lines)
    assert (c.first["t_us"], c.first["req_id"]) == (p * 1000, sid)


def test_only_the_reported_event_changes_not_the_verdict_or_the_count():
    lines, *_ = early_arrival(sim_lines(), before_poll=True)
    other, *_ = early_arrival(sim_lines(), before_poll=False)
    a, b = first(lines), first(other)
    assert (a.status, a.mismatches, a.matched) == (b.status, b.mismatches, b.matched)


@pytest.mark.parametrize("extra_first", [True, False])
def test_a_missing_output_and_another_requests_extra_line_in_one_millisecond(extra_first):
    """The poll's reply is gone, and a line of the turning request is added in that millisecond. The
    missing reply is placed right after the poll's recv line; the extra line is reported when the log
    has it before that line, the missing reply when the log has the extra line after it."""
    lines = sim_lines()
    rid, _, k, sid = poll_in_turn(lines)
    p = ms(lines[k])
    extra = f"{p} send ACK {rid}"
    block = [extra, lines[k]] if extra_first else [lines[k], extra]
    lines = lines[:k] + block + lines[k + 2:]
    c = first(lines)
    assert c.first["t_us"] == p * 1000
    if extra_first:
        assert c.first["req_id"] == rid and c.first["device"]["event"] == f"send ACK {rid}"
        assert c.first["model"] is None
    else:
        assert c.first["req_id"] == sid and c.first["model"]["event"] == f"send STATUS_REPLY {sid} state=" \
            + c.first["model"]["event"].split("state=")[1]
        assert c.first["device"] is None


def test_candidates_at_different_times_inside_the_window_are_decided_by_time():
    """The extra line 1 ms after the missing reply: the earlier, the missing reply, is reported."""
    lines = sim_lines()
    rid, _, k, sid = poll_in_turn(lines)
    p = ms(lines[k])
    lines = lines[:k] + [lines[k], f"{p + 1} send ACK {rid}"] + lines[k + 2:]
    c = first(lines)
    assert (c.first["t_us"], c.first["req_id"]) == (p * 1000, sid)


def reordered_arrival(lines):
    """The first arrival's lines with the state before the motor stop: an order difference on its request."""
    i = next(j for j, x in enumerate(lines) if x.split()[1:3] == ["effect", "motor_stop"])
    rid = lines[i].split()[3]
    assert lines[i + 1].split()[1] == "state" and lines[i + 2].split()[1:3] == ["send", "DONE"]
    return lines[:i] + [lines[i + 1], lines[i]] + lines[i + 2:], i, rid, ms(lines[i])


@pytest.mark.parametrize("extra_after", [True, False])
def test_an_order_difference_and_another_requests_extra_line_follow_the_log(extra_after):
    lines, i, rid, t = reordered_arrival(sim_lines())
    extra = f"{t} send STATUS_REPLY s-9999 state=LEFT"
    lines = lines[:i + 3] + [extra] + lines[i + 3:] if extra_after else lines[:i] + [extra] + lines[i:]
    c = first(lines)
    assert c.first["t_us"] == t * 1000
    if extra_after:
        assert (c.first["kind"], c.first["req_id"]) == ("order", rid)
    else:
        assert (c.first["kind"], c.first["req_id"]) == ("event", "s-9999")
    assert c.order_differences == 1


def test_an_order_difference_and_an_unmatched_event_on_the_same_request_report_the_unmatched_event():
    lines, i, rid, t = reordered_arrival(sim_lines())
    lines = lines[:i + 3] + [f"{t} send ACK {rid}"] + lines[i + 3:]
    c = first(lines)
    assert (c.first["kind"], c.first["req_id"], c.first["device"]["event"]) == ("event", rid, f"send ACK {rid}")
