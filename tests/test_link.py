import json

import pytest

import echo
from replayspect import Scheduler, Trace
from replayspect.sim.link import (
    Channel,
    ChannelProfile,
    Delay,
    Disconnect,
    FaultPlan,
    LinkError,
    LinkProfile,
    Message,
    MessageFault,
    MsgKey,
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
         "req_id": "r-1", "data": {"floor": 3, "link": {"dir": "c2s", "n": 0, "k": 0, "delay_us": 1_000}}},
        {"seq": 1, "t_us": 501_000, "actor": "device", "kind": "recv", "name": "MOVE_UP",
         "req_id": "r-1", "data": {"floor": 3, "link": {"dir": "c2s", "n": 0, "k": 0, "copy": 0}}},
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
    assert dup.data == {"dir": "c2s", "n": 0, "msg": "PING", "k": 0, "extra_us": 5_000}


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
        delays=(Delay(MsgKey("c2s", "A", "r-0", 0), 300_000),),
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


def ping(i, k=0):
    return MsgKey("c2s", "PING", f"r-{i:04d}", k)


def test_explicit_plan_applies_only_listed_faults():
    plan = FaultPlan(
        delays=(Delay(ping(2), 50_000),),
        faults=(MessageFault(ping(1), drop=True), MessageFault(ping(2), dup_extra_us=10_000)),
    )
    prof = ChannelProfile(c2s=LinkProfile(delay_us=(1_000, 900_000), drop_p=0.9))
    trace, _ = echo.run(0, prof, plan, n_msgs=4, spacing_us=100_000)
    sends = {e.req_id: e.data["link"].get("delay_us") for e in trace if e.kind == "send" and e.actor == "client"}
    # A dropped send still records the delay it would have had.
    assert sends == {"r-0000": 1_000, "r-0001": 1_000, "r-0002": 50_000, "r-0003": 1_000}
    recv = [(e.req_id, e.data["link"]["copy"], e.t_us) for e in trace if e.kind == "recv" and e.actor == "device"]
    assert recv == [("r-0000", 0, 1_000), ("r-0002", 0, 250_000), ("r-0002", 1, 260_000), ("r-0003", 0, 301_000)]


def test_random_draw_order_is_pinned():
    # Draw order per message, dropped or not: drop?, delay, duplicate?, extra delay.
    # Changing it changes what every existing seed produces.
    prof = ChannelProfile(c2s=LinkProfile(delay_us=(0, 999), drop_p=0.3, dup_p=0.3, dup_extra_us=(0, 99)))
    sched, trace, ch, _, _ = world(prof, seed=0)
    for i in range(8):
        sched.at_us(i, lambda i=i: ch.send("client", Message("M", f"r-{i}")))
    sched.run_until(1)
    decisions = []
    for e in trace:
        if e.kind == "send":
            decisions.append([e.req_id, e.data["link"].get("delay_us")])
        elif e.name == "drop":
            decisions[-1].append("drop")
        elif e.name == "duplicate":
            decisions[-1].append(e.data["extra_us"])
    assert decisions == PINNED_DECISIONS


PINNED_DECISIONS = [
    ["r-0", 460, "drop"], ["r-1", 692, "drop"], ["r-2", 673, "drop"], ["r-3", 677, 5],
    ["r-4", 18], ["r-5", 652], ["r-6", 707, "drop"], ["r-7", 11, "drop"],
]


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


def test_removing_one_fault_does_not_shift_other_requests():
    """Dropping r-A's first PING causes a retry. Removing that drop removes the
    retry, but the duplicate planned for r-C must still hit r-C."""

    def run(plan):
        sched, trace, ch, inbox, _ = world(plan=plan)
        got = set()
        ch.attach("device", lambda m: ch.send("device", Message("ECHO", m.req_id)))
        ch.attach("client", lambda m: got.add(m.req_id))

        def send(rid, attempt=0):
            ch.send("client", Message("PING", rid))
            if attempt == 0:
                sched.after(0.1, lambda: rid in got or send(rid, 1))

        sched.at(0.00, lambda: send("r-A"))
        sched.at(0.05, lambda: send("r-B"))
        sched.at(0.30, lambda: send("r-C"))
        sched.run_until(1)
        return trace

    drop_a = MessageFault(MsgKey("c2s", "PING", "r-A", 0), drop=True)
    dup_c = MessageFault(MsgKey("c2s", "PING", "r-C", 0), dup_extra_us=7_000)
    full = FaultPlan(faults=(drop_a, dup_c))

    t_full = run(full)
    assert [e.req_id for e in t_full if e.kind == "send" and e.actor == "client"] == ["r-A", "r-B", "r-A", "r-C"]
    t_less = run(full.without_fault(drop_a.key))
    assert [e.req_id for e in t_less if e.kind == "send" and e.actor == "client"] == ["r-A", "r-B", "r-C"]
    for t in (t_full, t_less):
        assert [e.req_id for e in t if e.name == "duplicate"] == ["r-C"]


