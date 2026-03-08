import json
from pathlib import Path

import anyio
import pytest

from frontend_design_loop_core import mcp_code_server
from frontend_design_loop_core.config import load_config
from frontend_design_loop_core.providers.kilo_cli import KiloCLIProvider
from frontend_design_loop_core.utils import extract_json_strict


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Northstar Automation Studio</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <div class="grid-bg"></div>
  <header class="header">
    <div class="header-inner">
      <div class="logo">Northstar<span class="logo-dot"></span></div>
      <nav class="nav">
        <a href="#system">The System</a>
        <a href="#proof">Proof</a>
        <a href="#deploy">Deploy</a>
      </nav>
    </div>
  </header>
  <main class="hero-shell">
    <section class="hero-copy">
      <p class="eyebrow">missed-call interception for owner-operators</p>
      <h1>automation that closes the gap before the callback dies</h1>
      <p class="subcopy">text-back, routing, and booking capture without agency filler.</p>
    </section>
  </main>
</body>
</html>
"""

_STYLES_CSS = """:root {
  --bg: #09111f;
  --panel: rgba(10, 17, 31, 0.78);
  --line: rgba(155, 255, 208, 0.24);
  --ink: #f4f8ff;
  --accent: #7fffd4;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: "Inter", sans-serif;
  color: var(--ink);
  background:
    radial-gradient(circle at top, rgba(127, 255, 212, 0.14), transparent 36%),
    linear-gradient(180deg, #08101d 0%, #050913 100%);
}

.hero-shell {
  min-height: 100vh;
  padding: 96px 72px 80px;
}

.hero-copy {
  max-width: 720px;
  padding: 40px;
  border: 1px solid var(--line);
  background: var(--panel);
  backdrop-filter: blur(18px);
}
"""


def _build_realistic_patch_bundle_text() -> str:
    payload = {
        "patches": [
            {"path": "index.html", "patch": _INDEX_HTML},
            {"path": "styles.css", "patch": _STYLES_CSS},
        ],
        "notes": ["whole-file rewrite salvage repro from kilo stream"],
    }
    return json.dumps(payload, separators=(",", ":"))


def test_kilo_cli_salvages_streamed_whole_file_patch_bundle_before_strict_json_parse() -> None:
    provider = KiloCLIProvider(load_config())
    payload_text = _build_realistic_patch_bundle_text()

    # Split inside a token so the test isolates stream reassembly rather than
    # whitespace damage from chunk boundaries.
    split_at = payload_text.index("Automation") + 5
    fragment_one = payload_text[:split_at]
    fragment_two = payload_text[split_at:]

    with pytest.raises(ValueError):
        extract_json_strict(fragment_one)

    stdout_text = (
        json.dumps({"type": "text", "part": {"text": fragment_one}})
        + "\n"
        + json.dumps({"type": "text", "part": {"text": fragment_two}})
        + "\n"
        + json.dumps({"type": "step_finish", "part": {"type": "step-finish"}})
        + "\n"
    )

    with pytest.raises(ValueError):
        extract_json_strict(stdout_text)

    content = provider._extract_content(
        stdout_text=stdout_text,
        stderr_text="",
        output_file=None,
    )

    assert content == payload_text
    data = extract_json_strict(content)
    assert [item["path"] for item in data["patches"]] == ["index.html", "styles.css"]
    assert data["patches"][0]["patch"].startswith("<!doctype html>")
    assert "Northstar Automation Studio" in data["patches"][0]["patch"]


def test_kilo_cli_prefers_merged_or_longest_valid_fragment_when_last_chunk_regresses() -> None:
    provider = KiloCLIProvider(load_config())
    payload_text = _build_realistic_patch_bundle_text()
    fragment_one = payload_text[:180]
    fragment_two = payload_text
    fragment_three = payload_text[:-40]

    stdout_text = (
        json.dumps({"type": "text", "part": {"text": fragment_one}})
        + "\n"
        + json.dumps({"type": "text", "part": {"text": fragment_two}})
        + "\n"
        + json.dumps({"type": "text", "part": {"text": fragment_three}})
        + "\n"
    )

    content = provider._extract_content(
        stdout_text=stdout_text,
        stderr_text="",
        output_file=None,
    )

    assert content == payload_text
    data = extract_json_strict(content)
    assert [item["path"] for item in data["patches"]] == ["index.html", "styles.css"]


def test_apply_patch_bundle_accepts_whole_file_rewrites_from_salvaged_kilo_bundle(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html><body>old hero</body>\n", encoding="utf-8")
    (repo / "styles.css").write_text("body { color: black; }\n", encoding="utf-8")

    payload = extract_json_strict(_build_realistic_patch_bundle_text())

    async def run_apply() -> tuple[bool, list[str]]:
        return await mcp_code_server._apply_patch_bundle(
            repo_root=repo,
            patches=payload["patches"],
        )

    applied_ok, touched = anyio.run(run_apply)

    assert applied_ok is True
    assert touched == ["index.html", "styles.css"]
    assert (repo / "index.html").read_text(encoding="utf-8") == _INDEX_HTML
    assert (repo / "styles.css").read_text(encoding="utf-8") == _STYLES_CSS
