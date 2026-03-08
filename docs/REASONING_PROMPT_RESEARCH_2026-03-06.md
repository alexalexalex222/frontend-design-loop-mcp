# Reasoning Prompt Research - 2026-03-06

Repo: `/Users/alexburkhart/Desktop/saved/frontend-design-loop-mcp`
Scope: official 2026 prompting guidance for short-reasoning and non-reasoning models, plus local reasoning-skill archaeology from the Codex/Claude prompt corpus.
Status: research memo for prompt-system design, not yet wired into runtime.

## Executive Summary

The strongest 2026 pattern is not "force more chain-of-thought." It is:

1. Route the task to the right reasoning depth.
2. Give the model a structured external scaffold.
3. Ask for evidence-backed intermediate artifacts instead of raw hidden CoT.
4. Interleave tools with reasoning when the task is empirical.
5. Use a critique or risk pass before final output.
6. Keep the final output schema rigid.

That matches the best parts of the local skill corpus much more than the weak parts.

The local corpus already has four reusable ideas that are better than generic "think harder" prompting:
- `ultrathink`: classify the task before selecting depth.
- `deepthink`: force decomposition, branch comparison, inversion, and critique.
- `megamind`: split reasoning into multiple angles, then synthesize conflict and risk.
- `subprocess-reasoning`: isolate heavy planning from the main execution context.

The official docs push in the same direction, but with an important correction:
- do **not** over-specify hidden reasoning format
- do **not** demand giant exposed chain-of-thought dumps
- do ask for structured work products: plan, evidence table, risk ledger, decision matrix, and next action

For Petamind, the best next design is:
- planner prompts should ask for visible planning artifacts, not raw hidden thought
- implementation prompts should stay short, precise, and schema-bound
- short-reasoning models like Opus 4.6 should get evidence-first and interleaved-tool prompts, not bloated "narrate every thought" instructions
- non-reasoning models should be scaffolded with multi-pass external structure: classify -> decompose -> propose -> critique -> verify

## What Official 2026 Guidance Actually Says

### Anthropic / Claude

Primary sources:
- Chain of thought tips: <https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/chain-of-thought>
- Extended thinking: <https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking>
- Prompt engineering overview: <https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview>

Verified takeaways:
- Anthropic recommends giving **general instructions** for how to think, not brittle micromanagement of hidden reasoning format.
- When you need a specific reasoning pattern, Anthropic recommends **examples** rather than over-constraining internal thinking.
- For tool-heavy tasks, Anthropic explicitly recommends **interleaved thinking** so the model can alternate between tool outputs and updated reasoning.
- Anthropic recommends **XML tags / explicit structure** for separating instructions, context, and examples.

Implication for Opus 4.6 and similar models:
- Good: "work evidence-first, separate observation from inference, update your plan after each tool result, output a risk table before the final answer."
- Bad: "show me 20,000 tokens of chain-of-thought" or rigid hidden-tag micromanagement.

### OpenAI / GPT-5 / Codex

Primary sources:
- GPT-5 prompting guide: <https://cookbook.openai.com/examples/gpt-5/gpt-5_prompting_guide>
- Platform prompt engineering guide: <https://platform.openai.com/docs/guides/prompt-engineering>

Verified takeaways:
- OpenAI recommends starting with a **minimal prompt** and only adding structure when needed.
- The strongest improvements come from **agentic loops** and explicit tool instructions, not from telling the model to narrate more hidden thoughts.
- OpenAI recommends using **rubrics/checklists** and explicit success criteria where accuracy matters.
- For code and agent workflows, the useful pattern is: plan first, execute surgically, then verify against a rubric.

Implication for Codex/GPT-5.4:
- Planner prompt should produce a compact but explicit execution contract.
- Implementation prompt should be short, task-scoped, and diff-minimizing.
- Verification prompts should use findings-first or pass/fail rubrics.

### Google / Gemini

Primary sources:
- Thinking guide: <https://ai.google.dev/gemini-api/docs/thinking>
- Prompt strategies: <https://ai.google.dev/gemini-api/docs/prompting-strategies>

Verified takeaways:
- Google recommends using thinking models with enough **thinking budget** for complex tasks.
- Better results come from **clear task instructions, examples, and explicit output schemas**.
- Gemini guidance leans toward strong structure: constraints first, examples when needed, exact output contract.

Implication for Gemini 3.1 Pro:
- Gemini responds well to explicit decomposition into constraints, schema, and deliverable.
- It benefits less from vague "be creative and think hard" language than from crisp task framing plus room for hidden reasoning.

## The Local Skill Corpus: What Is Actually Valuable

### 1. `ultrathink` is a router, not a prose prompt

