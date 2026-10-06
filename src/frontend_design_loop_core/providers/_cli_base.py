"""Native CLI transport, process ownership and honest execution receipts."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar

from frontend_design_loop_core.cli_paths import resolve_native_cli
from frontend_design_loop_core.config import Config
from frontend_design_loop_core.reasoning_prompts import compose_native_cli_overlay
from frontend_design_loop_core.utils import run_process_argv

from .base import CompletionResponse, LLMProvider, Message


class NativeCLIError(RuntimeError):
    """A sanitized failure with the same receipt shape as a successful call."""

    def __init__(self, message: str, *, execution: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.execution = execution


def _stringify_content(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content.strip()
    return "\n\n".join(
        str(item.get("text") or item.get("content") or "").strip()
        for item in content
        if isinstance(item, dict)
    ).strip()


def _flatten_messages(messages: list[Message]) -> str:
    return "\n\n".join(
        f"{message.role.upper()}:\n{text}"
        for message in messages
        if (text := _stringify_content(message.content))
    )


def json_events(text: str) -> list[dict[str, Any]]:
    """Accept a JSON object or JSONL, never promote plain text to a receipt."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, list) and all(isinstance(item, dict) for item in obj):
            return obj
    except ValueError:
        pass
    events = []
    for line in text.splitlines():
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                events.append(obj)
        except ValueError:
            pass
    return events


def safe_diagnostic(text: str, env: dict[str, str] | None = None) -> str:
    """Redact known secrets and common credential formats before surfacing errors."""
    for key, value in (env or {}).items():
        if value and any(part in key.upper() for part in ("TOKEN", "SECRET", "KEY", "PASSWORD")):
            text = text.replace(value, "[redacted]")
    text = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[redacted]", text)
    text = re.sub(r"\b(?:sk-|sk_ant-|sk-ant-|ghp_|github_pat_)[A-Za-z0-9_-]+", "[redacted]", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|token)[\"']?\s*[=:]\s*[\"']?)[^\s,}\"']+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[redacted]", text)
    text = re.sub(r"(https?://)[^/\s:@]+:[^/@\s]+@", r"\1[redacted]@", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted email]", text)
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    return text.strip()[:1200]


def native_failure_diagnostic(stdout: str, env: dict[str, str]) -> str:
    # Extract native error fields only; never expose ordinary transcript/prompt text.
    for event in reversed(json_events(stdout)):
        if event.get("type") != "error":
            continue
        error = event.get("error") or {}
        data = error.get("data") or {} if isinstance(error, dict) else {}
        message = data.get("message") or event.get("message")
        if isinstance(message, str):
            return safe_diagnostic(message, env)
    return ""


