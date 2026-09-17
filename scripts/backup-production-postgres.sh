#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
# COMPOSE_FILE and POSTGRES_SERVICE make the script testable without touching a VPS.
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/compose.production.yaml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"

# shellcheck source=production-env.sh
source "$ROOT_DIR/scripts/production-env.sh"

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE." >&2; exit 2; }
command -v docker >/dev/null || { echo "Docker is required." >&2; exit 2; }
command -v flock >/dev/null || { echo "flock is required for single-writer backups." >&2; exit 2; }

POSTGRES_DB="$(production_require_value "$ENV_FILE" POSTGRES_DB)"
POSTGRES_USER="$(production_require_value "$ENV_FILE" POSTGRES_USER)"
BACKUP_ROOT="$(production_require_value "$ENV_FILE" BACKUP_DIR)"
RETENTION_DAYS="$(production_env_value "$ENV_FILE" BACKUP_RETENTION_DAYS)"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || { echo "BACKUP_RETENTION_DAYS must be a non-negative integer." >&2; exit 2; }

BACKUP_DIR="$BACKUP_ROOT/postgres"
mkdir -p "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || { echo "A PostgreSQL backup is already running." >&2; exit 3; }

compose=(docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_path="$BACKUP_DIR/tacahu-postgres-$timestamp.dump"
temporary_path="$(mktemp "$BACKUP_DIR/.tacahu-postgres-$timestamp.XXXXXX")"

cleanup() {
  [[ -e "$temporary_path" ]] && unlink "$temporary_path"
}
trap cleanup EXIT

"${compose[@]}" exec -T "$POSTGRES_SERVICE" \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --format=custom --no-owner --no-privileges > "$temporary_path"

[[ -s "$temporary_path" ]] || { echo "pg_dump returned an empty archive." >&2; exit 1; }
mv "$temporary_path" "$final_path"
trap - EXIT

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$final_path" > "$final_path.sha256"
else
  shasum -a 256 "$final_path" > "$final_path.sha256"
fi

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'tacahu-postgres-*.dump' -mtime "+$RETENTION_DAYS" -print -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'tacahu-postgres-*.dump.sha256' -mtime "+$RETENTION_DAYS" -print -delete

RCLONE_REMOTE="$(production_env_value "$ENV_FILE" BACKUP_OFFSITE_RCLONE_REMOTE)"
if [[ -n "$RCLONE_REMOTE" ]]; then
  command -v rclone >/dev/null || { echo "BACKUP_OFFSITE_RCLONE_REMOTE is set but rclone is unavailable." >&2; exit 1; }
  rclone copy "$final_path" "$RCLONE_REMOTE/postgres"
  rclone copy "$final_path.sha256" "$RCLONE_REMOTE/postgres"
fi

echo "PostgreSQL backup completed: $final_path"