Source:
- `/Users/alexburkhart/.codex/skills/ultrathink/SKILL.md`

The useful pattern:
- classify `task type`
- classify `complexity`
- classify `stakes`
- select one of `standard`, `deep`, `ensemble`, `megamind`

Why it matters:
- This is better than globally forcing max reasoning on every task.
- It turns reasoning depth into a routing decision instead of a vibe.

What to reuse:
- task classification block
- mode selection rules
- explicit mapping from task class to reasoning budget

What not to reuse literally:
- token count claims like `10K+` or `50K+` as guarantees
- old `codex-cool` examples as if they are universally current

### 2. `deepthink` is a scaffold library

Source:
- `/Users/alexburkhart/.codex/skills/deepthink/SKILL.md`

The useful pattern is the sequence, not the verbosity:
- meta-cognition
- step-back on what the user actually wants
- decomposition
- branch comparison / tree of thought
- first-principles check
- devil's advocate
- inversion / pre-mortem
- reflection and adaptation
- self-critique and improved draft

Why it matters:
- This is the strongest local example of an **external reasoning scaffold**.
- It forces deliberate work even when the underlying model does not naturally reason deeply.

What to reuse:
- decomposition block
- alternative-branch comparison
- pre-mortem
- self-critique + improved draft

What to compress:
- all 10 stages should not be pasted into every prompt verbatim
- use it as a menu of scaffolds, not a monolithic runtime payload

### 3. `megamind` is the right pattern for high-stakes planning only

Source:
- `/Users/alexburkhart/.codex/skills/megamind/SKILL.md`

The useful pattern:
- multiple independent angles
- separate synthesizers for consensus, conflict, and risk
- loop when confidence is too low

Why it matters:
- This is the best local pattern for architecture, risk, and ambiguous failure analysis.
- It is not just "more thinking"; it is **structured disagreement**.

What to reuse:
- angle families
- consensus / conflict / risk split
- explicit confidence threshold for looping

What to avoid:
- running 10-angle megamind on every ordinary coding task
- embedding the entire 10 -> 3 -> 1 protocol directly into short implementation prompts

### 4. `subprocess-reasoning` and `megamind-subprocess` solve a real systems problem

Sources:
- `/Users/alexburkhart/.codex/skills/subprocess-reasoning/SKILL.md`
- `/Users/alexburkhart/.codex/skills/megamind-subprocess/SKILL.md`

The useful pattern:
- keep heavyweight planner reasoning out of the main working context
- bring back only the synthesized plan, confidence, and major risks

Why it matters for Petamind:
- exactly matches the future `host_cli` planner lane
- avoids bloating the implementation agent's active context

What to reuse:
- planner subprocess contract
- return format with recommendation, confidence, and top risks

### 5. The orchestration skills contain the best operational prompt pattern

Sources:
- `/Users/alexburkhart/.codex/skills/cli-subagent-orchestrator-v3/SKILL.md`
- `/Users/alexburkhart/.codex/skills/agentic-rag-router/SKILL.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/prompts/SUBAGENT_CLAUDE_OPUS_ADDON.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/prompts/SUBAGENT_CODEX_BACKEND_ADDON.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/prompts/SUBAGENT_CODEX_SPARK_WORKER_ADDON.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/runbooks/ROUTING_POLICY.md`

The useful pattern:
- retrieve source-of-truth files first
- define DONE before acting
- assign strict ownership
- require proof artifacts
- route by lane, not by one monolithic prompt

Why it matters:
- These files already encode the difference between planner work, implementation work, research work, and verification work.
- That is the real prompt architecture Petamind should inherit.

## The Core Design Rule For Short-Reasoning Or Non-Reasoning Models

Do not try to brute-force hidden reasoning length.

Instead, externalize the reasoning into required work products.

### Good externalized artifacts
- task classification
- constraints table
- evidence ledger
- alternative strategies with pros/cons
- selected plan
- risk/pre-mortem table
- verification checklist
- schema-bound final answer

### Bad externalized artifacts
- "show all your chain-of-thought"
- raw hidden scratchpad dumping
- huge free-form narration with no output contract
- emotional or dramatic reasoning language that adds length without structure

## Best-Practice Prompt Tactics By Model Family

### A. Opus 4.6 / Claude-style short reasoning

Use when:
- long-context synthesis
- ambiguous repo investigations
- strategic planning
- evidence-heavy design language or architecture decisions

Best pattern:
1. Give the task, constraints, and output schema.
2. Ask for evidence-first reasoning.
3. If tools are involved, force `observation -> inference -> next action` updates.
4. Ask for a decision table and risk table before final recommendation.
5. Keep final output strict.

Recommended prompt skeleton:

