"""Official Claude CLI-backed provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._cli_base import NativeCLIProvider
from .base import ProviderFactory


class ClaudeCLIProvider(NativeCLIProvider):
    cli_name = "claude"
    supports_vision = True
    vision_transport = "workspace_files"
    env_allowlist_prefixes = ("ANTHROPIC_", "CLAUDE_")

    @property
    def name(self) -> str:
        return "claude_cli"

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
        effort = str(kwargs.get("reasoning_profile") or "high").strip().lower()
        if effort in {"xhigh", "max"}:
            effort = "high"
        if effort in {"none", "off"}:
            effort = "low"
        args = [
            self.cli_name,
            "--print",
            "--output-format",
            "text",
            "--model",
            model,
            "--effort",
            effort,
        ]
        if images:
            args.extend(
                [
                    "--permission-mode",
                    "bypassPermissions",
                    "--add-dir",
                    str(cwd or Path.cwd()),
                ]
            )
        else:
            args.extend(["--tools", ""])
        args.extend(["--", prompt])
        return args


ProviderFactory.register("claude_cli", ClaudeCLIProvider)
