#!/usr/bin/env bash
# ==============================================================================
# Bootstrap and manage sun-flat-yamada/dotfiles on WSL2 (Ubuntu), Linux & macOS
# Usage:
#   ./install.sh --dry-run
#   ./install.sh --profile full
#   ./install.sh --status
#   ./install.sh --doctor
#   ./install.sh --validate
#   ./install.sh --rollback --backup-dir ~/.dotfiles-backup/<timestamp>
# ==============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_SCRIPT="${REPO_ROOT}/scripts/dotfiles.py"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[!] Error: python3 is required to run ${ENGINE_SCRIPT}" >&2
  exit 1
fi

case "${1:-}" in
  --validate|validate)
    shift
    exec "$PYTHON_BIN" "$ENGINE_SCRIPT" validate "$@"
    ;;
  --doctor|doctor)
    shift
    exec "$PYTHON_BIN" "$ENGINE_SCRIPT" doctor "$@"
    ;;
  --status|status)
    shift
    exec "$PYTHON_BIN" "$ENGINE_SCRIPT" status "$@"
    ;;
  --rollback|rollback)
    shift
    exec "$PYTHON_BIN" "$ENGINE_SCRIPT" rollback "$@"
    ;;
  *)
    exec "$PYTHON_BIN" "$ENGINE_SCRIPT" install "$@"
    ;;
esac