class NativeCLIProvider(LLMProvider):
    cache_scope: ClassVar[str] = "none"
    cli_name: ClassVar[str] = ""
    supports_vision: ClassVar[bool] = False
    supports_repository_edit: ClassVar[bool] = False
    strict_native: ClassVar[bool] = False
    stdin_prompt: ClassVar[bool] = False
    vision_transport: ClassVar[str] = "none"
    env_allowlist_keys: ClassVar[set[str]] = set()
    env_allowlist_prefixes: ClassVar[tuple[str, ...]] = ()

    def __init__(self, config: Config) -> None:
        self.config = config

    def _controls(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        controls = dict(kwargs)
        controls["auth_mode"] = (
            str(kwargs.get("auth_mode") or ("subscription" if self.strict_native else "configured"))
            .strip()
            .lower()
        )
        controls["reasoning_profile"] = (
            str(kwargs.get("reasoning_profile") or ("high" if self.strict_native else ""))
            .strip()
            .lower()
        )
        if self.strict_native:
            unknown = set(kwargs) - {
                "reasoning_profile",
                "auth_mode",
                "timeout_s",
                "cwd",
                "env",
                "prompt_role",
                "operation",
            }
            if unknown:
                raise NativeCLIError("Unsupported native controls: " + ", ".join(sorted(unknown)))
            if controls["auth_mode"] not in {"subscription", "api_key", "configured"}:
                raise NativeCLIError("auth_mode must be subscription, api_key, or configured")
            # Aliases obscure which runtime control was requested. Leave exact native
            # values intact and let capability preflight reject unsupported ones.
            if controls["reasoning_profile"] == "off":
                raise NativeCLIError(
                    f"Unsupported reasoning_profile: {controls['reasoning_profile']}; select a native effort/variant"
                )
        else:
            self._validate_auth_mode(controls, allowed={"configured", "api_key"})
        return controls

    def _build_prompt(
        self,
        messages: list[Message],
        *,
        model: str,
        kwargs: dict[str, Any],
        image_paths: list[Path] | None = None,
    ) -> str:
        prompt = _flatten_messages(messages)
        overlay = self._reasoning_overlay(messages=messages, model=model, kwargs=kwargs)
        if overlay:
            prompt = f"{overlay}\n\n{prompt}".strip()
        if image_paths and self.vision_transport == "workspace_files":
            files = "\n".join(f"- {path}" for path in image_paths)
            prompt = f"VISUAL INPUT FILES\nInspect these screenshot files before judging. Report unreadable evidence as unknown.\n{files}\n\n{prompt}"
        return prompt

    def _reasoning_overlay(
        self, *, messages: list[Message], model: str, kwargs: dict[str, Any]
    ) -> str:
        system_prompt = next(
            (_stringify_content(m.content) for m in messages if m.role == "system"), ""
        )
        return compose_native_cli_overlay(
            provider_name=self.name,
            model=model,
            reasoning_profile=kwargs.get("reasoning_profile"),
            system_prompt=system_prompt,
            prompt_role=kwargs.get("prompt_role"),
            prompt_root=self.config.prompts_path,
        )

    def _build_env(self, kwargs: dict[str, Any]) -> dict[str, str]:
        base_keys = {
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TERM",
            "TERMINFO",
            "TMPDIR",
            "TMP",
            "TEMP",
            "USER",
            "LOGNAME",
            "SHELL",
            "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME",
            "XDG_DATA_HOME",
            "NO_COLOR",
            "COLORTERM",
            "VIRTUAL_ENV",
            "__CF_USER_TEXT_ENCODING",
            "SystemRoot",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
        }
        subscription = (
            self.strict_native and kwargs.get("auth_mode", "subscription") == "subscription"
        )
        native_locations = {"CODEX_HOME", "CLAUDE_CONFIG_DIR"}
        env = {
            k: v
            for k, v in os.environ.items()
            if k in base_keys
            or k in native_locations
            or (
                not subscription
                and (
                    k in self.env_allowlist_keys
                    or any(k.startswith(p) for p in self.env_allowlist_prefixes)
                )
            )
            or k.startswith("FRONTEND_DESIGN_LOOP_")
        }
        explicit = kwargs.get("env") or {}
        if subscription:
            forbidden = [
                k
                for k in explicit
                if k not in base_keys | native_locations
                and not k.startswith("FRONTEND_DESIGN_LOOP_")
            ]
            if forbidden:
                # Report keys only, never values or credential files.
                raise NativeCLIError(
                    "Subscription mode rejects environment overrides: "
                    + ", ".join(sorted(forbidden))
                )
        env.update({k: str(v) for k, v in explicit.items()})
        return env

    async def _probe(
        self, args: list[str], *, env: dict[str, str], cwd: Path, timeout_s: float = 20.0
    ) -> tuple[int, str, str]:
        try:
            executable_args = [resolve_native_cli(args[0], env=env, cwd=cwd), *args[1:]]
            return await run_process_argv(executable_args, cwd, env=env, timeout_s=timeout_s)
        except asyncio.TimeoutError as exc:
            raise NativeCLIError(f"{self.name} capability/auth preflight timed out") from exc
        except OSError as exc:
            raise NativeCLIError(
                f"{self.cli_name} unavailable; install the native CLI and sign in separately"
            ) from exc
        except ValueError as exc:
            raise NativeCLIError(safe_diagnostic(str(exc), env)) from exc

    async def _preflight(
        self,
        *,
        model: str,
        kwargs: dict[str, Any],
        env: dict[str, str],
        cwd: Path,
        timeout_s: float,
    ) -> dict[str, Any]:
        return {"auth_mode": None, "model_availability": "unknown", "reasoning_profile": None}

    async def preflight(self, model: str, **kwargs: Any) -> dict[str, Any]:
        """Read-only CLI/help/auth checks; never loads or prints credential files."""
        controls = self._controls(kwargs)
        timeout = float(20.0 if controls.get("timeout_s") is None else controls["timeout_s"])
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_s must be finite and positive")
        with tempfile.TemporaryDirectory(prefix="frontend-design-loop-preflight-") as tmp:
            controls["runtime_dir"] = Path(tmp)
            try:
                return await asyncio.wait_for(
                    self._preflight(
                        model=model,
                        kwargs=controls,
                        env=self._build_env(controls),
                        cwd=Path(tmp),
                        timeout_s=timeout,
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                raise NativeCLIError(f"{self.name} capability/auth preflight timed out") from exc

    def _extract_content(
        self, *, stdout_text: str, stderr_text: str, output_file: Path | None
    ) -> str:
        if output_file is not None and output_file.exists():
            return output_file.read_text(encoding="utf-8").strip()
        return stdout_text.strip()

    def _observed_execution(self, stdout_text: str) -> dict[str, Any]:
        return {}

    def _build_command(
        self,
        *,
        model: str,
        prompt: str,
        cwd: Path | None,
        kwargs: dict[str, Any],
        images: list[Path] | None = None,
        output_file: Path | None = None,
    ) -> list[str]:
        raise NotImplementedError

    async def _run_cli(
        self,
        *,
        args: list[str],
        cwd: Path | None,
        env: dict[str, str],
        timeout_s: float,
        output_file: Path | None = None,
        input_text: str | None = None,
    ) -> CompletionResponse:
        try:
            rc, stdout, stderr = await run_process_argv(
                [resolve_native_cli(args[0], env=env, cwd=cwd), *args[1:]],
                cwd,
                env=env,
                timeout_s=timeout_s,
                input_text=input_text,
            )
        except asyncio.TimeoutError as exc:
            raise NativeCLIError(
                f"{self.name} timed out after {timeout_s:.1f}s; process tree stopped"
            ) from exc
        except OSError as exc:
            raise NativeCLIError(f"{self.name} could not start its native CLI") from exc
        except ValueError as exc:
            raise NativeCLIError(safe_diagnostic(str(exc), env)) from exc
        if rc != 0:
            # Stdout may contain the entire user prompt; only use sanitized stderr.
            raise NativeCLIError(
                f"{self.name} failed (exit {rc}): {safe_diagnostic(stderr, env) or native_failure_diagnostic(stdout, env) or 'no safe diagnostic'}"
            )
        try:
            content = self._extract_content(
                stdout_text=stdout, stderr_text=stderr, output_file=output_file
            )
            observed = self._observed_execution(stdout)
        except RuntimeError as exc:
            raise NativeCLIError(safe_diagnostic(str(exc), env)) from None
        if not content:
            raise NativeCLIError(f"{self.name} returned empty output")
        return CompletionResponse(
            content=content,
            model="",
            raw_response={
                "execution": {"observed": observed},
                "process": {
                    "exit_code": rc,
                    "prompt_transport": "stdin" if input_text is not None else "argv",
                    "stderr_present": bool(stderr.strip()),
                },
            },
        )

    async def _execute(
        self,
        messages: list[Message],
        model: str,
        *,
        images: list[bytes] | None,
        repo_path: Path | None,
        max_tokens: int,
        temperature: float,
        kwargs: dict[str, Any],
    ) -> CompletionResponse:
        controls = self._controls(kwargs)
        operation = (
            "edit_repository"
            if repo_path is not None
            else "vision"
            if images is not None
            else "complete"
        )
        controls["operation"] = operation
        controls["has_images"] = bool(images)
        timeout_s = float(300.0 if controls.get("timeout_s") is None else controls["timeout_s"])
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        if not str(model).strip() or model.startswith("-"):
            raise ValueError("A nonempty explicit native model is required")
        execution = {
            "requested": {
                "provider": self.name,
                "model": model,
                "reasoning_profile": controls["reasoning_profile"],
                "auth_mode": controls["auth_mode"],
                "operation": operation,
                "timeout_s": timeout_s,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            "observed": {"model": None, "reasoning_profile": None, "auth_mode": None},
            "unsupported_controls": ["max_tokens", "temperature"],
        }
        deadline = time.monotonic() + timeout_s
        try:
            with tempfile.TemporaryDirectory(prefix=f"frontend-design-loop-{self.name}-") as tmp:
                tmp_dir = Path(tmp)
                # Completion/judging has no need to inherit the caller's repository,
                # configs, hooks or tools. Editing explicitly names its isolated root.
                cwd = repo_path or (
                    tmp_dir
                    if self.strict_native or self.vision_transport == "workspace_files"
                    else Path(str(controls.get("cwd") or os.getcwd())).resolve()
                )
                controls["runtime_dir"] = tmp_dir
                env = self._build_env(controls)
                try:
                    facts = await asyncio.wait_for(
                        self._preflight(
                            model=model,
                            kwargs=controls,
                            env=env,
                            cwd=tmp_dir,
                            timeout_s=min(20.0, timeout_s),
                        ),
                        timeout=min(20.0, timeout_s),
                    )
                except asyncio.TimeoutError as exc:
                    raise NativeCLIError(f"{self.name} timed out during preflight") from exc
                execution["preflight"] = facts
                execution["observed"]["auth_mode"] = facts.get("auth_mode")
                execution["observed"]["auth_source"] = facts.get("auth_source")
                paths = []
                for idx, data in enumerate(images or []):
                    extension = ".jpg" if data.startswith(b"\xff\xd8\xff") else ".png"
                    path = tmp_dir / f"image_{idx}{extension}"
                    path.write_bytes(data)
                    paths.append(path)
                controls["image_paths"] = paths
                prompt = self._build_prompt(
                    messages, model=model, kwargs=controls, image_paths=paths
                )
                output_file = tmp_dir / "last_message.txt" if self.name == "codex_cli" else None
                args = self._build_command(
                    model=model,
                    prompt=prompt,
                    cwd=cwd,
                    kwargs=controls,
                    images=paths or None,
                    output_file=output_file,
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NativeCLIError(f"{self.name} timed out during preflight")
                run_kwargs = dict(
                    args=args, cwd=cwd, env=env, timeout_s=remaining, output_file=output_file
                )
                if self.stdin_prompt:
                    run_kwargs["input_text"] = prompt
                response = await self._run_cli(**run_kwargs)
                raw = response.raw_response or {}
                execution["observed"].update(raw.get("execution", {}).get("observed", {}))
                observed = execution["observed"]
                if self.name == "claude_cli" and paths:
                    read_paths = set(observed.get("verified_image_reads", []))
                    if not all(str(path) in read_paths for path in paths):
                        raise NativeCLIError(
                            "Claude did not provide successful native image-read evidence for every supplied screenshot"
                        )
                if self.strict_native:
                    if observed.get("model") is not None and observed["model"] != model:
                        raise NativeCLIError(
                            f"{self.name} reported a different model; automatic fallback is forbidden"
                        )
                    if (
                        observed.get("reasoning_profile") is not None
                        and observed["reasoning_profile"] != controls["reasoning_profile"]
                    ):
                        raise NativeCLIError(
                            f"{self.name} reported a different effort; automatic remapping is forbidden"
                        )
                response.model = (
                    model  # Compatibility identifier; observed model lives in the receipt.
                )
                response.raw_response = {"execution": execution, "process": raw.get("process", {})}
                return response
        except NativeCLIError as exc:
            exc.execution = execution
            raise

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> CompletionResponse:
        return await self._execute(
            messages,
            model,
            images=None,
            repo_path=None,
            max_tokens=max_tokens,
            temperature=temperature,
            kwargs=kwargs,
        )

    async def complete_with_vision(
        self,
        messages: list[Message],
        model: str,
        images: list[bytes],
        max_tokens: int = 500,
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> CompletionResponse:
        if not self.supports_vision or self.vision_transport == "none":
            raise NotImplementedError(f"{self.name} does not support automated vision input")
        if not images:
            raise ValueError("Vision judging requires at least one screenshot")
        return await self._execute(
            messages,
            model,
            images=images,
            repo_path=None,
            max_tokens=max_tokens,
            temperature=temperature,
            kwargs=kwargs,
        )

    async def edit_repository(
        self, messages: list[Message], model: str, repo_path: str | Path, **kwargs: Any
    ) -> CompletionResponse:
        """Edit in a caller-owned isolated worktree, without creating or merging it.

        The caller owns isolation, checkpointing and validation. Native permission
        controls confine tools; they do not replace OS isolation for untrusted code.
        """
        if not self.supports_repository_edit:
            raise NotImplementedError(f"{self.name} does not support native repository editing")
        missing = [
            key
            for key in ("reasoning_profile", "auth_mode", "timeout_s")
            if kwargs.get(key) is None or kwargs.get(key) == ""
        ]
        if missing:
            raise ValueError("edit_repository requires explicit " + ", ".join(missing))
        path = Path(repo_path).resolve(strict=True)
        if not path.is_dir():
            raise ValueError("repo_path must be an existing isolated worktree directory")
        images = kwargs.pop("images", None)
        return await self._execute(
            messages,
            model,
            images=images,
            repo_path=path,
            max_tokens=int(kwargs.pop("max_tokens", 2000)),
            temperature=float(kwargs.pop("temperature", 0.7)),
            kwargs=kwargs,
        )
