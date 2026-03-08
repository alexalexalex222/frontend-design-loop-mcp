# Frontend Design Loop MCP Security Audit - Deep Sweep

Date: 2026-03-07
Repo: /Users/alexburkhart/Desktop/saved/frontend-design-loop-mcp
Scope: source review, static analysis, targeted runtime probes, full test baseline
Reviewer: Codex
Supersedes: `security_best_practices_report.md` for current repo state
Note: this report now includes the later provider/release findings from the 9-lane parallel CLI audit.

## Executive Summary

The residual deep-sweep findings from earlier on 2026-03-07 are now closed in live code.
The later parallel-audit blockers are also now closed in live code.

Current verdict:
- Good: raw shell execution still requires explicit opt-in via `unsafe_shell_commands=true`
- Good: inline interpreter/code execution like `bash -c` and `python -c` is also blocked unless `unsafe_shell_commands=true`
- Good: preview mode is bound to the launched local preview origin and port by default
- Good: preview readiness rejects cross-origin redirects, and browser screenshots block cross-origin subresources by default
- Good: auto-context filtering now excludes the common secret stores found in the deep sweep probes
- Good: `.git/config` and other `.git/**` paths are excluded from prompt context
- Good: shared worktree reuse dirs are disabled by default; callers must opt in explicitly if they want the isolation tradeoff
- Good: cloud providers are no longer singleton-cached across config changes
- Good: MiniMax proxy-only vision lanes are explicitly downgraded to `vision_review_mode=\"proxy_structural\"` and no longer count as full automated visual passes
- Good: `kilo_cli` no longer forces `--auto` in the general patch-generation lane
- Good: release docs and CI now validate the real packaged install flow (`setup` then `setup --check`)
- Good: gate logs, preview output tails, and context blobs redact common secret shapes before persistence
- Residual posture: this is still a trusted-local stdio MCP, not a multi-tenant sandbox; the explicit unsafe flags intentionally widen the trust boundary when enabled

No remaining critical or high-severity findings were verified in this pass beyond the explicit unsafe opt-ins.

## Verification Baseline

Commands run:
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_mcp_code_server_eval_patch.py tests/test_mcp_code_server_auto_context.py tests/test_mcp_code_server_host_modes.py tests/test_mcp_code_server_end_to_end.py tests/test_mcp_code_server_apply_guard.py -q --import-mode=importlib`
- `PYTHONPATH=src .venv/bin/python -m pytest -q --import-mode=importlib`
- `PYTHONPATH=src .venv/bin/python scripts/preflight_check.py`
- `PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py`
- temporary scanner venv for `bandit -r src -f json -o out/security-bandit-deep.json`
- temporary scanner venv for `pip-audit --path .venv/lib/python3.14/site-packages --format json --output out/security-pip-audit-deep.json`
- targeted Python probes written to `out/security-probes.json`

Results:
- `54 passed in 2.15s`
- `120 passed in 14.64s`
- offline preflight: all checks passed
- stdio smoke: `OK: frontend_design_loop_eval`, run dir `out/mcp-eval-runs/eval_b0da1f9f7d`
- `bandit`: `15 LOW`, `0 MEDIUM`, `0 HIGH`
- `pip-audit`: `0 known vulnerabilities`

## Resolved Findings

### FDL-SEC-006 - VERIFIED FIXED - Preview mode now binds to the launched local preview instance

Status:
- VERIFIED FIXED in live code on 2026-03-07

What changed:
- preview validation now enforces the launched local host+port by default
- mismatched localhost ports are rejected unless `unsafe_external_preview=true`
- HTTP readiness no longer follows cross-origin redirects
- browser screenshot capture blocks cross-origin subresources by default and rejects navigation that leaves the preview origin

Evidence:
- preview validation helper: `src/frontend_design_loop_core/mcp_code_server.py`
- readiness probe helper: `src/frontend_design_loop_core/mcp_code_server.py`
- screenshot origin guard: `src/frontend_design_loop_core/mcp_code_server.py`
- regression tests: `tests/test_mcp_code_server_eval_patch.py`
- probe artifact: `out/security-probes.json`

Probe proof:
- `http://127.0.0.1:3000/` -> accepted
- `http://localhost:9999/admin` with expected port `3000` -> rejected
- same-origin request allowlist permits `http://127.0.0.1:3000/...` and blocks `http://127.0.0.1:4000/...` and `https://127.0.0.1:3000/...`

### FDL-SEC-007 - VERIFIED FIXED - Auto-context secret filter now covers the missed credential stores

Status:
- VERIFIED FIXED in live code on 2026-03-07

What changed:
- sensitive-path matching now covers `.docker/`, `.kube/`, token-named files, `.git-credentials`, and service-account-style JSON in addition to the earlier `.env*`, `.aws/`, `.ssh/`, and `.config/gcloud/` coverage
- context-blob assembly and auto-context discovery both use the expanded matcher

