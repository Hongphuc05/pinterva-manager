#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
OUT="${1:?usage: db_backup.sh <output-file.dump>}"
pg_dump --format=custom --file="$OUT" --dbname="$DATABASE_URL"
echo "Backup written to $OUT"
