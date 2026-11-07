"""End-to-end: the MCP server over stdio, driven by the MCP SDK's own client."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SRC = Path(__file__).parent.parent / "src"


def _attr(obj, *names):
    for n in names:
        if getattr(obj, n, None) is not None:
            return getattr(obj, n)
    return None


async def _session_calls(log):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "replayspect.mcp_server", "--mutant", "M5", "--budget", "2", "--log", str(log)],
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            out = {"tools": tools}
            for name, args in [("describe", {}), ("run_plan", {"plan": {"base": "random"}}),
                               ("run_plan", {"plan": '{"base": "fixed"}'}), ("run_plan", {"plan": {"base": "random"}})]:
                res = await s.call_tool(name, args)
                data = _attr(res, "structured_content", "structuredContent")
                if data is None:  # older SDKs: JSON text content
                    data = json.loads(res.content[0].text)
                out.setdefault(name, []).append(data)
            return out


def test_mcp_server_end_to_end(tmp_path):
    out = asyncio.run(_session_calls(tmp_path / "log.jsonl"))
    assert out["tools"] == ["describe", "run_plan"]
    (d,) = out["describe"]
    assert d["system"] == "lift.v0" and "M5" not in json.dumps(d)
    ok, rejected, exhausted = out["run_plan"]
    assert ok["status"] == "ok" and ok["violations"][0]["contract"] == "C5"
    assert rejected["status"] == "rejected" and rejected["budget"]["left"] == 0
    assert exhausted["status"] == "budget_exhausted"
    lines = (tmp_path / "log.jsonl").read_text().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["config"]["mutants"] == ["M5"]


def test_session_tools_stay_on_the_event_loop(tmp_path, monkeypatch):
    from replayspect.mcp_server import build_server
    from replayspect.session import Session, SessionConfig

    async def check():
        session = Session(SessionConfig(budget=2), tmp_path / "log.jsonl")
        loop = asyncio.get_running_loop()
        original = session.run_plan
        calls = []

        def checked(plan):
            # SDK 2 sends synchronous tools to workers. Session mutations must
            # stay serialized on the server loop, including the log append.
            assert asyncio.get_running_loop() is loop
            calls.append(plan)
            return original(plan)

        monkeypatch.setattr(session, "run_plan", checked)
        server = build_server(session)
        await asyncio.gather(*(
            server.call_tool("run_plan", {"plan": {"base": "random"}})
            for _ in range(2)
        ))
        assert len(calls) == 2 and session.used == 2

    asyncio.run(check())
