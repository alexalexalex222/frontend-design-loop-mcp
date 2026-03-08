import json
import subprocess
from pathlib import Path

import anyio

from frontend_design_loop_core import mcp_code_server


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_frontend_design_loop_solve_end_to_end_offline(tmp_path: Path, monkeypatch) -> None:
    # Create a tiny git repo we can run worktrees against.
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

    # Keep run artifacts inside the temp dir.
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(out_dir))

    # Force a deterministic offline "LLM" response.
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
                    "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello world\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)

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
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello world",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            vision_mode="auto",
            section_creativity_mode="off",
            apply_to_repo=False,
            allow_nonpassing_winner=False,
        )

    result = anyio.run(run)

    assert result["test_command_inferred"] is True
    assert result["test_command"] == "true"
    assert "skipping" in str(result["test_command_inferred_reason"] or "").lower()

    winner = result["winner"]
    assert winner is not None
    assert "hello world" in winner["patch"]

    # Ensure we didn't accidentally apply changes to the original repo.
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello\n"

    # Ensure artifacts got written.
    run_dir = Path(result["run_dir"])
    assert run_dir.exists()
    assert (run_dir / "run_summary.json").exists()


def test_frontend_design_loop_solve_falls_back_when_git_diff_breaks(tmp_path: Path, monkeypatch) -> None:
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
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_KEEP_WORKTREES", "1")

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
                    "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello world\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    async def fake_capture_diff_screenshots(*, diff_text: str, out_dir: Path, timeout_ms: int):
        _ = timeout_ms
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "diff.png"
        p.write_bytes(diff_text.encode("utf-8"))
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 10.0},
        }

    original_run_command = mcp_code_server.run_command

    async def flaky_run_command(command: str, cwd: Path, timeout_ms: int):
        if command == "git diff --no-color" and "cand_0" in str(cwd):
            return 128, "", "fatal: not a git repository: broken-worktree"
        return await original_run_command(command, cwd=cwd, timeout_ms=timeout_ms)

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)
    monkeypatch.setattr(mcp_code_server, "run_command", flaky_run_command)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello world",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            vision_mode="auto",
            section_creativity_mode="off",
            apply_to_repo=False,
            allow_nonpassing_winner=False,
        )

    result = anyio.run(run)
    winner = result["winner"]
    assert winner is not None
    assert winner["error"] is None
    assert "hello world" in winner["patch"]


