#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not in PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running."
  exit 1
fi

get_container_id() {
  docker compose ps -q "$1" 2>/dev/null || true
}

is_container_running() {
  local container_id="$1"
  [ -n "$container_id" ] && [ "$(docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null || true)" = "true" ]
}

container_name() {
  local container_id="$1"
  docker inspect -f '{{.Name}}' "$container_id" 2>/dev/null | sed 's#^/##'
}

detect_uvicorn_log_level() {
  local container_id="$1"
  local cmd_json
  cmd_json="$(docker inspect -f '{{json .Config.Cmd}}' "$container_id" 2>/dev/null || true)"
  if echo "$cmd_json" | grep -Eiq -- '--log-level[= ]info'; then
    echo "INFO"
    return 0
  fi
  if echo "$cmd_json" | grep -Eiq -- '--log-level[= ]debug'; then
    echo "DEBUG"
    return 0
  fi
  if echo "$cmd_json" | grep -Eiq -- '--log-level[= ]warning'; then
    echo "WARNING"
    return 0
  fi
  if echo "$cmd_json" | grep -Eiq -- '--log-level[= ]error'; then
    echo "ERROR"
    return 0
  fi
  if echo "$cmd_json" | grep -Eiq -- '--log-level[= ]critical'; then
    echo "CRITICAL"
    return 0
  fi
  if echo "$cmd_json" | grep -Eiq -- '--log-level[= ]trace'; then
    echo "TRACE"
    return 0
  fi
  echo "INFO (default)"
}

db_id="$(get_container_id db)"
web_id="$(get_container_id web)"

if is_container_running "$db_id" && is_container_running "$web_id"; then
  db_name="$(container_name "$db_id")"
  web_name="$(container_name "$web_id")"
  echo "Project is already started. Running containers: ${db_name}, ${web_name}."
  echo "Web log level: $(detect_uvicorn_log_level "$web_id")"
  exit 0
fi

docker compose up -d --build

# Tag the newly built web image with a timestamp for rollback/audit
WEB_IMAGE="$(docker compose images web --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | head -n1)"
if [ -n "$WEB_IMAGE" ]; then
  TIMESTAMP_TAG="$(date +%Y%m%d-%H%M%S)"
  docker tag "$WEB_IMAGE" "${WEB_IMAGE%%:*}:${TIMESTAMP_TAG}"
  echo "Tagged image: ${WEB_IMAGE%%:*}:${TIMESTAMP_TAG}"
fi

web_id="$(get_container_id web)"
if [ -n "$web_id" ]; then
  echo "Web log level: $(detect_uvicorn_log_level "$web_id")"
fi
echo "Project started."
