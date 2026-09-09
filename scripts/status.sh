#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
export ENV_FILE
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 2; }

env_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"; }
compose=(docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.yaml" --profile tunnel)

echo "Backend version: $(env_value BACKEND_IMAGE):$(env_value BACKEND_VERSION)"
"${compose[@]}" ps
if "${compose[@]}" exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read().decode())"; then
  echo "API health: ok"
else
  echo "API health: failed" >&2
  exit 1
fi
