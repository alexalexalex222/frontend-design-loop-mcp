# Contributing

## Product boundary

Frontend Design Loop MCP is the public MCP product surface.
Keep this repo focused on starting, fixing, improving, and verifying frontend work for coding agents.

## Default workflow

Prefer:
- `frontend_design_loop_eval`
- client-side vision by the host agent

Treat `frontend_design_loop_solve` as advanced/internal.

## Verification

Run before shipping changes:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q --import-mode=importlib
PYTHONPATH=src .venv/bin/python scripts/preflight_check.py
PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py
```

## Local install note

`./scripts/setup.sh` uses a non-editable install on purpose so the generated
console scripts work reliably on the current Python 3.14 toolchain. For source
tests and local iteration, keep using `PYTHONPATH=src` commands.