def test_field_names_may_shadow_record_parameters():
    sched, trace, ch, inbox, _ = world()
    fields = {"name": "lift-A", "kind": "freight", "actor": "x", "req_id": "y"}
    sched.at(0, lambda: ch.send("device", Message("STATUS_REPLY", "r-1", fields)))
    sched.run_until(1)
    assert inbox["client"][0].fields == fields
    send, recv = trace.events
    assert (send.name, send.req_id) == ("STATUS_REPLY", "r-1")
    assert {k: send.data[k] for k in fields} == fields


def test_fields_are_snapshotted_at_send():
    sched, trace, ch, inbox, _ = world(ChannelProfile(c2s=LinkProfile(dup_p=1.0, dup_extra_us=(5, 5))))
    payload = {"v": [1]}
    sched.at(0, lambda: ch.send("client", Message("M", "r-1", payload)))
    sched.at(0, lambda: payload["v"].append(2))
    sched.run_until(1)
    assert [m.fields for m in inbox["device"]] == [{"v": [1]}, {"v": [1]}]
    assert trace[0].data["v"] == [1]
    inbox["device"][0].fields["v"].append(99)
    assert inbox["device"][1].fields == {"v": [1]}
    assert trace[0].data["v"] == [1]


def test_plan_dict_uses_message_keys():
    plan = FaultPlan(
        delays=(Delay(MsgKey("s2c", "ACK", "r-3", 0), 2_300_000),),
        faults=(MessageFault(MsgKey("c2s", "MOVE_UP", "r-3", 1), dup_extra_us=400_000),),
        disconnects=(Disconnect(5_000_000, 1_000_000),),
    )
    assert plan.to_dict() == {
        "delays": [{"dir": "s2c", "msg": "ACK", "req_id": "r-3", "k": 0, "delay_us": 2_300_000}],
        "faults": [{"dir": "c2s", "msg": "MOVE_UP", "req_id": "r-3", "k": 1, "dup_extra_us": 400_000}],
        "disconnects": [{"t_us": 5_000_000, "duration_us": 1_000_000}],
    }
    assert FaultPlan.from_dict(plan.to_dict()) == plan


@pytest.mark.parametrize("make", [
    lambda: FaultPlan(delays=(Delay(ping(0), 1), Delay(ping(0), 2))),
    lambda: FaultPlan(faults=(MessageFault(ping(0), drop=True), MessageFault(ping(0), drop=True))),
    lambda: FaultPlan(disconnects=(Disconnect(0, 100), Disconnect(50, 100))),
    lambda: MessageFault(ping(0), drop=True, dup_extra_us=5),
    lambda: MessageFault(ping(0)),
    lambda: MsgKey("x2y", "PING", None, 0),
    lambda: MsgKey("c2s", "PING", None, -1),
    lambda: Delay(ping(0), -1),
    lambda: Disconnect(10, 0),
])
def test_plan_validation(make):
    with pytest.raises(LinkError):
        make()


# -- removing faults restores original timing --------------------------------------


def _first(trace, pred):
    return next(e for e in trace if pred(e))


def test_removing_an_injected_drop_restores_the_drawn_delay():
    for seed in range(50):
        trace, _ = echo.run(seed, echo.STORMY)
        plan = FaultPlan.from_trace(trace)
        drops = [f for f in plan.faults if f.drop and f.key.dir == "c2s"]
        if drops:
            break
    key = drops[0].key
    drawn = _first(trace, lambda e: e.kind == "send" and e.req_id == key.req_id
                   and e.name == key.msg and e.data["link"]["k"] == key.k).data["link"]["delay_us"]
    replay, _ = echo.run(seed, echo.STORMY, plan.without_fault(key))
    send = _first(replay, lambda e: e.kind == "send" and e.req_id == key.req_id
                  and e.name == key.msg and e.data["link"]["k"] == key.k)
    assert send.data["link"]["delay_us"] == drawn
    assert drawn != echo.STORMY.c2s.delay_us[0]
    # the message is no longer dropped by injection
    assert not [e for e in replay if e.name == "drop" and e.req_id == key.req_id
                and e.data["k"] == key.k and e.data["reason"] == "injected"]


