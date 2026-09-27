#!/usr/bin/env bash
# Run both halves of the app.
#
#   ./run.sh          start the API and the web app
#   ./run.sh --clean  clear Next's build cache first
#
# The optimiser is Python (OR-Tools, LightGBM) and the UI is Next.js, so two
# processes are unavoidable. Forgetting the Python one shows up in the browser
# as an opaque "Failed to fetch", which is why this exists.
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "--clean" ]]; then
  echo "clearing web/.next"
  rm -rf web/.next
fi

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "No .venv — run:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
if [[ ! -d web/node_modules ]]; then
  echo "Web deps missing — run:  npm --prefix web install" >&2
  exit 1
fi

for port in 8077 3000; do
  if lsof -ti:"$port" >/dev/null 2>&1; then
    echo "Port $port is already in use. Stop that process first:" >&2
    echo "  lsof -ti:$port | xargs kill" >&2
    exit 1
  fi
done

# SIGTERM, not SIGKILL. Killing Next mid-write leaves .next inconsistent and
# the next start fails with "Cannot find module './<n>.js'" — recoverable
# only by deleting the directory, which is what --clean is for.
cleanup() {
  echo
  echo "stopping…"
  kill -TERM 0 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "API  → http://localhost:8077"
# --reload: without it an edited endpoint keeps serving stale code,
# which looks exactly like the change not working.
.venv/bin/uvicorn src.api.app:app --port 8077 --host 127.0.0.1 --reload &

echo "App  → http://localhost:3000"
npm --prefix web run dev &

wait
