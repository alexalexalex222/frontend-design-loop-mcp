"""First-party Claude Code with exact effort and confined native tools."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._cli_base import NativeCLIError, NativeCLIProvider, json_events
from .base import ProviderFactory

# Official model-config effort table, checked 2026-10-05. Claude Code silently
# lowers unsupported effort, so CLI help alone is insufficient preflight.
# https://code.claude.com/docs/en/model-config#adjust-effort-level
_MODEL_EFFORTS = {
    **{
        f"claude-{family}-{version}": {"low", "medium", "high", "xhigh", "max"}
        for family, versions in (
            ("opus", ("5-5", "5", "4-8", "4-7")),
            ("sonnet", ("5-5", "5")),
            ("fable", ("5-1", "5")),
        )
        for version in versions
    },
    "claude-opus-4-6": {"low", "medium", "high", "max"},
    "claude-sonnet-4-6": {"low", "medium", "high", "max"},
}


class ClaudeCLIProvider(NativeCLIProvider):
    cli_name = "claude"
    supports_vision = True
    supports_repository_edit = True
    strict_native = True
    stdin_prompt = True
    vision_transport = "workspace_files"
    env_allowlist_prefixes = ("ANTHROPIC_", "CLAUDE_")

    @property
    def name(self) -> str:
        return "claude_cli"

    async def _preflight(
        self,
        *,
        model: str,
        kwargs: dict[str, Any],
        env: dict[str, str],
        cwd: Path,
        timeout_s: float,
    ) -> dict[str, Any]:
        rc, help_text, help_errors = await self._probe(
            [self.cli_name, "--help"], env=env, cwd=cwd, timeout_s=timeout_s
        )
        help_text += "\n" + help_errors
        flags = (
            "--effort",
            "--restricted",
            "--strict-mcp-config",
            "--setting-sources",
            "--allowedTools",
            "--tools",
            "--no-session-persistence",
            "--safe-mode",
            "--permission-prompts",
        )
        if rc or any(flag not in help_text for flag in flags):
            raise NativeCLIError(
                "Claude Code needs exact effort, restricted tools/config and nonpersistent print mode; upgrade the native CLI"
            )
        # Use the installed CLI's advertised values. Do not translate xhigh/max/none.
        match = re.search(r"--effort\b[\s\S]*?(?=\n\s*--|\n\s*-[A-Za-z],|\Z)", help_text)
        advertised = set(
            re.findall(
                r"\b(?:low|medium|high|xhigh|max|none|minimal|ultracode)\b",
                match.group(0) if match else "",
            )
        )
        if kwargs["reasoning_profile"] not in advertised:
            raise NativeCLIError(
                f"Installed Claude Code does not advertise effort {kwargs['reasoning_profile']}; choose a supported exact level"
            )
        model_key = re.sub(r"-\d{8}$", "", model.removesuffix("[1m]"))
        levels = _MODEL_EFFORTS.get(model_key)
        if levels is None or kwargs["reasoning_profile"] not in levels:
            raise NativeCLIError(
                "Requested Claude model/effort is not verified in the documented capability table; select a supported exact pair (xhigh is unsupported on 4.6)"
            )
        rc, out, _ = await self._probe(
            [self.cli_name, "auth", "status", "--json"], env=env, cwd=cwd, timeout_s=timeout_s
        )
        try:
            status = json.loads(out)
        except ValueError as exc:
            raise NativeCLIError("Claude Code auth status is unavailable or unparseable") from exc
        if rc or not isinstance(status, dict) or status.get("loggedIn") is not True:
            raise NativeCLIError(
                "Claude Code is not logged in; sign in with the native CLI separately"
            )
        method = status.get("authMethod")
        first_party = status.get("apiProvider") == "firstParty"
        observed = (
            "subscription"
            if method == "claude.ai" and first_party
            else "api_key"
            if method == "api_key"
            else None
        )
        mode = kwargs["auth_mode"]
        if mode != "configured" and observed != mode:
            raise NativeCLIError(
                f"Claude Code auth status does not establish auth_mode={mode}; subscription requires claude.ai and firstParty"
            )
        return {
            "auth_mode": observed,
            "auth_source": "claude auth status",
            "provider": "firstParty" if first_party else None,
            "model_availability": "unknown",
            "reasoning_profile": None,
            "effort_validation": "CLI help and official model capability table",
            "advertised_efforts": sorted(levels),
            "user_config_isolated": True,
        }

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
        edit = kwargs.get("operation") == "edit_repository"
        tools = "Read,Glob,Grep,Edit,Write" if edit else "Read" if images else ""
        args = [
            self.cli_name,
            "--print",
            "--output-format",
            "json",
            "--model",
            model,
            "--effort",
            kwargs["reasoning_profile"],
            "--restricted",
            "--safe-mode",
            "--permission-prompts",
            "none",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--no-session-persistence",
            "--tools",
            tools,
            "--permission-mode",
            "acceptEdits" if edit else "dontAsk",
            "--settings",
            '{"disableAllHooks":true,"fallbackModel":[],"switchModelsOnFlag":false}',
        ]
        if tools:
            args.extend(["--allowedTools", tools])
        if edit and images:
            args.extend(["--add-dir", str(images[0].parent)])
        # Image files already live in the judge's isolated cwd, so no additional
        # filesystem grants or bypass mode are necessary.
        return args

    def _extract_content(
        self, *, stdout_text: str, stderr_text: str, output_file: Path | None
    ) -> str:
        events = json_events(stdout_text)
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if result is None:
            raise NativeCLIError("Claude Code did not return its native JSON result")
        if result.get("is_error") or result.get("subtype") not in {None, "success"}:
            raise NativeCLIError(
                "Claude Code reported an unsuccessful result; no completion accepted"
            )
        return str(result.get("result") or "").strip()

    def _observed_execution(self, stdout_text: str) -> dict[str, Any]:
        result = next(
            (e for e in reversed(json_events(stdout_text)) if e.get("type") == "result"), {}
        )
        usage = result.get("modelUsage")
        if isinstance(usage, dict) and len(usage) > 1:
            raise NativeCLIError(
                "Claude Code reported multiple served models; fallback is forbidden"
            )
        model = next(iter(usage)) if isinstance(usage, dict) and len(usage) == 1 else None
        # modelUsage is native runtime accounting, not a guarantee from the server.
        reads, successes = {}, set()
        for event in json_events(stdout_text):
            message = event.get("message") or {}
            for block in (
                message.get("content", []) if isinstance(message.get("content"), list) else []
            ):
                if block.get("type") == "tool_use" and block.get("name") == "Read":
                    path = (block.get("input") or {}).get("file_path")
                    if isinstance(path, str):
                        reads[block.get("id")] = path
                if block.get("type") == "tool_result" and not block.get("is_error", False):
                    content = block.get("content")
                    if isinstance(content, list) and any(
                        isinstance(item, dict) and item.get("type") == "image" for item in content
                    ):
                        successes.add(block.get("tool_use_id"))
        return {
            "model": model,
            "model_source": "claude result.modelUsage" if model else None,
            "verified_image_reads": sorted({reads[key] for key in successes if key in reads}),
        }


ProviderFactory.register("claude_cli", ClaudeCLIProvider)