def test_removing_a_disconnect_restores_drawn_delays():
    trace, _ = echo.run(1, echo.STORMY)
    plan = FaultPlan.from_trace(trace)
    lost = [e for e in trace if e.name == "drop" and e.data["reason"] == "disconnected"]
    assert lost
    first = plan.disconnects[0]
    victims = [e for e in lost if first.t_us <= e.t_us < first.t_us + first.duration_us]
    assert victims
    calmer = FaultPlan(plan.delays, plan.faults, plan.disconnects[1:])
    replay, _ = echo.run(1, echo.STORMY, calmer)
    for v in victims:
        key = MsgKey(v.data["dir"], v.data["msg"], v.req_id, v.data["k"])
        assert plan.delay(key) is not None
        sent = _first(replay, lambda e: e.kind == "send" and e.req_id == key.req_id
                      and e.name == key.msg and e.data["link"]["k"] == key.k)
        assert sent.data["link"]["delay_us"] == plan.delay(key)


# -- message field validation ------------------------------------------------------


@pytest.mark.parametrize("fields", [
    {"pos": (1, 2)},
    {"map": {1: "a"}},
    {"x": float("nan")},
    {"obj": object()},
    {"nested": [{"t": (1,)}]},
])
def test_fields_that_would_change_in_transit_are_rejected(fields):
    sched, trace, ch, inbox, _ = world()
    with pytest.raises(LinkError):
        ch.send("client", Message("M", "r-1", fields))
    assert len(trace) == 0


def test_link_key_added_after_construction_is_rejected_at_send():
    sched, trace, ch, inbox, _ = world()
    msg = Message("M", "r-1", {"a": 1})
    msg.fields["link"] = "sneaky"
    with pytest.raises(LinkError, match="reserved"):
        ch.send("client", msg)


def test_plain_json_values_pass_unchanged():
    sched, trace, ch, inbox, _ = world()
    fields = {"a": [1, 2.5, "x", None, True], "b": {"c": {"d": []}}}
    sched.at(0, lambda: ch.send("client", Message("M", "r-1", fields)))
    sched.run_until(1)
    assert inbox["device"][0].fields == fields


# -- keys --------------------------------------------------------------------------


def test_msg_keys_sort_only_via_sort_key():
    keys = [MsgKey("c2s", "HB", None, 1), MsgKey("c2s", "HB", "r-1", 0), MsgKey("s2c", "ACK", None, 0)]
    with pytest.raises(TypeError):
        sorted(keys)
    assert sorted(keys, key=MsgKey.sort_key)[0] == MsgKey("c2s", "HB", None, 1)


# -- strict plan parsing ---------------------------------------------------------------


@pytest.mark.parametrize("d,match", [
    ({"lose": []}, "unknown plan fields"),
    ({"faults": [{"dir": "c2s", "msg": "M", "req_id": "r", "k": 0, "lose": 1}]}, "unknown fields"),
    ({"faults": [{"dir": "c2s", "msg": "M", "req_id": "r", "drop": True}]}, "missing"),
    ({"delays": [{"dir": "c2s", "msg": "M", "req_id": "r", "k": 0}]}, "missing"),
    ({"faults": [{"dir": "c2s", "msg": 5, "req_id": "r", "k": 0, "drop": True}]}, "msg must be a string"),
    ({"faults": [{"dir": "c2s", "msg": "M", "req_id": 3, "k": 0, "drop": True}]}, "req_id"),
    ({"faults": [{"dir": "c2s", "msg": "M", "req_id": "r", "k": "0", "drop": True}]}, "k must be an integer"),
    ({"faults": [{"dir": "c2s", "msg": "M", "req_id": "r", "k": 0, "drop": "yes"}]}, "drop must be"),
    ({"disconnects": [{"t_us": 1.5, "duration_us": 10}]}, "t_us must be an integer"),
    ({"faults": {"dir": "c2s"}}, "must be a list"),
    ({"base": "chaos"}, "base must be"),
    ([], "mapping"),
])
def test_plan_from_dict_rejects_malformed_input(d, match):
    with pytest.raises(LinkError, match=match):
        FaultPlan.from_dict(d)


def test_plan_req_id_may_be_omitted_for_messages_without_one():
    plan = FaultPlan.from_dict({"faults": [{"dir": "c2s", "msg": "HB", "k": 2, "drop": True}]})
    assert plan.faults[0].key == MsgKey("c2s", "HB", None, 2)


