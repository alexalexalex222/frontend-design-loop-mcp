# CLI Agent Host Routing Plan

Date: 2026-03-06
Repo: /Users/alexburkhart/Desktop/saved/frontend-design-loop-mcp
Status: planning artifact

## Objective

Make Frontend Design Loop MCP work cleanly with host-side coding agents and CLIs, not just its own internal provider loop.

Target host agents:
- Claude Code / `claude`
- Codex / `codex`
- Gemini CLI / `gemini`
- Droid / `droid`
- OpenCode / `opencode`

Primary principle:
- When a capable host agent is already present, Petamind should not own the main reasoning loop.
- Petamind should become a deterministic coprocessor for worktrees, patch apply, tests, preview boot, screenshots, browser automation, and artifact persistence.
- Server-side provider-owned generation remains a fallback lane for unattended runs.

## Non-Negotiable Architecture

### Mode 1: `host_agent`

This is the default for interactive coding-agent environments.

The host agent owns:
- repo reading
- planning
- patch generation
- fix reasoning
- aesthetic judgment
- final accept/reject

Petamind owns:
- isolated git worktrees
- patch application
- deterministic gates
- preview command execution
- screenshot capture
- browser automation
- structured artifact output

Recommended Petamind entrypoint:
- `frontend_design_loop_eval`

Why:
- The live repo already describes `frontend_design_loop_eval` as the primitive for agent-orchestrated workflows.
- The live docs already recommend `vision_provider=client` for this path.

### Mode 2: `host_cli`

This is the unattended automation mode.

Petamind owns the orchestration loop, but model calls route through official local CLIs instead of cloud-provider SDK wrappers.

Examples:
- `claude --print --model claude-opus-4-6 --effort high|max`
- `codex exec --model gpt-5.4 -p pro-xhigh`
- `gemini -m gemini-3.1-pro-preview -p ...`
- `droid exec --model claude-opus-4-6 -r max`
- `opencode run --model provider/model --variant high|max`

Use this when:
- no interactive host agent is present
- you want the user's own CLI auth/account path
- you want durable unattended execution

### Mode 3: `provider`

This is the legacy mode.

Petamind owns generation, reasoning, and vision through its own configured providers.
Use only when no suitable host agent or host CLI is available.

## Required Petamind Changes

### 1. Add a routing switch

Add `solver_mode=host_agent|host_cli|provider` to the MCP interface.

Suggested default selection:
- Claude Code / Codex / Gemini CLI / Droid / OpenCode interactive sessions: `host_agent`
- scripted fire-and-forget runs with explicit CLI target: `host_cli`
- current config-only operation: `provider`

### 2. Stop double-owning reasoning in `host_agent`

In `host_agent` mode, bypass:
- `_call_llm_json()` planning/generation
- server-side refiner passes
- server-side section creativity passes
- server-side aesthetic winner selection beyond deterministic structural checks

Keep:
- tests/lint/build
- preview
- screenshots
- browser automation
- patch application
- artifact storage

### 3. Add CLI-backed providers

Create provider adapters that implement the existing provider interface but shell out to local CLIs.

Suggested new files:
- `src/frontend_design_loop_core/providers/claude_cli.py`
- `src/frontend_design_loop_core/providers/codex_cli.py`
- `src/frontend_design_loop_core/providers/gemini_cli.py`
- `src/frontend_design_loop_core/providers/droid_cli.py`
- `src/frontend_design_loop_core/providers/opencode_cli.py`

Keep the current `ProviderFactory` abstraction and register these providers there.

### 4. Separate planning from execution

Petamind should support a planner lane distinct from implementation.

Minimum useful split:
- planner agent/model
- implementer agent/model
- optional verifier/judge agent/model

This must not assume all CLIs expose the same knobs.

## Current Local Agent Reality

Verified installed CLIs:
- `claude`
- `codex`
- `gemini`
- `droid`
- `opencode`

Verified local control surfaces:

### Claude CLI
- supports `--model`
- supports `--effort`
- supports `--print`
- supports `--output-format`
- supports MCP config loading and tool restrictions

Implication:
- Claude is the cleanest `host_cli` target for high-depth planning and surgical implementation.

### Codex CLI
- supports `--model`
- supports config profiles
- local config already defaults to `gpt-5.4`
- local config already defines `pro-xhigh`, `codex54-xhigh`, and `planning` profiles

Implication:
- Codex is the cleanest path for MegaMind subprocess planning and high-effort code execution.

### Gemini CLI
- supports `--model`
- supports non-interactive prompt mode
- supports policy files and extensions
- local settings default to `gemini-3.1-pro-preview`

