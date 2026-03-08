import anyio

from frontend_design_loop_core.config import load_config
from frontend_design_loop_core.providers import ProviderFactory
from frontend_design_loop_core.providers.base import CompletionResponse, Message
from frontend_design_loop_core.providers.claude_cli import ClaudeCLIProvider
from frontend_design_loop_core.providers.codex_cli import CodexCLIProvider
from frontend_design_loop_core.providers.droid_cli import DroidCLIProvider
from frontend_design_loop_core.providers.gemini_cli import GeminiCLIProvider
from frontend_design_loop_core.providers.kilo_cli import KiloCLIProvider
from frontend_design_loop_core.providers.opencode_cli import OpenCodeCLIProvider
from frontend_design_loop_core.reasoning_prompts import compose_native_cli_overlay


def test_provider_factory_does_not_cache_cli_providers() -> None:
    config = load_config()
    ProviderFactory.clear()

    a = ProviderFactory.get("claude_cli", config)
    b = ProviderFactory.get("claude_cli", config)

    assert a is not b


def test_provider_factory_does_not_cache_openrouter_instances(tmp_path, monkeypatch) -> None:
    cfg1 = tmp_path / "one.yaml"
    cfg2 = tmp_path / "two.yaml"
    base1 = """\
models:
  planner_model: gpt-5.4
  patch_model: gpt-5.4
  vision_model: google/gemini-3.1-pro
pipeline: {}
budget:
  concurrency_openrouter: 1
  concurrency_vertex: 1
  concurrency_gemini: 1
  concurrency_anthropic_vertex: 1
export: {}
gcs: {}
vertex:
  project: test
  location: us-central1
  bucket: test
openrouter:
  base_url: https://example-one.invalid
"""
    cfg1.write_text(base1, encoding="utf-8")
    cfg2.write_text(base1.replace("example-one.invalid", "example-two.invalid"), encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    ProviderFactory.clear()
    a = ProviderFactory.get("openrouter", load_config(cfg1))
    b = ProviderFactory.get("openrouter", load_config(cfg2))

    assert a is not b
    assert getattr(a, "base_url") == "https://example-one.invalid"
    assert getattr(b, "base_url") == "https://example-two.invalid"


def test_codex_cli_env_is_allowlisted(monkeypatch) -> None:
    provider = CodexCLIProvider(load_config())
    monkeypatch.setenv("OPENAI_API_KEY", "allowed")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "blocked")
    monkeypatch.setenv("FRONTEND_DESIGN_LOOP_CONFIG_PATH", "/tmp/config.yaml")

    env = provider._build_env({"env": {"EXPLICIT_TOKEN": "present"}})

    assert env["OPENAI_API_KEY"] == "allowed"
    assert env["FRONTEND_DESIGN_LOOP_CONFIG_PATH"] == "/tmp/config.yaml"
    assert env["EXPLICIT_TOKEN"] == "present"
    assert "AWS_SECRET_ACCESS_KEY" not in env


