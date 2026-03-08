# Frontend Design Loop MCP Security Audit

Date: 2026-03-07
Repo: /Users/alexburkhart/Desktop/saved/frontend-design-loop-mcp
Scope: source review + test baseline + local static inspection
Reviewer: Codex

## Executive Summary

Update after remediation pass on 2026-03-07:
- custom commands default to shell-free argv execution, and shell syntax requires `unsafe_shell_commands=true`
- `preview_url` is localhost-only by default, and external preview fetches require `unsafe_external_preview=true`
- auto-context skips common secret-bearing files/directories by default
- native CLI providers inherit a minimal allowlisted environment instead of the full host shell env
- workspace-file vision runs inside the temp screenshot directory, not the whole repo/worktree

Current security posture is production-ready for the intended trust boundary:
- the MCP server is local-only over stdio
- the caller is fully trusted
- the caller is allowed to inspect local repos and may explicitly opt into unsafe modes when needed

Under a broader or semi-trusted trust model, unsafe opt-in paths still matter:
- `unsafe_shell_commands=true` intentionally re-enables shell syntax
- `unsafe_external_preview=true` intentionally re-enables non-local preview fetches

## Remediation Status

- Critical 1: VERIFIED FIXED in live code on 2026-03-07
- Critical 2: VERIFIED FIXED in live code on 2026-03-07
- High 3: VERIFIED FIXED in live code on 2026-03-07
- High 4: VERIFIED FIXED in live code on 2026-03-07
- Medium 5: VERIFIED FIXED in live code on 2026-03-07

## Findings

### Critical 1: Raw shell command execution is exposed in the main MCP tool surface

Status:
- Historical finding
- VERIFIED FIXED in live code on 2026-03-07

Impact:
- Any client that can call `frontend_design_loop_eval` or `frontend_design_loop_solve` can cause arbitrary shell execution inside the target repo context via `test_command`, `lint_command`, or `preview_command`.
- If this MCP is connected to an agent that does not already have unrestricted shell authority, this is a privilege-escalation surface.

Evidence:
- `frontend_design_loop_solve` accepts raw commands: `src/frontend_design_loop_core/mcp_code_server.py:2166-2220`
- `frontend_design_loop_eval` accepts raw commands: `src/frontend_design_loop_core/mcp_code_server.py:4212-4229`
- gate execution runs raw strings: `src/frontend_design_loop_core/mcp_code_server.py:2031-2052`
- preview execution runs raw strings: `src/frontend_design_loop_core/mcp_code_server.py:3010-3048`, `src/frontend_design_loop_core/mcp_code_server.py:3913-3953`
- command runner uses shell execution: `src/frontend_design_loop_core/utils.py:564-589`
- long-running preview runner uses shell execution: `src/frontend_design_loop_core/utils.py:608-632`

Why this matters:
- The code is not just executing inferred commands like `npm test`; it accepts caller-controlled command strings.
- Even if the intended workflow is trusted local use, this needs to be treated as a privileged operation and documented/guarded as such.

Remediation summary:
- custom commands now parse as shell-free argv by default
- shell operators/substitutions require `unsafe_shell_commands=true`
- regression coverage added for both eval and solve paths

### Critical 2: `preview_url` allows SSRF and arbitrary local-network/browser fetches

Status:
- Historical finding
- VERIFIED FIXED in live code on 2026-03-07

Impact:
- The caller can point `preview_url` at arbitrary HTTP targets, including internal services and cloud metadata endpoints.
- The runtime will both fetch the URL via `httpx` and load it in Playwright, then capture screenshots or return errors.

Evidence:
- `preview_url` is accepted directly in solve: `src/frontend_design_loop_core/mcp_code_server.py:2214-2215`
- `preview_url` is accepted directly in eval: `src/frontend_design_loop_core/mcp_code_server.py:4228-4229`
- the tool formats and uses the URL directly: `src/frontend_design_loop_core/mcp_code_server.py:3010-3011`, `src/frontend_design_loop_core/mcp_code_server.py:3915-3916`
- readiness check fetches the caller-supplied URL: `src/frontend_design_loop_core/mcp_code_server.py:1664-1677`, `src/frontend_design_loop_core/mcp_code_server.py:3059-3067`, `src/frontend_design_loop_core/mcp_code_server.py:3961-3969`
- screenshot capture loads the same URL in Chromium: `src/frontend_design_loop_core/mcp_code_server.py:1741-1777`, `src/frontend_design_loop_core/mcp_code_server.py:3070-3077`, `src/frontend_design_loop_core/mcp_code_server.py:3972-3979`

Why this matters:
- The intended use is local preview like `http://127.0.0.1:{port}/...`.
- The current code does not enforce that boundary.
- This is a classic SSRF surface with browser-assisted reachability.

