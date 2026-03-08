"""Smoke test for Frontend Design Loop MCP over stdio (no Claude required).

This verifies:
- server starts (stdio)
- list_tools works
- frontend_design_loop_eval runs on a tiny temp git repo
- tool returns a JSON summary with deterministic pass + pending client vision
- tool returns at least one screenshot ImageContent

Run:
  .venv/bin/python scripts/smoke_mcp_stdio.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import ImageContent, TextContent


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _make_tmp_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="frontend-design-loop-mcp-smoke-"))
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return repo


def _extract_json_from_contents(contents) -> dict:
    for c in contents:
        if isinstance(c, TextContent):
            try:
                data = json.loads(c.text)
            except Exception:
                continue
            if isinstance(data, dict) and "run_id" in data and "passes_all_gates" in data:
                return data
    raise RuntimeError("No JSON summary found in tool result contents.")


async def _run() -> None:
    repo = _make_tmp_repo()
    patch = "@@ -1,1 +1,1 @@\n-hello\n+hello world\n"
    repo_root = Path(__file__).resolve().parents[1]
    pythonpath = str(repo_root / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath = pythonpath + os.pathsep + existing_pythonpath

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "frontend_design_loop_mcp.mcp_server"],
        cwd=str(repo_root),
        env={
            **os.environ,
            "PYTHONPATH": pythonpath,
            "FRONTEND_DESIGN_LOOP_CONFIG_PATH": str(repo_root / "config" / "config.yaml"),
        },
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = sorted([t.name for t in tools.tools])
            assert "frontend_design_loop_eval" in tool_names, tool_names

            res = await session.call_tool(
                "frontend_design_loop_eval",
                {
                    "repo_path": str(repo),
                    "patches": [{"path": "hello.txt", "patch": patch}],
                    "test_command": "true",
                    # Default vision_provider=client returns screenshots for Claude to judge.
                    "vision_mode": "auto",
                    "include_images": True,
                    "include_vision_instructions": True,
                },
            )

            summary = _extract_json_from_contents(res.content)
            assert summary["deterministic_passed"] is True, summary
            assert summary["vision_pending"] is True, summary
            assert summary["vision_scored"] is False, summary
            assert summary["final_pass"] is None, summary
            assert summary["passes_all_gates"] is False, summary

            img_count = sum(1 for c in res.content if isinstance(c, ImageContent))
            assert img_count >= 1, f"expected >=1 ImageContent, got {img_count}"

            print("OK: frontend_design_loop_eval")
            print("  run_dir:", summary.get("run_dir"))
            print("  vision_kind:", summary.get("vision_kind"))
            print("  deterministic_passed:", summary.get("deterministic_passed"))
            print("  vision_pending:", summary.get("vision_pending"))
            print("  images:", img_count)


def main() -> None:
    anyio.run(_run)


if __name__ == "__main__":
    main()
