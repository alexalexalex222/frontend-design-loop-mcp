#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / 'README.md'
PYPROJECT_PATH = REPO_ROOT / 'pyproject.toml'
SERVER_JSON_PATH = REPO_ROOT / 'server.json'
MCP_NAME_RE = re.compile(r"<!--\s*mcp-name:\s*([^\s]+)\s*-->")
EXPECTED_REPOSITORY = 'https://github.com/alexalexalex222/frontend-design-loop-mcp'
EXPECTED_NAMESPACE = 'io.github.alexalexalex222/frontend-design-loop-mcp'


def fail(message: str) -> None:
    print(f'[registry-ready] ERROR: {message}', file=sys.stderr)
    raise SystemExit(1)


def load_pyproject() -> dict:
    with PYPROJECT_PATH.open('rb') as fh:
        return tomllib.load(fh)


def extract_mcp_name(readme_text: str) -> str:
    match = MCP_NAME_RE.search(readme_text)
    if not match:
        fail('README.md is missing the hidden mcp-name marker comment')
    return match.group(1)


def check_pypi(name: str, version: str) -> None:
    url = f'https://pypi.org/pypi/{name}/json'
    try:
        with urlopen(url, timeout=10) as resp:
            payload = json.load(resp)
    except HTTPError as exc:
        fail(f'PyPI package check failed for {name}: HTTP {exc.code}')
    except URLError as exc:
        fail(f'PyPI package check failed for {name}: {exc.reason}')

    releases = payload.get('releases', {})
    if version not in releases or not releases[version]:
        fail(f'PyPI package {name} does not have published version {version}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Validate official MCP registry metadata readiness.')
    parser.add_argument('--check-pypi', action='store_true', help='Require the declared PyPI package/version to exist live on PyPI.')
    args = parser.parse_args()

    pyproject = load_pyproject()
    project = pyproject.get('project', {})
    package_name = project.get('name')
    package_version = project.get('version')
    if not package_name or not package_version:
        fail('pyproject.toml is missing project.name or project.version')

    readme_text = README_PATH.read_text(encoding='utf-8')
    mcp_name = extract_mcp_name(readme_text)
    if mcp_name != EXPECTED_NAMESPACE:
        fail(f'README mcp-name marker must be {EXPECTED_NAMESPACE}, got {mcp_name}')

    server = json.loads(SERVER_JSON_PATH.read_text(encoding='utf-8'))
    if server.get('name') != mcp_name:
        fail('server.json name does not match the README mcp-name marker')
    if server.get('version') != package_version:
        fail('server.json version does not match pyproject project.version')
    if server.get('repository', {}).get('url') != EXPECTED_REPOSITORY:
        fail('server.json repository.url does not match the canonical GitHub repo URL')
    if server.get('repository', {}).get('source') != 'github':
        fail('server.json repository.source must be github')

    packages = server.get('packages')
    if not isinstance(packages, list) or len(packages) != 1:
        fail('server.json must declare exactly one package entry for this repo')

    package = packages[0]
    if package.get('registryType') != 'pypi':
        fail('server.json package.registryType must be pypi')
    if package.get('registryBaseUrl') != 'https://pypi.org':
        fail('server.json package.registryBaseUrl must be https://pypi.org')
    if package.get('identifier') != package_name:
        fail('server.json package.identifier must match pyproject project.name')
    if package.get('version') != package_version:
        fail('server.json package.version must match pyproject project.version')
    if package.get('transport', {}).get('type') != 'stdio':
        fail('server.json package transport.type must be stdio')

    if args.check_pypi:
        check_pypi(package_name, package_version)

    summary = {
        'mcp_name': mcp_name,
        'package_name': package_name,
        'version': package_version,
        'repository': EXPECTED_REPOSITORY,
        'pypi_checked': args.check_pypi,
    }
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