def test_gemini_cli_scrubs_inherited_google_env_but_keeps_explicit_env(monkeypatch) -> None:
    provider = GeminiCLIProvider(load_config())
    monkeypatch.setenv("GOOGLE_API_KEY", "inherited-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "inherited-gemini")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "blocked")

    env = provider._build_env({"env": {"GOOGLE_API_KEY": "explicit-google"}})

    assert env["GOOGLE_API_KEY"] == "explicit-google"
    assert "GEMINI_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env


def test_claude_cli_builds_reasoning_command(monkeypatch) -> None:
    provider = ClaudeCLIProvider(load_config())
    seen: dict[str, object] = {}

    async def fake_run_cli(*, args, cwd, env, timeout_s, output_file=None):
        seen["args"] = args
        seen["cwd"] = cwd
        seen["timeout_s"] = timeout_s
        _ = (env, output_file)
        return CompletionResponse(content='{"ok": true}', model="claude-opus-4-6")

    monkeypatch.setattr(provider, "_run_cli", fake_run_cli)

    async def run() -> CompletionResponse:
        return await provider.complete(
            messages=[
                Message(role="system", content="Return JSON only."),
                Message(role="user", content="Make a tiny patch plan."),
            ],
            model="claude-opus-4-6",
            reasoning_profile="xhigh",
        )

    result = anyio.run(run)
    assert result.content == '{"ok": true}'
    args = list(seen["args"])
    assert "--model" in args
    assert "claude-opus-4-6" in args
    assert "--effort" in args
    assert "high" in args
    assert "--tools" in args
    assert "--" in args
    prompt = str(args[-1])
    assert "NATIVE CLI REASONING HARNESS" in prompt
    assert "OPUS INTERLEAVED REASONING CONTRACT" in prompt


def test_codex_cli_supports_image_attachments(monkeypatch) -> None:
    provider = CodexCLIProvider(load_config())
    seen: dict[str, object] = {}

    async def fake_run_cli(*, args, cwd, env, timeout_s, output_file=None):
        seen["args"] = args
        _ = (cwd, env, timeout_s)
        if output_file is not None:
            output_file.write_text('{"score": 9.0}', encoding="utf-8")
        return CompletionResponse(content='{"score": 9.0}', model="gpt-5.4")

    monkeypatch.setattr(provider, "_run_cli", fake_run_cli)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[Message(role="user", content="Score these screenshots.")],
            model="gpt-5.4",
            images=[b"fake-image-bytes"],
            reasoning_profile="xhigh",
        )

    result = anyio.run(run)
    assert result.content == '{"score": 9.0}'
    args = list(seen["args"])
    assert "-i" in args
    assert "gpt-5.4" in args
    assert "--" in args
    prompt = str(args[-1])
    assert "VISUAL INPUT FILES" not in prompt
    assert "CODEX IMPLEMENTATION CONTRACT" in prompt


def test_claude_cli_vision_uses_workspace_files(monkeypatch) -> None:
    provider = ClaudeCLIProvider(load_config())
    seen: dict[str, object] = {}

    async def fake_run_cli(*, args, cwd, env, timeout_s, output_file=None):
        seen["args"] = args
        seen["cwd"] = cwd
        _ = (env, timeout_s, output_file)
        return CompletionResponse(content='{"score": 9.0}', model="claude-opus-4-6")

    monkeypatch.setattr(provider, "_run_cli", fake_run_cli)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[
                Message(role="system", content="You are a STRICT website screenshot validator."),
                Message(role="user", content="Return JSON only."),
            ],
            model="claude-opus-4-6",
            images=[b"fake-image-bytes"],
            reasoning_profile="high",
            prompt_role="vision_broken",
        )

    result = anyio.run(run)
    assert result.content == '{"score": 9.0}'
    args = list(seen["args"])
    assert "--permission-mode" in args
    assert "bypassPermissions" in args
    assert "--add-dir" in args
    add_dir = str(args[args.index("--add-dir") + 1])
    assert add_dir == str(seen["cwd"])
    assert "frontend-design-loop-claude_cli-vision-" in add_dir
    assert "--" in args
    prompt = str(args[-1])
    assert "VISUAL INPUT FILES" in prompt
    assert "STRUCTURAL VISION GATE" in prompt


def test_gemini_cli_vision_uses_workspace_files(monkeypatch) -> None:
    provider = GeminiCLIProvider(load_config())
    seen: dict[str, object] = {}

    async def fake_run_cli(*, args, cwd, env, timeout_s, output_file=None):
        seen["args"] = args
        seen["cwd"] = cwd
        _ = (env, timeout_s, output_file)
        return CompletionResponse(content='{"score": 8.5}', model="gemini-3.1-pro-preview")

    monkeypatch.setattr(provider, "_run_cli", fake_run_cli)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[Message(role="user", content="Score these screenshots.")],
            model="gemini-3.1-pro-preview",
            images=[b"fake-image-bytes"],
            reasoning_profile="high",
            prompt_role="vision_score",
        )

    result = anyio.run(run)
    assert result.content == '{"score": 8.5}'
    args = list(seen["args"])
    assert "--yolo" in args
    assert "--extensions" in args
    prompt = str(args[-1])
    assert "IMAGE REFERENCES" in prompt
    assert "@./image_0.png" in prompt
    assert "VISUAL INPUT FILES" in prompt
    assert "GEMINI STRUCTURED THINKING CONTRACT" in prompt


