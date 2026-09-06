#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
IN="${1:?usage: db_restore.sh <input-file.dump>}"
pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" "$IN"
echo "Restored from $IN"
