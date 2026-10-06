"""Integration regressions for native edits, review evidence, and owned shutdown."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from design_toolkit.tools.review import review_evidence
from frontend_design_loop_core import mcp_code_server as core
from frontend_design_loop_core.config import load_config
from frontend_design_loop_core.evidence import visual_verdict
from frontend_design_loop_core.providers.base import CompletionResponse
from frontend_design_loop_core.providers.claude_cli import ClaudeCLIProvider

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9JkAAAAASUVORK5CYII="
)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "source with spaces"
    root.mkdir()
    (root / "index.html").write_text("before\n")
    git(root, "init")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    return root


def assessed(score=8.5, blockers=None):
    return {
        "schema_version": 1,
        "status": "assessed",
        "broken": False,
        "score": score,
        "pass": None,
        "blockers": blockers or [],
        "uncertainty": [],
        "limits": [],
        "evidence": {"kind": "ui", "sufficient": True, "observations": ["visible fixture"]},
    }


@pytest.mark.asyncio
async def test_native_partial_failure_rolls_back_files_and_index(repository, tmp_path):
    worktree = tmp_path / "candidate"
    git(repository, "worktree", "add", "--detach", str(worktree), "HEAD")
    before = git(worktree, "status", "--porcelain")

    class BrokenEditor:
        async def edit_repository(self, **kwargs):
            (worktree / "index.html").write_text("partial\n")
            (worktree / "added.txt").write_text("partial\n")
            git(worktree, "add", ".")
            raise RuntimeError("offline native interruption")

    try:
        with pytest.raises(RuntimeError, match="interruption"):
            await core._native_edit_transaction(BrokenEditor(), repo_path=worktree)
        assert (worktree / "index.html").read_text() == "before\n"
        assert not (worktree / "added.txt").exists()
        assert git(worktree, "status", "--porcelain") == before
    finally:
        git(repository, "worktree", "remove", "--force", str(worktree))


@pytest.mark.asyncio
async def test_higher_scoring_native_refinement_with_blocker_restores_inspected_state(
    repository, tmp_path, monkeypatch
):
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_MCP_OUT_DIR", str(tmp_path / "runs"))
    calls = []

    class Editor:
        supports_repository_edit = True

        async def edit_repository(self, **kwargs):
            calls.append(kwargs)
            root = Path(kwargs["repo_path"])
            (root / "index.html").write_text("first\n" if len(calls) == 1 else "regressed\n")
            (root / "added.txt").write_text("new source\n")
            return CompletionResponse(content="edited", model=kwargs["model"])

    monkeypatch.setattr(core.ProviderFactory, "get", lambda *a: Editor())

    async def capture(**kwargs):
        path = kwargs["out_dir"] / "desktop.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
        return [path]

    reports = iter([assessed(7.5), assessed(8.8, ["Configured interaction failed"])])

    async def judge(**kwargs):
        return next(reports)

    monkeypatch.setattr(core, "_capture_screenshots", capture)
    monkeypatch.setattr(core, "_vision_eval", judge)
    result = await core.frontend_design_loop_solve(
        repo_path=str(repository),
        goal="Improve the fixture",
        model="fixture-model",
        provider="codex_cli",
        editing_mode="native",
        capture_baseline=False,
        auto_context_mode="off",
        test_command="git diff --check",
        preview_command=f'"{sys.executable}" -m http.server {{port}} --bind 127.0.0.1',
        preview_url="http://127.0.0.1:{port}/index.html",
        max_candidates=1,
        max_fix_rounds=0,
        max_vision_fix_rounds=1,
        section_creativity_mode="off",
        allow_nonpassing_winner=True,
        builder_effort="high",
        refiner_effort="xhigh",
    )
    assert result["winner"]["vision_score"] == 7.5
    assert result["winner"]["applied"] is True
    assert "+first" in result["winner"]["patch"] and "regressed" not in result["winner"]["patch"]
    assert "added.txt" in result["winner"]["patch"]
    assert (repository / "index.html").read_text() == "before\n"
    assert len(calls) == 2 and calls[1]["images"] == [PNG]
    assert calls[0]["reasoning_profile"] == "high" and calls[1]["reasoning_profile"] == "xhigh"
    assert json.loads((Path(result["run_dir"]) / "candidates/0/delivery.json").read_text())["ok"]


@pytest.mark.asyncio
async def test_malformed_judge_is_evaluator_error_not_design_failure(monkeypatch):
    class Judge:
        async def complete_with_vision(self, **kwargs):
            return CompletionResponse(content='{"score": "invented"}', model="fixture-model")

    monkeypatch.setattr(core.ProviderFactory, "get", lambda *a: Judge())
    report = await core._vision_eval(
        images=[PNG],
        goal="Fixture",
        threshold=8,
        provider_name="codex_cli",
        model="fixture-model",
        min_confidence=0.9,
        kind="ui",
    )
    assert report["status"] == "error" and report["broken"] is None
    assert visual_verdict(report, 8) == (False, None)


def manifest(root, label):
    root.mkdir()
    path = root / "desktop.png"
    path.write_bytes(PNG)
    value = {
        "schema_version": 1,
        "screenshots": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(PNG).hexdigest(),
                "label": label,
                "state": "initial",
                "width": 1440,
                "height": 900,
                "image_width": 1,
                "image_height": 1,
            }
        ],
        "viewports": [],
        "limitations": [],
    }
    target = root / "manifest.json"
    target.write_text(json.dumps(value))
    return target


@pytest.mark.asyncio
async def test_toolkit_review_labels_baseline_indices_and_rejects_stale_image(
    tmp_path, monkeypatch
):
    candidate = manifest(tmp_path / "candidate", "desktop")
    baseline = manifest(tmp_path / "baseline", "desktop")
    calls = []

    class Judge:
        async def complete_with_vision(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return CompletionResponse(
                content=json.dumps(assessed()),
                model=kwargs["model"],
                raw_response={"execution": {"observed": {"model": None}}},
            )

    monkeypatch.setattr(core.ProviderFactory, "get", lambda *a: Judge())
    result = await review_evidence(
        manifest_path=candidate,
        baseline_path=baseline,
        goal="Fixture",
        provider_name="codex_cli",
        model="fixture",
        effort="xhigh",
        threshold=8,
    )
    assert result["eligible"] and calls[0][1]["images"] == [PNG, PNG]
    assert calls[0][1]["reasoning_profile"] == "xhigh"
    labels = json.loads(calls[0][0][1].content.split("LABELED EVIDENCE\n")[1])
    assert labels["candidate"]["images"][0]["image_index"] == 0
    assert labels["baseline"]["images"][0]["image_index"] == 1
    (candidate.parent / "desktop.png").write_bytes(PNG + b"changed")
    with pytest.raises(ValueError, match="do not match"):
        await review_evidence(
            manifest_path=candidate,
            goal="Fixture",
            provider_name="codex_cli",
            model="fixture",
            effort="high",
            threshold=8,
        )
    assert len(calls) == 1


def test_claude_array_receipt_requires_successful_image_read():
    provider = ClaudeCLIProvider(load_config())
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "id": "shot",
                        "input": {"file_path": "/tmp/shot.png"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "shot", "content": [{"type": "image"}]}
                ]
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "result": "review",
            "modelUsage": {"claude-opus-5-5": {}},
        },
    ]
    text = json.dumps(events)
    assert provider._extract_content(stdout_text=text, stderr_text="", output_file=None) == "review"
    assert provider._observed_execution(text)["verified_image_reads"] == ["/tmp/shot.png"]
    events[1]["message"]["content"][0]["is_error"] = True
    assert provider._observed_execution(json.dumps(events))["verified_image_reads"] == []


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX SIGTERM integration")
async def test_stdio_sigterm_stops_owned_preview(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Shutdown</title>")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "design_toolkit.server",
        cwd=tmp_path,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def request(value):
        proc.stdin.write((json.dumps(value) + "\n").encode())
        await proc.stdin.drain()
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), 10)
            assert line, "MCP exited before returning JSON"
            result = json.loads(line)
            if result.get("id") == value.get("id"):
                return result

    preview_pid = None
    try:
        await request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "shutdown-fixture", "version": "1"},
                },
            }
        )
        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        await proc.stdin.drain()
        response = await request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "preview_start",
                    "arguments": {
                        "command": [
                            sys.executable,
                            "-m",
                            "http.server",
                            "{port}",
                            "--bind",
                            "127.0.0.1",
                        ],
                        "cwd": str(tmp_path),
                    },
                },
            }
        )
        content = response["result"]["structuredContent"]
        assert content["status"] == "passed", content
        preview_pid = content["pid"]
        proc.send_signal(signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), 20)
        with pytest.raises(ProcessLookupError):
            os.kill(preview_pid, 0)
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        if preview_pid:
            try:
                os.kill(preview_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


@pytest.mark.asyncio
async def test_dirty_delivery_excludes_generated_outputs_and_credentials(repository, tmp_path):
    from frontend_design_loop_core import delivery
    from frontend_design_loop_core.evidence import apply_source_snapshot, source_snapshot

    (repository / "index.html").write_text("dirty baseline\n")
    source = await source_snapshot(repository)
    worktree = tmp_path / "candidate-exclusions"
    git(repository, "worktree", "add", "--detach", str(worktree), "HEAD")
    try:
        await apply_source_snapshot(worktree, source)
        (worktree / "index.html").write_text("retained candidate\n")
        (worktree / ".env.local").write_text("DO_NOT_EXPORT=private-fixture-value\n")
        (worktree / "next-env.d.ts").write_text("generated\n")
        patch = await delivery.export_candidate_delta(worktree, source)
        assert "+retained candidate" in patch
        assert "private-fixture-value" not in patch and "next-env.d.ts" not in patch
        assert (await delivery.verify_candidate_delta(repository, source, patch, worktree))["ok"]
    finally:
        git(repository, "worktree", "remove", "--force", str(worktree))


@pytest.mark.asyncio
async def test_explicit_candidate_setup_runs_in_isolation_and_redacts_logs(tmp_path):
    script = tmp_path / "setup.py"
    script.write_text(
        "from pathlib import Path\nPath('node_modules').mkdir()\nPath('node_modules/ready').write_text('ready')\nprint('API_KEY=private-fixture-secret')\n"
    )
    await core._setup_candidate(tmp_path, f'"{sys.executable}" setup.py', tmp_path / "logs")
    assert (tmp_path / "node_modules/ready").read_text() == "ready"
    output = (tmp_path / "logs/setup_stdout.txt").read_text()
    assert "private-fixture-secret" not in output and "REDACTED" in output


@pytest.mark.asyncio
async def test_ipv6_only_preview_returns_actual_ready_origin_and_stops(tmp_path):
    import socket

    from design_toolkit.tools.preview import preview_start, preview_stop

    try:
        with socket.socket(socket.AF_INET6) as probe:
            probe.bind(("::1", 0))
            port = probe.getsockname()[1]
    except OSError:
        pytest.skip("IPv6 loopback unavailable")
    (tmp_path / "index.html").write_text("<!doctype html><title>IPv6 fixture</title>")
    result = await preview_start(
        command=[sys.executable, "-m", "http.server", "{port}", "--bind", "::1"],
        cwd=tmp_path,
        port=port,
        wait_timeout_s=5,
    )
    assert result["status"] == "passed", result
    try:
        assert result["url"] == f"http://[::1]:{port}"
    finally:
        stopped = await preview_stop(pid=result["pid"])
        assert stopped["ok"] and result["pid"] in stopped["stopped_pids"]
