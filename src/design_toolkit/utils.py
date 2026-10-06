"""Shared utilities for the design toolkit MCP."""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any


async def run_command(
    cmd: str,
    *,
    cwd: Path | str | None = None,
    timeout_ms: int = 120_000,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Compatibility wrapper over shared bounded shell execution."""
    from frontend_design_loop_core.utils import run_command as shared_run

    if env is not None:
        raise ValueError("Use run_command_argv for explicit environments")
    return await shared_run(cmd, cwd=cwd, timeout_ms=timeout_ms)


def shlex_quote(s: str) -> str:
    """Cross-platform shlex.quote."""
    return shlex.quote(str(s))


_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)```",
    re.DOTALL,
)


def extract_json(text: str) -> Any:
    """Extract JSON from text - handles markdown fences, bare JSON, and wrappers."""
    raw = str(text or "").strip()
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    for open_ch, close_ch in [("{", "}"), ("[", "]")]:
        start = raw.find(open_ch)
        if start == -1:
            continue
        end = raw.rfind(close_ch)
        if end <= start:
            continue
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            continue

    return None


def tail(text: str, max_chars: int = 4000) -> str:
    """Return the last max_chars characters of text."""
    if len(text) <= max_chars:
        return text
    return "..." + text[-max_chars:]


def write_text(path: Path, content: str) -> None:
    """Write text to a file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_text(path: Path, *, max_chars: int = 100_000) -> str:
    """Read a file's text content with a size cap."""
    if not path.exists() or not path.is_file():
        return ""
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            return stream.read(max(0, max_chars))
    except Exception:
        return ""


def merge_unique(items: list[str]) -> list[str]:
    """Deduplicate a list while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def log(msg: str) -> None:
    """Log to stderr because MCP stdio needs clean stdout."""
    print(f"[design-toolkit] {msg}", file=sys.stderr, flush=True)
