"""Official OpenCode CLI-backed provider."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from frontend_design_loop_core.image_proxy_context import build_visual_proxy_context

from ._cli_base import NativeCLIProvider
from .base import Message, ProviderFactory


class OpenCodeCLIProvider(NativeCLIProvider):
    cli_name = "opencode"
    supports_vision = True
    vision_transport = "file_attachments"
    env_allowlist_prefixes = ("OPENCODE_",)

    @property
    def name(self) -> str:
        return "opencode_cli"

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
        _ = output_file
        variant = str(kwargs.get("reasoning_profile") or "max").strip().lower() or "max"
        if variant == "xhigh":
            variant = "max"
        if variant == "off":
            variant = "minimal"
        args = [
            self.cli_name,
            "run",
            "--dir",
            str(cwd or Path.cwd()),
            "--model",
            model,
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
                "This model lane cannot inspect pixels directly. Use the OCR text and image stats below as hard evidence.\n"
                "Treat this as a structural render-health check, not an aesthetic taste review.\n"
                "Do not penalize polish you cannot verify from the proxy.\n"
            )
        else:
            guidance = (
                "VISUAL PROXY MODE\n"
                "This model lane cannot inspect pixels directly. Use the OCR text and image stats below as hard evidence.\n"
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
    ):
        if not self._uses_visual_proxy(model):
            return await super().complete_with_vision(
                messages=messages,
                model=model,
                images=images,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )

        with tempfile.TemporaryDirectory(prefix="frontend-design-loop-opencode-proxy-") as tmp_dir_str:
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


ProviderFactory.register("opencode_cli", OpenCodeCLIProvider)
