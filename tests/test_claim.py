"""claim check: a candidate contract against incidents and a normal corpus (simulator data only)."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from replayspect.__main__ import main
from replayspect.claim import check_claims
from replayspect.devicelog import Completeness, device_report, read_device_log
from replayspect.runner import get_system
from replayspect.sut.lift import run_lift
from replayspect.tracefile import Header, write_trace_file

LIFT = get_system("lift.v0")
REV2 = Path(__file__).parent.parent / "contracts" / "lift.v0.rev2.yaml"
SOURCE = {"doc": "docs/protocol-lift.md", "lines": "43-46", "quote": "a test candidate"}
FULL = ["device:recv,send,state,effect"]
T = "2026-11-13T22:43:05.116898+09:00"

#: C10 as the rev2 file states it: DONE only after the motor stopped for that id.
C10 = next(c for c in yaml.safe_load(REV2.read_text())["contracts"] if c["id"] == "C10")
#: The count_le form of "DONE only after the stop", which a correct device breaks: a repeat after DONE is
#: answered with DONE again, with no second stop.
D1 = {"id": "D1", "desc": "no more DONE than motor stops per id", "kind": "count_le", "per": "req_id",
      "event": "device.send(DONE)", "bound": "device.effect(motor_stop)", "grade": "stated", "source": SOURCE}
#: About a message the lift never sends: it cannot be exercised.
X1 = {"id": "X1", "desc": "at most one BRAKE per id", "kind": "at_most_once", "per": "req_id",
      "event": "device.send(BRAKE)", "grade": "stated", "source": SOURCE}
#: No ACK for an id after its DONE or ERROR.
N1 = {"id": "N1", "desc": "no ACK after the end", "kind": "never_after", "per": "req_id",
      "event": "device.send(ACK)", "after": "device.send(DONE|ERROR)", "grade": "stated", "source": SOURCE}

#: A device log of a correct lift, with one change: a repeat of a refused request answered DONE, no move.
UNMOVED = [
    "0 build defect=none", "0 state DOWN from=- on=init",
    "4 recv MOVE_UP r-0001", "4 send ACK r-0001",
    "54 effect motor_start r-0001 dir=up", "54 state MOVING_UP r-0001 from=DOWN on=MOVE_UP",
    "2000 recv MOVE_DOWN r-0002", "2000 send ACK r-0002", "2050 send ERROR r-0002 reason=illegal",
    "2500 recv MOVE_DOWN r-0002", "2500 send DONE r-0002",
    "3054 effect motor_stop r-0001", "3054 state UP r-0001 from=MOVING_UP on=arrived", "3054 send DONE r-0001",
]


def dlog(path, lines):
    path.write_text("".join(f"{T} # {x}\n" for x in lines), encoding="utf-8")
    return path


def candidates(tmp_path, *cs, name="cands.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump({"protocol": "lift.v0", "contracts": list(cs)}, sort_keys=False), encoding="utf-8")
    return p


def sim_trace(tmp_path, seed, mutants=(), name=None):
    p = tmp_path / (name or f"sim-{seed}.jsonl")
    write_trace_file(p, run_lift(seed, mutants=list(mutants)).events,
                     Header(system="lift.v0", seed=seed, until_us=LIFT.until_us))
    return p


def out_of(capsys, argv):
    code = main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def by_id(rep, cid):
    return next(r for r in rep["results"] if r["id"] == cid)


# -- the three cases the work order names ------------------------------------------------------------


@pytest.fixture(scope="module")
def three(tmp_path_factory):
    d = tmp_path_factory.mktemp("claim")
    cands = candidates(d, C10, D1)
    incident = sim_trace(d, 36, ["M10"], "m10-36.jsonl")  # M10 answers a repeat of a refused request DONE
    return d, cands, incident, check_claims(cands, [(incident, None)], normal=[], seeds=range(10), system=LIFT)


def test_a_known_good_candidate_passes(three):
    _, _, incident, rep = three
    r = by_id(rep, "C10")
    assert r["verdict"] == "passes" and r["reasons"] == []
    (inc,) = r["incidents"]
    assert inc["input"] == str(incident) and inc["status"] == "violated"
    assert inc["first_violation"]["req_id"] is not None and inc["first_violation"]["t_us"] > 0
    assert inc["same_request"] == "not given" and inc["model_first_mismatch"] == "not given"
    assert r["normal"]["inputs"] == 10 and r["normal"]["exercised"] == 10 and r["normal"]["violations"] == []


def test_a_candidate_that_a_correct_device_breaks_fails(three):
    _, _, _, rep = three
    r = by_id(rep, "D1")
    assert r["verdict"] == "fails"
    n = len({v["input"] for v in r["normal"]["violations"]})
    assert n == 10 and r["reasons"] == [f"violated on {n} of 10 normal inputs"]
    v = r["normal"]["violations"][0]
    assert v["input"] == "lift.v0 seed 0" and v["req_id"].startswith("r-") and v["detail"].startswith("DONE #2")
    # every violation is listed, not only the first per input
    assert len(r["normal"]["violations"]) >= n


def adapter_trace(path, rows):
    """rows: (t_us, name, req_id), device sends."""
    ev = {"source": "adapter:x", "actor": "device", "kind": "send"}
    path.write_text("".join(json.dumps(x) + "\n" for x in [
        {"type": "header", "schema": "replayspect.trace/1", "source": "adapter:x"},
        *({**ev, "seq": i, "t_us": t, "name": n, "req_id": r} for i, (t, n, r) in enumerate(rows))]),
        encoding="utf-8")
    return path


def test_a_candidate_never_exercised_is_untested(tmp_path):
    incident = adapter_trace(tmp_path / "brake.jsonl", [(10, "BRAKE", "r-0001"), (20, "BRAKE", "r-0001")])
    rep = check_claims(candidates(tmp_path, X1), [(incident, None)], normal=[], seeds=range(10), system=LIFT)
    (r,) = rep["results"]
    assert r["incidents"][0]["status"] == "violated"
    assert r["verdict"] == "untested" and r["reasons"] == ["never exercised on the normal corpus (10 inputs)"]
    assert r["normal"]["exercised"] == 0 and r["normal"]["statuses"] == {"not exercised": 10}


def test_failing_on_an_incident_comes_before_untested(tmp_path):
    rep = check_claims(candidates(tmp_path, X1), [(sim_trace(tmp_path, 36, ["M10"]), None)], normal=[],
                       seeds=range(2), system=LIFT)
    (r,) = rep["results"]
    assert r["verdict"] == "fails"
    assert r["reasons"][0].startswith("not caught on incident ") and r["reasons"][0].endswith("(not exercised)")


# -- incidents: device logs, completeness, the model result -----------------------------------------


def model_result(tmp_path, log_path, name="rep.json"):
    rep = device_report(LIFT, read_device_log(log_path.read_text()), complete=Completeness.parse(FULL))
    p = tmp_path / name
    p.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def test_the_model_result_says_whether_the_request_is_the_first_mismatch(tmp_path):
    log = dlog(tmp_path / "inc-device.log", UNMOVED)
    rep_file = model_result(tmp_path, log)
    cands = candidates(tmp_path, C10)
    rep = check_claims(cands, [(log, rep_file)], normal=[], seeds=range(2), system=LIFT, complete=FULL)
    inc = rep["results"][0]["incidents"][0]
    assert inc["first_violation"] == {"req_id": "r-0002", "t_us": 2_500_000,
                                      "detail": "DONE with no earlier device.effect(motor_stop)"}
    assert inc["model_first_mismatch"] == "r-0002" and inc["same_request"] == "yes"
    assert rep["incidents"] == [{"path": str(log), "kind": "device log", "sha256": sha(log),
                                 "model_result": {"path": str(rep_file), "sha256": sha(rep_file)}}]
    # another request in the model result: "no"
    other = json.loads(rep_file.read_text())
    other["models"][0]["first"]["req_id"] = "r-0001"
    (tmp_path / "other.json").write_text(json.dumps(other), encoding="utf-8")
    inc = check_claims(cands, [(log, tmp_path / "other.json")], normal=[], seeds=range(1), system=LIFT,
                       complete=FULL)["results"][0]["incidents"][0]
    assert inc["same_request"] == "no"
    # no model result: "not given", never "no"
    rep = check_claims(cands, [(log, None)], normal=[], seeds=range(1), system=LIFT, complete=FULL)
    inc = rep["results"][0]["incidents"][0]
    assert inc["same_request"] == "not given" and rep["incidents"][0]["model_result"] == "not given"


def test_a_model_that_conforms_is_said_so(tmp_path):
    log = dlog(tmp_path / "inc-device.log", UNMOVED[:9] + UNMOVED[11:])  # no repeat: the model conforms
    rep = check_claims(candidates(tmp_path, D1), [(log, model_result(tmp_path, log))], normal=[], seeds=range(1),
                       system=LIFT, complete=FULL)
    inc = rep["results"][0]["incidents"][0]
    assert inc["status"] == "ok" and inc["model_first_mismatch"] == "model conforms"
    assert inc["same_request"] == "not violated"


def test_not_judged_on_an_incident_is_not_a_catch(tmp_path):
    log = dlog(tmp_path / "inc-device.log", UNMOVED)
    rep = check_claims(candidates(tmp_path, C10), [(log, None)], normal=[], seeds=range(2), system=LIFT,
                       complete=["device:recv,send,state"])  # effect not declared: a stop could be missing
    (r,) = rep["results"]
    assert r["incidents"][0]["status"] == "not judged" and r["incidents"][0]["needs_complete"] == ["device effect"]
    assert r["verdict"] == "fails" and r["reasons"][0] == f"not caught on incident {log} (not judged)"


def test_an_invalid_device_log_is_not_judged(tmp_path):
    log = dlog(tmp_path / "inc-device.log", UNMOVED + ["3100 error watchdog"])
    rep = check_claims(candidates(tmp_path, C10), [(log, None)], normal=[], seeds=range(1), system=LIFT,
                       complete=FULL)
    inc = rep["results"][0]["incidents"][0]
    assert inc["status"] == "not judged" and inc["why_not_judged"] == "invalid log (an error line)"


# -- never_after: how often the normal corpus tried it ---------------------------------------------------


def test_never_after_reports_the_keys_that_were_tried(tmp_path):
    rep = check_claims(candidates(tmp_path, N1), [(sim_trace(tmp_path, 0, ["M1"]), None)], normal=[],
                       seeds=range(10), system=LIFT)
    (r,) = rep["results"]
    tried = r["normal"]["tried"]
    # keys with an after and anything later with the same key; the client's own receipt of the DONE counts
    assert tried["keys_with_after"] == tried["after_then_anything"] > 0
    # proposed, shown alongside: something later by the event's own actor (here: the device heard of it again)
    assert 0 < tried["after_then_event_actor"] < tried["after_then_anything"]
    assert tried["event_actor"] == "device" and r["verdict"] == "passes"
    assert tried["inputs_with_a_key_tried"] == r["normal"]["exercised"] == 10
    assert 0 < tried["inputs_with_a_key_tried_by_event_actor"] <= 10


def test_never_after_with_no_key_tried_is_untested_even_if_its_event_occurs(tmp_path):
    p = adapter_trace(tmp_path / "normal.jsonl", [(10, "ACK", "r-0001"), (20, "DONE", "r-0001")])
    inc = sim_trace(tmp_path, 0, ["M1"])
    rep = check_claims(candidates(tmp_path, N1), [(inc, None)], normal=[p], seeds=(), system=LIFT)
    (r,) = rep["results"]
    assert r["normal"]["statuses"] == {"ok": 1}  # the ACK occurred, so the status is ok...
    assert r["normal"]["tried"]["after_then_anything"] == 0  # ...but nothing came after the DONE
    assert r["verdict"] == "untested" and r["normal"]["exercised"] == 0


# -- inputs, output and the command line ------------------------------------------------------------------


def test_a_normal_directory_is_read_in_name_order_and_named_with_hashes(tmp_path):
    d = tmp_path / "normal"
    d.mkdir()
    sim_trace(d, 1, name="b.jsonl")
    dlog(d / "a-device.log", UNMOVED[:9] + UNMOVED[11:])
    (d / ".hidden").write_text("x")
    (d / "sub").mkdir()
    rep = check_claims(candidates(tmp_path, C10), [(sim_trace(tmp_path, 36, ["M10"]), None)], normal=[d],
                       seeds=(), system=LIFT, complete=FULL)
    files = rep["normal"]["files"]
    assert [(f["path"], f["kind"]) for f in files] == [(str(d / "a-device.log"), "device log"),
                                                       (str(d / "b.jsonl"), "trace")]
    listing = "".join(f"{f['sha256']}  {f['path']}\n" for f in files)
    assert rep["normal"]["files_sha256"] == hashlib.sha256(listing.encode()).hexdigest()
    assert rep["normal"]["seeds"] is None and rep["results"][0]["normal"]["inputs"] == 2


def test_cli_text_and_json_are_deterministic(tmp_path, capsys):
    cands = candidates(tmp_path, C10, D1, X1)
    log = dlog(tmp_path / "inc-device.log", UNMOVED)
    rep_file = model_result(tmp_path, log)
    argv = ["claim", "check", str(cands), "--incident", str(log), "--model", str(rep_file),
            "--incident", str(sim_trace(tmp_path, 36, ["M10"])), "--normal-seeds", "0-4", "--complete", FULL[0]]
    code1, out1, _ = out_of(capsys, argv + ["--out", str(tmp_path / "a.json")])
    code2, out2, _ = out_of(capsys, argv + ["--out", str(tmp_path / "b.json")])
    assert code1 == code2 == 1 and out1 == out2  # one candidate does not pass
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    assert "C10 (only_after): passes" in out1
    assert "D1 (count_le): fails: violated on 5 of 5 normal inputs" in out1
    assert "X1 (at_most_once): fails: not caught on incident" in out1
    assert f"model result: {rep_file} sha256 {sha(rep_file)}" in out1
    assert "model result: not given" in out1
    assert "same request as the model's first mismatch: yes" in out1
    rep = json.loads((tmp_path / "a.json").read_text())
    assert rep["candidates"] == {"path": str(cands), "sha256": sha(cands)}
    assert rep["normal"]["seeds"] == {"system": "lift.v0", "first": 0, "last": 4, "implementation": "correct"}


def test_cli_exit_zero_when_every_candidate_passes(tmp_path, capsys):
    code, out, _ = out_of(capsys, ["claim", "check", str(candidates(tmp_path, C10)), "--incident",
                                   str(sim_trace(tmp_path, 36, ["M10"])), "--normal-seeds", "0-2"])
    assert code == 0 and "C10 (only_after): passes" in out


@pytest.mark.parametrize("extra, edit, message", [
    ([], lambda c: {k: v for k, v in c.items() if k != "source"}, "C10: a candidate needs grade and source"),
    (["--model", "x.json"], None, "--model must follow an --incident"),
    (None, None, "give a normal corpus"),
])
def test_cli_rejects_bad_input(tmp_path, capsys, extra, edit, message):
    cands = candidates(tmp_path, edit(C10) if edit else C10)
    inc = str(sim_trace(tmp_path, 36, ["M10"]))
    if extra is None:
        argv = ["claim", "check", str(cands), "--incident", inc]
    else:
        argv = ["claim", "check", str(cands), *extra, "--incident", inc, "--normal-seeds", "0-1"]
    code, _, err = out_of(capsys, argv)
    assert code == 2 and message in err


def test_cli_rejects_candidates_for_another_system(tmp_path, capsys):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"protocol": "turntable.v0", "contracts": [C10]}), encoding="utf-8")
    code, _, err = out_of(capsys, ["claim", "check", str(p), "--incident", str(sim_trace(tmp_path, 36, ["M10"])),
                                   "--normal-seeds", "0-1"])
    assert code == 2 and "is for turntable.v0, not lift.v0" in err
