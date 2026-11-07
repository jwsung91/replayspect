"""Work-mode tools: search, shrink and replay for a developer, kept apart from planning sessions."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from replayspect.mcp_work import Workspace
from replayspect.runner import read_repro
from test_session import REASONED

SRC = Path(__file__).parent.parent / "src"


def ws(tmp_path, **kw):
    return Workspace(tmp_path / "repros", **kw)


# -- search ------------------------------------------------------------------------------------


def test_search_reports_hits_and_writes_the_smallest_repro(tmp_path):
    w = ws(tmp_path)
    r = w.search(mutants=["M1"], seeds=5, target="C8", candidates=2)
    assert r["status"] == "ok" and r["runs"] == 5
    assert r["hits"]["C8"] == {"runs": 5, "first_seed": 0}
    rep = r["repro"]
    assert rep["name"] == "lift.v0-M1-C8-seed0.json" and rep["faults_after"] <= rep["faults_before"]
    assert rep["simulations"] >= 5
    doc = read_repro(w.root / rep["name"])
    assert doc["mutants"] == ["M1"] and doc["target"] == "C8"
    assert rep["violation"]["contract"] == "C8"


def test_search_without_target_writes_nothing(tmp_path):
    w = ws(tmp_path)
    r = w.search(mutants=["M1"], seeds=3)
    assert r["status"] == "ok" and r["repro"] is None and "C8" in r["hits"]
    assert not w.root.exists() or not any(w.root.iterdir())


def test_search_target_not_violated(tmp_path):
    r = ws(tmp_path).search(seeds=3, target="C3")
    assert r["status"] == "ok" and r["hits"] == {} and r["repro"] is None
    assert "not violated" in r["note"]


@pytest.mark.parametrize("kw, match", [
    ({"mutants": ["M99"]}, "unknown mutants"),
    ({"target": "C99"}, "unknown contract"),
    ({"seeds": 0}, "seeds"),
    ({"seeds": 10_001}, "seeds"),
    ({"candidates": 0, "target": "C8"}, "candidates"),
])
def test_search_rejects_bad_arguments(tmp_path, kw, match):
    r = ws(tmp_path).search(**kw)
    assert r["status"] == "error" and match in r["error"]


# -- shrink ------------------------------------------------------------------------------------


def test_shrink_an_explicit_plan(tmp_path):
    w = ws(tmp_path)
    r = w.shrink(seed=0, target="C3", mutants=["M4"], plan=REASONED)
    assert r["status"] == "ok"
    rep = r["repro"]
    assert rep["faults_before"] == 3 and rep["faults_after"] <= 3
    doc = read_repro(w.root / rep["name"])
    assert doc["seed"] == 0 and doc["plan"]["base"] == "random" and doc["target"] == "C3"


def test_shrink_a_plan_given_as_json_text(tmp_path):
    r = ws(tmp_path).shrink(seed=0, target="C3", mutants=["M4"], plan=json.dumps(REASONED))
    assert r["status"] == "ok"


def test_shrink_a_random_run_when_no_plan_is_given(tmp_path):
    w = ws(tmp_path)
    r = w.shrink(seed=0, target="C8", mutants=["M1"])
    assert r["status"] == "ok" and r["repro"]["faults_before"] > 0
    assert w.replay(r["repro"]["name"])["ok"] is True


@pytest.mark.parametrize("kw, match", [
    ({"seed": 2, "target": "C3", "mutants": ["M4"], "plan": REASONED}, "does not violate C3"),
    ({"seed": 0, "target": "C3", "plan": REASONED}, "does not violate C3"),
    ({"seed": 0, "target": "C3", "mutants": ["M4"], "plan": {"base": "random", "oops": 1}}, "oops"),
    ({"seed": 0, "target": "C3", "mutants": ["M4"], "plan": "{not json"}, "not valid JSON"),
    ({"seed": 0, "target": "C3", "mutants": ["M4"],
      "plan": {"base": "random", "disconnects": [{"t_us": 1_000_000, "duration_us": 60_000_000}]}},
     "outside the allowed range"),
    ({"seed": 0, "target": "C99"}, "unknown contract"),
    ({"seed": 0, "target": "C8", "mutants": ["M99"]}, "unknown mutants"),
])
def test_shrink_rejects_bad_input(tmp_path, kw, match):
    r = ws(tmp_path).shrink(**kw)
    assert r["status"] == "error" and match in r["error"]


def test_repro_names_never_overwrite(tmp_path):
    w = ws(tmp_path)
    a = w.shrink(seed=0, target="C3", mutants=["M4"], plan=REASONED)["repro"]["name"]
    b = w.shrink(seed=0, target="C3", mutants=["M4"], plan=REASONED)["repro"]["name"]
    assert a == "lift.v0-M4-C3-seed0.json" and b == "lift.v0-M4-C3-seed0-2.json"
    assert {p.name for p in w.root.iterdir()} == {a, b}


# -- replay ------------------------------------------------------------------------------------


def test_replay_a_written_repro(tmp_path):
    w = ws(tmp_path)
    name = w.search(mutants=["M1"], seeds=2, target="C8", candidates=1)["repro"]["name"]
    r = w.replay(name)
    assert r == {**r, "status": "ok", "ok": True, "digest_ok": True, "violations_ok": True,
                 "target_ok": True, "target": "C8", "mutants": ["M1"]}


def test_replay_reports_a_changed_execution(tmp_path):
    w = ws(tmp_path)
    name = w.search(mutants=["M1"], seeds=2, target="C8", candidates=1)["repro"]["name"]
    path = w.root / name
    doc = json.loads(path.read_text())
    doc["expect"]["digest"] = "0" * 64
    path.write_text(json.dumps(doc))
    r = w.replay(name)
    assert r["status"] == "ok" and r["ok"] is False and r["digest_ok"] is False


@pytest.mark.parametrize("name, match", [
    ("../x.json", "plain file name"),
    ("sub/x.json", "plain file name"),
    ("/etc/passwd", "plain file name"),
    ("x.txt", ".json"),
    ("missing.json", "no repro"),
])
def test_replay_stays_inside_the_repro_directory(tmp_path, name, match):
    w = ws(tmp_path)
    w.root.mkdir(parents=True)
    r = w.replay(name)
    assert r["status"] == "error" and match in r["error"]


def test_replay_rejects_a_file_that_is_not_a_repro(tmp_path):
    w = ws(tmp_path)
    w.root.mkdir(parents=True)
    (w.root / "x.json").write_text('{"format": "something else"}')
    r = w.replay("x.json")
    assert r["status"] == "error" and "not a" in r["error"]


# -- over MCP ----------------------------------------------------------------------------------


async def _work_calls(root):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "replayspect.mcp_work", "--repros", str(root)],
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            out = {"tools": sorted(t.name for t in (await s.list_tools()).tools)}
            for name, args in [
                ("search", {"mutants": ["M1"], "seeds": 2, "target": "C8", "candidates": 1}),
                ("shrink", {"seed": 0, "target": "C3", "mutants": ["M4"], "plan": REASONED}),
                ("replay", {"name": "lift.v0-M1-C8-seed0.json"}),
            ]:
                res = await s.call_tool(name, args)
                data = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
                if data is None:
                    data = json.loads(res.content[0].text)
                out[name] = data
            return out


def test_work_server_end_to_end(tmp_path):
    pytest.importorskip("mcp")
    out = asyncio.run(_work_calls(tmp_path / "repros"))
    assert out["tools"] == ["replay", "search", "shrink"]
    assert out["search"]["repro"]["name"] == "lift.v0-M1-C8-seed0.json"
    assert out["shrink"]["status"] == "ok"
    assert out["replay"]["ok"] is True
