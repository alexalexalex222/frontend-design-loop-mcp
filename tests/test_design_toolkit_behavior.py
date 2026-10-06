from __future__ import annotations

import os
import socket
import sys
from types import SimpleNamespace

import pytest

from design_toolkit.tools import context, gates, preview, screenshots


async def test_skipped_gates_are_not_passed(tmp_path):
    result = await gates.run_gates(repo_root=tmp_path)
    assert result.test_status == result.lint_status == "skipped"
    assert result.test_ok is None and result.test_rc is None


async def test_real_gate_pass_fail_timeout(tmp_path):
    script = tmp_path / "gate.py"
    script.write_text('import sys\nprint("evidence")\nsys.exit(int(sys.argv[1]))\n')
    result = await gates.run_gates(
        repo_root=tmp_path,
        test_command=[sys.executable, str(script), "0"],
        lint_command=[sys.executable, str(script), "3"],
    )
    assert result.test_status == "passed" and result.lint_status == "failed"
    assert result.test_stdout.strip() == "evidence" and result.lint_rc == 3
    script.write_text("import time\ntime.sleep(30)\n")
    result = await gates.run_gates(
        repo_root=tmp_path, test_command=[sys.executable, str(script)], timeout_ms=100
    )
    assert result.test_status == "error" and result.test_ok is None


def test_windows_command_and_argv(monkeypatch):
    monkeypatch.setattr(gates, "os", SimpleNamespace(name="nt"))
    assert (
        gates.prepare_command('"C:\\Program Files\\Python\\python.exe" -m pytest').argv[0]
        == "C:\\Program Files\\Python\\python.exe"
    )
    assert gates.prepare_command(["python", "-c", "print('a;b')"]).argv[-1] == "print('a;b')"
    with pytest.raises(ValueError):
        gates.prepare_command("npm test && npm build")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "file:///tmp/site",
        "http://user:secret@localhost/",
        "http://127.0.0.1.example.com",
        "http://0.0.0.0",
    ],
)
def test_external_preview_urls_rejected(url):
    with pytest.raises(ValueError):
        preview.validate_local_url(url)


def test_local_origin_binding():
    assert preview.validate_local_url("http://[::1]:3000/x") == "http://::1:3000"
    with pytest.raises(ValueError):
        preview.validate_local_url("http://localhost:3001", expected_origin="http://localhost:3000")


async def test_unknown_pid_never_signalled(monkeypatch):
    monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("must never signal arbitrary PID"))
    result = await preview.preview_stop(pid=987654321)
    assert result["ok"] is False and result["stopped_pids"] == []


@pytest.fixture
def loopback_allowed():
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip(
                "Environment denies loopback binding; real preview test requires an unrestricted runner"
            )


async def test_owned_preview_drains_chatty_output_and_stops(tmp_path, loopback_allowed):
    script = tmp_path / "serve.py"
    script.write_text(
        'import sys\nfrom http.server import HTTPServer, SimpleHTTPRequestHandler\nprint("x" * 200000, flush=True)\nprint("y" * 200000, file=sys.stderr, flush=True)\nHTTPServer(("127.0.0.1", int(sys.argv[1])), SimpleHTTPRequestHandler).serve_forever()\n'
    )
    result = await preview.preview_start(
        command=[sys.executable, str(script), "{port}"], cwd=tmp_path, wait_timeout_s=8
    )
    try:
        assert result["status"] == "passed"
        server = preview._active_servers[result["pid"]]
        assert len(server.logs["stdout"]) <= 16000
        assert "x" in server.logs["stdout"] and "y" in server.logs["stderr"]
    finally:
        stopped = await preview.preview_stop(pid=result["pid"])
    assert stopped["ok"] and stopped["stopped_pids"] == [result["pid"]]


async def test_failed_preview_cleaned_up(tmp_path, loopback_allowed):
    script = tmp_path / "fail.py"
    script.write_text(
        'import sys\nprint("failed launch", file=sys.stderr, flush=True)\nsys.exit(7)\n'
    )
    result = await preview.preview_start(
        command=[sys.executable, str(script)], cwd=tmp_path, wait_timeout_s=5
    )
    assert result["status"] == "error" and "failed launch" in result["logs"]["stderr"]
    assert not preview._active_servers