def test_section_creativity_runs_on_structurally_sound_nonpassing_ui(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><p>hello</p>\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "index.html")
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
                    "path": "index.html",
                    "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><p>hello</p>\n+<!doctype html><main class=\"hero\"><p>hello world</p></main>\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    async def fake_capture_screenshots(*, url: str, out_dir: Path, viewports, timeout_ms: int, unsafe_external_preview: bool = False):
        _ = (url, viewports, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "desktop.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 7.5},
        }

    seen: dict[str, bool] = {"called": False}

    async def fake_section_creativity_eval(*, image, provider_name, model, timeout_s=None):
        _ = (image, provider_name, model, timeout_s)
        seen["called"] = True
        return {
            "sections": [
                {"label": "hero", "score": 0.2, "confidence": 0.9, "notes": "generic"},
            ]
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_screenshots", fake_capture_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)
    monkeypatch.setattr(mcp_code_server, "_section_creativity_eval", fake_section_creativity_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Turn this into a premium landing page",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            test_command="true",
            vision_mode="on",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}/index.html",
            preview_wait_timeout_s=10.0,
            section_creativity_mode="on",
            max_creativity_fix_rounds=0,
            allow_nonpassing_winner=True,
            apply_to_repo=False,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert seen["called"] is True


def test_section_creativity_eval_applies_timeout_override(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeProvider:
        async def complete_with_vision(self, **kwargs):
            seen["timeout_s"] = kwargs.get("timeout_s")
            return FakeResponse('{"sections":[]}')

    monkeypatch.setattr(mcp_code_server.ProviderFactory, "get", lambda provider_name, config: FakeProvider())

    async def run():
        return await mcp_code_server._section_creativity_eval(
            image=b"fake-image",
            provider_name="codex_cli",
            model="gpt-5.4",
            timeout_s=180.0,
        )

    result = anyio.run(run)
    assert result == {"sections": []}
    assert seen["timeout_s"] == 180.0


def test_creativity_refiner_scopes_to_top_weak_sections_for_kilo(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><p>hello</p>\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "index.html")
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

    seen: dict[str, object] = {"prompt": None, "max_tokens": None}

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
            temperature,
            cwd,
            reasoning_profile,
            timeout_s,
        )
        if prompt_role == "creativity_refiner":
            seen["prompt"] = user_prompt
            seen["max_tokens"] = max_tokens
            return {"patches": [], "notes": ["no-op creativity refiner"]}
        return {
            "patches": [
                {
                    "path": "index.html",
                    "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><p>hello</p>\n+<!doctype html><main class=\"hero\"><p>hello world</p></main>\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    async def fake_capture_screenshots(*, url: str, out_dir: Path, viewports, timeout_ms: int, unsafe_external_preview: bool = False):
        _ = (url, viewports, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "desktop.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 7.4},
        }

    async def fake_section_creativity_eval(*, image, provider_name, model, timeout_s=None):
        _ = (image, provider_name, model, timeout_s)
        return {
            "sections": [
                {"label": "footer", "score": 0.61, "confidence": 0.82, "notes": "generic footer"},
                {"label": "hero", "score": 0.12, "confidence": 0.91, "notes": "hero lacks signature moment"},
                {"label": "header", "score": 0.18, "confidence": 0.88, "notes": "plain nav"},
                {"label": "proof_wall", "score": 0.32, "confidence": 0.86, "notes": "proof is too generic"},
                {"label": "final_cta", "score": 0.67, "confidence": 0.9, "notes": "quiet CTA"},
            ]
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_screenshots", fake_capture_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)
    monkeypatch.setattr(mcp_code_server, "_section_creativity_eval", fake_section_creativity_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Turn this into a premium landing page",
            solver_mode="host_cli",
            planning_mode="off",
            provider="kilo_cli",
            model="kilo/minimax/minimax-m2.5:free",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            test_command="true",
            vision_mode="on",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}/index.html",
            preview_wait_timeout_s=10.0,
            vision_provider="codex_cli",
            vision_model="gpt-5.4",
            section_creativity_mode="on",
            max_creativity_fix_rounds=1,
            allow_nonpassing_winner=True,
            apply_to_repo=False,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    prompt = str(seen["prompt"] or "")
    assert "WEAK_SECTIONS (edit ONLY these highest-priority targets)" in prompt
    assert "hero, header, proof_wall" in prompt
    assert "footer" not in prompt
    assert "final_cta" not in prompt
    assert seen["max_tokens"] == 3200


def test_patch_apply_failure_can_reanchor_once_and_recover(tmp_path: Path, monkeypatch) -> None:
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

    seen: dict[str, int] = {"repair_calls": 0}

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
        )
        if prompt_role == "patch_fixer":
            seen["repair_calls"] += 1
            return {
                "patches": [
                    {
                        "path": "hello.txt",
                        "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello world\n",
                    }
                ],
                "notes": ["re-anchored patch"],
            }
        return {
            "patches": [
                {
                    "path": "hello.txt",
                    "patch": "@@ -1,1 +1,1 @@\n-hello there\n+hello world\n",
                }
            ],
            "notes": ["bad anchor"],
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
            "score": {"score": 10.0},
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_diff_screenshots", fake_capture_diff_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Change hello to hello world",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            vision_mode="auto",
            section_creativity_mode="off",
            allow_nonpassing_winner=False,
            apply_to_repo=False,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert seen["repair_calls"] == 1
    assert "hello world" in result["winner"]["patch"]


def test_creativity_refiner_runs_even_when_no_sections_are_strong(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><p>hello</p>\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "index.html")
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

    seen: dict[str, bool] = {"creativity_fix_called": False}

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
        )
        if prompt_role == "creativity_refiner":
            seen["creativity_fix_called"] = True
            return {
                "patches": [
                    {
                        "path": "index.html",
                        "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><main class=\"hero\"><p>hello world</p></main>\n+<!doctype html><main class=\"hero signature\"><p>hello world</p></main>\n",
                    }
                ],
                "notes": ["coarse creativity rescue"],
            }
        return {
            "patches": [
                {
                    "path": "index.html",
                    "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><p>hello</p>\n+<!doctype html><main class=\"hero\"><p>hello world</p></main>\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    async def fake_capture_screenshots(*, url: str, out_dir: Path, viewports, timeout_ms: int, unsafe_external_preview: bool = False):
        _ = (url, viewports, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "desktop.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 7.5},
        }

    async def fake_section_creativity_eval(*, image, provider_name, model, timeout_s=None):
        _ = (image, provider_name, model, timeout_s)
        return {
            "sections": [
                {"label": "hero", "score": 0.2, "confidence": 0.9, "notes": "generic"},
            ]
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_screenshots", fake_capture_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)
    monkeypatch.setattr(mcp_code_server, "_section_creativity_eval", fake_section_creativity_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Turn this into a premium landing page",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            test_command="true",
            vision_mode="on",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}/index.html",
            preview_wait_timeout_s=10.0,
            section_creativity_mode="on",
            max_creativity_fix_rounds=1,
            allow_nonpassing_winner=True,
            apply_to_repo=False,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert seen["creativity_fix_called"] is True


def test_optional_vision_refine_failure_does_not_discard_candidate(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><p>hello</p>\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "index.html")
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
        )
        if prompt_role == "vision_fixer":
            raise RuntimeError("kilo_cli timed out after 300.0s")
        return {
            "patches": [
                {
                    "path": "index.html",
                    "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><p>hello</p>\n+<!doctype html><main class=\"hero\"><p>hello world</p></main>\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    async def fake_capture_screenshots(*, url: str, out_dir: Path, viewports, timeout_ms: int, unsafe_external_preview: bool = False):
        _ = (url, viewports, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "desktop.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 7.5},
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_screenshots", fake_capture_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Turn this into a premium landing page",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            test_command="true",
            vision_mode="on",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}/index.html",
            preview_wait_timeout_s=10.0,
            max_vision_fix_rounds=1,
            section_creativity_mode="off",
            allow_nonpassing_winner=True,
            apply_to_repo=False,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert result["winner"]["error"] is None
    assert result["winner"]["vision_score"] == 7.5


def test_optional_vision_refine_falls_back_to_vision_provider(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><p>hello</p>\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "index.html")
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

    seen: dict[str, list[str] | float | None] = {"vision_fix_providers": [], "kilo_timeout_s": None}
    vision_states = iter(
        [
            {"broken": {"broken": True, "confidence": 1.0, "reasons": ["layout collapse"]}, "score": {"score": 7.5}},
            {"broken": {"broken": False, "confidence": 1.0, "reasons": []}, "score": {"score": 8.2}},
        ]
    )

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
            model,
            system_prompt,
            user_prompt,
            temperature,
            max_tokens,
            cwd,
            reasoning_profile,
        )
        if prompt_role == "vision_fixer":
            casted = seen["vision_fix_providers"]
            assert isinstance(casted, list)
            casted.append(provider_name)
            if provider_name == "kilo_cli":
                seen["kilo_timeout_s"] = timeout_s
                raise RuntimeError("kilo_cli timed out after 300.0s")
            return {
                "patches": [
                    {
                        "path": "index.html",
                        "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><main class=\"hero\"><p>hello world</p></main>\n+<!doctype html><main class=\"hero signature\"><p>hello world</p></main>\n",
                    }
                ],
                "notes": ["vision fallback patch"],
            }
        return {
            "patches": [
                {
                    "path": "index.html",
                    "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><p>hello</p>\n+<!doctype html><main class=\"hero\"><p>hello world</p></main>\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    async def fake_capture_screenshots(*, url: str, out_dir: Path, viewports, timeout_ms: int, unsafe_external_preview: bool = False):
        _ = (url, viewports, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "desktop.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return next(vision_states)

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_screenshots", fake_capture_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Turn this into a premium landing page",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            provider="kilo_cli",
            model="kilo/minimax/minimax-m2.5:free",
            solver_mode="host_cli",
            test_command="true",
            vision_mode="on",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}/index.html",
            preview_wait_timeout_s=10.0,
            vision_provider="codex_cli",
            vision_model="gpt-5.4",
            max_vision_fix_rounds=1,
            section_creativity_mode="off",
            allow_nonpassing_winner=True,
            apply_to_repo=False,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert result["winner"]["vision_score"] == 8.2
    assert seen["vision_fix_providers"] == ["codex_cli"]
    assert seen["kilo_timeout_s"] is None

    run_dir = Path(result["run_dir"])
    response_path = run_dir / "candidates" / "0" / "llm_vision_fix_response_1.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    assert response["_frontend_design_loop_eval_meta"]["provider_used"] == "codex_cli"
    assert response["_frontend_design_loop_eval_meta"]["fallback_used"] is True
    assert (run_dir / "candidates" / "0" / "vision_fix_primary_error_1.txt").exists()


def test_optional_creativity_refine_falls_back_to_vision_provider(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><p>hello</p>\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "index.html")
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

    seen: dict[str, list[str] | float | None] = {"creativity_fix_providers": [], "kilo_timeout_s": None}

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
            model,
            system_prompt,
            user_prompt,
            temperature,
            max_tokens,
            cwd,
            reasoning_profile,
        )
        if prompt_role == "creativity_refiner":
            casted = seen["creativity_fix_providers"]
            assert isinstance(casted, list)
            casted.append(provider_name)
            if provider_name == "kilo_cli":
                seen["kilo_timeout_s"] = timeout_s
                raise RuntimeError("kilo_cli timed out after 300.0s")
            return {
                "patches": [
                    {
                        "path": "index.html",
                        "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><main class=\"hero\"><p>hello world</p></main>\n+<!doctype html><main class=\"hero signature\"><p>hello world</p></main>\n",
                    }
                ],
                "notes": ["creativity fallback patch"],
            }
        return {
            "patches": [
                {
                    "path": "index.html",
                    "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><p>hello</p>\n+<!doctype html><main class=\"hero\"><p>hello world</p></main>\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    async def fake_capture_screenshots(*, url: str, out_dir: Path, viewports, timeout_ms: int, unsafe_external_preview: bool = False):
        _ = (url, viewports, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "desktop.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": 7.5},
        }

    async def fake_section_creativity_eval(*, image, provider_name, model, timeout_s=None):
        _ = (image, provider_name, model, timeout_s)
        return {
            "sections": [
                {"label": "hero", "score": 0.2, "confidence": 0.9, "notes": "generic"},
            ]
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_screenshots", fake_capture_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)
    monkeypatch.setattr(mcp_code_server, "_section_creativity_eval", fake_section_creativity_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Turn this into a premium landing page",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            provider="kilo_cli",
            model="kilo/minimax/minimax-m2.5:free",
            solver_mode="host_cli",
            test_command="true",
            vision_mode="on",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}/index.html",
            preview_wait_timeout_s=10.0,
            vision_provider="codex_cli",
            vision_model="gpt-5.4",
            max_vision_fix_rounds=0,
            section_creativity_mode="on",
            max_creativity_fix_rounds=1,
            allow_nonpassing_winner=True,
            apply_to_repo=False,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert seen["creativity_fix_providers"] == ["codex_cli"]
    assert seen["kilo_timeout_s"] is None

    run_dir = Path(result["run_dir"])
    response_path = run_dir / "candidates" / "0" / "llm_creativity_fix_response_1.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    assert response["_frontend_design_loop_eval_meta"]["provider_used"] == "codex_cli"
    assert response["_frontend_design_loop_eval_meta"]["fallback_used"] is True
    assert (run_dir / "candidates" / "0" / "creativity_fix_primary_error_1.txt").exists()


def test_kilo_near_threshold_skips_vision_fix_and_uses_targeted_creativity(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><p>hello</p>\n", encoding="utf-8")

    _git(repo, "init")
    _git(repo, "add", "index.html")
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

    seen: dict[str, list[str]] = {"vision_fix_providers": [], "creativity_fix_providers": []}

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
            model,
            system_prompt,
            user_prompt,
            temperature,
            max_tokens,
            cwd,
            reasoning_profile,
            timeout_s,
        )
        if prompt_role == "vision_fixer":
            seen["vision_fix_providers"].append(provider_name)
            return {
                "patches": [
                    {
                        "path": "index.html",
                        "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><main class=\"hero\"><p>hello world</p></main>\n+<!doctype html><main class=\"hero rescue\"><p>hello world</p></main>\n",
                    }
                ],
                "notes": ["vision fix should not run"],
            }
        if prompt_role == "creativity_refiner":
            seen["creativity_fix_providers"].append(provider_name)
            return {
                "patches": [
                    {
                        "path": "index.html",
                        "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><main class=\"hero\"><p>hello world</p></main>\n+<!doctype html><main class=\"hero signature\"><p>hello world</p></main>\n",
                    }
                ],
                "notes": ["targeted creativity patch"],
            }
        return {
            "patches": [
                {
                    "path": "index.html",
                    "patch": "@@ -1,1 +1,1 @@\n-<!doctype html><p>hello</p>\n+<!doctype html><main class=\"hero\"><p>hello world</p></main>\n",
                }
            ],
            "notes": ["offline stub patch"],
        }

    async def fake_capture_screenshots(*, url: str, out_dir: Path, viewports, timeout_ms: int, unsafe_external_preview: bool = False):
        _ = (url, viewports, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "desktop.png"
        p.write_bytes(b"fake")
        return [p]

    vision_scores = iter([7.4, 8.2])

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        return {
            "broken": {"broken": False, "confidence": 1.0, "reasons": []},
            "score": {"score": next(vision_scores)},
        }

    async def fake_section_creativity_eval(*, image, provider_name, model, timeout_s=None):
        _ = (image, provider_name, model, timeout_s)
        return {
            "sections": [
                {"label": "hero", "score": 0.2, "confidence": 0.9, "notes": "generic"},
            ]
        }

    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_screenshots", fake_capture_screenshots)
    monkeypatch.setattr(mcp_code_server, "_vision_eval", fake_vision_eval)
    monkeypatch.setattr(mcp_code_server, "_section_creativity_eval", fake_section_creativity_eval)

    async def run():
        return await mcp_code_server.frontend_design_loop_solve(
            repo_path=str(repo),
            goal="Turn this into a premium landing page",
            planning_mode="off",
            auto_context_mode="off",
            max_candidates=1,
            candidate_concurrency=1,
            max_fix_rounds=0,
            provider="kilo_cli",
            model="kilo/minimax/minimax-m2.5:free",
            solver_mode="host_cli",
            test_command="true",
            vision_mode="on",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}/index.html",
            preview_wait_timeout_s=10.0,
            vision_provider="codex_cli",
            vision_model="gpt-5.4",
            max_vision_fix_rounds=1,
            section_creativity_mode="on",
            max_creativity_fix_rounds=1,
            allow_nonpassing_winner=True,
            apply_to_repo=False,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert result["winner"]["vision_score"] == 8.2
    assert seen["vision_fix_providers"] == []
    assert seen["creativity_fix_providers"] == ["codex_cli"]

    run_dir = Path(result["run_dir"])
    response_path = run_dir / "candidates" / "0" / "llm_creativity_fix_response_1.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    assert response["_frontend_design_loop_eval_meta"]["provider_used"] == "codex_cli"
    assert response["_frontend_design_loop_eval_meta"]["fallback_used"] is True
