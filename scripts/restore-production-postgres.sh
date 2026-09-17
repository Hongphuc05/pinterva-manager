#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/compose.production.yaml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"

if [[ $# -ne 2 || "$1" != "--confirm-restore" ]]; then
  echo "Usage: $0 --confirm-restore <path-to-postgres.dump>" >&2
  echo "This destroys current database contents. Restore only after taking a fresh backup." >&2
  exit 2
fi

DUMP_PATH="$2"
[[ -f "$DUMP_PATH" ]] || { echo "Backup archive not found: $DUMP_PATH" >&2; exit 2; }

# shellcheck source=production-env.sh
source "$ROOT_DIR/scripts/production-env.sh"
POSTGRES_DB="$(production_require_value "$ENV_FILE" POSTGRES_DB)"
POSTGRES_USER="$(production_require_value "$ENV_FILE" POSTGRES_USER)"

compose=(docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${compose[@]}" ps "$POSTGRES_SERVICE" >/dev/null

# Validate that the archive can be parsed before altering the live database.
cat "$DUMP_PATH" | "${compose[@]}" exec -T "$POSTGRES_SERVICE" pg_restore --list >/dev/null
cat "$DUMP_PATH" | "${compose[@]}" exec -T "$POSTGRES_SERVICE" \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --clean --if-exists --no-owner --no-privileges
echo "Database restore completed from: $DUMP_PATH"
