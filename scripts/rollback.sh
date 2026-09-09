#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || "$1" != sha-* ]]; then
  echo "Usage: ./scripts/rollback.sh sha-<known-good-commit>" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
export ENV_FILE
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 2; }

tmp_file="$(mktemp "${ENV_FILE}.XXXXXX")"
trap 'rm -f "$tmp_file"' EXIT
awk -v version="$1" '
  /^BACKEND_VERSION=/ { print "BACKEND_VERSION=" version; seen=1; next }
  { print }
  END { if (!seen) print "BACKEND_VERSION=" version }
' "$ENV_FILE" > "$tmp_file"
chmod 600 "$tmp_file"
mv "$tmp_file" "$ENV_FILE"
trap - EXIT

echo "Selected rollback version $1. Deploying it now..."
exec "$ROOT_DIR/scripts/deploy.sh"
