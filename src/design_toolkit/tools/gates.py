"""run_gates - run test and lint commands, return pass/fail plus output."""

from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from design_toolkit.utils import run_command, tail

_SHELL_ONLY_TOKENS = {"&&", "||", ";", "|", "&", ">", ">>", "<", "<<", "2>", "1>", "2>>", "1>>"}
_SHELL_EXECUTABLES = {"sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh"}
_INLINE_CODE_EXECUTABLES = {
    "python",
    "python3",
    "python3.10",
    "python3.11",
    "python3.12",
    "python3.13",
    "python3.14",
    "node",
    "deno",
    "ruby",
    "perl",
    "php",
    "pwsh",
    "powershell",
    "osascript",
}
_INLINE_CODE_FLAGS = {"-c", "-e", "-E", "--eval", "-command", "--command", "/c", "-lc"}


def _token_requires_shell(token: str) -> bool:
    if token in _SHELL_ONLY_TOKENS:
        return True
    if any(op in token for op in ("&&", "||", ";", "|", "&", ">", "<")):
        return True
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*", token))


@dataclass
class PreparedCommand:
    raw: str
    argv: list[str] | None
    shell_mode: bool = False


def prepare_command(
    raw: str | None,
    *,
    label: str = "command",
    unsafe_shell: bool = False,
) -> PreparedCommand | None:
    """Parse a command string into a PreparedCommand."""
    raw_str = str(raw or "").strip()
    if not raw_str:
        return None

    tokens = shlex.split(raw_str)
    if not tokens:
        return None

    needs_shell = any(_token_requires_shell(token) for token in tokens)

    if len(tokens) >= 2 and tokens[0].lower() in _INLINE_CODE_EXECUTABLES:
        if any(token in _INLINE_CODE_FLAGS for token in tokens[1:]):
            if not unsafe_shell:
                raise ValueError(
                    f"{label}: inline code execution detected in {tokens[0]}. "
                    "Set unsafe_shell=true to allow."
                )
            needs_shell = True

    if tokens and tokens[0].lower() in _SHELL_EXECUTABLES:
        if not unsafe_shell:
            raise ValueError(
                f"{label}: direct shell execution detected ({tokens[0]}). "
                "Set unsafe_shell=true to allow."
            )
        needs_shell = True

    if needs_shell and not unsafe_shell:
        raise ValueError(f"{label}: shell operators detected. Set unsafe_shell=true to allow.")

    return PreparedCommand(
        raw=raw_str,
        argv=None if needs_shell else tokens,
        shell_mode=needs_shell,
    )


async def run_prepared_command(
    cmd: PreparedCommand | None,
    *,
    cwd: Path,
    timeout_ms: int = 120_000,
) -> tuple[int, str, str]:
    """Run a PreparedCommand and return (return_code, stdout, stderr)."""
    if cmd is None:
        return 0, "", ""

    if cmd.shell_mode or cmd.argv is None:
        return await run_command(cmd.raw, cwd=cwd, timeout_ms=timeout_ms)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_ms / 1000.0,
        )
        return (
            proc.returncode or 0,
            (stdout_bytes or b"").decode("utf-8", errors="replace"),
            (stderr_bytes or b"").decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return -1, "", f"Command timed out after {timeout_ms}ms"
    except Exception as exc:
        return -1, "", str(exc)


@dataclass
class GateResult:
    test_ok: bool
    test_rc: int
    test_stdout: str
    test_stderr: str
    lint_ok: bool
    lint_rc: int
    lint_stdout: str
    lint_stderr: str


async def run_gates(
    *,
    repo_root: Path,
    test_command: str | None = None,
    lint_command: str | None = None,
    timeout_ms: int = 120_000,
    unsafe_shell: bool = False,
) -> GateResult:
    """Run test and lint commands, return structured results."""
    test_cmd = prepare_command(test_command, label="test_command", unsafe_shell=unsafe_shell)
    lint_cmd = prepare_command(lint_command, label="lint_command", unsafe_shell=unsafe_shell)

    test_rc, test_out, test_err = await run_prepared_command(
        test_cmd,
        cwd=repo_root,
        timeout_ms=timeout_ms,
    )
    lint_rc, lint_out, lint_err = await run_prepared_command(
        lint_cmd,
        cwd=repo_root,
        timeout_ms=timeout_ms,
    )

    return GateResult(
        test_ok=test_rc == 0,
        test_rc=test_rc,
        test_stdout=tail(test_out),
        test_stderr=tail(test_err),
        lint_ok=lint_rc == 0,
        lint_rc=lint_rc,
        lint_stdout=tail(lint_out),
        lint_stderr=tail(lint_err),
    )


async def infer_test_command(repo_root: Path) -> str | None:
    """Try to auto-detect the test command for a repo."""
    pkg_json = repo_root / "package.json"
    if pkg_json.exists():
        import json

        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                return "npm test"
        except Exception:
            pass

    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        return "python -m pytest"

    makefile = repo_root / "Makefile"
    if makefile.exists():
        text = makefile.read_text(encoding="utf-8", errors="replace")
        if "test:" in text:
            return "make test"

    return None
