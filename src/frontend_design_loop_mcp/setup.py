"""Frontend Design Loop MCP setup helper.

This exists to make public packaged installs feel product-like:
users can run a single command to install the required Playwright browser
binaries and wire the MCP into supported coding clients.

Why this is needed:
- Installing the Python dependency `playwright` is not enough.
- The Chromium browser binaries are downloaded separately via `playwright install chromium`.
- Most users do not want to hand-edit five different MCP config formats.

This helper runs those steps inside the *current* Python environment, so it
works correctly inside pipx-managed virtualenvs and repo-local `.venv` installs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

from pathlib import Path

from frontend_design_loop_core.command_runtime import prepare_process_argv
from frontend_design_loop_mcp.runtime_paths import (
    get_default_config_path,
    get_default_prompts_path,
    get_default_template_path,
    is_repo_checkout,
    repo_root,
)

_WORKFLOW = "toolkit"


def _check_playwright_ready() -> tuple[bool, str]:
    """Return whether Playwright Chromium is ready in the current environment."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - import failure is enough
        return (
            False,
            f"Playwright import failed: {exc}. Run 'frontend-design-loop-setup' after installation.",
        )

    try:
        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
            if executable.exists():
                browser = playwright.chromium.launch(headless=True, timeout=10000)
                try:
                    page = browser.new_page()
                    page.set_content("<!doctype html><title>Setup check</title>")
                    if page.title() != "Setup check":
                        raise RuntimeError("Chromium did not complete its readiness check")
                finally:
                    browser.close()
    except Exception as exc:  # pragma: no cover - defensive check
        return (
            False,
            f"Playwright Chromium check failed: {exc}. Run 'frontend-design-loop-setup'.",
        )

    if executable.exists():
        return (True, f"Playwright Chromium launched successfully at {executable}")

    return (
        False,
        f"Playwright Chromium is not installed for this environment (expected {executable}). "
        "Run 'frontend-design-loop-setup'.",
    )


def _doctor_check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    if detail:
        print(f"       {detail}")
    return ok


def _build_claude_payload() -> dict[str, object]:
    # Bind the launcher to this environment; GUI clients often have a different PATH.
    module = (
        "design_toolkit.server" if _WORKFLOW == "toolkit" else "frontend_design_loop_mcp.mcp_server"
    )
    payload: dict[str, object] = {"command": sys.executable, "args": ["-m", module]}
    if _WORKFLOW == "automated" and is_repo_checkout():
        payload["env"] = {"FRONTEND_DESIGN_LOOP_CONFIG_PATH": str(get_default_config_path())}
    return payload


