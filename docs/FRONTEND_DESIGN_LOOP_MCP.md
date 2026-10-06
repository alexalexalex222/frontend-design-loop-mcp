# Workflow and client reference

Setup defaults to the host-agent toolkit. `--workflow automated` selects the loop
server. Both use stdio; clients launch the server as a subprocess. Both entrypoints
ship in the distribution. The host-agent toolkit works with any client supporting
local stdio and benefits from a host that can inspect returned MCP image blocks.

## Copyable client configurations

Use `frontend-design-loop-setup --print-config` or the client-specific print flag
for the **correct absolute Python path in your environment**. These examples use
`/absolute/path/to/.venv/bin/python`; substitute your environment's executable.
On Windows use `C:\\path\\to\\.venv\\Scripts\\python.exe` inside JSON/TOML strings.
Generated configs escape paths for you. Print flags do not download browsers or
write client settings.

Generic MCP JSON (`--print-config`):

```json
{
  "mcpServers": {
    "frontend-design-toolkit": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "design_toolkit.server"]
    }
  }
}
```

Claude Code (`--print-claude-config`) uses the same command/args payload with
`claude mcp add-json --scope user frontend-design-toolkit '<payload>'`.
The helper prints a platform-specific command; in PowerShell, a JSON file/manual
merge avoids command-line JSON quoting differences. Explicit `--install-claude`
invokes the client CLI. Choose `--scope project` for shared project configuration.
[Claude Code documentation](https://code.claude.com/docs/en/mcp).

Codex (`--print-codex-config`; default `~/.codex/config.toml`):

```toml
[mcp_servers."frontend-design-toolkit"]
command = "/absolute/path/to/.venv/bin/python"
args = ["-m", "design_toolkit.server"]
enabled = true
startup_timeout_sec = 30
tool_timeout_sec = 900
```

The helper includes managed-block markers so explicit installation can update its
own block. Existing unmanaged entries with the same name are refused. Use
`--server-name` for a separate entry. [Codex documentation](https://developers.openai.com/codex/mcp).

OpenCode (`--print-opencode-config`; default `~/.config/opencode/opencode.json`):

```json
{
  "mcp": {
    "frontend-design-toolkit": {
      "type": "local",
      "command": ["/absolute/path/to/.venv/bin/python", "-m", "design_toolkit.server"],
      "enabled": true
    }
  }
}
```

[OpenCode documentation](https://opencode.ai/docs/mcp-servers/).
Existing settings are preserved by value; explicit OpenCode installation converts
JSONC to formatted JSON. Its comments are not preserved. If that matters, copy the
printed block yourself. Print/install flags for Gemini and Droid are retained.
Path overrides let developers install into project/test config files.

## Host-agent workflow

Read `get_playbook("solve")`. The host owns edits, source checkpoints, planning,
visual review, and delivery. Toolkit preview tools do not isolate your source tree.
Use native Git or your normal snapshot mechanism to preserve baseline/best states.

`preview_start` accepts a command string or argv array, working directory, optional
port, and readiness timeout. Prefer argv arrays across platforms. `{port}`, `$PORT`,
and `${PORT}` expand to the selected port; PORT is also supplied in the child env.
Use the returned URL/PID. Busy ports are refused. Readiness requires HTTP 2xx/3xx
and a running owned child; it does not prove the page is correct. Stop only owned
previews using `preview_stop(pid)`; omit PID to stop all owned previews. The toolkit
also stops previews during normal server shutdown.

`run_gates` accepts explicit test/lint argv arrays or strings. Strings are shell-free
unless `unsafe_shell=true` is explicitly requested. These commands run with your
user privileges. Only an explicit package.json test script is inferred by default.
Pass `auto_detect_test=false` for a deliberately manual run. Missing commands yield
`status="skipped"`, `*_ok=null`, and null return code. Execution errors/timeouts are
`error`; nonzero command exits are `failed`; successful exits are `passed`. Choose
which gates are required from the actual task, not from the absence of failures.

## Screenshots, focused interactions, and evidence

Capture baseline and candidate using consistent viewport definitions. Example:

```json
{
  "url": "http://127.0.0.1:3100/",
  "evidence_label": "candidate-menu",
  "viewports": [
    {"label": "mobile", "width": 375, "height": 812},
    {"label": "desktop", "width": 1440, "height": 900}
  ],
  "interactions": [
    {"action": "click", "selector": "button[aria-label='Menu']"},
    {"action": "expect_visible", "selector": "#mobile-menu"},
    {"action": "expect_text", "selector": "#mobile-menu", "value": "Book a repair"}
  ]
}
```

Interactions support click, fill, press, expect_visible, and expect_text. Each
viewport starts fresh and executes the same requested steps; capture separately
if desktop/mobile have different controls. Initial and post-interaction images are
both retained. Stops at the first failed step on each viewport. Unrequested
interaction checks are `not_run`. Click/fill alone does not assert a business
outcome. Use explicit state assertions and additional project tests for real flows.

The response includes labeled MCP image content and a structured manifest plus a
JSON text copy for clients without structured-content support. `include_images=false`
returns manifest only; overlarge image responses stop at a bounded size and report
the omitted content. Read the remaining local image paths if your host supports it.
Every capture has its own directory, JSON manifest, dimensions, state labels, PNG
hashes, console/page errors, navigation checks, and document overflow checks.
The source revision is caller-supplied and unverified. Capture failure is `error`,
a detected issue is `failed`; a completed check with no detected issue is `passed`.

Only the requested local document origin is permitted, including redirects and
frames. Remote assets (fonts/images/scripts) can load; this is not a network sandbox.
Console collection and redaction are bounded/heuristic. Horizontal overflow does
not detect all clipping. Image capture does not verify all animation/hover/loading
states, accessibility, copy accuracy, subjective quality, or human preference.

## Optional automated loop

Use `--workflow automated` when printing/installing configurations. This chooses
`frontend_design_loop_mcp.mcp_server`. Native provider adapters require their CLI
installed and an existing suitable login; use supported explicit provider/model/
effort/auth_mode settings from the tool schema. The helper never picks a model or
changes account/default-provider settings. `--auth-check` only checks local status;
live inference is always reported separately as `not_run` by setup.

Cloud providers remain optional through `[cloud]`. Native-only installation keeps cloud packages optional; cloud selection requires
the extra. Provider credentials are not needed for toolkit
capture or automated host-reviewed evaluation. Examine actual artifacts and explicit
check status before claiming an automated result passed.

## Developer checks

Install editable `.[dev]` into a local environment. Run focused setup/toolkit tests:

```sh
python -m pytest tests/test_frontend_design_loop_setup.py tests/test_design_toolkit_behavior.py tests/test_design_toolkit_server_contract.py
python -m design_toolkit.smoke
```

Toolkit smoke exercises installed-module stdio initialization, playbooks, skipped
gates, and PID rejection without models. Real preview/render checks need loopback
and browser permissions. The lead runs both installed entrypoints and actual desktop/
mobile rendering during integration. Hosted Windows results and live native-model
success must be reported only after their respective real runs.

## Native automation and delivery

See the README for an exact native model/effort example and background-job calls.
`frontend_design_loop_design` accepts `design_scope=repair|refine|redesign`, explicit
candidate directions, independent planner/builder/refiner/judge choices, and a
`worktree_setup_command` for isolated dependency installation. The host toolkit
remains suitable for non-Git projects and clients that own their own edits.

The source policy retains tracked working contents and untracked ordinary source.
Snapshots record every ignored/generated/sensitive untracked exclusion. Changed
tracked sensitive paths, submodules, sparse checkouts, and transforming Git filters
fail explicitly. Delivery includes additions, binaries, deletions and executable
modes and is relative to the captured working baseline. Replay uses temporary
indices/filesystems without commits, branches or checkout hooks. A changed live
checkout blocks optional automatic application. Source indexes remain untouched.

Responsive evidence includes initial and post-interaction states, viewport and PNG
dimensions, hashes, font/image readiness, HTTP status, browser errors, broken images,
overflow and requested assertions. Very tall pages use bounded viewport captures;
those limitations are recorded. `asset_policy=same_origin` blocks foreign assets;
`public_assets` permits HTTPS GET/HEAD image/font/style/script/media reads. Foreign
document navigation and writes remain blocked. Policy-caused console errors are
recorded as blocked requests rather than application defects. This is not a sandbox
for project code or proof of untested accessibility/behavior.

Native binaries resolve from PATH and common installation directories. An explicit
absolute binary override can be supplied with FRONTEND_DESIGN_LOOP_CODEX_CLI,
FRONTEND_DESIGN_LOOP_CLAUDE_CLI or FRONTEND_DESIGN_LOOP_OPENCODE_CLI. No auth/default
model configuration is changed. Unsupported exact model/effort pairs stop clearly.

Normal disconnect and POSIX SIGTERM/SIGINT unwind owned jobs/processes and worktrees.
A forced OS kill cannot guarantee cleanup; native Windows forced-kill behavior has
not been verified locally. Portable process cleanup and responsive stdio smoke are
included in CI. Locally observed native inference is not a guarantee for every
provider/model, platform or enterprise-managed effort policy.
