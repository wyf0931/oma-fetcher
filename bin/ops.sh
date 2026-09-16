#!/usr/bin/env bash
# Manage a local uvicorn instance without persisting runtime files in the repo.
set -euo pipefail

readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RUNTIME_DIR="${TMPDIR:-/tmp}/oma-fetcher"
PORT=7890

usage() {
  cat <<'EOF'
Usage: bin/ops.sh <start|stop|restart|status> [-p PORT]

Commands:
  start       Start OMA Fetcher in the background.
  stop        Stop the instance started for this port.
  restart     Stop then start the instance for this port.
  status      Show process and health status.

Options:
  -p PORT     Local port to manage (default: 7890).
  -h          Show this help text.
EOF
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }

while getopts ':p:h' option; do
  case "$option" in
    p) PORT="$OPTARG" ;;
    h) usage; exit 0 ;;
    :) die "Option -$OPTARG needs a value." ;;
    \?) die "Unknown option: -$OPTARG" ;;
  esac
done
shift $((OPTIND - 1))

COMMAND="${1:-}"
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) || die "Port must be between 1 and 65535."
[[ -n "$COMMAND" ]] || { usage; exit 1; }

PID_FILE="$RUNTIME_DIR/uvicorn-$PORT.pid"
LOG_FILE="$RUNTIME_DIR/uvicorn-$PORT.log"

read_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  cat "$PID_FILE"
}

is_running() {
  local pid
  pid="$(read_pid)" || return 1
  kill -0 "$pid" 2>/dev/null
}

remove_stale_pid() {
  if [[ -f "$PID_FILE" ]] && ! is_running; then
    rm -f "$PID_FILE"
  fi
}

start() {
  command -v uv >/dev/null 2>&1 || die "uv is required. Install it from https://docs.astral.sh/uv/"
  mkdir -p "$RUNTIME_DIR"
  remove_stale_pid
  if is_running; then
    info "OMA Fetcher is already running on port $PORT (PID $(read_pid))."
    return
  fi
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    die "Port $PORT is already in use by another process."
  fi

  info "Starting OMA Fetcher on http://127.0.0.1:$PORT"
  (
    cd "$ROOT_DIR"
    nohup uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >>"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
  )

  for _ in {1..20}; do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
      info "Ready (PID $(read_pid)). Logs: $LOG_FILE"
      return
    fi
    sleep 0.5
  done
  info "The process did not become healthy. Recent logs:"
  tail -n 40 "$LOG_FILE" 2>/dev/null || true
  stop || true
  die "OMA Fetcher failed to start."
}

stop() {
  remove_stale_pid
  if ! is_running; then
    info "OMA Fetcher is not running on port $PORT."
    return
  fi
  local pid
  pid="$(read_pid)"
  info "Stopping OMA Fetcher on port $PORT (PID $pid)"
  kill -TERM "$pid"
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      info "Stopped. Logs remain at $LOG_FILE"
      return
    fi
    sleep 0.5
  done
  die "Process $pid did not stop within 10 seconds; inspect $LOG_FILE."
}

restart() {
  stop
  start
}

status() {
  remove_stale_pid
  if ! is_running; then
    info "OMA Fetcher is stopped on port $PORT."
    return 1
  fi
  local pid
  pid="$(read_pid)"
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    info "OMA Fetcher is healthy on http://127.0.0.1:$PORT (PID $pid)."
  else
    info "OMA Fetcher process is running but health check is failing (PID $pid). Logs: $LOG_FILE"
    return 1
  fi
}

case "$COMMAND" in
  start) start ;;
  stop) stop ;;
  restart) restart ;;
  status) status ;;
  *) usage; die "Unknown command: $COMMAND" ;;
esac