def _atomic_config_write(path: Path, text: str, *, toml: bool = False) -> None:
    """Validate before replacing; leave the existing file intact on failure."""
    if toml:
        tomllib.loads(text)
    else:
        json.loads(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".new", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _claude_add_json_command(scope: str, server_name: str) -> list[str]:
    payload = json.dumps(_build_claude_payload(), separators=(",", ":"))
    return ["claude", "mcp", "add-json", "--scope", scope, server_name, payload]


def _default_codex_config_path() -> Path:
    return Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"


def _default_gemini_settings_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def _default_droid_mcp_path() -> Path:
    return Path.home() / ".factory" / "mcp.json"


def _default_opencode_config_path() -> Path:
    return Path.home() / ".config" / "opencode" / "opencode.json"


def _strip_jsonc_comments(text: str) -> str:
    out: list[str] = []
    in_string = False
    string_quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if line_comment:
            if ch in "\r\n":
                line_comment = False
                out.append(ch)
            i += 1
            continue

        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == string_quote:
                in_string = False
            i += 1
            continue

        if ch in ('"', "'"):
            in_string = True
            string_quote = ch
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue

        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _strip_jsonc_trailing_commas(text: str) -> str:
    out: list[str] = []
    in_string = False
    string_quote = ""
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == string_quote:
                in_string = False
            i += 1
            continue

        if ch in ('"', "'"):
            in_string = True
            string_quote = ch
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j < len(text) and text[j] in "}]":
                i += 1
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def _read_json_object(path: Path, *, jsonc: bool = False) -> dict[str, object]:
    if not path.exists():
        return {}

    raw = path.read_text(encoding="utf-8")
    if jsonc:
        raw = _strip_jsonc_trailing_commas(_strip_jsonc_comments(raw))
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise SystemExit(f"Config at {path} is not a JSON object.")
    return parsed


def _merge_entry(existing: object, updated: dict[str, object]) -> dict[str, object]:
    merged = {**(existing if isinstance(existing, dict) else {}), **updated}
    for key in ("env", "environment"):
        prior = existing.get(key) if isinstance(existing, dict) else None
        addition = updated.get(key)
        if isinstance(prior, dict) and isinstance(addition, dict):
            merged[key] = {**prior, **addition}
    return merged


def _payload_command_argv() -> list[str]:
    payload = _build_claude_payload()
    return [str(payload["command"]), *(str(arg) for arg in payload["args"])]


def _payload_env() -> dict[str, str]:
    payload = _build_claude_payload()
    env = payload.get("env") or {}
    return {str(key): str(value) for key, value in env.items()}


def _looks_like_managed_stdio_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    args = entry.get("args")
    expected = _payload_command_argv()
    return (
        isinstance(command, str)
        and command == expected[0]
        and isinstance(args, list)
        and [str(arg) for arg in args] == expected[1:]
    )


def _looks_like_managed_opencode_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    expected = _payload_command_argv()
    return isinstance(command, list) and [str(arg) for arg in command] == expected


def _detect_install_targets(*, skip_clients: set[str] | None = None) -> list[str]:
    skip = skip_clients or set()
    targets: list[str] = []
    if "claude" not in skip and shutil.which("claude"):
        targets.append("claude")
    if "codex" not in skip and (shutil.which("codex") or _default_codex_config_path().exists()):
        targets.append("codex")
    if "gemini" not in skip and (
        shutil.which("gemini") or _default_gemini_settings_path().exists()
    ):
        targets.append("gemini")
    if "droid" not in skip and (shutil.which("droid") or _default_droid_mcp_path().exists()):
        targets.append("droid")
    if "opencode" not in skip and (
        shutil.which("opencode") or _default_opencode_config_path().exists()
    ):
        targets.append("opencode")
    return targets


def _build_codex_config_block(server_name: str) -> str:
    payload = _build_claude_payload()
    key = json.dumps(server_name, ensure_ascii=False)
    table = f"mcp_servers.{key}"
    lines = [
        f"# BEGIN frontend-design-loop-mcp managed block: {server_name}",
        f"[{table}]",
        "command = " + json.dumps(payload["command"], ensure_ascii=False),
        "args = " + json.dumps(payload["args"], ensure_ascii=False),
        "enabled = true",
        "startup_timeout_sec = 30",
        "tool_timeout_sec = 900",
    ]
    env = payload.get("env") or {}
    if env:
        lines.extend(["", f"[{table}.env]"])
        for key, value in env.items():
            lines.append(json.dumps(key) + " = " + json.dumps(value, ensure_ascii=False))
    lines.append(f"# END frontend-design-loop-mcp managed block: {server_name}")
    block = "\n".join(lines) + "\n"
    tomllib.loads(block)
    return block


def _replace_or_append_managed_block(text: str, *, server_name: str, block: str) -> str:
    header = f"# BEGIN frontend-design-loop-mcp managed block: {server_name}"
    footer = f"# END frontend-design-loop-mcp managed block: {server_name}"
    if header in text and footer in text:
        pattern = re.compile(
            rf"{re.escape(header)}[\s\S]*?{re.escape(footer)}\n?",
            re.MULTILINE,
        )
        return pattern.sub(lambda _: block, text, count=1)

    parsed = tomllib.loads(text)
    if server_name in parsed.get("mcp_servers", {}):
        raise SystemExit(
            f"Codex config already has an unmanaged MCP entry {server_name!r}. "
            "Use --server-name to choose a different name."
        )

    suffix = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + suffix + block


def _print_codex_config(server_name: str) -> None:
    print(_build_codex_config_block(server_name))
    print(f"Write this block into {_default_codex_config_path()}")


def _install_codex_config(server_name: str, config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    updated = _replace_or_append_managed_block(
        existing,
        server_name=server_name,
        block=_build_codex_config_block(server_name),
    )
    _atomic_config_write(config_path, updated, toml=True)
    print(f"Installed Codex MCP entry '{server_name}' into {config_path}.")


def _print_gemini_config(server_name: str) -> None:
    print(
        json.dumps(
            {"mcpServers": {server_name: _build_claude_payload()}},
            indent=2,
        )
    )
    print()
    print(f"Merge this into {_default_gemini_settings_path()}")


def _install_gemini_config(server_name: str, settings_path: Path) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = _read_json_object(settings_path)
    servers = settings.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"Gemini settings at {settings_path} have a non-object mcpServers field.")
    existing = servers.get(server_name)
    if existing is not None and not _looks_like_managed_stdio_entry(existing):
        raise SystemExit(
            f"Gemini config already has an unmanaged {server_name!r} entry; choose --server-name."
        )
    servers[server_name] = _merge_entry(existing, _build_claude_payload())
    _atomic_config_write(settings_path, json.dumps(settings, indent=2) + "\n")
    print(f"Installed Gemini MCP entry '{server_name}' into {settings_path}.")


def _build_droid_config_snippet(server_name: str) -> dict[str, object]:
    payload = _build_claude_payload()
    entry: dict[str, object] = {
        "type": "stdio",
        "command": payload["command"],
        "args": payload["args"],
    }
    env = payload.get("env") or {}
    if env:
        entry["env"] = env
    return {"mcpServers": {server_name: entry}}


def _print_droid_config(server_name: str) -> None:
    print(json.dumps(_build_droid_config_snippet(server_name), indent=2))
    print()
    print(f"Merge this into {_default_droid_mcp_path()}")


def _install_droid_config(server_name: str, mcp_path: Path) -> None:
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    config = _read_json_object(mcp_path)
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"Droid MCP config at {mcp_path} has a non-object mcpServers field.")
    existing = servers.get(server_name)
    if existing is not None and not _looks_like_managed_stdio_entry(existing):
        raise SystemExit(
            f"Droid MCP config already has an unmanaged '{server_name}' entry. "
            "Use --server-name to install under a different name or remove the existing entry first."
        )
    servers[server_name] = _merge_entry(
        existing, _build_droid_config_snippet(server_name)["mcpServers"][server_name]
    )
    _atomic_config_write(mcp_path, json.dumps(config, indent=2) + "\n")
    print(f"Installed Droid MCP entry '{server_name}' into {mcp_path}.")


