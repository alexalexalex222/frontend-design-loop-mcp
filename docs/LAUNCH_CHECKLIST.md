# Launch Checklist

## Goal

Keep the public story narrow and believable:
- coding agents can get pages functional
- Frontend Design Loop makes them materially better
- screenshot-grounded iteration plus proof artifacts is the differentiator

## Public Story Checklist

- README above the fold includes:
  - one-line promise
  - one public install command
  - one setup command
  - one real MCP call example
  - one strong whole-page before/after proof
  - link to `docs/case-studies/index.md`
  - short explanation of how the MCP works in practice
- `docs/FRONTEND_DESIGN_LOOP_MCP.md` keeps the single-model default explicit
- public docs do not imply multi-model-by-default behavior
- public docs do not reintroduce legacy public branding or old repo identities

## Proof Checklist

- ACA whole-page proof is present in `docs/images/`
- case-study landing page exists at `docs/case-studies/index.md`
- traction push should include at least 3 whole-page case studies
- each case study should include:
  - whole-page before
  - whole-page after
  - whole-page compare
  - short write-up on what changed and why it matters
- no fake before states
- no section-only headline proof

## Distribution Checklist

- canonical install snippet uses:

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

- GitHub fallback remains available:

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

- `docs/MCP_DIRECTORY_SUBMISSIONS.md` is the source of truth for directory copy
- PyPI release is live. Current preferred maintenance path:
  - workflow file: `.github/workflows/release.yml`
  - GitHub environment: `pypi`
  - PyPI project name: `frontend-design-loop-mcp`
  - automated publish currently uses repo secret `PYPI_TOKEN`
- submission targets:
  - Glama
  - PulseMCP
  - MCP Market

## Verification Checklist

Run these before claiming the docs and launch surface are clean:

```bash
rg -n "single-model default|split routing only happens when the caller explicitly asks" README.md docs/FRONTEND_DESIGN_LOOP_MCP.md
test -f docs/images/aca-site50-v9-fullpage-before.png
test -f docs/images/aca-site50-v22-fullpage-after.png
```

Repo-level verification expected after merge:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q --import-mode=importlib
PYTHONPATH=src .venv/bin/python scripts/preflight_check.py
PYTHONPATH=src .venv/bin/python scripts/smoke_mcp_stdio.py
python -m build
twine check dist/*
```

## PyPI Release

Only switch the public install story after PyPI is actually live:

1. bump version in `pyproject.toml`
2. run the release checklist from `RELEASING.md`
3. publish to PyPI
4. verify `pipx install frontend-design-loop-mcp`
5. refresh directory listings with the PyPI install path
