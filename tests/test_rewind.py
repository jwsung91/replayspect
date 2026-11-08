"""WP1: the rewind viewer reads trace files only and is deterministic."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.rewind import (
    Selection,
    TraceFileError,
    cursor_at,
    divergence,
    parse_time_us,
    parse_trace,
    read_trace,
    step,
    view,
)
from replayspect.runner import get_system, make_repro, run_once, write_repro
from replayspect.sim.link import FaultPlan
from replayspect.trace import Trace

ROOT = Path(__file__).parent.parent
LIFT = get_system("lift.v0")
TURNTABLE = get_system("turntable.v0")
LIFT_CONTRACTS = str(ROOT / "contracts" / "lift.v0.yaml")
TURNTABLE_CONTRACTS = str(ROOT / "contracts" / "turntable.v0.yaml")


def write_trace(tmp_path, trace, name="t.jsonl"):
    p = tmp_path / name
    p.write_text(trace.to_jsonl(), encoding="utf-8")
    return p


@pytest.fixture
def m4_run():
    # seed 58 is the first random seed at which M4 breaks C3 (tests/test_lift.py)
    return run_once(LIFT, 58, ["M4"])


@pytest.fixture
def m4_file(tmp_path, m4_run):
    return write_trace(tmp_path, m4_run.trace, "m4.jsonl")


def out_of(capsys, argv):
    code = main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


# -- reading trace files ---------------------------------------------------------------------


def test_a_written_trace_reads_back_identically(m4_run, m4_file):
    back = read_trace(m4_file)
    assert back.digest() == m4_run.trace.digest()
    assert back.events == m4_run.trace.events


@pytest.mark.parametrize("lines, lineno, message", [
    (['{"seq":0,"t_us":0,"actor":"a","kind":"state","name":"X"}', "not json"], 2, "Expecting value"),
    (['{"seq":0,"t_us":0,"actor":"a","kind":"bogus","name":"X"}'], 1, "unknown event kind"),
    (['{"seq":0,"t_us":0,"actor":"a","kind":"state"}'], 1, "missing field(s) name"),
    (['{"seq":0,"t_us":0,"actor":"a","kind":"state","name":"X"}',
      '{"seq":2,"t_us":1,"actor":"a","kind":"state","name":"Y"}'], 2, "seq 2 out of order; expected 1"),
    (['{"seq":0,"t_us":5,"actor":"a","kind":"state","name":"X"}',
      '{"seq":1,"t_us":4,"actor":"a","kind":"state","name":"Y"}'], 2, "time goes backwards"),
    (['{"seq":0,"t_us":1.5,"actor":"a","kind":"state","name":"X"}'], 1, "t_us must be a non-negative integer"),
    (['{"seq":0,"t_us":0,"actor":"a","kind":"send","name":"X","req_id":7}'], 1, "req_id must be a string"),
    (['{"seq":0,"t_us":0,"actor":"a","kind":"send","name":"X","data":[1]}'], 1, "data must be an object"),
    (['[1, 2]'], 1, "expected a JSON object"),
])
def test_a_bad_trace_file_fails_with_its_line_number(tmp_path, lines, lineno, message):
    p = tmp_path / "bad.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(TraceFileError) as exc:
        read_trace(p)
    assert str(exc.value).startswith(f"{p}:{lineno}: ")
    assert message in str(exc.value)


def test_blank_lines_are_skipped_but_counted_and_extra_fields_ignored():
    text = ('{"seq":0,"t_us":0,"actor":"a","kind":"state","name":"X","source":"sim"}\n\n'
            '{"seq":1,"t_us":1,"actor":"a","kind":"bogus","name":"Y"}\n')
    with pytest.raises(TraceFileError, match=r"^f:3: "):
        parse_trace(text, "f")
    assert len(parse_trace(text.splitlines()[0])) == 1


def test_cli_reports_unreadable_input_with_status_2(tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{}\n", encoding="utf-8")
    code, out, err = out_of(capsys, ["rewind", str(bad)])
    assert code == 2 and out == "" and f"{bad}:1: missing field(s)" in err
    code, _, err = out_of(capsys, ["rewind", str(tmp_path / "missing.jsonl")])
    assert code == 2 and "missing.jsonl" in err


@pytest.mark.parametrize("text, us", [
    ("1500000", 1_500_000), ("1.5s", 1_500_000), ("1500ms", 1_500_000), ("1500000us", 1_500_000), ("0", 0),
])
def test_times(text, us):
    assert parse_time_us(text) == us


@pytest.mark.parametrize("bad", ["-1", "1.5 m", "s", "1e6", ""])
def test_bad_times(bad):
    with pytest.raises(ValueError):
        parse_time_us(bad)


# -- rewinding and stepping ------------------------------------------------------------------


def test_rewinding_to_a_time_gives_the_same_events_every_run(m4_run, m4_file):
    """Done-when of WP1: replay a trace, rewind to a time, get identical events every run."""
    t = 20_000_000
    views = [view(read_trace(m4_file), at_us=t, step_n=-8).lines for _ in range(3)]
    assert views[0] == views[1] == views[2]
    replayed = run_once(LIFT, 58, ["M4"]).trace  # a fresh replay of the same seed
    assert view(replayed, at_us=t, step_n=-8).lines == views[0]
    cursor = cursor_at(replayed, t)
    assert all(e.t_us <= t for e in replayed.events[:cursor])
    assert all(e.t_us > t for e in replayed.events[cursor:])


def test_rewind_output_is_the_same_in_fresh_processes_with_other_hash_seeds(m4_file):
    argv = [sys.executable, "-m", "replayspect", "rewind", str(m4_file), "--at", "20s", "--step", "-8",
            "--contracts", LIFT_CONTRACTS]
    outs = {
        subprocess.run(argv, capture_output=True, text=True, check=True,
                       env=dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONHASHSEED=h)).stdout
        for h in ("0", "1", "4242")
    }
    assert len(outs) == 1


def test_steps_go_forward_and_back_from_the_cursor(m4_run):
    tr = m4_run.trace
    cursor = cursor_at(tr, 20_000_000)
    assert step(tr, cursor, 3, Selection()) == list(tr.events[cursor:cursor + 3])
    assert step(tr, cursor, -3, Selection()) == list(tr.events[cursor - 3:cursor])
    assert step(tr, cursor, 0, Selection()) == []
    assert step(tr, 0, -5, Selection()) == []
    assert step(tr, len(tr), 5, Selection()) == []
    device = Selection(actors=frozenset({"device"}))
    fwd = step(tr, cursor, 4, device)
    assert len(fwd) == 4 and all(e.actor == "device" and e.seq >= cursor for e in fwd)


def test_cursor_includes_every_event_at_the_time(m4_run):
    tr = m4_run.trace
    t = tr.events[50].t_us
    cursor = cursor_at(tr, t)
    assert tr.events[cursor - 1].t_us == t and (cursor == len(tr) or tr.events[cursor].t_us > t)
    assert cursor_at(tr, 0) == len([e for e in tr if e.t_us == 0])
    assert cursor_at(tr, 10**12) == len(tr)


def test_the_state_at_a_time_is_each_actors_latest_state(m4_run):
    tr = m4_run.trace
    t = 20_000_000
    lines = view(tr, at_us=t).lines
    expected = [e for e in tr if e.kind == "state" and e.actor == "device" and e.t_us <= t][-1]
    device_line = next(line for line in lines if line.startswith("  device: "))
    assert f"state {expected.name} (since " in device_line


# -- selecting -------------------------------------------------------------------------------


def test_a_window_never_contains_events_outside_it(m4_run, capsys, m4_file):
    tr = m4_run.trace
    t0, t1 = tr.events[100].t_us, tr.events[140].t_us
    sel = Selection((t0, t1))
    got = sel.apply(tr)
    assert got == [e for e in tr if t0 <= e.t_us <= t1]
    assert got[0].t_us == t0 and got[-1].t_us == t1  # both ends are inclusive
    code, out, _ = out_of(capsys, ["rewind", str(m4_file), "--window", f"{t0}", f"{t1}", "--limit", "1000"])
    assert code == 0
    listed = [line.strip() for line in out.splitlines() if line.startswith("  #")]
    assert len(listed) == len(got)
    for line in listed:
        t = round(float(line.split()[1][:-1]) * 1_000_000)
        assert t0 <= t <= t1


def test_a_window_that_ends_before_it_starts_is_rejected(m4_file, capsys):
    code, _, err = out_of(capsys, ["rewind", str(m4_file), "--window", "5s", "4s"])
    assert code == 2 and "window starts after it ends" in err


def test_actor_filter_keeps_only_that_participant(m4_run, m4_file, capsys):
    code, out, _ = out_of(capsys, ["rewind", str(m4_file), "--actor", "link", "--window", "0", "90s",
                                   "--limit", "1000"])
    assert code == 0
    listed = [line for line in out.splitlines() if line.startswith("  #")]
    assert listed and all(line.split()[2] == "link" for line in listed)
    assert len(listed) == sum(e.actor == "link" for e in m4_run.trace)


# -- reference traces ------------------------------------------------------------------------


def test_divergence_from_a_reference(tmp_path, m4_run):
    same = divergence(m4_run.trace.events, run_once(LIFT, 58, ["M4"]).trace.events)
    assert same.index is None and same.compared == len(m4_run.trace)
    other = run_once(LIFT, 59, ["M4"]).trace
    d = divergence(m4_run.trace.events, other.events)
    i = next(i for i, (a, b) in enumerate(zip(m4_run.trace, other)) if a.to_dict() != b.to_dict())
    assert d.index == i and d.ours == m4_run.trace.events[i] and d.theirs == other.events[i]
    prefix = divergence(m4_run.trace.events[:10], m4_run.trace.events)
    assert (prefix.index, prefix.ours, prefix.theirs) == (10, None, m4_run.trace.events[10])


def test_cli_reference(tmp_path, m4_file, capsys):
    ref = write_trace(tmp_path, run_once(LIFT, 58).trace, "correct.jsonl")  # same seed, no mutant
    code, out, _ = out_of(capsys, ["rewind", str(m4_file), "--ref", str(ref)])
    assert code == 0 and "reference: first divergence at position" in out
    code, out, _ = out_of(capsys, ["rewind", str(m4_file), "--ref", str(m4_file)])
    assert "reference: identical (" in out


# -- contracts -------------------------------------------------------------------------------


def test_contract_status_first_line_names_the_end_time(m4_file, capsys, m4_run):
    code, out, _ = out_of(capsys, ["rewind", str(m4_file), "--contracts", LIFT_CONTRACTS])
    lines = out.splitlines()
    last = m4_run.trace.events[-1].t_us
    assert code == 0
    assert lines[0] == f"judged until t={last / 1e6:.6f}s (last event; pass --end to change)"
    assert any(line.startswith("  C3 violated at #") for line in lines)
    code, out, _ = out_of(capsys, ["rewind", str(m4_file), "--contracts", LIFT_CONTRACTS, "--end", "120s"])
    assert out.splitlines()[0] == "judged until t=120.000000s (given)"


def test_the_end_time_changes_deadline_verdicts(tmp_path, capsys):
    # A command that is never answered: C2 fails only once 15 s have passed by the end time.
    tr = run_once(LIFT, 0, [], until_us=6_000_000).trace
    p = write_trace(tmp_path, tr)
    _, early, _ = out_of(capsys, ["rewind", str(p), "--contracts", LIFT_CONTRACTS])
    _, late, _ = out_of(capsys, ["rewind", str(p), "--contracts", LIFT_CONTRACTS, "--end", "90s"])
    assert "C2 violated" not in early and "C2 violated at end of run" in late


def test_an_end_before_the_last_event_or_without_contracts_is_rejected(m4_file, capsys):
    code, _, err = out_of(capsys, ["rewind", str(m4_file), "--contracts", LIFT_CONTRACTS, "--end", "1s"])
    assert code == 2 and "before the last event" in err
    code, _, err = out_of(capsys, ["rewind", str(m4_file), "--end", "90s"])
    assert code == 2 and "needs contracts (--contracts or the trace header)" in err


def test_contracts_so_far_only_judge_events_up_to_the_rewind_time(m4_run):
    cs = LIFT.contracts()
    first = next(v for v in m4_run.first() if v.contract == "C3")
    before = view(m4_run.trace, at_us=m4_run.trace.events[first.seq].t_us - 1, contracts=cs).lines
    after = view(m4_run.trace, at_us=m4_run.trace.events[first.seq].t_us, contracts=cs).lines
    assert any("contracts so far: 0 violated" in line for line in before)
    assert any("contracts so far: 1 violated" in line for line in after)


def test_contracts_that_match_nothing_are_not_exercised(tmp_path, capsys):
    p = tmp_path / "one.jsonl"
    p.write_text('{"seq":0,"t_us":0,"actor":"device","kind":"state","name":"DOWN",'
                 '"data":{"from":null,"on":"init"}}\n', encoding="utf-8")
    code, out, _ = out_of(capsys, ["rewind", str(p), "--contracts", LIFT_CONTRACTS])
    assert code == 0
    assert "contracts (lift.v0): 0 violated, 1 ok (C3), not exercised: C1, C2, C4, C5, C6, C7, C8" in out


# -- both example systems --------------------------------------------------------------------


def test_works_on_a_turntable_trace(tmp_path, capsys):
    tr = run_once(TURNTABLE, 3).trace
    p = write_trace(tmp_path, tr)
    code, out, _ = out_of(capsys, ["rewind", str(p), "--contracts", TURNTABLE_CONTRACTS, "--end", "90s",
                                   "--at", "10s", "--step", "3", "--actor", "device"])
    assert code == 0
    assert "contracts (turntable.v0): 0 violated, 8 ok" in out
    assert "  device: state " in out and "step 3: selected events after t=10.000000s (3):" in out


# -- output stays short ----------------------------------------------------------------------


def test_listings_are_capped_and_the_full_dump_goes_to_a_new_file(tmp_path, m4_run, m4_file, capsys):
    full = tmp_path / "out" / "full.jsonl"
    code, out, _ = out_of(capsys, ["rewind", str(m4_file), "--window", "0", "90s", "--limit", "5",
                                   "--full", str(full)])
    assert code == 0
    assert len([line for line in out.splitlines() if line.startswith("  #")]) == 5
    assert f"... {len(m4_run.trace) - 5} more" in out
    assert len(out.splitlines()) < 20
    dumped = read_trace(full)  # WP2: the dump is a trace file and reads back
    assert dumped.events == m4_run.trace.events
    code, _, err = out_of(capsys, ["rewind", str(m4_file), "--full", str(full)])
    assert code == 2 and "not overwriting" in err


def test_default_output_is_a_summary(m4_file, capsys):
    code, out, _ = out_of(capsys, ["rewind", str(m4_file)])
    assert code == 0 and len(out.splitlines()) == 2 and "#" not in out


# -- replay --trace-out ----------------------------------------------------------------------


def test_replay_writes_the_trace_it_reproduced(tmp_path, m4_run, capsys):
    planned = run_once(LIFT, 58, ["M4"], FaultPlan.from_trace(m4_run.trace))
    repro = write_repro(make_repro(planned, "C3"), tmp_path / "r.json")
    out_path = tmp_path / "traces" / "r.jsonl"
    code, out, _ = out_of(capsys, ["replay", str(repro), "--trace-out", str(out_path)])
    assert code == 0 and f"trace: {len(m4_run.trace)} events -> {out_path}" in out
    assert read_trace(out_path).digest() == json.loads(repro.read_text())["expect"]["digest"]
    code, _, err = out_of(capsys, ["replay", str(repro), "--trace-out", str(out_path)])
    assert code == 2 and "not overwriting" in err


def test_rewind_does_not_need_the_system_that_made_the_trace():
    # An adapter's trace has made-up actors and no simulator data; the reader must not care.
    text = "".join(json.dumps(d) + "\n" for d in [
        {"seq": 0, "t_us": 0, "actor": "controller", "kind": "send", "name": "GO", "req_id": "a1"},
        {"seq": 1, "t_us": 7, "actor": "module", "kind": "recv", "name": "GO", "req_id": "a1"},
        {"seq": 2, "t_us": 9, "actor": "module", "kind": "effect", "name": "spin", "data": {"rpm": 3}},
    ])
    tr = parse_trace(text)
    lines = view(tr, at_us=8, step_n=1).lines
    assert "  controller: no state recorded; last event #0 0.000000s controller send GO a1" in lines
    assert lines[-1] == '  #2 0.000009s module effect spin - {"rpm":3}'
    assert isinstance(tr, Trace)
