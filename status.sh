#!/bin/sh
# MuseTalk lip-sync service - status check (Linux/macOS)
cd "$(dirname "$0")" || exit 1
echo ""
echo "======== MuseTalk Status ========"
docker ps --filter "name=musetalk" --format "  Container: {{.Names}}  {{.Status}}  (Ports: {{.Ports}})"
if command -v curl >/dev/null 2>&1; then
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:5000/api/health)
    if [ "$code" = "200" ]; then
        echo "  API health: OK (http 200)"
    else
        echo "  API health: not ready (container down or model still loading, http $code)"
    fi
else
    echo "  (curl not found - skip API health check)"
fi
echo "================================"
