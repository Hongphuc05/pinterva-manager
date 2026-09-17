#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"

# shellcheck source=production-env.sh
source "$ROOT_DIR/scripts/production-env.sh"

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE." >&2; exit 2; }
command -v flock >/dev/null || { echo "flock is required for single-writer backups." >&2; exit 2; }

DATA_DIR="$(production_require_value "$ENV_FILE" DATA_DIR)"
BACKUP_ROOT="$(production_require_value "$ENV_FILE" BACKUP_DIR)"
RETENTION_DAYS="$(production_env_value "$ENV_FILE" BACKUP_RETENTION_DAYS)"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || { echo "BACKUP_RETENTION_DAYS must be a non-negative integer." >&2; exit 2; }

BACKUP_DIR="$BACKUP_ROOT/assets"
mkdir -p "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || { echo "An asset backup is already running." >&2; exit 3; }

sources=(crawled_assets order_assets platform_data playwright_evidence)
if [[ "$(production_env_value "$ENV_FILE" BACKUP_INCLUDE_CHROME_PROFILES)" == "true" ]]; then
  sources+=(chrome_profiles)
fi
for source_dir in "${sources[@]}"; do
  [[ -d "$DATA_DIR/$source_dir" ]] || { echo "Missing asset directory: $DATA_DIR/$source_dir" >&2; exit 2; }
done

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_path="$BACKUP_DIR/tacahu-assets-$timestamp.tar.gz"
temporary_path="$(mktemp "$BACKUP_DIR/.tacahu-assets-$timestamp.XXXXXX")"

cleanup() {
  [[ -e "$temporary_path" ]] && unlink "$temporary_path"
}
trap cleanup EXIT

tar --create --gzip --file="$temporary_path" --directory="$DATA_DIR" "${sources[@]}"
[[ -s "$temporary_path" ]] || { echo "Asset archive is empty." >&2; exit 1; }
mv "$temporary_path" "$final_path"
trap - EXIT

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$final_path" > "$final_path.sha256"
else
  shasum -a 256 "$final_path" > "$final_path.sha256"
fi

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'tacahu-assets-*.tar.gz' -mtime "+$RETENTION_DAYS" -print -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'tacahu-assets-*.tar.gz.sha256' -mtime "+$RETENTION_DAYS" -print -delete

RCLONE_REMOTE="$(production_env_value "$ENV_FILE" BACKUP_OFFSITE_RCLONE_REMOTE)"
if [[ -n "$RCLONE_REMOTE" ]]; then
  command -v rclone >/dev/null || { echo "BACKUP_OFFSITE_RCLONE_REMOTE is set but rclone is unavailable." >&2; exit 1; }
  rclone copy "$final_path" "$RCLONE_REMOTE/assets"
  rclone copy "$final_path.sha256" "$RCLONE_REMOTE/assets"
fi

echo "Asset backup completed: $final_path"
