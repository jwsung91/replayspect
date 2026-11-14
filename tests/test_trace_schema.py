"""WP2: the trace file schema (docs/trace-schema.md, schemas/trace-1.schema.json)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.contract import judge, load_contracts, misses_without_earlier_events, needs_earlier_events
from replayspect.rewind import read_trace
from replayspect.runner import get_system, make_repro, run_once, write_repro
from replayspect.sim.link import FaultPlan
from replayspect.trace import Trace
from replayspect.tracefile import (
    SCHEMA,
    Header,
    TraceFileError,
    contracts_ref,
    core_trace,
    file_sha256,
    parse_trace_file,
    read_trace_file,
    write_trace_file,
)

ROOT = Path(__file__).parent.parent
LIFT = get_system("lift.v0")
TURNTABLE = get_system("turntable.v0")
SCHEMA_FILE = ROOT / "schemas" / "trace-1.schema.json"
EV = {"seq": 0, "t_us": 0, "actor": "a", "kind": "state", "name": "X"}


def out_of(capsys, argv):
    code = main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def repro_file(tmp_path, system, seed, mutants, target, name="r.json"):
    rnd = run_once(system, seed, mutants)
    planned = run_once(system, seed, mutants, FaultPlan.from_trace(rnd.trace))
    return write_repro(make_repro(planned, target), tmp_path / name), planned


@pytest.fixture
def m4(tmp_path, capsys):
    """A lift trace written by ``replay --trace-out`` (seed 58 is where M4 first breaks C3)."""
    repro, run = repro_file(tmp_path, LIFT, 58, ["M4"], "C3")
    out = tmp_path / "m4.jsonl"
    assert out_of(capsys, ["replay", str(repro), "--trace-out", str(out)])[0] == 0
    return out, run, repro


def lines_of(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def header_file(tmp_path, header, events, name="h.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(d) + "\n" for d in [{"type": "header", "schema": SCHEMA, **header}, *events]),
                 encoding="utf-8")
    return p


# -- the digest covers what happened, not how we know it --------------------------------------


def test_fidelity_and_source_are_not_in_the_digest(m4):
    _, run, _ = m4
    other = Trace.from_events([replace(e, fidelity="reconstructed", source="adapter:text") for e in run.trace])
    assert other.digest() == run.trace.digest()
    assert run.trace[0].to_record() == {**run.trace[0].to_dict(), "fidelity": "exact", "source": "sim"}
    assert "fidelity" not in run.trace.to_jsonl()


# -- replay --trace-out writes a header and full event lines ----------------------------------


def test_replay_writes_a_header_then_events_with_fidelity_and_source(m4):
    path, run, repro = m4
    lines = lines_of(path)
    head, events = lines[0], lines[1:]
    assert head == {
        "type": "header", "schema": "replayspect.trace/1", "system": "lift.v0", "source": "sim", "seed": 58,
        "plan": {"sha256": head["plan"]["sha256"], "repro": str(repro)},
        "contracts": {"path": head["contracts"]["path"], "sha256": file_sha256(LIFT.contracts_path)},
        "until_us": 90_000_000, "slice": None,
    }
    assert len(head["plan"]["sha256"]) == 64 and Path(head["contracts"]["path"]).resolve() == LIFT.contracts_path
    assert len(events) == len(run.trace)
    assert all(e["fidelity"] == "exact" and e["source"] == "sim" for e in events)
    # Principle 2: the repro's digest still matches the trace read back from the file.
    assert read_trace(path).digest() == json.loads(repro.read_text())["expect"]["digest"]
    tf = read_trace_file(path)
    assert tf.header.seed == 58 and tf.header.slice is None and tf.trace.events == run.trace.events


def test_mutants_are_not_in_the_header(m4):
    # Mutants are hidden answers for WP4; the header must not carry them.
    path, _, _ = m4
    assert "M4" not in json.dumps({k: v for k, v in lines_of(path)[0].items() if k != "plan"})


# -- files without a header read as before ----------------------------------------------------


def test_a_headerless_file_still_reads_and_defaults_to_sim_and_exact(tmp_path, capsys):
    run = run_once(LIFT, 58, ["M4"])
    p = tmp_path / "old.jsonl"
    p.write_text(run.trace.to_jsonl(), encoding="utf-8")
    tf = read_trace_file(p)
    assert tf.header is None and tf.trace.digest() == run.trace.digest()
    assert {(e.fidelity, e.source) for e in tf.trace} == {("exact", "sim")}
    code, out, _ = out_of(capsys, ["rewind", str(p)])
    assert code == 0 and len(out.splitlines()) == 2 and "header" not in out


def test_events_take_the_header_source_unless_they_name_one(tmp_path):
    p = header_file(tmp_path, {"source": "adapter:text"}, [
        dict(EV), {**EV, "seq": 1, "source": "sim", "fidelity": "reconstructed"}])
    a, b = read_trace_file(p).trace
    assert (a.source, a.fidelity) == ("adapter:text", "exact")
    assert (b.source, b.fidelity) == ("sim", "reconstructed")


# -- the header gives rewind its defaults -----------------------------------------------------


def test_rewind_judges_with_the_header_contracts_and_end(m4, capsys):
    path, _, _ = m4
    code, out, _ = out_of(capsys, ["rewind", str(path)])
    lines = out.splitlines()
    assert code == 0
    assert lines[0] == "judged until t=90.000000s (header until_us)"
    assert lines[1].startswith("  C3 violated at #180 31.712568s r-0004:")
    assert lines[2] == "contracts (lift.v0): 1 violated, 7 ok (C1, C2, C4, C5, C6, C7, C8)"
    assert lines[3].startswith("contracts file: ") and lines[3].endswith("lift.v0.yaml (from header)")


def test_command_line_values_override_the_header_and_say_so(m4, tmp_path, capsys):
    path, _, _ = m4
    code, out, _ = out_of(capsys, ["rewind", str(path), "--end", "95s"])
    assert code == 0 and out.splitlines()[0] == "judged until t=95.000000s (given; differs from header: 90.000000s)"
    code, out, _ = out_of(capsys, ["rewind", str(path), "--end", "90s"])
    assert out.splitlines()[0] == "judged until t=90.000000s (given; same as header)"

    same = str(LIFT.contracts_path)
    code, out, _ = out_of(capsys, ["rewind", str(path), "--contracts", same])
    assert f"contracts file: {same} (given; same file as the header's)" in out.splitlines()
    edited = tmp_path / "edited.yaml"
    edited.write_text(LIFT.contracts_path.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    code, out, _ = out_of(capsys, ["rewind", str(path), "--contracts", str(edited)])
    assert code == 0
    assert any(line.startswith(f"contracts file: {edited} (given; differs from header: ") for line in out.splitlines())


def test_a_changed_or_missing_header_contract_file_is_reported(tmp_path, capsys):
    yaml = tmp_path / "c.yaml"
    yaml.write_text(LIFT.contracts_path.read_text(encoding="utf-8"), encoding="utf-8")
    run = run_once(LIFT, 3)
    events = [e.to_record() for e in run.trace]
    p = header_file(tmp_path, {"contracts": {"path": str(yaml), "sha256": file_sha256(yaml)}, "until_us": 90_000_000},
                    events)
    yaml.write_text(yaml.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    code, out, _ = out_of(capsys, ["rewind", str(p)])
    assert code == 0 and "(from header; changed since the trace was written: sha256 " in out
    yaml.unlink()
    code, out, _ = out_of(capsys, ["rewind", str(p)])
    assert code == 0 and "judged until" not in out
    assert out.splitlines()[0] == f"contracts file: {yaml} (from header) not found; not judged; pass --contracts"


# -- --full writes a slice that reads back ----------------------------------------------------


def test_full_writes_a_slice_with_its_cut_and_the_original_seq(m4, tmp_path, capsys):
    path, run, _ = m4
    dev = tmp_path / "dev.jsonl"
    code, out, _ = out_of(capsys, ["rewind", str(path), "--actor", "device", "--full", str(dev)])
    assert code == 0
    tf = read_trace_file(dev)
    full_head = lines_of(path)[0]
    assert tf.header.slice.to_dict() == {"window": None, "actors": ["device"], "of": run.trace.digest()}
    assert {k: v for k, v in lines_of(dev)[0].items() if k != "slice"} == \
        {k: v for k, v in full_head.items() if k != "slice"}
    assert tf.trace.events == tuple(e for e in run.trace if e.actor == "device")
    seqs = [e.seq for e in tf.trace]
    assert seqs != list(range(len(seqs))) and seqs == sorted(seqs)
    # Judging the slice points at the original position, not the position in the slice.
    code, out, _ = out_of(capsys, ["rewind", str(dev)])
    assert out.splitlines()[1].startswith("  C3 violated at #180 31.712568s r-0004:")


def test_slicing_a_slice_narrows_the_cut_and_keeps_the_original_digest(m4, tmp_path, capsys):
    path, run, _ = m4
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    out_of(capsys, ["rewind", str(path), "--window", "10s", "60s", "--full", str(a)])
    code, _, _ = out_of(capsys, ["rewind", str(a), "--window", "30s", "90s", "--actor", "client", "--full", str(b)])
    assert code == 0
    assert read_trace_file(b).header.slice.to_dict() == {
        "window": [30_000_000, 60_000_000], "actors": ["client"], "of": run.trace.digest()}
    code, _, err = out_of(capsys, ["rewind", str(a), "--window", "70s", "80s", "--full", str(tmp_path / "c.jsonl")])
    assert code == 2 and "does not overlap" in err and not (tmp_path / "c.jsonl").exists()


# -- judging a slice: the window's end, and what a cut start can break ------------------------


@pytest.fixture
def correct_trace(tmp_path):
    """A full trace of the correct lift (seed 0) with a header, so slices of it carry ``until_us``."""
    run = run_once(LIFT, 0)
    path = tmp_path / "full.jsonl"
    write_trace_file(path, run.trace.events, Header(system="lift.v0", seed=0, until_us=run.until_us))
    return path, run


def test_a_window_slice_is_judged_until_the_window_end(correct_trace, tmp_path, capsys):
    path, run = correct_trace
    first = next(e for e in run.trace if e.actor == "client" and e.kind == "send" and e.name == "MOVE_UP")
    cut = tmp_path / "cut.jsonl"
    end = first.t_us + 1_000_000  # C2's 15 s deadline lies after the cut
    out_of(capsys, ["rewind", str(path), "--window", "0", f"{end}us", "--full", str(cut)])
    code, out, _ = out_of(capsys, ["rewind", str(cut), "--contracts", str(LIFT.contracts_path)])
    assert code == 0
    assert out.splitlines()[0] == f"judged until t={end / 1e6:.6f}s (slice window end; the run went on to 90.000000s)"
    assert "C2 violated" not in out and "0 violated" in out
    # --end still wins, and an end past the deadline finds the close missing.
    code, out, _ = out_of(capsys, ["rewind", str(cut), "--contracts", str(LIFT.contracts_path), "--end", "90s"])
    assert "C2 violated at end of run r-0001: never happened" in out


def test_a_slice_with_a_cut_start_does_not_judge_what_the_cut_can_break(correct_trace, tmp_path, capsys):
    path, run = correct_trace
    assert run.violations == []
    mid = tmp_path / "mid.jsonl"
    out_of(capsys, ["rewind", str(path), "--window", "30s", "60s", "--full", str(mid)])
    code, out, _ = out_of(capsys, ["rewind", str(mid), "--contracts", str(LIFT.contracts_path)])
    assert code == 0
    assert "contracts (lift.v0): 0 violated, 1 ok (C4), no violation in the slice (earlier events not seen): " \
           "C1, C2, C6, C8, not judged: C3, C5, C7 (the slice starts at t=30.000000s; earlier events may be cut)" in out
    # Without the rule, the first state event and the first poll reply of the slice fail C3 and C5.
    events = read_trace_file(mid).trace.events
    assert {v.contract for v in judge(core_trace(events), LIFT.contracts(), 60_000_000)} == {"C3", "C5"}
    # The same holds at a rewind time inside the slice.
    code, out, _ = out_of(capsys, ["rewind", str(mid), "--contracts", str(LIFT.contracts_path), "--at", "45s"])
    assert "not judged: C3, C5, C7 (the slice starts at t=30.000000s" in out.split("contracts so far")[1]


def test_a_slice_from_time_zero_or_by_actor_is_judged_in_full(correct_trace, tmp_path, capsys):
    path, _ = correct_trace
    dev = tmp_path / "dev.jsonl"
    out_of(capsys, ["rewind", str(path), "--actor", "device", "--full", str(dev)])
    code, out, _ = out_of(capsys, ["rewind", str(dev), "--contracts", str(LIFT.contracts_path)])
    assert "not judged" not in out and out.splitlines()[0] == "judged until t=90.000000s (header until_us)"


ONCE = {"protocol": "p", "contracts": [{"id": "C1", "desc": "motor starts at most once per req_id",
                                         "kind": "at_most_once", "per": "req_id", "event": "device.effect(motor_start)"}]}


def start(seq, t_us):
    return {"seq": seq, "t_us": t_us, "actor": "device", "kind": "effect", "name": "motor_start", "req_id": "r-0001"}


@pytest.mark.parametrize("window, events, line, status", [
    # the second start is in the slice: violated, as before
    ([10, 100], [start(3, 20), start(5, 30)], "  C1 violated at #5 0.000030s r-0001: motor_start #2", "violated"),
    # the first start (seq 1, t=5) was cut: the second looks like a first, so nothing is found in the slice
    ([10, 100], [start(5, 30)], "0 violated, 0 ok, no violation in the slice (earlier events not seen): C1",
     "no violation in the slice"),
    # a window from time 0 cuts nothing at the start: ok
    ([0, 100], [start(5, 30)], "0 violated, 1 ok (C1)", "ok"),
])
def test_a_kind_that_a_cut_start_can_only_make_miss(tmp_path, capsys, window, events, line, status):
    import yaml
    from replayspect.rewind import contract_status
    c = tmp_path / "c.yaml"
    c.write_text(yaml.safe_dump(ONCE), encoding="utf-8")
    path = header_file(tmp_path, {"until_us": 200, "slice": {"window": window, "actors": None, "of": None}}, events)
    code, out, _ = out_of(capsys, ["rewind", str(path), "--contracts", str(c)])
    assert code == 0 and line in out
    cut = window[0] if window[0] > 0 else None
    st = contract_status(read_trace_file(path).trace.events, load_contracts(ONCE), 100, "window end", cut)
    assert st.to_dict() == {"C1": status}


def test_which_contract_kinds_a_cut_start_can_break():
    cs = LIFT.contracts()
    assert {c.id for c in cs.contracts if misses_without_earlier_events(c)} == {"C1", "C2", "C6", "C8"}
    assert {c.id for c in cs.contracts if needs_earlier_events(c)} == {"C3", "C5", "C7"}  # state_machine,
    # consistent with last(...), count_le; a forbid only when its condition reads last(...).
    base = {"id": "X", "desc": "x", "kind": "forbid", "event": "device.send(DONE)"}
    plain = load_contracts({"protocol": "p", "contracts": [{**base, "when": "req_id == null"}]})
    with_last = load_contracts({"protocol": "p", "contracts": [
        {**base, "when": "last(device.effect(motor_stop)).req_id != req_id"}]})
    assert not needs_earlier_events(plain.contracts[0]) and needs_earlier_events(with_last.contracts[0])


# -- bad files fail with the line number ------------------------------------------------------


@pytest.mark.parametrize("lines, lineno, message", [
    ([EV, {"type": "header", "schema": SCHEMA}], 2, "may only be the first line"),
    ([{"type": "footer"}], 1, "unknown line type 'footer'"),
    ([{"type": "header", "schema": "replayspect.trace/2"}], 1, "replayspect.trace/2 is not supported"),
    ([{"type": "header", "schema": "trace"}], 1, "header schema must look like"),
    ([{"type": "header", "schema": SCHEMA, "source": "log"}], 1, "header source must be"),
    ([{"type": "header", "schema": SCHEMA, "until_us": 5}, {**EV, "t_us": 9}], 1, "is before the last event"),
    ([{"type": "header", "schema": SCHEMA, "seed": -1}], 1, "header seed must be a non-negative integer"),
    ([{"type": "header", "schema": SCHEMA, "contracts": {"path": "c.yaml"}}], 1, "needs a non-empty sha256"),
    ([{"type": "header", "schema": SCHEMA, "slice": {"window": [5, 1]}}], 1, "starts after it ends"),
    ([{"type": "header", "schema": SCHEMA, "slice": {"of": "x"}}, {**EV, "seq": 4}, {**EV, "seq": 4}], 3,
     "a slice's seq must increase"),
    ([{**EV, "seq": 1}], 1, "seq 1 out of order; expected 0"),
    ([{**EV, "fidelity": "guessed"}], 1, "fidelity must be one of exact, reconstructed"),
    ([{**EV, "source": "adapter:"}], 1, "source must be 'sim' or 'adapter:<name>'"),
])
def test_a_bad_trace_file_fails_with_its_line_number(tmp_path, lines, lineno, message):
    p = tmp_path / "bad.jsonl"
    p.write_text("".join(json.dumps(d) + "\n" for d in lines), encoding="utf-8")
    with pytest.raises(TraceFileError) as exc:
        read_trace_file(p)
    assert str(exc.value).startswith(f"{p}:{lineno}: ") and message in str(exc.value)


def test_unknown_fields_are_ignored():
    text = json.dumps({"type": "header", "schema": SCHEMA, "later": 1}) + "\n" + json.dumps({**EV, "note": "x"})
    tf = parse_trace_file(text)
    assert len(tf.trace) == 1 and tf.header.schema == SCHEMA


# -- the JSON Schema accepts what we write and rejects what the reader rejects ----------------


@pytest.fixture(scope="module")
def validator():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_existing_traces_validate_against_the_schema(validator, m4, tmp_path, capsys):
    path, run, _ = m4
    old = tmp_path / "old.jsonl"
    old.write_text(run.trace.to_jsonl(), encoding="utf-8")  # a WP1-era file: no header, no fidelity
    sliced = tmp_path / "s.jsonl"
    out_of(capsys, ["rewind", str(path), "--window", "10s", "20s", "--actor", "device", "--full", str(sliced)])
    tt = tmp_path / "tt.jsonl"  # the turntable has no mutants yet, so no repro: write its run directly
    tt_run = run_once(TURNTABLE, 7)
    write_trace_file(tt, tt_run.trace.events, Header(system="turntable.v0", seed=7, until_us=tt_run.until_us,
                                                     contracts=contracts_ref(TURNTABLE.contracts_path)))
    checked = 0
    for f in (path, old, sliced, tt):
        for d in lines_of(f):
            errors = list(validator.iter_errors(d))
            assert not errors, f"{f}: {d}: {errors[0].message}"
            checked += 1
    assert checked > 900


@pytest.mark.parametrize("line", [
    {**EV, "kind": "bogus"},
    {**EV, "t_us": 1.5},
    {**EV, "name": ""},
    {**EV, "data": [1]},
    {**EV, "fidelity": "guessed"},
    {**EV, "source": "log"},
    {k: v for k, v in EV.items() if k != "name"},
    {"type": "header", "schema": "replayspect.trace/2"},
    {"type": "header", "schema": SCHEMA, "seed": -1},
    {"type": "header", "schema": SCHEMA, "contracts": {"path": "c.yaml"}},
    {"type": "footer", "schema": SCHEMA},
])
def test_the_schema_rejects_lines_the_reader_rejects(validator, line):
    assert list(validator.iter_errors(line))
    with pytest.raises(TraceFileError):
        parse_trace_file(json.dumps(line))