def test_kilo_cli_uses_json_run_contract(monkeypatch) -> None:
    provider = KiloCLIProvider(load_config())
    seen: dict[str, object] = {}

    async def fake_run_cli(*, args, cwd, env, timeout_s, output_file=None):
        seen["args"] = args
        seen["cwd"] = cwd
        _ = (env, timeout_s, output_file)
        return CompletionResponse(content='{"ok": true}', model="kilo/minimax/minimax-m2.5:free")

    monkeypatch.setattr(provider, "_run_cli", fake_run_cli)

    async def run() -> CompletionResponse:
        return await provider.complete(
            messages=[
                Message(role="system", content="Return JSON only."),
                Message(role="user", content="Make a tiny patch plan."),
            ],
            model="kilo/minimax/minimax-m2.5:free",
            reasoning_profile="xhigh",
        )

    result = anyio.run(run)
    assert result.content == '{"ok": true}'
    args = list(seen["args"])
    assert args[:2] == ["kilo", "run"]
    assert "--format" in args
    assert "json" in args
    assert "--variant" in args
    assert "max" in args
    assert "--auto" not in args
    assert "--" in args
    prompt = str(args[-1])
    assert "NATIVE CLI REASONING HARNESS" in prompt
    assert "MINIMAX FREE EXECUTION CONTRACT" in prompt


def test_kilo_cli_patch_generator_caps_minimax_max_variant_to_high(monkeypatch) -> None:
    provider = KiloCLIProvider(load_config())
    seen: dict[str, object] = {}

    async def fake_run_cli(*, args, cwd, env, timeout_s, output_file=None):
        seen["args"] = args
        _ = (cwd, env, timeout_s, output_file)
        return CompletionResponse(content='{"ok": true}', model="kilo/minimax/minimax-m2.5:free")

    monkeypatch.setattr(provider, "_run_cli", fake_run_cli)

    async def run() -> CompletionResponse:
        return await provider.complete(
            messages=[
                Message(role="system", content="You are TITAN-CODE, an expert patch generator for software repositories."),
                Message(role="user", content="Emit a patch bundle."),
            ],
            model="kilo/minimax/minimax-m2.5:free",
            reasoning_profile="xhigh",
            prompt_role="patch_generator",
        )

    result = anyio.run(run)
    assert result.content == '{"ok": true}'
    args = list(seen["args"])
    variant_idx = args.index("--variant") + 1
    assert args[variant_idx] == "high"


def test_kilo_patch_generator_overlay_carries_quality_bans() -> None:
    config = load_config()
    overlay = compose_native_cli_overlay(
        provider_name="kilo_cli",
        model="kilo/minimax/minimax-m2.5:free",
        reasoning_profile="xhigh",
        system_prompt="You are TITAN-CODE, an expert patch generator for software repositories.",
        prompt_role="patch_generator",
        prompt_root=config.prompts_path,
    )

    assert "do NOT invent a fake \"trusted by\" logo strip" in overlay
    assert "second distinct proof/control move deeper in the page" in overlay
    assert "allow at most one uniform card-grid section" in overlay
    assert "large empty dark band with one lonely button" in overlay


def test_droid_cli_vision_uses_workspace_files(monkeypatch) -> None:
    provider = DroidCLIProvider(load_config())
    seen: dict[str, object] = {}

    async def fake_run_cli(*, args, cwd, env, timeout_s, output_file=None):
        seen["args"] = args
        seen["cwd"] = cwd
        _ = (env, timeout_s, output_file)
        return CompletionResponse(content='{"score": 8.8}', model="claude-opus-4-6")

    monkeypatch.setattr(provider, "_run_cli", fake_run_cli)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[Message(role="user", content="Score these screenshots.")],
            model="claude-opus-4-6",
            images=[b"fake-image-bytes"],
            reasoning_profile="high",
            prompt_role="vision_score",
        )

    result = anyio.run(run)
    assert result.content == '{"score": 8.8}'
    args = list(seen["args"])
    assert "stream-json" in args
    assert "--reasoning-effort" in args
    assert "max" in args
    assert "--auto" in args
    prompt = str(args[-1])
    assert "VISUAL INPUT FILES" in prompt
    assert "OPUS INTERLEAVED REASONING CONTRACT" in prompt


