#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
WITH_TUNNEL=false
[[ "${1:-}" == "--with-tunnel" ]] && WITH_TUNNEL=true
[[ $# -le 1 ]] || { echo "Usage: $0 [--with-tunnel]" >&2; exit 2; }

compose=(docker compose --project-directory "$ROOT_DIR" --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.production.yaml")
[[ "$WITH_TUNNEL" == true ]] && compose+=(--profile tunnel)

"${compose[@]}" ps
"${compose[@]}" exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read().decode())"
