"""MCP server for planning sessions: ``python3 -m replayspect.mcp_server``.

Exposes one :class:`~replayspect.session.Session` to an MCP client (for
example Claude Code) over stdio, with two tools:

* ``describe``: protocol, contracts, plan format, limits and budget
* ``run_plan``: run one fault plan and get the timeline, violations and
  entries that had no effect

The session enforces seed assignment, budget, bounds and logging. Mutants
are given on the command line by the operator and omitted from tool
results; the operator must isolate that configuration from the planner.

With ``--incident FILE`` it serves a bridge session instead
(:mod:`replayspect.bridge`): ``describe`` adds a partial log of a hidden
failing run, ``run_plan`` also reports whether the run reproduces it, and
two more tools exist:

* ``check_cause``: rerun a reproducing run's plan without one entry
* ``finish``: end the session

Requires the optional dependency ``mcp`` (``pip install -e ".[mcp]"``);
both the 1.x (``FastMCP``) and 2.x (``MCPServer``) SDK lines work.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from replayspect.bridge import BridgeConfig, BridgeSession
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


BRIDGE_INSTRUCTIONS = (
    "replayspect runs an integration in a deterministic simulator and checks it against behavioural "
    "contracts. Call describe first: it includes a partial log of a recorded failing run. Submit fault "
    "plans with run_plan to reproduce that log, then name the cause with check_cause. Every run_plan and "
    "check_cause call uses up one run of the budget, including rejected calls."
)


def build_bridge_server(session: BridgeSession):
    server = _server_class()("replayspect", instructions=BRIDGE_INSTRUCTIONS)

    @server.tool()
    async def describe() -> dict[str, Any]:
        """The task, the partial log of the recorded failing run, the protocol, contracts (YAML),
        fault plan format, allowed value ranges and the remaining budget. Call this first."""
        return session.describe()

    @server.tool()
    async def run_plan(plan: dict[str, Any] | str) -> dict[str, Any]:
        """Run the system once with the given fault plan (a JSON object, see plan_format in
        describe), in the same environment as the recorded run. Returns whether the run reproduces
        the log (lines matched and the first mismatch), the run's timeline, the contracts it
        violated, plan entries that had no effect, and the remaining budget. Uses one run."""
        return session.run_plan(plan)

    @server.tool()
    async def check_cause(run: int, entry: str) -> dict[str, Any]:
        """Name one entry of a reproducing run's plan as the cause, e.g. entry="faults[0]",
        "delays[2]" or "disconnects[0]" (indexes into the plan as you submitted it). The run is
        repeated without that entry; confirmed means the failure went away. A confirmed cause ends
        the session. Uses one run."""
        return session.check_cause(run, entry)

    @server.tool()
    async def finish(note: str = "") -> dict[str, Any]:
        """End the session without naming a confirmed cause. Does not use the budget."""
        return session.finish(note)

    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m replayspect.mcp_server")
    ap.add_argument("--system", default="lift.v0")
    ap.add_argument("--mutant", action="append", default=[], help="hidden from the client; repeatable")
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--budget", type=int, default=100)
    ap.add_argument("--max-faults", type=int, default=20)
    ap.add_argument("--log", required=True, help="session log path; keep it outside the client's directory")
    ap.add_argument("--incident", metavar="FILE",
                    help="serve a bridge session for this incident file instead (hidden from the client; "
                         "--system, --mutant and --seed-base do not apply)")
    args = ap.parse_args(argv)
    if args.incident:
        if args.mutant or args.seed_base or args.system != "lift.v0":
            ap.error("--incident takes its system, mutants or variant and seed from the incident file")
        bridge = BridgeSession(BridgeConfig(args.incident, args.budget, args.max_faults), Path(args.log))
        build_bridge_server(bridge).run()  # stdio
        return 0
    config = SessionConfig(args.system, tuple(args.mutant), args.seed_base, args.budget, args.max_faults)
    session = Session(config, Path(args.log))
    build_server(session).run()  # stdio
    return 0


if __name__ == "__main__":
    sys.exit(main())
