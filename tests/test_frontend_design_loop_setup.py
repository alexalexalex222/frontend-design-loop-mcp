import json
import pytest
from pathlib import Path

from frontend_design_loop_mcp import setup as setup_mod


def test_setup_check_exits_zero_when_playwright_ready(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        setup_mod,
        "_check_playwright_ready",
        lambda: (True, "Playwright Chromium ready at /tmp/chromium"),
    )

    setup_mod.main(["--check"])

    out = capsys.readouterr().out
    assert "Playwright Chromium ready" in out


def test_setup_check_exits_nonzero_when_playwright_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        setup_mod,
        "_check_playwright_ready",
        lambda: (False, "Playwright Chromium is not installed"),
    )

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(["--check"])

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not installed" in out


def test_setup_print_claude_config_outputs_json_and_command(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)
    monkeypatch.setattr(setup_mod.sys, "executable", "/tmp/python")

    setup_mod.main(["--print-claude-config"])

    out = capsys.readouterr().out
    assert '"command": "frontend-design-loop-mcp"' in out
    assert "claude mcp add-json --scope user frontend-design-loop-mcp" in out


def test_setup_print_claude_config_uses_repo_python_for_checkout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: True)
    monkeypatch.setattr(setup_mod.sys, "executable", "/repo/.venv/bin/python")
    monkeypatch.setattr(setup_mod, "get_default_config_path", lambda: Path("/repo/config/config.yaml"))

    setup_mod.main(["--print-claude-config"])

    out = capsys.readouterr().out
    assert '"/repo/.venv/bin/python"' in out
    assert '"FRONTEND_DESIGN_LOOP_CONFIG_PATH": "/repo/config/config.yaml"' in out


def test_setup_install_claude_invokes_cli_and_doctor(monkeypatch) -> None:
    calls: list[list[str]] = []
    doctor_calls: list[bool] = []

    monkeypatch.setattr(setup_mod.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: None)
    monkeypatch.setattr(setup_mod, "_run_doctor", lambda *, run_smoke: doctor_calls.append(run_smoke) or 0)
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    def fake_run(cmd, check, **kwargs):
        calls.append(cmd)
        return None

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(["--install-claude", "--scope", "user"])

    assert exc_info.value.code == 0
    assert calls == [
        [
            "claude",
            "mcp",
            "add-json",
            "--scope",
            "user",
            "frontend-design-loop-mcp",
            '{"command":"frontend-design-loop-mcp","args":[]}',
        ]
    ]
    assert doctor_calls == [False]


def test_setup_doctor_runs_without_installing_playwright(monkeypatch) -> None:
    doctor_calls: list[bool] = []
    ensured: list[bool] = []

    monkeypatch.setattr(setup_mod, "_run_doctor", lambda *, run_smoke: doctor_calls.append(run_smoke) or 0)
    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: ensured.append(True))

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(["--doctor"])

    assert exc_info.value.code == 0
    assert doctor_calls == [False]
    assert ensured == []


def test_setup_doctor_smoke_skip_is_nonfatal(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_mod, "_check_playwright_ready", lambda: (True, "ready"))
    monkeypatch.setattr(setup_mod, "get_default_config_path", lambda: Path("/tmp/config.yaml"))
    monkeypatch.setattr(setup_mod, "get_default_prompts_path", lambda: Path("/tmp/prompts"))
    monkeypatch.setattr(setup_mod, "get_default_template_path", lambda: Path("/tmp/templates"))
    monkeypatch.setattr(setup_mod, "get_default_out_dir", lambda: Path("/tmp/out"))
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)
    monkeypatch.setattr(setup_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup_mod.Path, "exists", lambda self: True)
    monkeypatch.setattr(setup_mod, "_run_smoke", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(["--doctor", "--smoke"])

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "skipped outside repo checkout" in out


def test_setup_print_codex_config_outputs_managed_block(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    setup_mod.main(["--print-codex-config"])

    out = capsys.readouterr().out
    assert "[mcp_servers.frontend-design-loop-mcp]" in out
    assert 'command = "frontend-design-loop-mcp"' in out
    assert "managed block" in out


def test_setup_install_codex_writes_managed_block_and_runs_doctor(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
    doctor_calls: list[bool] = []

    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: None)
    monkeypatch.setattr(setup_mod, "_run_doctor", lambda *, run_smoke: doctor_calls.append(run_smoke) or 0)
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(["--install-codex", "--codex-config-path", str(config_path)])

    assert exc_info.value.code == 0
    text = config_path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.4"' in text
    assert "[mcp_servers.frontend-design-loop-mcp]" in text
    assert 'command = "frontend-design-loop-mcp"' in text
    assert doctor_calls == [False]


def test_setup_install_codex_refuses_unmanaged_existing_block(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[mcp_servers.frontend-design-loop-mcp]\ncommand = \"existing\"\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        setup_mod._install_codex_config("frontend-design-loop-mcp", config_path)

    assert "unmanaged" in str(exc_info.value)


def test_setup_print_gemini_config_outputs_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    setup_mod.main(["--print-gemini-config"])

    out = capsys.readouterr().out
    assert '"mcpServers"' in out
    assert '"frontend-design-loop-mcp"' in out
    assert '"command": "frontend-design-loop-mcp"' in out


def test_setup_install_gemini_updates_settings_and_runs_doctor(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"general": {"model": "gemini-3.1-pro-preview"}}), encoding="utf-8")
    doctor_calls: list[bool] = []

    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: None)
    monkeypatch.setattr(setup_mod, "_run_doctor", lambda *, run_smoke: doctor_calls.append(run_smoke) or 0)
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(["--install-gemini", "--gemini-settings-path", str(settings_path)])

    assert exc_info.value.code == 0
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["general"]["model"] == "gemini-3.1-pro-preview"
    assert data["mcpServers"]["frontend-design-loop-mcp"]["command"] == "frontend-design-loop-mcp"
    assert doctor_calls == [False]


