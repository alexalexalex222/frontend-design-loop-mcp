"""preview - start and stop dev servers, wait for HTTP readiness."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from design_toolkit.utils import log


def pick_preview_port(*, idx: int = 0, base: int = 3100, stride: int = 25) -> int:
    """Pick an available port for a preview server."""
    base = int(os.getenv("DESIGN_TOOLKIT_PORT_START", str(base)))
    stride = int(os.getenv("DESIGN_TOOLKIT_PORT_STRIDE", str(stride)))
    if stride < 1:
        stride = 25

    port_start = base + (idx * stride)
    for offset in range(stride):
        port = port_start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue

    raise RuntimeError(f"No available port found in range {port_start}-{port_start + stride - 1}")


async def wait_for_http(url: str, *, timeout_s: float = 30.0) -> tuple[bool, str]:
    """Wait for a URL to respond with HTTP 2xx-4xx."""
    start = asyncio.get_event_loop().time()
    last_err = ""

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        while asyncio.get_event_loop().time() - start < timeout_s:
            try:
                response = await client.get(url)
                if 200 <= response.status_code < 500:
                    return True, ""
                last_err = f"HTTP {response.status_code}"
            except Exception as exc:
                last_err = str(exc)
            await asyncio.sleep(0.35)

    return False, last_err


@dataclass
class PreviewServer:
    """A running preview server."""

    pid: int
    port: int
    url: str
    process: asyncio.subprocess.Process


_active_servers: dict[int, PreviewServer] = {}


async def preview_start(
    *,
    command: str,
    cwd: Path,
    port: int | None = None,
    idx: int = 0,
    wait_timeout_s: float = 30.0,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Start a preview server and wait for it to be ready."""
    if port is None:
        port = pick_preview_port(idx=idx)

    env = dict(os.environ)
    env["PORT"] = str(port)
    if env_overrides:
        env.update(env_overrides)

    cmd = command.replace("$PORT", str(port)).replace("${PORT}", str(port))

    log(f"Starting preview: {cmd} (port={port}, cwd={cwd})")

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
        env=env,
    )

    url = f"http://127.0.0.1:{port}"
    ok, err = await wait_for_http(url, timeout_s=wait_timeout_s)

    if not ok:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return {"error": f"Preview server failed to start: {err}", "port": port}

    server = PreviewServer(pid=proc.pid, port=port, url=url, process=proc)
    _active_servers[proc.pid] = server

    log(f"Preview ready: {url} (pid={proc.pid})")
    return {"url": url, "port": port, "pid": proc.pid}


async def preview_stop(*, pid: int | None = None) -> dict[str, Any]:
    """Stop a preview server by PID, or stop all if pid is None."""
    stopped: list[int] = []

    if pid is not None:
        server = _active_servers.pop(pid, None)
        if server:
            try:
                server.process.terminate()
                await asyncio.wait_for(server.process.wait(), timeout=5.0)
            except Exception:
                try:
                    server.process.kill()
                    await server.process.wait()
                except Exception:
                    pass
            stopped.append(pid)
            log(f"Preview stopped: pid={pid}")
        else:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped.append(pid)
            except Exception:
                pass
    else:
        for active_pid, server in list(_active_servers.items()):
            try:
                server.process.terminate()
                await asyncio.wait_for(server.process.wait(), timeout=5.0)
            except Exception:
                try:
                    server.process.kill()
                    await server.process.wait()
                except Exception:
                    pass
            stopped.append(active_pid)
        _active_servers.clear()
        log(f"All preview servers stopped ({len(stopped)} total)")

    return {"ok": True, "stopped_pids": stopped}
