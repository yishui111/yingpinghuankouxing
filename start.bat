@echo off
rem ============================================================
rem  MuseTalk lip-sync service - one-click start
rem  Requirements: Docker (Desktop) running + NVIDIA GPU driver
rem  First run auto-loads image.tar (about 5-10 minutes)
rem ============================================================
cd /d "%~dp0"

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Please start Docker Desktop first.
    exit /b 1
)

docker image inspect musetalk-platform-full >nul 2>&1
if errorlevel 1 (
    if exist "image.tar" (
        echo [FIRST RUN] Loading docker image from image.tar (5-10 min)...
        docker load -i "image.tar"
        if errorlevel 1 (
            echo [ERROR] Failed to load image.tar
            exit /b 1
        )
    ) else (
        echo [ERROR] image.tar not found in the project folder.
        echo Please download image.tar first - see README.md / DEPLOY.md.
        exit /b 1
    )
)

docker compose up -d
if errorlevel 1 (
    echo [ERROR] docker compose up failed. Check docker-compose.yml.
    exit /b 1
)

echo.
echo MuseTalk service started:
echo   Web console:   http://localhost:5000
echo   Health check:  http://localhost:5000/api/health
echo.
echo Model loading takes about 1-2 minutes, run status.bat to check.
echo Opening browser...
start "" "http://localhost:5000"
exit /b 0