```text
You are the planner/verifier.

Work evidence-first.
Do not guess past missing evidence.
If tools are used, alternate:
1. observation
2. inference
3. next action

Before final answer, produce:
- constraints
- evidence ledger
- 2-3 candidate strategies
- chosen strategy with why
- top 3 risks
- exact next actions

Output schema:
<schema here>
```

What not to do:
- do not demand giant narrated reasoning
- do not over-script hidden tags
- do not replace evidence with a clean executive story

### B. Codex / GPT-5.4 planner

Use when:
- codebase navigation
- implementation planning
- risky technical decisions
- diff-safe patch strategies

Best pattern:
1. classify complexity/stakes
2. produce a compact execution plan
3. call out repo evidence vs assumptions
4. list risks and tests
5. keep implementation prompt surgical

Recommended planner skeleton:

```text
Classify the task first:
- type
- complexity
- stakes

Then return:
- objective
- repo evidence
- assumptions
- minimal patch strategy
- verification plan
- top risks
```

Recommended implementation skeleton:

```text
Implement the approved plan.
Favor minimal diffs.
Do not widen scope.
Preserve output schema exactly.
Verify against these checks:
- <test/build/lint>
```

### C. Gemini 3.1 Pro

Use when:
- structured synthesis
- UI/system prompt planning
- schema-constrained multi-part outputs

Best pattern:
1. front-load constraints and schema
2. decompose into sections explicitly
3. use examples if exact format matters
4. avoid vague "think deeper" instructions

Recommended skeleton:

```text
Decompose this task into:
- constraints
- required evidence
- output contract
- failure conditions

Then solve.
Return only this schema:
<schema>
```

### D. Non-reasoning or weak-reasoning models

Use when:
- model has no explicit reasoning mode
- model tends to answer quickly and shallowly
- you need deliberate behavior from a cheaper/faster lane

Best pattern: multi-pass external scaffolding.

Pass 1: classify and decompose.
Pass 2: propose 2-3 options.
Pass 3: critique/pre-mortem.
Pass 4: final schema-bound answer.

If only one pass is possible, embed those sections visibly:

```text
Return exactly these sections:
1. Constraints
2. Evidence
3. Options
4. Chosen approach
5. Risks
6. Final answer
```

This works better than saying "think step by step" because it forces deliberative artifacts without needing hidden-reasoning support.

## The Right Petamind Prompt Architecture

Petamind should stop treating "reasoning prompt" as one giant prompt.
It should use a layered contract.

### Layer 1: Router Prompt
Purpose:
- decide reasoning depth and lane

Derived from:
- `ultrathink`
- `ROUTING_POLICY.md`

Outputs:
- task type
- complexity
- stakes
- recommended mode: `standard | deep | megamind | host_agent | host_cli`
- verification burden

### Layer 2: Planner Prompt
Purpose:
- create a visible plan artifact

Derived from:
- `deepthink`
- `megamind`
- Anthropic evidence-first guidance
- OpenAI rubric/checklist guidance

Outputs:
- goal
- evidence
- assumptions
- alternatives
- chosen plan
- risk table
- verification plan

### Layer 3: Implementation Prompt
Purpose:
- make the change with minimal drift

Derived from:
- current `reasoning_codex_impl.md`
- Codex surgical-edit guidance

Outputs:
- code change only
- exact final schema / patch / diff

### Layer 4: Verification Prompt
Purpose:
- evaluate pass/fail without aesthetic drift or fake certainty

Derived from:
- `cli-subagent-orchestrator-v3`
- `agentic-rag-router`
- findings-first code review patterns

Outputs:
- evidence table
- pass/fail per criterion
- remaining risks
- next action

## Elite Prompt Patterns To Add

### 1. Evidence Ledger Pattern

```text
Before deciding, list the evidence buckets:
- verified facts from files/tools
- inferred facts
- missing facts
Do not treat inferred facts as verified.
```

### 2. Option Table Pattern

```text
Generate 2-3 viable strategies.
For each: cost, upside, downside, failure mode.
Then pick one and justify the tradeoff.
```

### 3. Pre-Mortem Pattern

```text
Assume the chosen plan failed in production.
List the 3 most likely reasons.
Add one mitigation for each before finalizing.
```

### 4. Interleaved Tool Pattern

```text
When tools are used, loop in this order:
- observation
- inference
- next action
- updated plan if evidence changes
```

### 5. Assumption Firewall Pattern

```text
Every uncertain point must be labeled either:
- verified
- inferred
- unknown
If unknown, give the fastest verification step.
```

### 6. Schema Lock Pattern

```text
All reasoning happens in service of this exact output contract.
Do not add extra prose outside the schema.
```

## Anti-Patterns To Ban

