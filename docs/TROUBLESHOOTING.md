# Troubleshooting

## Browser missing or launch fails

Run `frontend-design-loop-setup` in the same Python environment that launches your
server. It installs Chromium, not client configs. `--check` launches Chromium and
checks a local page in that environment. On Linux, install the system
browser libraries required by Playwright using your administrator's normal workflow
(`python -m playwright install --with-deps chromium` may require system privileges).

Use `--doctor` for read-only checks. The toolkit needs no provider CLI or credentials.
`--auth-check` opts into CLI status probes, never login or model inference. Installed,
authenticated, and usable model access are separate states; OpenCode credential-list
output cannot establish the effective route of a particular provider/model.

## Client cannot find the server

Print fresh configs from the installed environment using `--print-config` or
`--print-codex-config`, `--print-claude-config`, `--print-opencode-config`.
They use an absolute interpreter path. Keep the environment at that path and restart
the client. Use `--workflow automated` only when you want the automated loop module.
Both console entrypoints also support `--version`. If the client has an existing
entry with `enabled = false`, restarting will not activate it. Inspect and enable
that specific entry when you want to use it; setup preserves existing settings.

Windows fallback launches:

```text
<venv>\Scripts\python.exe -m design_toolkit.server
<venv>\Scripts\python.exe -m frontend_design_loop_mcp.mcp_server
```

This also avoids the observed `uv trampoline failed to canonicalize script path`
launcher problem. Windows command paths are escaped in generated JSON/TOML. Prefer
argv arrays for test/preview commands rather than shell text. Git is required for
automated worktree flows, not static toolkit screenshot capture.

Windows command strings follow Microsoft C runtime argument rules: use double
quotes around paths with spaces. Single quotes remain literal. An argv array
avoids quoting entirely, including embedded quotes and trailing backslashes.
Native `.exe`/`.com` commands and recognized npm-generated Node launchers are
supported. Custom batch wrappers fail with an explicit error; supply their native
executable or Node script as argv instead. Commands resolve against the child
environment's PATH and PATHEXT.

Source snapshots record actual checkout bytes separately from Git's normalized
blobs and modes. CRLF normalization and `core.symlinks=false` do not require
altering the developer's index or repository settings. Delivered patches include
any byte or type changes needed to reproduce the inspected candidate exactly.

## Existing client entry is refused

An unmanaged entry is left intact. Choose `--server-name` or merge the printed
configuration yourself after inspecting the existing entry. Invalid JSON/TOML is
not replaced. JSONC installation preserves values but removes comments/formatting;
print and merge manually when comment preservation matters.

## Preview does not start or is rejected

Use the actual project preview command, an existing cwd, and `{port}`. The toolkit
sets PORT and refuses a busy port. HTTP 404/5xx is not readiness. Launch failures
return bounded drained logs. Loopback URLs and document navigation must stay at the
requested origin; public URLs and redirects to another port are rejected. Remote
assets may still load. A sandbox denying socket binds/browser execution cannot
verify a preview; rerun in an environment with those permissions.

The preview command must stay in the foreground. Commands that start a daemon
and immediately exit cannot give the toolkit ownership of that detached process.
Use the framework's foreground mode and inspect the returned launch logs.
For Astro 7.3.5, agent detection can start a background server even without an
explicit `--background`; `--ignore-lock` keeps this isolated preview in the
foreground:

```text
["npm", "run", "dev", "--", "--port", "{port}", "--host", "127.0.0.1", "--ignore-lock"]
```

If a prior attempt daemonized, use `astro dev status` and `astro dev stop` from
that exact project to reconcile its server. Do not stop another project's preview.

For Vite, use `npm run dev -- --host 127.0.0.1 --port {port}`. For Next.js,
build the project first and preview with `npm run start -- --port {port}` (where
`start` is `next start`). The validation fixtures exercised Vite 8.3.2, Astro
7.3.5, and Next.js 16.3.8 with actual desktop/mobile form and route interactions.
These checks establish the tested commands, not every framework configuration.

On this host, Next.js 16.3.8 dev HMR/hydration failed under the default server
binding even when the page returned HTTP 200. Explicitly binding the server to
IPv4 allowed the interactions to run:
`npm run dev -- --port {port} --hostname 127.0.0.1`. Keep PostCSS configuration
inside the project; an inherited parent config can break an isolated fixture.

For client-rendered controls, start the interaction list with `expect_visible` on
an application-provided ready state, or keep controls disabled until initialized.
Visible server-rendered markup does not prove its client handler is ready.

Only returned preview PIDs are owned. `preview_stop` rejects arbitrary PIDs. It
terminates the preview process tree, not unrelated applications. If the MCP is
abruptly killed by the operating system, inspect the actual process yourself before
terminating it; normal toolkit shutdown performs cleanup.

On Windows, each command runs through a small owned Python host which joins an
anonymous Job Object before creating the target. Descendants stay in that Job
even if the target exits first. A Job or launch failure returns an error before
the runner hands back a process; it does not proceed without ownership. The
returned PID belongs to the invocation host. POSIX commands own process groups.

## Tests or interactions say skipped/not_run

That is unverified, not success. Supply the project's actual test/lint commands or
requested selector-based interactions. The toolkit does not invent a Python test
suite from pyproject.toml. Each viewport starts fresh; desktop controls may differ
from mobile, requiring separate captures. A click alone proves execution, so add
expect_visible/expect_text for the result you need.

## Images are missing from the client

Check manifest status and image paths. `include_images=false` deliberately returns
no image blocks; a bounded response can omit later images. Some MCP clients/models
do not support images. Use a vision-capable host and local image reading when
available. Missing evidence leaves visual review pending. Manifests and paths are
not equivalent to inspected images.

## Cloud provider import fails

Install this checkout with `python -m pip install '.[cloud]'` in the server environment
when selecting cloud adapters. Native CLI/toolkit installs should not require that
extra. Selecting a provider does not authorize login/account or default-provider
changes; configure only the requested route and check current CLI support.
