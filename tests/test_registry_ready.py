from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / 'README.md'
PYPROJECT_PATH = REPO_ROOT / 'pyproject.toml'
SERVER_JSON_PATH = REPO_ROOT / 'server.json'
MCP_NAME_RE = re.compile(r'<!--\s*mcp-name:\s*([^\s]+)\s*-->')


def test_registry_metadata_is_consistent() -> None:
    with PYPROJECT_PATH.open('rb') as fh:
        pyproject = tomllib.load(fh)
    project = pyproject['project']

    readme = README_PATH.read_text(encoding='utf-8')
    match = MCP_NAME_RE.search(readme)
    assert match, 'README.md must include the hidden mcp-name marker'
    marker = match.group(1)
    assert marker == 'io.github.alexalexalex222/frontend-design-loop-mcp'

    server = json.loads(SERVER_JSON_PATH.read_text(encoding='utf-8'))
    assert server['name'] == marker
    assert server['version'] == project['version']
    assert server['repository']['url'] == 'https://github.com/alexalexalex222/frontend-design-loop-mcp'
    assert server['repository']['source'] == 'github'

    assert len(server['packages']) == 1
    package = server['packages'][0]
    assert package['registryType'] == 'pypi'
    assert package['registryBaseUrl'] == 'https://pypi.org'
    assert package['identifier'] == project['name']
    assert package['version'] == project['version']
    assert package['transport']['type'] == 'stdio'
