#!/bin/bash
set -e
mkdir -p /arena/logs

echo "[$(date -Iseconds)] The Pit exchange starting on port 7070" >> /arena/logs/service_exchange.log
python3 /app/app.py >> /arena/logs/service_exchange.log 2>&1 &

# Keep container alive
exec tail -f /dev/null
