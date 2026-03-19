# Codex Test Prompt: Frontend Design Toolkit MCP

You have access to the `frontend-design-toolkit` MCP server.

This MCP is not an evaluator hiding another model behind the scenes. It gives you:
- playbooks that tell you exactly how to run the workflow
- mechanical helpers for preview, screenshots, gates, and context

You must do the actual planning, editing, reviewing, scoring, and iteration yourself.

## Your Task

Build a single-page website for a fictional watch restoration atelier called **"Horologica"**.

Requirements:
- premium dark theme
- modern typography
- glassmorphism elements
- responsive
- at least 6 sections:
  - hero
  - services
  - process timeline
  - before/after gallery
  - testimonials
  - contact / CTA

## Workflow

### Step 1: Read the playbooks

Call:
- `get_playbook("solve")`
- `get_playbook("megamind")`
- `get_playbook("vision_gate")`
- `get_playbook("creativity")`

Follow them literally.

### Step 2: Set up the project

Create a new directory at `/tmp/horologica-test/` with:
- `index.html`
- `styles.css`

Use plain HTML/CSS.

### Step 3: Build context and plan

Call:
- `build_context(repo_path="/tmp/horologica-test", auto_context_mode="goal", goal="Premium dark-themed watch restoration landing page with 6 sections")`

Then create:
- a bold plan
- a minimal plan
- a safe plan

Synthesize them into one plan yourself.

### Step 4: Build the site

Write the HTML and CSS yourself.

Rules:
- no lorem ipsum
- no placeholder-feeling copy
- no generic template feel
- make at least one memorable signature moment

### Step 5: Run gates and capture screenshots

Use the MCP tools:

```text
1. run_gates(repo_path="/tmp/horologica-test")
2. preview_start(command="python3 -m http.server $PORT", cwd="/tmp/horologica-test")
3. capture_screenshots(url=<preview_url>)
4. preview_stop(pid=<pid>)
```

### Step 6: Review and score the result yourself

Read the screenshots yourself and apply the rubric from `vision_gate`.

You must produce your own review object:

```json
{
  "score": 0.0,
  "pass": false,
  "broken": false,
  "issues": ["..."],
  "highlights": ["..."],
  "fix_suggestions": ["..."]
}
```

Threshold is `8.0 / 10`.

If your self-score is below `8.0`, you must fix the page and repeat the loop.

### Step 7: Review section creativity yourself

Use the rubric from `creativity` and produce your own section breakdown.

Identify:
- strong sections
- weak sections
- average section score
- weakest section score

If sections are weak, refine them and rerun the screenshot loop.

### Step 8: Report proof

Tell me:
- final self-assigned score
- creativity breakdown by section
- what you fixed during iteration
- final screenshot paths
- deterministic gate results

## Non-negotiables

- Do not ask the MCP to think for you
- Do not rely on hidden evaluation APIs
- Do the planning yourself
- Do the scoring yourself from the screenshots
- Actually iterate if the score is below threshold
