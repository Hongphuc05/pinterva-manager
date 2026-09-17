#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_USER="${DEPLOY_USER:-}"

[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo "Run this installer with sudo on the VPS." >&2; exit 2; }
[[ "$DEPLOY_USER" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || {
  echo "Set DEPLOY_USER to the Linux account that owns /srv/tacahu-ops." >&2
  exit 2
}

for unit in tacahu-postgres-backup.service tacahu-postgres-backup.timer tacahu-assets-backup.service tacahu-assets-backup.timer; do
  source="$ROOT_DIR/deploy/systemd/$unit"
  target="/etc/systemd/system/$unit"
  sed "s/__DEPLOY_USER__/$DEPLOY_USER/g" "$source" > "$target"
done

systemctl daemon-reload
systemctl enable --now tacahu-postgres-backup.timer tacahu-assets-backup.timer
systemctl list-timers --all 'tacahu-*-backup.timer'
