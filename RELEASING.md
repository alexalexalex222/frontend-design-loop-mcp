# Releasing Frontend Design Loop MCP

## Current public install path

PyPI is live. The real public install path today is:

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

GitHub install remains the fallback when you want the repo head instead of the latest published release:

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

## Local release checklist

```bash
./scripts/verify_release.sh
```

This script bootstraps `.venv` if needed, installs `.[dev]`, runs the repo checks,
builds `dist/`, verifies both wheel and sdist, and then runs isolated PyPI and
GitHub-install smokes in a temp home/bin sandbox.

If you need the CI-safe variant that skips the live GitHub install check:

```bash
./scripts/verify_release.sh --skip-github-install
```

Registry metadata consistency is now part of the local release path via:

```bash
python3 scripts/check_registry_ready.py
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

## Recommended publish path: GitHub release workflow with PyPI token

- GitHub workflow: `.github/workflows/release.yml`
- GitHub environment: `pypi`
- publish action: `pypa/gh-action-pypi-publish@release/v1`
- repo secret used by the workflow: `PYPI_TOKEN`

Current release flow:

1. bump the version in `pyproject.toml`
2. push the version bump
3. create a GitHub release on the target tag, or trigger `release.yml` manually
4. let the `build-distributions` job run full verification
5. let the `publish-pypi` job publish with the repo `PYPI_TOKEN` secret
6. verify the live install works:

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
frontend-design-loop-setup --doctor --smoke
```

7. update public docs if the new version changed the install or setup story
8. refresh MCP directory submissions with the live PyPI command
9. verify the registry metadata against the live package:

```bash
python3 scripts/check_registry_ready.py --check-pypi
```

10. publish the official MCP Registry entry from the tracked metadata:

```bash
mcp-publisher publish server.json
```

11. once the official registry entry is live, refresh any stale third-party directory listings only if they still point at the wrong repo

## Manual local upload fallback

If you need to publish once from a local machine without the GitHub release workflow:

```bash
test -n "${PYPI_TOKEN:-}"
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" .venv/bin/python -m twine upload dist/frontend_design_loop_mcp-<version>-py3-none-any.whl dist/frontend_design_loop_mcp-<version>.tar.gz
```
