#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# rollback-server.sh — Quick Rollback to Previous Docker Image on Ubuntu PC
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ENV="${DEPLOY_ENV:-$ROOT_DIR/.env.deploy}"

if [[ -f "$DEPLOY_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$DEPLOY_ENV"
fi

SERVER_HOST="${SERVER_HOST:-}"
SERVER_USER="${SERVER_USER:-}"
SERVER_PORT="${SERVER_PORT:-22}"
SERVER_PATH="${SERVER_PATH:-/srv/tacahu}"
SSH_KEY="${SSH_KEY:-}"

TARGET_VERSION="${1:-}"

if [[ -z "$TARGET_VERSION" ]]; then
  echo "Usage: $0 <target-version-tag>"
  echo "Example: $0 a831f92"
  exit 1
fi

if [[ -z "$SERVER_HOST" || -z "$SERVER_USER" ]]; then
  echo "Error: SERVER_HOST and SERVER_USER must be set in $DEPLOY_ENV or environment." >&2
  exit 1
fi

SSH_OPTS=(-p "$SERVER_PORT" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
if [[ -n "$SSH_KEY" && -f "$SSH_KEY" ]]; then
  SSH_OPTS+=(-i "$SSH_KEY")
fi

SSH_CMD=(ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_HOST}")

echo "========================================================"
echo "⏪ Initiating Rollback to Version: tacahu-backend:${TARGET_VERSION}"
echo "   Target Server: ${SERVER_USER}@${SERVER_HOST}:${SERVER_PATH}"
echo "========================================================"

REMOTE_SCRIPT=$(cat <<EOF
set -euo pipefail
cd "${SERVER_PATH}"

IMAGE_NAME="tacahu-backend:${TARGET_VERSION}"

echo "==> Verifying image exists locally on server: \${IMAGE_NAME}..."
if ! docker image inspect "\${IMAGE_NAME}" >/dev/null 2>&1; then
  echo "❌ Error: Docker image \${IMAGE_NAME} not found on server!" >&2
  echo "Available tacahu-backend images:" >&2
  docker images "tacahu-backend" --format "table {{.Repository}}:{{.Tag}}\t{{.CreatedAt}}" >&2
  exit 2
fi

export APP_VERSION="${TARGET_VERSION}"
export APP_SOURCE_DIR="./app"
export DATA_DIR="./data"

COMPOSE_ARGS=(docker compose -f compose.yaml --env-file .env)

echo "==> Restarting services with rollback image \${IMAGE_NAME}..."
"\${COMPOSE_ARGS[@]}" up -d

echo "==> Waiting for API health check..."
HEALTHY=false
for i in \$(seq 1 30); do
  if "\${COMPOSE_ARGS[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" >/dev/null 2>&1; then
    HEALTHY=true
    break
  fi
  sleep 2
done

if [[ "\$HEALTHY" != "true" ]]; then
  echo "❌ API failed health check after rollback!" >&2
  "\${COMPOSE_ARGS[@]}" ps >&2
  exit 3
fi

echo "==> Current container status:"
"\${COMPOSE_ARGS[@]}" ps
EOF
)

"${SSH_CMD[@]}" "bash -s" <<< "$REMOTE_SCRIPT"

echo "========================================================"
echo "✅ Rollback to tacahu-backend:${TARGET_VERSION} completed successfully!"
echo "========================================================"
