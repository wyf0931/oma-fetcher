#!/usr/bin/env bash
# Install and run OMA Fetcher on macOS using a published GHCR image.
# It never builds the image locally.
set -euo pipefail

readonly REPOSITORY_URL="https://github.com/wyf0931/oma-fetcher.git"
readonly DEFAULT_DIRECTORY="$HOME/oma-fetcher"
readonly DEFAULT_IMAGE="ghcr.io/wyf0931/oma-fetcher:latest"

info() { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
success() { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "This installer supports macOS only."

setup_brew_path() {
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    return
  fi
  info "Homebrew was not found; installing the official Homebrew distribution"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  setup_brew_path
  command -v brew >/dev/null 2>&1 || die "Homebrew installation completed but brew is not on PATH. Open a new terminal and run this script again."
}

ensure_formula() {
  local formula="$1"
  brew list --versions "$formula" >/dev/null 2>&1 || {
    info "Installing $formula"
    brew install "$formula"
  }
}

choose_colima_resources() {
  local cores memory_bytes memory_gib
  cores="$(sysctl -n hw.ncpu)"
  memory_bytes="$(sysctl -n hw.memsize)"
  memory_gib=$((memory_bytes / 1024 / 1024 / 1024))
  (( memory_gib >= 4 )) || die "At least 4 GiB of physical memory is required to reserve 2 GiB for Colima safely."

  # Leave capacity for macOS: half the CPU cores and memory, capped for a
  # lightweight single-service deployment, with the requested 1C/2GiB floor.
  COLIMA_CPUS="${COLIMA_CPUS:-$(( (cores + 1) / 2 ))}"
  (( COLIMA_CPUS < 1 )) && COLIMA_CPUS=1
  (( COLIMA_CPUS > 4 )) && COLIMA_CPUS=4
  COLIMA_MEMORY_GB="${COLIMA_MEMORY_GB:-$(( memory_gib / 2 ))}"
  (( COLIMA_MEMORY_GB < 2 )) && COLIMA_MEMORY_GB=2
  (( COLIMA_MEMORY_GB > 8 )) && COLIMA_MEMORY_GB=8
}

ensure_colima_running() {
  if colima status >/dev/null 2>&1; then
    success "Colima is already running; preserving its existing resource settings"
    return
  fi
  choose_colima_resources
  info "Starting Colima with ${COLIMA_CPUS} CPU(s) and ${COLIMA_MEMORY_GB} GiB memory"
  colima start --cpu "$COLIMA_CPUS" --memory "$COLIMA_MEMORY_GB"
}

compose_command=()
ensure_compose() {
  if docker compose version >/dev/null 2>&1; then
    compose_command=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    compose_command=(docker-compose)
  else
    ensure_formula docker-compose
    compose_command=(docker-compose)
  fi
}

prepare_source() {
  FETCHER_DIR="${FETCHER_DIR:-$DEFAULT_DIRECTORY}"
  if [[ -e "$FETCHER_DIR" && ! -d "$FETCHER_DIR/.git" ]]; then
    die "$FETCHER_DIR exists but is not an OMA Fetcher Git repository. Set FETCHER_DIR to another empty location."
  fi
  if [[ -d "$FETCHER_DIR/.git" ]]; then
    local origin
    origin="$(git -C "$FETCHER_DIR" remote get-url origin 2>/dev/null || true)"
    [[ "$origin" == "$REPOSITORY_URL" || "$origin" == "git@github.com:wyf0931/oma-fetcher.git" ]] || die "$FETCHER_DIR points to a different Git remote; refusing to overwrite it."
    info "Updating $FETCHER_DIR"
    git -C "$FETCHER_DIR" pull --ff-only origin main
  else
    info "Cloning OMA Fetcher into $FETCHER_DIR"
    git clone "$REPOSITORY_URL" "$FETCHER_DIR"
  fi
}

wait_for_health() {
  local health_url="http://127.0.0.1:${FETCHER_PORT}/healthz"
  for _ in {1..30}; do
    if curl -fsS "$health_url" >/dev/null; then
      success "OMA Fetcher is ready at $health_url"
      return
    fi
    sleep 2
  done
  "${compose_command[@]}" logs --tail=100 fetcher || true
  die "The service did not become healthy within 60 seconds."
}

main() {
  ensure_homebrew
  setup_brew_path
  ensure_formula git
  ensure_formula docker
  ensure_formula colima
  ensure_colima_running
  ensure_compose
  prepare_source

  FETCHER_PORT="${FETCHER_PORT:-7890}"
  if lsof -nP -iTCP:"$FETCHER_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    die "Port $FETCHER_PORT is already in use. Re-run with FETCHER_PORT=8003 or stop the conflicting service."
  fi

  export FETCHER_IMAGE="${FETCHER_IMAGE:-$DEFAULT_IMAGE}"
  export FETCHER_PORT
  info "Pulling published image $FETCHER_IMAGE (no local build)"
  (
    cd "$FETCHER_DIR"
    "${compose_command[@]}" pull
    "${compose_command[@]}" up -d --remove-orphans
  )
  wait_for_health
  printf '\nOpenAPI docs: http://127.0.0.1:%s/docs\n' "$FETCHER_PORT"
  printf 'Example: curl -sS http://127.0.0.1:%s/healthz | jq\n' "$FETCHER_PORT"
}

main "$@"
