"""Implementation variants loaded from outside the package (replayspect.variant)."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.runner import get_system, make_repro, read_repro, replay, run_once, write_repro
from replayspect.session import Session, SessionConfig, environment_diff, read_log, verify_log
from replayspect.sim.link import FaultPlan, MessageFault, MsgKey
from replayspect.variant import VariantError, load_variant

HERE = Path(__file__).resolve().parent
FILE = HERE / "neutral_variants.py"


def spec(name: str, path: Path = FILE) -> str:
    return f"{path}:{name}"


PLAN = FaultPlan(
    faults=(MessageFault(MsgKey("c2s", "TURN_LEFT", "r-0001", 0), drop=True),
            MessageFault(MsgKey("s2c", "ACK", "r-0002", 0), dup_extra_us=2_500_000)),
    base="random",
)


@pytest.mark.parametrize("system,name", [("lift.v0", "SAME_LIFT"), ("turntable.v0", "SAME_TURNTABLE")])
def test_a_variant_wired_from_the_system_parts_gives_the_registered_digest(system, name):
    """A variant must record with the system's own Scheduler, Channel and Trace and use the link
    profile it is given. Built that way, the registered implementation gives the registered digest
    for every seed and plan, so a variant's digest compares with the system's."""
    base, var = get_system(system), get_system(system, spec(name))
    assert var.variant is not None and var.variant.spec == spec(name)
    for seed in range(12):
        for plan in (None, PLAN):
            a, b = run_once(base, seed, (), plan), run_once(var, seed, (), plan)
            assert a.trace.digest() == b.trace.digest()
            assert a.violations == b.violations


def test_only_the_run_changes():
    base, var = get_system("turntable.v0"), get_system("turntable.v0", spec("FEWER_COMMANDS"))
    for field in ("name", "contracts_path", "until_us", "profile", "quiet_messages", "protocol_path", "vocabulary"):
        assert getattr(var, field) == getattr(base, field)
    a, b = run_once(base, 3), run_once(var, 3)
    assert a.trace.digest() != b.trace.digest()
    assert b.violations == []
    assert sum(e.kind == "send" and e.actor == "client" and e.name.startswith("TURN_") and e.data["link"]["k"] == 0
               for e in b.trace) == 3


def test_a_variant_that_records_its_own_way_is_refused():
    var = get_system("lift.v0", spec("OWN_RECORDER"))
    with pytest.raises(TypeError, match="not the package's Trace"):
        run_once(var, 0)


def test_variant_for_another_system_or_not_a_variant():
    with pytest.raises(ValueError, match="implements turntable.v0, not lift.v0"):
        get_system("lift.v0", spec("FEWER_COMMANDS"))
    with pytest.raises(VariantError, match="not a variant"):
        load_variant(spec("NOT_A_VARIANT"))
    with pytest.raises(VariantError, match="no attribute"):
        load_variant(spec("MISSING"))
    with pytest.raises(VariantError, match="not found"):
        load_variant(spec("X", HERE / "nope.py"))
    with pytest.raises(VariantError, match="bad variant spec"):
        load_variant(str(FILE))


def test_a_module_spec_loads_too(monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    v, ref = load_variant("neutral_variants:SAME_LIFT")
    assert v.system == "lift.v0" and ref.sha256 == hashlib.sha256(FILE.read_bytes()).hexdigest()
    with pytest.raises(VariantError, match="cannot import"):
        load_variant("no_such_module_here:X")


def test_a_file_can_import_its_neighbours(tmp_path):
    (tmp_path / "helper_for_variant_test.py").write_text(
        "from replayspect.variant import Variant\nV = Variant('lift.v0', lambda *a: None)\n")
    (tmp_path / "entry.py").write_text("from helper_for_variant_test import V\n")
    v, ref = load_variant(f"{tmp_path / 'entry.py'}:V")
    assert v.system == "lift.v0"
    # The digest covers the named file only, not what it imports.
    assert ref.sha256 == hashlib.sha256((tmp_path / "entry.py").read_bytes()).hexdigest()
    assert str(tmp_path) not in sys.path


def test_mutants_and_a_variant_cannot_be_combined():
    var = get_system("lift.v0", spec("SAME_LIFT"))
    with pytest.raises(ValueError, match="cannot be combined"):
        run_once(var, 0, ["M5"])
    with pytest.raises(ValueError, match="cannot be combined"):
        Session(SessionConfig("lift.v0", ("M5",), variant=spec("SAME_LIFT")))


def _variant_repro(tmp_path, variant_file: Path) -> Path:
    var = get_system("lift.v0", spec("LIFT_PUBLIC_M5", variant_file))
    rnd = run_once(var, 0)
    run = run_once(var, 0, (), FaultPlan.from_trace(rnd.trace), None, rnd.until_us)
    doc = make_repro(run, "C5")
    assert doc["variant"] == {"spec": var.variant.spec, "sha256": var.variant.sha256}
    assert doc["mutants"] == []
    return write_repro(doc, tmp_path / "r.json")


def test_repro_records_the_variant_and_replay_loads_it(tmp_path, capsys):
    path = _variant_repro(tmp_path, FILE)
    r = replay(read_repro(path))
    assert r.ok and r.variant_note is None and r.run.variant is not None
    assert main(["replay", str(path)]) == 0
    assert capsys.readouterr().out.startswith("digest ok")


def test_replay_notes_a_changed_variant_file_first(tmp_path, capsys):
    copy = tmp_path / "v.py"
    copy.write_text(FILE.read_text())
    path = _variant_repro(tmp_path, copy)
    copy.write_text(FILE.read_text() + "\n# edited\n")
    r = replay(read_repro(path))
    assert r.ok and r.variant_note == f"variant file changed since the repro was written: {copy}:LIFT_PUBLIC_M5"
    assert main(["replay", str(path)]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("note: variant file changed") and "the digest decides" in first


def test_repros_without_a_variant_have_no_variant_key():
    run = run_once(get_system("lift.v0"), 0, ["M5"], FaultPlan(base="random"))
    assert "variant" not in make_repro(run, "C5")


def test_session_with_a_variant_logs_it_and_replays(tmp_path):
    log = tmp_path / "log.jsonl"
    s = Session(SessionConfig("lift.v0", variant=spec("SAME_LIFT"), budget=2), log)
    out = s.run_plan({"base": "random", "delays": [], "faults": [], "disconnects": []})
    assert out["status"] == "ok"
    assert "variant" not in json.dumps(s.describe()) and "neutral_variants" not in json.dumps(out)
    head = read_log(log)[0]
    assert head["config"]["variant"] == spec("SAME_LIFT")
    assert head["variant"]["sha256"] == load_variant(spec("SAME_LIFT"))[1].sha256
    assert verify_log(log) == []
    assert not any(line.startswith("variant") for line in environment_diff(log))


def test_session_without_a_variant_logs_as_before(tmp_path):
    log = tmp_path / "log.jsonl"
    Session(SessionConfig("lift.v0", budget=1), log)
    head = read_log(log)[0]
    assert "variant" not in head and "variant" not in head["config"]


def test_cli_search_and_baseline_with_a_variant(tmp_path, capsys):
    v = spec("FEWER_COMMANDS")
    assert main(["search", "--system", "turntable.v0", "--variant", v, "--seeds", "2"]) == 0
    assert f"2 runs, system turntable.v0, variant {v}" in capsys.readouterr().out
    assert main(["baseline", "--system", "turntable.v0", "--variant", v, "--budget", "2"]) == 0
    assert f"variant {v}: no violation" in capsys.readouterr().out
    assert main(["search", "--variant", v, "--mutant", "M1", "--seeds", "1"]) == 2
    assert "cannot be combined" in capsys.readouterr().err
    assert main(["baseline", "--variant", v, "--budget", "1"]) == 2
    assert "implements turntable.v0, not lift.v0" in capsys.readouterr().err
