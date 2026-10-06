"""Installed-distribution stdio smoke; no provider or model invocation."""

from __future__ import annotations

import json
import sys
import tempfile

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="design-toolkit-smoke-") as directory:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "design_toolkit.server"], cwd=directory
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                required = {
                    "get_playbook",
                    "build_context",
                    "run_gates",
                    "preview_start",
                    "capture_screenshots",
                    "preview_stop",
                }
                assert required <= tools, f"Missing tools: {required - tools}"
                playbook = await session.call_tool("get_playbook", {"name": "solve"})
                assert not playbook.isError
                gates = await session.call_tool(
                    "run_gates", {"repo_path": directory, "auto_detect_test": False}
                )
                assert not gates.isError
                result = gates.structuredContent
                if result is None:
                    result = json.loads(
                        next(item.text for item in gates.content if item.type == "text")
                    )
                assert result["test_status"] == "skipped" and result["test_ok"] is None
                stopped = await session.call_tool("preview_stop", {"pid": 2147483647})
                assert not stopped.isError
        print(
            "PASS toolkit installed stdio, playbook, skipped gates, unowned-PID rejection; live inference not_run"
        )


def main() -> None:
    anyio.run(smoke)


if __name__ == "__main__":
    main()
