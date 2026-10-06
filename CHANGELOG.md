# Changelog

## 1.1.0 (local, unreleased)

The Windows repair addresses [Pandozer's report and proposed patch (#1)](https://github.com/alexalexalex222/frontend-design-loop-mcp/issues/1).

- Pass Git worktree paths as shell-free arguments, including paths with spaces.
- Isolate command stdin from MCP stdio and terminate process trees on timeouts and preview cleanup.
- Own Windows command trees through Job Objects before launching the target, including descendants whose original parent exits before cleanup.
- Preserve the original error when worktree creation fails during evaluation.
- Constrain the MCP SDK to its compatible 1.x API.
- Add subprocess/worktree regressions and cross-platform stdio preview CI.

- Make host-agent toolkit setup the default, with absolute launcher configs and optional cloud dependencies.
- Add exact native subscription CLI execution and independent role/model/effort settings with honest receipts.
- Replace style recipes and score pressure with brief-grounded building and honest evidence-based review.
- Add labeled responsive/interacted evidence and explicit independent native `review_design`.
- Snapshot retained dirty source, roll back failed/regressing candidates, export complete source deltas and verify replay without hooks.
- Add skipped/error gate states, isolated dependency setup, bounded background jobs and owned shutdown.
- Preserve Windows backslashes and quoted arguments; accept argv arrays throughout automated test, lint, and preview commands.
- Resolve Windows commands from the child environment and launch supported npm/Node shims directly without interpreting batch syntax.
- Separate physical source bytes from normalized Git metadata, preserving CRLF files and symlink-disabled checkouts during source overlay and patch replay.
- Extend portability CI with command/shim, source-replay, and toolkit stdio checks; document tested foreground framework previews and disabled client entries.
- Capture inputs without Playwright's temporary caret-style mutation, avoiding React hydration mismatches during screenshots.
- Preserve exact patch artifact bytes and verify the saved patch; parse Windows executable names with their separate CRT rules.

## 1.0.0

- initial Frontend Design Loop MCP public release
- agent-first MCP runtime
- design-first workflow, deterministic proof, and five-client install UX