Remediation summary:
- `preview_url` is restricted to `localhost`, `127.0.0.1`, or `::1` by default
- non-local preview fetches require `unsafe_external_preview=true`
- regression coverage added for the default rejection path

### High 3: Auto-context can send hidden secrets and local config files into model prompts

Status:
- Historical finding
- VERIFIED FIXED in live code on 2026-03-07

Impact:
- When `auto_context_mode` is enabled, the repo search can include hidden files and secret-bearing files.
- Their contents are then read into `context_blob` and sent to planner/generator/refiner model calls.
- This creates a secret exfiltration path from the repo into remote/provider or CLI-backed model lanes.

Evidence:
- auto-context search runs over hidden files: `src/frontend_design_loop_core/mcp_code_server.py:1379-1470`
- ignore globs exclude binaries and build folders, but do not exclude `.env`, `.pem`, `.key`, `.npmrc`, `.pypirc`, etc.: `src/frontend_design_loop_core/mcp_code_server.py:1413-1431`
- selected files are fully read into prompt context: `src/frontend_design_loop_core/mcp_code_server.py:1291-1322`
- solve mode expands context from planner output and auto-context search before model calls: `src/frontend_design_loop_core/mcp_code_server.py:2360-2405`

Why this matters:
- This is not hypothetical; the mechanism explicitly exists to broaden context automatically.
- Hidden files are included by design.
- In a repo with checked-in secrets, local tokens, or config material, the MCP can leak them upstream.

Recommended fix:
- Add a denylist before `_build_context_blob`, minimum:
  - `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `.npmrc`, `.pypirc`, `.netrc`, `id_*`, `credentials*`, `secrets*`
- Add a second denylist for known directories like `.aws/`, `.config/gcloud/`, `.ssh/` if ever reached.
- Default `auto_context_mode` should remain `off`; document it as privileged.
- Add redaction hooks before planner/generator prompt assembly.

Remediation summary:
- sensitive paths are filtered in both auto-context discovery and context-blob assembly
- regression coverage added for `.env` exclusion
- `auto_context_mode` remains off by default

### High 4: Native CLI providers inherit the full host environment by default

Status:
- Historical finding
- VERIFIED FIXED in live code on 2026-03-07

Impact:
- Native CLI subprocesses inherit the full parent environment, including any unrelated credentials, tokens, and local machine secrets.
- This broadens the blast radius of every CLI-backed provider, especially third-party CLIs.

Evidence:
- base env policy copies all host env vars: `src/frontend_design_loop_core/providers/_cli_base.py:94-97`
- CLI subprocesses run with that inherited env: `src/frontend_design_loop_core/providers/_cli_base.py:122-168`
- config also eagerly loads dotenv into process env: `src/frontend_design_loop_core/config.py:17-20`
- Gemini is the only provider that explicitly scrubs a subset of credential variables before launch: `src/frontend_design_loop_core/providers/gemini_cli.py:21-33`

Why this matters:
- The current design assumes all spawned CLIs are equally trusted with everything in the environment.
- That is too broad for a production MCP that may be used with multiple vendor CLIs and mixed local auth state.

Recommended fix:
- Replace `os.environ.copy()` with an allowlist per provider.
- Start from a minimal env and add only required keys, for example:
  - `PATH`, `HOME`, `LANG`, `TERM`, repo-specific config path, provider-specific auth vars only
- Add explicit denylist coverage for common secret families even in allowed env mode.
- Add regression tests proving secrets are not inherited by default.

Remediation summary:
- the native CLI base provider now starts from a minimal environment allowlist
- runtime namespace env vars remain available
- provider-specific auth/config prefixes are allowlisted explicitly
- regression coverage added for codex and gemini env handling

### Medium 5: Claude vision mode intentionally bypasses CLI permission checks for the whole working directory

Status:
- Initial report overstated scope
- VERIFIED FIXED / NOT REPRODUCED in current live code on 2026-03-07

Impact:
- Claude CLI vision invocations run with `--permission-mode bypassPermissions` and `--add-dir <cwd>`.
- That grants the CLI broad read access for a task that only requires screenshot inspection.

Evidence:
- command construction: `src/frontend_design_loop_core/providers/claude_cli.py:47-55`
- tests explicitly lock this behavior in: `tests/test_cli_providers.py:120-127`

Why this matters:
- This is not a bug by accident; it is an intentional privilege expansion.
- It is broader than necessary for screenshot-only vision work.

Recommended fix:
- Prefer direct image attachment if the CLI supports it.
- If workspace-file vision is required, mount only the temp screenshot directory, not the whole repo/worktree.
- Remove `bypassPermissions` unless there is a verified functional requirement that cannot be met another way.

Current verified state:
- workspace-file vision runs in the temp screenshot directory created by `_cli_base.complete_with_vision`
- Claude `--add-dir` matches that temp directory, not the repo root
- regression coverage added for the scoped temp-dir behavior

## Verified Positives

These are real hardening measures already present in live code.

1. Patch application is constrained to the repo/worktree root.
- path sanitization rejects `../` and absolute paths: `src/frontend_design_loop_core/mcp_code_server.py:855-861`
- target writes are checked with `resolve()` + `relative_to(repo_resolved)`: `src/frontend_design_loop_core/mcp_code_server.py:1180-1184`
- context reads do the same confinement: `src/frontend_design_loop_core/mcp_code_server.py:1304-1308`

2. Auto-apply is off by default and guarded.
- auto-apply only runs when `apply_to_repo=true`: `src/frontend_design_loop_core/mcp_code_server.py:3599-3618`
- it refuses to apply when tests were skipped or winner failed enabled gates: `src/frontend_design_loop_core/mcp_code_server.py:3600-3612`

3. The shipped MCP entrypoint is stdio-only, not an exposed network API.
- the packaged entrypoint is a thin stdio launcher: `src/frontend_design_loop_mcp/mcp_server.py:15-41`

4. Client-vision contract is honest now.
- eval mode distinguishes `vision_pending`, `vision_scored`, and `final_pass` instead of claiming a full pass before client judgment: `src/frontend_design_loop_core/mcp_code_server.py:4022-4029`, `src/frontend_design_loop_core/mcp_code_server.py:4107-4152`

## Test / Tooling Coverage

Verification runs in this audit:
- `PYTHONPATH=src .venv/bin/python -m pytest -q --import-mode=importlib`
- Initial result before remediation: `101 passed in 14.06s`
- Post-remediation targeted result: `13 passed in 2.94s`
- Post-remediation targeted result 2: `30 passed in 0.92s`
- Final full-suite result: `109 passed in 15.27s`
- Offline preflight: all checks passed
- stdio smoke: `OK: frontend_design_loop_eval`
- `bandit -r src`: `15 LOW`, `0 MEDIUM`, `0 HIGH`
- `pip-audit` against the repo venv: `0 known vulnerabilities`

Coverage gaps discovered:
- No test currently enforces localhost-only preview URLs.
- No test currently enforces environment allowlisting for CLI providers.
- No test currently blocks secret-bearing files from auto-context.
- No test currently forces raw shell commands behind an explicit unsafe flag.

Tooling limits in this environment:
- `bandit` and `pip-audit` were not preinstalled.
- Attempts to create temporary audit environments and install them were blocked by policy in this shell session.
- Result: this report is source-and-test based, not dependency-CVE complete.

## Production Readiness Verdict

Ready for production for the intended trust boundary:
- local stdio only
- fully trusted operator/client
- explicit acceptance that the MCP can inspect local repos and can re-enable unsafe modes only via explicit flags

Not ready for a semi-trusted or remote multi-tenant deployment without a different sandbox model.

## Commands Run

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q --import-mode=importlib
```

