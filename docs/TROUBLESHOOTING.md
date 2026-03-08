# Troubleshooting

## `frontend-design-loop-setup --check` fails

Run:

```bash
frontend-design-loop-setup
```

That installs Playwright Chromium for the current environment.

If you want the full environment summary:

```bash
frontend-design-loop-setup --doctor
```

## MCP server starts but tool calls fail to import local files

For a local clone, make sure the MCP config points at:
- `-m frontend_design_loop_mcp.mcp_server`
- `FRONTEND_DESIGN_LOOP_CONFIG_PATH=<repo>/config/config.yaml`

Legacy migration env vars still work:

If you want the tool to emit the exact config for your client instead of editing by hand:

```bash
frontend-design-loop-setup --install-all-detected-clients
frontend-design-loop-setup --print-claude-config
frontend-design-loop-setup --print-codex-config
frontend-design-loop-setup --print-gemini-config
frontend-design-loop-setup --print-droid-config
frontend-design-loop-setup --print-opencode-config
```

## I want repo-local artifacts, not user app-data artifacts

For a local clone, Frontend Design Loop uses repo `out/` automatically when it detects:
- `config/config.yaml`
- `templates/nextjs_app_router_tailwind`
- `prompts/`

You can also force the path:

```bash
export FRONTEND_DESIGN_LOOP_MCP_OUT_DIR="$HOME/frontend-design-loop-mcp-runs"
```

## I only want host-agent mode

Use:
- `frontend_design_loop_eval`
- `vision_provider=client`

That path requires no cloud/provider credentials.

## My custom command or preview URL is rejected

This is the secure default.

- `test_command`, `lint_command`, and `preview_command` run as shell-free argv by default
- shell operators like `>`, `|`, `&&`, `;`, backticks, and `$()` require `unsafe_shell_commands=true`
- inline interpreter/code execution like `bash -c`, `sh -c`, `python -c`, and `node -e` also require `unsafe_shell_commands=true`
- `preview_url` must target `localhost`, `127.0.0.1`, or `::1` unless `unsafe_external_preview=true`
- auto-context will ignore common secret-bearing paths like `.env*`, `.git/`, `.ssh/`, `.aws/`, `.config/gcloud/`, `.docker/`, and `.kube/`
- native CLI providers inherit a minimal allowlisted env; if a CLI truly needs extra auth/config vars, pass them explicitly instead of relying on ambient shell state

If you intentionally need shell syntax or a non-local preview target, opt in explicitly in the MCP call instead of relying on implicit shell behavior.

## My automated vision lane says `proxy_structural`

That is expected for MiniMax proxy-only lanes such as:
- `kilo_cli`
- `droid_cli` on MiniMax
- `opencode_cli` on MiniMax

Those lanes are treated as structural render-health checks only. They do not count as full automated visual scoring, so:
- `vision_scored=false`
- `vision_pending=true`
- `final_pass=null`

If you want the host agent to judge screenshots, use `vision_provider=client`.

## I need a quick proof that the repo works

```bash
PYTHONPATH=src .venv/bin/python scripts/preflight_check.py
PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py
```

Or use the built-in doctor from the repo checkout:

```bash
.venv/bin/frontend-design-loop-setup --doctor --smoke
```
