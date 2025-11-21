#!/usr/bin/env bash
set -euo pipefail

# Hardcode repo root to your project path
REPO_ROOT="/home/kmrs93/projects/rclone-tui"

# Re-exec with sudo if not root
if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

# Use venv python if present; else system python
VENV="${REPO_ROOT}/.env"
if [ -x "${VENV}/bin/python" ]; then
  PY="${VENV}/bin/python"
else
  PY="$(command -v python3 || true)"
  if [ -z "${PY}" ]; then
    echo "python3 not found. Please install it."
    exit 1
  fi
fi

# Ensure rclone exists
if ! command -v rclone >/dev/null 2>&1; then
  echo "rclone not found on PATH. Please install rclone."
  exit 1
fi

# Run package with src on PYTHONPATH
export PYTHONPATH="${REPO_ROOT}/src"
exec "${PY}" -m rclone_tui "$@"
