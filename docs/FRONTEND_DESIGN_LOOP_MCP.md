# Frontend Design Loop MCP

Frontend Design Loop is an MCP for coding agents that already got a page functional and now need to make it materially better with screenshot-grounded iteration and proof artifacts.

## Product Contract

- `frontend_design_loop_design` is the primary workflow
- `frontend_design_loop_eval` is the proof workflow for host-authored patches
- `frontend_design_loop_design` stays on one main `provider` + `model` lane by default
- planner, design generation, vision, and section-creativity inherit that same lane unless the caller explicitly overrides them
- split-lane routing is opt-in only
- `frontend_design_loop_solve` remains available for advanced unattended workflows, but it is not the default public story

## Real Call Example

```text
frontend_design_loop_design(
  repo_path="/absolute/path/to/site",
  goal="make the homepage look materially more premium without changing the information architecture",
  provider="gemini_cli",
  model="gemini-3.1-pro-preview",
  preview_command="python3 -m http.server {port}",
  preview_url="http://127.0.0.1:{port}/index.html"
)
```

## `frontend_design_loop_design`

Use this when the host agent wants the MCP to improve the page, not just judge it.

Typical use cases:
- the page works but still looks generic
- a section is structurally correct but visually weak
- a rough first pass needs a real design loop against screenshots

Required inputs:
- `repo_path`
- `goal`
- `preview_command`
- `preview_url`
- main `provider` + `model`

Default behavior:
- `solver_mode="host_cli"`
- `planning_mode="single"`
- `vision_mode="on"`
- `section_creativity_mode="on"`
- one main `provider` + `model` lane by default

What it returns:
- the winning patch
- screenshot artifacts
- run directories and machine-readable proof output

## `frontend_design_loop_eval`

Use this when the host agent already has the patch and wants proof.

Typical use cases:
- verify a host-authored patch in an isolated worktree
- capture screenshots for host review
- run deterministic checks before deciding whether the patch is acceptable

Key inputs:
- `repo_path`
- `patches`
- optional `goal`
- optional `test_command`
- optional `lint_command`
- optional `preview_command` and `preview_url`
- `vision_provider=client` by default
- `unsafe_shell_commands=false` by default
- `unsafe_external_preview=false` by default

Returned fields include:
- `deterministic_passed`
- `vision_pending`
- `vision_scored`
- `final_pass`
- `run_dir`
- `candidate_dir`
- `screenshot_files`
- `patch`

## How The MCP Works In Practice

1. The host agent points the MCP at a real repo and a concrete page goal.
2. The MCP boots a local preview and captures screenshots.
3. The main model lane iterates against the rendered result by default.
4. Deterministic gates catch structural regressions.
5. The MCP returns the winning patch plus proof artifacts the host agent can inspect.

That is the public wedge:
- coding agents can already make pages work
- Frontend Design Loop makes them materially better
- screenshot-grounded iteration plus proof artifacts is what changes the result

## Vision Modes

### Default: `vision_provider=client`

This is the recommended interactive proof path.

- no provider credentials required
- the MCP captures screenshots and returns them to the host agent
- the host agent decides whether the page is acceptable

In this mode:
- `vision_scored=false`
- `vision_pending=true` when deterministic gates passed
- `final_pass=null`

### Automated vision

Automated vision is available for unattended or batch workflows, but it is not the default public story.

### Proxy-structural vision lanes

MiniMax-based proxy lanes such as `kilo_cli`, `droid_cli`, and `opencode_cli` on MiniMax are treated as structural-only screenshot review.

In these lanes:
- `vision_review_mode="proxy_structural"`
- `vision_scored=false`
- `vision_pending=true` when deterministic gates passed
- they do not count as full automated visual scoring

## Safety Defaults

- custom commands run as shell-free argv by default
- shell syntax and inline interpreter execution like `bash -c`, `python -c`, and `node -e` require `unsafe_shell_commands=true`
- `preview_url` must match the launched local preview origin and port unless `unsafe_external_preview=true`
- preview readiness checks reject cross-origin redirects
- browser screenshots block cross-origin subresources by default
- auto-context skips common secret-bearing paths including `.git/`, `.docker/`, `.kube/`, token-named files, and service-account-style JSON
- native CLI providers inherit a minimal allowlisted environment
- shared worktree reuse directories are disabled by default

## Install

### Public install now

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

GitHub install remains the fallback:

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

### Local clone

```bash
./scripts/setup.sh
```

The repo-local setup path creates `.venv`, installs the package, installs Playwright Chromium, installs detected client entries when supported clients are present, and runs doctor plus stdio smoke.

### GitHub fallback install

Use this only if you want the live repo head instead of the latest PyPI release:

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

## MCP Config

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

## Setup Helpers

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

## Verification

```bash
PYTHONPATH=src .venv/bin/python scripts/preflight_check.py
PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py
```
