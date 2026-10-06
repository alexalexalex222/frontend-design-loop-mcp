# Frontend design workflow notes for host agents

Use the host-agent toolkit for native frontend edits, responsive image capture,
local previews, focused interaction checks, and evidence-grounded review.
Start with `get_playbook(name="solve")`; it defines the source/evidence workflow.
The host owns source checkpoints, edits, independent review authorization, and
complete delivery. Inspect returned image blocks rather than treating paths as
visual evidence. Skipped/not_run/error checks remain unverified.

Setup defaults to toolkit. Print configs before writing settings:
`frontend-design-loop-setup --print-config` or `--print-codex-config`,
`--print-claude-config`, `--print-opencode-config`. Explicit `--install-*` flags
perform the chosen client installation. Use `--workflow automated` for the
optional provider-driven server; retain explicit provider/model/effort/auth choices.

For automated isolated patch evaluation use `frontend_design_loop_eval`.
For provider-driven generation use `frontend_design_loop_design`. Read their current
tool schemas. Model-backed execution needs a separately configured provider route;
it is not required by the host-agent toolkit. Baseline/candidate evidence and
functional verification do not establish subjective quality or human preference.
