#!/usr/bin/env bash
# Unified control script for the two local stacks:
#   - ./waha/   WAHA WhatsApp API      http://localhost:3000
#   - ./.       Django API + dashboard http://localhost:8000 / http://localhost:3001
#
# Usage:
#   ./start-all.sh            start both stacks (builds the Clinic images)
#   ./start-all.sh logs       tail logs from both stacks
#   ./start-all.sh status     show container status for both stacks
#   ./start-all.sh stop       stop both stacks (data volumes are kept)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLINIC_DIR="$ROOT"
WAHA_DIR="$ROOT/waha"
NETWORK="clinic-waha-net"

usage() {
  sed -n '2,9p' "$0"
}

ensure_network() {
  if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    echo "Creating shared Docker network '$NETWORK'..."
    docker network create "$NETWORK"
  fi
}

start() {
  ensure_network
  echo "==> Starting WAHA (http://localhost:3000) ..."
  (cd "$WAHA_DIR" && docker compose up -d)
  echo "==> Starting Clinic (API :8000, dashboard :3001) ..."
  (cd "$CLINIC_DIR" && docker compose up -d --build)
  cat <<EOF

Both stacks are up.

  Dashboard : http://localhost:3001
  API docs  : http://localhost:8000/api/docs/
  WAHA UI   : http://localhost:3000/dashboard

First time only: open the WAHA UI and pair the session 'session_01' by
scanning the QR code. Patient appointment texts are sent from that number,
and patient replies arrive on the dashboard's Conversations page.

  $0 logs     follow both stacks
  $0 status   show container status
  $0 stop     stop both stacks
EOF
}

logs() {
  (cd "$WAHA_DIR" && docker compose logs -f) &
  local waha_pid=$!
  (cd "$CLINIC_DIR" && docker compose logs -f) &
  local clinic_pid=$!
  trap 'kill "$waha_pid" "$clinic_pid" 2>/dev/null || true' EXIT INT TERM
  wait
}

status() {
  echo "==> WAHA"
  (cd "$WAHA_DIR" && docker compose ps)
  echo "==> Clinic"
  (cd "$CLINIC_DIR" && docker compose ps)
}

stop() {
  (cd "$CLINIC_DIR" && docker compose down)
  (cd "$WAHA_DIR" && docker compose down)
}

case "${1:-start}" in
  start) start ;;
  logs) logs ;;
  status) status ;;
  stop) stop ;;
  -h|--help|help) usage ;;
  *) echo "Unknown command: $1" >&2; usage >&2; exit 1 ;;
esac