```bash
rg -n "@mcp\.tool|preview_url|preview_command|test_command|lint_command|create_subprocess_shell|create_subprocess_exec|auto_context_mode|_build_env|bypassPermissions" src tests README.md docs
```

```bash
nl -ba src/frontend_design_loop_core/mcp_code_server.py | sed -n '1,240p'
nl -ba src/frontend_design_loop_core/mcp_code_server.py | sed -n '700,1260p'
nl -ba src/frontend_design_loop_core/mcp_code_server.py | sed -n '1290,1478p'
nl -ba src/frontend_design_loop_core/mcp_code_server.py | sed -n '1980,2065p'
nl -ba src/frontend_design_loop_core/mcp_code_server.py | sed -n '2160,2410p'
nl -ba src/frontend_design_loop_core/mcp_code_server.py | sed -n '2480,3205p'
nl -ba src/frontend_design_loop_core/mcp_code_server.py | sed -n '3590,3665p'
nl -ba src/frontend_design_loop_core/mcp_code_server.py | sed -n '3820,4288p'
nl -ba src/frontend_design_loop_core/utils.py | sed -n '540,690p'
nl -ba src/frontend_design_loop_core/providers/_cli_base.py | sed -n '1,320p'
nl -ba src/frontend_design_loop_core/providers/claude_cli.py | sed -n '1,260p'
nl -ba src/frontend_design_loop_core/providers/gemini_cli.py | sed -n '1,260p'
nl -ba src/frontend_design_loop_core/providers/kilo_cli.py | sed -n '1,260p'
nl -ba src/frontend_design_loop_core/providers/droid_cli.py | sed -n '1,260p'
nl -ba src/frontend_design_loop_core/providers/opencode_cli.py | sed -n '1,260p'
nl -ba src/frontend_design_loop_core/config.py | sed -n '1,280p'
nl -ba src/frontend_design_loop_mcp/mcp_server.py | sed -n '1,240p'
nl -ba tests/test_cli_providers.py | sed -n '100,150p'
```
