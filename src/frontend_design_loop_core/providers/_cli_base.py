"""Shared helpers for native CLI-backed providers."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from frontend_design_loop_core.config import Config
from frontend_design_loop_core.reasoning_prompts import compose_native_cli_overlay

from .base import CompletionResponse, LLMProvider, Message


def _stringify_content(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content.strip()

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def _flatten_messages(messages: list[Message]) -> str:
    rendered: list[str] = []
    for message in messages:
        content = _stringify_content(message.content)
        if not content:
            continue
        rendered.append(f"{message.role.upper()}:\n{content}")
    return "\n\n".join(rendered).strip()


class NativeCLIProvider(LLMProvider):
    """Base class for native CLI-backed providers.

    These providers intentionally avoid singleton caching because the CLI runtime
    can be sensitive to per-call cwd/env choices.
    """

    cache_scope: ClassVar[str] = "none"
    cli_name: ClassVar[str] = ""
    supports_vision: ClassVar[bool] = False
    vision_transport: ClassVar[str] = "none"
    env_allowlist_keys: ClassVar[set[str]] = set()
    env_allowlist_prefixes: ClassVar[tuple[str, ...]] = ()

    def __init__(self, config: Config) -> None:
        self.config = config

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
            file_list = "\n".join(f"- {path.name}" for path in image_paths)
            prompt = (
                "VISUAL INPUT FILES\n"
                "You MUST inspect the local screenshot files listed below before answering.\n"
                "Base your judgment only on what is visibly present in those files.\n"
                f"{file_list}\n\n{prompt}"
            ).strip()
        return prompt

    def _reasoning_overlay(self, *, messages: list[Message], model: str, kwargs: dict[str, Any]) -> str:
        system_prompt = ""
        for message in messages:
            if message.role == "system":
                system_prompt = _stringify_content(message.content)
                if system_prompt:
                    break
        return compose_native_cli_overlay(
            provider_name=self.name,
            model=model,
            reasoning_profile=str(kwargs.get("reasoning_profile") or ""),
            system_prompt=system_prompt,
            prompt_role=str(kwargs.get("prompt_role") or "").strip().lower() or None,
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
            "EDITOR",
            "VISUAL",
            "PAGER",
            "VIRTUAL_ENV",
            "__CF_USER_TEXT_ENCODING",
        }
        runtime_prefixes = (
            "FRONTEND_DESIGN_LOOP_",
        )
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            if key in base_keys:
                env[key] = value
                continue
            if any(key.startswith(prefix) for prefix in runtime_prefixes):
                env[key] = value
                continue
            if key in self.env_allowlist_keys:
                env[key] = value
                continue
            if any(key.startswith(prefix) for prefix in self.env_allowlist_prefixes):
                env[key] = value
        env.update({k: str(v) for k, v in (kwargs.get("env") or {}).items()})
        return env

    def _extract_content(
        self,
        *,
        stdout_text: str,
        stderr_text: str,
        output_file: Path | None,
    ) -> str:
        if output_file is not None and output_file.exists():
            return output_file.read_text(encoding="utf-8").strip()
        return stdout_text.strip()

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
    ) -> CompletionResponse:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"{self.name} timed out after {timeout_s:.1f}s") from exc

        stdout_text = stdout.decode(errors="replace").strip()
        stderr_text = stderr.decode(errors="replace").strip()

        if proc.returncode != 0:
            detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
            raise RuntimeError(f"{self.name} failed: {detail}")
        content = self._extract_content(
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            output_file=output_file,
        )
        if not content:
            raise RuntimeError(f"{self.name} returned empty output")

        return CompletionResponse(
            content=content,
            model=args[0],
            raw_response={
                "args": args,
                "cwd": str(cwd) if cwd else None,
                "stdout": stdout_text,
                "stderr": stderr_text,
            },
        )

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> CompletionResponse:
        _ = (max_tokens, temperature)
        cwd = Path(str(kwargs.get("cwd") or os.getcwd())).resolve()
        timeout_s = float(kwargs.get("timeout_s") or 300.0)
        prompt = self._build_prompt(messages, model=model, kwargs=kwargs)
        env = self._build_env(kwargs)
        output_file: Path | None = None
        if self.name == "codex_cli":
            tmp_dir = Path(tempfile.mkdtemp(prefix="frontend-design-loop-codex-cli-"))
            output_file = tmp_dir / "last_message.txt"
        args = self._build_command(
            model=model,
            prompt=prompt,
            cwd=cwd,
            kwargs=kwargs,
            output_file=output_file,
        )
        try:
            response = await self._run_cli(
                args=args,
                cwd=cwd,
                env=env,
                timeout_s=timeout_s,
                output_file=output_file,
            )
        finally:
            if output_file is not None:
                try:
                    output_file.unlink(missing_ok=True)
                    output_file.parent.rmdir()
                except OSError:
                    pass
        response.model = model
        return response

    async def complete_with_vision(
        self,
        messages: list[Message],
        model: str,
        images: list[bytes],
        max_tokens: int = 500,
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> CompletionResponse:
        _ = (max_tokens, temperature)
        if not self.supports_vision or self.vision_transport == "none":
            raise NotImplementedError(
                f"{self.name} does not support automated vision input. Use vision_provider=client, gemini, anthropic_vertex, or a native CLI provider with vision support."
            )

        cwd = Path(str(kwargs.get("cwd") or os.getcwd())).resolve()
        timeout_s = float(kwargs.get("timeout_s") or 300.0)
        env = self._build_env(kwargs)

        with tempfile.TemporaryDirectory(prefix=f"frontend-design-loop-{self.name}-vision-") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            image_paths: list[Path] = []
            for idx, image in enumerate(images):
                path = tmp_dir / f"image_{idx}.png"
                path.write_bytes(image)
                image_paths.append(path)

            prompt = self._build_prompt(messages, model=model, kwargs=kwargs, image_paths=image_paths)
            output_file: Path | None = None
            if self.name == "codex_cli":
                output_file = tmp_dir / "last_message.txt"
            run_cwd = tmp_dir if self.vision_transport == "workspace_files" else cwd

            args = self._build_command(
                model=model,
                prompt=prompt,
                cwd=run_cwd,
                kwargs=kwargs,
                images=image_paths,
                output_file=output_file,
            )
            response = await self._run_cli(
                args=args,
                cwd=run_cwd,
                env=env,
                timeout_s=timeout_s,
                output_file=output_file,
            )
            response.model = model
            return response
