"""Native policy regressions and real pipe/process transport (no model calls)."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from frontend_design_loop_core.config import load_config
from frontend_design_loop_core.providers._cli_base import NativeCLIError, safe_diagnostic
from frontend_design_loop_core.providers.base import CompletionResponse, Message
from frontend_design_loop_core.providers.claude_cli import ClaudeCLIProvider
from frontend_design_loop_core.providers.codex_cli import CodexCLIProvider
from frontend_design_loop_core.providers.opencode_cli import OpenCodeCLIProvider
from frontend_design_loop_core.reasoning_prompts import compose_native_cli_overlay
from frontend_design_loop_core.utils import run_process_argv

PROVIDERS = [
    (CodexCLIProvider, "gpt-6.1-sol"),
    (ClaudeCLIProvider, "claude-opus-5-5"),
    (OpenCodeCLIProvider, "openai/gpt-6.1-sol"),
]
CODEX_HELP = "--ignore-user-config --ignore-rules --ephemeral --json --sandbox --model"
CLAUDE_HELP = "--restricted --safe-mode --permission-prompts --strict-mcp-config --setting-sources --allowedTools --tools --no-session-persistence\n--effort <level> (low, medium, high, xhigh, max)\n--model"
OPENCODE_HELP = "--pure --variant --agent --format --dir"


def catalog(model="openai/gpt-6.1-sol", **changes):
    provider, model_id = model.split("/", 1)
    obj = {
        "id": model_id,
        "providerID": provider,
        "api": {"id": model_id, "url": "https://api.openai.com/v1"},
        "variants": {"high": {}, "xhigh": {}, "max": {}},
        "capabilities": {"input": {"image": True}, "toolcall": True},
        "options": {},
        "headers": {},
    }
    obj.update(changes)
    return model + "\n" + json.dumps(obj, indent=2)


def fake_probe(provider, monkeypatch, *, auth=None, metadata=None, help_text=None):
    async def probe(args, **kwargs):
        if "--help" in args:
            return (
                0,
                help_text
                or {
                    "codex_cli": CODEX_HELP,
                    "claude_cli": CLAUDE_HELP,
                    "opencode_cli": OPENCODE_HELP,
                }[provider.name],
                "",
            )
        if "login" in args:
            return 0, "", auth or "Logged in using ChatGPT"
        if "models" in args:
            return 0, metadata or catalog(), ""
        if provider.name == "claude_cli":
            return (
                0,
                auth
                or json.dumps(
                    {
                        "loggedIn": True,
                        "authMethod": "claude.ai",
                        "apiProvider": "firstParty",
                        "email": "private@example.com",
                        "access_token": "secret",
                    }
                ),
                "",
            )
        return 0, auth or "│ ● OpenAI oauth\n└ 1 credentials", ""

    monkeypatch.setattr(provider, "_probe", probe)


@pytest.mark.parametrize("cls,model", PROVIDERS)
def test_subscription_env_excludes_inherited_keys_gateways_and_runtime_controls(
    cls, model, monkeypatch, tmp_path
):
    for key in (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "OPENAI_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "OPENCODE_CONFIG_CONTENT",
        "OPENCODE_PERMISSION",
        "AWS_SECRET_ACCESS_KEY",
    ):
        monkeypatch.setenv(key, "private-secret")
    provider = cls(load_config())
    env = provider._build_env({"auth_mode": "subscription", "runtime_dir": tmp_path})
    assert "private-secret" not in json.dumps(env)
    with pytest.raises(NativeCLIError, match="rejects environment"):
        provider._build_env(
            {
                "auth_mode": "subscription",
                "runtime_dir": tmp_path,
                "env": {"OPENAI_BASE_URL": "private-secret"},
            }
        )
    api_env = provider._build_env({"auth_mode": "api_key", "runtime_dir": tmp_path})
    if cls is not OpenCodeCLIProvider:
        assert "private-secret" in json.dumps(api_env)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,model", PROVIDERS)
async def test_exact_effort_stdin_and_honest_receipt(cls, model, monkeypatch, tmp_path):
    provider = cls(load_config())
    fake_probe(provider, monkeypatch)
    seen = {}

    async def run(**kwargs):
        seen.update(kwargs)
        assert "secret prompt" not in json.dumps(kwargs["args"])
        return CompletionResponse(
            content="result",
            model="untrusted compatibility field",
            raw_response={"stdout": "secret", "args": ["secret"]},
        )

    monkeypatch.setattr(provider, "_run_cli", run)
    response = await provider.complete(
        [Message(role="user", content="secret prompt")],
        model,
        reasoning_profile="xhigh",
        timeout_s=10,
    )
    assert "secret prompt" in seen["input_text"]
    assert not Path(seen["cwd"]).exists()
    if cls is CodexCLIProvider:
        assert 'model_reasoning_effort="xhigh"' in seen["args"]
        assert "--ignore-user-config" in seen["args"]
        assert "read-only" in seen["args"]
        assert "features.shell_tool=false" in seen["args"]
    else:
        flag = "--effort" if cls is ClaudeCLIProvider else "--variant"
        assert seen["args"][seen["args"].index(flag) + 1] == "xhigh"
    execution = response.raw_response["execution"]
    assert execution["requested"]["model"] == model
    assert execution["observed"]["model"] is None
    assert execution["observed"]["reasoning_profile"] is None
    assert execution["observed"]["auth_mode"] == "subscription"
    assert execution["unsupported_controls"] == ["max_tokens", "temperature"]
    assert "secret" not in json.dumps(response.raw_response)


@pytest.mark.asyncio
async def test_claude_rejects_native_silent_effort_downgrade(monkeypatch):
    provider = ClaudeCLIProvider(load_config())
    fake_probe(provider, monkeypatch)
    with pytest.raises(NativeCLIError, match="xhigh is unsupported on 4.6"):
        await provider.preflight("claude-opus-4-6", reasoning_profile="xhigh")
    assert (await provider.preflight("claude-opus-4-6", reasoning_profile="max"))[
        "auth_mode"
    ] == "subscription"
    with pytest.raises(NativeCLIError, match="documented capability"):
        await provider.preflight("claude-haiku-4-5", reasoning_profile="high")
    with pytest.raises(NativeCLIError, match="does not advertise effort"):
        await provider.preflight("claude-opus-5-5", reasoning_profile="none")


@pytest.mark.asyncio
async def test_codex_catalog_validates_exact_effort_without_assuming_max_is_xhigh(
    monkeypatch, tmp_path
):
    provider = CodexCLIProvider(load_config())
    fake_probe(provider, monkeypatch)
    home = tmp_path / "codex"
    home.mkdir()
    (home / "models_cache.json").write_text(
        json.dumps(
            {"models": [{"slug": "gpt-6.1-sol", "supported_reasoning_levels": [{"effort": "max"}]}]}
        )
    )
    assert (
        await provider.preflight(
            "gpt-6.1-sol", reasoning_profile="max", env={"CODEX_HOME": str(home)}
        )
    )["advertised_efforts"] == ["max"]
    with pytest.raises(NativeCLIError, match="does not advertise"):
        await provider.preflight(
            "gpt-6.1-sol", reasoning_profile="xhigh", env={"CODEX_HOME": str(home)}
        )
    args = provider._build_command(
        model="gpt-6.1-sol",
        prompt="long",
        cwd=tmp_path,
        kwargs={"reasoning_profile": "max", "auth_mode": "subscription"},
    )
    assert 'model_reasoning_effort="max"' in args


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,model", PROVIDERS)
async def test_subscription_rejects_api_login_and_unavailable_isolation(cls, model, monkeypatch):
    provider = cls(load_config())
    auth = {
        CodexCLIProvider: "Logged in using an API key: sk-private",
        ClaudeCLIProvider: json.dumps(
            {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"}
        ),
        OpenCodeCLIProvider: "OpenAI api\n",
    }[cls]
    fake_probe(provider, monkeypatch, auth=auth)
    with pytest.raises(NativeCLIError):
        await provider.preflight(model)
    assert (await provider.preflight(model, auth_mode="api_key"))["auth_mode"] == "api_key"
    fake_probe(provider, monkeypatch, help_text="--model")
    with pytest.raises(NativeCLIError, match="upgrade"):
        await provider.preflight(model)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,match",
    [
        ({"variants": {"max": {}}}, "exact requested variant"),
        ({"capabilities": {"input": {"image": False}, "toolcall": True}}, "image input"),
        ({"api": {"id": "other"}}, "different API model"),
        ({"options": {"baseURL": "https://gateway.invalid"}}, "overrides"),
        ({"api": {"id": "gpt-6.1-sol", "url": "https://gateway.invalid"}}, "first-party"),
    ],
)
async def test_opencode_capabilities_auth_and_routes_are_not_guessed(changes, match, monkeypatch):
    provider = OpenCodeCLIProvider(load_config())
    fake_probe(provider, monkeypatch, metadata=catalog(**changes))
    with pytest.raises(NativeCLIError, match=match):
        await provider.complete_with_vision(
            [Message(role="user", content="judge")],
            "openai/gpt-6.1-sol",
            [b"image"],
            reasoning_profile="xhigh",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,model", PROVIDERS)
async def test_judge_readonly_and_editing_confined_to_explicit_caller_workspace(
    cls, model, monkeypatch, tmp_path
):
    provider = cls(load_config())
    fake_probe(provider, monkeypatch)
    calls = []

    async def run(**kwargs):
        calls.append(kwargs)
        return CompletionResponse(
            content="ok",
            model=model,
            raw_response={
                "execution": {
                    "observed": {
                        "verified_image_reads": [
                            str(path) for path in kwargs.get("cwd", Path(".")).glob("image_*")
                        ]
                    }
                }
            },
        )

    monkeypatch.setattr(provider, "_run_cli", run)
    await provider.complete_with_vision(
        [Message(role="system", content="Judge")], model, [b"image"], prompt_role="vision_score"
    )
    judge = calls[-1]
    assert "bypassPermissions" not in judge["args"]
    assert "IMPLEMENTATION CONTRACT" not in judge["input_text"]
    if cls is ClaudeCLIProvider:
        assert judge["args"][judge["args"].index("--tools") + 1] == "Read"
        assert "dontAsk" in judge["args"]
        assert "--add-dir" not in judge["args"]
    if cls is OpenCodeCLIProvider:
        config = json.loads(judge["env"]["OPENCODE_CONFIG_CONTENT"])
        assert config["permission"]["edit"] == "deny"
        assert config["permission"]["*"] == "deny"
        assert config["permission"]["external_directory"] == "deny"
    with pytest.raises(ValueError, match="explicit"):
        await provider.edit_repository([], model, tmp_path)
    await provider.edit_repository(
        [Message(role="user", content="implement")],
        model,
        tmp_path,
        reasoning_profile="high",
        auth_mode="subscription",
        timeout_s=30,
    )
    editing = calls[-1]
    assert editing["cwd"] == tmp_path.resolve()
    assert tmp_path.exists()
    assert "bypassPermissions" not in editing["args"]
    if cls is CodexCLIProvider:
        assert "workspace-write" in editing["args"]
    if cls is ClaudeCLIProvider:
        assert "acceptEdits" in editing["args"]
        assert editing["args"][editing["args"].index("--tools") + 1] == "Read,Glob,Grep,Edit,Write"
        assert (
            json.loads(editing["args"][editing["args"].index("--settings") + 1])[
                "switchModelsOnFlag"
            ]
            is False
        )


@pytest.mark.asyncio
async def test_observed_model_or_effort_mismatch_rejected_with_failure_receipt(monkeypatch):
    provider = ClaudeCLIProvider(load_config())
    fake_probe(provider, monkeypatch)

    async def run(**kwargs):
        return CompletionResponse(
            content="ok",
            model="ignored",
            raw_response={"execution": {"observed": {"model": "claude-sonnet-5-5"}}},
        )

    monkeypatch.setattr(provider, "_run_cli", run)
    with pytest.raises(NativeCLIError, match="fallback") as exc:
        await provider.complete([], "claude-opus-5-5")
    assert exc.value.execution["observed"]["model"] == "claude-sonnet-5-5"
    assert exc.value.execution["requested"]["model"] == "claude-opus-5-5"


def test_native_json_errors_and_receipts_are_not_assistant_claims():
    claude = ClaudeCLIProvider(load_config())
    result = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "result": "model claims anything",
            "modelUsage": {"claude-opus-5-5": {}},
        }
    )
    assert (
        claude._extract_content(stdout_text=result, stderr_text="", output_file=None)
        == "model claims anything"
    )
    assert claude._observed_execution(result)["model"] == "claude-opus-5-5"
    for provider, text in [
        (claude, '{"type":"result","is_error":true}'),
        (CodexCLIProvider(load_config()), '{"type":"turn.failed"}'),
        (OpenCodeCLIProvider(load_config()), '{"type":"error"}'),
    ]:
        with pytest.raises(NativeCLIError):
            provider._extract_content(stdout_text=text, stderr_text="", output_file=None)
    assert CodexCLIProvider(load_config())._observed_execution('{"model":"invented"}') == {}
    assert (
        safe_diagnostic(
            "key=secret Bearer abc sk-private somebody@example.com", {"API_KEY": "secret"}
        ).count("redacted")
        >= 4
    )


@pytest.mark.parametrize(
    "role",
    [
        "planner_bold",
        "planner_safe",
        "planner_synth",
        "refine_reasoner",
        "vision_broken",
        "vision_score",
        "section_creativity",
        "creative_director",
        "judge",
    ],
)
def test_planner_and_judge_do_not_inherit_implementation_packs(role):
    overlay = compose_native_cli_overlay(
        provider_name="codex_cli",
        model="gpt-6.1-sol",
        reasoning_profile="xhigh",
        system_prompt="",
        prompt_role=role,
    )
    assert "IMPLEMENTATION CONTRACT" not in overlay
    assert "maximum internal" not in overlay
    assert "Hidden reasoning target" not in overlay
    assert "at most one" not in overlay


def test_reasoning_packs_are_identical_in_distribution():
    root = Path(__file__).resolve().parents[1]
    for file in (root / "prompts").glob("reasoning_*.md"):
        assert (
            file.read_bytes()
            == (root / "src/frontend_design_loop_mcp/assets/prompts" / file.name).read_bytes()
        )


@pytest.mark.asyncio
async def test_actual_subprocess_stdin_long_prompt_and_deliberate_eof():
    prompt = "a ✓ quoted $HOME `cmd`\n" * 20000
    rc, out, err = await run_process_argv(
        [sys.executable, "-c", "import sys; s=sys.stdin.buffer.read(); print(len(s))"],
        input_text=prompt,
    )
    assert rc == 0 and int(out) == len(prompt.encode()) and not err
    rc, out, _ = await run_process_argv(
        [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"]
    )
    assert rc == 0 and out.strip() == "''"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix", reason="POSIX process groups; Windows taskkill is separately mocked"
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_actual_timeout_and_cancellation_stop_descendants(tmp_path, cancel):
    stopped = tmp_path / "stopped"
    ready = tmp_path / "ready"
    child = f"import signal,time; signal.signal(signal.SIGTERM,lambda *a:(open({str(stopped)!r},'w').write('stopped'),exit(0))); open({str(ready)!r},'w').write('ready'); time.sleep(60)"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
    task = asyncio.create_task(
        run_process_argv(
            [sys.executable, "-c", parent], timeout_s=10 if cancel else 0.6, input_text="prompt"
        )
    )
    if cancel:
        for _ in range(100):
            if ready.exists():
                break
            await asyncio.sleep(0.01)
        assert ready.exists()
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=3)
    assert stopped.read_text() == "stopped"


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,model", PROVIDERS)
@pytest.mark.parametrize("operation", ["complete", "vision", "edit_repository"])
async def test_provider_protocol_with_real_subprocess_and_long_stdin(
    cls, model, operation, monkeypatch, tmp_path
):
    """Exercise native help/auth/run parsing with a deterministic CLI fixture."""
    script = tmp_path / "native_fixture.py"
    script.write_text("""import sys,json,os