def test_droid_cli_extracts_last_assistant_message_from_stream_json() -> None:
    provider = DroidCLIProvider(load_config())
    content = provider._extract_content(
        stdout_text=(
            '{"type":"system","subtype":"init"}\n'
            '{"type":"message","role":"assistant","text":"{\\"score\\": 8.9}"}\n'
            '{"type":"completion","finalText":""}\n'
        ),
        stderr_text="",
        output_file=None,
    )

    assert content == '{"score": 8.9}'


def test_droid_cli_raises_on_stream_json_error() -> None:
    provider = DroidCLIProvider(load_config())

    try:
        provider._extract_content(
            stdout_text='{"type":"error","message":"402 status code (no body)"}\n',
            stderr_text="",
            output_file=None,
        )
    except RuntimeError as exc:
        assert "402 status code" in str(exc)
    else:
        raise AssertionError("expected RuntimeError from droid stream-json error event")


def test_droid_cli_minimax_uses_visual_proxy(monkeypatch) -> None:
    provider = DroidCLIProvider(load_config())
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "frontend_design_loop_core.providers.droid_cli.build_visual_proxy_context",
        lambda image_paths: f"proxy:{len(image_paths)}",
    )

    async def fake_complete(*, messages, model, max_tokens=500, temperature=0.1, **kwargs):
        seen["messages"] = messages
        seen["model"] = model
        seen["kwargs"] = kwargs
        _ = (max_tokens, temperature)
        return CompletionResponse(content='{"score": 8.1}', model=model)

    monkeypatch.setattr(provider, "complete", fake_complete)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[Message(role="user", content="Score this screenshot.")],
            model="custom:minimax/minimax-m2.5:free",
            images=[b"fake-image-bytes"],
            prompt_role="vision_score",
        )

    result = anyio.run(run)
    assert result.content == '{"score": 8.1}'
    rendered = seen["messages"]
    assert any("SCREENSHOT_PROXY_CONTEXT" in str(msg.content) for msg in rendered)
    assert any("structural render-health check" in str(msg.content) for msg in rendered)


def test_kilo_cli_extracts_last_text_event() -> None:
    provider = KiloCLIProvider(load_config())
    content = provider._extract_content(
        stdout_text=(
            '{"type":"step_start","part":{"type":"step-start"}}\n'
            '{"type":"text","part":{"text":"{\\"score\\": 8.4}"}}\n'
            '{"type":"step_finish","part":{"type":"step-finish"}}\n'
        ),
        stderr_text="",
        output_file=None,
    )

    assert content == '{"score": 8.4}'


def test_kilo_cli_merges_streamed_text_fragments_when_they_form_valid_json() -> None:
    provider = KiloCLIProvider(load_config())
    content = provider._extract_content(
        stdout_text=(
            '{"type":"text","part":{"text":"{\\"patches\\":["}}\n'
            '{"type":"text","part":{"text":"{\\"path\\":\\"index.html\\",\\"patch\\":\\"@@ -1,1 +1,1 @@\\\\n-hi\\\\n+hello\\\\n\\"}]}"}}\n'
        ),
        stderr_text="",
        output_file=None,
    )

    assert content == '{"patches":[{"path":"index.html","patch":"@@ -1,1 +1,1 @@\\n-hi\\n+hello\\n"}]}'


def test_kilo_cli_minimax_uses_visual_proxy(monkeypatch) -> None:
    provider = KiloCLIProvider(load_config())
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "frontend_design_loop_core.providers.kilo_cli.build_visual_proxy_context",
        lambda image_paths: f"proxy:{len(image_paths)}",
    )

    async def fake_complete(*, messages, model, max_tokens=500, temperature=0.1, **kwargs):
        seen["messages"] = messages
        seen["model"] = model
        seen["kwargs"] = kwargs
        _ = (max_tokens, temperature)
        return CompletionResponse(content='{"score": 8.0}', model=model)

    monkeypatch.setattr(provider, "complete", fake_complete)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[Message(role="user", content="Score this screenshot.")],
            model="kilo/minimax/minimax-m2.5:free",
            images=[b"fake-image-bytes"],
            prompt_role="vision_score",
        )

    result = anyio.run(run)
    assert result.content == '{"score": 8.0}'
    rendered = seen["messages"]
    assert any("SCREENSHOT_PROXY_CONTEXT" in str(msg.content) for msg in rendered)
    assert any("structural render-health check" in str(msg.content) for msg in rendered)