def _build_opencode_config_snippet(server_name: str) -> dict[str, object]:
    payload = _build_claude_payload()
    entry: dict[str, object] = {
        "type": "local",
        "command": [payload["command"], *payload["args"]],
        "enabled": True,
    }
    env = payload.get("env") or {}
    if env:
        entry["environment"] = env
    return {"mcp": {server_name: entry}}


def _print_opencode_config(server_name: str) -> None:
    print(json.dumps(_build_opencode_config_snippet(server_name), indent=2))
    print()
    print(f"Merge this into {_default_opencode_config_path()}")


def _install_opencode_config(server_name: str, config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = _read_json_object(config_path, jsonc=True)
    mcp = config.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        raise SystemExit(f"OpenCode config at {config_path} has a non-object mcp field.")
    existing = mcp.get(server_name)
    if existing is not None and not _looks_like_managed_opencode_entry(existing):
        raise SystemExit(
            f"OpenCode config already has an unmanaged '{server_name}' MCP entry. "
            "Use --server-name to install under a different name or remove the existing entry first."
        )
    mcp[server_name] = _merge_entry(
        existing, _build_opencode_config_snippet(server_name)["mcp"][server_name]
    )
    _atomic_config_write(config_path, json.dumps(config, indent=2) + "\n")
    print(f"Installed OpenCode MCP entry '{server_name}' into {config_path}.")


def _install_detected_clients(
    *,
    scope: str,
    server_name: str,
    codex_config_path: Path,
    gemini_settings_path: Path,
    droid_mcp_path: Path,
    opencode_config_path: Path,
    skip_clients: set[str] | None = None,
) -> list[str]:
    installed: list[str] = []
    for client in _detect_install_targets(skip_clients=skip_clients):
        if client == "claude":
            _install_claude_config(scope=scope, server_name=server_name)
        elif client == "codex":
            _install_codex_config(server_name=server_name, config_path=codex_config_path)
        elif client == "gemini":
            _install_gemini_config(server_name=server_name, settings_path=gemini_settings_path)
        elif client == "droid":
            _install_droid_config(server_name=server_name, mcp_path=droid_mcp_path)
        elif client == "opencode":
            _install_opencode_config(server_name=server_name, config_path=opencode_config_path)
        installed.append(client)
    return installed


def _print_claude_config(scope: str, server_name: str) -> None:
    print(json.dumps(_build_claude_payload(), indent=2))
    print()
    print("Add to Claude Code with:")
    command = _claude_add_json_command(scope=scope, server_name=server_name)
    print(subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command))
    print(
        "For PowerShell, use --print-config and a client JSON file to avoid shell quoting differences."
    )


