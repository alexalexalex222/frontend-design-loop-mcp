# MCP Directory Submission Copy

Use this file as the source of truth for listing `frontend-design-loop-mcp` on MCP directories.

## Canonical repo

- Repo: `https://github.com/alexalexalex222/frontend-design-loop-mcp`
- Current public install:

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

## Canonical one-line description

Design-first MCP that helps coding agents start, fix, and materially improve websites with screenshot-grounded iteration and proof artifacts.

## Short description

Frontend Design Loop MCP helps coding agents turn rough or generic frontends into stronger pages by iterating against real screenshots, then returning proof artifacts and the winning patch.

## Longer description

Frontend Design Loop MCP is an agent-first design and verification layer for frontend work.

It is built for coding agents that already got the page functional but still need help making it look deliberate, fixing weak sections, or proving that a redesign actually improved the rendered result.

The main workflow, `frontend_design_loop_design`, stays on one main provider and model lane by default, boots a local preview, captures screenshots, iterates against the rendered result, and returns the winning patch plus proof artifacts.

The support workflow, `frontend_design_loop_eval`, is the proof path for host-authored patches: deterministic checks, screenshots, run directories, and stable machine-readable output.

## Core value props

- makes weak or generic frontends materially better, not just technically valid
- screenshot-grounded refinement instead of blind code-only tweaking
- one main model lane by default, with split lanes only when explicitly requested
- deterministic proof and artifact capture for coding-agent workflows
- works with Claude Code, Codex, Gemini CLI, Droid, OpenCode, and similar tools

## Suggested tags

- `frontend`
- `design`
- `website`
- `mcp`
- `coding-agents`
- `screenshots`
- `refinement`
- `verification`

## Suggested categories

- Frontend Development
- Design Tools
- Developer Productivity
- MCP / AI Agent Tooling

## Proof blurb

The repo includes a full-page before/after example showing an ugly early homepage version rebuilt into a materially stronger final page, plus a whole-page compare image. The product is meant to create visible page-level improvement, not just run static checks.

## Install snippet

```bash
pipx install git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git
frontend-design-loop-setup --install-all-detected-clients
```

## MCP config snippet

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

## Claude-specific setup snippet

```bash
frontend-design-loop-setup --install-claude --scope user
```

## Codex-specific setup snippet

```bash
frontend-design-loop-setup --install-codex
```

## Gemini-specific setup snippet

```bash
frontend-design-loop-setup --install-gemini
```

## Submission notes by directory

### Glama

Use the short description plus the install snippet.
If there is a field for why it matters, use:

`It gives coding agents a screenshot-grounded design loop so they can materially improve rough frontends instead of stopping at functional output.`

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

`Design-first MCP for starting, fixing, and upgrading websites.`

If there is a use-cases field, use:
- upgrade weak AI-generated frontends
- repair broken sections without losing momentum
- capture proof artifacts for host-agent review
