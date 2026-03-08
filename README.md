# Frontend Design Loop MCP

Frontend Design Loop MCP is a design-first MCP for coding agents that need to start, fix, and materially improve websites.

It is built for Claude Code, Codex, Gemini CLI, Droid, OpenCode, and similar coding agents when the base model gets the page functional but not yet sharp.

Frontend Design Loop owns three jobs:
- start a stronger frontend from a weak or rough first pass
- fix broken or under-designed sections through screenshot-grounded refinement loops
- verify the result with deterministic proof and artifact capture

The primary workflow is `frontend_design_loop_design`.
The support workflow is `frontend_design_loop_eval`.

## How it works

`frontend_design_loop_design` is the active builder/fixer path.

Typical flow:
- the host agent points the MCP at a weak page, broken section, or rough patch
- by default it sticks to one main `provider` + `model`
- planning, generation, refinement, vision, and section-creativity inherit that same lane unless you explicitly override them
- it boots a local preview, captures screenshots, and iterates against the rendered result
- it returns the winning patch plus proof artifacts

If you explicitly want split lanes, that is opt-in:
- optional explicit split overrides only when you want different lanes

Use it when the base model got the page functional but not sharp, or when the site needs a real redesign pass instead of only validation.

`frontend_design_loop_eval` is the proof path.

Use it when you already have the patch and want:
- deterministic build/test/lint proof
- screenshot capture
- run artifacts the host agent can judge

## Design target

This is the level of refinement the design-first path is meant to push toward: not just "working", but materially better-looking in the screenshot that actually sells the page.

Real reference proof from the live GA SMB pipeline:

Before: the first ugly full-home ACA version.

![ACA full-page before](docs/images/aca-site50-v9-fullpage-before.png)

After: the rebuilt ACA version with the hero, mid-page systems/specimen/doctrine work, and the polished bottom close.

![ACA full-page after](docs/images/aca-site50-v22-fullpage-after.png)

Whole-page compare:

![ACA whole-page before vs after](docs/images/aca-site50-v9-v22-wholepage-compare.png)

The point is not generic polish. The point is screenshot-aware, layout-specific improvement that a host agent can actually use in a sales-facing workflow.

## Fastest path

### Local clone

```bash
./scripts/setup.sh
```

What that does:
- creates `.venv`
- installs the package
- installs Playwright Chromium
- installs detected MCP client entries automatically when supported clients are present
- runs the built-in doctor
- runs the stdio smoke test

If you want to skip all automatic client installs:

```bash
FDL_SKIP_CLIENT_INSTALL=1 ./scripts/setup.sh
```

### Packaged install

```bash
pipx install /path/to/frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

That is the intended one-command happy path for a packaged install.

Additional local client installs:

```bash
frontend-design-loop-setup --install-all-detected-clients
frontend-design-loop-setup --install-codex
frontend-design-loop-setup --install-gemini
frontend-design-loop-setup --install-droid
frontend-design-loop-setup --install-opencode
```

## Install details

### From a local clone

```bash
./scripts/setup.sh
```

### From a packaged install

```bash
pipx install /path/to/frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

## Claude Code config

Fastest manual option:

```bash
frontend-design-loop-setup --print-claude-config
```

Automatic install:

```bash
frontend-design-loop-setup --install-claude --scope user
```

Install all detected supported clients at once:

```bash
frontend-design-loop-setup --install-all-detected-clients
```

Raw `claude mcp add-json` example:

```bash
claude mcp add-json --scope user frontend-design-loop-mcp '{
  "command": "frontend-design-loop-mcp",
  "args": []
}'
```

For a local clone:

```bash
claude mcp add-json --scope user frontend-design-loop-mcp '{
  "command": "'"$(pwd)"'/.venv/bin/python",
  "args": ["-m", "frontend_design_loop_mcp.mcp_server"],
  "env": {
    "FRONTEND_DESIGN_LOOP_CONFIG_PATH": "'"$(pwd)"'/config/config.yaml"
  }
}'
```

## Codex config

Fastest manual option:

```bash
frontend-design-loop-setup --print-codex-config
```

Automatic install into `~/.codex/config.toml`:

```bash
frontend-design-loop-setup --install-codex
```

If you want to target a non-default config path:

```bash
frontend-design-loop-setup --install-codex --codex-config-path /path/to/config.toml
```

## Gemini config

Fastest manual option:

```bash
frontend-design-loop-setup --print-gemini-config
```

Automatic install into `~/.gemini/settings.json`:

```bash
frontend-design-loop-setup --install-gemini
```