Implication:
- Gemini is viable as a host CLI, but reasoning depth is driven more by model choice and prompt structure than by an explicit CLI reasoning flag.

### Droid
- supports `--model`
- supports `--reasoning-effort`
- supports explicit tool enable/disable lists
- local install exposes Opus 4.6, GPT-5.4, Gemini 3.1 Pro, GLM-5, Kimi k2.5, and MiniMax M2.5
- local install does not currently expose `--spec-model` or `--use-spec` on `droid exec --help`

Implication:
- Do not design around doc-only spec-mode flags until they are verified in the installed binary.
- The safe headless integration surface today is `--model` plus `--reasoning-effort`.

### OpenCode
- supports `--model`
- supports `--agent`
- supports `--variant`
- supports `--thinking`
- docs support model-specific variants and agent model inheritance

Implication:
- OpenCode is a strong target for multi-agent role routing once Petamind can express planner/build/verifier roles.

## Existing Local Reasoning Skills

Verified skill files:
- `/Users/alexburkhart/.codex/skills/megamind/SKILL.md`
- `/Users/alexburkhart/.codex/skills/deepthink/SKILL.md`
- `/Users/alexburkhart/.codex/skills/ultrathink/SKILL.md`
- `/Users/alexburkhart/.codex/skills/subprocess-reasoning/SKILL.md`
- `/Users/alexburkhart/.codex/skills/megamind-subprocess/SKILL.md`

Recommended use:
- `ultrathink`: route low/medium/high/extreme tasks to the right reasoning depth
- `deepthink`: single-agent sequential reasoning when you need structure but not full MegaMind
- `megamind`: 10 -> 3 -> 1 reasoning for architecture, routing, planning, and ambiguous failure analysis
- `subprocess-reasoning`: run the heavy reasoning outside the main session to avoid context bloat
- `megamind-subprocess`: preferred planner primitive for Codex-backed planning lanes

## Recommended Reasoning Policy

### Base policy for all host agents

1. Use UltraThink to classify the task.
2. If complexity is high or critical, run MegaMind before implementation.
3. Persist the planner output as a file artifact.
4. Feed the synthesized plan into the implementation agent.
5. Run deterministic evaluation after each meaningful patch set.

### Planner output contract

Each planner must return:
- recommended architecture or patch strategy
- confidence 1-10
- top 3 risks
- exact verification checklist
- whether the implementer should act conservatively or aggressively

## 2026 Reasoning Tactics To Encode

These are the tactics worth encoding into Petamind prompt packs or provider adapters.

### Anthropic / Opus 4.6 tactics

Use:
- high or max reasoning effort
- general instructions rather than over-constraining chain detail
- enough token budget for thinking
- multishot examples when you need a specific thinking pattern
- interleaved tool use when investigation requires sequential evidence gathering

Why:
- Anthropic's current docs recommend giving Claude room to think with general guidance, using examples when a specific thinking pattern matters, and enabling interleaved thinking when tool use and reasoning need to alternate.

Petamind implication:
- For `claude_cli`, provide a dedicated `reasoning_style=megamind|deepthink|surgical` prompt wrapper.
- Prefer Opus 4.6 for planner and verifier lanes, not routine boilerplate generation.

### Gemini tactics

Use:
- model choice first (`gemini-3.1-pro-preview` for hard planning)
- explicit reasoning budget / thinking config when using API-backed routes
- dynamic thinking for open-ended planning, constrained budgets for latency-sensitive loops
- strong decomposition instructions plus explicit output schema

Why:
- Google's current docs for thinking models emphasize `thinkingBudget` / dynamic thinking as a real quality-latency control surface.

Petamind implication:
- `gemini_cli` adapter should support a reasoning style wrapper, but the deeper budget control will likely live in API-backed Gemini provider paths, not the current CLI surface.

### Codex tactics

Use:
- `gpt-5.4` with `xhigh` for planning and risky edits
- smaller execution prompts with explicit repo goals and verification criteria
- MegaMind as a subprocess planner, then a shorter implementation prompt for the main Codex run

Why:
- The live local Codex config already uses `gpt-5.4` + `xhigh` and defines dedicated high-effort profiles. This machine is already set up to do deep Codex reasoning cleanly.

Petamind implication:
- Codex should be the default MegaMind planner backend unless the user explicitly wants Opus or Gemini.

### Droid tactics

Use:
- explicit `--reasoning-effort`
- model-specific selection based on job type
- high-autonomy only for trusted deterministic follow-through

Why:
- Droid exposes model and reasoning effort directly in the local binary, which makes it a viable `host_cli` executor.

Petamind implication:
- treat Droid as an execution-capable alternate host CLI, not the primary planner until spec-mode controls are proven in the installed version.

