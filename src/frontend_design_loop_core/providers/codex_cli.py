"""First-party Codex execution with explicit config and auth isolation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._cli_base import NativeCLIError, NativeCLIProvider, json_events
from .base import ProviderFactory


class CodexCLIProvider(NativeCLIProvider):
    cli_name = "codex"
    supports_vision = True
    supports_repository_edit = True
    strict_native = True
    stdin_prompt = True
    vision_transport = "direct_images"
    env_allowlist_prefixes = ("OPENAI_", "CODEX_")

    @property
    def name(self) -> str:
        return "codex_cli"

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
            [self.cli_name, "exec", "--help"], env=env, cwd=cwd, timeout_s=timeout_s
        )
        help_text += "\n" + help_errors
        required = (
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--json",
            "--sandbox",
            "--model",
        )
        if rc or any(flag not in help_text for flag in required):
            raise NativeCLIError(
                "Codex needs an exec version supporting user-config/rules isolation, ephemeral JSON output and sandbox selection; upgrade the native CLI"
            )
        effort = kwargs["reasoning_profile"]
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
            raise NativeCLIError(
                f"Codex does not support reasoning_profile={effort}; select an exact native level"
            )
        # This is a nonsecret native catalog, never an auth/token file. It proves
        # advertised controls, not entitlement or the model actually served.
        cache_path = (
            Path(env.get("CODEX_HOME", str(Path(env.get("HOME", str(Path.home()))) / ".codex")))
            / "models_cache.json"
        )
        catalog_model = None
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            catalog_model = next(
                (
                    m
                    for m in cache.get("models", [])
                    if isinstance(m, dict) and m.get("slug") == model
                ),
                None,
            )
        except (OSError, ValueError, AttributeError):
            pass
        levels = [
            v.get("effort")
            for v in (catalog_model or {}).get("supported_reasoning_levels", [])
            if isinstance(v, dict)
        ]
        if levels and effort not in levels:
            raise NativeCLIError(
                f"Codex catalog does not advertise effort {effort} for the requested model"
            )
        mode = kwargs["auth_mode"]
        rc, out, err = await self._probe(
            [self.cli_name, "login", "status"], env=env, cwd=cwd, timeout_s=timeout_s
        )
        status = (out + "\n" + err).lower()
        observed_auth = (
            "subscription"
            if "logged in using chatgpt" in status
            else "api_key"
            if "logged in using an api key" in status
            else None
        )
        if rc or observed_auth is None:
            raise NativeCLIError(
                "Codex login status could not verify native authentication; sign in with the native CLI separately"
            )
        if mode != "configured" and observed_auth != mode:
            raise NativeCLIError(
                f"Codex auth_mode={mode} requires that native login type; the current login is {observed_auth}"
            )
        return {
            "auth_mode": observed_auth,
            "auth_source": "codex login status",
            "model_availability": "unknown",
            "reasoning_profile": None,
            "effort_validation": "native cached catalog"
            if levels
            else "native runtime; catalog unavailable",
            "advertised_efforts": levels,
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
        root = cwd or Path.cwd()
        edit = kwargs.get("operation") == "edit_repository"
        args = [
            self.cli_name,
            "-a",
            "never",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            "-C",
            str(root),
            "-s",
            "workspace-write" if edit else "read-only",
            "-m",
            model,
        ]
        values = {
            "model_provider": "openai",
            "model_reasoning_effort": kwargs["reasoning_profile"],
            "web_search": "disabled",
            "sandbox_workspace_write.network_access": False,
            "features.multi_agent": False,
            "features.apps": False,
            "features.multi_agent_v2": False,
            "features.plugins": False,
            "features.hooks": False,
            "features.memories": False,
            "features.browser_use": False,
            "features.browser_use_external": False,
            "features.computer_use": False,
            "features.shell_tool": edit,
            "features.unified_exec": edit,
            # Project-level provider overrides/hooks/MCP must not change this route.
            f"projects.{json.dumps(str(root))}.trust_level": "untrusted",
        }
        mode = kwargs["auth_mode"]
        if mode != "configured":
            values["forced_login_method"] = "chatgpt" if mode == "subscription" else "api"
        for key, value in values.items():
            args.extend(["-c", f"{key}={json.dumps(value)}"])
        if output_file is not None:
            args.extend(["--output-last-message", str(output_file)])
        for image in images or []:
            args.extend(["-i", str(image)])
        args.append("-")
        return args

    def _extract_content(
        self, *, stdout_text: str, stderr_text: str, output_file: Path | None
    ) -> str:
        events = json_events(stdout_text)
        for event in events:
            if event.get("type") in {"error", "turn.failed"}:
                raise NativeCLIError("Codex reported a failed turn; no completion accepted")
        if output_file is not None and output_file.exists():
            return output_file.read_text(encoding="utf-8").strip()
        texts = [
            e["item"].get("text", "")
            for e in events
            if e.get("type") == "item.completed"
            and isinstance(e.get("item"), dict)
            and e["item"].get("type") == "agent_message"
        ]
        return str(texts[-1]).strip() if texts else ""

    # Codex JSONL does not currently return a served-model/effort receipt.
    # Its requested/configured values must not be relabeled as observed.


ProviderFactory.register("codex_cli", CodexCLIProvider)
