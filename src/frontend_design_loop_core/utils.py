"""Utility functions for TITAN Factory."""

import asyncio
import hashlib
import json
import os
import re
import signal
import socket
import sys
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

_RUN_LOG_PATH: Path | None = None
_RUN_LOG_LOCK = threading.Lock()

_JSON_ESCAPE_MAP = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def set_run_log_file(path: Path | None, *, append: bool = True) -> None:
    """Enable/disable writing plain-text logs to a run-local file (e.g. out/<run>/run.log).

    This keeps rich console output for humans while also persisting a stable log file
    that the HTML portal can fetch and display.

    Args:
        path: Log file path, or None to disable.
        append: If False, truncate/overwrite the file.
    """
    global _RUN_LOG_PATH
    _RUN_LOG_PATH = path
    if _RUN_LOG_PATH is None:
        return

    try:
        _RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not append:
            _RUN_LOG_PATH.write_text("", encoding="utf-8")
    except Exception:
        # Logging must never crash the pipeline.
        _RUN_LOG_PATH = None


def _write_run_log(level: str, msg: str) -> None:
    """Best-effort append of a single line to the run log file."""
    if _RUN_LOG_PATH is None:
        return

    try:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{ts} {level} {msg}\n"
        with _RUN_LOG_LOCK:
            with open(_RUN_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        # Never crash pipeline due to log IO.
        return


def generate_task_id(niche_id: str, page_type: str, seed: int) -> str:
    """Generate a deterministic task ID.

    Args:
        niche_id: The niche identifier
        page_type: The page type
        seed: Random seed

    Returns:
        Stable hash-based ID
    """
    content = f"{niche_id}:{page_type}:{seed}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def generate_candidate_id(
    task_id: str,
    model: str,
    variant: int,
    prompt_id: str | None = None,
    *,
    generator_key: str | None = None,
) -> str:
    """Generate a candidate ID.

    Args:
        task_id: Parent task ID
        model: Generator model name
        variant: Variant index
        prompt_id: Optional prompt variant identifier
        generator_key: Optional generator instance key (e.g. temperature bucket) to
            avoid ID collisions when the same model appears multiple times in config.

    Returns:
        Candidate ID
    """
    parts: list[str] = [task_id, model]
    if generator_key:
        parts.append(generator_key)
    if prompt_id:
        parts.append(prompt_id)
    parts.append(str(variant))
    content = ":".join(parts)
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def hash_prompt(messages: list[dict], params: dict) -> str:
    """Hash prompt for caching.

    Args:
        messages: Chat messages
        params: Model parameters

    Returns:
        Hash string
    """
    content = json.dumps({"messages": messages, "params": params}, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


def extract_json(text: str | None) -> dict[str, Any] | None:
    """Safely extract JSON from model response.

    Tries multiple strategies:
    1. Strip thinking blocks (<think>...</think>)
    2. Parse full string as JSON
    3. Look for ```json code blocks (tries ALL blocks, not just first)
    4. Find first { and last } and parse

    Args:
        text: Raw model response (can be None)

    Returns:
        Parsed JSON dict or None if extraction fails
    """
    if not text:
        return None

    # Strip BOM and whitespace
    text = text.lstrip("\ufeff").strip()

    # Strategy 0: Strip <think>...</think> blocks (thinking models like Kimi K2)
    # These models output reasoning before JSON
    think_pattern = re.compile(r"<think>[\s\S]*?</think>\s*", re.IGNORECASE)
    text = think_pattern.sub("", text).strip()

    # Also handle unclosed <think> blocks (truncated responses)
    # Remove everything from <think> to the first { if think block wasn't closed
    if "<think>" in text.lower() and "</think>" not in text.lower():
        first_brace = text.find("{")
        if first_brace != -1:
            text = text[first_brace:]

    def _sanitize_json_fragment(fragment: str) -> str:
        """Fix common model JSON issues deterministically.

        Models sometimes emit invalid JSON by inserting raw newlines/tabs inside
        quoted string literals, e.g.:

          {"notes":"line 1
          line 2"}

        JSON strings cannot contain raw control characters, so json.loads fails.
        This sanitizer replaces raw control chars *inside strings* with spaces.
        """
        out: list[str] = []
        in_str = False
        escaped = False

        for ch in fragment:
            if escaped:
                out.append(ch)
                escaped = False
                continue

            if ch == "\\":
                out.append(ch)
                escaped = True
                continue

            if ch == '"':
                out.append(ch)
                in_str = not in_str
                continue

            if in_str and ch in ("\n", "\r", "\t"):
                out.append(" ")
                continue

            out.append(ch)

        return "".join(out)

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(_sanitize_json_fragment(text))
        except json.JSONDecodeError:
            pass

    # Strategy 2: Try ALL code blocks, not just the first (Fix B from GPT-5.2 Pro)
    # Some models emit multiple fenced blocks - we want the first one that parses
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE):
        block = match.group(1).strip()
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            try:
                return json.loads(_sanitize_json_fragment(block))
            except json.JSONDecodeError:
                continue

    # Strategy 3: Find first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            fragment = text[first_brace : last_brace + 1]
            try:
                return json.loads(fragment)
            except json.JSONDecodeError:
                return json.loads(_sanitize_json_fragment(fragment))
        except json.JSONDecodeError:
            pass

    # Strategy 4: Try to find array
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")

    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        try:
            fragment = text[first_bracket : last_bracket + 1]
            try:
                return json.loads(fragment)
            except json.JSONDecodeError:
                return json.loads(_sanitize_json_fragment(fragment))
        except json.JSONDecodeError:
            pass

    # Strategy 5: Salvage loosely-formed patch bundle payloads.
    patch_bundle = _extract_patch_bundle_loose(text)
    if patch_bundle is not None:
        return patch_bundle

    return None


