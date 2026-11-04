import pytest

from replayspect import Scheduler, SchedulerError


def test_runs_in_time_order():
    s = Scheduler(0)
    log = []
    s.at(2.0, lambda: log.append("b"))
    s.at(1.0, lambda: log.append("a"))
    s.at(3.0, lambda: log.append("c"))
    s.run_until(10)
    assert log == ["a", "b", "c"]


def test_same_instant_is_fifo():
    s = Scheduler(0)
    log = []
    for name in "xyzw":
        s.at(1.0, lambda n=name: log.append(n))
    s.run_until(1.0)
    assert log == list("xyzw")


def test_action_scheduled_now_runs_after_already_queued_same_instant():
    s = Scheduler(0)
    log = []

    def first():
        log.append("first")
        s.after(0, lambda: log.append("nested"))

    s.at(1.0, first)
    s.at(1.0, lambda: log.append("second"))
    s.run_until(1.0)
    assert log == ["first", "second", "nested"]


def test_clock_reads_action_time_inside_action():
    s = Scheduler(0)
    seen = []
    s.at(1.25, lambda: seen.append(s.now_us))
    s.run_until(5)
    assert seen == [1_250_000]


def test_run_until_is_inclusive_and_advances_clock():
    s = Scheduler(0)
    log = []
    s.at(1.0, lambda: log.append("at-end"))
    s.at(1.000001, lambda: log.append("after-end"))
    assert s.run_until(1.0) == 1
    assert log == ["at-end"]
    assert s.now_us == 1_000_000
    s.run_until(4.0)
    assert s.now_us == 4_000_000
    assert log == ["at-end", "after-end"]


def test_cancel():
    s = Scheduler(0)
    log = []
    h = s.at(1.0, lambda: log.append("never"))
    s.at(2.0, lambda: log.append("yes"))
    h.cancel()
    h.cancel()
    assert h.cancelled
    assert s.pending() == 1
    s.run_until(5)
    assert log == ["yes"]


def test_cannot_schedule_in_the_past():
    s = Scheduler(0)
    s.run_until(2.0)
    with pytest.raises(SchedulerError):
        s.at(1.0, lambda: None)
    with pytest.raises(SchedulerError):
        s.after(-0.1, lambda: None)
    with pytest.raises(SchedulerError):
        s.run_until(1.0)


def test_runaway_same_instant_loop_is_caught():
    s = Scheduler(0)

    def again():
        s.after(0, again)

    s.at(0, again)
    with pytest.raises(SchedulerError, match="max_actions"):
        s.run_until(1.0, max_actions=1000)


def test_seconds_convert_to_exact_microseconds():
    s = Scheduler(0)
    h = s.at(0.1 + 0.2, lambda: None)
    assert h.time_us == 300_000


def test_rng_is_seeded():
    a = [Scheduler(42).rng.random() for _ in range(3)]
    b = [Scheduler(42).rng.random() for _ in range(3)]
    assert a == b
