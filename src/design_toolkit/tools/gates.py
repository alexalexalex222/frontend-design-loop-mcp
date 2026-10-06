"""Explicit command gates using the shared process runtime."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from design_toolkit.utils import tail
from frontend_design_loop_core.command_runtime import (
    display_argv,
    parse_command_line,
    validate_argv,
)
from frontend_design_loop_core.utils import run_command, run_command_argv


@dataclass
class PreparedCommand:
    raw: str
    argv: list[str] | None
    shell_mode: bool = False


def prepare_command(
    raw: str | list[str] | None, *, label: str = "command", unsafe_shell: bool = False
) -> PreparedCommand | None:
    if raw is None or raw == "" or raw == []:
        return None
    if isinstance(raw, list):
        validate_argv(raw)
        return PreparedCommand(display_argv(raw, windows=os.name == "nt"), list(raw))
    if not isinstance(raw, str):
        raise ValueError(f"{label}: command must be a string or argv array")
    if unsafe_shell:
        return PreparedCommand(raw, None, True)
    tokens = parse_command_line(raw, windows=os.name == "nt")
    if not tokens:
        return None
    if any(
        any(op in item for op in ("&&", "||", ";", "|", ">", "<", "`", "$(")) for item in tokens
    ):
        raise ValueError(f"{label}: use argv or explicitly set unsafe_shell=true for shell syntax")
    return PreparedCommand(raw, tokens)


async def run_prepared_command(
    cmd: PreparedCommand | None, *, cwd: Path, timeout_ms: int = 120_000
) -> tuple[int | None, str, str]:
    if cmd is None:
        return None, "", ""
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    if cmd.shell_mode:
        return await run_command(cmd.raw, cwd=cwd, timeout_ms=timeout_ms)
    return await run_command_argv(cmd.argv, cwd=cwd, timeout_ms=timeout_ms)


@dataclass
class GateResult:
    test_ok: bool | None
    test_rc: int | None
    test_stdout: str
    test_stderr: str
    lint_ok: bool | None
    lint_rc: int | None
    lint_stdout: str
    lint_stderr: str
    test_status: str
    lint_status: str

    def to_dict(self) -> dict:
        result = asdict(self)
        result["test_return_code"] = result.pop("test_rc")
        result["lint_return_code"] = result.pop("lint_rc")
        return result


def _status(rc: int | None) -> str:
    return "skipped" if rc is None else "error" if rc == -1 else "passed" if rc == 0 else "failed"


async def run_gates(
    *,
    repo_root: Path,
    test_command: str | list[str] | None = None,
    lint_command: str | list[str] | None = None,
    timeout_ms: int = 120_000,
    unsafe_shell: bool = False,
) -> GateResult:
    test = prepare_command(test_command, label="test_command", unsafe_shell=unsafe_shell)
    lint = prepare_command(lint_command, label="lint_command", unsafe_shell=unsafe_shell)
    trc, tout, terr = await run_prepared_command(test, cwd=repo_root, timeout_ms=timeout_ms)
    lrc, lout, lerr = await run_prepared_command(lint, cwd=repo_root, timeout_ms=timeout_ms)
    return GateResult(
        None if trc is None or trc == -1 else trc == 0,
        trc,
        tail(tout),
        tail(terr),
        None if lrc is None or lrc == -1 else lrc == 0,
        lrc,
        tail(lout),
        tail(lerr),
        _status(trc),
        _status(lrc),
    )


async def infer_test_command(repo_root: Path) -> str | None:
    """Only infer an explicit package test script; project type is not a test suite."""
    try:
        pkg = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
        if pkg.get("scripts", {}).get("test"):
            return "npm test"
    except (OSError, ValueError, AttributeError):
        pass
    return None