def _skip_ws(text: str, idx: int) -> int:
    while idx < len(text) and text[idx] in " \t\r\n":
        idx += 1
    return idx


def _consume_loose_string(text: str, idx: int) -> tuple[str, int] | None:
    if idx >= len(text) or text[idx] != '"':
        return None

    out: list[str] = []
    i = idx + 1
    while i < len(text):
        ch = text[i]
        if ch == '"':
            return "".join(out), i + 1
        if ch == "\\":
            if i + 1 >= len(text):
                out.append("\\")
                return "".join(out), i + 1
            nxt = text[i + 1]
            if nxt == "u" and i + 5 < len(text):
                hex_fragment = text[i + 2 : i + 6]
                if re.fullmatch(r"[0-9A-Fa-f]{4}", hex_fragment):
                    out.append(chr(int(hex_fragment, 16)))
                    i += 6
                    continue
            mapped = _JSON_ESCAPE_MAP.get(nxt)
            if mapped is not None:
                out.append(mapped)
            else:
                # Preserve malformed escapes literally instead of rejecting the whole payload.
                out.append("\\")
                out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return None


def _skip_jsonish_value(text: str, idx: int) -> int | None:
    i = _skip_ws(text, idx)
    if i >= len(text):
        return None

    ch = text[i]
    if ch == '"':
        parsed = _consume_loose_string(text, i)
        return parsed[1] if parsed is not None else None

    if ch in "[{":
        stack = [ch]
        in_str = False
        escaped = False
        i += 1
        while i < len(text):
            cur = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif cur == "\\":
                    escaped = True
                elif cur == '"':
                    in_str = False
                i += 1
                continue
            if cur == '"':
                in_str = True
                i += 1
                continue
            if cur in "[{":
                stack.append(cur)
                i += 1
                continue
            if cur in "]}":
                if not stack:
                    return None
                opener = stack.pop()
                if (opener, cur) not in {("{", "}"), ("[", "]")}:
                    return None
                i += 1
                if not stack:
                    return i
                continue
            i += 1
        return None

    while i < len(text) and text[i] not in ",]}":
        i += 1
    return i


def _parse_loose_string_array(text: str, idx: int) -> tuple[list[str], int] | None:
    i = _skip_ws(text, idx)
    if i >= len(text) or text[i] != "[":
        return None
    i += 1
    items: list[str] = []
    while i < len(text):
        i = _skip_ws(text, i)
        if i >= len(text):
            return None
        if text[i] == "]":
            return items, i + 1
        if text[i] == ",":
            i += 1
            continue
        parsed = _consume_loose_string(text, i)
        if parsed is None:
            next_i = _skip_jsonish_value(text, i)
            if next_i is None:
                return None
            i = next_i
            continue
        value, i = parsed
        items.append(value)
    return None


