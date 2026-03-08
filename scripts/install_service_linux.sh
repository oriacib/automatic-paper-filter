#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${1:-paper-watcher}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
USER_NAME="${SUDO_USER:-$USER}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat <<EOF | sudo tee "${SERVICE_FILE}" >/dev/null
[Unit]
Description=Paper Watcher Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_BIN} -m app.main daemon
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
echo "Installed and started systemd service: ${SERVICE_NAME}"
