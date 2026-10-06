"""Owned preview handles, continuously drained logs, and loopback readiness."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from design_toolkit.tools.context import redact_sensitive_text
from design_toolkit.tools.gates import prepare_command
from frontend_design_loop_core.utils import managed_process_argv


def validate_local_url(url: str, *, expected_origin: str | None = None) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Use a loopback http(s) URL without credentials")
    host = parsed.hostname.lower()
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if not local:
        raise ValueError("Preview and screenshot URLs must use localhost or a loopback IP")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    origin = f"{parsed.scheme}://{host}:{port}"
    if expected_origin is not None and origin != expected_origin:
        raise ValueError("Navigation left the requested local origin")
    return origin


def _check_port(port: int) -> None:
    # Probe both families: a Vite/Node localhost listener may be IPv6-only.
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family) as sock:
                sock.bind((address, port))
        except OSError as exc:
            import errno

            if family == socket.AF_INET6 and exc.errno in {
                errno.EAFNOSUPPORT,
                errno.EADDRNOTAVAIL,
                errno.EPROTONOSUPPORT,
            }:
                continue
            raise


def pick_preview_port(*, idx: int = 0, base: int = 3100, stride: int = 25) -> int:
    base = int(os.getenv("DESIGN_TOOLKIT_PORT_START", str(base)))
    stride = int(os.getenv("DESIGN_TOOLKIT_PORT_STRIDE", str(stride)))
    if stride < 1:
        raise ValueError("Port stride must be positive")
    for port in range(base + idx * stride, base + (idx + 1) * stride):
        if not 1 <= port <= 65535:
            raise ValueError("Port must be in 1..65535")
        try:
            _check_port(port)
            return port
        except PermissionError as exc:
            raise PermissionError(
                "Loopback binding is denied by this environment; preview cannot be verified"
            ) from exc
        except OSError:
            continue
    raise RuntimeError("No available preview port; choose a different port range")


async def wait_for_http(
    url: str, *, timeout_s: float = 30.0, process: asyncio.subprocess.Process | None = None
) -> tuple[bool, str]:
    validate_local_url(url)
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("wait_timeout_s must be finite and positive")
    deadline = asyncio.get_running_loop().time() + timeout_s
    last_error = "No response"
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
        while asyncio.get_running_loop().time() < deadline:
            if process is not None and process.returncode is not None:
                return False, f"Preview exited with {process.returncode}"
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                response = await client.get(url, timeout=min(2.0, max(0.01, remaining)))
                # A local redirect proves listening, but 404 is not a usable preview.
                if 200 <= response.status_code < 400:
                    if response.is_redirect:
                        from urllib.parse import urljoin

                        validate_local_url(
                            urljoin(url, response.headers.get("location", "")),
                            expected_origin=validate_local_url(url),
                        )
                    return True, ""
                last_error = f"HTTP {response.status_code}"
            except ValueError:
                raise
            except httpx.HTTPError as exc:
                last_error = str(exc)
            await asyncio.sleep(min(0.15, max(0, deadline - asyncio.get_running_loop().time())))
    return False, last_error


@dataclass
class PreviewServer:
    pid: int
    port: int
    url: str
    process: asyncio.subprocess.Process
    context: Any
    logs: dict[str, str] = field(default_factory=lambda: {"stdout": "", "stderr": ""})
    drains: list[asyncio.Task] = field(default_factory=list)


_active_servers: dict[int, PreviewServer] = {}


async def _drain(stream: asyncio.StreamReader, server: PreviewServer, label: str) -> None:
    while chunk := await stream.read(8192):
        server.logs[label] = (server.logs[label] + chunk.decode("utf-8", errors="replace"))[
            -16_000:
        ]


async def _close(server: PreviewServer) -> None:
    try:
        await server.context.__aexit__(None, None, None)
    finally:
        for task in server.drains:
            task.cancel()
        await asyncio.gather(*server.drains, return_exceptions=True)


async def preview_start(
    *,
    command: str | list[str],
    cwd: Path,
    port: int | None = None,
    idx: int = 0,
    wait_timeout_s: float = 30.0,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not cwd.is_dir():
        raise ValueError("Preview cwd must be an existing directory")
    if not math.isfinite(wait_timeout_s) or wait_timeout_s <= 0:
        raise ValueError("wait_timeout_s must be finite and positive")
    port = pick_preview_port(idx=idx) if port is None else port
    if not 1 <= port <= 65535:
        raise ValueError("Port must be in 1..65535")
    # Refuse pre-existing listeners in either address family.
    try:
        _check_port(port)
    except PermissionError:
        raise
    except OSError as exc:
        raise ValueError(f"Port {port} is already in use; choose a free port") from exc

    def expand(value: str) -> str:
        return (
            value.replace("${PORT}", str(port))
            .replace("$PORT", str(port))
            .replace("{port}", str(port))
        )

    expanded = [expand(item) for item in command] if isinstance(command, list) else expand(command)
    prepared = prepare_command(expanded)
    if prepared is None:
        raise ValueError("Preview command must be nonempty")
    env = {**os.environ, **(env_overrides or {}), "PORT": str(port)}
    context = managed_process_argv(prepared.argv, cwd=cwd, env=env)
    proc = await context.__aenter__()
    server = PreviewServer(proc.pid, port, f"http://127.0.0.1:{port}", proc, context)
    _active_servers[proc.pid] = server
    for label in ("stdout", "stderr"):
        server.drains.append(asyncio.create_task(_drain(getattr(proc, label), server, label)))
    try:

        async def readiness(target):
            ok, detail = await wait_for_http(target, timeout_s=wait_timeout_s, process=proc)
            return ok, detail, target

        probes = [
            asyncio.create_task(readiness(target))
            for target in (server.url, f"http://[::1]:{port}")
        ]
        ok, detail = False, "No response from loopback addresses"
        try:
            for completed in asyncio.as_completed(probes):
                available, failure, target = await completed
                if available:
                    ok, server.url = True, target
                    break
                detail = failure
        finally:
            for probe in probes:
                if not probe.done():
                    probe.cancel()
            await asyncio.gather(*probes, return_exceptions=True)
        if not ok:
            logs = {key: redact_sensitive_text(value) for key, value in server.logs.items()}
            await preview_stop(pid=proc.pid)
            return {"status": "error", "error": detail, "port": port, "logs": logs}
        return {"status": "passed", "url": server.url, "port": port, "pid": proc.pid}
    except BaseException:
        await preview_stop(pid=proc.pid)
        raise


async def preview_stop(*, pid: int | None = None) -> dict[str, Any]:
    if pid is not None and pid not in _active_servers:
        return {
            "status": "error",
            "ok": False,
            "error": "PID is not an owned preview handle",
            "stopped_pids": [],
        }
    selected = [pid] if pid is not None else list(_active_servers)
    stopped, errors = [], []
    for key in selected:
        server = _active_servers[key]
        try:
            await _close(server)
            _active_servers.pop(key, None)
            stopped.append(key)
        except Exception as exc:
            errors.append({"pid": key, "error": str(exc)})
    return {
        "status": "error" if errors else "passed",
        "ok": not errors,
        "stopped_pids": stopped,
        "errors": errors,
    }
