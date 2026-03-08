# Frontend Design Loop MCP Skill Notes

Use Frontend Design Loop MCP when an interactive coding agent needs:
- active frontend design improvement
- isolated patch evaluation
- deterministic gates
- preview screenshots
- machine-readable run artifacts

Preferred tool:
- `frontend_design_loop_design` for design improvement
- `frontend_design_loop_eval` for proof-only verification

Design workflow rule:
- `frontend_design_loop_design` stays on one main provider/model by default
- only split planning or vision onto other lanes when the caller explicitly overrides those fields

Migration aliases still exist, but new docs and new clients should use the Frontend Design Loop names.

Quick client setup helpers:
- All detected: `frontend-design-loop-setup --install-all-detected-clients`
- Claude: `frontend-design-loop-setup --install-claude --scope user`
- Codex: `frontend-design-loop-setup --install-codex`
- Gemini: `frontend-design-loop-setup --install-gemini`
- Droid: `frontend-design-loop-setup --install-droid`
- OpenCode: `frontend-design-loop-setup --install-opencode`
