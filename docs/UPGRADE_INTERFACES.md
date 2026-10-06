# Setup/toolkit integration notes (2026-10-05)

This file coordinates the disjoint local upgrade; it does not grant new authority.

Native-runtime owner: setup moved Google authentication and retry dependencies
into `[cloud]` (unused storage/aiohttp/aiosqlite removed). Please make `providers` registration lazy so native
entrypoints import without Google packages or tenacity. Preserve exported provider
classes and give a missing-extra error at cloud provider selection.

Toolkit now delegates commands to `run_command_argv` / `run_command` and previews
to `managed_process_argv(args, cwd, env)`. Toolkit owns bounded continuous drain
tasks and invokes the shared context cleanup, which terminates owned process trees.
Keep these APIs compatible; native runtime must handle timeout/cancellation cleanup.

Lead: `--workflow toolkit` is the setup default; `--workflow automated` selects the
existing loop. Toolkit screenshots return MCP image content and a versioned JSON
manifest. Toolkit owns its preview handles; unknown PIDs are rejected. Judge tool
is deferred unless shared restricted native-auth execution can be reused without
core edits; hosts can independently review images using their own authorized tools.

Package version stays 1.0.0 in this worker to avoid diverging from the version file
outside ownership; lead may update all version metadata together to 1.1.0.

## Verification handoff

- Focused setup/toolkit tests: 39 passed, 2 skipped (sandbox denies loopback binds).
- Toolkit stdio contract and installed-wheel smoke passed without model inference.
- Wheel built with system Python/setuptools; final temporary wheel installation at
  `/private/tmp/frontend-toolkit-final-install`; final wheel/build log are at
  `/private/tmp/frontend-toolkit-final-wheel` and `/private/tmp/frontend-toolkit-final-build.log`.
- Both installed console entrypoint `--version` checks passed at 1.0.0.
- Native-only import probe with Google/tenacity deliberately unavailable: toolkit
  passed; automated core failed on `google.auth` from eager provider imports.
  **Integration blocker:** lazy provider registration is required before declaring
  the new base installation ready for automated/native server startup.
- Lead still needs real preview/render/mobile/interaction checks, both final installed
  stdio entrypoints, and hosted Windows runs. This worker cannot bind local sockets.
- `scripts/smoke_toolkit_stdio.py` delegates to packaged `design_toolkit.smoke`;
  smoke works outside checkout. Browser tests are in test_design_toolkit_behavior.py.

Final toolkit checks also passed: Ruff on owned Python, scoped git diff whitespace
validation, installed-wheel packaged smoke, both console --version outputs.
MCP image serialization regression proves labeled PNG bytes reach host content;
this is serialization evidence, not a claim of real rendering in this sandbox.
No model worker, auth/login command, account mutation, commit, push, or publication
was run. Native judge remains a host-authorized optional review flow, not a new tool.

Final integration supersedes the deferred-review notes: review_design now reuses the restricted native adapters. Cloud imports are lazy, all version metadata is 1.1.0, and the lead verified real renders/native execution. Detailed local receipts are in the upgrade artifact directory; this is still unpublished.
