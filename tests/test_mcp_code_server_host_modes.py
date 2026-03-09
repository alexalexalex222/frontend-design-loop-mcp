import json
import subprocess
from pathlib import Path

import anyio
import pytest

from frontend_design_loop_core import mcp_code_server
from frontend_design_loop_core.providers.base import CompletionResponse
from frontend_design_loop_core.providers.codex_cli import CodexCLIProvider
from frontend_design_loop_core.providers.kilo_cli import KiloCLIProvider


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _make_repo(tmp_path: Path) -> Path:
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
    return repo


def test_frontend_design_loop_solve_rejects_host_agent_mode(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    async def run() -> None:
        await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello world",
            solver_mode="host_agent",
        )

    with pytest.raises(ValueError, match="frontend_design_loop_eval"):
        anyio.run(run)


def test_frontend_design_loop_solve_rejects_shell_commands_by_default(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    async def run() -> None:
        await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello world",
            solver_mode="host_cli",
            planning_mode="off",
            provider="codex_cli",
            model="gpt-5.4",
            max_candidates=1,
            test_command="printf ok >/dev/null",
        )

    with pytest.raises(ValueError, match="unsafe_shell_commands=true"):
        anyio.run(run)


def test_mcp_tool_registry_exposes_canonical_names() -> None:
    tool_names = sorted(mcp_code_server.mcp._tool_manager._tools.keys())
    assert "frontend_design_loop_design" in tool_names
    assert "frontend_design_loop_eval" in tool_names
    assert "frontend_design_loop_solve" in tool_names


