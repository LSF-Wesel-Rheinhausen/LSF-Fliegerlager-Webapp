#!/usr/bin/env bash
set -Eeuo pipefail

state_file="${DAST_STATE_FILE:-${RUNNER_TEMP:-/tmp}/dast-container-name}"
container_name="${DAST_CONTAINER_NAME:-lsf-webapp}"
health_url="${DAST_HEALTH_URL:-http://127.0.0.1:8000/healthz/}"
health_timeout_seconds="${DAST_HEALTH_TIMEOUT_SECONDS:-60}"
health_poll_seconds="${DAST_HEALTH_POLL_SECONDS:-2}"
image="${DAST_IMAGE:-lsf-webapp:test}"

case "$container_name" in
  ''|*[!a-zA-Z0-9_.-]*)
    echo "Invalid DAST container name" >&2
    exit 2
    ;;
esac
case "$health_timeout_seconds" in
  ''|*[!0-9]*)
    echo "DAST health timeout and poll interval must be non-negative integers" >&2
    exit 2
    ;;
esac
case "$health_poll_seconds" in
  ''|*[!0-9]*)
    echo "DAST health timeout and poll interval must be non-negative integers" >&2
    exit 2
    ;;
esac

write_state() {
  mkdir -p "$(dirname "$state_file")"
  printf '%s\n' "$container_name" > "$state_file"
}

read_state() {
  if [ -s "$state_file" ]; then
    IFS= read -r container_name < "$state_file"
  fi
}

start() {
  docker run -d \
    --name "$container_name" \
    -p 8000:8000 \
    -e DJANGO_DEBUG=0 \
    -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
    -e DJANGO_SECRET_KEY=test-only-zap-secret-with-more-than-fifty-characters-1234567890 \
    "$image" >/dev/null
  write_state
}

wait_for_health() {
  if [ ! -s "$state_file" ]; then
    echo "DAST application state is missing" >&2
    return 1
  fi
  read_state
  local deadline=$((SECONDS + health_timeout_seconds))
  while :; do
    if curl --fail --silent --show-error --max-time 2 "$health_url" >/dev/null; then
      return 0
    fi
    if ! running_state="$(docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null)"; then
      echo "DAST application stopped before health check succeeded" >&2
      return 1
    fi
    if [ "$running_state" != "true" ]; then
      echo "DAST application stopped before health check succeeded" >&2
      return 1
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "DAST health check timed out after ${health_timeout_seconds}s" >&2
      return 1
    fi
    sleep "$health_poll_seconds"
  done
}

cleanup() {
  read_state
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is unavailable during DAST cleanup" >&2
    return 1
  fi
  if docker inspect "$container_name" >/dev/null 2>&1; then
    docker rm -f "$container_name" >/dev/null
  fi
  rm -f "$state_file"
}

case "${1:-}" in
  start) start ;;
  wait) wait_for_health ;;
  cleanup) cleanup ;;
  *)
    echo "Usage: $0 {start|wait|cleanup}" >&2
    exit 2
    ;;
esac
