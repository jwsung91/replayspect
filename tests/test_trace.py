import pytest

from replayspect import Scheduler, Trace, TraceError


def make():
    s = Scheduler(0)
    return s, Trace(lambda: s.now_us)


def test_record_stamps_seq_and_virtual_time():
    s, tr = make()
    s.at(1.5, lambda: tr.record("device", "effect", "motor_start", "r-1", state="MOVING_UP"))
    s.run_until(2)
    (ev,) = tr.events
    assert (ev.seq, ev.t_us, ev.actor, ev.kind, ev.name, ev.req_id) == (
        0, 1_500_000, "device", "effect", "motor_start", "r-1"
    )
    assert ev.data == {"state": "MOVING_UP"}


def test_unknown_kind_rejected():
    _, tr = make()
    with pytest.raises(TraceError, match="unknown event kind"):
        tr.record("client", "complete", "DONE")


def test_non_json_data_rejected():
    _, tr = make()
    with pytest.raises(TraceError, match="JSON"):
        tr.record("client", "send", "MOVE_UP", payload=object())


def test_jsonl_is_canonical_and_round_trips():
    _, tr = make()
    tr.record("client", "send", "MOVE_UP", "r-1", b=2, a=1)
    tr.record("link", "fault", "drop", "r-1", dir="c2s")
    text = tr.to_jsonl()
    assert text.splitlines()[0] == (
        '{"actor":"client","data":{"a":1,"b":2},"kind":"send","name":"MOVE_UP",'
        '"req_id":"r-1","seq":0,"t_us":0}'
    )
    back = Trace.from_jsonl(text)
    assert back.events == tr.events
    assert back.digest() == tr.digest()


def test_digest_changes_with_any_field():
    _, a = make()
    _, b = make()
    a.record("client", "send", "MOVE_UP", "r-1")
    b.record("client", "send", "MOVE_UP", "r-2")
    assert a.digest() != b.digest()
