#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not in PATH."
  exit 1
fi

get_container_id() {
  docker compose ps -q "$1" 2>/dev/null || true
}

is_container_running() {
  local container_id="$1"
  [ -n "$container_id" ] && [ "$(docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null || true)" = "true" ]
}

db_id="$(get_container_id db)"
web_id="$(get_container_id web)"

if ! is_container_running "$db_id" && ! is_container_running "$web_id"; then
  echo "Project is already stopped."
  exit 0
fi

docker compose down
echo "Project stopped."
