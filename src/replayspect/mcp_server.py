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
import json
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


BRIDGE_INSTRUCTIONS = {
    "full": (
        "replayspect runs an integration in a deterministic simulator and checks it against behavioural "
        "contracts. Call describe first: it includes a partial log of a recorded failing run and a symptom "
        "report. Submit fault plans with run_plan to reproduce that log, then answer which defect caused the "
        "failure. Every run_plan and check_cause call uses up one run of the budget, including rejected calls."
    ),
    "answer_only": (
        "replayspect runs an integration in a deterministic simulator and checks it against behavioural "
        "contracts. Call describe first: it includes a partial log of a recorded failing run, a symptom report "
        "and a fault plan that reproduces the log. Then answer which defect caused the failure."
    ),
    "symptom_only": (
        "replayspect runs an integration in a deterministic simulator and checks it against behavioural "
        "contracts. Call describe first: it includes a symptom report of a failing run. Then answer which "
        "defect caused the failure."
    ),
}


def build_bridge_server(session: BridgeSession):
    """Tools by mode: ``full`` adds run_plan and check_cause; the defect tool is name_defect when the
    system's defects are published (condition A), describe_defect otherwise (condition B)."""
    mode = session.config.mode
    server = _server_class()("replayspect", instructions=BRIDGE_INSTRUCTIONS[mode])

    @server.tool(meta={"anthropic/maxResultSizeChars": 200000})
    async def describe() -> dict[str, Any]:
        """The task and everything you get about the recorded failing run, the protocol and contracts
        (YAML), and what this session allows. Call this first."""
        return session.describe()

    if mode == "full":

        @server.tool()
        async def run_plan(plan: dict[str, Any] | str) -> dict[str, Any]:
            """Run the system once with the given fault plan (a JSON object, see plan_format in
            describe), in the same environment as the recorded run. Returns whether the run reproduces
            the log (lines matched and the first mismatch), the logged participant's side of your run,
            the contracts it violated, plan entries that had no effect, and the remaining budget. Uses one
            run."""
            return session.run_plan(plan)

        @server.tool()
        async def check_cause(run: int, entry: str) -> dict[str, Any]:
            """Name one entry of a reproducing run's plan as the trigger, e.g. entry="faults[0]",
            "delays[2]" or "disconnects[0]" (indexes into the plan as you submitted it). The run is
            repeated without that entry; confirmed means the failure went away. Uses one run."""
            return session.check_cause(run, entry)

    if session.question == "name":

        @server.tool()
        async def name_defect(defect_id: str) -> dict[str, Any]:
            """Answer which defect in the implementation caused the failure: one id from the defect list
            in describe. One answer; it ends the session. Does not use the budget."""
            return session.name_defect(defect_id)

    else:

        @server.tool()
        async def describe_defect(text: str) -> dict[str, Any]:
            """Answer what defect in the implementation caused the failure: a short description of the
            faulty behaviour. One answer; it ends the session. Does not use the budget."""
            return session.describe_defect(text)

    @server.tool()
    async def finish(note: str = "") -> dict[str, Any]:
        """End the session without an answer. Does not use the budget."""
        return session.finish(note)

    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m replayspect.mcp_server")
    ap.add_argument("--system", default="lift.v0")
    ap.add_argument("--mutant", action="append", default=[], help="hidden from the client; repeatable")
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--budget", type=int, default=None,
                    help="runs per session (default 100; with --incident 120, as registered for WP4)")
    ap.add_argument("--max-faults", type=int, default=20)
    ap.add_argument("--log", required=True, help="session log path; keep it outside the client's directory")
    ap.add_argument("--incident", metavar="FILE",
                    help="serve a bridge session for this incident file instead (hidden from the client; "
                         "--system, --mutant and --seed-base do not apply)")
    ap.add_argument("--mode", choices=["full", "answer-only", "symptom-only"], default="full",
                    help="with --incident: full (runs, then a defect answer), answer-only (a reproducing plan "
                         "is given; defect answer only) or symptom-only (no log; defect answer only)")
    ap.add_argument("--given-plan", metavar="FILE",
                    help="with --mode answer-only: JSON fault plan that reproduces the incident")
    args = ap.parse_args(argv)
    if args.incident:
        if args.mutant or args.seed_base or args.system != "lift.v0":
            ap.error("--incident takes its system, mutants or variant and seed from the incident file")
        mode = args.mode.replace("-", "_")
        if (mode == "answer_only") != bool(args.given_plan):
            ap.error("--given-plan goes with --mode answer-only, and only with it")
        given = json.loads(Path(args.given_plan).read_text(encoding="utf-8")) if args.given_plan else None
        budget = 120 if args.budget is None else args.budget
        bridge = BridgeSession(BridgeConfig(args.incident, budget, args.max_faults, mode, given), Path(args.log))
        build_bridge_server(bridge).run()  # stdio
        return 0
    if args.mode != "full" or args.given_plan:
        ap.error("--mode and --given-plan need --incident")
    budget = 100 if args.budget is None else args.budget
    config = SessionConfig(args.system, tuple(args.mutant), args.seed_base, budget, args.max_faults)
    session = Session(config, Path(args.log))
    build_server(session).run()  # stdio
    return 0


if __name__ == "__main__":
    sys.exit(main())
