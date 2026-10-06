"""Per-request role settings and auditable model execution records."""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import struct
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import anyio

role_settings: ContextVar[dict[str, Any]] = ContextVar("role_settings", default={})
execution_dir: ContextVar[Path | None] = ContextVar("execution_dir", default=None)
current_images: ContextVar[list[Path]] = ContextVar("current_images", default=[])
baseline_images: ContextVar[list[Path]] = ContextVar("baseline_images", default=[])
cleanup_callbacks: ContextVar[list[Any]] = ContextVar("cleanup_callbacks", default=[])


def with_execution_context(fn):
    """Keep settings isolated across concurrent MCP requests and candidate tasks."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        inherited = dict(role_settings.get())
        inherited.update(
            {
                key: bound.arguments[key]
                for key in (
                    "auth_mode",
                    "planner_effort",
                    "builder_effort",
                    "refiner_effort",
                    "judge_effort",
                    "interaction_steps",
                )
                if key in bound.arguments
            }
        )
        tokens = [
            (role_settings, role_settings.set(inherited)),
            (execution_dir, execution_dir.set(execution_dir.get())),
            (current_images, current_images.set([])),
            (baseline_images, baseline_images.set([])),
            (cleanup_callbacks, cleanup_callbacks.set([])),
        ]
        try:
            return await fn(*args, **kwargs)
        finally:
            original_error = sys.exc_info()[0]
            failures = []
            try:
                with anyio.CancelScope(shield=True):
                    for cleanup in reversed(cleanup_callbacks.get()):
                        try:
                            await cleanup()
                        except BaseException as exc:
                            failures.append(exc)
            finally:
                for variable, token in reversed(tokens):
                    variable.reset(token)
            if failures and original_error is None:
                raise failures[0]

    return wrapped


def execution_options(role: str | None, fallback_effort: str | None = None) -> dict[str, Any]:
    settings = role_settings.get()
    name = str(role or "")
    if name.startswith("planner"):
        key = "planner_effort"
    elif name in {"vision_broken", "vision_score", "section_creativity", "judge"}:
        key = "judge_effort"
    elif "fix" in name or "refin" in name:
        key = "refiner_effort"
    else:
        key = "builder_effort"
    return {
        "reasoning_profile": settings.get(key, fallback_effort or "high"),
        "auth_mode": settings.get("auth_mode", "subscription"),
    }


def image_manifest(paths: list[Path], *, revision: str) -> list[dict[str, Any]]:
    result = []
    for index, path in enumerate(paths):
        data = path.read_bytes()
        dimensions = (
            struct.unpack(">II", data[16:24])
            if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24
            else (None, None)
        )
        capture_info = {}
        manifest_path = path.parent / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            capture_info = next(
                (shot for shot in manifest.get("screenshots", []) if shot.get("path") == str(path)),
                {},
            )
        result.append(
            {
                "image_index": index,
                "label": path.stem,
                "revision": revision,
                "path": str(path),
                "sha256": hashlib.sha256(data).hexdigest(),
                "viewport_width": capture_info.get("width"),
                "viewport_height": capture_info.get("height"),
                "state": capture_info.get("state", path.stem),
                "image_width": dimensions[0],
                "image_height": dimensions[1],
            }
        )
    return result


def record_execution(role: str, model: str, system: str, user: str, response: Any) -> None:
    directory = execution_dir.get()
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    # Metadata is supplied by adapters; don't persist native transcripts or hidden thinking.
    raw = getattr(response, "raw_response", None) or {}
    metadata = raw.get("execution", {}) if isinstance(raw, dict) else {}
    from design_toolkit.tools.context import redact_sensitive_text

    record = {
        "role": role,
        "requested_model": model,
        "options": execution_options(role),
        "system_prompt": system,
        "user_prompt": user,
        "execution": metadata,
        "response": redact_sensitive_text(getattr(response, "content", "")),
    }
    path = directory / f"{role or 'completion'}_{uuid.uuid4().hex[:10]}.json"
    temporary = path.with_suffix(".json.new")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
