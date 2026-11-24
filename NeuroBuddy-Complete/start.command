#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
# Keep data local; both services listen only on loopback.
for cmd in python3 node npm curl; do
  command -v "$cmd" >/dev/null || { echo "Missing $cmd. Install Python 3.11+ and Node.js 22.12+ (or 24 LTS)."; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
node -e 'const [a,b]=process.versions.node.split(".").map(Number); if (!(a===20&&b>=19||a===22&&b>=12||a>=24)) {console.error("Use Node 22.12+ or 24 LTS");process.exit(1)}'
for port in 5173 8765; do
  if command -v lsof >/dev/null && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is occupied. Stop the old NeuroBuddy/dev server (Ctrl+C) and run again."; exit 1
  fi
done
cd "$ROOT/neurobuddy-coach"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
cd "$ROOT/demo-site"
npm ci
BACKEND_PID=''; DEMO_PID=''
cleanup() { if [ -n "$DEMO_PID" ]; then kill "$DEMO_PID" 2>/dev/null || true; fi; if [ -n "$BACKEND_PID" ]; then kill "$BACKEND_PID" 2>/dev/null || true; fi; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$ROOT/neurobuddy-coach"
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765 & BACKEND_PID=$!
wait_ready() {
  local url="$1" pid="$2" i
  for i in $(seq 1 120); do
    if ! kill -0 "$pid" 2>/dev/null; then echo "Service stopped: $url"; return 1; fi
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "Service did not become ready: $url"; return 1
}
wait_ready http://127.0.0.1:8765/api/v2/health "$BACKEND_PID"
cd "$ROOT/demo-site"
# Run Vite directly so cleanup stops the actual server process.
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort & DEMO_PID=$!
wait_ready http://127.0.0.1:5173/ "$DEMO_PID"
echo 'Demo: http://127.0.0.1:5173/'
echo 'Coach: http://127.0.0.1:8765/#library'
echo 'Both are running. Press Ctrl+C to stop.'
if command -v open >/dev/null; then open http://127.0.0.1:5173/ || true; fi
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$DEMO_PID" 2>/dev/null; do sleep 2; done
echo 'A service stopped. See the errors above.'; exit 1
