@echo off
rem ============================================================
rem  MuseTalk smoke test (read-only checks, safe to run anytime)
rem  Checks: Docker daemon / container status / API health
rem ============================================================
cd /d "%~dp0\.."

echo ======== MuseTalk Smoke Test ========
echo.
echo [1/3] Docker daemon ...
docker info >nul 2>&1 && echo   [OK] Docker daemon is running || echo   [FAIL] Docker is not running
echo.
echo [2/3] Container status ...
docker ps --filter "name=musetalk" --format "   {{.Names}}: {{.Status}}"
docker ps --filter "name=musetalk" --format "{{.Names}}" | findstr "musetalk" >nul && echo   [OK] Container is running || echo   [DOWN] Container is not running
echo.
echo [3/3] API health check ...
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://localhost:5000/api/health' -TimeoutSec 5; Write-Host ('   [OK] status=' + $r.status) } catch { Write-Host '   [DOWN] API not ready (model loading or not started)' }"
echo.
echo ======== Smoke Test Finished ========