def test_frontend_design_loop_design_requires_preview(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    async def run() -> None:
        await mcp_code_server.frontend_design_loop_design(
            repo_path=str(repo),
            goal="Make the page feel premium and more distinctive",
        )

    with pytest.raises(ValueError, match="preview_command \\+ preview_url"):
        anyio.run(run)


def test_frontend_design_loop_design_wraps_solve_with_design_defaults(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    captured: dict[str, object] = {}

    async def fake_solve(**kwargs):
        captured.update(kwargs)
        return {"winner": {"patch": "diff --git a/file b/file"}, "solver_mode": kwargs["solver_mode"]}

    monkeypatch.setattr(mcp_code_server, "frontend_design_loop_solve", fake_solve)

    async def run():
        return await mcp_code_server.frontend_design_loop_design(
            repo_path=str(repo),
            goal="Push the design harder without breaking the build",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}",
            provider="gemini_cli",
            model="gemini-3.1-pro-preview",
        )

    result = anyio.run(run)
    assert result["design_mode"] == "active_design_pass"
    assert captured["solver_mode"] == "host_cli"
    assert captured["planning_mode"] == "single"
    assert captured["provider"] == "gemini_cli"
    assert captured["model"] == "gemini-3.1-pro-preview"
    assert captured["vision_mode"] == "on"
    assert captured["vision_provider"] == "gemini_cli"
    assert captured["vision_model"] == "gemini-3.1-pro-preview"
    assert captured["planner_provider"] == "gemini_cli"
    assert captured["planner_model"] == "gemini-3.1-pro-preview"
    assert captured["section_creativity_mode"] == "on"
    assert captured["section_creativity_model"] == "gemini-3.1-pro-preview"
    assert captured["temperature_schedule"] == [0.28, 0.62, 0.96]
    assert result["design_defaults"]["single_model_default"] is True


def test_frontend_design_loop_design_allows_explicit_split_overrides(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    captured: dict[str, object] = {}

    async def fake_solve(**kwargs):
        captured.update(kwargs)
        return {"winner": {"patch": "diff --git a/file b/file"}, "solver_mode": kwargs["solver_mode"]}

    monkeypatch.setattr(mcp_code_server, "frontend_design_loop_solve", fake_solve)

    async def run():
        return await mcp_code_server.frontend_design_loop_design(
            repo_path=str(repo),
            goal="Use a separate planner and separate vision lane on purpose",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}",
            provider="gemini_cli",
            model="gemini-3.1-pro-preview",
            planner_provider="codex_cli",
            planner_model="gpt-5.4",
            vision_provider="codex_cli",
            vision_model="gpt-5.4",
        )

    result = anyio.run(run)
    assert captured["provider"] == "gemini_cli"
    assert captured["model"] == "gemini-3.1-pro-preview"
    assert captured["planner_provider"] == "codex_cli"
    assert captured["planner_model"] == "gpt-5.4"
    assert captured["vision_provider"] == "codex_cli"
    assert captured["vision_model"] == "gpt-5.4"
    assert captured["section_creativity_model"] == "gpt-5.4"
    assert result["design_defaults"]["single_model_default"] is False


def test_kilo_optional_polish_policy_is_banded() -> None:
    passing_report = {
        "broken": {"broken": False, "confidence": 1.0, "reasons": []},
        "score": {"score": 8.2},
    }
    near_threshold_report = {
        "broken": {"broken": False, "confidence": 1.0, "reasons": []},
        "score": {"score": 7.5},
    }
    low_report = {
        "broken": {"broken": False, "confidence": 1.0, "reasons": []},
        "score": {"score": 5.9},
    }

    assert mcp_code_server._kilo_optional_polish_policy(
        provider_name="kilo_cli",
        model="kilo/minimax/minimax-m2.5:free",
        vision_report=passing_report,
        vision_ok=True,
        threshold=8.0,
    ) == (False, False, "kilo optional polish skipped: initial vision already passed")

    assert mcp_code_server._kilo_optional_polish_policy(
        provider_name="kilo_cli",
        model="kilo/minimax/minimax-m2.5:free",
        vision_report=near_threshold_report,
        vision_ok=False,
        threshold=8.0,
    ) == (False, True, "kilo optional polish: skip broad vision fixer, run targeted creativity")

    assert mcp_code_server._kilo_optional_polish_policy(
        provider_name="kilo_cli",
        model="kilo/minimax/minimax-m2.5:free",
        vision_report=low_report,
        vision_ok=False,
        threshold=8.0,
    ) == (False, False, "kilo optional polish skipped: initial vision score below salvage band")


def test_frontend_design_loop_solve_host_cli_offline(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    async def fake_run_cli(self, *, args, cwd, env, timeout_s, output_file=None):
        _ = (self, args, cwd, env, timeout_s)
        content = (
            '{"patches":['
            '{"path":"hello.txt","patch":"@@ -1,1 +1,1 @@\\n-hello\\n+hello host cli\\n"}'
            '],"notes":["native cli"]}'
        )
        if output_file is not None:
            output_file.write_text(content, encoding="utf-8")
        return CompletionResponse(content=content, model="gpt-5.4")

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 10.0},
        }

    monkeypatch.setattr(CodexCLIProvider, "_run_cli", fake_run_cli)
    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello host cli",
            solver_mode="host_cli",
            planning_mode="off",
            provider="codex_cli",
            model="gpt-5.4",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            test_command="true",
            vision_mode="auto",
            vision_provider="anthropic_vertex",
            section_creativity_mode="off",
            apply_to_repo=False,
            allow_nonpassing_winner=False,
        )

    result = anyio.run(run)
    assert result["solver_mode"] == "host_cli"
    assert result["winner"] is not None
    assert "hello host cli" in result["winner"]["patch"]


def test_frontend_design_loop_solve_host_cli_offline_with_kilo(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    async def fake_run_cli(self, *, args, cwd, env, timeout_s, output_file=None):
        _ = (self, args, cwd, env, timeout_s, output_file)
        content = (
            '{"patches":['
            '{"path":"hello.txt","patch":"@@ -1,1 +1,1 @@\\n-hello\\n+hello kilo host cli\\n"}'
            '],"notes":["kilo native cli"]}'
        )
        return CompletionResponse(content=content, model="kilo/minimax/minimax-m2.5:free")

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 10.0},
        }

    monkeypatch.setattr(KiloCLIProvider, "_run_cli", fake_run_cli)
    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello kilo host cli",
            solver_mode="host_cli",
            planning_mode="off",
            provider="kilo_cli",
            model="kilo/minimax/minimax-m2.5:free",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            test_command="true",
            vision_mode="auto",
            vision_provider="anthropic_vertex",
            section_creativity_mode="off",
            apply_to_repo=False,
            allow_nonpassing_winner=False,
        )

    result = anyio.run(run)
    assert result["solver_mode"] == "host_cli"
    assert result["winner"] is not None
    assert "hello kilo host cli" in result["winner"]["patch"]


