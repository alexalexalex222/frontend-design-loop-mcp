"""Official Codex CLI-backed provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._cli_base import NativeCLIProvider
from .base import ProviderFactory


class CodexCLIProvider(NativeCLIProvider):
    cli_name = "codex"
    supports_vision = True
    vision_transport = "direct_images"
    env_allowlist_prefixes = ("OPENAI_", "CODEX_")

    @property
    def name(self) -> str:
        return "codex_cli"

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
        effort = str(kwargs.get("reasoning_profile") or "xhigh").strip().lower() or "xhigh"
        if effort == "max":
            effort = "xhigh"
        if effort == "off":
            effort = "none"
        args = [
            self.cli_name,
            "-a",
            "never",
            "exec",
            "--skip-git-repo-check",
            "-C",
            str(cwd or Path.cwd()),
            "-s",
            "read-only",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
        ]
        if output_file is not None:
            args.extend(["--output-last-message", str(output_file)])
        if images:
            for image in images:
                args.extend(["-i", str(image)])
        args.extend(["--", prompt])
        return args


ProviderFactory.register("codex_cli", CodexCLIProvider)
