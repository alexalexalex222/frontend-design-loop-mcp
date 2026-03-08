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
./scripts/verify_release.sh
```

This script bootstraps `.venv` if needed, installs `.[dev]`, runs the repo checks,
builds `dist/`, verifies both wheel and sdist, and then runs an isolated `pipx
install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git`
smoke in a temp home/bin sandbox.

If you need the CI-safe variant that skips the live GitHub install check:

```bash
./scripts/verify_release.sh --skip-github-install
```

## Manual package smoke (if you need to inspect by hand)

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
2. run `./scripts/verify_release.sh`
3. confirm PyPI credentials are present locally:

```bash
test -n "${PYPI_TOKEN:-}"
```

4. publish with:

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" .venv/bin/python -m twine upload dist/frontend_design_loop_mcp-<version>-py3-none-any.whl dist/frontend_design_loop_mcp-<version>.tar.gz
```

5. verify the live install works:

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
frontend-design-loop-setup --doctor --smoke
```

6. update public docs so the GitHub install fallback becomes secondary instead of primary
7. refresh MCP directory submissions with the live PyPI command
8. only add official-registry `server.json` metadata after PyPI is live and the repo README has the required MCP name marker
