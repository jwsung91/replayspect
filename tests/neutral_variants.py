"""Neutral implementation variants for the variant tests (loaded by path, as an operator would).

Each one is built the way a variant must be: from the package's Scheduler,
Channel and Trace, with the link profile it is given. ``SAME_*`` wire up the
registered implementation exactly, so they must give the registered digest.
``FEWER_COMMANDS`` changes only how many commands the client sends: the run
differs but stays correct. ``LIFT_PUBLIC_FAILING`` switches on a mutant the lift
already publishes (``replayspect.sut.lift.MUTANTS``), so a variant run can fail
without this file adding a defect of its own.
"""

from replayspect.sim.link import Channel
from replayspect.sim.scheduler import Scheduler
from replayspect.sut import lift, turntable
from replayspect.trace import Trace
from replayspect.variant import Variant


def _wire(device_cls, client_cls, n_commands, mutants=frozenset()):
    def run(seed, profile, plan, until_us):
        sched = Scheduler(seed)
        trace = Trace(lambda: sched.now_us)
        ch = Channel(sched, trace, profile, plan)
        device_cls(sched, trace, ch, mutants)
        client = client_cls(sched, trace, ch, mutants, n_commands)
        ch.start()
        client.start()
        sched.run_until_us(until_us)
        return trace

    return run


SAME_LIFT = Variant("lift.v0", _wire(lift.LiftDevice, lift.LiftClient, 6))
SAME_TURNTABLE = Variant(
    "turntable.v0", _wire(turntable.TurntableDevice, turntable.TurntableClient, len(turntable.SEQUENCE))
)
FEWER_COMMANDS = Variant("turntable.v0", _wire(turntable.TurntableDevice, turntable.TurntableClient, 3))
LIFT_PUBLIC_FAILING = Variant("lift.v0", _wire(lift.LiftDevice, lift.LiftClient, 6, frozenset({"M5"})))


class _Recorder(Trace):
    pass


def _own_recorder(seed, profile, plan, until_us):
    return _Recorder(lambda: 0)


#: Returns its own trace type: refused, since its recording is not the package's.
OWN_RECORDER = Variant("lift.v0", _own_recorder)
#: Not a variant at all.
NOT_A_VARIANT = object()
