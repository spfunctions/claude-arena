#!/bin/bash
set -e
mkdir -p /arena/logs

echo "[$(date -Iseconds)] Fort HTTP starting on port 8080" >> /arena/logs/service_a.log
python3 /app/app.py >> /arena/logs/service_a.log 2>&1 &

# Keep container alive
exec tail -f /dev/null
