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

data_dir="$(awk -F= '$1 == "DATA_DIR" { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE")"
work_note_assets_dir="$data_dir/private_work_note_assets"
existing_api_container="$("${compose[@]}" ps -q api 2>/dev/null || true)"

# Releases before private_work_note_assets was added kept pasted screenshots inside the API
# container. Preserve them before Compose recreates that container. Refuse ambiguous merges
# rather than overwrite attachment bytes that may already have been recovered manually.
if [[ -n "$existing_api_container" ]]; then
  existing_assets_mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/private_work_note_assets"}}{{.Source}}{{end}}{{end}}' "$existing_api_container")"
  if [[ -z "$existing_assets_mount" ]] \
    && docker exec "$existing_api_container" test -d /app/private_work_note_assets \
    && docker exec "$existing_api_container" sh -c 'find /app/private_work_note_assets -mindepth 1 -print -quit | grep -q .'; then
    if find "$work_note_assets_dir" -mindepth 1 -print -quit | grep -q .; then
      echo "Refusing to merge legacy work-note attachments into non-empty $work_note_assets_dir." >&2
      echo "Verify or merge the files manually before deploying." >&2
      exit 1
    fi
    echo "Preserving legacy private work-note attachments before API recreate..."
    docker cp "$existing_api_container:/app/private_work_note_assets/." "$work_note_assets_dir"
  fi
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
    release="$(awk -F= '$1 == "APP_VERSION" { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE")"
    release_dir="$data_dir/releases"
    mkdir -p "$release_dir"
    current="$(cat "$release_dir/current" 2>/dev/null || true)"
    if [[ -n "$current" && "$current" != "$release" ]]; then
      printf '%s\n' "$current" > "$release_dir/previous"
    fi
    printf '%s\n' "$release" > "$release_dir/current"
    echo "Deployment healthy: $release"
    "${compose[@]}" ps
    exit 0
  fi
  sleep 2
done

echo "API failed healthcheck. Inspect container logs before retrying." >&2
"${compose[@]}" ps >&2 || true
exit 1
