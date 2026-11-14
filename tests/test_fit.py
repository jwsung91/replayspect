"""The fit (replayspect.fit): fix what a client log shows, explain the rest with the fewest faults."""

import json
import random
from itertools import product
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.driven import DrivenSetup
from replayspect import fit as F
from replayspect.fit import (Choice, Ranges, Usual, _Runner, attempts_of, fit_log, logged_disconnects, report_lines,
                             slow_round_trips)
from replayspect.incident import text_log
from replayspect.ingest import ingest_text, read_rules
from replayspect.runner import get_system
from replayspect.sim.link import FaultPlan
from replayspect.sut.lift import run_lift
from replayspect.trace import Event

RULES = Path(__file__).parent.parent / "examples" / "rules" / "sim-client-ros.yaml"
LIFT = get_system("lift.v0")
#: Short synthetic logs: every message takes the profile's 10 ms unless a fault says otherwise.
USUAL = Usual.given(10_000, 10_000, 25_000)


def logged(trace, ms=False):
    return ingest_text(text_log(trace.events, "client", ms=ms).encode(), read_rules(RULES)).events


def short(faults=(), n=2, until=14_000_000, seed=1, disconnects=()):
    """A short lift session with exactly these link faults (all other delays 10 ms), as a fit setup."""
    plan = FaultPlan.from_dict({"base": "fixed", "faults": list(faults), "disconnects": list(disconnects)})
    log = logged(run_lift(seed, plan=plan, n_commands=n, until_us=until))
    return DrivenSetup(LIFT, log, until, tolerance_us=25_000)


def f(d, msg, rid, k=0, **kw):
    return {"dir": d, "msg": msg, "req_id": rid, "k": k, **kw}


def true_choice(hidden, log):
    """The hidden run's own request arrivals, drops and duplicates, as an arrival choice."""
    plan = FaultPlan.from_trace(hidden)
    d = {(x.key.msg, x.key.req_id, x.key.k): x.delay_us for x in plan.delays if x.key.dir == "c2s"}
    drops = {(x.key.msg, x.key.req_id, x.key.k) for x in plan.faults if x.key.dir == "c2s" and x.drop}
    dups = {(x.key.msg, x.key.req_id, x.key.k): x.dup_extra_us for x in plan.faults
            if x.key.dir == "c2s" and x.dup_extra_us is not None}
    atts = attempts_of(log, "client")
    return Choice(tuple((a.key, None if a.key in drops else d[a.key]) for a in atts),
                  tuple(sorted(dups.items(), key=lambda kv: str(kv[0]))))


def flat(res):
    """Every explanation of a fit result as a set of fault identities, and those with one fault more."""
    outs = [set(o) for o in res.outside] or [set()]
    sets = [[set(x.faults) for x in u.explanations] for u in res.units]
    minimal = {frozenset(set().union(o, *combo)) for o in outs for combo in product(*sets)}
    plus = set()
    for i, u in enumerate(res.units):
        others = [s for j, s in enumerate(sets) if j != i]
        for x in u.plus_one:
            for o in outs:
                for combo in product(*others):
                    plus.add(frozenset(set().union(o, set(x.faults), *combo)))
    for u in res.more:  # one fault more on a command outside the units
        for x in u.plus_one:
            for o in outs:
                for combo in product(*sets):
                    plus.add(frozenset(set().union(o, set(x.faults), *combo)))
    return minimal, plus


def brute(setup, usual=USUAL):
    """Run every choice of the same option space on the whole log, with no levels and no units."""
    ranges = Ranges.of(setup)
    q = setup.system.quiet_messages
    atts = attempts_of(setup.log, "client")
    dis = logged_disconnects(setup.log, "client", setup.until_us)
    r = _Runner(setup, ranges, dis, 10**9, usual)
    default = F._default_choice(setup, atts, r)
    ev0 = r.evaluate_all(default)
    first = ev0.first
    polls = F._poll_units(setup, ev0.fit)
    # every command attempt, and the attempts of polls with a fault in the default
    ua = [a for a in atts if (a.key[0] not in q or a.req_id in polls) and not F._sent_while_down(a, dis)]
    opts = [F._options(setup, first, a, default.delay(a.key), ranges, usual, dis, setup.log[-1].t_us - setup.tolerance_us)
            for a in ua]
    found = {}
    for combo in product(*opts):
        ev = r.evaluate_all(default.assign({a.key: (o[0], o[1]) for a, o in zip(ua, combo)}))
        if ev.fit.unexplained:  # a receive nothing explains (a poll reply, which the match leaves out)
            continue
        for fd, ok, _ in ev.results:
            if ok:
                found[frozenset(fd)] = len(fd)
    return found


# -- the log as facts ---------------------------------------------------------------------------


def test_connection_lines_become_client_states_and_disconnects():
    hidden = run_lift(7)
    log = logged(hidden)
    states = [(e.name, e.t_us) for e in log if e.kind == "state"]
    assert states and states[0][0] == "DISCONNECTED"
    true = [(d.t_us, d.duration_us) for d in FaultPlan.from_trace(hidden).disconnects]
    assert [(d["t_us"], d["duration_us"]) for d in logged_disconnects(log, "client", 90_000_000)] == true
    open_end = [Event(0, 5, "client", "state", "DISCONNECTED")]
    assert logged_disconnects(open_end, "client", 100) == [{"t_us": 5, "duration_us": 95}]


