"""Echo world for link tests: the client sends PINGs, the device echoes them."""

from __future__ import annotations

from replayspect import Scheduler, Trace
from replayspect.sim.link import Channel, ChannelProfile, FaultPlan, LinkProfile, Message

#: A profile that exercises every random fault kind.
STORMY = ChannelProfile(
    c2s=LinkProfile(
        delay_us=(20_000, 400_000), drop_p=0.1, dup_p=0.15, dup_extra_us=(0, 300_000)
    ),
    s2c=LinkProfile(
        delay_us=(20_000, 400_000), drop_p=0.1, dup_p=0.15, dup_extra_us=(0, 300_000)
    ),
    disconnect_mean_interval_us=1_500_000,
    disconnect_duration_us=(100_000, 600_000),
)


def run(
    seed: int,
    profile: ChannelProfile | None = None,
    plan: FaultPlan | None = None,
    n_msgs: int = 30,
    spacing_us: int = 200_000,
    until_us: int = 20_000_000,
):
    sched = Scheduler(seed)
    trace = Trace(lambda: sched.now_us)
    ch = Channel(sched, trace, profile, plan)
    conn_log: list[tuple[int, str, bool]] = []

    def device_on(msg: Message) -> None:
        ch.send("device", Message("ECHO", msg.req_id, {"v": msg.fields["v"]}))

    def client_on(msg: Message) -> None:
        trace.record("client", "handle", msg.name, msg.req_id)

    ch.attach("client", client_on, lambda up: conn_log.append((sched.now_us, "client", up)))
    ch.attach("device", device_on, lambda up: conn_log.append((sched.now_us, "device", up)))
    ch.start()
    for i in range(n_msgs):
        sched.at_us(
            i * spacing_us,
            lambda i=i: ch.send("client", Message("PING", f"r-{i:04d}", {"v": i})),
        )
    sched.run_until_us(until_us)
    return trace, conn_log
