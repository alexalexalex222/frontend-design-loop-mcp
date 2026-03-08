#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PY="${PYTHON:-python3}"

echo "[frontend-design-loop-mcp] repo: $REPO_ROOT"
echo "[frontend-design-loop-mcp] python: $PY"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.10+ and re-run." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[frontend-design-loop-mcp] creating venv (.venv)…"
  "$PY" -m venv .venv
fi

echo "[frontend-design-loop-mcp] installing package…"
.venv/bin/python -m pip install --force-reinstall '.[dev]' -q

SETUP_ARGS=(--doctor --smoke)

if [ "${FDL_SKIP_CLIENT_INSTALL:-0}" != "1" ]; then
  echo "[frontend-design-loop-mcp] installing detected client entries…"
  SETUP_ARGS=(--install-all-detected-clients --scope user "${SETUP_ARGS[@]}")
  if [ "${FDL_SKIP_CLAUDE_INSTALL:-0}" = "1" ]; then
    SETUP_ARGS=(--skip-client claude "${SETUP_ARGS[@]}")
  fi
  if [ "${FDL_SKIP_CODEX_INSTALL:-0}" = "1" ]; then
    SETUP_ARGS=(--skip-client codex "${SETUP_ARGS[@]}")
  fi
  if [ "${FDL_SKIP_GEMINI_INSTALL:-0}" = "1" ]; then
    SETUP_ARGS=(--skip-client gemini "${SETUP_ARGS[@]}")
  fi
  if [ "${FDL_SKIP_DROID_INSTALL:-0}" = "1" ]; then
    SETUP_ARGS=(--skip-client droid "${SETUP_ARGS[@]}")
  fi
  if [ "${FDL_SKIP_OPENCODE_INSTALL:-0}" = "1" ]; then
    SETUP_ARGS=(--skip-client opencode "${SETUP_ARGS[@]}")
  fi
else
  echo "[frontend-design-loop-mcp] client auto-install skipped; leaving config manual."
fi

echo "[frontend-design-loop-mcp] running setup/doctor flow…"
PYTHONPATH=src .venv/bin/python -m frontend_design_loop_mcp.setup "${SETUP_ARGS[@]}"

echo
echo "[frontend-design-loop-mcp] done."
echo
echo "Next:"
if [ "${FDL_SKIP_CLIENT_INSTALL:-0}" != "1" ]; then
  echo "1) Restart your client if it was already open, then use the MCP:"
  echo "   frontend_design_loop_eval"
else
  echo "1) Add the MCP server to your client:"
  echo "   PYTHONPATH=src .venv/bin/python -m frontend_design_loop_mcp.setup --install-all-detected-clients"
fi
echo
echo "2) Re-run the doctor/smoke any time:"
echo "   PYTHONPATH=src .venv/bin/python -m frontend_design_loop_mcp.setup --doctor --smoke"
echo
echo "3) Optional other client installs:"
echo "   PYTHONPATH=src .venv/bin/python -m frontend_design_loop_mcp.setup --install-codex"
echo "   PYTHONPATH=src .venv/bin/python -m frontend_design_loop_mcp.setup --install-gemini"
echo "   PYTHONPATH=src .venv/bin/python -m frontend_design_loop_mcp.setup --install-droid"
echo "   PYTHONPATH=src .venv/bin/python -m frontend_design_loop_mcp.setup --install-opencode"