def test_frontend_design_loop_solve_marks_proxy_structural_vision_lanes(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    async def fake_call_llm_json(
        *,
        provider_name: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        cwd=None,
        reasoning_profile=None,
        timeout_s=None,
        prompt_role=None,
    ):
        _ = (
            provider_name,
            model,
            system_prompt,
            user_prompt,
            temperature,
            max_tokens,
            cwd,
            reasoning_profile,
            timeout_s,
            prompt_role,
        )
        return {
            "patches": [
                {
                    "path": "hello.txt",
                    "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello proxy lane\n",
                }
            ],
            "notes": ["proxy lane"],
        }

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 9.3},
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello proxy lane",
            planning_mode="off",
            auto_context_mode="off",
            provider="codex_cli",
            model="gpt-5.4",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            test_command="true",
            vision_mode="auto",
            vision_provider="kilo_cli",
            vision_model="kilo/minimax/minimax-m2.5:free",
            section_creativity_mode="off",
            apply_to_repo=False,
            allow_nonpassing_winner=True,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert result["winner_passes_all"] is False
    assert result["winner"]["vision_review_mode"] == "proxy_structural"
    assert result["winner"]["vision_score"] is None


def test_frontend_design_loop_solve_host_cli_auto_tunes_kilo_defaults(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    seen: dict[str, str | None] = {"planner_provider": None, "planner_model": None}

    async def fake_call_llm_json(
        *,
        provider_name: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        cwd=None,
        reasoning_profile=None,
        timeout_s=None,
        prompt_role=None,
    ):
        _ = (
            system_prompt,
            user_prompt,
            temperature,
            max_tokens,
            cwd,
            reasoning_profile,
            timeout_s,
            prompt_role,
        )
        if provider_name == "codex_cli":
            seen["planner_provider"] = provider_name
            seen["planner_model"] = model
            return {
                "plan_summary": "single planner",
                "edits": ["hello.txt"],
                "risks": [],
                "tests": ["true"],
            }
        return {
            "patches": [
                {
                    "path": "hello.txt",
                    "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello kilo tuned\n",
                }
            ],
            "notes": ["kilo tuned"],
        }

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = (diff_text, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 8.4},
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)
    monkeypatch.setattr(mcp_code_server, "_native_cli_command_available", lambda provider_name: provider_name == "codex_cli")

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello kilo tuned",
            solver_mode="host_cli",
            provider="kilo_cli",
            model="kilo/minimax/minimax-m2.5:free",
            max_candidates=2,
            candidate_concurrency=1,
            max_fix_rounds=0,
            test_command="true",
            vision_mode="auto",
            vision_provider="codex_cli",
            vision_model="gpt-5.4",
            apply_to_repo=False,
            allow_nonpassing_winner=True,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert seen["planner_provider"] == "codex_cli"
    assert seen["planner_model"] == "gpt-5.4"

    request_payload = json.loads((Path(result["run_dir"]) / "request.json").read_text(encoding="utf-8"))
    assert request_payload["planning_mode"] == "single"
    assert request_payload["planner_provider"] == "codex_cli"
    assert request_payload["planner_model"] == "gpt-5.4"
    assert request_payload["temperature_schedule"] == [0.45, 0.82]
    assert "kilo_minimax_default_planner=codex_cli/gpt-5.4 single" in request_payload["runtime_tuning_notes"]
    assert "kilo_minimax_patch_generator_variant=high" in request_payload["runtime_tuning_notes"]
    assert "kilo_minimax_patch_timeout=1200s_multi_candidate" in request_payload["runtime_tuning_notes"]
    assert (
        "kilo_minimax_optional_polish=banded (skip passers; salvage only near-threshold)"
        in request_payload["runtime_tuning_notes"]
    )
