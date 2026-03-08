import subprocess
from pathlib import Path

import anyio
import pytest

from frontend_design_loop_core import mcp_code_server


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_eval_patch_offline_writes_summaries(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(
        *,
        images,
        goal,
        threshold,
        provider_name,
        model,
        min_confidence,
        kind,
    ):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 10.0},
        }

    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello world\n"}],
            test_command="true",
            vision_mode="auto",
            vision_provider="anthropic_vertex",
        )

    result = anyio.run(run)
    assert result["passes_all_gates"] is True
    run_dir = Path(result["run_dir"])
    cand_dir = Path(result["candidate_dir"])
    assert (run_dir / "run_summary.json").exists()
    assert (cand_dir / "candidate_summary.json").exists()


def test_eval_patch_uses_default_out_dir_helper_without_env(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    default_out = tmp_path / "state-out"
    monkeypatch.delenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", raising=False)
    monkeypatch.setattr(
        mcp_code_server,
        "get_default_out_dir",
        lambda subdir=None: default_out / subdir if subdir else default_out,
    )

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(
        *,
        images,
        goal,
        threshold,
        provider_name,
        model,
        min_confidence,
        kind,
    ):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 10.0},
        }

    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello there\n"}],
            test_command="true",
            vision_mode="auto",
        )

    result = anyio.run(run)
    assert Path(result["run_dir"]).is_relative_to(default_out / "mcp-eval-runs")


def test_eval_patch_client_vision_is_pending_not_passed(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello pending\n"}],
            test_command="true",
            vision_mode="auto",
            vision_provider="client",
        )

    result = anyio.run(run)
    assert result["deterministic_passed"] is True
    assert result["vision_pending"] is True
    assert result["vision_scored"] is False
    assert result["final_pass"] is None
    assert result["passes_all_gates"] is False
    assert result["vision_ok"] is None


def test_eval_patch_rejects_shell_commands_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello shell\n"}],
            test_command="printf ok >/dev/null",
        )

    with pytest.raises(ValueError, match="unsafe_shell_commands=true"):
        anyio.run(run)


def test_eval_patch_allows_shell_commands_with_opt_in(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello shell ok\n"}],
            test_command="printf ok >/dev/null",
            vision_provider="client",
            unsafe_shell_commands=True,
        )

    result = anyio.run(run)
    assert result["deterministic_passed"] is True
    assert result["unsafe_shell_commands"] is True


def test_prepare_user_command_rejects_inline_interpreter_exec_when_shell_disabled() -> None:
    with pytest.raises(ValueError, match="unsafe_shell_commands=true"):
        mcp_code_server._prepare_user_command(
            'bash -c "echo hi"',
            label="test_command",
            unsafe_shell=False,
        )
    with pytest.raises(ValueError, match="unsafe_shell_commands=true"):
        mcp_code_server._prepare_user_command(
            'python -c "print(1)"',
            label="test_command",
            unsafe_shell=False,
        )
    prepared = mcp_code_server._prepare_user_command(
        "python -m http.server 3000",
        label="preview_command",
        unsafe_shell=False,
    )
    assert prepared is not None
    assert prepared.argv == ["python", "-m", "http.server", "3000"]


def test_write_gate_logs_redacts_common_secret_shapes(tmp_path: Path) -> None:
    mcp_code_server._write_gate_logs(
        cand_dir=tmp_path,
        test_out='API_KEY=super-secret\nurl=https://token@example.com/repo.git\n',
        test_err="Authorization: Bearer abc123\n",
        lint_out='{"client_secret":"top-secret"}\n',
        lint_err="Cookie: session=xyz\n",
    )
    combined = "\n".join(
        (tmp_path / name).read_text(encoding="utf-8")
        for name in ("test_stdout.txt", "test_stderr.txt", "lint_stdout.txt", "lint_stderr.txt")
    )
    assert "super-secret" not in combined
    assert "abc123" not in combined
    assert "top-secret" not in combined
    assert "session=xyz" not in combined
    assert "[REDACTED]" in combined


def test_eval_patch_rejects_external_preview_url_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello preview\n"}],
            test_command="true",
            vision_mode="on",
            vision_provider="client",
            preview_command="python3 -m http.server {port}",
            preview_url="http://example.com:{port}/",
        )

    with pytest.raises(ValueError, match="preview_url must point to localhost"):
        anyio.run(run)


