import json

import pytest

import echo
from replayspect import Scheduler, Trace
from replayspect.sim.link import (
    Channel,
    ChannelProfile,
    Disconnect,
    FaultPlan,
    LinkError,
    LinkProfile,
    Message,
    MessageFault,
)


def world(profile=None, plan=None, seed=0):
    sched = Scheduler(seed)
    trace = Trace(lambda: sched.now_us)
    ch = Channel(sched, trace, profile, plan)
    inbox = {"client": [], "device": []}
    conn = []
    ch.attach("client", inbox["client"].append, lambda up: conn.append(("client", up)))
    ch.attach("device", inbox["device"].append, lambda up: conn.append(("device", up)))
    ch.start()
    return sched, trace, ch, inbox, conn


# -- trace layout -------------------------------------------------------------


def test_default_delivery_and_exact_trace_layout():
    sched, trace, ch, inbox, _ = world()
    sched.at(0.5, lambda: ch.send("client", Message("MOVE_UP", "r-1", {"floor": 3})))
    sched.run_until(1)
    assert [m.name for m in inbox["device"]] == ["MOVE_UP"]
    assert [e.to_dict() for e in trace] == [
        {"seq": 0, "t_us": 500_000, "actor": "client", "kind": "send", "name": "MOVE_UP",
         "req_id": "r-1", "data": {"floor": 3, "link": {"dir": "c2s", "n": 0, "delay_us": 1_000}}},
        {"seq": 1, "t_us": 501_000, "actor": "device", "kind": "recv", "name": "MOVE_UP",
         "req_id": "r-1", "data": {"floor": 3, "link": {"dir": "c2s", "n": 0, "copy": 0}}},
    ]


def test_link_field_name_is_reserved():
    with pytest.raises(LinkError):
        Message("X", fields={"link": 1})


@pytest.mark.parametrize("kwargs", [
    {"delay_us": (5, 1)}, {"delay_us": (-1, 3)}, {"drop_p": 1.5}, {"dup_p": -0.1},
    {"dup_extra_us": (2, 1)},
])
def test_profile_validation(kwargs):
    with pytest.raises(LinkError):
        LinkProfile(**kwargs)


def test_channel_must_be_started_with_both_endpoints():
    sched = Scheduler(0)
    ch = Channel(sched, Trace(lambda: sched.now_us))
    with pytest.raises(LinkError):
        ch.send("client", Message("X"))
    ch.attach("client", lambda m: None)
    with pytest.raises(LinkError):
        ch.start()


# -- random faults --------------------------------------------------------------


def test_random_mode_is_deterministic():
    assert echo.run(5, echo.STORMY)[0].digest() == echo.run(5, echo.STORMY)[0].digest()
    assert echo.run(5, echo.STORMY)[0].digest() != echo.run(6, echo.STORMY)[0].digest()


def test_drop_all():
    prof = ChannelProfile(c2s=LinkProfile(drop_p=1.0))
    trace, _ = echo.run(0, prof, n_msgs=5)
    drops = [e for e in trace if e.kind == "fault" and e.name == "drop"]
    assert len(drops) == 5
    assert {e.data["reason"] for e in drops} == {"injected"}
    assert not [e for e in trace if e.kind == "recv"]


def test_duplicate_all_arrives_twice_with_extra_delay():
    prof = ChannelProfile(c2s=LinkProfile(delay_us=(10_000, 10_000), dup_p=1.0, dup_extra_us=(5_000, 5_000)))
    trace, _ = echo.run(0, prof, n_msgs=1)
    recv = [e for e in trace if e.kind == "recv" and e.actor == "device"]
    assert [(e.t_us, e.data["link"]["copy"]) for e in recv] == [(10_000, 0), (15_000, 1)]
    (dup,) = [e for e in trace if e.name == "duplicate"]
    assert dup.data == {"dir": "c2s", "n": 0, "msg": "PING", "extra_us": 5_000}


def test_jitter_reorders_messages_for_some_seed():
    prof = ChannelProfile(c2s=LinkProfile(delay_us=(0, 500_000)))
    def reordered(seed):
        trace, _ = echo.run(seed, prof, n_msgs=10, spacing_us=50_000)
        ns = [e.data["link"]["n"] for e in trace if e.kind == "recv" and e.actor == "device"]
        return ns != sorted(ns)
    assert any(reordered(s) for s in range(20))


def test_same_instant_arrivals_keep_send_order():
    sched, trace, ch, inbox, _ = world(ChannelProfile(c2s=LinkProfile(delay_us=(7, 7))))
    for i in range(4):
        sched.at(0, lambda i=i: ch.send("client", Message("M", f"r-{i}")))
    sched.run_until(1)
    assert [m.req_id for m in inbox["device"]] == ["r-0", "r-1", "r-2", "r-3"]


