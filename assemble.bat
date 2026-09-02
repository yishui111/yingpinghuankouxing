@echo off
rem ==================================================
rem  YINGPINGHUANKOUXING - one-key preflight for big assets
rem  Guarantee flow: (A) copy original project folder
rem  with big assets (fastest), or (B) clone this repo
rem  then run this script; details: see DEPLOY.md top.
rem ==================================================
setlocal
cd /d "%~dp0"
set "MISSING=0"
echo Checking required big assets...
if exist "image.tar" (echo   OK   image.tar) else (echo   MISS image.tar ^& set MISSING=1)
echo.
if %MISSING%==0 (
  echo ALL big assets present. Run start.bat now.
) else (
  echo Some big assets missing. See DEPLOY.md (top section
  "Deployment guarantee") for download instructions.
)
pause
