"""Provider registry; native CLI use does not require cloud SDKs."""

from importlib import import_module

from ._cli_base import NativeCLIError
from .base import AuthPolicyError, CompletionResponse, LLMProvider, Message, ProviderFactory
from .claude_cli import ClaudeCLIProvider
from .codex_cli import CodexCLIProvider
from .droid_cli import DroidCLIProvider
from .gemini_cli import GeminiCLIProvider
from .kilo_cli import KiloCLIProvider
from .opencode_cli import OpenCodeCLIProvider

_CLOUD_EXPORTS = {
    "OpenRouterProvider": "openrouter",
    "VertexProvider": "vertex",
    "AnthropicVertexProvider": "anthropic_vertex",
    "GeminiProvider": "gemini",
}
for _name in _CLOUD_EXPORTS.values():
    ProviderFactory.register_lazy(_name, f"{__name__}.{_name}")


def __getattr__(name: str):
    if name in _CLOUD_EXPORTS:
        return getattr(import_module(f"{__name__}.{_CLOUD_EXPORTS[name]}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "LLMProvider",
    "Message",
    "CompletionResponse",
    "ProviderFactory",
    "AuthPolicyError",
    "NativeCLIError",
    "VertexProvider",
    "AnthropicVertexProvider",
    "OpenRouterProvider",
    "GeminiProvider",
    "ClaudeCLIProvider",
    "CodexCLIProvider",
    "GeminiCLIProvider",
    "KiloCLIProvider",
    "DroidCLIProvider",
    "OpenCodeCLIProvider",
]