def test_kilo_cli_minimax_section_creativity_uses_coarse_creativity_proxy(monkeypatch) -> None:
    provider = KiloCLIProvider(load_config())
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "frontend_design_loop_core.providers.kilo_cli.build_visual_proxy_context",
        lambda image_paths: f"proxy:{len(image_paths)}",
    )

    async def fake_complete(*, messages, model, max_tokens=500, temperature=0.1, **kwargs):
        seen["messages"] = messages
        seen["model"] = model
        seen["kwargs"] = kwargs
        _ = (max_tokens, temperature)
        return CompletionResponse(content='{"sections": []}', model=model)

    monkeypatch.setattr(provider, "complete", fake_complete)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[Message(role="user", content="Map strong and weak sections.")],
            model="kilo/minimax/minimax-m2.5:free",
            images=[b"fake-image-bytes"],
            prompt_role="section_creativity",
        )

    result = anyio.run(run)
    assert result.content == '{"sections": []}'
    rendered = seen["messages"]
    assert any("SCREENSHOT_PROXY_CONTEXT" in str(msg.content) for msg in rendered)
    assert any("generic-vs-distinctive structure" in str(msg.content) for msg in rendered)
    assert not any("structurally broken, blank, or obviously misrendered" in str(msg.content) for msg in rendered)



def test_opencode_cli_supports_file_attachments_for_vision(monkeypatch) -> None:
    provider = OpenCodeCLIProvider(load_config())
    seen: dict[str, object] = {}

    async def fake_run_cli(*, args, cwd, env, timeout_s, output_file=None):
        seen["args"] = args
        seen["cwd"] = cwd
        _ = (env, timeout_s, output_file)
        return CompletionResponse(content='{"score": 9.2}', model="anthropic/claude-opus-4-6")

    monkeypatch.setattr(provider, "_run_cli", fake_run_cli)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[Message(role="user", content="Score these screenshots.")],
            model="anthropic/claude-opus-4-6",
            images=[b"fake-image-bytes"],
            reasoning_profile="xhigh",
            prompt_role="vision_score",
        )

    result = anyio.run(run)
    assert result.content == '{"score": 9.2}'
    args = list(seen["args"])
    assert "--file" in args
    assert "--variant" in args
    assert "max" in args
    assert "--" in args
    prompt = str(args[-1])
    assert "OPUS INTERLEAVED REASONING CONTRACT" in prompt


def test_opencode_cli_minimax_uses_visual_proxy(monkeypatch) -> None:
    provider = OpenCodeCLIProvider(load_config())
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "frontend_design_loop_core.providers.opencode_cli.build_visual_proxy_context",
        lambda image_paths: f"proxy:{len(image_paths)}",
    )

    async def fake_complete(*, messages, model, max_tokens=500, temperature=0.1, **kwargs):
        seen["messages"] = messages
        seen["model"] = model
        seen["kwargs"] = kwargs
        _ = (max_tokens, temperature)
        return CompletionResponse(content='{"score": 7.9}', model=model)

    monkeypatch.setattr(provider, "complete", fake_complete)

    async def run() -> CompletionResponse:
        return await provider.complete_with_vision(
            messages=[Message(role="user", content="Score this screenshot.")],
            model="opencode/minimax-m2.5-free",
            images=[b"fake-image-bytes"],
            prompt_role="vision_score",
        )

    result = anyio.run(run)
    assert result.content == '{"score": 7.9}'
    rendered = seen["messages"]
    assert any("SCREENSHOT_PROXY_CONTEXT" in str(msg.content) for msg in rendered)
    assert any("structural render-health check" in str(msg.content) for msg in rendered)
