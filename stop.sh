#!/bin/sh
# MuseTalk lip-sync service - one-click stop (Linux/macOS)
cd "$(dirname "$0")" || exit 1
docker compose stop
echo "[OK] MuseTalk container stopped (kept for fast restart)."
