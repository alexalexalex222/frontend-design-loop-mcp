"""OpenCode with catalog-verified models/variants and explicit auth policy."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._cli_base import NativeCLIError, NativeCLIProvider, json_events
from .base import ProviderFactory


def _catalog_entry(text: str, model: str) -> dict[str, Any] | None:
    # Native models --verbose prints provider/model, followed by a JSON object.
    match = re.search(r"(?m)^" + re.escape(model) + r"\s*$", text)
    if match is None:
        return None
    tail = text[match.end() :].lstrip()
    try:
        entry, _ = json.JSONDecoder().raw_decode(tail)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


class OpenCodeCLIProvider(NativeCLIProvider):
    cli_name = "opencode"
    supports_vision = True
    supports_repository_edit = True
    strict_native = True
    stdin_prompt = True
    vision_transport = "file_attachments"
    env_allowlist_prefixes = ("OPENCODE_", "OPENAI_", "ANTHROPIC_")
    env_allowlist_keys = {"OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"}

    @property
    def name(self) -> str:
        return "opencode_cli"

    def _build_env(self, kwargs: dict[str, Any]) -> dict[str, str]:
        env = super()._build_env(kwargs)
        runtime = Path(kwargs.get("runtime_dir") or kwargs.get("preflight_dir") or ".")
        permission = {
            "*": "deny",
            "read": "allow",
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
            "edit": "allow" if kwargs.get("operation") == "edit_repository" else "deny",
            "external_directory": "deny",
            "question": "deny",
        }
        config = {
            "share": "disabled",
            "autoupdate": False,
            "mcp": {},
            "plugin": [],
            "permission": permission,
            "agent": {
                "fdl": {
                    "mode": "primary",
                    "description": "Scoped frontend design task",
                    "permission": permission,
                    "prompt": "Follow the caller's role and evidence contract. Stay within this workspace.",
                }
            },
        }
        if kwargs["auth_mode"] == "subscription":
            # Keep native credentials in the data directory; isolate user/project
            # provider overrides. No tokens are copied or inspected by this adapter.
            env["XDG_CONFIG_HOME"] = str(runtime)
            native_home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
            # OpenCode also discovers ~/.opencode independently of XDG_CONFIG_HOME.
            # Preserve the native data/cache locations while giving that discovery
            # an empty home. These are child-only settings, not account changes.
            env["XDG_DATA_HOME"] = env.get("XDG_DATA_HOME") or str(native_home / ".local" / "share")
            env["XDG_CACHE_HOME"] = env.get("XDG_CACHE_HOME") or str(native_home / ".cache")
            env["XDG_STATE_HOME"] = str(runtime / "state")
            env["HOME"] = str(runtime)
            env["USERPROFILE"] = str(runtime)
        env.update(
            OPENCODE_CONFIG_CONTENT=json.dumps(config),
            OPENCODE_CONFIG_DIR=str(runtime),
            OPENCODE_DISABLE_PROJECT_CONFIG="true",
            OPENCODE_DISABLE_CLAUDE_CODE="true",
            OPENCODE_DISABLE_LSP_DOWNLOAD="true",
            OPENCODE_DISABLE_MODELS_FETCH="true",
            OPENCODE_PERMISSION=json.dumps(permission),
        )
        return env

    async def _preflight(
        self,
        *,
        model: str,
        kwargs: dict[str, Any],
        env: dict[str, str],
        cwd: Path,
        timeout_s: float,
    ) -> dict[str, Any]:
        if "/" not in model or not all(model.split("/", 1)):
            raise NativeCLIError("OpenCode requires an explicit provider/model identifier")
        provider_id, model_id = model.split("/", 1)
        if kwargs["auth_mode"] == "subscription" and provider_id != "openai":
            raise NativeCLIError(
                "OpenCode pure mode only has a verified native OpenAI subscription loader; use claude_cli for Claude subscriptions or explicitly select configured for other routes"
            )
        rc, help_text, help_errors = await self._probe(
            [self.cli_name, "run", "--help"], env=env, cwd=cwd, timeout_s=timeout_s
        )
        help_text += "\n" + help_errors
        if rc or any(
            flag not in help_text
            for flag in ("--pure", "--variant", "--agent", "--format", "--dir")
        ):
            raise NativeCLIError(
                "OpenCode needs native pure mode, model variants, scoped agents and JSON output; upgrade the native CLI"
            )
        rc, catalog, _ = await self._probe(
            [self.cli_name, "models", provider_id, "--verbose", "--pure"],
            env=env,
            cwd=cwd,
            timeout_s=timeout_s,
        )
        entry = _catalog_entry(catalog, model) if not rc else None
        if entry is None:
            raise NativeCLIError(
                "OpenCode did not advertise the exact requested model and its metadata; configure that native provider/model separately"
            )
        if entry.get("id") != model_id or entry.get("providerID") != provider_id:
            raise NativeCLIError(
                "OpenCode catalog model/provider identifiers disagree with the request"
            )
        api = entry.get("api") or {}
        if api.get("id") != model_id:
            raise NativeCLIError(
                "OpenCode model aliases that resolve to a different API model are unsupported; select the exact model"
            )
        variants = entry.get("variants") or {}
        if not isinstance(variants, dict) or kwargs["reasoning_profile"] not in variants:
            raise NativeCLIError(
                "OpenCode does not advertise the exact requested variant for this model; variants are model-specific and are never remapped"
            )
        caps = entry.get("capabilities") or {}
        if (kwargs.get("operation") == "vision" or kwargs.get("has_images")) and (
            caps.get("input") or {}
        ).get("image") is not True:
            raise NativeCLIError(
                "OpenCode catalog does not advertise image input for this model; proxy text cannot substitute for a visual judge"
            )
        if (
            kwargs.get("operation") in {"vision", "edit_repository"}
            and caps.get("toolcall") is not True
        ):
            raise NativeCLIError("OpenCode catalog does not advertise native tools for this model")
        mode = kwargs["auth_mode"]
        rc, out, err = await self._probe(
            [self.cli_name, "auth", "list", "--pure"], env=env, cwd=cwd, timeout_s=timeout_s
        )
        if rc:
            raise NativeCLIError(
                "OpenCode native auth list is unavailable; authentication cannot be verified"
            )
        # The native v1 command deliberately prints provider names and auth types,
        # not secrets. Subscription policy supports only known first-party OAuth
        # providers; arbitrary OAuth/gateway plugins are not subscription evidence.
        label = {"openai": "OpenAI", "anthropic": "Anthropic"}.get(provider_id)
        status = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out + "\n" + err)
        types = re.findall(
            r"(?:^|[\s│●])" + re.escape(label or provider_id) + r"\s+(oauth|api)\s*(?=\n|$)",
            status,
            re.I,
        )
        observed = (
            "subscription"
            if types == ["oauth"] and label
            else "api_key"
            if types == ["api"]
            else None
        )
        if mode == "subscription":
            if observed != "subscription":
                raise NativeCLIError(
                    "OpenCode subscription mode requires native first-party OAuth authentication for the selected provider"
                )
            # Catalog endpoints/options must not silently replace first-party routing.
            allowed_urls = {
                "openai": {"https://api.openai.com/v1", "https://chatgpt.com/backend-api/codex"},
                "anthropic": {"https://api.anthropic.com/v1", "https://api.anthropic.com"},
            }[provider_id]
            options = entry.get("options") or {}
            builtin_default = (
                api.get("url") in {None, ""}
                and provider_id == "openai"
                and api.get("npm") == "@ai-sdk/openai"
            )
            if not builtin_default and (
                not isinstance(api.get("url"), str) or api["url"].rstrip("/") not in allowed_urls
            ):
                raise NativeCLIError(
                    "OpenCode subscription catalog points outside the first-party provider"
                )
            if any(k in options for k in ("baseURL", "baseUrl", "apiKey", "headers")) or entry.get(
                "headers"
            ):
                raise NativeCLIError(
                    "OpenCode subscription mode rejects model API/gateway/credential overrides"
                )
        elif mode == "api_key" and observed != "api_key":
            raise NativeCLIError(
                "OpenCode auth list did not verify API-key authentication; use configured for an explicitly selected custom route"
            )
        return {
            "auth_mode": observed if mode != "configured" else None,
            "native_credential_type": observed,
            "auth_source": "opencode auth list",
            "provider": provider_id,
            "model_availability": "advertised",
            "advertised_variants": sorted(variants),
            "image_input": (caps.get("input") or {}).get("image") is True,
            "native_tools": caps.get("toolcall") is True,
            "reasoning_profile": None,
            "effort_validation": "native model catalog",
            "user_config_isolated": mode == "subscription",
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
        args = [
            self.cli_name,
            "run",
            "--pure",
            "--dir",
            str(cwd or Path.cwd()),
            "--model",
            model,
            "--variant",
            kwargs["reasoning_profile"],
            "--agent",
            "fdl",
            "--format",
            "json",
            "--title",
            "Frontend design loop",
        ]
        for image in images or []:
            args.extend(["--file", str(image)])
        return args

    def _extract_content(
        self, *, stdout_text: str, stderr_text: str, output_file: Path | None
    ) -> str:
        parts = []
        for event in json_events(stdout_text):
            if event.get("type") == "error":
                raise NativeCLIError(
                    "OpenCode reported an unsuccessful turn; no completion accepted"
                )
            if event.get("type") == "text" and isinstance(event.get("part"), dict):
                text = event["part"].get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()


ProviderFactory.register("opencode_cli", OpenCodeCLIProvider)
