# Releasing Frontend Design Loop MCP

## Current public install path

PyPI is not published yet.
The real public install path today is:

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

Do not tell users to run `pipx install frontend-design-loop-mcp` until PyPI is live.

## Local release checklist

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q --import-mode=importlib
PYTHONPATH=src .venv/bin/python scripts/preflight_check.py
PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

## Package smoke

```bash
pipx install dist/*.whl
frontend-design-loop-mcp --help
frontend-design-loop-mcp --version
frontend-design-loop-setup
frontend-design-loop-setup --install-all-detected-clients
frontend-design-loop-setup --print-claude-config
frontend-design-loop-setup --print-codex-config
frontend-design-loop-setup --print-gemini-config
frontend-design-loop-setup --print-droid-config
frontend-design-loop-setup --print-opencode-config
frontend-design-loop-setup --doctor
frontend-design-loop-setup --check
```

## PyPI publish checklist

1. bump the version in `pyproject.toml`
2. rebuild the package
3. verify `dist/*` with `twine check`
4. upload to PyPI with `twine upload dist/*`
5. verify the live install works:

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
frontend-design-loop-setup --doctor --smoke
```

6. update public docs so the GitHub install fallback becomes secondary instead of primary
7. submit the live package/install path to MCP directories
