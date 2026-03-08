"""Frontend Design Loop MCP setup helper.

This exists to make `pipx install frontend-design-loop-mcp` feel product-like:
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
from pathlib import Path

from frontend_design_loop_mcp.runtime_paths import (
    get_default_config_path,
    get_default_out_dir,
    get_default_prompts_path,
    get_default_template_path,
    is_repo_checkout,
    repo_root,
)


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
    except Exception as exc:  # pragma: no cover - defensive check
        return (
            False,
            f"Playwright Chromium check failed: {exc}. Run 'frontend-design-loop-setup'.",
        )

    if executable.exists():
        return (True, f"Playwright Chromium ready at {executable}")

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
    if is_repo_checkout():
        return {
            "command": sys.executable,
            "args": ["-m", "frontend_design_loop_mcp.mcp_server"],
            "env": {
                "FRONTEND_DESIGN_LOOP_CONFIG_PATH": str(get_default_config_path()),
            },
        }
    return {
        "command": "frontend-design-loop-mcp",
        "args": [],
    }


def _claude_add_json_command(scope: str, server_name: str) -> list[str]:
    payload = json.dumps(_build_claude_payload(), separators=(",", ":"))
    return ["claude", "mcp", "add-json", "--scope", scope, server_name, payload]


def _default_codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


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
    if "gemini" not in skip and (shutil.which("gemini") or _default_gemini_settings_path().exists()):
        targets.append("gemini")
    if "droid" not in skip and (shutil.which("droid") or _default_droid_mcp_path().exists()):
        targets.append("droid")
    if "opencode" not in skip and (shutil.which("opencode") or _default_opencode_config_path().exists()):
        targets.append("opencode")
    return targets


def _build_codex_config_block(server_name: str) -> str:
    payload = _build_claude_payload()
    lines = [
        f'# BEGIN frontend-design-loop-mcp managed block: {server_name}',
        f"[mcp_servers.{server_name}]",
        f'command = "{payload["command"]}"',
        "args = [" + ", ".join(json.dumps(arg) for arg in payload["args"]) + "]",
        "enabled = true",
    ]
    env = payload.get("env") or {}
    if env:
        lines.append("")
        lines.append(f"[mcp_servers.{server_name}.env]")
        for key, value in env.items():
            lines.append(f'{key} = "{value}"')
    lines.append(f"# END frontend-design-loop-mcp managed block: {server_name}")
    return "\n".join(lines) + "\n"


def _replace_or_append_managed_block(text: str, *, server_name: str, block: str) -> str:
    header = f"# BEGIN frontend-design-loop-mcp managed block: {server_name}"
    footer = f"# END frontend-design-loop-mcp managed block: {server_name}"
    if header in text and footer in text:
        pattern = re.compile(
            rf"{re.escape(header)}[\s\S]*?{re.escape(footer)}\n?",
            re.MULTILINE,
        )
        return pattern.sub(block, text, count=1)

    unmanaged_pattern = re.compile(
        rf"(?m)^\[mcp_servers\.{re.escape(server_name)}\]\s*$"
    )
    if unmanaged_pattern.search(text):
        raise SystemExit(
            f"Codex config already has an unmanaged [mcp_servers.{server_name}] block. "
            "Use --server-name to install under a different name or convert it to the managed block first."
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
    config_path.write_text(updated, encoding="utf-8")
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
    servers[server_name] = _build_claude_payload()
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
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
    servers[server_name] = _build_droid_config_snippet(server_name)["mcpServers"][server_name]
    mcp_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
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
    mcp[server_name] = _build_opencode_config_snippet(server_name)["mcp"][server_name]
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
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
    print(shlex.join(_claude_add_json_command(scope=scope, server_name=server_name)))


def _install_claude_config(scope: str, server_name: str) -> None:
    if not shutil.which("claude"):
        raise SystemExit("Claude CLI not found on PATH. Install Claude Code first or use --print-claude-config.")
    subprocess.run(_claude_add_json_command(scope=scope, server_name=server_name), check=True)
    print(f"Installed Claude Code MCP entry '{server_name}' at scope '{scope}'.")


def _run_smoke() -> bool:
    if not is_repo_checkout():
        return False

    smoke_script = repo_root() / "scripts" / "smoke_mcp_stdio.py"
    pythonpath = str(repo_root() / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath = pythonpath + os.pathsep + existing_pythonpath
    env = {
        **os.environ,
        "PYTHONPATH": pythonpath,
        "FRONTEND_DESIGN_LOOP_CONFIG_PATH": str(get_default_config_path()),
    }
    subprocess.run([sys.executable, str(smoke_script)], cwd=str(repo_root()), env=env, check=True)
    return True


def _run_doctor(*, run_smoke: bool) -> int:
    ok = True

    ready, detail = _check_playwright_ready()
    ok &= _doctor_check("playwright chromium ready", ready, detail)

    config_path = get_default_config_path()
    prompts_path = get_default_prompts_path()
    template_path = get_default_template_path()
    out_dir = get_default_out_dir()
    ok &= _doctor_check("config path exists", config_path.exists(), str(config_path))
    ok &= _doctor_check("prompts path exists", prompts_path.exists(), str(prompts_path))
    ok &= _doctor_check("template path exists", template_path.exists(), str(template_path))
    ok &= _doctor_check("default out dir resolved", bool(out_dir), str(out_dir))
    _doctor_check(
        "install mode",
        True,
        "repo checkout" if is_repo_checkout() else "packaged install",
    )

    claude_path = shutil.which("claude")
    _doctor_check("claude cli visible", bool(claude_path), claude_path or "not on PATH")
    codex_path = shutil.which("codex")
    _doctor_check("codex cli visible", bool(codex_path), codex_path or "not on PATH")
    gemini_path = shutil.which("gemini")
    _doctor_check("gemini cli visible", bool(gemini_path), gemini_path or "not on PATH")
    droid_path = shutil.which("droid")
    _doctor_check("droid cli visible", bool(droid_path), droid_path or "not on PATH")
    opencode_path = shutil.which("opencode")
    _doctor_check("opencode cli visible", bool(opencode_path), opencode_path or "not on PATH")

    if run_smoke:
        try:
            ran = _run_smoke()
            if ran:
                _doctor_check("stdio smoke", True, "frontend_design_loop_eval")
            else:
                _doctor_check("stdio smoke", True, "skipped outside repo checkout")
        except subprocess.CalledProcessError as exc:
            ok &= _doctor_check("stdio smoke", False, str(exc))

    print()
    print("Recommended client setup commands:")
    print("  All detected: frontend-design-loop-setup --install-all-detected-clients")
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
    parser = argparse.ArgumentParser(
        prog="frontend-design-loop-setup",
        description="Install or verify the Playwright Chromium dependency used by Frontend Design Loop MCP.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify Playwright is importable without downloading browsers",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="run install/asset/CLI checks and print the recommended Claude config",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run the stdio smoke test when executed from a repo checkout",
    )
    parser.add_argument(
        "--print-claude-config",
        action="store_true",
        help="print the ready-to-use Claude Code MCP JSON plus add-json command",
    )
    parser.add_argument(
        "--install-claude",
        action="store_true",
        help="install the MCP entry into Claude Code with claude mcp add-json",
    )
    parser.add_argument(
        "--install-all-detected-clients",
        action="store_true",
        help="install the MCP entry into every detected supported client (Claude, Codex, Gemini, Droid, OpenCode)",
    )
    parser.add_argument(
        "--print-codex-config",
        action="store_true",
        help="print the managed Codex config block to add to ~/.codex/config.toml",
    )
    parser.add_argument(
        "--install-codex",
        action="store_true",
        help="install the MCP entry into the Codex config file",
    )
    parser.add_argument(
        "--codex-config-path",
        default=str(_default_codex_config_path()),
        help="Codex config.toml path to print/install against",
    )
    parser.add_argument(
        "--print-gemini-config",
        action="store_true",
        help="print the JSON snippet to merge into ~/.gemini/settings.json",
    )
    parser.add_argument(
        "--install-gemini",
        action="store_true",
        help="install the MCP entry into Gemini settings.json",
    )
    parser.add_argument(
        "--gemini-settings-path",
        default=str(_default_gemini_settings_path()),
        help="Gemini settings.json path to print/install against",
    )
    parser.add_argument(
        "--print-droid-config",
        action="store_true",
        help="print the JSON snippet to merge into ~/.factory/mcp.json",
    )
    parser.add_argument(
        "--install-droid",
        action="store_true",
        help="install the MCP entry into Droid ~/.factory/mcp.json",
    )
    parser.add_argument(
        "--droid-mcp-path",
        default=str(_default_droid_mcp_path()),
        help="Droid mcp.json path to print/install against",
    )
    parser.add_argument(
        "--print-opencode-config",
        action="store_true",
        help="print the JSON snippet to merge into ~/.config/opencode/opencode.json",
    )
    parser.add_argument(
        "--install-opencode",
        action="store_true",
        help="install the MCP entry into OpenCode config",
    )
    parser.add_argument(
        "--opencode-config-path",
        default=str(_default_opencode_config_path()),
        help="OpenCode config path to print/install against",
    )
    parser.add_argument(
        "--scope",
        default="user",
        help="scope passed to claude mcp add-json (default: user)",
    )
    parser.add_argument(
        "--server-name",
        default="frontend-design-loop-mcp",
        help="Claude Code MCP server name to install/print (default: frontend-design-loop-mcp)",
    )
    parser.add_argument(
        "--skip-client",
        action="append",
        default=[],
        choices=["claude", "codex", "gemini", "droid", "opencode"],
        help="client(s) to skip when using --install-all-detected-clients",
    )
    args = parser.parse_args(argv)
    skip_clients = set(args.skip_client)

    if args.check:
        ready, detail = _check_playwright_ready()
        print(detail)
        if not ready:
            raise SystemExit(1)
        return

    if args.print_claude_config and not (
        args.install_claude
        or args.install_all_detected_clients
        or args.install_codex
        or args.install_gemini
        or args.install_droid
        or args.install_opencode
        or args.doctor
        or args.smoke
        or args.print_codex_config
        or args.print_gemini_config
        or args.print_droid_config
        or args.print_opencode_config
    ):
        _print_claude_config(scope=args.scope, server_name=args.server_name)
        return
    if args.print_codex_config and not (
        args.install_claude
        or args.install_all_detected_clients
        or args.install_codex
        or args.install_gemini
        or args.install_droid
        or args.install_opencode
        or args.doctor
        or args.smoke
        or args.print_claude_config
        or args.print_gemini_config
        or args.print_droid_config
        or args.print_opencode_config
    ):
        _print_codex_config(server_name=args.server_name)
        return
    if args.print_gemini_config and not (
        args.install_claude
        or args.install_all_detected_clients
        or args.install_codex
        or args.install_gemini
        or args.install_droid
        or args.install_opencode
        or args.doctor
        or args.smoke
        or args.print_claude_config
        or args.print_codex_config
        or args.print_droid_config
        or args.print_opencode_config
    ):
        _print_gemini_config(server_name=args.server_name)
        return
    if args.print_droid_config and not (
        args.install_claude
        or args.install_all_detected_clients
        or args.install_codex
        or args.install_gemini
        or args.install_droid
        or args.install_opencode
        or args.doctor
        or args.smoke
        or args.print_claude_config
        or args.print_codex_config
        or args.print_gemini_config
        or args.print_opencode_config
    ):
        _print_droid_config(server_name=args.server_name)
        return
    if args.print_opencode_config and not (
        args.install_claude
        or args.install_all_detected_clients
        or args.install_codex
        or args.install_gemini
        or args.install_droid
        or args.install_opencode
        or args.doctor
        or args.smoke
        or args.print_claude_config
        or args.print_codex_config
        or args.print_gemini_config
        or args.print_droid_config
    ):
        _print_opencode_config(server_name=args.server_name)
        return

    if (
        args.install_claude
        or args.install_all_detected_clients
        or args.install_codex
        or args.install_gemini
        or args.install_droid
        or args.install_opencode
        or args.smoke
    ):
        _ensure_playwright_ready()

    if args.install_claude:
        _install_claude_config(scope=args.scope, server_name=args.server_name)
    if args.install_all_detected_clients:
        installed = _install_detected_clients(
            scope=args.scope,
            server_name=args.server_name,
            codex_config_path=Path(args.codex_config_path).expanduser(),
            gemini_settings_path=Path(args.gemini_settings_path).expanduser(),
            droid_mcp_path=Path(args.droid_mcp_path).expanduser(),
            opencode_config_path=Path(args.opencode_config_path).expanduser(),
            skip_clients=skip_clients,
        )
        if installed:
            print("Installed detected clients: " + ", ".join(installed))
        else:
            print("No supported clients detected for auto-install.")
    if args.install_codex:
        _install_codex_config(
            server_name=args.server_name,
            config_path=Path(args.codex_config_path).expanduser(),
        )
    if args.install_gemini:
        _install_gemini_config(
            server_name=args.server_name,
            settings_path=Path(args.gemini_settings_path).expanduser(),
        )
    if args.install_droid:
        _install_droid_config(
            server_name=args.server_name,
            mcp_path=Path(args.droid_mcp_path).expanduser(),
        )
    if args.install_opencode:
        _install_opencode_config(
            server_name=args.server_name,
            config_path=Path(args.opencode_config_path).expanduser(),
        )

    if (
        args.doctor
        or args.smoke
        or args.install_claude
        or args.install_all_detected_clients
        or args.install_codex
        or args.install_gemini
        or args.install_droid
        or args.install_opencode
    ):
        if args.print_claude_config:
            print()
            print("Claude config:")
            _print_claude_config(scope=args.scope, server_name=args.server_name)
        if args.print_codex_config:
            print()
            print("Codex config:")
            _print_codex_config(server_name=args.server_name)
        if args.print_gemini_config:
            print()
            print("Gemini config:")
            _print_gemini_config(server_name=args.server_name)
        if args.print_droid_config:
            print()
            print("Droid config:")
            _print_droid_config(server_name=args.server_name)
        if args.print_opencode_config:
            print()
            print("OpenCode config:")
            _print_opencode_config(server_name=args.server_name)
        raise SystemExit(_run_doctor(run_smoke=args.smoke))

    _ensure_playwright_ready()

    print()
    print("Next:")
    print("1) Add the MCP everywhere supported:")
    print("   frontend-design-loop-setup --install-all-detected-clients")
    print("2) Or target one client:")
    print("   frontend-design-loop-setup --install-claude --scope user")
    print("   frontend-design-loop-setup --install-codex")
    print("   frontend-design-loop-setup --install-gemini")
    print("   frontend-design-loop-setup --install-droid")
    print("   frontend-design-loop-setup --install-opencode")
    print("3) Or print configs instead:")
    print("   frontend-design-loop-setup --print-claude-config")
    print("   frontend-design-loop-setup --print-codex-config")
    print("   frontend-design-loop-setup --print-gemini-config")
    print("   frontend-design-loop-setup --print-droid-config")
    print("   frontend-design-loop-setup --print-opencode-config")
    if is_repo_checkout():
        print("4) Run the local stdio smoke:")
        print("   frontend-design-loop-setup --doctor --smoke")


if __name__ == "__main__":
    main()
