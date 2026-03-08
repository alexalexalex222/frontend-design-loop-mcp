"""Official Gemini CLI-backed provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._cli_base import NativeCLIProvider
from .base import Message, ProviderFactory


class GeminiCLIProvider(NativeCLIProvider):
    cli_name = "gemini"
    supports_vision = True
    vision_transport = "workspace_files"

    @property
    def name(self) -> str:
        return "gemini_cli"

    def _build_env(self, kwargs: dict[str, Any]) -> dict[str, str]:
        env = super()._build_env(kwargs)
        for key in (
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_REGION",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_GENAI_USE_GCA",
        ):
            env.pop(key, None)
        env.update({k: str(v) for k, v in (kwargs.get("env") or {}).items()})
        return env

    def _build_prompt(
        self,
        messages: list[Message],
        *,
        model: str,
        kwargs: dict[str, Any],
        image_paths: list[Path] | None = None,
    ) -> str:
        prompt = super()._build_prompt(messages, model=model, kwargs=kwargs, image_paths=image_paths)
        if image_paths:
            refs = " ".join(f"@./{path.name}" for path in image_paths)
            prompt = (
                "IMAGE REFERENCES\n"
                "Inspect the referenced local files directly before answering.\n"
                f"{refs}\n\n{prompt}"
            ).strip()
        return prompt

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
        args = [
            self.cli_name,
            "--model",
            model,
            "--output-format",
            "text",
            "--extensions",
            "",
        ]
        if images:
            args.extend(["--yolo"])
        args.extend(["--prompt", prompt])
        return args


ProviderFactory.register("gemini_cli", GeminiCLIProvider)
