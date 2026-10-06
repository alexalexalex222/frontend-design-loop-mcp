# Windows verification

Owning Windows hardware is unnecessary for automated verification. GitHub provides
actual hosted Windows machines. The prepared workflow uses Windows Server 2022
and 2025 with x64 Python 3.10, 3.12 and 3.14, plus Windows 11 on an ARM host with
x64 Python/Node under emulation. The Windows 11 job tests that OS's kernel and
filesystem behavior; it does not establish native ARM64 Python/browser support.

## Release checks

The `portability` job runs the complete test suite, including native Windows
process tests. Platform-specific skipped tests report their reasons. Windows
Job Object tests must execute on Windows rather than being inferred from Mac
mocks. They cover ordinary descendant membership, parent exit, redirected and
held-open pipes, timeout/cancellation, startup failures, inherited stdin/stdout,
and Windows exit status. Source replay checks include physical CRLF bytes, Git
normalization, paths with spaces, and disabled symlinks.

After those tests, the job builds a wheel and source distribution. The portable
release checker installs each into a separate clean environment, without cloud
extras, and runs outside the checkout. It verifies all three console entrypoints,
packaged playbooks, a real `npm` gate and preview, desktop/mobile interactions,
returned PNGs and file hashes, owned preview shutdown, and responsive automated
evaluation through MCP stdio. It invokes no provider or model.

```sh
python -m build --outdir out/distributions
python scripts/verify_installed_package.py --artifact out/distributions --out-dir out/wheel-proof
python scripts/verify_installed_package.py --artifact out/distributions --distribution sdist --installer uv --out-dir out/sdist-proof
```

Git, Node/npm, and Python must be available. Install `uv` for the second route.
The checker installs Chromium in the selected environment; Linux hosts also need
Playwright's documented browser system libraries. Each output directory must be
new or empty. Successful receipts contain the actual OS, Python, installer,
distribution hash and verification result. CI retains the receipts, JUnit test
results, logs, and screenshots, including evidence from failed attempts.

## Current evidence and remaining acceptance

The checker has passed on macOS against clean pip wheel and `uv tool` source
installs of the 1.1.0 upgrade. Hosted checks now run on the
[verification branch](https://github.com/alexalexalex222/frontend-design-loop-mcp/actions/workflows/ci.yml?query=branch%3Acodex%2Ffrontend-loop-1.1-windows).
Use the result for the exact candidate commit; an older green run does not verify
later changes. Failed attempts retain their platform receipts and diagnostics.

Before declaring Windows support verified, run the prepared workflow against the
exact candidate, fix observed failures, and retain passing native receipts.
Before release, also verify setup and one normal workflow in a supported desktop
MCP client with standard user permissions. Hosted runners run with elevated
permissions and cannot establish every desktop client's launch configuration,
login flow, restrictive corporate policy, or antivirus behavior. Real model
authentication/inference remains a separate opt-in check.

The upgrade is on the verification branch and has not been published as a package
release. These checks do not activate a desktop client or change its accounts.
