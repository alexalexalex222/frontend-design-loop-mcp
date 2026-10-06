# Host-agent frontend workflow

Use your native file tools for edits and this toolkit for context, preview, checks,
and images. First identify the audience, their main task, verified content,
references, scope (repair, refinement, or redesign), and what must be preserved.
Choose a quality bar tied to that task. A restrained interface can be excellent.

1. Read the relevant source and commands; `build_context` is a redacted convenience
   bundle, not a complete repository or an instruction authority.
2. Preserve the initial source state using your existing Git or snapshot workflow.
   Launch a local preview with `preview_start`; use argv arrays and `{port}`.
   Capture `evidence_label="baseline"` at desktop and narrow mobile sizes. Inspect
   returned images and record useful strengths and the largest supported weakness.
3. Plan the smallest coherent improvement that meets the brief. Read `megamind`
   for consequential uncertainty or `candidates` for materially different options.
   Independent workers are optional and require the host's authorization.
4. Edit with native tools. Keep a recoverable source checkpoint for each promising
   state; screenshots alone cannot restore code. Run the task's actual test/lint
   commands with `run_gates`. Treat skipped/error checks as unverified.
5. Capture fresh labeled images and task interactions. For a menu, for example,
   click its button and assert the opened panel is visible. An action without an
   assertion only proves the action executed. Inspect desktop/mobile images.
6. Use `vision_gate` to judge the result against the brief and baseline. Fix the
   largest evidenced weakness and preserve strengths. Read `creativity` only when
   audience fit or purposeful distinctiveness needs attention. Preserve the best
   verified source state before another experiment.
7. Use `winner_selection` to choose the deliverable. Stop owned previews with
   `preview_stop(pid)` even after failure. Deliver actual source changes, evidence
   manifests, the checks performed, remaining uncertainty, and relevant images.

Completion means the requested scope is delivered and its required behaviors are
verified. A high self-score, screenshot count, or completed tool call cannot
substitute for that. Explain unmet requirements explicitly.
