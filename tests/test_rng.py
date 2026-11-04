from replayspect import Scheduler


def draws(rng, k=5):
    return [rng.random() for _ in range(k)]


def test_fork_is_deterministic_per_seed_and_name():
    assert draws(Scheduler(3).fork_rng("link/c2s")) == draws(Scheduler(3).fork_rng("link/c2s"))


def test_forks_differ_by_name_and_seed():
    a = draws(Scheduler(3).fork_rng("link/c2s"))
    assert a != draws(Scheduler(3).fork_rng("link/s2c"))
    assert a != draws(Scheduler(4).fork_rng("link/c2s"))


def test_fork_is_independent_of_other_streams():
    s1 = Scheduler(3)
    s1.rng.random()
    s1.fork_rng("other").random()
    s2 = Scheduler(3)
    assert draws(s1.fork_rng("link/c2s")) == draws(s2.fork_rng("link/c2s"))


def test_fork_value_is_pinned():
    # Guards against accidental changes to the derivation (sha256 of "seed/name").
    assert Scheduler(0).fork_rng("link/c2s").randint(0, 10**9) == PINNED


PINNED = 166261411
