from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
EXPECTED_TOOLS = {
    "get_playbook",
    "build_context",
    "run_gates",
    "preview_start",
    "capture_screenshots",
    "preview_stop",
}
EXPECTED_RESOURCES = {
    "playbook://solve",
    "playbook://megamind",
    "playbook://candidates",
    "playbook://vision_gate",
    "playbook://creativity",
    "playbook://winner_selection",
}
REMOVED_TOOLS = {"apply_patch", "vision_score", "creativity_eval"}


async def _fetch_contract() -> tuple[set[str], set[str]]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "design_toolkit.server"],
        env=env,
        cwd=str(REPO_ROOT),
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            resources = await session.list_resources()

    tool_names = {tool.name for tool in tools.tools}
    resource_uris = {str(resource.uri) for resource in resources.resources}
    return tool_names, resource_uris


def test_stdio_contract_matches_agent_owned_surface() -> None:
    tool_names, resource_uris = anyio.run(_fetch_contract)

    assert tool_names == EXPECTED_TOOLS
    assert resource_uris == EXPECTED_RESOURCES
    assert tool_names.isdisjoint(REMOVED_TOOLS)
