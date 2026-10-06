"""Portable, provider-free release check against a clean pip or uv tool install.

Run with --artifact <wheel-or-sdist> --out-dir <new-directory> [--installer uv].
The resulting JSON, logs and browser evidence can be retained by CI. This tests
the installed toolkit and automated evaluator; it never invokes a model.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_bytes((json.dumps(value, indent=2) + "\n").encode("utf-8"))
    temporary.replace(path)


def clean_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        if key.upper() in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} or key.upper().startswith(
            ("FRONTEND_DESIGN_LOOP_", "DESIGN_TOOLKIT_")
        ):
            del env[key]
    return env


def run_logged(argv: list[str], *, cwd: Path, env: dict[str, str], log: Path) -> None:
    with log.open("wb") as stream:
        result = subprocess.run(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, timeout=600,
        )
    if result.returncode:
        raise RuntimeError(f"Command failed with exit {result.returncode}; see {log}")


def executable(directory: Path, name: str) -> Path:
    return directory / ("Scripts" if os.name == "nt" else "bin") / (
        name + ".exe" if os.name == "nt" else name
    )


def payload(result) -> dict:
    assert not result.isError, result
    value = result.structuredContent
    if value is None:
        value = json.loads(next(item.text for item in result.content if item.type == "text"))
    assert isinstance(value, dict), value
    return value


async def exercise_toolkit(out: Path) -> dict:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    assert importlib.util.find_spec("google") is None, "Cloud extras leaked into clean install"
    directory = Path(sys.prefix)
    for name in ("frontend-design-toolkit-mcp", "frontend-design-loop-mcp", "frontend-design-loop-setup"):
        assert executable(directory, name).is_file(), name
    project = out / "project spaces & forms \u96ea"
    project.mkdir()
    (project / "index.html").write_bytes(b'''<!doctype html><html lang="en">
<meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Installed Windows workflow</title>
<style>body{font:18px system-ui;margin:24px;max-width:50rem}input,button{font:inherit;padding:12px;box-sizing:border-box;max-width:100%}form{display:grid;gap:16px}label{display:grid;gap:8px}</style>
<h1>Local preview</h1><form id="form"><label>Your name<input id="name" required autocomplete="name"></label><button>Continue</button></form><p id="result" aria-live="polite"></p>
<script>document.querySelector('#form').addEventListener('submit',event=>{event.preventDefault();document.querySelector('#result').textContent='Ready for '+document.querySelector('#name').value})</script></html>''')
    (project / "serve.cjs").write_bytes(b'''const http=require('node:http'),fs=require('node:fs');
http.createServer((req,res)=>{if(req.url==='/favicon.ico'){res.writeHead(204);res.end();return;}res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync('index.html'));}).listen(Number(process.argv[2]),'127.0.0.1');''')
    (project / "gate.cjs").write_bytes(b"require('node:assert').ok(require('node:fs').readFileSync('index.html','utf8').includes('Local preview'));console.log('fixture gate passed');")
    write_json(project / "package.json", {
        "name": "installed-workflow-fixture", "version": "1.0.0", "private": True,
        "scripts": {"dev": "node serve.cjs", "test": "node gate.cjs"},
    })
    parameters = StdioServerParameters(
        command=str(executable(directory, "frontend-design-toolkit-mcp")),
        cwd=str(project), env=clean_environment(),
    )
    started = None
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            playbook = payload(await session.call_tool("get_playbook", {"name": "solve"}))
            assert playbook["content"], playbook
            gates = payload(await session.call_tool("run_gates", {
                "repo_path": str(project), "test_command": ["npm", "test"],
            }))
            assert gates["test_status"] == "passed" and gates["lint_status"] == "skipped", gates
            try:
                started = payload(await session.call_tool("preview_start", {
                    "command": ["npm", "run", "dev", "--", "{port}"],
                    "cwd": str(project), "wait_timeout_s": 30,
                }))
                assert started["status"] == "passed", started
                captured = await session.call_tool("capture_screenshots", {
                    "url": started["url"], "out_dir": str(out / "browser evidence"),
                    "viewports": [{"label": "mobile", "width": 375, "height": 812},
                                  {"label": "desktop", "width": 1440, "height": 900}],
                    "interactions": [
                        {"action": "fill", "selector": "#name", "value": "Casey"},
                        {"action": "click", "selector": "button"},
                        {"action": "expect_text", "selector": "#result", "value": "Ready for Casey"},
                    ],
                    "asset_policy": "same_origin",
                })
                manifest = payload(captured)
                assert manifest["status"] == "passed", manifest
                assert {item["label"] for item in manifest["viewports"]} == {"mobile", "desktop"}
                for viewport in manifest["viewports"]:
                    assert viewport["checks"]["interactions"]["status"] == "passed", viewport
                for shot in manifest["screenshots"]:
                    assert hashlib.sha256(Path(shot["path"]).read_bytes()).hexdigest() == shot["sha256"]
                images = [item for item in captured.content if item.type == "image"]
                assert len(images) == len(manifest["screenshots"]) >= 4
                assert all(base64.b64decode(item.data).startswith(b"\x89PNG\r\n\x1a\n") for item in images)
            finally:
                if started and "pid" in started:
                    stopped = payload(await session.call_tool("preview_stop", {"pid": started["pid"]}))
                    assert stopped["ok"], stopped
    deadline = time.monotonic() + 5
    while True:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            listening = sock.connect_ex(("127.0.0.1", started["port"])) == 0
        if not listening:
            break
        assert time.monotonic() < deadline, "Owned npm preview still listening after stop"
        time.sleep(0.05)
    return {
        "status": "passed", "viewports": ["mobile", "desktop"], "images": len(images),
        "npm_gate": "passed", "npm_preview": "passed", "interactions": "passed",
        "preview_port_released": True, "cloud_extras": "absent", "live_inference": "not_run",
    }


def verify(artifact: Path, out: Path, installer: str) -> None:
    if out.exists() and any(out.iterdir()):
        raise ValueError("out-dir must be empty so the install is demonstrably clean")
    out.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "running", "platform": platform.platform(), "machine": platform.machine(),
        "python": platform.python_version(), "installer": installer,
        "artifact": str(artifact), "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    receipt = out / "result.json"
    write_json(receipt, result)
    env = clean_environment()
    try:
        if installer == "pip":
            directory = out / "clean environment \u96ea"
            run_logged([sys.executable, "-I", "-m", "venv",
                        "--copies" if os.name == "nt" else "--symlinks", str(directory)],
                       cwd=out, env=env, log=out / "create-venv.log")
            python = executable(directory, "python")
            install = [str(python), "-I", "-m", "pip", "install", str(artifact)]
        else:
            uv = shutil.which("uv")
            if uv is None:
                raise RuntimeError("uv must be installed to verify the uv tool route")
            env.update({"UV_TOOL_DIR": str(out / "uv tools"), "UV_TOOL_BIN_DIR": str(out / "uv bin")})
            directory = out / "uv tools" / "frontend-design-loop-mcp"
            python = executable(directory, "python")
            install = [uv, "tool", "install", "--python", sys.executable, str(artifact)]
        run_logged(install, cwd=out, env=env, log=out / "install.log")
        run_logged([str(executable(directory, "frontend-design-loop-setup")), "--help"],
                   cwd=out, env=env, log=out / "setup-help.log")
        run_logged([str(python), "-I", "-m", "playwright", "install", "chromium"],
                   cwd=out, env=env, log=out / "browser-install.log")
        run_logged([str(python), "-I", str(Path(__file__).resolve()), "--exercise", str(out)],
                   cwd=out, env=env, log=out / "toolkit.log")
        result["toolkit"] = json.loads((out / "toolkit-result.json").read_text(encoding="utf-8"))
        env["FRONTEND_DESIGN_LOOP_MCP_OUT_DIR"] = str(out / "automated evidence")
        run_logged([str(python), "-I", str(Path(__file__).with_name("smoke_mcp_stdio.py").resolve()),
                    "--installed", "--preview"], cwd=out, env=env, log=out / "automated.log")
        result.update(status="passed", automated_stdio="passed", live_inference="not_run")
    except Exception as exc:
        result.update(status="failed", error=str(exc))
        raise
    finally:
        write_json(receipt, result)
    print(f"PASS clean {installer} install, toolkit/npm interactions, automated responsive eval; {ascii(str(receipt))}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--installer", choices=("pip", "uv"), default="pip")
    parser.add_argument("--distribution", choices=("wheel", "sdist"), default="wheel",
                        help="Select a single distribution when --artifact names a directory")
    parser.add_argument("--exercise", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.exercise is not None:
        import anyio

        async def check():
            with anyio.fail_after(120):
                return await exercise_toolkit(args.exercise)

        write_json(args.exercise / "toolkit-result.json", anyio.run(check))
    elif args.artifact is not None and args.out_dir is not None:
        artifact = args.artifact.resolve(strict=True)
        if artifact.is_dir():
            matches = list(artifact.glob("*.whl" if args.distribution == "wheel" else "*.tar.gz"))
            if len(matches) != 1:
                parser.error(f"Expected exactly one {args.distribution} in {artifact}")
            artifact = matches[0]
        verify(artifact, args.out_dir.resolve(), args.installer)
    else:
        parser.error("--artifact and --out-dir are required")


if __name__ == "__main__":
    main()
