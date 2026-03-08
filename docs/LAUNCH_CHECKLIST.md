# Launch Checklist

## Goal

Make `frontend-design-loop-mcp` easy to install, easy to believe, and easy to discover.

## Phase 1: Current public launch

This is the minimum launch state that should exist before promoting the repo.

- public repo is live and clean
- README above-the-fold includes:
  - one-sentence promise
  - public install command
  - one MCP setup command
  - one strong whole-page before/after proof
  - one concrete tool-call example
- local verification is green:
  - tests
  - offline preflight
  - stdio smoke
- MCP docs match the public install story
- directory submission copy exists

## Phase 2: Distribution

### Current public install path

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

### Future public install path

Use this only after PyPI is actually live:

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

## Phase 3: Proof assets

Before pushing traction, make sure the repo has at least:

- 3 full-page before/after case studies
- 1 case where the base page is ugly but functional
- 1 case where the page is broken or rough and gets fixed
- 1 case where an AI-generated page gets materially improved
- one whole-page compare image for each
- one short explanation of what changed and why it matters

## Phase 4: Directory submissions

Submit to:
- Glama
- PulseMCP
- MCP Market

Use `docs/MCP_DIRECTORY_SUBMISSIONS.md` as the source for submission copy.

## Phase 5: Launch message

The launch story should be narrow and believable:
- coding agents already make pages work
- this MCP makes them look materially better
- it does that with screenshot-grounded iteration and proof artifacts

Avoid positioning it as a generic everything-tool.

## Phase 6: PyPI release

Only after the public GitHub launch path is stable:

1. bump version in `pyproject.toml`
2. run release checklist from `RELEASING.md`
3. publish to PyPI
4. verify `pipx install frontend-design-loop-mcp`
5. update README and docs to make PyPI the primary install path
6. refresh directory listings with the PyPI install path
