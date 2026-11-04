"""A tiny ping-pong world used to prove determinism end to end.

A client sends PINGs with retries over a link whose delay and loss come from
the scheduler's seeded RNG; a server answers PONG. It is deliberately small,
but it exercises everything that can break determinism: same-instant
ordering, cancellation, rescheduling and random draws.
"""

from __future__ import annotations

from replayspect import Scheduler, Trace

TIMEOUT_S = 0.5
MAX_RETRIES = 2


def run(seed: int, n_requests: int = 20, until_s: float = 30.0) -> Trace:
    sched = Scheduler(seed)
    trace = Trace(lambda: sched.now_us)
    rng = sched.rng

    def deliver(direction: str, name: str, req_id: str, on_arrive) -> None:
        if rng.random() < 0.15:
            trace.record("link", "fault", "drop", req_id, {"dir": direction, "msg": name})
            return
        delay_us = rng.randint(50_000, 700_000)
        sched.after_us(delay_us, on_arrive, f"{direction}:{name}:{req_id}")

    def server_recv(req_id: str) -> None:
        trace.record("server", "recv", "PING", req_id)
        trace.record("server", "send", "PONG", req_id)
        deliver("s2c", "PONG", req_id, lambda: client_recv(req_id))

    done: set[str] = set()
    timers: dict[str, object] = {}

    def client_recv(req_id: str) -> None:
        trace.record("client", "recv", "PONG", req_id)
        if req_id in done:  # duplicate reply, or a late one after we gave up
            return
        done.add(req_id)
        timers.pop(req_id).cancel()
        trace.record("client", "handle", "PONG", req_id)

    def client_send(req_id: str, attempt: int) -> None:
        trace.record("client", "send", "PING", req_id, {"attempt": attempt})
        deliver("c2s", "PING", req_id, lambda: server_recv(req_id))
        timers[req_id] = sched.after(TIMEOUT_S, lambda: client_timeout(req_id, attempt), f"timeout:{req_id}")

    def client_timeout(req_id: str, attempt: int) -> None:
        if attempt < MAX_RETRIES:
            client_send(req_id, attempt + 1)
        else:
            timers.pop(req_id, None)
            done.add(req_id)
            trace.record("client", "handle", "ERROR", req_id, {"reason": "timeout"})

    for i in range(n_requests):
        req_id = f"r-{i:04d}"
        sched.at(i * 0.3, lambda r=req_id: client_send(r, 0), f"start:{req_id}")

    sched.run_until(until_s)
    return trace


if __name__ == "__main__":
    import sys

    print(run(int(sys.argv[1])).digest())