def test_setup_print_droid_config_outputs_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    setup_mod.main(["--print-droid-config"])

    out = capsys.readouterr().out
    assert '"mcpServers"' in out
    assert '"type": "stdio"' in out
    assert '"command": "frontend-design-loop-mcp"' in out


def test_setup_install_droid_updates_mcp_json_and_runs_doctor(tmp_path, monkeypatch) -> None:
    mcp_path = tmp_path / "mcp.json"
    mcp_path.write_text(json.dumps({"mcpServers": {"existing": {"type": "stdio", "command": "foo"}}}), encoding="utf-8")
    doctor_calls: list[bool] = []

    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: None)
    monkeypatch.setattr(setup_mod, "_run_doctor", lambda *, run_smoke: doctor_calls.append(run_smoke) or 0)
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(["--install-droid", "--droid-mcp-path", str(mcp_path)])

    assert exc_info.value.code == 0
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["existing"]["command"] == "foo"
    assert data["mcpServers"]["frontend-design-loop-mcp"]["type"] == "stdio"
    assert data["mcpServers"]["frontend-design-loop-mcp"]["command"] == "frontend-design-loop-mcp"
    assert doctor_calls == [False]


def test_setup_install_droid_refuses_unmanaged_existing_entry(tmp_path) -> None:
    mcp_path = tmp_path / "mcp.json"
    mcp_path.write_text(
        json.dumps({"mcpServers": {"frontend-design-loop-mcp": {"type": "stdio", "command": "existing", "args": []}}}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        setup_mod._install_droid_config("frontend-design-loop-mcp", mcp_path)

    assert "unmanaged" in str(exc_info.value)


def test_setup_print_opencode_config_outputs_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    setup_mod.main(["--print-opencode-config"])

    out = capsys.readouterr().out
    assert '"mcp"' in out
    assert '"type": "local"' in out
    assert '"frontend-design-loop-mcp"' in out


def test_setup_install_opencode_updates_config_and_runs_doctor(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "opencode.json"
    config_path.write_text(
        '{\n  // keep comments\n  "default_agent": "build",\n}\n',
        encoding="utf-8",
    )
    doctor_calls: list[bool] = []

    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: None)
    monkeypatch.setattr(setup_mod, "_run_doctor", lambda *, run_smoke: doctor_calls.append(run_smoke) or 0)
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(["--install-opencode", "--opencode-config-path", str(config_path)])

    assert exc_info.value.code == 0
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["default_agent"] == "build"
    assert data["mcp"]["frontend-design-loop-mcp"]["type"] == "local"
    assert data["mcp"]["frontend-design-loop-mcp"]["command"] == ["frontend-design-loop-mcp"]
    assert data["mcp"]["frontend-design-loop-mcp"]["enabled"] is True
    assert doctor_calls == [False]


def test_setup_install_opencode_refuses_unmanaged_existing_entry(tmp_path) -> None:
    config_path = tmp_path / "opencode.json"
    config_path.write_text(
        json.dumps({"mcp": {"frontend-design-loop-mcp": {"type": "local", "command": ["other"], "enabled": True}}}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        setup_mod._install_opencode_config("frontend-design-loop-mcp", config_path)

    assert "unmanaged" in str(exc_info.value)


def test_detect_install_targets_respects_skip_clients(monkeypatch, tmp_path) -> None:
    codex_cfg = tmp_path / "config.toml"
    gemini_cfg = tmp_path / "settings.json"
    droid_cfg = tmp_path / "mcp.json"
    opencode_cfg = tmp_path / "opencode.json"
    codex_cfg.write_text("", encoding="utf-8")
    gemini_cfg.write_text("{}", encoding="utf-8")
    droid_cfg.write_text("{}", encoding="utf-8")
    opencode_cfg.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(setup_mod, "_default_codex_config_path", lambda: codex_cfg)
    monkeypatch.setattr(setup_mod, "_default_gemini_settings_path", lambda: gemini_cfg)
    monkeypatch.setattr(setup_mod, "_default_droid_mcp_path", lambda: droid_cfg)
    monkeypatch.setattr(setup_mod, "_default_opencode_config_path", lambda: opencode_cfg)
    monkeypatch.setattr(
        setup_mod.shutil,
        "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )

    assert setup_mod._detect_install_targets() == ["claude", "codex", "gemini", "droid", "opencode"]
    assert setup_mod._detect_install_targets(skip_clients={"claude", "gemini", "opencode"}) == ["codex", "droid"]


def test_setup_install_all_detected_clients_installs_everything(monkeypatch, tmp_path, capsys) -> None:
    codex_cfg = tmp_path / "config.toml"
    gemini_cfg = tmp_path / "settings.json"
    droid_cfg = tmp_path / "mcp.json"
    opencode_cfg = tmp_path / "opencode.json"
    gemini_cfg.write_text("{}", encoding="utf-8")
    doctor_calls: list[bool] = []
    installed: list[str] = []

    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: None)
    monkeypatch.setattr(setup_mod, "_run_doctor", lambda *, run_smoke: doctor_calls.append(run_smoke) or 0)
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)
    monkeypatch.setattr(setup_mod, "_detect_install_targets", lambda *, skip_clients=None: ["claude", "codex", "gemini", "droid", "opencode"])
    monkeypatch.setattr(setup_mod, "_install_claude_config", lambda **kwargs: installed.append("claude"))
    monkeypatch.setattr(setup_mod, "_install_codex_config", lambda **kwargs: installed.append("codex"))
    monkeypatch.setattr(setup_mod, "_install_gemini_config", lambda **kwargs: installed.append("gemini"))
    monkeypatch.setattr(setup_mod, "_install_droid_config", lambda **kwargs: installed.append("droid"))
    monkeypatch.setattr(setup_mod, "_install_opencode_config", lambda **kwargs: installed.append("opencode"))

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(
            [
                "--install-all-detected-clients",
                "--codex-config-path",
                str(codex_cfg),
                "--gemini-settings-path",
                str(gemini_cfg),
                "--droid-mcp-path",
                str(droid_cfg),
                "--opencode-config-path",
                str(opencode_cfg),
            ]
        )

    assert exc_info.value.code == 0
    assert installed == ["claude", "codex", "gemini", "droid", "opencode"]
    assert doctor_calls == [False]
    out = capsys.readouterr().out
    assert "Installed detected clients: claude, codex, gemini, droid, opencode" in out


def test_setup_install_all_detected_clients_honors_skip(monkeypatch, tmp_path, capsys) -> None:
    codex_cfg = tmp_path / "config.toml"
    gemini_cfg = tmp_path / "settings.json"
    droid_cfg = tmp_path / "mcp.json"
    opencode_cfg = tmp_path / "opencode.json"
    doctor_calls: list[bool] = []

    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: None)
    monkeypatch.setattr(setup_mod, "_run_doctor", lambda *, run_smoke: doctor_calls.append(run_smoke) or 0)
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: False)
    monkeypatch.setattr(setup_mod, "_detect_install_targets", lambda *, skip_clients=None: [])

    with pytest.raises(SystemExit) as exc_info:
        setup_mod.main(
            [
                "--install-all-detected-clients",
                "--skip-client",
                "claude",
                "--skip-client",
                "codex",
                "--skip-client",
                "gemini",
                "--skip-client",
                "droid",
                "--skip-client",
                "opencode",
                "--codex-config-path",
                str(codex_cfg),
                "--gemini-settings-path",
                str(gemini_cfg),
                "--droid-mcp-path",
                str(droid_cfg),
                "--opencode-config-path",
                str(opencode_cfg),
            ]
        )

    assert exc_info.value.code == 0
    assert doctor_calls == [False]
    out = capsys.readouterr().out
    assert "No supported clients detected for auto-install." in out
