#!/usr/bin/env bash
# Shared helpers for production-only scripts. This file is sourced, not executed.

production_root_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

production_env_value() {
  local env_file="$1" key="$2"
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$env_file"
}

production_require_value() {
  local env_file="$1" key="$2" value
  value="$(production_env_value "$env_file" "$key")"
  if [[ -z "$value" || "$value" == *"replace-with"* || "$value" == *"CHANGE_ME"* ]]; then
    echo "Set a real $key in $env_file." >&2
    return 1
  fi
  printf '%s' "$value"
}

production_compose_args() {
  local root_dir="$1" env_file="$2"
  printf '%s\0' docker compose --project-directory "$root_dir" --env-file "$env_file" -f "$root_dir/compose.production.yaml"
}

production_release_dir() {
  local env_file="$1" data_dir
  data_dir="$(production_require_value "$env_file" DATA_DIR)" || return 1
  printf '%s/releases' "$data_dir"
}
