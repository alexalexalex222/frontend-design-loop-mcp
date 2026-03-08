#!/usr/bin/env python3
"""Offline preflight for Frontend Design Loop MCP.

This intentionally validates the public Frontend Design Loop MCP product surface.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    if detail:
        print(f"       {detail}")
    return ok


def main() -> None:
    ok = True

    from frontend_design_loop_core.config import load_config
    from frontend_design_loop_mcp.runtime_paths import (
        get_default_config_path,
        get_default_out_dir,
        get_default_prompts_path,
        get_default_template_path,
    )
    from frontend_design_loop_mcp.setup import _check_playwright_ready

    cfg = None
    try:
        cfg = load_config()
        ok &= check("config loads", True, str(get_default_config_path()))
    except Exception as exc:
        ok &= check("config loads", False, str(exc))

    ok &= check("prompt path exists", get_default_prompts_path().exists(), str(get_default_prompts_path()))
    ok &= check("template path exists", get_default_template_path().exists(), str(get_default_template_path()))
    ok &= check("default out dir resolved", bool(get_default_out_dir()), str(get_default_out_dir()))

    ready, detail = _check_playwright_ready()
    ok &= check("playwright chromium ready", ready, detail)

    native_bins = {
        "codex": shutil.which("codex"),
        "gemini": shutil.which("gemini"),
        "kilo": shutil.which("kilo"),
        "droid": shutil.which("droid"),
        "opencode": shutil.which("opencode"),
        "claude": shutil.which("claude"),
    }
    for name, path in native_bins.items():
        check(f"native cli visible: {name}", bool(path), path or "not on PATH")

    if cfg is not None:
        check(
            "default MCP tooling mode is agent-first",
            True,
            "Use frontend_design_loop_eval with vision_provider=client for interactive sessions.",
        )

    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
