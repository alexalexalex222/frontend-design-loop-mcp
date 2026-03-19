"""MCP server for the Frontend Design Toolkit.

This server is intentionally narrow:
- It exposes playbooks that teach the agent how to work.
- It exposes mechanical helpers the agent can call directly.

It does NOT hide another evaluator, planner, or patch-writer behind MCP.
The agent owns:
- planning
- subagent delegation
- code edits
- screenshot review
- scoring
- iteration
- final selection

The MCP only provides sharp tools plus instruction resources.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from design_toolkit.tools import (
    context as ctx_mod,
    gates as gates_mod,
    preview as preview_mod,
    screenshots as screens_mod,
)

mcp = FastMCP("frontend-design-toolkit")

_PLAYBOOKS_DIR = Path(__file__).parent / "playbooks"

_PLAYBOOK_NAMES = {
    "solve": "Master agent-owned design workflow",
    "megamind": "Multi-perspective planning via agent subagents",
    "candidates": "Parallel candidate generation with agent-owned edits",
    "vision_gate": "Agent-owned screenshot review and iteration loop",
    "creativity": "Agent-owned section creativity review and refinement",
    "winner_selection": "Scoring and selecting the best candidate",
}


@mcp.resource("playbook://solve")
def resource_solve() -> str:
    return (_PLAYBOOKS_DIR / "solve.md").read_text(encoding="utf-8")


@mcp.resource("playbook://megamind")
def resource_megamind() -> str:
    return (_PLAYBOOKS_DIR / "megamind.md").read_text(encoding="utf-8")


@mcp.resource("playbook://candidates")
def resource_candidates() -> str:
    return (_PLAYBOOKS_DIR / "candidates.md").read_text(encoding="utf-8")


@mcp.resource("playbook://vision_gate")
def resource_vision_gate() -> str:
    return (_PLAYBOOKS_DIR / "vision_gate.md").read_text(encoding="utf-8")


@mcp.resource("playbook://creativity")
def resource_creativity() -> str:
    return (_PLAYBOOKS_DIR / "creativity.md").read_text(encoding="utf-8")


@mcp.resource("playbook://winner_selection")
def resource_winner_selection() -> str:
    return (_PLAYBOOKS_DIR / "winner_selection.md").read_text(encoding="utf-8")


@mcp.tool()
async def get_playbook(name: str) -> dict[str, Any]:
    """Read a strategy playbook.

    These playbooks define the workflow. They are the core product here.
    """
    normalized = str(name or "").strip().lower().replace("-", "_")
    if normalized not in _PLAYBOOK_NAMES:
        return {
            "error": f"Unknown playbook: {normalized}",
            "available": list(_PLAYBOOK_NAMES.keys()),
        }

    path = _PLAYBOOKS_DIR / f"{normalized}.md"
    if not path.exists():
        return {"error": f"Playbook file missing: {normalized}.md"}

    return {
        "name": normalized,
        "description": _PLAYBOOK_NAMES[normalized],
        "content": path.read_text(encoding="utf-8"),
    }


@mcp.tool()
async def run_gates(
    repo_path: str,
    *,
    test_command: str | None = None,
    lint_command: str | None = None,
    timeout_ms: int = 120_000,
    unsafe_shell: bool = False,
    auto_detect_test: bool = True,
) -> dict[str, Any]:
    """Run test and lint commands and return pass/fail plus tailed output."""
    repo_root = Path(repo_path).resolve()
    if not repo_root.exists():
        return {"error": f"Repo path does not exist: {repo_path}"}

    if test_command is None and auto_detect_test:
        test_command = await gates_mod.infer_test_command(repo_root)

    result = await gates_mod.run_gates(
        repo_root=repo_root,
        test_command=test_command,
        lint_command=lint_command,
        timeout_ms=timeout_ms,
        unsafe_shell=unsafe_shell,
    )

    return {
        "test_ok": result.test_ok,
        "test_return_code": result.test_rc,
        "test_stdout": result.test_stdout,
        "test_stderr": result.test_stderr,
        "lint_ok": result.lint_ok,
        "lint_return_code": result.lint_rc,
        "lint_stdout": result.lint_stdout,
        "lint_stderr": result.lint_stderr,
    }


@mcp.tool()
async def capture_screenshots(
    url: str,
    *,
    out_dir: str | None = None,
    viewports: list[dict[str, Any]] | None = None,
    timeout_ms: int = 30_000,
    full_page: bool = True,
) -> dict[str, Any]:
    """Capture screenshots for the agent to inspect directly."""
    if out_dir:
        out_path = Path(out_dir)
    else:
        out_path = Path(
            os.getenv("DESIGN_TOOLKIT_OUT_DIR", "/tmp/design-toolkit-screenshots")
        ) / uuid.uuid4().hex[:8]

    screenshots = await screens_mod.capture_screenshots(
        url=url,
        out_dir=out_path,
        viewports=viewports,
        timeout_ms=timeout_ms,
        full_page=full_page,
    )

    return {"screenshots": screenshots, "out_dir": str(out_path)}


@mcp.tool()
async def preview_start(
    command: str,
    cwd: str,
    *,
    port: int | None = None,
    wait_timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Start a preview server and wait until it responds."""
    return await preview_mod.preview_start(
        command=command,
        cwd=Path(cwd),
        port=port,
        wait_timeout_s=wait_timeout_s,
    )


@mcp.tool()
async def preview_stop(pid: int | None = None) -> dict[str, Any]:
    """Stop a preview server by PID, or stop all managed previews."""
    return await preview_mod.preview_stop(pid=pid)


@mcp.tool()
async def build_context(
    repo_path: str,
    *,
    files: list[str] | None = None,
    auto_context_mode: Literal["off", "goal", "queries"] = "off",
    auto_context_queries: list[str] | None = None,
    goal: str | None = None,
    max_file_chars: int = 12_000,
    max_total_chars: int = 150_000,
    max_auto_files: int = 20,
) -> dict[str, Any]:
    """Build a redacted context blob from repository files."""
    repo_root = Path(repo_path).resolve()
    if not repo_root.exists():
        return {
            "error": f"Repo path does not exist: {repo_path}",
            "context_blob": "",
            "files_included": [],
        }

    context_files = list(files or [])

    if auto_context_mode != "off":
        queries: list[str] = []
        if auto_context_mode == "goal" and goal:
            queries = ctx_mod.derive_auto_context_queries(goal)
        elif auto_context_mode == "queries" and auto_context_queries:
            queries = auto_context_queries

        if queries:
            auto_files = await ctx_mod.auto_context_files(
                repo_root=repo_root,
                queries=queries,
                max_files=max_auto_files,
            )
            context_files.extend(auto_files)

    from design_toolkit.utils import merge_unique

    context_files = merge_unique(context_files)
    blob = ctx_mod.build_context_blob(
        repo_root=repo_root,
        context_files=context_files,
        max_file_chars=max_file_chars,
        max_total_chars=max_total_chars,
    )

    return {
        "context_blob": blob,
        "files_included": context_files,
    }


def main() -> None:
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
