"""Windows parsing plus executable argv/shim regressions (no model calls)."""

import asyncio
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from design_toolkit.tools import gates
from frontend_design_loop_core import cli_paths, command_runtime, mcp_code_server, utils
from frontend_design_loop_core.config import load_config
from frontend_design_loop_core.providers._cli_base import NativeCLIError
from frontend_design_loop_core.providers.codex_cli import CodexCLIProvider

# Fixture from npm/cmd-shim's generated template, including its batch-only tail.
NODE_SHIM = r"""@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0

IF EXIST "%dp0%\node.exe" (
  SET "_prog=%dp0%\node.exe"
) ELSE (
  SET "_prog=node"
)

endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & set PATHEXT=%PATHEXT:;.JS;=;% & "%_prog%"  "%dp0%\node_modules\fixture\cli.js" %*
"""

NPM_SHIM = r""":: Created by npm, please don't edit manually.
@ECHO OFF

SETLOCAL

SET "NODE_EXE=%~dp0\node.exe"
IF NOT EXIST "%NODE_EXE%" (
  SET "NODE_EXE=node"
)

SET "NPM_PREFIX_JS=%~dp0\node_modules\npm\bin\npm-prefix.js"
SET "NPM_CLI_JS=%~dp0\node_modules\npm\bin\npm-cli.js"
FOR /F "delims=" %%F IN ('CALL "%NODE_EXE%" "%NPM_PREFIX_JS%"') DO (
  SET "NPM_PREFIX_NPM_CLI_JS=%%F\node_modules\npm\bin\npm-cli.js"
)
IF EXIST "%NPM_PREFIX_NPM_CLI_JS%" (
  SET "NPM_CLI_JS=%NPM_PREFIX_NPM_CLI_JS%"
)
"%NODE_EXE%" "%NPM_CLI_JS%" %*
"""

LITERAL_ARGS = [
    "",
    "space & %USERPROFILE% !literal! ^caret",
    "site&other",
    "a|b;c>d<e",
    'embedded"quote',
    "'single quotes'",
    r"C:\My Site\out" + "\\",
    r"unquoted\backslashes",
    r"backslash\"quote",
    "$(no-expansion)",
    "`no-expansion`",
    "✓ Unicode",
    "{literal}",
]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (r"C:\Python314\python.exe -m pytest", [r"C:\Python314\python.exe", "-m", "pytest"]),
        (
            r'"C:\Program Files\node.exe" --output="C:\My Site\out"',
            [r"C:\Program Files\node.exe", r"--output=C:\My Site\out"],
        ),
        (r'cli "a b c" d e', ["cli", "a b c", "d", "e"]),
        (r'cli "ab\"c" "\\" d', ["cli", 'ab"c', "\\", "d"]),
        (r'cli a\\\b d"e f"g h', ["cli", r"a\\\b", "de fg", "h"]),
        (r"cli a\\\"b c d", ["cli", r"a\"b", "c", "d"]),
        (r'cli a\\\\"b c" d e', ["cli", r"a\\b c", "d", "e"]),
        (r'cli a"b"" c d', ["cli", 'ab" c d']),
        ("cli 'a b'", ["cli", "'a", "b'"]),
        ('cli "" --name=""', ["cli", "", "--name="]),
    ],
)
def test_windows_parser_documented_examples(line, expected):
    assert command_runtime.parse_command_line(line, windows=True) == expected


def test_windows_parser_list2cmdline_roundtrips():
    randomizer = random.Random(601)
    alphabet = 'abc \\"\t%&|<>!^✓'
    vectors = [LITERAL_ARGS]
    for _ in range(300):
        vectors.append(
            [
                "".join(randomizer.choice(alphabet) for _ in range(randomizer.randrange(25)))
                for _ in range(8)
            ]
        )
    for arguments in vectors:
        argv = ["tool.exe", *arguments]
        assert (
            command_runtime.parse_command_line(subprocess.list2cmdline(argv), windows=True) == argv
        )


def test_parser_keeps_posix_behavior_and_documented_unclosed_quotes():
    assert command_runtime.parse_command_line(r"cli 'a b' c\ d", windows=False) == [
        "cli",
        "a b",
        "c d",
    ]
    assert command_runtime.parse_command_line('cli "broken', windows=True) == ["cli", "broken"]
    with pytest.raises(ValueError):
        command_runtime.parse_command_line('cli "broken', windows=False)


