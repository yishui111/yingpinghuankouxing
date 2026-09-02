@echo off
rem ============================================================
rem  MuseTalk lip-sync service - one-click stop
rem ============================================================
cd /d "%~dp0"

docker compose stop
echo [OK] MuseTalk container stopped (kept for fast restart).
