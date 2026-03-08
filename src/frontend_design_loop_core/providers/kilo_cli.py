"""Official Kilo CLI-backed provider."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from frontend_design_loop_core.image_proxy_context import build_visual_proxy_context
from frontend_design_loop_core.utils import extract_json

from ._cli_base import NativeCLIProvider
from .base import CompletionResponse, Message, ProviderFactory


class KiloCLIProvider(NativeCLIProvider):
    cli_name = "kilo"
    supports_vision = True
    vision_transport = "file_attachments"
    env_allowlist_prefixes = ("KILO_",)

    @property
    def name(self) -> str:
        return "kilo_cli"

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
        _ = (cwd, output_file)
        role = str(kwargs.get("prompt_role") or "").strip().lower()
        variant = str(kwargs.get("reasoning_profile") or "max").strip().lower() or "max"
        if variant == "xhigh":
            variant = "max"
        if variant == "off":
            variant = "minimal"
        if "minimax" in str(model or "").strip().lower() and role == "patch_generator" and variant == "max":
            variant = "high"
        args = [
            self.cli_name,
            "run",
            "--model",
            model,
            "--format",
            "json",
            "--variant",
            variant,
        ]
        if images:
            for image in images:
                args.extend(["--file", str(image)])
        args.extend(["--", prompt])
        return args

    def _uses_visual_proxy(self, model: str) -> bool:
        model_key = str(model or "").strip().lower()
        return "minimax" in model_key

    def _proxy_messages(
        self,
        *,
        messages: list[Message],
        proxy_context: str,
        prompt_role: str | None,
    ) -> list[Message]:
        role = str(prompt_role or "").strip().lower()
        if role == "vision_score":
            guidance = (
                "VISUAL PROXY MODE\n"
                "This Kilo MiniMax lane cannot inspect pixels directly. Use the OCR text and image stats below as hard evidence.\n"
                "Treat this as a structural render-health check, not an aesthetic taste review.\n"
                "Do not penalize polish you cannot verify from the proxy.\n"
            )
        elif role in {"section_creativity", "creative_director"}:
            guidance = (
                "VISUAL PROXY MODE\n"
                "This Kilo MiniMax lane cannot inspect pixels directly. Use the OCR text, layout cues, and image stats below as hard evidence.\n"
                "You may judge generic-vs-distinctive structure, hierarchy, section pacing, proof density, and whether the page has a signature moment at a coarse level.\n"
                "Do not invent color, texture, motion, or typography details that the proxy cannot support.\n"
            )
        else:
            guidance = (
                "VISUAL PROXY MODE\n"
                "This Kilo MiniMax lane cannot inspect pixels directly. Use the OCR text and image stats below as hard evidence.\n"
                "Decide only whether the screenshot appears structurally broken, blank, or obviously misrendered.\n"
            )
        block = f"{guidance}\nSCREENSHOT_PROXY_CONTEXT\n{proxy_context}".strip()
        rendered: list[Message] = []
        appended = False
        for message in messages:
            if not appended and message.role == "user" and isinstance(message.content, str):
                rendered.append(Message(role=message.role, content=f"{message.content}\n\n{block}"))
                appended = True
                continue
            rendered.append(message)
        if not appended:
            rendered.append(Message(role="user", content=block))
        return rendered

    async def complete_with_vision(
        self,
        messages: list[Message],
        model: str,
        images: list[bytes],
        max_tokens: int = 500,
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> CompletionResponse:
        if not self._uses_visual_proxy(model):
            return await super().complete_with_vision(
                messages=messages,
                model=model,
                images=images,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )

        with tempfile.TemporaryDirectory(prefix="frontend-design-loop-kilo-proxy-") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            image_paths: list[Path] = []
            for idx, image in enumerate(images):
                path = tmp_dir / f"image_{idx}.png"
                path.write_bytes(image)
                image_paths.append(path)
            proxy_context = build_visual_proxy_context(image_paths)
        proxy_messages = self._proxy_messages(
            messages=messages,
            proxy_context=proxy_context,
            prompt_role=str(kwargs.get("prompt_role") or "").strip().lower() or None,
        )
        return await self.complete(
            messages=proxy_messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    def _extract_content(
        self,
        *,
        stdout_text: str,
        stderr_text: str,
        output_file: Path | None,
    ) -> str:
        _ = output_file
        text_parts: list[str] = []
        last_text = ""
        for raw_line in stdout_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "error":
                detail = str(payload.get("message") or payload.get("error") or "unknown kilo error").strip()
                raise RuntimeError(f"{self.name} failed: {detail}")
            if payload.get("type") != "text":
                continue
            part = payload.get("part") or {}
            text = str(getattr(part, "get", lambda _k, _d=None: "")("text", "") or "").strip()
            if text:
                text_parts.append(text)
                last_text = text
        if text_parts:
            merged = self._merge_text_fragments(text_parts)
            candidates: list[str] = []
            if merged:
                candidates.append(merged)
            joined = "".join(text_parts).strip()
            if joined and joined not in candidates:
                candidates.append(joined)
            longest = max(text_parts, key=len)
            if longest and longest not in candidates:
                candidates.append(longest)
            if last_text and last_text not in candidates:
                candidates.append(last_text)
            for candidate in candidates:
                if extract_json(candidate) is not None:
                    return candidate
            if merged:
                return merged
            if longest:
                return longest
            if last_text:
                return last_text
        return super()._extract_content(
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            output_file=output_file,
        )

    @staticmethod
    def _merge_text_fragments(text_parts: list[str]) -> str:
        merged = ""
        for raw_part in text_parts:
            part = str(raw_part or "").strip()
            if not part:
                continue
            if not merged:
                merged = part
                continue
            if part in merged:
                continue
            if merged in part:
                merged = part
                continue
            max_overlap = min(len(merged), len(part))
            overlap = 0
            for size in range(max_overlap, 0, -1):
                if merged.endswith(part[:size]):
                    overlap = size
                    break
            merged = (merged + part[overlap:]).strip()
        return merged.strip()


ProviderFactory.register("kilo_cli", KiloCLIProvider)