### OpenCode tactics

Use:
- per-agent model assignment
- `--variant high|max` for harder reasoning tasks
- `--thinking` when you want exposed reasoning traces for debugging
- primary-agent model inheritance for subagents where possible

Why:
- OpenCode's current docs expose variant and agent-level routing as first-class controls.

Petamind implication:
- map planner/build/verifier roles directly into OpenCode agent definitions when implementing `opencode_cli`.

## Web-Verified 2026 Tactics Worth Adopting

1. Anthropic extended thinking guidance:
- use general instructions
- allow enough budget
- consider multishot examples for desired thinking patterns
- use interleaved thinking when tool use and thought should alternate

2. Gemini thinking guidance:
- explicitly control thinking budget where the route supports it
- use dynamic thinking for complex planning
- lower budgets for fast deterministic loops

3. OpenCode routing guidance:
- use model variants per task
- subagents inherit primary model when not explicitly overridden
- agent-specific models are a real supported concept

4. Factory mixed-model guidance:
- separate specification/planning from execution when the toolchain supports it
- do not assume documentation flags exist locally without verifying the installed binary

## New Prompt Packs To Add

These should be added as local Petamind prompt templates, not ad hoc inline strings.

1. `prompts/reasoning_megamind.md`
- wraps a task in the MegaMind 10 -> 3 -> 1 planning contract
- emits structured planner JSON

2. `prompts/reasoning_deepthink.md`
- sequential high-structure reasoning for medium-complexity work

3. `prompts/reasoning_opus46_interleaved.md`
- optimized for Opus 4.6
- encourages evidence-first investigation with tool reasoning cycles

4. `prompts/reasoning_gemini_thinking.md`
- decomposition-first planning prompt
- tuned for Gemini 3.1 Pro

5. `prompts/reasoning_codex_impl.md`
- convert planner output into short, surgical implementation instructions for Codex

## Implementation Order

### Step 1
Add `solver_mode` and make `host_agent` work with zero server-side LLM calls.

### Step 2
Promote `frontend_design_loop_eval` as the canonical Claude/Codex/Gemini interactive workflow.

### Step 3
Add `claude_cli` and `codex_cli` providers first.
These are the cleanest, best-verified local CLI surfaces.

### Step 4
Add `droid_cli` and `opencode_cli` providers.
Keep the interface minimal: prompt, model, reasoning profile, cwd, tools policy, output capture.

### Step 5
Add `gemini_cli` provider.
Be careful with environment inheritance and Vertex-vs-personal-account drift.

### Step 6
Add planner role support:
- planner backend
- implementer backend
- verifier backend

### Step 7
Add reasoning packs and structured planner outputs.

## Do Not Do

- Do not try to infer the active interactive model/session from inside MCP.
- Do not make Petamind recursively call a host CLI for every tiny step.
- Do not keep server-owned creativity or refinement loops active in `host_agent` mode.
- Do not depend on Droid spec-mode flags until the installed binary proves them.
- Do not let Gemini CLI inherit random Vertex or OAuth env without explicit sanitization.

## First Patch Set

Files to touch first:
- `src/frontend_design_loop_core/mcp_code_server.py`
- `src/frontend_design_loop_core/providers/base.py`
- `src/frontend_design_loop_core/config.py`
- `docs/FRONTEND_DESIGN_LOOP_MCP.md`
- `README.md`

Minimum first patch outcome:
- new `solver_mode`
- `host_agent` path using `frontend_design_loop_eval`
- docs updated so Claude/Codex interactive usage defaults to host-agent evaluation
- no provider recursion during host-agent runs

## Source References

Local source and docs:
- `docs/FRONTEND_DESIGN_LOOP_MCP.md`
- `README.md`
- `src/frontend_design_loop_core/mcp_code_server.py`
- `src/frontend_design_loop_core/providers/base.py`
- `src/frontend_design_loop_core/config.py`
- `/Users/alexburkhart/.codex/skills/megamind/SKILL.md`
- `/Users/alexburkhart/.codex/skills/deepthink/SKILL.md`
- `/Users/alexburkhart/.codex/skills/ultrathink/SKILL.md`
- `/Users/alexburkhart/.codex/skills/subprocess-reasoning/SKILL.md`
- `/Users/alexburkhart/.codex/skills/megamind-subprocess/SKILL.md`

Current official docs checked on 2026-03-06:
- Anthropic prompt engineering and extended thinking docs
- Google Gemini thinking docs
- Factory Droid mixed-model/specification docs
- OpenCode model/variant/agent docs
- OpenAI agent setup guidance around `AGENTS.md`
