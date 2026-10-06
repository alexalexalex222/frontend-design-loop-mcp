import asyncio
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from frontend_design_loop_core import mcp_code_server, utils


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["shell", "argv", "managed_shell", "managed_argv"])
async def test_commands_do_not_inherit_mcp_stdin(monkeypatch, mode):
    calls = []

    class Process:
        pid = 4321
        returncode = 0

        async def communicate(self):
            return b"ok", b""

        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setattr(utils, "_launch_process", spawn)
    monkeypatch.setattr(utils.os, "killpg", lambda *args: None, raising=False)
    monkeypatch.setattr(utils, "prepare_process_argv", lambda args, **kwargs: args)
    if mode == "shell":
        await utils.run_command("git status")
    elif mode == "argv":
        await utils.run_command_argv(["git", "status"])
    elif mode == "managed_shell":
        async with utils.managed_process("preview"):
            pass
    else:
        async with utils.managed_process_argv(["preview"]):
            pass
    assert calls[0][1].get("stdin") == asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["managed_shell", "managed_argv"])
async def test_windows_preview_cleanup_terminates_owned_host(monkeypatch, mode):
    calls = []

    class Process:
        pid = 4321
        returncode = None

        def kill(self):
            calls.append("kill-owned-host")
            self.returncode = -9

        async def wait(self):
            calls.append("reaped-owned-host")
            return self.returncode

    process = Process()

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(utils, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(utils, "prepare_process_argv", lambda args, **kwargs: args)
    monkeypatch.setattr(utils, "_launch_process", spawn)
    if mode == "managed_shell":
        async with utils.managed_process("preview"):
            pass
    else:
        async with utils.managed_process_argv(["preview"]):
            pass
    assert calls[0][1].get("stdin") == asyncio.subprocess.DEVNULL
    assert calls[1:] == ["kill-owned-host", "reaped-owned-host"]


@pytest.mark.asyncio
async def test_worktree_paths_are_passed_without_a_shell(tmp_path, monkeypatch):
    calls = []

    async def run_argv(args, **kwargs):
        calls.append((args, kwargs))
        return 0, "", ""

    async def forbid_shell(*args, **kwargs):
        pytest.fail("worktree paths must not be interpreted by a shell")

    monkeypatch.setattr(mcp_code_server, "run_command_argv", run_argv)
    monkeypatch.setattr(mcp_code_server, "run_command", forbid_shell)
    dest = tmp_path / "space & %USERPROFILE% 'quoted'"
    assert await mcp_code_server._make_worktree(repo_root=tmp_path, commit="HEAD", dest=dest)
    await mcp_code_server._remove_worktree(repo_root=tmp_path, dest=dest)
    assert calls[0][0][:2] == ["git", "-c"]
    assert calls[0][0][2].startswith("core.hooksPath=")
    assert calls[0][0][3:] == ["worktree", "add", "--detach", str(dest), "HEAD"]
    assert calls[1][0] == ["git", "worktree", "remove", "--force", str(dest)]


@pytest.mark.asyncio
async def test_real_worktree_with_spaces_and_shell_metacharacters(tmp_path):
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "hello.txt").write_text("hello\n")
    subprocess.run(["git", "add", "hello.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    dest = tmp_path / "worktree & %USERPROFILE% 'quoted'"
    try:
        assert await mcp_code_server._make_worktree(repo_root=repo, commit="HEAD", dest=dest)
        assert (dest / "hello.txt").read_text() == "hello\n"
    finally:
        await mcp_code_server._remove_worktree(repo_root=repo, dest=dest)
    assert not dest.exists()


@pytest.mark.asyncio
async def test_real_preview_stops_and_releases_its_port(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    args = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
    async with utils.managed_process_argv(args, cwd=tmp_path) as proc:
        async with httpx.AsyncClient(timeout=0.3, trust_env=False) as client:
            for _ in range(30):
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/")
                    assert response.status_code == 200
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.1)
            else:
                pytest.fail("preview never became ready")
    assert proc.returncode is not None
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.asyncio
async def test_eval_reports_worktree_failure_without_masking_it(tmp_path, monkeypatch):
    async def root(_):
        return tmp_path

    async def head(_):
        return "abc123"

    async def fail(**kwargs):
        return False

    async def remove(**kwargs):
        pass

    async def snapshot(_):
        return {"base_head": "abc123", "patch": "", "fingerprint": "fixture", "files": {}}

    monkeypatch.setattr(mcp_code_server, "source_snapshot", snapshot)
    monkeypatch.setattr(mcp_code_server, "_git_root", root)
    monkeypatch.setattr(mcp_code_server, "_git_head", head)
    monkeypatch.setattr(mcp_code_server, "_make_worktree", fail)
    monkeypatch.setattr(mcp_code_server, "_remove_worktree", remove)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(tmp_path / "out"))
    result = await mcp_code_server._frontend_design_loop_eval_impl(
        repo_path=str(tmp_path),
        patches=[{"path": "hello.txt", "patch": "@@ -1 +1 @@\n-a\n+b\n"}],
        test_command="git status",
        vision_provider="client",
    )
    assert result["error"] == "git worktree add failed"
    assert result["deterministic_passed"] is False
    assert result["vision_model"] == "client"
    assert (Path(result["run_dir"]) / "run_summary.json").exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group integration")
@pytest.mark.parametrize("mode", ["shell", "argv"])
async def test_timeout_terminates_children_holding_output_pipes(tmp_path, mode):
    pid_file = tmp_path / "child.pid"
    code = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"open({str(pid_file)!r},'w').write(str(p.pid)); time.sleep(60)"
    )
    args = [sys.executable, "-c", code]
    try:
        if mode == "shell":
            import shlex

            run = utils.run_command(shlex.join(args), timeout_ms=300)
        else:
            run = utils.run_command_argv(args, timeout_ms=300)
        rc, _, error = await asyncio.wait_for(run, timeout=3)
        assert rc == -1
        assert "timed out" in error
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
