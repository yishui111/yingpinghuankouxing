@echo off
rem ============================================================
rem  MuseTalk lip-sync service - status check
rem ============================================================
cd /d "%~dp0"

echo.
echo ======== MuseTalk Status ========
docker ps --filter "name=musetalk" --format "  Container: {{.Names}}  {{.Status}}  (Ports: {{.Ports}})"
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://localhost:5000/api/health' -TimeoutSec 5; Write-Host ('  API health: OK  status=' + $r.status) } catch { Write-Host '  API health: not ready (container down or model still loading)' }"
echo ================================
