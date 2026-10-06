"""Setup configuration safety and honest doctor regressions."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend_design_loop_mcp import setup as setup_mod


@pytest.fixture(autouse=True)
def toolkit(monkeypatch):
    monkeypatch.setattr(setup_mod, "_WORKFLOW", "toolkit")


def test_default_generic_config_is_toolkit_and_read_only(monkeypatch, capsys):
    monkeypatch.setattr(
        setup_mod,
        "_ensure_playwright_ready",
        lambda: pytest.fail("printed configs must not download"),
    )
    setup_mod.main(["--print-config"])
    data = json.loads(capsys.readouterr().out)
    payload = data["mcpServers"]["frontend-design-toolkit"]
    assert payload == {"command": setup_mod.sys.executable, "args": ["-m", "design_toolkit.server"]}


def test_automated_selection_preserves_legacy_flag(monkeypatch, capsys):
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: True)
    monkeypatch.setattr(setup_mod, "get_default_config_path", lambda: Path("/project/config.yaml"))
    setup_mod.main(["--workflow", "automated", "--print-config"])
    payload = json.loads(capsys.readouterr().out)["mcpServers"]["frontend-design-loop-mcp"]
    assert payload["args"] == ["-m", "frontend_design_loop_mcp.mcp_server"]
    assert payload["env"]["FRONTEND_DESIGN_LOOP_CONFIG_PATH"] == str(Path("/project/config.yaml"))


def test_codex_windows_paths_and_quoted_name_round_trip(tmp_path, monkeypatch):
    payload = {
        "command": "C:\\Program Files\\Python\\python.exe",
        "args": ["-m", "design_toolkit.server"],
        "env": {"SITE_PATH": 'C:\\Users\\Alex\\new\\a"b'},
    }
    monkeypatch.setattr(setup_mod, "_build_claude_payload", lambda: payload)
    name = 'my.tools"quoted'
    config = tmp_path / "config.toml"
    config.write_text('model = "unchanged"\n[features]\nother = true\n')
    setup_mod._install_codex_config(name, config)
    setup_mod._install_codex_config(name, config)
    parsed = setup_mod.tomllib.loads(config.read_text())
    assert parsed["mcp_servers"][name]["command"] == payload["command"]
    assert parsed["mcp_servers"][name]["env"] == payload["env"]
    assert parsed["model"] == "unchanged" and parsed["features"]["other"] is True
    assert config.read_text().count("# BEGIN") == 1


@pytest.mark.parametrize(
    "existing",
    ['[mcp_servers."same"]\ncommand="user"\n', 'mcp_servers = {same = {command="user"}}\n'],
)
def test_codex_unmanaged_collision_preserves_bytes(tmp_path, existing):
    config = tmp_path / "config.toml"
    config.write_text(existing)
    with pytest.raises(SystemExit, match="unmanaged"):
        setup_mod._install_codex_config("same", config)
    assert config.read_text() == existing


def test_invalid_toml_never_replaced(tmp_path):
    config = tmp_path / "config.toml"
    original = 'model = "unterminated\n'
    config.write_text(original)
    with pytest.raises(ValueError):
        setup_mod._install_codex_config("new", config)
    assert config.read_text() == original


def test_failed_atomic_replace_preserves_original(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('model="old"\n')
    monkeypatch.setattr(
        setup_mod.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("busy"))
    )
    with pytest.raises(OSError, match="busy"):
        setup_mod._install_codex_config("new", config)
    assert config.read_text() == 'model="old"\n'
    assert list(tmp_path.iterdir()) == [config]


@pytest.mark.parametrize(
    "client,field", [("gemini", "mcpServers"), ("droid", "mcpServers"), ("opencode", "mcp")]
)
def test_json_install_preserves_unrelated_and_refuses_collision(tmp_path, client, field):
    path = tmp_path / "settings.json"
    data = {"unrelated": {"model": "user-selected"}, field: {"other": {"command": "custom"}}}
    path.write_text(json.dumps(data))
    install = getattr(setup_mod, f"_install_{client}_config")
    install("ours", path)
    parsed = json.loads(path.read_text())
    assert parsed["unrelated"] == data["unrelated"]
    assert parsed[field]["other"] == data[field]["other"]
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="unmanaged"):
        install("other", path)
    assert path.read_bytes() == before


def test_opencode_jsonc_preserves_semantic_settings(tmp_path):
    path = tmp_path / "opencode.jsonc"
    path.write_text('{// comment\n"model":"keep", "url":"https://example.com",}\n')
    setup_mod._install_opencode_config("new", path)
    parsed = json.loads(path.read_text())
    assert parsed["model"] == "keep" and parsed["url"] == "https://example.com"
    assert parsed["mcp"]["new"]["command"] == setup_mod._payload_command_argv()


def test_print_multiple_configs_never_installs(monkeypatch, capsys):
    monkeypatch.setattr(
        setup_mod, "_ensure_playwright_ready", lambda: pytest.fail("must be read only")
    )
    setup_mod.main(["--print-codex-config", "--print-opencode-config"])
    text = capsys.readouterr().out
    assert "tool_timeout_sec = 900" in text and '"type": "local"' in text


def test_explicit_install_uses_selected_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_mod, "_ensure_playwright_ready", lambda: None)
    monkeypatch.setattr(setup_mod, "_run_doctor", lambda **kwargs: 0)
    path = tmp_path / "config.toml"
    with pytest.raises(SystemExit) as error:
        setup_mod.main(["--install-codex", "--codex-config-path", str(path)])
    assert error.value.code == 0
    assert (
        setup_mod.tomllib.loads(path.read_text())["mcp_servers"]["frontend-design-toolkit"]["args"][
            -1
        ]
        == "design_toolkit.server"
    )


def test_doctor_no_cli_is_optional_and_no_auth_or_inference(monkeypatch, capsys):
    monkeypatch.setattr(setup_mod, "_check_playwright_ready", lambda: (True, "ready"))
    monkeypatch.setattr(setup_mod.shutil, "which", lambda name, **kwargs: None)
    monkeypatch.setattr(
        setup_mod.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not probe")
    )
    assert setup_mod._run_doctor(run_smoke=False) == 0
    assert '"live_inference": "not_run"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "cli,response,status",
    [
        (
            "claude",
            SimpleNamespace(
                returncode=0,
                stdout='{"loggedIn":true,"authMethod":"claude.ai","email":"private"}',
                stderr="",
            ),
            "authenticated",
        ),
        (
            "codex",
            SimpleNamespace(returncode=0, stdout="", stderr="Logged in using ChatGPT"),
            "authenticated",
        ),
        (
            "codex",
            SimpleNamespace(returncode=1, stdout="", stderr="Not logged in"),
            "unauthenticated",
        ),
        (
            "opencode",
            SimpleNamespace(returncode=0, stdout="provider token private", stderr=""),
            "unknown",
        ),
    ],
)
def test_auth_probes_classify_without_echoing_accounts(monkeypatch, cli, response, status):
    monkeypatch.setattr(setup_mod.shutil, "which", lambda name, **kwargs: setup_mod.sys.executable)
    calls = []
    monkeypatch.setattr(
        setup_mod.subprocess, "run", lambda command, **kw: calls.append((command, kw)) or response
    )
    result = setup_mod._native_auth_status(cli, probe=True)
    assert result["authentication"] == status
    assert result["live_inference"] == "not_run"
    assert "private" not in json.dumps(result)
    assert calls[0][1]["timeout"] == 10


def test_auth_probe_unrecognized_output_stays_unknown(monkeypatch):
    monkeypatch.setattr(setup_mod.shutil, "which", lambda name, **kwargs: setup_mod.sys.executable)
    monkeypatch.setattr(
        setup_mod.subprocess,
        "run",
        lambda *args, **kw: SimpleNamespace(returncode=0, stdout="changed format", stderr=""),
    )
    assert setup_mod._native_auth_status("claude", probe=True)["authentication"] == "unknown"


def test_check_missing_chromium_fails(monkeypatch):
    monkeypatch.setattr(setup_mod, "_check_playwright_ready", lambda: (False, "missing"))
    with pytest.raises(SystemExit) as error:
        setup_mod.main(["--check"])
    assert error.value.code == 1


def test_managed_json_entry_preserves_user_environment_and_options(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_mod, "_WORKFLOW", "automated")
    monkeypatch.setattr(setup_mod, "is_repo_checkout", lambda: True)
    path = tmp_path / "settings.json"
    payload = setup_mod._build_claude_payload()
    payload["env"]["CUSTOM_OPTION"] = "keep"
    payload["timeout"] = 123
    path.write_text(json.dumps({"mcpServers": {"ours": payload}}))
    setup_mod._install_gemini_config("ours", path)
    entry = json.loads(path.read_text())["mcpServers"]["ours"]
    assert entry["env"]["CUSTOM_OPTION"] == "keep" and entry["timeout"] == 123


def test_claude_install_passes_json_through_prepared_argv(monkeypatch):
    monkeypatch.setattr(setup_mod.shutil, "which", lambda *args, **kwargs: "claude.cmd")
    prepared = []
    launches = []

    def prepare(argv):
        prepared.append(argv)
        return ["node.exe", "claude-cli.js", *argv[1:]]

    monkeypatch.setattr(setup_mod, "prepare_process_argv", prepare)
    monkeypatch.setattr(setup_mod.subprocess, "run", lambda argv, **kwargs: launches.append((argv, kwargs)))
    setup_mod._install_claude_config(scope="user", server_name="tool with spaces")
    assert prepared[0][0] == "claude"
    assert launches[0][0] == ["node.exe", "claude-cli.js", *prepared[0][1:]]
    assert json.loads(launches[0][0][-1]) == setup_mod._build_claude_payload()
    assert launches[0][1]["check"] is True


def test_auth_probe_uses_prepared_argv_and_detached_stdin(monkeypatch):
    monkeypatch.setattr(setup_mod.shutil, "which", lambda *args, **kwargs: "found")
    calls = []
    monkeypatch.setattr(setup_mod, "prepare_process_argv", lambda argv: ["node.exe", "claude-cli.js", *argv[1:]])
    monkeypatch.setattr(setup_mod.subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)) or SimpleNamespace(returncode=0, stdout='{"loggedIn":true}', stderr=""))
    result = setup_mod._native_auth_status("claude", probe=True)
    assert result["authentication"] == "authenticated"
    assert calls[0][0] == ["node.exe", "claude-cli.js", "auth", "status"]
    assert calls[0][1]["stdin"] == setup_mod.subprocess.DEVNULL
