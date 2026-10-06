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

import argparse
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
    repo = Path(tempfile.mkdtemp(prefix="frontend design loop smoke "))
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    (repo / "index.html").write_text("<!doctype html><title>Smoke</title><p>Hello</p>\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", "hello.txt", "index.html")
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


async def _run(*, preview: bool = False, installed: bool = False) -> None:
    repo = _make_tmp_repo()
    patch = "@@ -1,1 +1,1 @@\n-hello\n+hello world\n"
    repo_root = Path(__file__).resolve().parents[1]
    pythonpath = str(repo_root / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath = pythonpath + os.pathsep + existing_pythonpath

    env = dict(os.environ)
    if installed:
        # The installed console launcher and an external cwd exercise delivery.
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("FRONTEND_DESIGN_LOOP_CONFIG_PATH", None)
    else:
        env.update({
            "PYTHONPATH": pythonpath,
            "FRONTEND_DESIGN_LOOP_CONFIG_PATH": str(repo_root / "config" / "config.yaml"),
        })
    console = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin") / (
        "frontend-design-loop-mcp.exe" if os.name == "nt" else "frontend-design-loop-mcp"
    )
    server = StdioServerParameters(
        command=str(console) if installed else sys.executable,
        args=[] if installed else ["-m", "frontend_design_loop_mcp.mcp_server"],
        cwd=str(repo) if installed else str(repo_root),
        env=env,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = sorted([t.name for t in tools.tools])
            assert "frontend_design_loop_eval" in tool_names, tool_names

            preview_options = {}
            if preview:
                preview_options = {
                    "preview_command": [sys.executable, str(Path(__file__).with_name("preview_fixture.py")), "{port}", "--bind", "127.0.0.1"],
                    "preview_url": "http://127.0.0.1:{port}/index.html",
                    "vision_mode": "on",
                    "viewports": [
                        {"label": "mobile", "width": 390, "height": 844},
                        {"label": "desktop", "width": 1440, "height": 900},
                    ],
                }
            res = await session.call_tool(
                "frontend_design_loop_eval",
                {
                    "repo_path": str(repo),
                    "patches": [{"path": "hello.txt", "patch": patch}],
                    "test_command": "git diff --check",
                    # Default vision_provider=client returns screenshots for Claude to judge.
                    "vision_mode": "auto",
                    "include_images": True,
                    "include_vision_instructions": True,
                    **preview_options,
                },
            )

            assert not res.isError, res
            summary = _extract_json_from_contents(res.content)
            assert summary["deterministic_passed"] is True, summary
            assert summary["vision_pending"] is True, summary
            assert summary["vision_scored"] is False, summary
            assert summary["final_pass"] is None, summary
            assert summary["passes_all_gates"] is False, summary

            img_count = sum(1 for c in res.content if isinstance(c, ImageContent))
            expected_images = 2 if preview else 1
            assert img_count >= expected_images, f"expected >={expected_images} ImageContent, got {img_count}"
            if preview:
                assert summary["vision_kind"] == "ui", summary

            print("OK: frontend_design_loop_eval")
            print("  run_dir:", summary.get("run_dir"))
            print("  vision_kind:", summary.get("vision_kind"))
            print("  deterministic_passed:", summary.get("deterministic_passed"))
            print("  vision_pending:", summary.get("vision_pending"))
            print("  images:", img_count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="Capture a real page at mobile and desktop widths")
    parser.add_argument("--installed", action="store_true", help="Resolve the installed package outside the source checkout")
    args = parser.parse_args()

    async def run():
        with anyio.fail_after(90):
            await _run(preview=args.preview, installed=args.installed)

    anyio.run(run)


if __name__ == "__main__":
    main()