def test_both_frontends_share_windows_parser_and_keep_array_literals(monkeypatch):
    monkeypatch.setattr(gates, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(mcp_code_server, "os", SimpleNamespace(name="nt"))
    line = r'"C:\Program Files\node.exe" script.js --output="C:\My Site\out" ""'
    expected = [r"C:\Program Files\node.exe", "script.js", r"--output=C:\My Site\out", ""]
    assert gates.prepare_command(line).argv == expected
    assert (
        mcp_code_server._prepare_user_command(line, label="test", unsafe_shell=False).argv
        == expected
    )
    for unsafe in (False, True):
        args = ["tool.exe", *LITERAL_ARGS]
        automated = mcp_code_server._prepare_user_command(args, label="test", unsafe_shell=unsafe)
        toolkit = gates.prepare_command(args, unsafe_shell=unsafe)
        assert automated.argv == toolkit.argv == args
        assert not automated.shell_mode and not toolkit.shell_mode


def test_automated_inline_code_policy_still_applies_to_arrays(monkeypatch):
    monkeypatch.setattr(mcp_code_server, "os", SimpleNamespace(name="nt"))
    for executable in (r"C:\Python314\python.exe", r"C:\bin\node.exe"):
        args = [executable, "-c" if "python" in executable else "-e", "print(1)"]
        with pytest.raises(ValueError, match="unsafe_shell_commands=true"):
            mcp_code_server._prepare_user_command(args, label="test", unsafe_shell=False)
        prepared = mcp_code_server._prepare_user_command(args, label="test", unsafe_shell=True)
        assert prepared.argv == args and not prepared.shell_mode
    with pytest.raises(ValueError, match="unsafe_shell_commands=true"):
        mcp_code_server._prepare_user_command(
            "npm test && npm build", label="test", unsafe_shell=False
        )
    assert mcp_code_server._prepare_user_command(
        "npm test && npm build", label="test", unsafe_shell=True
    ).shell_mode
    with pytest.raises(ValueError, match="unsafe_shell_commands=true"):
        mcp_code_server._prepare_user_command(
            [r"C:\Windows\System32\cmd.exe", "/c", "echo marker"], label="test", unsafe_shell=False
        )


def test_command_templates_and_mcp_array_schema():
    args = ["node", "preview.js", "--port={port}", '{"literal": true}', "space & %literal%"]
    assert mcp_code_server._format_command_template(args, port=4321) == [
        "node",
        "preview.js",
        "--port=4321",
        '{"literal": true}',
        "space & %literal%",
    ]
    assert mcp_code_server._format_command_template(
        "npm run dev -- --port {port}", port=4321
    ).endswith("4321")
    for name in (
        "frontend_design_loop_solve",
        "frontend_design_loop_eval",
        "frontend_design_loop_design",
    ):
        properties = mcp_code_server.mcp._tool_manager._tools[name].parameters["properties"]
        for key in ("test_command", "lint_command", "preview_command", "worktree_setup_command"):
            assert any(option.get("type") == "array" for option in properties[key]["anyOf"])


def test_windows_resolves_child_path_and_pathext(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    (parent / "fixture.exe").touch()
    (child / "fixture.cmd").write_text("unsupported")
    monkeypatch.setenv("PATH", str(parent))
    monkeypatch.setenv("PATHEXT", ".EXE")
    env = {"Path": str(child), "Pathext": ".CMD"}
    assert command_runtime.find_executable("fixture", env=env, windows=True) == str(
        child / "fixture.cmd"
    )
    assert (
        command_runtime.find_executable(
            "fixture", env={"PATH": str(child), "PATHEXT": ".EXE"}, windows=True
        )
        is None
    )
    assert command_runtime.find_executable("fixture", env={}, windows=True) is None
    (child / "fixture.exe").touch()
    assert command_runtime.prepare_process_argv(
        ["fixture", *LITERAL_ARGS], env={"PATH": str(child)}, windows=True
    ) == [str(child / "fixture.exe"), *LITERAL_ARGS]
    assert command_runtime.find_executable(
        "fixture", cwd=tmp_path, env={"PATH": "child"}, windows=True
    ) == str(child / "fixture.exe")


def test_provider_resolver_uses_supplied_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_CODEX_CLI", str(tmp_path / "missing-parent-cli"))
    override = tmp_path / ("chosen.exe" if os.name == "nt" else "chosen")
    override.write_text("fixture")
    override.chmod(0o755)
    assert cli_paths.resolve_native_cli(
        "codex", env={"FRONTEND_DESIGN_LOOP_CODEX_CLI": str(override), "PATH": ""}
    ) == str(override)


@pytest.mark.asyncio
async def test_provider_passes_child_environment_to_resolver(tmp_path, monkeypatch):
    from frontend_design_loop_core.providers import _cli_base

    seen = []
    environment = {"PATH": str(tmp_path)}

    def resolve(name, **kwargs):
        seen.append((name, kwargs))
        return "fixture.exe"

    async def run(args, cwd, **kwargs):
        assert args == ["fixture.exe", "--model", "unchanged-model"]
        assert kwargs["env"] is environment
        return 0, '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}', ""

    monkeypatch.setattr(_cli_base, "resolve_native_cli", resolve)
    monkeypatch.setattr(_cli_base, "run_process_argv", run)
    provider = CodexCLIProvider(load_config())
    await provider._probe(["fixture", "--model", "unchanged-model"], env=environment, cwd=tmp_path)
    await provider._run_cli(
        args=["fixture", "--model", "unchanged-model"], env=environment, cwd=tmp_path, timeout_s=1
    )
    assert seen == [("fixture", {"env": environment, "cwd": tmp_path})] * 2


@pytest.mark.asyncio
async def test_unsupported_batch_fails_before_process_creation(tmp_path, monkeypatch):
    shim = tmp_path / "fixture.cmd"
    shim.write_text("@echo off\nnode script.js %*\necho side-effect\n")

    async def forbid(*args, **kwargs):
        pytest.fail("unsupported batch wrapper was launched")

    monkeypatch.setattr(utils.asyncio, "create_subprocess_exec", forbid)
    real_prepare = command_runtime.prepare_process_argv
    monkeypatch.setattr(
        utils,
        "prepare_process_argv",
        lambda args, **kwargs: real_prepare(
            args, windows=True, **{k: v for k, v in kwargs.items() if k != "windows"}
        ),
    )
    rc, _, error = await utils.run_command_argv([str(shim), *LITERAL_ARGS])
    assert rc == -1 and "Unsupported Windows batch shim" in error
    with pytest.raises(ValueError, match="Unsupported Windows batch shim"):
        async with utils.managed_process_argv([str(shim)]):
            pass
    provider = CodexCLIProvider(load_config())
    with pytest.raises(NativeCLIError, match="Unsupported Windows batch shim"):
        await provider._run_cli(args=[str(shim)], cwd=tmp_path, env=dict(os.environ), timeout_s=1)


@pytest.fixture
def node_install(tmp_path, monkeypatch):
    node = command_runtime.find_executable("node", native_only=True)
    if node is None:
        pytest.skip("Node native runtime is unavailable")
    install = tmp_path / "node installation & %literal%"
    install.mkdir()
    native = install / "node.exe"
    if os.name == "nt":
        shutil.copy2(node, native)
    else:
        native.symlink_to(node)
    script = install / "node_modules" / "fixture" / "cli.js"
    script.parent.mkdir(parents=True)
    script.write_text(
        "let input=''; process.stdin.setEncoding('utf8'); process.stdin.on('data', c => input += c); process.stdin.on('end', () => console.log(JSON.stringify({argv:process.argv.slice(2),input,cwd:process.cwd(),marker:process.env.FIXTURE_MARKER})));",
        encoding="utf-8",
    )
    shim = install / "fixture.cmd"
    shim.write_text(NODE_SHIM, encoding="utf-8")
    # Exercise Windows preparation on macOS too, retaining real native process
    # execution and cleanup. On Windows this uses actual CreateProcess/taskkill.
    real_prepare = command_runtime.prepare_process_argv
    monkeypatch.setattr(
        utils,
        "prepare_process_argv",
        lambda args, **kwargs: real_prepare(
            args, windows=True, **{k: v for k, v in kwargs.items() if k != "windows"}
        ),
    )
    return install, script, shim


@pytest.mark.asyncio
async def test_real_node_shim_preserves_argv_stdin_environment(node_install, tmp_path):
    install, _, _ = node_install
    env = {
        **os.environ,
        "PATH": str(install),
        "PATHEXT": ".EXE;.CMD",
        "FIXTURE_MARKER": "child environment",
    }
    rc, output, error = await utils.run_process_argv(
        ["fixture", *LITERAL_ARGS],
        cwd=tmp_path,
        env=env,
        input_text='stdin ✓ %literal% & "quote"\n',
    )
    assert rc == 0, error
    assert json.loads(output) == {
        "argv": LITERAL_ARGS,
        "input": 'stdin ✓ %literal% & "quote"\n',
        "cwd": str(tmp_path.resolve()),
        "marker": "child environment",
    }
    # Toolkit gate uses the same preparation and runtime, including empty args.
    result = await gates.run_gates(
        repo_root=tmp_path, test_command=[str(install / "fixture.cmd"), *LITERAL_ARGS]
    )
    assert result.test_status == "passed"
    assert json.loads(result.test_stdout)["argv"] == LITERAL_ARGS


def test_generated_shim_flags_and_custom_changes(node_install):
    install, _, shim = node_install
    original = shim.read_text()
    shim.write_text(original.replace('"%_prog%"  ', '"%_prog%" --no-warnings '))
    prepared = command_runtime.prepare_process_argv([str(shim), "literal%&"], windows=True)
    assert prepared[1] == "--no-warnings" and prepared[-1] == "literal%&"
    # A matching target alone is insufficient: don't bypass custom shim effects.
    shim.write_text(original + "\necho custom-side-effect\n")
    with pytest.raises(ValueError, match="Unsupported Windows batch shim"):
        command_runtime.prepare_process_argv([str(shim)], windows=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["npm", "npx"])
async def test_real_npm_prefix_dispatch_keeps_selected_cli(node_install, tmp_path, name):
    install, script, _ = node_install
    npm_bin = install / "node_modules" / "npm" / "bin"
    npm_bin.mkdir(parents=True)
    local_cli = npm_bin / f"{name}-cli.js"
    local_cli.write_text("throw new Error('wrong local version');")
    selected = tmp_path / "prefix with spaces & %literal%"
    selected_cli = selected / "node_modules" / "npm" / "bin" / f"{name}-cli.js"
    selected_cli.parent.mkdir(parents=True)
    shutil.copy2(script, selected_cli)
    (npm_bin / "npm-prefix.js").write_text(f"console.log({json.dumps(str(selected))});")
    shim = install / f"{name}.cmd"
    text = (
        NPM_SHIM
        if name == "npm"
        else NPM_SHIM.replace("NPM_CLI_JS", "NPX_CLI_JS").replace("npm-cli.js", "npx-cli.js")
    )
    shim.write_text(text)
    env = {**os.environ, "PATH": str(install), "PATHEXT": ".EXE;.CMD"}
    rc, out, err = await utils.run_process_argv(
        [name, *LITERAL_ARGS], cwd=tmp_path, env=env, input_text="prefix stdin", timeout_s=10
    )
    assert rc == 0, err
    assert json.loads(out)["argv"] == LITERAL_ARGS
    assert json.loads(out)["input"] == "prefix stdin"


@pytest.mark.asyncio
async def test_npm_empty_prefix_keeps_local_cli(node_install, tmp_path):
    install, script, _ = node_install
    local_bin = install / "node_modules" / "npm" / "bin"
    local_bin.mkdir(parents=True)
    shutil.copy2(script, local_bin / "npm-cli.js")
    (local_bin / "npm-prefix.js").write_text("process.exit(1);")
    cwd_bin = tmp_path / "node_modules" / "npm" / "bin"
    cwd_bin.mkdir(parents=True)
    (cwd_bin / "npm-cli.js").write_text("throw new Error('wrong cwd CLI');")
    shim = install / "npm.cmd"
    shim.write_text(NPM_SHIM)
    rc, out, err = await utils.run_process_argv([str(shim), "local"], cwd=tmp_path)
    assert rc == 0, err
    assert json.loads(out)["argv"] == ["local"]


@pytest.mark.asyncio
async def test_real_shim_timeout_and_cancellation(node_install, tmp_path):
    _, script, shim = node_install
    script.write_text("console.log('started'); setInterval(() => {}, 1000);")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(utils.run_process_argv([str(shim)], timeout_s=0.2), timeout=10)
    task = asyncio.create_task(utils.run_process_argv([str(shim)], timeout_s=30))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    async with utils.managed_process_argv([str(shim)], cwd=tmp_path) as process:
        assert await asyncio.wait_for(process.stdout.readline(), timeout=10) == b"started\n"
    assert process.returncode is not None


@pytest.mark.asyncio
async def test_real_native_python_argument_roundtrip(tmp_path):
    script = tmp_path / "roundtrip.py"
    script.write_text("import json,sys\nprint(json.dumps(sys.argv[1:]))\n")
    # Parsed Windows input then actual native argv serialization/execution.
    argv = [sys.executable, str(script), *LITERAL_ARGS]
    parsed = command_runtime.parse_command_line(subprocess.list2cmdline(argv), windows=True)
    assert parsed == argv
    rc, out, err = await utils.run_command_argv(parsed, cwd=tmp_path)
    assert rc == 0, err
    assert json.loads(out) == LITERAL_ARGS


@pytest.mark.asyncio
async def test_real_npm_version_and_package_test(node_install, tmp_path):
    install, _, _ = node_install
    npm_command = shutil.which("npm")
    if npm_command is None:
        pytest.skip("npm is unavailable")
    npm_path = Path(npm_command)
    npm_package = (
        npm_path.parent / "node_modules" / "npm"
        if os.name == "nt"
        else npm_path.resolve().parent.parent
    )
    if not (npm_package / "bin" / "npm-cli.js").is_file():
        pytest.skip("npm package cannot be located without installation")
    package = install / "node_modules" / "npm"
    if os.name == "nt":
        shutil.copytree(npm_package, package)
    else:
        package.symlink_to(npm_package, target_is_directory=True)
        (install / "node").symlink_to(install / "node.exe")
    # The fixture launcher is a generated npm cmd-shim, calling the real npm.
    (install / "npm.cmd").write_text(NODE_SHIM.replace(r"fixture\cli.js", r"npm\bin\npm-cli.js"))
    project = tmp_path / "project & %literal%"
    project.mkdir()
    (project / "package.json").write_text(json.dumps({"scripts": {"test": "node record.js"}}))
    (project / "record.js").write_text("console.log(JSON.stringify(process.argv.slice(2)));")
    empty_config = tmp_path / "empty.npmrc"
    empty_config.write_text("")
    global_config = tmp_path / "global.npmrc"
    global_config.write_text("")
    env = {
        **os.environ,
        "PATH": str(install),
        "PATHEXT": ".EXE;.CMD",
        "NPM_CONFIG_USERCONFIG": str(empty_config),
        "NPM_CONFIG_GLOBALCONFIG": str(global_config),
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        "NPM_CONFIG_CACHE": str(tmp_path / "npm-cache"),
    }
    if os.name != "nt":
        env["NPM_CONFIG_SCRIPT_SHELL"] = "/bin/sh"
    rc, out, err = await utils.run_process_argv(["npm", "--version"], cwd=project, env=env)
    assert rc == 0, err
    assert out.strip() == json.loads((npm_package / "package.json").read_text())["version"]
    # npm's package script intentionally uses its own shell. Verify ordinary
    # package arguments here; hostile literal argv is tested without that shell.
    rc, out, err = await utils.run_process_argv(
        ["npm", "test", "--", "literal", "backslash\\path"], cwd=project, env=env
    )
    assert rc == 0, err
    assert json.loads(out.splitlines()[-1]) == ["literal", "backslash\\path"]


@pytest.mark.asyncio
async def test_real_generated_native_target_shim(node_install):
    install, script, _ = node_install
    shim = install / "native.cmd"
    shim.write_text(NODE_SHIM.split("IF EXIST")[0] + '"%dp0%\\node.exe"   %*\n')
    rc, out, err = await utils.run_process_argv([str(shim), str(script), *LITERAL_ARGS])
    assert rc == 0, err
    assert json.loads(out)["argv"] == LITERAL_ARGS


@pytest.mark.asyncio
async def test_real_legacy_npm_shim_and_child_path_node_fallback(
    node_install, tmp_path, monkeypatch
):
    install, _, shim = node_install
    legacy = NODE_SHIM.replace(
        '  SET "_prog=node"\n)',
        '  SET "_prog=node"\n  SET PATHEXT=%PATHEXT:;.JS;=;%\n)',
    ).replace('set PATHEXT=%PATHEXT:;.JS;=;% & "%_prog%"', '"%_prog%"')
    shim.write_text(legacy)
    child_bin = tmp_path / "child node runtime"
    child_bin.mkdir()
    (install / "node.exe").rename(child_bin / "node.exe")
    parent_bin = tmp_path / "parent node runtime"
    parent_bin.mkdir()
    (parent_bin / "node.exe").write_text("wrong runtime")
    monkeypatch.setenv("PATH", str(parent_bin))
    env = {**os.environ, "PATH": str(install) + ";" + str(child_bin), "PATHEXT": ".EXE;.CMD"}
    rc, out, err = await utils.run_process_argv(["fixture", *LITERAL_ARGS], env=env)
    assert rc == 0, err
    assert json.loads(out)["argv"] == LITERAL_ARGS
    with pytest.raises(FileNotFoundError, match="requires node.exe"):
        command_runtime.prepare_process_argv([str(shim)], env={"PATH": str(install)}, windows=True)


def test_windows_executable_name_has_distinct_crt_rules():
    line = r'"C:\Program Files\nodejs\"node.exe --version'
    assert command_runtime.parse_command_line(line, windows=True) == [r"C:\Program Files\nodejs\node.exe", "--version"]
    assert command_runtime.parse_command_line(r'"--title=\"quoted\""', windows=True, first_arg_is_executable=False) == ['--title="quoted"']
