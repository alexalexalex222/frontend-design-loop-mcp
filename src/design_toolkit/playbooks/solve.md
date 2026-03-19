# Solve Playbook - Agent-Owned Frontend Workflow

This MCP does not evaluate or patch code for you. It gives you playbooks plus a few mechanical helpers.

You own:
- planning
- subagent delegation
- code edits
- screenshot review
- scoring
- iteration
- winner selection

Use the MCP only for context packing, gates, previews, and screenshots.

---

## Step 0: Build Context

Before editing, understand the repo.

```text
Call: build_context(repo_path, auto_context_mode="goal", goal=<the_goal>)
```

Read the returned `context_blob` and identify:
- framework/runtime
- relevant files
- test/lint commands
- risks and constraints

Do not treat `build_context` as truth. It is only a fast bundle for your own reasoning.

---

## Step 1: Plan

Read `megamind.md` and create:
- a bold plan
- a minimal plan
- a safe plan

Then synthesize them yourself into one execution plan.

If the task is trivial, skip the full Megamind loop and plan directly.

---

## Step 2: Generate Candidates

Read `candidates.md`.

Generate 1-4 candidate implementations depending on task complexity. Each candidate should be created by you or your subagents, not by the MCP.

Each candidate should record:
- intent
- files touched
- risk level
- what makes it different

---

## Step 3: Edit Code

Apply the candidate changes using your native editing flow.

The MCP does not apply patches for you. Own the code changes directly.

For each candidate:
1. edit the code
2. keep the diff scoped
3. record what changed

---

## Step 4: Run Deterministic Gates

Use the MCP for mechanical validation:

```text
Call: run_gates(repo_path, test_command=?, lint_command=?)
```

If gates fail:
1. read the output
2. fix the issue yourself
3. rerun gates

Do not move to visual review until the page renders and deterministic checks are clean enough for preview.

---

## Step 5: Capture Review Surfaces

Use the MCP for preview lifecycle and screenshot capture:

```text
1. Call: preview_start(command, cwd)
2. Call: capture_screenshots(url)
3. Call: preview_stop(pid)
```

The screenshots are for you to inspect directly with your native image/vision capability.

---

## Step 6: Score the Result Yourself

Read `vision_gate.md` and score the screenshots yourself.

Produce a review object like:

```json
{
  "score": 0.0,
  "pass": false,
  "issues": ["..."],
  "highlights": ["..."],
  "fix_suggestions": ["..."]
}
```

If the page is good but generic, cap it accordingly. If it is broken, fix structural issues first.

---

## Step 7: Refine Creativity

Read `creativity.md`.

After the page is structurally solid, score section creativity yourself from the screenshots and improve only the weakest sections.

---

## Step 8: Pick the Winner

Read `winner_selection.md`.

Use your own review notes plus deterministic gate results to pick the best candidate.

---

## Step 9: Deliver Proof

Your final output should include:
- chosen candidate
- gate results
- your self-assigned review score
- section creativity breakdown
- screenshot paths
- what changed during iteration
