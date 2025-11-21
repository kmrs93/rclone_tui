#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(pwd)"
VENV="${REPO_ROOT}/.env"
SYMLINK="/usr/local/bin/rclone_tui"
LAUNCHER="${REPO_ROOT}/bin/rclone_tui.sh"

echo "[*] Creating virtual environment..."
python3 -m venv "${VENV}"

echo "[*] Installing requirements..."
"${VENV}/bin/pip" install -r requirements.txt

echo "[*] Ensuring launcher is executable..."
chmod +x "${LAUNCHER}"

echo "[*] Preparing log file (optional)..."
if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "[*] Escalating to sudo to write system files..."
  exec sudo "$0"
fi

touch /var/log/rclone_tui.log || true
chmod 600 /var/log/rclone_tui.log || true

echo "[*] Creating/refreshing system-wide symlink: ${SYMLINK}"
ln -sf "${LAUNCHER}" "${SYMLINK}"

echo "[*] Installation complete."
echo "Run: rclone_tui"