If you want to target a non-default settings file:

```bash
frontend-design-loop-setup --install-gemini --gemini-settings-path /path/to/settings.json
```

## Droid config

Fastest manual option:

```bash
frontend-design-loop-setup --print-droid-config
```

Automatic install into `~/.factory/mcp.json`:

```bash
frontend-design-loop-setup --install-droid
```

If you want to target a non-default config path:

```bash
frontend-design-loop-setup --install-droid --droid-mcp-path /path/to/mcp.json
```

## OpenCode config

Fastest manual option:

```bash
frontend-design-loop-setup --print-opencode-config
```

Automatic install into `~/.config/opencode/opencode.json`:

```bash
frontend-design-loop-setup --install-opencode
```

If you want to target a non-default config path:

```bash
frontend-design-loop-setup --install-opencode --opencode-config-path /path/to/opencode.json
```

## Default usage

### Design-first workflow

Use `frontend_design_loop_design` when you want Frontend Design Loop to actively make the UI better.

Default design-pass behavior:
- stays on one main `provider` + `model` by default
- planning, generation, refinement, vision, and section-creativity inherit that same lane unless explicitly overridden
- requires preview screenshots so the MCP can see what it is changing
- forces vision and section-creativity passes instead of stopping at compile-safe output
- returns the winner patch plus full screenshot/run artifacts

This is the workflow that makes the MCP more than a verifier.

### Verification workflow

Use `frontend_design_loop_eval` when the host agent already has the patch or can generate it.

What it returns:
- deterministic pass/fail
- screenshot paths and inline image blocks
- preview artifacts
- run directory and candidate directory
- a stable JSON summary for the host agent to judge

Safety defaults on the interactive path:
- `test_command`, `lint_command`, and `preview_command` are parsed as shell-free argv by default
- shell operators and substitutions require `unsafe_shell_commands=true`
- direct interpreter escapes like `bash -c`, `sh -c`, `python -c`, and `node -e` also require `unsafe_shell_commands=true`
- `preview_url` must resolve to the exact launched local preview origin and port by default
- external preview fetches require `unsafe_external_preview=true`
- preview readiness checks reject cross-origin redirects, and browser screenshots block cross-origin subresources by default
- auto-context skips common secret-bearing files and directories by default, including `.env*`, `.git/`, `.aws/`, `.ssh/`, `.config/gcloud/`, `.docker/`, `.kube/`, token-named files, and service-account-style JSON
- native CLI providers inherit a minimal allowlisted environment instead of the full host env
- shared worktree reuse dirs are off by default; opt in only if you intentionally trade isolation for speed

Client-side vision is the default for `frontend_design_loop_eval`:
- no provider credentials required
- the host agent judges the screenshots
- Frontend Design Loop reports `vision_pending=true` until that judgment happens

`frontend_design_loop_design` is different on purpose:
- it uses native CLI model lanes so the MCP can actively improve the design
- it is the design enhancer path, not the proof-only path

Proxy-only automated vision lanes are explicitly downgraded:
- MiniMax proxy lanes (`kilo_cli`, `droid_cli`, `opencode_cli` on MiniMax) are treated as structural-only screenshot checks
- they report `vision_review_mode="proxy_structural"`
- they do not count as full automated visual scoring

## Optional advanced mode

`frontend_design_loop_solve` still exists for advanced unattended or host-cli workflows, but it is not the primary product path.

If you are using Frontend Design Loop interactively:
- prefer `frontend_design_loop_design` when you want the MCP to make the design better
- prefer `frontend_design_loop_eval` when you already have the patch and want proof

## Verification

Offline preflight:

```bash
PYTHONPATH=src .venv/bin/python scripts/preflight_check.py
```

stdio smoke:

```bash
PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py
```

Built-in doctor:

```bash
frontend-design-loop-setup --doctor
frontend-design-loop-setup --doctor --smoke
```

## Environment variables

Primary env vars:
- `FRONTEND_DESIGN_LOOP_CONFIG_PATH`
- `FRONTEND_DESIGN_LOOP_MCP_OUT_DIR`
- `FRONTEND_DESIGN_LOOP_MCP_PORT_START`

## Repo layout

- `src/frontend_design_loop_mcp/`: packaged CLI entrypoints, runtime paths, bundled assets
- `src/frontend_design_loop_core/`: MCP runtime, deterministic gates, screenshot/vision plumbing, provider adapters
- `config/config.yaml`: default local-clone config
- `prompts/`: reasoning overlays and prompt packs
- `templates/`: default Next.js template used by the runtime
- `tests/`: MCP-focused regression suite