@pytest.mark.parametrize("seed", [1, 5, 7, 23])
def test_with_the_true_arrivals_reply_delays_are_computed_and_reproduce(seed):
    # The core claim: reply delays do not change the device, so given the request arrivals,
    # one run gives every reply's send time and the plan follows by arithmetic.
    hidden = run_lift(seed)
    log = logged(hidden)
    setup = DrivenSetup(LIFT, log, 90_000_000)
    fit, _ = _Runner(setup, Ranges.of(setup), logged_disconnects(log, "client", 90_000_000), 10).evaluate(
        true_choice(hidden, log))
    assert not [e for e in fit.unexplained if e.name not in LIFT.quiet_messages]
    assert fit.match.reproduced and fit.match.max_dt_us == 0


# -- defaults, faults, pairing --------------------------------------------------------------------


def test_usual_delay_defaults():
    r = Ranges((10_000, 1_500_000), (10_000, 1_500_000), (0, 4_000_000))
    assert Usual.of(r) == Usual(10_000, 10_000, 1_500_000, 1_500_000)  # no delay inside the range is a fault
    assert Usual.given(4_000, 4_000, 25_000) == Usual(4_000, 4_000, 29_000, 29_000)


def test_an_attempt_the_log_does_not_bound_arrives_at_the_usual_delay():
    # The first attempt is lost: nothing in the log bounds its arrival. It defaults to the usual
    # delay, not to the middle of the range (testbed-01: the middle invented DONE drops).
    setup = short([f("c2s", "MOVE_UP", "r-0001", drop=True)])
    ranges = Ranges((0, 5_000_000), (0, 5_000_000), (0, 5_000_000))
    atts = attempts_of(setup.log, "client")
    r = _Runner(setup, ranges, logged_disconnects(setup.log, "client", setup.until_us), 100, USUAL)
    default = F._default_choice(setup, atts, r)
    assert default.delay(("MOVE_UP", "r-0001", 0)) == 10_000
    assert default.delay(("MOVE_UP", "r-0001", 1)) == 10_000  # the reply allows it: the usual value


def _all_assignments(ss, rs, ranges, limit, horizon):
    """Every assignment of receives to sends (independent of fit._pair_key), with its cost."""
    lo, hi = ranges.s2c
    dlo, dhi = ranges.dup_extra
    out = []
    for asg in product(*([("u",)] + [(t, j) for j in range(len(ss)) for t in ("f", "d")] for _ in rs)):
        firsts = [a[1] for a in asg if a[0] == "f"]
        if len(firsts) != len(set(firsts)):
            continue
        dups = [a[1] for a in asg if a[0] == "d"]
        if len(dups) != len(set(dups)):
            continue
        ok, faults = True, 0
        first_i = {a[1]: i for i, a in enumerate(asg) if a[0] == "f"}  # send -> index of its first copy
        first_at = {j: rs[i] for j, i in first_i.items()}
        for i, (r, a) in enumerate(zip(rs, asg)):
            if a[0] == "f":
                d = r - ss[a[1]]
                ok &= lo <= d <= hi
                faults += d > limit
            elif a[0] == "d":
                j = a[1]
                # a duplicate comes after its first copy, within the extra-delay range
                ok &= j in first_i and first_i[j] < i and dlo <= r - rs[first_i[j]] <= dhi
                faults += 1
        if not ok:
            continue
        for j, s in enumerate(ss):
            if j not in first_at:
                faults += F._unreceived(s, ranges, limit, horizon, [])[0] == "drop"
        out.append(((sum(a[0] == "u" for a in asg), faults), list(asg)))
    return out


def test_reply_pairing_is_the_minimum_fault_assignment_with_every_tie():
    # A2, the reply side: compare with every assignment, on random small keys.
    rng = random.Random(5)
    ranges = Ranges((0, 5_000_000), (0, 5_000_000), (0, 5_000_000))
    for _ in range(300):
        ss = sorted(rng.sample(range(0, 6_000_000, 1000), rng.randint(0, 3)))
        rs = sorted(rng.sample(range(0, 9_000_000, 1000), rng.randint(0, 3)))
        best, ties = F._pair_key(ss, rs, ranges, 29_000, 20_000_000, [])
        every = _all_assignments(ss, rs, ranges, 29_000, 20_000_000)
        want = min(c for c, _ in every)
        assert best == want
        assert sorted(map(str, ties)) == sorted(str(a) for c, a in every if c == want)


def test_a_lost_reply_followed_by_a_normal_one_is_one_drop_not_a_long_delay():
    # Two DONE sends, one receive, at the second's usual delay: one drop (the in-order pairing read
    # it as one long delay of the first plus a drop of the second).
    ranges = Ranges((0, 5_000_000), (0, 5_000_000), (0, 5_000_000))
    best, ties = F._pair_key([1_000_000, 3_000_000], [3_004_000], ranges, 29_000, 20_000_000, [])
    assert best == (0, 1) and ties == [[("f", 1)]]