# -- random base: chosen faults on top of seed-dependent timing ---------------------------


def _send_delays(trace):
    return {(e.data["link"]["dir"], e.name, e.req_id, e.data["link"]["k"]): e.data["link"]["delay_us"]
            for e in trace if e.kind == "send"}


def test_random_base_round_trips_and_defaults_to_fixed():
    plan = FaultPlan(faults=(MessageFault(ping(1), drop=True),), base="random")
    assert plan.to_dict()["base"] == "random"
    assert FaultPlan.from_dict(plan.to_dict()) == plan
    assert "base" not in FaultPlan().to_dict()
    assert FaultPlan.from_dict({}).base == "fixed"


def test_random_base_draws_delays_from_the_profile_and_the_seed():
    plan = FaultPlan(base="random")
    a, _ = echo.run(1, echo.STORMY, plan)
    b, _ = echo.run(2, echo.STORMY, plan)
    da, db = _send_delays(a), _send_delays(b)
    lo, hi = echo.STORMY.c2s.delay_us
    assert all(lo <= v <= hi for v in da.values())
    assert len(set(da.values())) > 10
    assert da != db
    assert echo.run(1, echo.STORMY, plan)[0].digest() == a.digest()


def test_random_base_injects_only_planned_faults():
    plan = FaultPlan(faults=(MessageFault(ping(3), drop=True),), base="random")
    trace, conn = echo.run(4, echo.STORMY, plan)
    faults = [(e.name, e.req_id) for e in trace if e.kind == "fault"]
    assert faults == [("drop", "r-0003")]
    assert conn == []


def test_random_base_keeps_other_delays_when_a_fault_is_added():
    quiet = FaultPlan(base="random")
    noisy = FaultPlan(faults=(MessageFault(ping(3), drop=True), MessageFault(ping(5), dup_extra_us=1)), base="random")
    dq = _send_delays(echo.run(7, echo.STORMY, quiet)[0])
    dn = _send_delays(echo.run(7, echo.STORMY, noisy)[0])
    shared = set(dq) & set(dn)
    assert len(shared) > 40
    assert all(dq[k] == dn[k] for k in shared)


def test_random_base_respects_planned_delays():
    plan = FaultPlan(delays=(Delay(ping(2), 123_456),), base="random")
    trace, _ = echo.run(0, echo.STORMY, plan)
    assert _send_delays(trace)[("c2s", "PING", "r-0002", 0)] == 123_456


def test_random_base_run_replays_exactly_as_a_fixed_plan():
    plan = FaultPlan(faults=(MessageFault(ping(3), drop=True),), disconnects=(Disconnect(1_000_000, 300_000),),
                     base="random")
    trace, _ = echo.run(5, echo.STORMY, plan)
    fixed = FaultPlan.from_trace(trace)
    assert fixed.base == "fixed"
    assert echo.run(5, echo.STORMY, fixed)[0].digest() == trace.digest()


# -- plan report ------------------------------------------------------------------------------


def test_plan_report_lists_entries_that_never_took_effect():
    from replayspect.sim.link import plan_report

    ghost = MsgKey("c2s", "PING", "r-9999", 0)
    typo = MsgKey("c2s", "PNIG", "r-0001", 0)
    lost = ping(2)  # sent at 0.4 s, during the disconnect below
    plan = FaultPlan(
        delays=(Delay(ping(0), 5_000), Delay(ghost, 5_000)),
        faults=(MessageFault(ping(1), drop=True), MessageFault(typo, drop=True), MessageFault(lost, drop=True)),
        disconnects=(Disconnect(300_000, 200_000), Disconnect(50_000_000, 1_000)),
    )
    trace, _ = echo.run(0, echo.STORMY, plan, n_msgs=5)
    rep = plan_report(plan, trace)
    assert [d.key for d in rep.unmatched_delays] == [ghost]
    assert [f.key for f in rep.unmatched_faults] == [typo]
    assert [f.key for f in rep.faults_lost_to_disconnect] == [lost]
    assert rep.unapplied_disconnects == (Disconnect(50_000_000, 1_000),)
    assert not rep.all_applied
    assert set(rep.to_dict()) == {
        "unmatched_delays", "unmatched_faults", "faults_lost_to_disconnect", "unapplied_disconnects",
    }


def test_plan_from_trace_is_fully_applied():
    from replayspect.sim.link import plan_report

    trace, _ = echo.run(3, echo.STORMY)
    plan = FaultPlan.from_trace(trace)
    assert plan_report(plan, echo.run(3, echo.STORMY, plan)[0]).all_applied
