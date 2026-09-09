#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy-server.sh — Deploy from Mac to 24/7 Ubuntu PC Server via rsync + SSH
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ENV="${DEPLOY_ENV:-$ROOT_DIR/.env.deploy}"

# 1. Load deployment configuration
if [[ -f "$DEPLOY_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$DEPLOY_ENV"
fi

SERVER_HOST="${SERVER_HOST:-}"
SERVER_USER="${SERVER_USER:-}"
SERVER_PORT="${SERVER_PORT:-22}"
SERVER_PATH="${SERVER_PATH:-/srv/tacahu}"
SSH_KEY="${SSH_KEY:-}"
DEPLOY_WITH_TUNNEL="${DEPLOY_WITH_TUNNEL:-false}"
EXTERNAL_API_URL="${EXTERNAL_API_URL:-}"

ALLOW_DIRTY=false
for arg in "$@"; do
  case "$arg" in
    --allow-dirty)
      ALLOW_DIRTY=true
      shift
      ;;
    *)
      ;;
  esac
done

# Validate required variables
if [[ -z "$SERVER_HOST" || -z "$SERVER_USER" ]]; then
  echo "Error: SERVER_HOST and SERVER_USER must be set in $DEPLOY_ENV or environment." >&2
  echo "See .env.deploy.example for guidance." >&2
  exit 1
fi