def _parse_loose_patch_item(text: str, idx: int) -> tuple[dict[str, str], int] | None:
    i = _skip_ws(text, idx)
    if i >= len(text) or text[i] != "{":
        return None
    i += 1

    patch_item: dict[str, str] = {}
    while i < len(text):
        i = _skip_ws(text, i)
        if i >= len(text):
            return None
        if text[i] == "}":
            return patch_item, i + 1
        if text[i] == ",":
            i += 1
            continue
        parsed_key = _consume_loose_string(text, i)
        if parsed_key is None:
            return None
        key, i = parsed_key
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] != ":":
            return None
        i = _skip_ws(text, i + 1)

        if key in {"path", "patch"}:
            parsed_val = _consume_loose_string(text, i)
            if parsed_val is None:
                return None
            value, i = parsed_val
            patch_item[key] = value
            continue

        next_i = _skip_jsonish_value(text, i)
        if next_i is None:
            return None
        i = next_i

    return None


def _parse_loose_patch_array(text: str, idx: int) -> tuple[list[dict[str, str]], int] | None:
    i = _skip_ws(text, idx)
    if i >= len(text) or text[i] != "[":
        return None
    i += 1

    patches: list[dict[str, str]] = []
    while i < len(text):
        i = _skip_ws(text, i)
        if i >= len(text):
            return None
        if text[i] == "]":
            return patches, i + 1
        if text[i] == ",":
            i += 1
            continue
        parsed_item = _parse_loose_patch_item(text, i)
        if parsed_item is None:
            return None
        item, i = parsed_item
        if item.get("path") and item.get("patch") is not None:
            patches.append({"path": item["path"], "patch": item["patch"]})

    return None


def _parse_loose_patch_bundle_object(text: str, idx: int) -> tuple[dict[str, Any], int] | None:
    i = _skip_ws(text, idx)
    if i >= len(text) or text[i] != "{":
        return None
    i += 1

    data: dict[str, Any] = {}
    while i < len(text):
        i = _skip_ws(text, i)
        if i >= len(text):
            return None
        if text[i] == "}":
            return data, i + 1
        if text[i] == ",":
            i += 1
            continue
        parsed_key = _consume_loose_string(text, i)
        if parsed_key is None:
            return None
        key, i = parsed_key
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] != ":":
            return None
        i = _skip_ws(text, i + 1)

        if key == "patches":
            parsed_patches = _parse_loose_patch_array(text, i)
            if parsed_patches is None:
                return None
            data["patches"], i = parsed_patches
            continue
        if key == "notes":
            parsed_notes = _parse_loose_string_array(text, i)
            if parsed_notes is None:
                next_i = _skip_jsonish_value(text, i)
                if next_i is None:
                    return None
                i = next_i
                continue
            data["notes"], i = parsed_notes
            continue

        next_i = _skip_jsonish_value(text, i)
        if next_i is None:
            return None
        i = next_i

    return None


def _extract_patch_bundle_loose(text: str) -> dict[str, Any] | None:
    if '"patches"' not in text:
        return None

    starts = [match.start() for match in re.finditer(r'"patches"\s*:', text)]
    for patches_pos in starts:
        start = text.rfind("{", 0, patches_pos)
        while start != -1:
            parsed = _parse_loose_patch_bundle_object(text, start)
            if parsed is not None:
                data, end_idx = parsed
                if end_idx > patches_pos and isinstance(data.get("patches"), list) and data["patches"]:
                    return data
            start = text.rfind("{", 0, start)
    return None


def extract_json_strict(text: str | None) -> dict[str, Any]:
    """Extract JSON, raising on failure.

    Args:
        text: Raw model response (can be None)

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If JSON extraction fails
    """
    result = extract_json(text)
    if result is None:
        # Fix A from GPT-5.2 Pro: Handle None safely instead of crashing on text[:500]
        preview = "<None>" if text is None else text[:500]
        raise ValueError(f"Failed to extract JSON from response: {preview}...")
    return result


def find_available_port(start: int = 3000, max_attempts: int = 100) -> int:
    """Find an available port.

    Args:
        start: Starting port number
        max_attempts: Maximum ports to try

    Returns:
        Available port number

    Raises:
        RuntimeError: If no port found
    """
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {start}-{start + max_attempts}")


