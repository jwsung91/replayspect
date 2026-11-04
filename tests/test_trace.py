import pytest

from replayspect import Scheduler, Trace, TraceError


def make():
    s = Scheduler(0)
    return s, Trace(lambda: s.now_us)


def test_record_stamps_seq_and_virtual_time():
    s, tr = make()
    s.at(1.5, lambda: tr.record("device", "effect", "motor_start", "r-1", {"state": "MOVING_UP"}))
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
        tr.record("client", "send", "MOVE_UP", data={"payload": object()})


def test_jsonl_is_canonical_and_round_trips():
    _, tr = make()
    tr.record("client", "send", "MOVE_UP", "r-1", {"b": 2, "a": 1})
    tr.record("link", "fault", "drop", "r-1", {"dir": "c2s"})
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


def test_data_is_snapshotted():
    _, tr = make()
    payload = {"v": [1], "t": (1, 2)}
    tr.record("client", "send", "M", "r-1", payload)
    payload["v"].append(2)
    assert tr[0].data == {"v": [1], "t": [1, 2]}


def test_data_keys_may_shadow_parameters():
    _, tr = make()
    data = {"name": "lift-A", "kind": "x", "actor": "y", "req_id": "z"}
    ev = tr.record("device", "send", "STATUS_REPLY", "r-1", data)
    assert (ev.actor, ev.kind, ev.name, ev.req_id) == ("device", "send", "STATUS_REPLY", "r-1")
    assert ev.data == data


def test_req_id_by_keyword_lands_in_req_id():
    _, tr = make()
    ev = tr.record("device", "effect", "motor_start", req_id="r-1")
    assert ev.req_id == "r-1"
    assert ev.data == {}


def test_stray_keyword_is_an_error_not_data():
    _, tr = make()
    with pytest.raises(TypeError):
        tr.record("device", "effect", "motor_start", "r-1", state="MOVING_UP")
