"""MCP server for planning sessions: ``python3 -m replayspect.mcp_server``.

Exposes one :class:`~replayspect.session.Session` to an MCP client (for
example Claude Code) over stdio, with two tools:

* ``describe``: protocol, contracts, plan format, limits and budget
* ``run_plan``: run one fault plan and get the timeline, violations and
  entries that had no effect

The session enforces seed assignment, budget, bounds and logging. Mutants
are given on the command line by the operator and omitted from tool
results; the operator must isolate that configuration from the planner.

Requires the optional dependency ``mcp`` (``pip install -e ".[mcp]"``);
both the 1.x (``FastMCP``) and 2.x (``MCPServer``) SDK lines work.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from replayspect.session import Session, SessionConfig

INSTRUCTIONS = (
    "replayspect runs a robot-to-lift integration in a deterministic simulator and checks it "
    "against behavioural contracts. Call describe first. Then submit fault plans with run_plan "
    "and use each run's timeline to choose the next plan. Every run_plan call uses up one run "
    "of the budget, including rejected plans."
)


def _server_class():
    try:
        from mcp.server.mcpserver import MCPServer  # mcp 2.x

        return MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # mcp 1.x

        return FastMCP


def build_server(session: Session):
    server = _server_class()("replayspect", instructions=INSTRUCTIONS)

    # SDK 2 dispatches synchronous tools to worker threads. These wrappers
    # deliberately do not await inside a session operation: its budget, seed
    # assignment and log append run together on the server's event loop.
    @server.tool()
    async def describe() -> dict[str, Any]:
        """Describe the system under test: protocol, contracts (YAML), fault plan format,
        allowed value ranges and the remaining run budget. Call this first."""
        return session.describe()

    @server.tool()
    async def run_plan(plan: dict[str, Any] | str) -> dict[str, Any]:
        """Run the system once with the given fault plan (a JSON object, see plan_format in
        describe). Returns the run's timeline, the contracts it violated with details, plan
        entries that had no effect, and the remaining budget. Each call uses one run of the
        budget, even if the plan is rejected."""
        return session.run_plan(plan)

    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m replayspect.mcp_server")
    ap.add_argument("--system", default="lift.v0")
    ap.add_argument("--mutant", action="append", default=[], help="hidden from the client; repeatable")
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--budget", type=int, default=100)
    ap.add_argument("--max-faults", type=int, default=20)
    ap.add_argument("--log", required=True, help="session log path; keep it outside the client's directory")
    args = ap.parse_args(argv)
    config = SessionConfig(args.system, tuple(args.mutant), args.seed_base, args.budget, args.max_faults)
    session = Session(config, Path(args.log))
    build_server(session).run()  # stdio
    return 0


if __name__ == "__main__":
    sys.exit(main())
