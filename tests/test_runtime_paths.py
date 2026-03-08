from pathlib import Path

from frontend_design_loop_mcp import runtime_paths
from frontend_design_loop_core import config as config_mod


def test_load_config_uses_runtime_asset_helpers(tmp_path: Path, monkeypatch) -> None:
    asset_root = tmp_path / "assets"
    config_path = asset_root / "config" / "config.yaml"
    template_path = asset_root / "templates" / "nextjs_app_router_tailwind"
    prompts_path = asset_root / "prompts"
    out_path = tmp_path / "state-out"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.mkdir(parents=True, exist_ok=True)
    prompts_path.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "models:\n"
        "  planner: {}\n"
        "  ui_generators: []\n"
        "  patcher: {}\n"
        "  vision_judge: {}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config_mod, "get_default_config_path", lambda: config_path)
    monkeypatch.setattr(config_mod, "get_asset_root", lambda: asset_root)
    monkeypatch.setattr(config_mod, "get_default_template_path", lambda: template_path)
    monkeypatch.setattr(config_mod, "get_default_prompts_path", lambda: prompts_path)
    monkeypatch.setattr(
        config_mod,
        "get_default_out_dir",
        lambda subdir=None: out_path / subdir if subdir else out_path,
    )

    loaded = config_mod.load_config()

    assert loaded.project_root == asset_root
    assert loaded.template_path == template_path
    assert loaded.prompts_path == prompts_path
    assert loaded.out_path == out_path


def test_runtime_paths_use_user_state_dir_when_repo_layout_missing(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "not-a-repo-layout"
    package_assets = tmp_path / "pkg-assets"
    state_root = tmp_path / "state-root"

    monkeypatch.setattr(runtime_paths, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(runtime_paths, "package_asset_root", lambda: package_assets)
    monkeypatch.setattr(runtime_paths, "get_default_state_root", lambda: state_root)

    assert runtime_paths.get_asset_root() == package_assets
    assert runtime_paths.get_default_out_dir("mcp-code-runs") == state_root / "out" / "mcp-code-runs"


def test_load_config_accepts_frontend_design_loop_env_var(tmp_path: Path, monkeypatch) -> None:
    asset_root = tmp_path / "assets"
    config_path = asset_root / "config" / "config.yaml"
    template_path = asset_root / "templates" / "nextjs_app_router_tailwind"
    prompts_path = asset_root / "prompts"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.mkdir(parents=True, exist_ok=True)
    prompts_path.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "models:\n"
        "  planner: {}\n"
        "  ui_generators: []\n"
        "  patcher: {}\n"
        "  vision_judge: {}\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("FRONTEND_DESIGN_LOOP_CONFIG_PATH", raising=False)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_mod, "get_asset_root", lambda: asset_root)
    monkeypatch.setattr(config_mod, "get_default_template_path", lambda: template_path)
    monkeypatch.setattr(config_mod, "get_default_prompts_path", lambda: prompts_path)

    loaded = config_mod.load_config()

    assert loaded.project_root == asset_root