# -- the minimal explanations -------------------------------------------------------------------


def test_a_request_dup_and_an_ack_dup_are_alternatives():
    setup = short([f("c2s", "MOVE_UP", "r-0001", dup_extra_us=300_000)])
    res = fit_log(setup, Ranges.of(setup), usual=USUAL)
    assert res.reproduced and res.minimal_shown and res.min_faults == 1 and res.n_explanations == 2
    assert res.common() == {}
    (group, alts), = res.alternatives()
    assert group == "r-0001"
    assert sorted(k for a in alts for k in a) == [("dup", "c2s", "MOVE_UP", "r-0001", 0), ("dup", "s2c", "ACK", "r-0001", 0)]
    text = "\n".join(report_lines(res))
    assert "alternatives (the minimal explanations differ; values as seen" in text and " | " in text and "fewest faults: 1" in text


def test_a_request_drop_is_common_to_every_minimal_explanation():
    setup = short([f("c2s", "MOVE_UP", "r-0001", drop=True)])
    res = fit_log(setup, Ranges.of(setup), usual=USUAL, plus_one=True)
    assert res.reproduced and res.minimal_shown and res.plus_one_shown
    assert res.min_faults == 1 and res.n_explanations == 1
    assert set(res.common()) == {("drop", "c2s", "MOVE_UP", "r-0001", 0)}
    assert "with one fault more: " in "\n".join(report_lines(res))


