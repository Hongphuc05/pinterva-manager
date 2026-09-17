#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
WITH_TUNNEL=false

if [[ "${1:-}" == "--with-tunnel" ]]; then
  WITH_TUNNEL=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--with-tunnel]" >&2
  exit 2
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy .env.production.example and set production values." >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker Engine and Docker Compose plugin are required." >&2
  exit 2
fi

value() {
  awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"
}

require_value() {
  local key="$1" current
  current="$(value "$key")"
  if [[ -z "$current" || "$current" == *"replace-with"* || "$current" == *"CHANGE_ME"* ]]; then
    echo "Set a real $key in $ENV_FILE." >&2
    exit 2
  fi
}

for key in APP_VERSION DATA_DIR BACKUP_DIR POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL REDIS_URL SECRET_KEY CORS_ORIGINS; do
  require_value "$key"
done

if [[ ! "$(value APP_VERSION)" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "APP_VERSION may contain only letters, digits, dots, underscores and hyphens." >&2
  exit 2
fi

release_ref="$(value APP_VERSION)"
head_commit="$(git -C "$ROOT_DIR" rev-parse HEAD)"
release_commit="$(git -C "$ROOT_DIR" rev-parse -q --verify "${release_ref}^{commit}" 2>/dev/null || true)"
if [[ -z "$release_commit" || "$release_commit" != "$head_commit" ]]; then
  echo "APP_VERSION must be a commit SHA or Git tag that resolves to the checked-out HEAD." >&2
  exit 2
fi

if [[ "$(value COOKIE_SECURE)" != "true" ]]; then
  echo "COOKIE_SECURE must be true in production." >&2
  exit 2
fi

if [[ "$(value CORS_ORIGINS)" != *"https://tacahu.fun"* ]]; then
  echo "CORS_ORIGINS must include https://tacahu.fun." >&2
  exit 2
fi

if [[ "$WITH_TUNNEL" == true ]]; then
  require_value CLOUDFLARE_TUNNEL_TOKEN
fi

DATA_DIR="$(value DATA_DIR)"
if [[ ! -d "$DATA_DIR" ]]; then
  echo "DATA_DIR does not exist: $DATA_DIR" >&2
  exit 2
fi

BACKUP_DIR="$(value BACKUP_DIR)"
if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "BACKUP_DIR does not exist: $BACKUP_DIR" >&2
  exit 2
fi

available_kb="$(df -Pk "$DATA_DIR" | awk 'NR == 2 { print $4 }')"
if [[ "${available_kb:-0}" -lt 5242880 ]]; then
  echo "At least 5 GiB free space is required under DATA_DIR; found ${available_kb:-0} KiB." >&2
  exit 2
fi

if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
  echo "Refusing production preflight from a modified worktree." >&2
  echo "Commit the intended release first." >&2
  exit 2
fi

compose=(docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.production.yaml")
if [[ "$WITH_TUNNEL" == true ]]; then
  compose+=(--profile tunnel)
fi

"${compose[@]}" config >/dev/null
echo "Production preflight passed for $(git -C "$ROOT_DIR" rev-parse --short HEAD)."
