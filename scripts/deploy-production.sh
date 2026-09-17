#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
BUILD=false
WITH_TUNNEL=false

for arg in "$@"; do
  case "$arg" in
    --build) BUILD=true ;;
    --with-tunnel) WITH_TUNNEL=true ;;
    *)
      echo "Usage: $0 [--build] [--with-tunnel]" >&2
      exit 2
      ;;
  esac
done

# Building is explicit so this script cannot unexpectedly rebuild a release image.
if [[ "$BUILD" != true ]]; then
  echo "Refusing to deploy without --build. This prevents an accidental Docker rebuild." >&2
  exit 2
fi

if [[ "$WITH_TUNNEL" == true ]]; then
  ENV_FILE="$ENV_FILE" "$ROOT_DIR/scripts/production-preflight.sh" --with-tunnel
else
  ENV_FILE="$ENV_FILE" "$ROOT_DIR/scripts/production-preflight.sh"
fi

compose=(docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.production.yaml")
if [[ "$WITH_TUNNEL" == true ]]; then
  compose+=(--profile tunnel)
fi

"${compose[@]}" build
"${compose[@]}" up -d postgres redis
"${compose[@]}" --profile migration run --rm migrate
"${compose[@]}" up -d --no-build api celery-general celery-assignment celery-beat
if [[ "$WITH_TUNNEL" == true ]]; then
  "${compose[@]}" up -d --no-build cloudflared
fi

for _ in $(seq 1 30); do
  if "${compose[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" >/dev/null 2>&1; then
    echo "Deployment healthy: $(git -C "$ROOT_DIR" rev-parse --short HEAD)"
    "${compose[@]}" ps
    exit 0
  fi
  sleep 2
done

echo "API failed healthcheck. Inspect container logs before retrying." >&2
"${compose[@]}" ps >&2 || true
exit 1