1. `THINK HARDER` with no structure.
2. demanding giant exposed chain-of-thought dumps.
3. mixing planning, execution, verification, and aesthetics in one prompt.
4. asking a model to narrate internal reasoning in detail when you really need a plan artifact.
5. burying output schema under long motivational prose.
6. using the same heavy prompt for planner and implementer.
7. forcing megamind depth on ordinary implementation tasks.
8. letting short-reasoning models free-run without evidence buckets or critique phases.

## Concrete Recommendations For Petamind

### Immediate
1. Replace the current tiny `prompts/reasoning_*.md` files with fuller role-specific prompt packs.
2. Add a router prompt based on `ultrathink`.
3. Split planner vs implementer vs verifier prompts cleanly.
4. For Opus 4.6, use evidence-first + interleaved-tool prompts, not giant CoT demands.
5. For weak/non-reasoning models, add visible section scaffolds.

### Near-term
1. Add reusable prompt templates under `prompts/reasoning/` instead of five short single-file hints.
2. Add planner output schemas for:
   - architecture decisions
   - repo investigations
   - implementation plans
   - verification reports
3. Add a prompt selection layer tied to `solver_mode` and model capability.

### Capability mapping
- If the runtime exposes explicit effort knobs, maximize them within the actual surface.
- If the runtime does not expose effort knobs, increase structure, examples, and critique phases instead of pretending you can force hidden depth.

## Local CLI Reality That Matters

Verified on this machine:
- `claude --help` exposes `--effort low|medium|high`
- `codex exec` relies on model/config profiles; current local Codex routing already supports `gpt-5.4` and xhigh in config
- `gemini` headless mode exposes model and output controls, not an explicit reasoning-effort flag in the local CLI help
- `droid exec` exposes `--reasoning-effort`; local help reports `claude-opus-4-6` supports `[off, low, medium, high, max]`
- `opencode run` exposes `--variant` and `--thinking`

This means:
- the prompt system must distinguish between `effort knob available` and `no effort knob available`
- do not write one fake universal reasoning setting

## Draft Prompt Contracts For Future Wiring

### Router contract

```text
Classify the task by:
- type
- complexity
- stakes
- evidence burden

Return:
- recommended reasoning mode
- recommended model lane
- planner needed: yes/no
- verification burden
```

### Planner contract

```text
Work evidence-first.
Return exactly:
- objective
- verified evidence
- assumptions
- candidate strategies
- chosen strategy
- top risks
- verification plan
```

### Implementer contract

```text
Follow the approved plan.
Keep diffs minimal.
Preserve exact output schema.
Do not widen scope.
Return only the requested deliverable.
```

### Verifier contract

```text
Judge against explicit acceptance criteria.
Return:
- criterion
- pass/fail
- evidence
- remaining risk
- next action
```

## Strongest Synthesis

The elite move is not "max out CoT." The elite move is:
- use hidden reasoning where the model supports it
- use explicit effort knobs where available
- scaffold the work externally so even short-reasoning models behave deliberately
- separate planner, implementer, and verifier roles
- require evidence-backed intermediate artifacts

That is the clean merge between current official guidance and the best parts of the local skill corpus.

## Source File Inventory Used In This Memo

Local corpus:
- `/Users/alexburkhart/.codex/skills/megamind/SKILL.md`
- `/Users/alexburkhart/.codex/skills/megamind-subprocess/SKILL.md`
- `/Users/alexburkhart/.codex/skills/deepthink/SKILL.md`
- `/Users/alexburkhart/.codex/skills/ultrathink/SKILL.md`
- `/Users/alexburkhart/.codex/skills/subprocess-reasoning/SKILL.md`
- `/Users/alexburkhart/.codex/skills/cli-subagent-orchestrator-v3/SKILL.md`
- `/Users/alexburkhart/.codex/skills/agentic-rag-router/SKILL.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/prompts/SUBAGENT_CLAUDE_OPUS_ADDON.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/prompts/SUBAGENT_CODEX_BACKEND_ADDON.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/prompts/SUBAGENT_CODEX_SPARK_WORKER_ADDON.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/prompts/ORCHESTRATOR_CODEX_SYSTEM.md`
- `/Users/alexburkhart/.codex/orchestrator-pack-v3/runbooks/ROUTING_POLICY.md`
- `/Users/alexburkhart/Desktop/saved/frontend-design-loop-mcp/prompts/reasoning_*.md`
- `/Users/alexburkhart/Desktop/saved/Claudefoundthis.md`

Official web sources:
- Anthropic chain-of-thought tips
- Anthropic extended thinking
- Anthropic prompt engineering overview
- OpenAI GPT-5 prompting guide
- OpenAI prompt engineering guide
- Google Gemini thinking guide
- Google Gemini prompting strategies guide