def test_eval_patch_rejects_mismatched_local_preview_port_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello preview\n"}],
            test_command="true",
            vision_mode="on",
            vision_provider="client",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:9999/",
        )

    with pytest.raises(ValueError, match="launched preview port"):
        anyio.run(run)


def test_eval_patch_proxy_structural_vision_is_not_treated_as_full_scoring(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(
        *,
        images,
        goal,
        threshold,
        provider_name,
        model,
        min_confidence,
        kind,
    ):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 9.0},
        }

    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello proxy\n"}],
            test_command="true",
            vision_mode="auto",
            vision_provider="kilo_cli",
            vision_model="kilo/minimax/minimax-m2.5:free",
        )

    result = anyio.run(run)
    assert result["deterministic_passed"] is True
    assert result["vision_review_mode"] == "proxy_structural"
    assert result["vision_scored"] is False
    assert result["vision_pending"] is True
    assert result["final_pass"] is None
    assert result["vision_ok"] is True
    assert result["vision_ok_reason"] == "proxy_structural_only"
    assert result["vision_score"] is None


def test_wait_for_http_allows_same_origin_redirect(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
            self.status_code = status_code
            self.headers = headers or {}

    responses = {
        "http://127.0.0.1:3000/": FakeResponse(302, {"location": "/index.html"}),
        "http://127.0.0.1:3000/index.html": FakeResponse(200),
    }

    async def fake_get(self, url, *args, **kwargs):
        _ = (self, args, kwargs)
        return responses[url]

    monkeypatch.setattr(mcp_code_server.httpx.AsyncClient, "get", fake_get)
    ok, err = anyio.run(lambda: mcp_code_server._wait_for_http("http://127.0.0.1:3000/", timeout_s=0.5))
    assert ok is True
    assert err == ""


def test_wait_for_http_rejects_cross_origin_redirect(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
            self.status_code = status_code
            self.headers = headers or {}

    async def fake_get(self, url, *args, **kwargs):
        _ = (self, args, kwargs)
        return FakeResponse(302, {"location": "http://127.0.0.1:4000/"})

    monkeypatch.setattr(mcp_code_server.httpx.AsyncClient, "get", fake_get)
    ok, err = anyio.run(lambda: mcp_code_server._wait_for_http("http://127.0.0.1:3000/", timeout_s=0.5))
    assert ok is False
    assert "Redirect left the launched preview origin" in err


def test_preview_request_allowlist_is_same_origin_only() -> None:
    target = mcp_code_server._parse_preview_target("http://127.0.0.1:3000/index.html")
    assert (
        mcp_code_server._is_allowed_preview_request_url(
            "http://127.0.0.1:3000/assets/app.css", target=target
        )
        is True
    )
    assert mcp_code_server._is_allowed_preview_request_url("data:text/plain,ok", target=target) is True
    assert (
        mcp_code_server._is_allowed_preview_request_url(
            "http://127.0.0.1:4000/assets/app.css", target=target
        )
        is False
    )
    assert (
        mcp_code_server._is_allowed_preview_request_url(
            "https://127.0.0.1:3000/assets/app.css", target=target
        )
        is False
    )


def test_eval_patch_defaults_to_no_shared_worktree_reuse_dirs(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "hello.txt")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    seen: dict[str, list[str]] = {"reuse_dirs": []}

    def fake_symlink_reuse_dirs(*, repo_root: Path, worktree: Path, reuse_dirs: list[str]) -> list[str]:
        _ = (repo_root, worktree)
        seen["reuse_dirs"] = list(reuse_dirs)
        return []

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    monkeypatch.setattr(mcp_code_server, "_maybe_symlink_reuse_dirs", fake_symlink_reuse_dirs)
    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)

    async def run():
        return await mcp_code_server._frontend_design_loop_eval_impl(
            repo_path=str(repo),
            patches=[{"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello isolated\n"}],
            test_command="true",
            vision_provider="client",
        )

    result = anyio.run(run)
    assert result["deterministic_passed"] is True
    assert seen["reuse_dirs"] == []