from pathlib import Path
name=sys.argv[1]; args=sys.argv[2:]
if '--help' in args:
 print({'codex': '--ignore-user-config --ignore-rules --ephemeral --json --sandbox --model',
        'claude': '--restricted --safe-mode --permission-prompts --strict-mcp-config --setting-sources --allowedTools --tools --no-session-persistence\\n--effort <level> (low, medium, high, xhigh, max)\\n--model',
        'opencode': '--pure --variant --agent --format --dir'}[name]); sys.exit()
if 'login' in args:
 print('Logged in using ChatGPT',file=sys.stderr); sys.exit()
if 'auth' in args:
 if name=='claude': print(json.dumps({'loggedIn':True,'authMethod':'claude.ai','apiProvider':'firstParty','access_token':'private-fixture-token','email':'private@example.com'}))
 else: print('OpenAI oauth')
 sys.exit()
if 'models' in args:
 print('openai/gpt-6.1-sol')
 print(json.dumps({'id':'gpt-6.1-sol','providerID':'openai','api':{'id':'gpt-6.1-sol','url':'https://api.openai.com/v1'},'variants':{'high':{},'xhigh':{}},'capabilities':{'input':{'image':True},'toolcall':True}}));sys.exit()
prompt=sys.stdin.read()
assert len(prompt)>500000
assert not any('long prompt marker' in arg for arg in args)
model=args[args.index('-m')+1] if name=='codex' else args[args.index('--model')+1]
edit=('-s' in args and args[args.index('-s')+1]=='workspace-write') or 'acceptEdits' in args or (name=='opencode' and json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])['permission']['edit']=='allow')
if edit: Path('native-edited.txt').write_text('edited by fixture')
for flag in ('-i','--file'):
 for idx,arg in enumerate(args):
  if arg==flag: assert Path(args[idx+1]).is_file()
