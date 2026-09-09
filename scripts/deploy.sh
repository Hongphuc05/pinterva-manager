#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
export ENV_FILE

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy .env.example and set production values." >&2
  exit 2
fi

env_value() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"
}

require_value() {
  local key="$1" value
  value="$(env_value "$key")"
  if [[ -z "$value" || "$value" == *"replace-with"* || "$value" == *"USER:PASSWORD@HOST"* ]]; then
    echo "Set a real $key in $ENV_FILE before deployment." >&2
    exit 2
  fi
}

for key in DATABASE_URL REDIS_URL SECRET_KEY CORS_ORIGINS BACKEND_IMAGE BACKEND_VERSION; do
  require_value "$key"
done

deploy_with_tunnel="$(env_value DEPLOY_WITH_TUNNEL)"
if [[ "$deploy_with_tunnel" == "true" ]]; then
  require_value CLOUDFLARE_TUNNEL_TOKEN
fi

compose=(docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.yaml")
if [[ "$deploy_with_tunnel" == "true" ]]; then
  compose+=(--profile tunnel)
fi

echo "Pulling backend version $(env_value BACKEND_VERSION)..."
"${compose[@]}" pull

echo "Applying database migrations..."
migration_compose=("${compose[@]}" --profile migration)
"${migration_compose[@]}" run --rm migrate

echo "Starting services..."
"${compose[@]}" up -d

echo "Waiting for API health..."
for _ in $(seq 1 24); do
  if "${compose[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" >/dev/null 2>&1; then
    echo "Deployment healthy: $(env_value BACKEND_IMAGE):$(env_value BACKEND_VERSION)"
    "${compose[@]}" ps
    exit 0
  fi
  sleep 2
done

echo "Deployment failed health check. Inspect logs with ./scripts/logs.sh" >&2
"${compose[@]}" ps >&2 || true
exit 1