SSH_OPTS=(-p "$SERVER_PORT" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
if [[ -n "$SSH_KEY" && -f "$SSH_KEY" ]]; then
  SSH_OPTS+=(-i "$SSH_KEY")
fi

SSH_CMD=(ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_HOST}")

# 2. Check Git working tree and determine version
if ! git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: $ROOT_DIR is not a git repository." >&2
  exit 1
fi

GIT_SHA="$(git -C "$ROOT_DIR" rev-parse --short HEAD)"
IS_DIRTY=false
if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
  IS_DIRTY=true
fi

if [[ "$IS_DIRTY" == "true" ]]; then
  if [[ "$ALLOW_DIRTY" == "true" ]]; then
    APP_VERSION="${GIT_SHA}-dirty-$(date +%s)"
    echo "⚠️  WARNING: Deploying uncommitted changes! Version tagged as: $APP_VERSION"
  else
    echo "❌ Error: Working tree has uncommitted changes." >&2
    echo "   Commit changes or run with --allow-dirty to force deployment." >&2
    git -C "$ROOT_DIR" status --short >&2
    exit 2
  fi
else
  APP_VERSION="$GIT_SHA"
fi

echo "========================================================"
echo "🚀 Deploying Tacahu Ops Backend"
echo "   Target Server : ${SERVER_USER}@${SERVER_HOST}:${SERVER_PATH}"
echo "   Version Tag   : tacahu-backend:${APP_VERSION}"
echo "========================================================"

# 3. Test SSH connectivity
echo "🔍 Checking SSH connectivity to server..."
if ! "${SSH_CMD[@]}" "echo 'SSH connected successfully'" >/dev/null 2>&1; then
  echo "❌ Error: Cannot connect to ${SERVER_USER}@${SERVER_HOST} via SSH." >&2
  exit 3
fi

# Ensure server directories exist with proper write permissions for container user
"${SSH_CMD[@]}" "mkdir -p '${SERVER_PATH}/app' '${SERVER_PATH}/data/'{crawled_assets,order_assets,platform_data,playwright_evidence,chrome_profiles,redis} '${SERVER_PATH}/backups' && chmod -R 777 '${SERVER_PATH}/data/'{crawled_assets,order_assets,platform_data,playwright_evidence,chrome_profiles} 2>/dev/null || true"

# 4. Sync source code to staging directory using rsync
echo "📦 Syncing source files via rsync to ${SERVER_PATH}/app/..."

RSYNC_SSH="ssh -p ${SERVER_PORT}"
if [[ -n "$SSH_KEY" && -f "$SSH_KEY" ]]; then
  RSYNC_SSH+=" -i ${SSH_KEY}"
fi

rsync -avz --delete \
  -e "$RSYNC_SSH" \
  --exclude='.git/' \
  --exclude='.github/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.mypy_cache/' \
  --exclude='node_modules/' \
  --exclude='frontend/' \
  --exclude='.env*' \
  --exclude='logs/' \
  --exclude='backups/' \
  --exclude='dist/' \
  --exclude='build/' \
  --exclude='chrome-profile*' \
  --exclude='crawled_assets' \
  --exclude='order_assets' \
  --exclude='platform_data' \
  --exclude='playwright-evidence' \
  --exclude='credentials/' \
  --exclude='*.log' \
  --exclude='*.pid' \
  --exclude='*.db' \
  --exclude='*.dump' \
  --exclude='*.sql' \
  "${ROOT_DIR}/" \
  "${SERVER_USER}@${SERVER_HOST}:${SERVER_PATH}/app/"

# Sync compose.yaml and support scripts to server root
rsync -avz -e "$RSYNC_SSH" "${ROOT_DIR}/compose.yaml" "${SERVER_USER}@${SERVER_HOST}:${SERVER_PATH}/compose.yaml"

# 5. Remote Build & Deploy
echo "🔨 Building Docker image on server (using Docker layer cache)..."

"${SSH_CMD[@]}" "APP_VERSION='$APP_VERSION' DEPLOY_WITH_TUNNEL='$DEPLOY_WITH_TUNNEL' SERVER_PATH='$SERVER_PATH' bash -s" << 'EOF'
set -euo pipefail
cd "$SERVER_PATH"

if [[ ! -f .env ]]; then
  echo "❌ Error: Missing $SERVER_PATH/.env on server! Copy .env.example and set production secrets." >&2
  exit 4
fi

if grep -q "^APP_VERSION=" .env; then
  sed -i "s/^APP_VERSION=.*/APP_VERSION=${APP_VERSION}/" .env
else
  echo "APP_VERSION=${APP_VERSION}" >> .env
fi

export APP_VERSION="$APP_VERSION"
export APP_SOURCE_DIR="./app"
export DATA_DIR="./data"

mkdir -p "$DATA_DIR/crawled_assets" "$DATA_DIR/order_assets" "$DATA_DIR/platform_data" "$DATA_DIR/playwright-evidence" "$DATA_DIR/credentials"
chmod -R 777 "$DATA_DIR/crawled_assets" "$DATA_DIR/order_assets" "$DATA_DIR/platform_data" "$DATA_DIR/playwright-evidence" "$DATA_DIR/credentials" 2>/dev/null || true

COMPOSE_ARGS=(docker compose -f compose.yaml --env-file .env)
if [[ "$DEPLOY_WITH_TUNNEL" == "true" ]]; then
  COMPOSE_ARGS+=(--profile tunnel)
fi

echo "==> Building tacahu-backend:${APP_VERSION}..."
"${COMPOSE_ARGS[@]}" build
docker tag "tacahu-backend:${APP_VERSION}" tacahu-backend:latest 2>/dev/null || true

echo "==> Running Alembic migrations..."
MIGRATE_ARGS=(docker compose -f compose.yaml --env-file .env --profile migration)
"${MIGRATE_ARGS[@]}" run --rm migrate

echo "==> Starting / Updating containers..."
"${COMPOSE_ARGS[@]}" up -d --force-recreate

echo "==> Waiting for API health check..."
HEALTHY=false
for i in $(seq 1 30); do
  if "${COMPOSE_ARGS[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" >/dev/null 2>&1; then
    HEALTHY=true
    break
  fi
  sleep 2
done

if [[ "$HEALTHY" != "true" ]]; then
  echo "❌ API failed healthcheck after deployment!" >&2
  "${COMPOSE_ARGS[@]}" ps >&2
  exit 5
fi

echo "==> Deployment containers status:"
"${COMPOSE_ARGS[@]}" ps
EOF

# 6. External Health Check (Optional)
if [[ -n "$EXTERNAL_API_URL" ]]; then
  echo "🌐 Verifying external API via Cloudflare Tunnel: ${EXTERNAL_API_URL}/api/health..."
  EXTERNAL_OK=false
  for _ in $(seq 1 15); do
    if curl -sSf "${EXTERNAL_API_URL}/api/health" >/dev/null 2>&1; then
      EXTERNAL_OK=true
      break
    fi
    sleep 2
  done

  if [[ "$EXTERNAL_OK" == "true" ]]; then
    echo "✅ External health check passed: ${EXTERNAL_API_URL}/api/health (HTTP 200)"
  else
    echo "⚠️  Warning: Internal deployment succeeded, but external URL ${EXTERNAL_API_URL}/api/health is not responding yet."
  fi
fi

echo "========================================================"
echo "🎉 SUCCESS: Version tacahu-backend:${APP_VERSION} deployed successfully!"
echo "========================================================"