result=json.dumps({'prompt_chars':len(prompt),'edited':edit})
if name=='claude':
 import re
 events=[]
 for idx,path in enumerate(re.findall(r'^- (.+image_\\d+\\.(?:png|jpg))$',prompt,re.M)):
  events += [{'type':'assistant','message':{'content':[{'type':'tool_use','id':str(idx),'name':'Read','input':{'file_path':path}}]}}, {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':str(idx),'content':[{'type':'image'}]}]}}]
 events.append({'type':'result','subtype':'success','is_error':False,'result':result,'modelUsage':{model:{}}})
 print(json.dumps(events))
elif name=='codex':
 Path(args[args.index('--output-last-message')+1]).write_text(result)
 print(json.dumps({'type':'thread.started','thread_id':'fixture'}))
 print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':result}}))
else: print(json.dumps({'type':'text','part':{'text':result}}))
""")
    provider = cls(load_config())
    original_probe = provider._probe
    original_command = provider._build_command

    async def probe(args, **kwargs):
        return await original_probe(
            [sys.executable, str(script), cls.cli_name, *args[1:]], **kwargs
        )

    def command(**kwargs):
        args = original_command(**kwargs)
        return [sys.executable, str(script), cls.cli_name, *args[1:]]

    monkeypatch.setattr(provider, "_probe", probe)
    monkeypatch.setattr(provider, "_build_command", command)
    messages = [Message(role="user", content="long prompt marker ✓ $HOME `cmd`\n" * 20000)]
    if operation == "edit_repository":
        repo = tmp_path / "isolated repo with spaces"
        repo.mkdir()
        response = await provider.edit_repository(
            messages,
            model,
            repo,
            images=[b"image"],
            reasoning_profile="xhigh",
            auth_mode="subscription",
            timeout_s=10,
        )
        assert (repo / "native-edited.txt").read_text() == "edited by fixture"
    elif operation == "vision":
        response = await provider.complete_with_vision(
            messages, model, [b"image"], reasoning_profile="xhigh", timeout_s=10
        )
    else:
        response = await provider.complete(messages, model, reasoning_profile="xhigh", timeout_s=10)
    assert json.loads(response.content)["prompt_chars"] > 500000
    assert response.raw_response["process"]["prompt_transport"] == "stdin"
    assert response.raw_response["execution"]["requested"]["operation"] == operation
    assert "private-fixture-token" not in json.dumps(response.raw_response)
    assert "private@example.com" not in json.dumps(response.raw_response)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["openrouter", "gemini", "vertex", "anthropic_vertex"])
@pytest.mark.parametrize("vision", [False, True])
async def test_cloud_routes_refuse_subscription_policy_before_auth_or_network(
    provider_name, vision
):
    from importlib import import_module

    from frontend_design_loop_core.providers import AuthPolicyError

    names = {
        "openrouter": "OpenRouterProvider",
        "gemini": "GeminiProvider",
        "vertex": "VertexProvider",
        "anthropic_vertex": "AnthropicVertexProvider",
    }
    cls = getattr(
        import_module(f"frontend_design_loop_core.providers.{provider_name}"), names[provider_name]
    )
    provider = object.__new__(cls)
    method = provider.complete_with_vision if vision else provider.complete
    kwargs = {"images": [b"image"]} if vision else {}
    with pytest.raises(AuthPolicyError, match="cannot satisfy auth_mode=subscription"):
        await method([], "explicit-model", auth_mode="subscription", **kwargs)


@pytest.mark.asyncio
async def test_native_registry_loads_without_optional_cloud_sdk():
    source = Path(__file__).resolve().parents[1] / "src"
    code = f"""import sys,importlib.abc
sys.path.insert(0,{str(source)!r})
class BlockCloud(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='google' or fullname.startswith('google.'):
   raise ModuleNotFoundError('fixture optional SDK unavailable',name=fullname)
sys.meta_path.insert(0,BlockCloud())
from frontend_design_loop_core.providers import ProviderFactory
from frontend_design_loop_core.config import load_config
assert ProviderFactory.get('codex_cli',load_config()).name=='codex_cli'
try: ProviderFactory.get('vertex',load_config())
except ValueError as exc: assert '[cloud]' in str(exc)
else: raise AssertionError('missing cloud SDK must report the optional install')
print('native registry works without google SDKs')
"""
    rc, out, err = await run_process_argv([sys.executable, "-I", "-c", code])
    assert rc == 0, err
    assert "native registry works" in out


@pytest.mark.asyncio
async def test_opencode_subscription_requires_a_verified_native_loader(monkeypatch):
    provider = OpenCodeCLIProvider(load_config())

    async def forbid_probe(*args, **kwargs):
        pytest.fail("An unverified subscription loader must fail before any process starts")

    monkeypatch.setattr(provider, "_probe", forbid_probe)
    with pytest.raises(NativeCLIError, match="verified native OpenAI subscription loader"):
        await provider.preflight("anthropic/claude-opus-5-5", reasoning_profile="xhigh")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process group success cleanup")
async def test_successful_parent_does_not_leave_a_helper_with_closed_pipes(tmp_path):
    ready = tmp_path / "ready"
    stopped = tmp_path / "stopped"
    child = f"import signal,time; signal.signal(signal.SIGTERM,lambda *a:(open({str(stopped)!r},'w').write('stopped'),exit(0))); open({str(ready)!r},'w').write('ready'); time.sleep(60)"
    parent = f"""import subprocess,sys,time
from pathlib import Path
subprocess.Popen([sys.executable,'-c',{child!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
while not Path({str(ready)!r}).exists(): time.sleep(.01)
print('parent done')
"""
    rc, out, err = await run_process_argv([sys.executable, "-c", parent], timeout_s=3)
    assert (rc, out.strip(), err) == (0, "parent done", "")
    assert stopped.read_text() == "stopped"


@pytest.mark.asyncio
async def test_optional_timeout_none_retains_default_and_invalid_timeout_never_launches(
    monkeypatch,
):
    provider = ClaudeCLIProvider(load_config())
    fake_probe(provider, monkeypatch)
    seen = []

    async def run(**kwargs):
        seen.append(kwargs)
        return CompletionResponse(content="ok", model="claude-opus-5-5")

    monkeypatch.setattr(provider, "_run_cli", run)
    response = await provider.complete([], "claude-opus-5-5", timeout_s=None)
    assert response.raw_response["execution"]["requested"]["timeout_s"] == 300
    for value in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="finite and positive"):
            await provider.complete([], "claude-opus-5-5", timeout_s=value)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_opencode_builtin_sdk_default_and_stderr_help(monkeypatch):
    provider = OpenCodeCLIProvider(load_config())
    fake_probe(
        provider,
        monkeypatch,
        metadata=catalog(api={"id": "gpt-6.1-sol", "url": "", "npm": "@ai-sdk/openai"}),
    )
    original = provider._probe

    async def stderr_help(args, **kwargs):
        rc, out, error = await original(args, **kwargs)
        return (rc, "", out) if "--help" in args else (rc, out, error)

    monkeypatch.setattr(provider, "_probe", stderr_help)
    result = await provider.preflight(
        "openai/gpt-6.1-sol", reasoning_profile="high", auth_mode="subscription"
    )
    assert result["auth_mode"] == "subscription" and result["user_config_isolated"]
    fake_probe(
        provider,
        monkeypatch,
        metadata=catalog(api={"id": "gpt-6.1-sol", "url": "", "npm": "custom-sdk"}),
    )
    with pytest.raises(NativeCLIError, match="first-party"):
        await provider.preflight(
            "openai/gpt-6.1-sol", reasoning_profile="high", auth_mode="subscription"
        )


def test_native_error_fields_surface_auth_failure_without_transcript():
    from frontend_design_loop_core.providers._cli_base import native_failure_diagnostic

    text = json.dumps(
        [
            {"type": "text", "part": {"text": "private user prompt"}},
            {
                "type": "error",
                "error": {"name": "UnknownError", "data": {"message": "Token refresh failed: 401"}},
            },
        ]
    )
    assert native_failure_diagnostic(text, {}) == "Token refresh failed: 401"
    assert (
        native_failure_diagnostic(json.dumps({"type": "text", "text": "private prompt"}), {}) == ""
    )


def test_native_and_toolkit_servers_import_without_optional_cloud_dependencies():
    import subprocess

    program = """
import importlib.abc
import sys
class NoCloud(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'google', 'tenacity', 'requests'}:
            raise ModuleNotFoundError('Optional cloud dependency blocked', name=fullname)
sys.meta_path.insert(0, NoCloud())
import frontend_design_loop_core.mcp_code_server
import design_toolkit.server
from frontend_design_loop_core.providers import ProviderFactory
from frontend_design_loop_core.config import load_config
try:
    ProviderFactory.get('openrouter', load_config())
except ValueError as error:
    assert 'frontend-design-loop-mcp[cloud]' in str(error), str(error)
else:
    raise AssertionError('Cloud adapter should require the optional extra')
"""
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
