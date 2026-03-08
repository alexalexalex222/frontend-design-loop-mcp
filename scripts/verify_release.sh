#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage: ./scripts/verify_release.sh [--python=/path/to/python] [--github-install-spec=git+https://...] [--skip-github-install]

Runs the release verification flow:
- bootstrap dev dependencies
- pytest
- offline preflight
- stdio smoke
- build + twine check
- wheel smoke
- sdist smoke
- optional GitHub pipx install smoke
EOF
}

PYTHON_BIN=""
HOST_PYTHON="${HOST_PYTHON:-python3}"
GITHUB_INSTALL_SPEC="${GITHUB_INSTALL_SPEC:-git+https://github.com/alexalexalex222/frontend-design-loop-mcp.git}"
RUN_GITHUB_INSTALL=1

for arg in "$@"; do
  case "$arg" in
    --python=*)
      PYTHON_BIN="${arg#*=}"
      ;;
    --github-install-spec=*)
      GITHUB_INSTALL_SPEC="${arg#*=}"
      ;;
    --skip-github-install)
      RUN_GITHUB_INSTALL=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
  if [ ! -x "$PYTHON_BIN" ]; then
    if ! command -v "$HOST_PYTHON" >/dev/null 2>&1; then
      echo "Missing host python: $HOST_PYTHON" >&2
      exit 1
    fi
    "$HOST_PYTHON" -m venv "$REPO_ROOT/.venv"
  fi
fi

if [ ! -x "$PYTHON_BIN" ] && command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v "$PYTHON_BIN")"
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python interpreter is not executable: $PYTHON_BIN" >&2
  exit 1
fi

if ! command -v "$HOST_PYTHON" >/dev/null 2>&1; then
  HOST_PYTHON="$PYTHON_BIN"
fi

echo "[verify_release] repo: $REPO_ROOT"
echo "[verify_release] python: $PYTHON_BIN"

"$PYTHON_BIN" -m pip install --quiet --upgrade pip '.[dev]'

PACKAGE_VERSION="$("$PYTHON_BIN" - <<'PY'
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"
WHEEL_PATH="dist/frontend_design_loop_mcp-${PACKAGE_VERSION}-py3-none-any.whl"
SDIST_PATH="dist/frontend_design_loop_mcp-${PACKAGE_VERSION}.tar.gz"

run_repo_check() {
  echo
  echo "[verify_release] $1"
  shift
  "$@"
}

run_repo_check "pytest" env PYTHONPATH=src "$PYTHON_BIN" -m pytest -q --import-mode=importlib
run_repo_check "offline preflight" env PYTHONPATH=src "$PYTHON_BIN" scripts/preflight_check.py
run_repo_check "stdio smoke" env PYTHONPATH=src "$PYTHON_BIN" scripts/smoke_mcp_stdio.py
run_repo_check "registry metadata check" "$PYTHON_BIN" scripts/check_registry_ready.py
run_repo_check "build" "$PYTHON_BIN" -m build --outdir dist
run_repo_check "twine check" "$PYTHON_BIN" -m twine check "$WHEEL_PATH" "$SDIST_PATH"

wheel_smoke() {
  local tmp_venv
  tmp_venv="$(mktemp -d "${TMPDIR:-/tmp}/fdl-wheel-XXXXXX")"
  echo
  echo "[verify_release] wheel smoke: $tmp_venv"
  "$HOST_PYTHON" -m venv "$tmp_venv"
  "$tmp_venv/bin/pip" install --quiet "$WHEEL_PATH"
  "$tmp_venv/bin/frontend-design-loop-mcp" --help
  "$tmp_venv/bin/frontend-design-loop-mcp" --version
  "$tmp_venv/bin/frontend-design-loop-setup"
  "$tmp_venv/bin/frontend-design-loop-setup" --check
}

sdist_smoke() {
  local tmp_venv
  tmp_venv="$(mktemp -d "${TMPDIR:-/tmp}/fdl-sdist-XXXXXX")"
  echo
  echo "[verify_release] sdist smoke: $tmp_venv"
  "$HOST_PYTHON" -m venv "$tmp_venv"
  "$tmp_venv/bin/pip" install --quiet "$SDIST_PATH"
  "$tmp_venv/bin/frontend-design-loop-mcp" --help
  "$tmp_venv/bin/frontend-design-loop-mcp" --version
  "$tmp_venv/bin/frontend-design-loop-setup"
  "$tmp_venv/bin/frontend-design-loop-setup" --check
}

github_pipx_smoke() {
  local tmp_root tmp_home tmp_pipx_home tmp_pipx_bin tmp_fake_bin tool
  if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx is required for the GitHub install smoke. Re-run with --skip-github-install or install pipx." >&2
    exit 1
  fi

  tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/fdl-pipx-XXXXXX")"
  tmp_home="$tmp_root/home"
  tmp_pipx_home="$tmp_root/pipx-home"
  tmp_pipx_bin="$tmp_root/pipx-bin"
  tmp_fake_bin="$tmp_root/fake-bin"
  mkdir -p "$tmp_home" "$tmp_pipx_home" "$tmp_pipx_bin" "$tmp_fake_bin"

  for tool in codex gemini droid opencode; do
    cat > "$tmp_fake_bin/$tool" <<'EOF'
#!/usr/bin/env sh
exit 0
EOF
    chmod +x "$tmp_fake_bin/$tool"
  done

  echo
  echo "[verify_release] github pipx smoke: $tmp_root"
  env \
    HOME="$tmp_home" \
    PIPX_HOME="$tmp_pipx_home" \
    PIPX_BIN_DIR="$tmp_pipx_bin" \
    PIPX_DEFAULT_PYTHON="$(command -v "$HOST_PYTHON")" \
    PATH="$tmp_fake_bin:$tmp_pipx_bin:$PATH" \
    pipx install "$GITHUB_INSTALL_SPEC"

  env \
    HOME="$tmp_home" \
    PIPX_HOME="$tmp_pipx_home" \
    PIPX_BIN_DIR="$tmp_pipx_bin" \
    PIPX_DEFAULT_PYTHON="$(command -v "$HOST_PYTHON")" \
    PATH="$tmp_fake_bin:$tmp_pipx_bin:$PATH" \
    "$tmp_pipx_bin/frontend-design-loop-mcp" --version

  env \
    HOME="$tmp_home" \
    PIPX_HOME="$tmp_pipx_home" \
    PIPX_BIN_DIR="$tmp_pipx_bin" \
    PIPX_DEFAULT_PYTHON="$(command -v "$HOST_PYTHON")" \
    PATH="$tmp_fake_bin:$tmp_pipx_bin:$PATH" \
    "$tmp_pipx_bin/frontend-design-loop-setup" --install-all-detected-clients --skip-client claude --doctor

  grep -q "frontend-design-loop-mcp" "$tmp_home/.codex/config.toml"
  grep -q "frontend-design-loop-mcp" "$tmp_home/.gemini/settings.json"
  grep -q "frontend-design-loop-mcp" "$tmp_home/.factory/mcp.json"
  grep -q "frontend-design-loop-mcp" "$tmp_home/.config/opencode/opencode.json"
}

wheel_smoke
sdist_smoke
if [ "$RUN_GITHUB_INSTALL" -eq 1 ]; then
  github_pipx_smoke
fi

echo
echo "[verify_release] release verification passed."
echo "[verify_release] publish command:"
echo "TWINE_USERNAME=__token__ TWINE_PASSWORD=\"\$PYPI_TOKEN\" \"$PYTHON_BIN\" -m twine upload \"$WHEEL_PATH\" \"$SDIST_PATH\""
