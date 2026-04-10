#!/bin/bash
set -e
mkdir -p /arena/logs

echo "[$(date -Iseconds)] Fort SSH starting on port 9090" >> /arena/logs/service_b.log
node /app/app.js >> /arena/logs/service_b.log 2>&1 &

# Keep container alive
exec tail -f /dev/null
