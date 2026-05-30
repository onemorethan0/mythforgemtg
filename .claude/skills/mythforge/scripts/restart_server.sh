#!/usr/bin/env bash
# Restart the Myth Forge FastAPI server so backend (Python) edits take effect.
# Kills whatever holds :8000, relaunches detached (logs to /tmp), polls /api/health.
# Run from the repo root.
set -u
LOG="${1:-/tmp/mythforge_restart.log}"

for pid in $(netstat -ano | grep ":8000" | grep LISTENING | awk '{print $5}' | sort -u); do
  taskkill //PID "$pid" //F //T >/dev/null 2>&1 || true
done
sleep 1

python server.py > "$LOG" 2>&1 &
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health 2>/dev/null || true)
  if [ "$code" = "200" ]; then echo "Myth Forge UP after ${i}s (log: $LOG)"; exit 0; fi
  sleep 1
done
echo "Server did not become healthy in 30s — check $LOG"; tail -n 20 "$LOG" 2>/dev/null
exit 1
