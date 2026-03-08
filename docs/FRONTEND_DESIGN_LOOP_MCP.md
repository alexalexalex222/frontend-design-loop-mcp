# Frontend Design Loop MCP

## Recommended contract

Use `frontend_design_loop_design` when you want the MCP to actively improve the UI.
Use `frontend_design_loop_eval` when you already have the patch and want proof.

Interactive split:
- `frontend_design_loop_design`: design-enhancement workflow
- `frontend_design_loop_eval`: verification workflow

Frontend Design Loop returns:
- `deterministic_passed`
- `vision_pending`
- `vision_scored`
- `final_pass`
- `run_dir`
- `candidate_dir`
- `screenshot_files`
- `patch`

`passes_all_gates` is only true when automated vision actually ran and passed.

## Tool: `frontend_design_loop_design`

High-level signature:

`frontend_design_loop_design(repo_path, goal, preview_command=..., preview_url=..., ...)`

What it is for:
- push a page beyond “works” into “looks deliberate”
- run screenshot-grounded design passes without making you hand-wire all the creative defaults every time
- start from a rough page, weak section, or base-model first pass and move it into a stronger visual class

Default behavior:
- `solver_mode="host_cli"`
- one main `provider` + `model` lane by default
- planner, design generation, vision, and section-creativity inherit that same lane unless explicitly overridden
- `planning_mode="single"`
- `vision_mode="on"`
- `section_creativity_mode="on"`

Key inputs:
- `repo_path`
- `goal`
- `preview_command`
- `preview_url`
- main `provider` + `model`
- optional explicit split overrides for `planner_provider` / `planner_model`
- optional explicit split overrides for `vision_provider` / `vision_model`
- optional `section_creativity_model`

Behavior:
- generate multiple design candidates
- run deterministic gates
- capture screenshots
- run automated design review and section-creativity refinement
- return the winner patch plus run artifacts

Use this when the base model got the page functional but still generic, flat, or weak.

## Tool: `frontend_design_loop_eval`

High-level signature:

`frontend_design_loop_eval(repo_path, patches, ...)`

Key inputs:
- `repo_path`
- `patches`
- `goal` optional
- `test_command` optional
- `lint_command` optional
- `vision_mode=auto|on`
- `vision_provider=client` by default
- `preview_command` and `preview_url` when you want UI screenshots instead of diff screenshots
- `unsafe_shell_commands=false` by default
- `unsafe_external_preview=false` by default

Behavior:
- apply patch bundle in an isolated worktree
- run deterministic gates
- capture screenshots
- either:
  - return screenshots for host judgment, or
  - run automated vision through a configured provider
- write stable artifacts under the run directory

Safety defaults:
- custom commands are executed as shell-free argv by default
- shell operators, substitutions, direct shell syntax, and inline interpreter/code execution like `bash -c`, `python -c`, and `node -e` require `unsafe_shell_commands=true`
- `preview_url` must match the launched local preview origin and port unless `unsafe_external_preview=true`
- preview readiness checks reject cross-origin redirects, and browser screenshots block cross-origin subresources by default
- auto-context skips common secret-bearing paths by default, including `.git/`, `.docker/`, `.kube/`, token-named files, and service-account-style JSON
- native CLI providers inherit a minimal allowlisted environment, not the full host shell env
- shared worktree reuse dirs are disabled by default; opt in explicitly if you want to reuse `node_modules` or other heavy dirs

## Vision modes

### Default: `vision_provider=client`

This is the best proof path when the host agent already owns the patch.

It requires no provider credentials.
The MCP captures screenshots and returns them to the host agent.
The host agent decides whether the page is acceptable.

In this mode:
- `vision_scored=false`
- `vision_pending=true` when deterministic gates passed
- `final_pass=null`
- `passes_all_gates=false`

### Automated vision

Optional providers can score screenshots inside Frontend Design Loop itself.
This is useful for unattended or batch workflows, not as the default interactive path.

### Proxy-structural vision lanes

MiniMax-based proxy lanes (`kilo_cli`, `droid_cli`, `opencode_cli` on MiniMax) are not treated as full automated visual scoring.

In these lanes:
- `vision_review_mode="proxy_structural"`
- `vision_scored=false`
- `vision_pending=true` when deterministic gates passed
- `final_pass=null`
- `vision_ok` reflects only structural render health from the proxy evidence

## Optional advanced tool: `frontend_design_loop_solve`

`frontend_design_loop_solve` remains available for advanced unattended workflows.
It is not the main product story.

If you are in Claude Code, Codex, Gemini CLI, Droid, or OpenCode interactively:
- use `frontend_design_loop_design` first when you want the MCP to improve the design
- use `frontend_design_loop_eval` when you already have the patch and want proof only

## Install

### Public install right now

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

### Local clone

```bash
./scripts/setup.sh
```

This is the easiest repo-checkout path. It:
- creates `.venv`
- installs the package
- installs Playwright Chromium
- installs detected MCP client entries automatically when supported clients are available
- runs the built-in doctor
- runs the stdio smoke test

### Future PyPI install

PyPI is not live yet. When it is published, the public install should become:

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

## MCP config

Packaged install example:

```json
{
  "mcpServers": {
    "frontend-design-loop-mcp": {
      "command": "frontend-design-loop-mcp",
      "args": []
    }
  }
}
```

Local clone example:

```json
{
  "mcpServers": {
    "frontend-design-loop-mcp": {
      "command": "<REPO>/.venv/bin/python",
      "args": ["-m", "frontend_design_loop_mcp.mcp_server"],
      "env": {
        "FRONTEND_DESIGN_LOOP_CONFIG_PATH": "<REPO>/config/config.yaml"
      }
    }
  }
}
```

## Setup helpers

```bash
frontend-design-loop-setup --install-all-detected-clients
frontend-design-loop-setup --print-claude-config
frontend-design-loop-setup --print-codex-config
frontend-design-loop-setup --print-gemini-config
frontend-design-loop-setup --print-droid-config
frontend-design-loop-setup --print-opencode-config
frontend-design-loop-setup --install-claude --scope user
frontend-design-loop-setup --install-codex
frontend-design-loop-setup --install-gemini
frontend-design-loop-setup --install-droid
frontend-design-loop-setup --install-opencode
frontend-design-loop-setup --doctor
frontend-design-loop-setup --doctor --smoke
```

## Verification commands

```bash
PYTHONPATH=src .venv/bin/python scripts/preflight_check.py
PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py
```