def _install_claude_config(scope: str, server_name: str) -> None:
    if not shutil.which("claude"):
        raise SystemExit(
            "Claude CLI not found on PATH. Install Claude Code first or use --print-claude-config."
        )
    command = prepare_process_argv(_claude_add_json_command(scope=scope, server_name=server_name))
    subprocess.run(command, check=True)
    print(f"Installed Claude Code MCP entry '{server_name}' at scope '{scope}'.")


def _run_smoke() -> bool:
    if _WORKFLOW == "toolkit":
        subprocess.run([sys.executable, "-m", "design_toolkit.smoke"], check=True, timeout=60)
        return True
    if not is_repo_checkout():
        return False
    smoke_script = repo_root() / "scripts" / "smoke_mcp_stdio.py"
    env = {
        **os.environ,
        "PYTHONPATH": str(repo_root() / "src"),
        "FRONTEND_DESIGN_LOOP_CONFIG_PATH": str(get_default_config_path()),
    }
    subprocess.run(
        [sys.executable, str(smoke_script)], cwd=str(repo_root()), env=env, check=True, timeout=120
    )
    return True


def _native_auth_status(cli: str, *, probe: bool) -> dict[str, object]:
    from frontend_design_loop_core.cli_paths import resolve_native_cli

    executable = resolve_native_cli(cli)
    installed = bool(shutil.which(cli) or Path(executable).is_file())
    result: dict[str, object] = {
        "cli": cli,
        "installed": installed,
        "authentication": "unknown" if installed else "not_run",
        "auth_probe": "not_run",
        "live_inference": "not_run",
    }
    if not installed:
        result["next_action"] = f"Install {cli} only if you want that optional native provider."
        return result
    commands = {
        "claude": ["claude", "auth", "status"],
        "codex": ["codex", "login", "status"],
        "opencode": ["opencode", "auth", "list"],
    }
    result["next_action"] = (
        "Run --auth-check to probe local auth; this does not prove inference access."
    )
    if not probe or cli not in commands:
        return result
    try:
        response = subprocess.run(
            prepare_process_argv([executable, *commands[cli][1:]]),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        # Do not echo auth output: it may contain account identifiers or credentials.
        output = (response.stdout or "") + (response.stderr or "")
        result["auth_probe"] = "performed"
        if cli == "claude":
            parsed = json.loads(response.stdout)
            if isinstance(parsed, dict) and isinstance(parsed.get("loggedIn"), bool):
                result["authentication"] = (
                    "authenticated" if parsed["loggedIn"] else "unauthenticated"
                )
                method = parsed.get("authMethod")
                if method in {"claude.ai", "oauth_token", "api_key"}:
                    result["auth_method"] = method
        elif cli == "codex":
            lower = output.lower()
            if response.returncode == 0 and "logged in" in lower:
                result["authentication"] = "authenticated"
                result["auth_method"] = "chatgpt" if "chatgpt" in lower else "unknown"
            elif "not logged in" in lower:
                result["authentication"] = "unauthenticated"
        # OpenCode lists provider credentials, not the effective route of a selected model.
        if result["authentication"] == "unauthenticated":
            result["next_action"] = (
                f"Sign in yourself using {cli}; setup never changes login state."
            )
        else:
            result["next_action"] = (
                "Choose an explicit provider/model for automation; auth status does not verify live inference or billing route."
            )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        result["auth_probe"] = "error"
        result["next_action"] = (
            f"Check `{cli} --help` and its auth status command locally; probe was inconclusive."
        )
    return result


def _report_native_auth(*, probe: bool = False) -> None:
    for cli in ("claude", "codex", "opencode"):
        print(json.dumps(_native_auth_status(cli, probe=probe), sort_keys=True))


def _run_doctor(*, run_smoke: bool) -> int:
    ok = True

    ready, detail = _check_playwright_ready()
    ok &= _doctor_check("playwright chromium ready", ready, detail)

    if _WORKFLOW == "automated":
        for label, path in (
            ("config", get_default_config_path()),
            ("prompts", get_default_prompts_path()),
            ("template", get_default_template_path()),
        ):
            ok &= _doctor_check(label + " path exists", path.exists(), str(path))
    _doctor_check(
        "install mode", True, "repo checkout" if is_repo_checkout() else "packaged install"
    )
    print(
        "Native CLIs are optional for the host-agent toolkit. Auth and inference are separate checks."
    )
    _report_native_auth()
    if run_smoke:
        try:
            ran = _run_smoke()
            if ran:
                _doctor_check("stdio smoke", True, _WORKFLOW + " stdio initialization")
            else:
                _doctor_check(
                    "stdio smoke",
                    True,
                    "skipped outside repo checkout; automated render smoke unavailable",
                )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            ok &= _doctor_check("stdio smoke", False, str(exc))

    print()
    print("Recommended client setup commands:")
    print("  Any MCP client: frontend-design-loop-setup --print-config (recommended)")
    print(
        "  All detected: frontend-design-loop-setup --install-all-detected-clients (writes settings)"
    )
    print("  Claude:       frontend-design-loop-setup --install-claude --scope user")
    print("  Codex:        frontend-design-loop-setup --install-codex")
    print("  Gemini:       frontend-design-loop-setup --install-gemini")
    print("  Droid:        frontend-design-loop-setup --install-droid")
    print("  OpenCode:     frontend-design-loop-setup --install-opencode")
    return 0 if ok else 1


def _ensure_playwright_ready() -> None:
    ready, detail = _check_playwright_ready()
    if ready:
        print(detail)
        return

    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    subprocess.run(command, check=True)
    ready, detail = _check_playwright_ready()
    print(detail)
    if not ready:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    global _WORKFLOW
    parser = argparse.ArgumentParser(
        prog="frontend-design-loop-setup",
        description="Prepare Chromium and print or explicitly install MCP client configurations.",
    )
    parser.add_argument(
        "--workflow",
        choices=["toolkit", "automated"],
        default="toolkit",
        help="host-agent toolkit (recommended) or automated loop server",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--doctor", action="store_true", help="read-only environment checks; never runs inference"
    )
    parser.add_argument(
        "--auth-check",
        action="store_true",
        help="opt in to bounded read-only CLI auth status probes",
    )
    parser.add_argument(
        "--smoke", action="store_true", help="run selected stdio smoke (no model inference)"
    )
    parser.add_argument("--print-config", action="store_true", help="print generic mcpServers JSON")
    parser.add_argument("--install-all-detected-clients", action="store_true")
    for client in ("claude", "codex", "gemini", "droid", "opencode"):
        parser.add_argument(f"--print-{client}-config", action="store_true")
        parser.add_argument(f"--install-{client}", action="store_true")
    parser.add_argument("--codex-config-path", default=str(_default_codex_config_path()))
    parser.add_argument("--gemini-settings-path", default=str(_default_gemini_settings_path()))
    parser.add_argument("--droid-mcp-path", default=str(_default_droid_mcp_path()))
    parser.add_argument("--opencode-config-path", default=str(_default_opencode_config_path()))
    parser.add_argument("--scope", choices=["user", "project", "local"], default="user")
    parser.add_argument("--server-name", default=None)
    parser.add_argument(
        "--skip-client",
        action="append",
        default=[],
        choices=["claude", "codex", "gemini", "droid", "opencode"],
    )
    args = parser.parse_args(argv)
    _WORKFLOW = args.workflow
    name = args.server_name or (
        "frontend-design-toolkit" if _WORKFLOW == "toolkit" else "frontend-design-loop-mcp"
    )
    if not name or any(ord(ch) < 32 for ch in name):
        parser.error("server name must be nonempty and contain no control characters")
    if args.check:
        ready, detail = _check_playwright_ready()
        print(detail)
        if not ready:
            raise SystemExit(1)
        return
    printers = {
        "claude": lambda: _print_claude_config(args.scope, name),
        "codex": lambda: _print_codex_config(name),
        "gemini": lambda: _print_gemini_config(name),
        "droid": lambda: _print_droid_config(name),
        "opencode": lambda: _print_opencode_config(name),
    }
    installers = {
        "claude": lambda: _install_claude_config(scope=args.scope, server_name=name),
        "codex": lambda: _install_codex_config(
            server_name=name, config_path=Path(args.codex_config_path).expanduser()
        ),
        "gemini": lambda: _install_gemini_config(
            server_name=name, settings_path=Path(args.gemini_settings_path).expanduser()
        ),
        "droid": lambda: _install_droid_config(
            server_name=name, mcp_path=Path(args.droid_mcp_path).expanduser()
        ),
        "opencode": lambda: _install_opencode_config(
            server_name=name, config_path=Path(args.opencode_config_path).expanduser()
        ),
    }
    printed = args.print_config
    if args.print_config:
        print(json.dumps({"mcpServers": {name: _build_claude_payload()}}, indent=2))
    for client, printer in printers.items():
        if getattr(args, f"print_{client}_config"):
            printer()
            printed = True
    installs = [client for client in installers if getattr(args, f"install_{client}")]
    if args.install_all_detected_clients:
        installs.extend(_detect_install_targets(skip_clients=set(args.skip_client)))
    if installs or args.smoke:
        _ensure_playwright_ready()
    for client in dict.fromkeys(installs):
        installers[client]()
    if args.install_all_detected_clients:
        print(
            "Installed detected clients: " + ", ".join(dict.fromkeys(installs))
            if installs
            else "No supported clients detected for auto-install."
        )
    if args.auth_check:
        _report_native_auth(probe=True)
    if args.doctor or args.smoke or installs or args.install_all_detected_clients:
        raise SystemExit(_run_doctor(run_smoke=args.smoke))
    if printed or args.auth_check:
        return
    _ensure_playwright_ready()
    print("Next: frontend-design-loop-setup --print-config (any MCP client)")
    print("Or --print-codex-config / --print-claude-config / --print-opencode-config")
    print("Only --install-* flags write client settings. --workflow automated selects the loop.")


if __name__ == "__main__":
    main()