# -- disconnects ----------------------------------------------------------------


def test_disconnect_drops_in_flight_and_new_sends_then_recovers():
    plan = FaultPlan(
        messages=(MessageFault("c2s", 0, delay_us=300_000),),
        disconnects=(Disconnect(t_us=100_000, duration_us=400_000),),
    )
    sched, trace, ch, inbox, conn = world(plan=plan)
    sched.at(0.0, lambda: ch.send("client", Message("A", "r-0")))    # in flight at 0.1s
    sched.at(0.2, lambda: ch.send("client", Message("B", "r-1")))    # sent while down
    sched.at(0.6, lambda: ch.send("client", Message("C", "r-2")))    # after reconnect
    sched.run_until(2)
    drops = [(e.req_id, e.data["reason"], e.t_us) for e in trace if e.name == "drop"]
    assert drops == [("r-1", "disconnected", 200_000), ("r-0", "connection_lost", 300_000)]
    assert [m.req_id for m in inbox["device"]] == ["r-2"]
    assert conn == [("client", False), ("device", False), ("client", True), ("device", True)]
    faults = [(e.name, e.t_us) for e in trace if e.kind == "fault" and e.name != "drop"]
    assert faults == [("disconnect", 100_000), ("reconnect", 500_000)]
    # n counts every send attempt, including the one dropped while down
    assert [e.data["link"]["n"] for e in trace if e.kind == "send"] == [0, 1, 2]


def test_random_disconnects_happen_and_alternate():
    trace, conn = echo.run(1, echo.STORMY)
    names = [e.name for e in trace if e.name in ("disconnect", "reconnect")]
    assert names[:4] == ["disconnect", "reconnect", "disconnect", "reconnect"]
    ups = [up for _, who, up in conn if who == "client"]
    assert all(a != b for a, b in zip(ups, ups[1:]))


# -- explicit mode and replay ---------------------------------------------------


def test_explicit_plan_applies_only_listed_faults():
    plan = FaultPlan(messages=(
        MessageFault("c2s", 1, drop=True),
        MessageFault("c2s", 2, delay_us=50_000, dup_extra_us=10_000),
    ))
    prof = ChannelProfile(c2s=LinkProfile(delay_us=(1_000, 900_000), drop_p=0.9))
    trace, _ = echo.run(0, prof, plan, n_msgs=4, spacing_us=100_000)
    sends = {e.data["link"]["n"]: e.data["link"].get("delay_us") for e in trace if e.kind == "send" and e.actor == "client"}
    assert sends == {0: 1_000, 1: None, 2: 50_000, 3: 1_000}
    recv = [(e.data["link"]["n"], e.data["link"]["copy"], e.t_us) for e in trace if e.kind == "recv" and e.actor == "device"]
    assert recv == [(0, 0, 1_000), (2, 0, 250_000), (2, 1, 260_000), (3, 0, 301_000)]


@pytest.mark.parametrize("seed", range(40))
def test_plan_from_random_run_replays_to_same_digest(seed):
    random_trace, random_conn = echo.run(seed, echo.STORMY)
    plan = FaultPlan.from_trace(random_trace)
    replay_trace, replay_conn = echo.run(seed, echo.STORMY, plan)
    assert replay_trace.digest() == random_trace.digest()
    assert replay_conn == random_conn


def test_plan_replay_does_not_depend_on_seed():
    random_trace, _ = echo.run(9, echo.STORMY)
    plan = FaultPlan.from_trace(random_trace)
    assert echo.run(12345, echo.STORMY, plan)[0].digest() == random_trace.digest()


def test_plan_dict_round_trip_is_json():
    plan = FaultPlan.from_trace(echo.run(3, echo.STORMY)[0])
    d = json.loads(json.dumps(plan.to_dict()))
    assert FaultPlan.from_dict(d) == FaultPlan.from_dict(plan.to_dict())
    assert echo.run(3, echo.STORMY, FaultPlan.from_dict(d))[0].digest() == echo.run(3, echo.STORMY)[0].digest()


@pytest.mark.parametrize("make", [
    lambda: FaultPlan(messages=(MessageFault("c2s", 0), MessageFault("c2s", 0))),
    lambda: FaultPlan(disconnects=(Disconnect(0, 100), Disconnect(50, 100))),
    lambda: MessageFault("c2s", 0, drop=True, delay_us=5),
    lambda: MessageFault("x2y", 0),
    lambda: Disconnect(10, 0),
])
def test_plan_validation(make):
    with pytest.raises(LinkError):
        make()