async def run_command(
    cmd: str,
    cwd: Path | str | None = None,
    timeout_ms: int = 120000,
    capture_output: bool = True,
) -> tuple[int, str, str]:
    """Run a shell command asynchronously.

    Args:
        cmd: Command to run
        cwd: Working directory
        timeout_ms: Timeout in milliseconds
        capture_output: Whether to capture stdout/stderr

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    timeout_s = timeout_ms / 1000

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE if capture_output else None,
            stderr=asyncio.subprocess.PIPE if capture_output else None,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            return (
                proc.returncode or 0,
                stdout.decode() if stdout else "",
                stderr.decode() if stderr else "",
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return -1, "", f"Command timed out after {timeout_s}s"

    except Exception as e:
        return -1, "", str(e)


async def run_command_argv(
    args: list[str],
    cwd: Path | str | None = None,
    timeout_ms: int = 120000,
    capture_output: bool = True,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a command without invoking a shell."""
    if not args:
        return -1, "", "No command provided"

    timeout_s = timeout_ms / 1000

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE if capture_output else None,
            stderr=asyncio.subprocess.PIPE if capture_output else None,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            return (
                proc.returncode or 0,
                stdout.decode() if stdout else "",
                stderr.decode() if stderr else "",
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return -1, "", f"Command timed out after {timeout_s}s"

    except Exception as e:
        return -1, "", str(e)


@asynccontextmanager
async def managed_process(
    cmd: str,
    cwd: Path | str | None = None,
) -> AsyncGenerator[asyncio.subprocess.Process, None]:
    """Context manager for a long-running process.

    Ensures process AND all child processes are killed on exit.
    Uses process groups to ensure child processes (like next-server spawned by npm)
    are properly terminated.

    Args:
        cmd: Command to run
        cwd: Working directory

    Yields:
        The running process
    """
    # Start process in its own process group so we can kill all children
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # Creates new process group
    )

    try:
        yield proc
    finally:
        if proc.returncode is None:
            try:
                # Kill entire process group (process + all children)
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                await asyncio.sleep(0.5)  # Give time for graceful shutdown
                # Force kill if still running
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # Already dead
            except (ProcessLookupError, PermissionError):
                # Process already dead or no permission
                pass
            await proc.wait()


@asynccontextmanager
async def managed_process_argv(
    args: list[str],
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> AsyncGenerator[asyncio.subprocess.Process, None]:
    """Context manager for a long-running argv-based process."""
    if not args:
        raise ValueError("No command provided")

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    try:
        yield proc
    finally:
        if proc.returncode is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                await asyncio.sleep(0.5)
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            except (ProcessLookupError, PermissionError):
                pass
            await proc.wait()


def truncate_text(text: str, max_length: int = 1000) -> str:
    """Truncate text to max length.

    Args:
        text: Text to truncate
        max_length: Maximum length

    Returns:
        Truncated text with ellipsis if needed
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def estimate_tokens(text: str) -> int:
    """Rough token count estimate.

    Args:
        text: Text to estimate

    Returns:
        Approximate token count (chars / 4)
    """
    return len(text) // 4


def format_build_error(stdout: str, stderr: str, max_lines: int = 50) -> str:
    """Format build error output for model consumption.

    Args:
        stdout: Build stdout
        stderr: Build stderr
        max_lines: Max lines to include

    Returns:
        Formatted error string
    """
    lines = []

    if stderr:
        lines.append("=== STDERR ===")
        lines.extend(stderr.strip().split("\n")[:max_lines])

    if stdout:
        lines.append("=== STDOUT ===")
        lines.extend(stdout.strip().split("\n")[:max_lines])

    return "\n".join(lines)


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists.

    Args:
        path: Directory path

    Returns:
        The path
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_info(msg: str) -> None:
    """Log info message."""
    console.print(f"[blue]INFO[/blue] {msg}")
    _write_run_log("INFO", msg)


def log_success(msg: str) -> None:
    """Log success message."""
    console.print(f"[green]OK[/green] {msg}")
    _write_run_log("OK", msg)


def log_warning(msg: str) -> None:
    """Log warning message."""
    console.print(f"[yellow]WARN[/yellow] {msg}")
    _write_run_log("WARN", msg)


def log_error(msg: str) -> None:
    """Log error message."""
    console.print(f"[red]ERROR[/red] {msg}")
    _write_run_log("ERROR", msg)


def ensure_console_to_stderr() -> None:
    """Force Rich console output to stderr.

    MCP stdio servers must keep stdout clean (JSON-RPC only). Some runtime helpers
    log via Rich; this helper ensures those logs do not corrupt stdio transport.
    """
    try:
        console.file = sys.stderr
    except Exception:
        # Never crash due to logging reconfiguration.
        return
