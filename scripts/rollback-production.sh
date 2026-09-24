#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
WITH_TUNNEL=false
RELEASE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) RELEASE="${2:-}"; shift 2 ;;
    --with-tunnel) WITH_TUNNEL=true; shift ;;
    *) echo "Usage: $0 --release <image-tag> [--with-tunnel]" >&2; exit 2 ;;
  esac
done

[[ "$RELEASE" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid release tag." >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE." >&2; exit 2; }

# shellcheck source=production-env.sh
source "$ROOT_DIR/scripts/production-env.sh"
DATA_DIR="$(production_require_value "$ENV_FILE" DATA_DIR)"

if [[ "$WITH_TUNNEL" == true ]]; then
  ENV_FILE="$ENV_FILE" "$ROOT_DIR/scripts/production-preflight.sh" --with-tunnel
else
  ENV_FILE="$ENV_FILE" "$ROOT_DIR/scripts/production-preflight.sh"
fi

docker image inspect "tacahu-ops:$RELEASE" >/dev/null || {
  echo "Image tacahu-ops:$RELEASE is not present on this VPS." >&2
  exit 2
}

temporary_env="$(mktemp "${ENV_FILE}.rollback.XXXXXX")"
cleanup() { [[ -e "$temporary_env" ]] && unlink "$temporary_env"; }
trap cleanup EXIT
awk -v release="$RELEASE" '
  /^APP_VERSION=/ { print "APP_VERSION=" release; found=1; next }
  { print }
  END { if (!found) print "APP_VERSION=" release }
' "$ENV_FILE" > "$temporary_env"
chmod 600 "$temporary_env"

compose=(docker compose --project-directory "$ROOT_DIR" --env-file "$temporary_env" -f "$ROOT_DIR/compose.production.yaml")
[[ "$WITH_TUNNEL" == true ]] && compose+=(--profile tunnel)

# Application rollback deliberately does not run Alembic downgrade. Database schema
# changes require a tested restore plan, not an automated destructive downgrade.
"${compose[@]}" up -d --no-build api celery-general celery-assignment celery-compare celery-beat
[[ "$WITH_TUNNEL" == true ]] && "${compose[@]}" up -d --no-build cloudflared

for _ in $(seq 1 30); do
  if "${compose[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" >/dev/null 2>&1; then
    release_dir="$DATA_DIR/releases"
    mkdir -p "$release_dir"
    previous="$(cat "$release_dir/current" 2>/dev/null || true)"
    [[ -n "$previous" ]] && printf '%s\n' "$previous" > "$release_dir/previous"
    printf '%s\n' "$RELEASE" > "$release_dir/current"
    echo "Application rollback healthy: $RELEASE"
    exit 0
  fi
  sleep 2
done

echo "Rollback failed API healthcheck; inspect logs before another action." >&2
exit 1
