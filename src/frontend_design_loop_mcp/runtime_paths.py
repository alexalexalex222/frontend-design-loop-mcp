from __future__ import annotations

import os
import sys
from importlib.resources import files
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return _REPO_ROOT


def is_repo_checkout() -> bool:
    return _looks_like_repo_root(repo_root())


def package_asset_root() -> Path:
    return Path(str(files("frontend_design_loop_mcp").joinpath("assets")))


def _looks_like_repo_root(root: Path) -> bool:
    return (
        (root / "config" / "config.yaml").exists()
        and (root / "templates" / "nextjs_app_router_tailwind").exists()
        and (root / "prompts").exists()
    )


def get_asset_root() -> Path:
    root = repo_root()
    if _looks_like_repo_root(root):
        return root
    return package_asset_root()


def get_default_config_path() -> Path:
    return get_asset_root() / "config" / "config.yaml"


def get_default_template_path() -> Path:
    return get_asset_root() / "templates" / "nextjs_app_router_tailwind"


def get_default_prompts_path() -> Path:
    return get_asset_root() / "prompts"


def get_default_state_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "frontend-design-loop-mcp"
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "frontend-design-loop-mcp"
        return Path.home() / "AppData" / "Roaming" / "frontend-design-loop-mcp"

    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "frontend-design-loop-mcp"

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "frontend-design-loop-mcp"

    return Path.home() / ".local" / "share" / "frontend-design-loop-mcp"


def get_default_out_dir(subdir: str | None = None) -> Path:
    if is_repo_checkout():
        base = repo_root() / "out"
    else:
        base = get_default_state_root() / "out"
    if subdir:
        return base / subdir
    return base
