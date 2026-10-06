"""MCP server for the Frontend Design Toolkit.

The host agent owns planning and edits. Mechanical tools provide previews,
gates and labeled screenshot evidence. review_design explicitly invokes a
separately selected native CLI judge; no model call is hidden in capture or gates.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

from design_toolkit.tools import (
    context as ctx_mod,
)
from design_toolkit.tools import (
    gates as gates_mod,
)
from design_toolkit.tools import (
    preview as preview_mod,
)
from design_toolkit.tools import (
    screenshots as screens_mod,
)


@asynccontextmanager
async def _lifespan(server: FastMCP):
    try:
        yield {}
    finally:
        import anyio

        with anyio.CancelScope(shield=True):
            await preview_mod.preview_stop()


mcp = FastMCP("frontend-design-toolkit", lifespan=_lifespan)

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
    test_command: str | list[str] | None = None,
    lint_command: str | list[str] | None = None,
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

    return result.to_dict()


@mcp.tool()
async def review_design(
    manifest_path: str,
    goal: str,
    provider: Literal["codex_cli", "claude_cli", "opencode_cli"],
    model: str,
    effort: str = "high",
    baseline_manifest_path: str | None = None,
    threshold: float = 8.0,
    auth_mode: Literal["subscription", "configured"] = "subscription",
) -> dict[str, Any]:
    """Explicit independent design review through your logged-in native CLI.

    Verifies screenshot hashes, supplies labeled candidate/baseline pixels, and
    returns honest assessment plus requested/observed execution metadata. The
    native judge runs in a temporary workspace with editing/execution disabled.
    This call invokes the selected model; capture_screenshots alone does not.
    """
    from design_toolkit.tools.review import review_evidence

    return await review_evidence(
        manifest_path=Path(manifest_path),
        goal=goal,
        provider_name=provider,
        model=model,
        effort=effort,
        threshold=threshold,
        baseline_path=Path(baseline_manifest_path) if baseline_manifest_path else None,
        auth_mode=auth_mode,
    )


@mcp.tool()
async def capture_screenshots(
    url: str,
    *,
    out_dir: str | None = None,
    viewports: list[dict[str, Any]] | None = None,
    timeout_ms: int = 30_000,
    full_page: bool = True,
    interactions: list[dict[str, Any]] | None = None,
    evidence_label: str = "candidate",
    source_revision: str | None = None,
    include_images: bool = True,
    asset_policy: Literal["same_origin", "public_assets"] = "public_assets",
) -> CallToolResult:
    """Capture a local page; return labeled MCP images and a durable evidence manifest.

    Interactions support click/fill/press/expect_visible/expect_text with selector
    and optional value. Each viewport starts fresh. This is focused QA, not a
    complete accessibility or design-quality verdict. No judge/model is invoked.
    """
    out_path = (
        Path(out_dir)
        if out_dir
        else Path(
            os.getenv(
                "DESIGN_TOOLKIT_OUT_DIR",
                str(Path(tempfile.gettempdir()) / "design-toolkit-screenshots"),
            )
        )
    )
    manifest = await screens_mod.capture_evidence(
        url=url,
        out_dir=out_path,
        viewports=viewports,
        timeout_ms=timeout_ms,
        full_page=full_page,
        interactions=interactions,
        evidence_label=evidence_label,
        source_revision=source_revision,
        asset_policy=asset_policy,
    )
    content: list[TextContent | ImageContent] = []
    total = 0
    for shot in manifest["screenshots"]:
        if not include_images:
            break
        data = Path(shot["path"]).read_bytes()
        total += len(data)
        if total > 15_000_000:
            content.append(
                TextContent(
                    type="text",
                    text="Image return budget exceeded; remaining images are in the manifest paths.",
                )
            )
            break
        content.append(
            TextContent(
                type="text",
                text=f"{evidence_label}: {shot['label']} / {shot['state']} (sha256 {shot['sha256']})",
            )
        )
        content.append(
            ImageContent(
                type="image", data=base64.b64encode(data).decode("ascii"), mimeType="image/png"
            )
        )
    content.insert(0, TextContent(type="text", text=json.dumps(manifest)))
    return CallToolResult(
        content=content, structuredContent=manifest, isError=manifest["status"] == "error"
    )


@mcp.tool()
async def preview_start(
    command: str | list[str],
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


def main(argv: list[str] | None = None) -> None:
    """Run the MCP server via stdio transport."""
    parser = argparse.ArgumentParser(prog="frontend-design-toolkit-mcp")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        from frontend_design_loop_mcp import __version__

        print(__version__)
        return
    from frontend_design_loop_core.lifecycle import run_stdio_server

    run_stdio_server(mcp)


if __name__ == "__main__":
    main()
