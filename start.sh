#!/bin/sh
# ============================================================
#  MuseTalk lip-sync service - one-click start (Linux/macOS)
#  Requirements: docker engine running + NVIDIA GPU driver
#  First run auto-loads image.tar (about 5-10 minutes)
# ============================================================
cd "$(dirname "$0")" || exit 1

command -v docker >/dev/null 2>&1 || { echo "[ERROR] docker not found. Install Docker first."; exit 1; }
docker info >/dev/null 2>&1 || { echo "[ERROR] Docker daemon is not running."; exit 1; }

if ! docker image inspect musetalk-platform-full >/dev/null 2>&1; then
    if [ -f image.tar ]; then
        echo "[FIRST RUN] Loading docker image from image.tar (5-10 min)..."
        docker load -i image.tar || { echo "[ERROR] Failed to load image.tar"; exit 1; }
    else
        echo "[ERROR] image.tar not found in the project folder."
        echo "Please download image.tar first - see README.md / DEPLOY.md."
        exit 1
    fi
fi

docker compose up -d || { echo "[ERROR] docker compose up failed. Check docker-compose.yml."; exit 1; }

echo ""
echo "MuseTalk service started:"
echo "  Web console:   http://localhost:5000"
echo "  Health check:  http://localhost:5000/api/health"
echo ""
echo "Model loading takes about 1-2 minutes, run ./status.sh to check."