Evidence:
- sensitive matcher and context assembly: `src/frontend_design_loop_core/mcp_code_server.py`
- regression tests: `tests/test_mcp_code_server_auto_context.py`
- probe artifact: `out/security-probes.json`

Probe proof:
- `.docker/config.json` -> filtered
- `.kube/config` -> filtered
- `service-account.json` -> filtered
- `oauth_token.txt` -> filtered
- `context_blob_probe` now contains only `safe.txt`

### FDL-SEC-008 - VERIFIED FIXED - Shared worktree reuse is no longer enabled by default

Status:
- VERIFIED FIXED in live code on 2026-03-07

What changed:
- default `worktree_reuse_dirs` is now `[]` in both eval and solve paths
- reuse remains available as an explicit opt-in for callers who want the speed/isolation tradeoff

Evidence:
- solve default normalization: `src/frontend_design_loop_core/mcp_code_server.py`
- eval default normalization: `src/frontend_design_loop_core/mcp_code_server.py`
- regression test: `tests/test_mcp_code_server_eval_patch.py`
- probe artifact: `out/security-probes.json`

Probe proof:
- `default_reuse_dirs` now records `[]`

### FDL-SEC-009 - VERIFIED FIXED - `kilo_cli` no longer self-authorizes execution in the patch lane

Status:
- VERIFIED FIXED in live code on 2026-03-07

What changed:
- `kilo_cli` no longer appends `--auto` in its general command builder
- MiniMax proxy behavior remains scoped to vision proxy guidance, not direct worktree execution

Evidence:
- `src/frontend_design_loop_core/providers/kilo_cli.py`
- regression test: `tests/test_cli_providers.py`

### FDL-SEC-010 - VERIFIED FIXED - `.git/config` no longer enters prompt context

Status:
- VERIFIED FIXED in live code on 2026-03-07

What changed:
- `.git/**` is now treated as sensitive in path filtering
- planner-selected `files_to_read`, explicit `context_files`, and auto-context flows all pass through the same sensitive-path guard
- context blobs redact common secret shapes before persistence

Evidence:
- `src/frontend_design_loop_core/mcp_code_server.py`
- regression tests: `tests/test_mcp_code_server_auto_context.py`
- probe artifact: `out/security-probes.json`

### FDL-SEC-011 - VERIFIED FIXED - cloud provider cache drift is closed

Status:
- VERIFIED FIXED in live code on 2026-03-07

What changed:
- provider classes that bind live config/auth state now declare `cache_scope = "none"`
- `ProviderFactory.get()` returns fresh instances for non-cached providers

Evidence:
- `src/frontend_design_loop_core/providers/base.py`
- `src/frontend_design_loop_core/providers/openrouter.py`
- `src/frontend_design_loop_core/providers/vertex.py`
- `src/frontend_design_loop_core/providers/gemini.py`
- `src/frontend_design_loop_core/providers/anthropic_vertex.py`
- regression test: `tests/test_cli_providers.py`
- probe artifact: `out/security-probes.json`

### FDL-SEC-012 - VERIFIED FIXED - MiniMax proxy-only vision is no longer treated as full automated pass state

Status:
- VERIFIED FIXED in live code on 2026-03-07

What changed:
- proxy-only lanes now report `vision_review_mode="proxy_structural"`
- they do not set `vision_scored=true`
- eval mode reports `vision_pending=true`, `final_pass=null`
- solve mode no longer treats proxy-structural vision as `winner_passes_all=true`

Evidence:
- `src/frontend_design_loop_core/mcp_code_server.py`
- regression tests:
  - `tests/test_mcp_code_server_eval_patch.py`
  - `tests/test_mcp_code_server_host_modes.py`

### FDL-SEC-013 - VERIFIED FIXED - release/install contract is now validated honestly

Status:
- VERIFIED FIXED in live repo code/docs on 2026-03-07

What changed:
- CI now runs Python `3.10` through `3.14`
- release smoke builds the distribution, runs repo preflight/smoke, installs the wheel, runs `frontend-design-loop-setup`, then runs `frontend-design-loop-setup --check`
- `RELEASING.md` now matches the real package flow

Evidence:
- `.github/workflows/ci.yml`
- `RELEASING.md`

## Residual Notes

Remaining trust-boundary caveats are intentional and documented:
- `unsafe_shell_commands=true` re-enables shell syntax
- `unsafe_external_preview=true` re-enables external preview targets and relaxed preview fetch boundaries

This repo is hardened for its intended deployment shape:
- local stdio MCP
- trusted host agent
- local repo access

It is not designed as a remote multi-tenant sandbox.

Static/dependency scan artifacts:
- `out/security-bandit-deep.json`
- `out/security-pip-audit-deep.json`

## Current Recommended Position

The repo is in a strong security posture for the intended local-agent product model.

If you want further hardening beyond this point, the next work would be defense-in-depth rather than closing known active findings:
1. optional stricter provider-specific env allowlists per CLI lane
2. optional readonly/shared-cache strategy for caller-opted reuse dirs
3. optional artifact redaction pass for unusually sensitive repo content in logs and summaries