CASES = {
    "request drop": [f("c2s", "MOVE_UP", "r-0001", drop=True)],
    "ack drop": [f("s2c", "ACK", "r-0001", drop=True)],
    "request dup": [f("c2s", "MOVE_UP", "r-0001", dup_extra_us=300_000)],
    "ack dup": [f("s2c", "ACK", "r-0001", dup_extra_us=200_000)],
    "done lost, then a normal one": [f("s2c", "ACK", "r-0001", drop=True), f("s2c", "DONE", "r-0001", drop=True)],
    "fault on a retry": [f("c2s", "MOVE_UP", "r-0001", drop=True), f("c2s", "MOVE_UP", "r-0001", 1, dup_extra_us=300_000)],
    "two units": [f("c2s", "MOVE_UP", "r-0001", drop=True), f("s2c", "ACK", "r-0002", dup_extra_us=200_000)],
    "poll request lost": [f("c2s", "STATUS", "s-0002", drop=True)],
    "poll reply duplicated": [f("s2c", "STATUS_REPLY", "s-0002", dup_extra_us=300_000)],
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_search_finds_every_minimal_explanation_that_brute_force_finds(name):
    # A2: every choice of the same option space, run on the whole log with no levels and no units,
    # gives the same explanations with the fewest faults, and with one fault more.
    setup = short(CASES[name])
    res = fit_log(setup, Ranges.of(setup), usual=USUAL, plus_one=True)
    assert res.reproduced and res.minimal_shown and res.plus_one_shown
    found = brute(setup)
    best = min(found.values())
    minimal, plus = flat(res)
    assert res.min_faults == best
    assert minimal == {s for s, n in found.items() if n == best}
    assert plus == {s for s, n in found.items() if n == best + 1}


@pytest.mark.parametrize("name", list(CASES))
def test_no_random_arrival_explains_the_log_with_fewer_faults(name):
    # A5, not a proof: arrivals (and drops, duplicates) drawn at random inside the ranges, off the
    # discrete option points. A reproducing draw with fewer faults than f* would mean the option
    # points miss a smaller explanation.
    setup = short(CASES[name])
    ranges = Ranges.of(setup)
    res = fit_log(setup, ranges, usual=USUAL)
    assert res.reproduced
    q = setup.system.quiet_messages
    atts = [a for a in attempts_of(setup.log, "client") if a.key[0] not in q]
    dis = logged_disconnects(setup.log, "client", setup.until_us)
    r = _Runner(setup, ranges, dis, 10**9, USUAL)
    default = F._default_choice(setup, attempts_of(setup.log, "client"), r)
    probe = r.evaluate_all(Choice(tuple((a.key, ranges.c2s[0]) for a in attempts_of(setup.log, "client")))).first
    bounds = F._arrival_bounds(setup, atts, probe, ranges)
    rng = random.Random(len(name))
    reproduced = 0
    for _ in range(400):
        items = {}
        for a in atts:
            if rng.random() < 0.15:
                items[a.key] = (None, None)
                continue
            b_lo, b_hi = bounds[a.key]
            mode = rng.random()
            if mode < 0.4:  # near the default arrival, off the option points
                d = default.delay(a.key) + rng.randint(-60_000, 60_000)
            elif b_lo <= b_hi and mode < 0.8:  # inside the interval the replies allow
                d = rng.randint(b_lo, b_hi) - a.t_us
            else:  # anywhere in the range
                d = rng.randint(*ranges.c2s)
            d = min(max(d, ranges.c2s[0]), ranges.c2s[1])
            extra = rng.randint(*ranges.dup_extra) if rng.random() < 0.15 else None
            items[a.key] = (d, extra)
        ev = r.evaluate_all(default.assign(items))
        for fd, ok, _ in ev.results:
            if ok:
                reproduced += 1
                assert len(fd) >= res.min_faults, (name, fd)
    assert reproduced > 0  # the draws do reach reproducing explanations


WIDE = Ranges((0, 5_000_000), (0, 5_000_000), (0, 5_000_000))


def test_a_retry_answered_before_the_first_attempt_is_one_late_reply():
    # R04 (testbed-02): the first ACK is 2.5 s late, so the client retries; the retry's ACK (40 ms
    # late, under the limit with a late enough retry) is received first. One fault: the first ACK's
    # delay. It needs the retry to arrive inside the window where both its delay and its ACK's are
    # within the limit, paired with the first receive; the in-order bounds leave that window empty.
    plan = FaultPlan.from_dict({"base": "fixed", "delays": [{**f("s2c", "ACK", "r-0001"), "delay_us": 2_500_000},
                                                            {**f("s2c", "ACK", "r-0001", 1), "delay_us": 40_000}]})
    setup = DrivenSetup(LIFT, logged(run_lift(1, plan=plan, n_commands=2, until_us=14_000_000)), 14_000_000,
                        tolerance_us=25_000)
    assert [e.name for e in setup.log if e.req_id == "r-0001" and e.kind == "recv"] == ["ACK", "ACK", "DONE"]
    res = fit_log(setup, WIDE, usual=USUAL)
    assert res.reproduced and res.minimal_shown and res.min_faults == 1
    (k, (lo, hi)), = res.common().items()
    assert k == ("delay", "s2c", "ACK", "r-0001", 0) and lo <= 2_500_000 <= hi and hi - lo <= 50_000


def test_merged_explanations_keep_the_range_of_their_values():
    # R04's truth (both ACKs late: 2.5 s and 40 ms) has the same faults as the f*+1 explanation of the
    # other pairing (about 2.04 s and 0.5 s). Merged by faults, the explanation keeps both pairings'
    # values as a range per fault, so the truth's values are inside it.
    plan = FaultPlan.from_dict({"base": "fixed", "delays": [{**f("s2c", "ACK", "r-0001"), "delay_us": 2_500_000},
                                                            {**f("s2c", "ACK", "r-0001", 1), "delay_us": 40_000}]})
    setup = DrivenSetup(LIFT, logged(run_lift(1, plan=plan, n_commands=2, until_us=14_000_000)), 14_000_000,
                        tolerance_us=25_000)
    res = fit_log(setup, WIDE, usual=USUAL, plus_one=True)
    k0, k1 = ("delay", "s2c", "ACK", "r-0001", 0), ("delay", "s2c", "ACK", "r-0001", 1)
    both = [x.spans for u in res.units for x in u.plus_one if set(x.faults) == {k0, k1}]
    assert len(both) == 1
    (lo0, hi0), (lo1, hi1) = both[0][k0], both[0][k1]
    assert lo0 <= 2_100_000 and 2_500_000 <= hi0 and lo1 <= 40_000 and 450_000 <= hi1
    d = res.to_dict()
    got = [x for u in d["units"] for e in u["plus_one"] for x in e if x["kind"] == "delay" and x["k"] == 1
           and x["msg"] == "ACK"]
    assert got and got[0]["seen_range_us"] == [lo1, hi1]
    (lo, hi), = res.common().values()
    assert ("common to every minimal explanation (values as seen in the explanations found, not every possible "
            f"value): delay s2c ACK r-0001 k0 {lo / 1e6:.3f}-{hi / 1e6:.3f}s") in report_lines(res)


def test_the_random_arrival_check_finds_what_the_option_points_missed():
    # The check on its own: given the fit R04 got before the fix (f* 2, the retry at the usual
    # delay), draws of the retry's arrival find the 1-fault explanation. Given the fit, none is fewer.
    from dataclasses import replace
    plan = FaultPlan.from_dict({"base": "fixed", "delays": [{**f("s2c", "ACK", "r-0001"), "delay_us": 2_500_000},
                                                            {**f("s2c", "ACK", "r-0001", 1), "delay_us": 40_000}]})
    setup = DrivenSetup(LIFT, logged(run_lift(1, plan=plan, n_commands=2, until_us=14_000_000)), 14_000_000,
                        tolerance_us=25_000)
    res = fit_log(setup, WIDE, usual=USUAL)
    assert res.min_faults == 1
    ok = F.random_arrivals(setup, res, WIDE, USUAL, 100)
    assert ok["reproduced"] > 0 and ok["fewer"] == [] and ok["fewest"] == 1
    old = replace(res, min_faults=2, choice=res.choice.with_delay(("MOVE_UP", "r-0001", 1), USUAL.c2s))
    got = F.random_arrivals(setup, old, WIDE, USUAL, 100)
    assert got["fewer"] and all(len(x) == 1 for x in got["fewer"])
    assert "fewer than the fewest found: " in "\n".join(report_lines(replace(old, random_check=got)))


def test_a_lost_poll_is_a_lost_request_or_a_lost_reply():
    # A poll changes nothing on the device: a lost request and a lost reply look the same.
    setup = short([f("c2s", "STATUS", "s-0002", drop=True)])
    res = fit_log(setup, Ranges.of(setup), usual=USUAL)
    assert res.reproduced and res.minimal_shown and res.min_faults == 1 and res.n_explanations == 2
    assert res.common() == {}
    (group, alts), = res.alternatives()
    assert group == "s-0002"
    assert sorted(k for a in alts for k in a) == [("drop", "c2s", "STATUS", "s-0002", 0),
                                                  ("drop", "s2c", "STATUS_REPLY", "s-0002", 0)]


def test_a_late_poll_reply_is_a_late_request_or_a_late_reply_never_a_lost_request():
    # Poll replies are left out of the match, so a lost request would pass with the logged reply
    # unexplained. The search does not take it: the link cannot invent a reply (testbed-02 S13).
    plan = FaultPlan.from_dict({"base": "fixed", "delays": [{**f("s2c", "STATUS_REPLY", "s-0002"), "delay_us": 300_000}]})
    setup = DrivenSetup(LIFT, logged(run_lift(1, plan=plan, n_commands=2, until_us=14_000_000)), 14_000_000,
                        tolerance_us=25_000)
    res = fit_log(setup, WIDE, usual=USUAL)
    assert res.reproduced and res.min_faults == 1 and res.common() == {}
    (group, alts), = res.alternatives()
    assert group == "s-0002"
    assert sorted(k for a in alts for k in a) == [("delay", "c2s", "STATUS", "s-0002", 0),
                                                  ("delay", "s2c", "STATUS_REPLY", "s-0002", 0)]


def test_one_fault_more_is_searched_outside_the_anomalous_commands():
    # S03 (testbed-02): a request 40 ms late is absorbed (f* 0, nothing anomalous, no unit). The
    # f*+1 level still searches every command, and the late request is there.
    plan = FaultPlan.from_dict({"base": "fixed", "delays": [{**f("c2s", "MOVE_DOWN", "r-0002"), "delay_us": 40_000}]})
    setup = DrivenSetup(LIFT, logged(run_lift(1, plan=plan, n_commands=3, until_us=20_000_000)), 20_000_000,
                        tolerance_us=25_000)
    res = fit_log(setup, Ranges.of(setup), usual=USUAL, plus_one=True)
    assert res.reproduced and res.min_faults == 0 and res.units == [] and res.plus_one_shown
    _, plus = flat(res)
    late = [x for x in plus if {k[:4] for k in x} == {("delay", "c2s", "MOVE_DOWN", "r-0002")}]
    assert late and res.n_plus_one == len(plus)
    vals = [v for u in res.more for x in u.plus_one for k, v in x.faults.items() if k[0] == "delay" and k[1] == "c2s"
            and k[3] == "r-0002"]
    assert any(abs(v - 40_000) <= 25_000 for v in vals)


def test_a_request_in_flight_when_a_logged_disconnect_begins_is_lost_with_it():
    # T12 (testbed-01): the request is sent 40 us before the link goes down, then resent after the
    # reconnect. Lost in the disconnect, not a fault.
    clean = run_lift(1, plan=FaultPlan.from_dict({"base": "fixed"}), n_commands=2, until_us=14_000_000)
    t = next(e.t_us for e in clean.events if e.actor == "client" and e.kind == "send" and e.req_id == "r-0002")
    setup = short(disconnects=[{"t_us": t + 40, "duration_us": 1_500_000}])
    assert any(e.kind == "send" and e.req_id == "r-0002" for e in setup.log)
    res = fit_log(setup, Ranges((0, 5_000_000), (0, 5_000_000), (0, 5_000_000)), usual=USUAL)
    assert res.reproduced and res.min_faults == 0 and res.fit.faults == {}


def test_observed_slow_round_trips_list_what_the_threshold_absorbs():
    # A request 40 ms late splits into two non-faults (request <= 35 ms, ACK <= 35 ms): 0 faults.
    # The round trip is still 40 ms over the log's median: it is listed, apart from the fit.
    plan = FaultPlan.from_dict({"base": "fixed", "delays": [{**f("c2s", "MOVE_DOWN", "r-0002"), "delay_us": 50_000}]})
    setup = DrivenSetup(LIFT, logged(run_lift(1, plan=plan, n_commands=3, until_us=20_000_000)), 20_000_000,
                        tolerance_us=25_000)
    res = fit_log(setup, Ranges.of(setup), usual=USUAL)
    assert res.reproduced and res.min_faults == 0
    assert [(s["req_id"], s["k"], s["excess_us"]) for s in res.slow] == [("r-0002", 0, 40_000)]
    assert "observed slow round trips (from the log, not the fit): MOVE_DOWN r-0002 k0 +40.0ms" in "\n".join(report_lines(res))
    assert slow_round_trips(setup.log, "client", LIFT.quiet_messages, 45_000) == []


def test_receives_nothing_was_sent_for_are_unexplained():
    log = logged(run_lift(7))
    fake = Event(len(log), log[-1].t_us - 1_000_000, "client", "recv", "DONE", "r-0099", log={"line": 999})
    log = sorted([*log, fake], key=lambda e: e.t_us)
    res = fit_log(DrivenSetup(LIFT, log, 90_000_000), cap=20)
    assert not res.reproduced and any(e.req_id == "r-0099" for e in res.fit.unexplained)
    assert "DONE r-0099" in "\n".join(report_lines(res)) and "log line 999" in "\n".join(report_lines(res))


def test_unexplained_only_when_every_choice_of_the_unit_was_run():
    # A DONE far too early for the move: no choice gives it. The unit's choices are few, so all are
    # run, and the receive is evidence about the device. With a small cap it is a fitter limit.
    setup = short([f("c2s", "MOVE_UP", "r-0001", drop=True)], n=1, until=8_000_000)
    early = Event(0, 2_100_000, "client", "recv", "DONE", "r-0001")
    log = sorted([*setup.log, early], key=lambda e: e.t_us)
    from dataclasses import replace
    s2 = replace(setup, log=log)
    res = fit_log(s2, Ranges.of(s2), usual=USUAL)
    assert res.status == "unexplained" and res.units[0].exhausted
    assert "every choice in the fitter's choice space was run" in report_lines(res)[0]
    small = fit_log(s2, Ranges.of(s2), cap=5, usual=USUAL)
    assert small.status == "incomplete" and small.incomplete_reason == "cap"
    assert "run cap reached" in report_lines(small)[0] and "not evidence about the device" in report_lines(small)[0]


def test_delay_ranges_are_parameters():
    # Every message takes exactly 10 ms: fits with the profile's range, not with a 20 ms minimum.
    setup = short()
    assert fit_log(setup).reproduced
    slow = Ranges((20_000, 1_500_000), (20_000, 1_500_000), (0, 4_000_000))
    res = fit_log(setup, slow, cap=50)
    assert not res.reproduced and res.fit.unexplained


def test_a_long_simulator_log_reproduces_and_reports():
    res = fit_log(DrivenSetup(LIFT, logged(run_lift(3)), 90_000_000), branches=True)
    assert res.reproduced and res.matched == res.receives and res.runs <= F.FIT_RUNS
    text = "\n".join(report_lines(res))
    assert "not evidence that there is no defect" in text and "fewest faults:" in text
    assert "attempts with a branch point:" in text and res.branch_checked is not None
    assert "explanations matching every receive, by violated contracts" in text


def test_violation_ambiguity_is_not_resolved_without_expect():
    res = fit_log(short([f("c2s", "MOVE_UP", "r-0001", drop=True)]), usual=USUAL)
    res.outcomes = {(): 3, ("C3",): 1}
    assert res.ambiguous and "none is chosen" in "\n".join(report_lines(res))
    res.expect_given = True
    assert not res.ambiguous


def test_the_fit_is_deterministic():
    setup = short(CASES["two units"])
    a, b = fit_log(setup, usual=USUAL, plus_one=True), fit_log(setup, usual=USUAL, plus_one=True)
    assert (a.status, a.runs, a.fit.plan, a.to_dict()) == (b.status, b.runs, b.fit.plan, b.to_dict())


def test_dropped_traces_are_rebuilt_and_change_nothing(monkeypatch):
    # The runner keeps only the most recent runs whole (memory grew with the run count to several GB);
    # an older run's trace and plans are rebuilt when asked for. Keeping one changes no result.
    setup = short([f("c2s", "MOVE_UP", "r-0001", drop=True), f("s2c", "DONE", "r-0002", dup_extra_us=200_000)])
    full = fit_log(setup, Ranges.of(setup), usual=USUAL, plus_one=True, branches=True)
    runners = []
    init = F._Runner.__init__

    def keep(self, *a, **k):
        init(self, *a, **k)
        runners.append(self)
    monkeypatch.setattr(F._Runner, "__init__", keep)
    monkeypatch.setattr(F, "TRACES_KEPT", 1)
    lean = fit_log(setup, Ranges.of(setup), usual=USUAL, plus_one=True, branches=True)
    assert lean.to_dict() == full.to_dict() and lean.runs == full.runs
    r = max(runners, key=lambda x: len(x.cache))
    assert len(r.cache) > 10 and sum(e.trace is not None for e in r.cache.values()) <= 2
    assert all(e.fit.plan is None for e in r.cache.values() if e.trace is None)


def test_a_dropped_cache_entry_does_not_reach_the_returned_result(monkeypatch):
    # The final choice's entry can be dropped by the runs that follow it (here the f*+1 search outside
    # the units). Dropping clears that entry's plan, so the result must hold a copy, not the entry's
    # own Fit (on all 87 development logs this changed 81 results' plan to None before the fix).
    plan = FaultPlan.from_dict({"base": "fixed", "delays": [{**f("c2s", "MOVE_DOWN", "r-0002"), "delay_us": 40_000}]})
    setup = DrivenSetup(LIFT, logged(run_lift(1, plan=plan, n_commands=3, until_us=20_000_000)), 20_000_000,
                        tolerance_us=25_000)
    full = fit_log(setup, Ranges.of(setup), usual=USUAL, plus_one=True)
    monkeypatch.setattr(F, "TRACES_KEPT", 1)
    lean = fit_log(setup, Ranges.of(setup), usual=USUAL, plus_one=True)
    assert lean.more and lean.fit.plan is not None and lean.fit.plan == full.fit.plan
    assert lean.to_dict() == full.to_dict()


# -- device models -----------------------------------------------------------------------------


def models_of(setup, models=None):
    from dataclasses import replace
    ok = fit_log(setup, Ranges.of(setup), usual=USUAL)
    others = {m: fit_log(replace(setup, mutants=(m,)), Ranges.of(setup), usual=USUAL)
              for m in models or F.device_models(LIFT)}
    return ok, others, F.judge_models(ok, others)


def test_device_models_are_the_published_device_defects():
    assert F.device_models(LIFT) == ["M1", "M2", "M3", "M4", "M5", "M9", "M10", "M11"]


def test_a_defect_is_accused_when_the_correct_model_cannot_explain_and_ties_are_named_together():
    # M2 records an id only at DONE: a copy of the request during the move runs again, so the client
    # gets a second ACK and an ERROR. The correct device never sends that ERROR; M1 (no duplicate
    # detection) does the same as M2 here, with the same one fault, so both are named.
    plan = FaultPlan.from_dict({"base": "fixed", "faults": [f("c2s", "MOVE_UP", "r-0001", dup_extra_us=1_000_000)]})
    log = logged(run_lift(1, plan=plan, n_commands=2, until_us=14_000_000, mutants=("M2",)))
    setup = DrivenSetup(LIFT, log, 14_000_000, tolerance_us=25_000)
    ok, others, d = models_of(setup)
    assert ok.status == "unexplained"
    assert d["accused"] == ["M1", "M2"] and d["accused_size"] == 2 and d["difference"] is None
    assert "M9" in d["fewer"] and others["M9"].min_faults > 1  # fewer than the correct model, not the fewest
    assert d["verdict"] == "defect suspected: M1 or M2" and d["undecided"] == []
    text = "\n".join(F.model_lines(d))
    assert "verdict: defect suspected: M1 or M2 (the correct model is unexplained)" in text


def test_a_tie_is_no_accusation():
    # A request dup with no defect: M1 and M2 explain it as an ACK dup, one fault like the correct model.
    ok, others, d = models_of(short([f("c2s", "MOVE_UP", "r-0001", dup_extra_us=300_000)]), ["M1", "M2", "M4"])
    assert ok.min_faults == 1 and all(r.min_faults == 1 for r in others.values())
    assert d["verdict"] == "correct model" and d["accused"] == [] and d["fewer"] == [] and d["difference"] is None


def test_fewer_faults_counts_the_difference_capped_models_are_no_candidates_and_unsettled_are_undecided():
    from dataclasses import replace
    ok = fit_log(short([f("s2c", "ACK", "r-0001", drop=True), f("s2c", "DONE", "r-0002", drop=True)]),
                 usual=USUAL)
    assert ok.min_faults == 2
    one, zero = replace(ok, min_faults=1), replace(ok, min_faults=0)
    d = F.judge_models(ok, {"M4": one, "M10": zero, "M2": replace(ok, status="incomplete"),
                            "M9": replace(zero, random_check={"fewer": [["x"]]})})
    assert d["fewer"] == ["M4", "M10"] and d["accused"] == ["M10"] and d["difference"] == 2
    assert d["undecided"] == ["M9"]  # a random draw found fewer than its f*
    assert d["capped"] == ["M2"] and d["capped_count"] == 1  # ended by the cap before reproducing: no candidate
    assert ok.units
    capped = replace(ok, units=[replace(u, minimal_shown=False) for u in ok.units])
    d = F.judge_models(capped, {"M4": one})
    assert d["accused"] == [] and d["undecided"] == ["M4"]  # the correct model's minimum is not shown
    assert d["verdict"] == "undecided" and d["capped"] == ["correct"]
    d = F.judge_models(ok, {"M4": replace(ok, status="incomplete"), "M10": replace(ok, status="unexplained")})
    assert d["verdict"] == "correct model" and d["undecided"] == [] and d["capped"] == ["M4"]
    assert "ended by the run cap: M4" in F.model_lines(d)[-1]
    d = F.judge_models(ok, {"M4": replace(one, units=[replace(u, minimal_shown=False) for u in ok.units])})
    assert d["verdict"] == "undecided" and d["undecided"] == ["M4"] and d["capped"] == ["M4"]


def test_a_log_the_correct_model_does_not_settle_is_not_judged():
    # testbed-03 R014/R037: the cap ended every fit, the correct model's included, and the verdict
    # was "correct model". With no candidate, a correct model that is not settled means the log was
    # not judged: the verdict is undecided, never "correct model".
    from dataclasses import replace
    ok = fit_log(short([f("s2c", "ACK", "r-0001", drop=True), f("s2c", "DONE", "r-0002", drop=True)]),
                 usual=USUAL)
    assert F._settled(ok) and ok.units
    incomplete, unexplained = replace(ok, status="incomplete"), replace(ok, status="unexplained")
    not_shown = replace(ok, units=[replace(u, minimal_shown=False) for u in ok.units])
    fewer = replace(ok, random_check={"fewer": [["x"]]})
    cases = [  # (correct, others, reason in the verdict line)
        (incomplete, {"M4": incomplete, "M10": incomplete}, "incomplete, the run cap ended it"),
        (incomplete, {"M4": unexplained}, "incomplete, the run cap ended it"),
        (not_shown, {"M4": incomplete, "M10": unexplained}, "reproduced, the run cap ended it"),
        (fewer, {"M4": unexplained}, "reproduced, a random draw found fewer faults"),
        (unexplained, {"M4": unexplained, "M10": incomplete}, "unexplained, no defect model explains it"),
    ]
    for correct, others, why in cases:
        d = F.judge_models(correct, others)
        assert d["verdict"] == "undecided" and d["accused"] == [] and d["undecided"] == [], why
        assert d["correct_settled"] is False
        line = F.model_lines(d)[-1]
        assert line.startswith("verdict: undecided (the correct model's fit is not settled: " + why), line
        assert "the log is not judged" in line
    d = F.judge_models(incomplete, {"M4": incomplete})
    assert d["capped"] == ["correct", "M4"] and d["capped_count"] == 2
    # Unchanged: a settled defect model with an unexplained correct model is accused; a settled correct
    # model with no candidate is "correct model".
    d = F.judge_models(unexplained, {"M10": ok, "M4": incomplete})
    assert d["verdict"] == "defect suspected: M10" and d["difference"] is None
    d = F.judge_models(ok, {"M4": incomplete, "M10": unexplained})
    assert d["verdict"] == "correct model" and d["correct_settled"] is True
    assert "not settled" not in F.model_lines(d)[-1]


def test_cli_drive_fit(tmp_path, capsys):
    plan = FaultPlan.from_dict({"base": "fixed", "faults": [f("c2s", "MOVE_UP", "r-0001", dup_extra_us=300_000)]})
    log, trace, out_json = tmp_path / "c.log", tmp_path / "c.jsonl", tmp_path / "fit.json"
    log.write_text(text_log(run_lift(1, plan=plan, n_commands=2, until_us=14_000_000).events, "client"))
    assert main(["ingest", str(log), "--rules", str(RULES), "--out", str(trace)]) == 0
    capsys.readouterr()
    args = ["drive", str(trace), "--until", "14s", "--fit", "--tolerance", "25ms", "--usual-delay", "10ms", "10ms"]
    assert main(args + ["--plus-one", "--fit-out", str(out_json), "--branches", "--random-check", "30"]) == 0
    out = capsys.readouterr().out
    assert "fit: reproduced" in out and "fewest faults: 1" in out and "alternatives (" in out
    assert "attempts with a branch point" in out
    assert "random arrivals (a check, not a proof): 30 draws" in out and "fewer than the fewest found: 0" in out
    d = json.loads(out_json.read_text())
    assert d["min_faults"] == 1 and d["explanations"] == 2 and d["minimal_shown"] and d["alternatives"] and d["common"] == []
    assert d["models"] is None
    assert d["random_check"]["draws"] == 30 and d["random_check"]["fewer"] == []
    assert main(args + ["--fit-out", str(out_json)]) == 2  # exists: not overwritten
    assert main(["drive", str(trace), "--until", "14s", "--fit", "--usual-delay", "10s", "10ms"]) == 2
    assert main(["drive", str(trace), "--fit", "--reconstruct"]) == 2
    assert main(["drive", str(trace), "--fit", "--c2s-delay", "2s", "1s"]) == 2


def test_cli_drive_fit_models(tmp_path, capsys):
    plan = FaultPlan.from_dict({"base": "fixed", "faults": [f("c2s", "MOVE_UP", "r-0001", dup_extra_us=1_000_000)]})
    log, trace, out_json = tmp_path / "c.log", tmp_path / "c.jsonl", tmp_path / "fit.json"
    log.write_text(text_log(run_lift(1, plan=plan, n_commands=2, until_us=14_000_000, mutants=("M2",)).events, "client"))
    assert main(["ingest", str(log), "--rules", str(RULES), "--out", str(trace)]) == 0
    capsys.readouterr()
    args = ["drive", str(trace), "--until", "14s", "--fit", "--tolerance", "25ms", "--usual-delay", "10ms", "10ms"]
    main(args + ["--models", "M2,M10", "--random-check", "20", "--fit-out", str(out_json)])
    out = capsys.readouterr().out
    assert "  correct: unexplained" in out and "  M2: f* 1, 1 explanations" in out and "  M10: unexplained" in out
    assert "verdict: defect suspected: M2 (the correct model is unexplained)" in out
    d = json.loads(out_json.read_text())["models"]
    assert d["accused"] == ["M2"] and d["models"]["M2"]["random_fewer"] == 0 and d["fits"]["M2"]["min_faults"] == 1
    for bad in (["--models", "M6"], ["--models", "M2", "--mutant", "M4"], ["--models", ","]):
        assert main(args + bad) == 2
    assert "client defects are not compared" in capsys.readouterr().err
    assert main(args + ["--models", "device"]) in (0, 1)
    assert "  M11: " in capsys.readouterr().out