@pytest.mark.parametrize(
    "values", [[{"label": "../../escaped"}], [{"label": "x"}, {"label": "x"}], []]
)
def test_screenshot_filenames_validated(values):
    with pytest.raises(ValueError):
        screenshots._viewports(values)


async def test_context_query_is_argument_and_secret_files_excluded(tmp_path, monkeypatch):
    (tmp_path / "page.py").write_text("a useful needle")
    (tmp_path / ".env").write_text("needle = SECRET")
    monkeypatch.setattr(context.shutil, "which", lambda name: None)
    assert await context.auto_context_files(repo_root=tmp_path, queries=["needle"]) == ["page.py"]
    assert "SECRET" not in context.build_context_blob(
        repo_root=tmp_path, context_files=[".env", "../outside", "page.py"]
    )


def test_context_symlink_cannot_alias_credential_file(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("PRIVATE=unredacted value")
    alias = tmp_path / "public.txt"
    try:
        alias.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    assert context.build_context_blob(repo_root=tmp_path, context_files=["public.txt"]) == ""


def test_image_manifest_has_pixel_dimensions_and_hash(tmp_path):
    import hashlib
    import struct

    # Exercise PNG manifest metadata without a browser or subjective rendering claim.
    data = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 375, 2000)
    path = tmp_path / "mobile.png"
    path.write_bytes(data)
    result = screenshots._shot(
        path, {"label": "mobile", "width": 375, "height": 812}, "initial", True
    )
    assert result["height"] == 812 and result["image_height"] == 2000
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


async def test_mcp_capture_returns_labeled_image_content(tmp_path, monkeypatch):
    import base64

    from design_toolkit import server

    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9JkAAAAASUVORK5CYII="
    )
    path = tmp_path / "desktop.png"
    path.write_bytes(data)
    shot = screenshots._shot(
        path, {"label": "desktop", "width": 1440, "height": 900}, "initial", True
    )
    manifest = {
        "schema_version": 1,
        "status": "passed",
        "screenshots": [shot],
        "out_dir": str(tmp_path),
    }

    async def evidence(**kwargs):
        return manifest

    monkeypatch.setattr(server.screens_mod, "capture_evidence", evidence)
    result = await server.capture_screenshots("http://127.0.0.1:3100", evidence_label="baseline")
    assert result.structuredContent == manifest and not result.isError
    images = [item for item in result.content if item.type == "image"]
    assert len(images) == 1 and base64.b64decode(images[0].data) == data
    assert any(
        "baseline: desktop / initial" in item.text for item in result.content if item.type == "text"
    )
    result = await server.capture_screenshots("http://127.0.0.1:3100", include_images=False)
    assert all(item.type != "image" for item in result.content)


async def test_capture_does_not_mutate_input_styles_during_client_startup(tmp_path, loopback_allowed):
    pytest.importorskip("playwright.async_api")
    (tmp_path / "index.html").write_text("""<!doctype html><title>Delayed client startup</title>
      <input id="field" autocomplete="name"><p id="ready" hidden>Client ready</p>
      <p id="result">unchanged</p><div style="height:2000px"></div>
      <script>
        let changed = false;
        new MutationObserver(records => {
          if (records.some(record => record.target.id === 'field')) changed = true;
          document.querySelector('#result').textContent = changed ? 'mutated' : 'unchanged';
        }).observe(document.documentElement, {subtree:true, attributes:true, attributeFilter:['style']});
        setTimeout(() => { document.querySelector('#ready').hidden = false; }, 500);
      </script>""")
    started = await preview.preview_start(
        command=[sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"],
        cwd=tmp_path, wait_timeout_s=10,
    )
    try:
        assert started["status"] == "passed", started
        manifest = await screenshots.capture_evidence(
            url=started["url"], out_dir=tmp_path / "proof",
            viewports=[{"label":"mobile", "width":375, "height":812}, {"label":"desktop", "width":1440, "height":900}],
            interactions=[{"action":"expect_visible", "selector":"#ready"}, {"action":"fill", "selector":"#field", "value":"Casey"}, {"action":"expect_text", "selector":"#result", "value":"unchanged"}],
            timeout_ms=10000,
        )
        assert manifest["status"] == "passed", manifest
        assert len(manifest["screenshots"]) == 6
    finally:
        assert (await preview.preview_stop(pid=started["pid"]))["ok"]
