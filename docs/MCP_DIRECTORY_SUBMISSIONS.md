# MCP Directory Submission Copy

Use this file as the source of truth for listing `frontend-design-loop-mcp` on MCP directories.

## Canonical Repo

- Repo: `https://github.com/alexalexalex222/frontend-design-loop-mcp`
- Official registry metadata source: tracked in `server.json` at the repo root
- Current public install:

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

## Canonical One-Line Description

MCP for coding agents that upgrades rough frontends with screenshot-grounded iteration and proof artifacts.

## Short Description

Frontend Design Loop helps coding agents take a functional but weak page, iterate against real screenshots, and return the winning patch plus proof artifacts.

## Longer Description

Frontend Design Loop MCP is a design and verification layer for coding agents working on websites.

It is built for the common gap where the base model already got the page functional, but the result still looks generic, flat, rough, or visibly unfinished.

The main workflow, `frontend_design_loop_design`, boots a local preview, captures screenshots, iterates against the rendered result, and returns the winning patch plus proof artifacts. By default it stays on one main provider and model lane; split routing only happens when the caller explicitly asks for it.

The support workflow, `frontend_design_loop_eval`, is the proof path for host-authored patches: deterministic checks, screenshots, run directories, and stable machine-readable output.

## Core Value Props

- helps coding agents make rough frontends materially better, not just technically valid
- screenshot-grounded refinement instead of blind code-only tweaking
- single-model by default, with split lanes only on explicit override
- deterministic proof and artifact capture for host-agent workflows
- works with Claude Code, Codex, Gemini CLI, Droid, OpenCode, and similar tools

## Suggested Tags

- `frontend`
- `design`
- `website`
- `mcp`
- `coding-agents`
- `screenshots`
- `verification`

## Suggested Categories

- Frontend Development
- Design Tools
- Developer Productivity
- MCP / AI Agent Tooling

## Proof Blurb

The repo already includes a whole-page ACA before/after pair showing an ugly early homepage rebuilt into a materially stronger result. The case-study landing page lives in `docs/case-studies/`, and the public proof surface is intentionally sparse until additional owned/generated whole-page proofs are both visually strong and legally safe to publish.

## Install Snippet

```bash
pipx install frontend-design-loop-mcp
frontend-design-loop-setup --install-all-detected-clients
```

## MCP Config Snippet

```json
{
  "mcpServers": {
    "frontend-design-loop-mcp": {
      "command": "frontend-design-loop-mcp",
      "args": []
    }
  }
}
```

## Client Setup Snippets

Claude:

```bash
frontend-design-loop-setup --install-claude --scope user
```

Codex:

```bash
frontend-design-loop-setup --install-codex
```

Gemini:

```bash
frontend-design-loop-setup --install-gemini
```

## Submission Notes By Directory

## Current Live Status

Status snapshot from 2026-03-09:
- GitHub repo and PyPI package are live under `frontend-design-loop-mcp`
- Glama new-slug page `@alexalexalex222/frontend-design-loop-mcp` still resolves to the legacy `petamind-mcp` listing
- PulseMCP new-slug page returns `404`
- MCP Market new-slug page returns `403` from this shell, so browser/manual verification is still pending

Recommended next moves:
- Glama: fix or replace the legacy listing so the new slug stops redirecting to `petamind-mcp`
- PulseMCP: submit or refresh the new listing
- MCP Market: verify manually in a browser session, then submit or refresh if needed

### Glama

Use the short description plus the install snippet.

If there is a "why it matters" field, use:

`It gives coding agents a screenshot-grounded loop for taking a page past functional output and into a materially stronger rendered result.`

### PulseMCP

Use the longer description and the proof blurb.

If there is a features field, use:
- design-first workflow for weak frontends
- proof workflow for host-authored patches
- screenshot-grounded iteration
- deterministic verification artifacts
- multi-client setup helper

### MCP Market

Keep the headline tight:

`MCP for upgrading rough frontends with screenshot-grounded proof.`

If there is a use-cases field, use:
- upgrade weak AI-generated frontends
- fix rough or generic sections without losing momentum
- capture proof artifacts for host-agent review
