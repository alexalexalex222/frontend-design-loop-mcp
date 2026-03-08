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


def test_apply_to_repo_skips_when_winner_is_best_effort(tmp_path: Path, monkeypatch) -> None:
    # Create a tiny repo where gates pass but vision fails.
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
                {"path": "hello.txt", "patch": "@@ -1,1 +1,1 @@\n-hello\n+hello world\n"}
            ],
            "notes": ["stub patch"],
        }

    async def fake_capture_screenshots(*, url: str, out_dir: Path, viewports, timeout_ms: int, unsafe_external_preview: bool = False):
        _ = (url, viewports, timeout_ms)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "desktop.png"
        p.write_bytes(b"fake")
        return [p]

    async def fake_vision_eval(*, images, goal, threshold, provider_name, model, min_confidence, kind):
        _ = (images, goal, threshold, provider_name, model, min_confidence, kind)
        # Not broken, but score below threshold => vision_ok False.
        return {"broken": {"broken": False, "confidence": 1.0}, "score": {"score": 0.0}}

    # Avoid real model + real browser + real Gemini.
    monkeypatch.setattr(mcp_code_server, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(mcp_code_server, "_capture_screenshots", fake_capture_screenshots)
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
            test_command="true",
            vision_mode="on",
            preview_command="python3 -m http.server {port}",
            preview_url="http://127.0.0.1:{port}/",
            preview_wait_timeout_s=10.0,
            section_creativity_mode="off",
            allow_nonpassing_winner=True,
            apply_to_repo=True,
        )

    result = anyio.run(run)
    assert result["winner"] is not None
    assert result["winner"]["passes_all_gates"] is False
    assert result["applied_to_repo"] is False
    assert result["apply_skipped_reason"]

    # Original repo should be unchanged (since apply was skipped).
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello\n"


def test_apply_patch_bundle_accepts_full_file_replacement(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")

    async def run():
        return await mcp_code_server._apply_patch_bundle(
            repo_root=repo,
            patches=[{"path": "hello.txt", "patch": "hello world\n"}],
        )

    ok, touched = anyio.run(run)
    assert ok is True
    assert touched == ["hello.txt"]
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello world\n"


def test_apply_patch_bundle_repairs_obvious_missing_hunk_prefixes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "styles.css").write_text("body {\n  color: white;\n}\n", encoding="utf-8")

    malformed_patch = (
        "@@ -1,3 +1,8 @@\n"
        " body {\n"
        "-  color: white;\n"
        "+  color: white;\n"
        "+  background: #050816;\n"
        "+}\n"
        "+\n"
        ".hero {\n"
        "+  display: grid;\n"
        "+}\n"
    )

    async def run():
        return await mcp_code_server._apply_patch_bundle(
            repo_root=repo,
            patches=[{"path": "styles.css", "patch": malformed_patch}],
        )

    ok, touched = anyio.run(run)
    assert ok is True
    assert touched == ["styles.css"]
    text = (repo / "styles.css").read_text(encoding="utf-8")
    assert "background: #050816;" in text
    assert ".hero {" in text


def test_apply_patch_bundle_accepts_recountable_git_diff(tmp_path: Path) -> None:
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

    recount_patch = (
        "diff --git a/hello.txt b/hello.txt\n"
        "index 0000000..1111111 100644\n"
        "--- a/hello.txt\n"
        "+++ b/hello.txt\n"
        "@@ -1,99 +1,99 @@\n"
        "-hello\n"
        "+hello recounted\n"
    )

    async def run():
        return await mcp_code_server._apply_patch_bundle(
            repo_root=repo,
            patches=[{"path": "hello.txt", "patch": recount_patch}],
        )

    ok, touched = anyio.run(run)
    assert ok is True
    assert touched == ["hello.txt"]
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello recounted\n"


def test_apply_patch_bundle_merges_multiple_diff_entries_for_same_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text(
        "<main>\n  <section class=\"hero\"></section>\n  <section class=\"proof\"></section>\n</main>\n",
        encoding="utf-8",
    )

    _git(repo, "init")
    _git(repo, "add", "index.html")
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def run():
        return await mcp_code_server._apply_patch_bundle(
            repo_root=repo,
            patches=[
                {
                    "path": "index.html",
                    "patch": "@@ -1,4 +1,7 @@\n <main>\n   <section class=\"hero\"></section>\n+  <section class=\"banner\">live</section>\n   <section class=\"proof\"></section>\n </main>\n",
                },
                {
                    "path": "index.html",
                    "patch": "@@ -1,4 +1,7 @@\n <main>\n   <section class=\"hero\"></section>\n   <section class=\"proof\"></section>\n+  <section class=\"capabilities\"></section>\n </main>\n",
                },
            ],
        )

    ok, touched = anyio.run(run)
    assert ok is True
    assert touched == ["index.html"]
    text = (repo / "index.html").read_text(encoding="utf-8")
    assert '<section class="banner">live</section>' in text
    assert '<section class="capabilities"></section>' in text
