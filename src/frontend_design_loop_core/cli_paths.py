"""Locate native installations when desktop clients inherit a minimal PATH."""

from __future__ import annotations

import os
from pathlib import Path

from frontend_design_loop_core.command_runtime import environment_value, find_executable


def resolve_native_cli(
    name: str, *, env: dict[str, str] | None = None, cwd: Path | str | None = None
) -> str:
    environment = os.environ if env is None else env
    override = environment_value(
        environment, f"FRONTEND_DESIGN_LOOP_{name.upper()}_CLI", windows=os.name == "nt"
    )
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"Explicit {name} CLI must be an existing absolute file")
        return str(path)
    found = find_executable(name, env=env, cwd=cwd)
    if found:
        return found
    if Path(name).is_absolute():
        return name
    if name not in {"codex", "claude", "opencode"}:
        return name
    home_value = environment_value(
        environment, "USERPROFILE" if os.name == "nt" else "HOME", windows=os.name == "nt"
    )
    home = Path(home_value) if home_value else Path.home()
    directories = [
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        home / ".local" / "bin",
        home / ".npm-global" / "bin",
    ]
    if os.name == "nt":
        appdata = environment_value(environment, "APPDATA", windows=True) or str(home)
        directories = [Path(appdata) / "npm", home / ".local" / "bin"]
    for directory in directories:
        for suffix in [".exe", ".cmd", ""] if os.name == "nt" else [""]:
            candidate = directory / (name + suffix)
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return name
