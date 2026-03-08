import anyio

from frontend_design_loop_core.mcp_code_server import _call_llm_json
from frontend_design_loop_core.providers.base import CompletionResponse, LLMProvider, ProviderFactory
from frontend_design_loop_core.utils import extract_json, extract_json_strict


_MALFORMED_PATCH_BUNDLE = r'''{"patches":[{"path":"index.html","patch":"<!doctype html>
<html lang=\"en\">
<body>
  <style>body::before { content: \"\hero-grid\"; }</style>
  <main class=\"hero\">northstar</main>
</body>
</html>"}],"notes":["whole-file rewrite"]}'''


class _LoosePatchProvider(LLMProvider):
    cache_scope = "none"

    def __init__(self, _config) -> None:
        self._config = _config

    @property
    def name(self) -> str:
        return "loose_patch_test"

    async def complete(self, messages, model, max_tokens=2000, temperature=0.7, **kwargs):
        _ = (messages, model, max_tokens, temperature, kwargs)
        return CompletionResponse(content=_MALFORMED_PATCH_BUNDLE, model="loose_patch_test")

    async def complete_with_vision(self, messages, model, images, max_tokens=500, temperature=0.1, **kwargs):
        _ = (messages, model, images, max_tokens, temperature, kwargs)
        raise NotImplementedError


def test_extract_json_salvages_loose_patch_bundle_with_invalid_escape() -> None:
    data = extract_json(_MALFORMED_PATCH_BUNDLE)

    assert data is not None
    assert data["patches"][0]["path"] == "index.html"
    assert "northstar" in data["patches"][0]["patch"]
    assert "\\hero-grid" in data["patches"][0]["patch"]
    assert data["notes"] == ["whole-file rewrite"]


def test_call_llm_json_salvages_loose_patch_bundle_provider_output() -> None:
    ProviderFactory.register("loose_patch_test", _LoosePatchProvider)

    async def run() -> dict:
        return await _call_llm_json(
            provider_name="loose_patch_test",
            model="loose_patch_test",
            system_prompt="Return JSON only.",
            user_prompt="Emit a patch bundle.",
            temperature=0.2,
            max_tokens=2000,
            prompt_role="patch_generator",
        )

    data = anyio.run(run)

    assert data["patches"][0]["path"] == "index.html"
    assert extract_json_strict(_MALFORMED_PATCH_BUNDLE)["notes"] == ["whole-file rewrite"]
