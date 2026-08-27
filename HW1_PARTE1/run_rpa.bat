@echo off
cd /d "C:\Users\Beca1\Documents\GitHub\Data-science-2026-II\rpa_peoplesync"

if not exist output mkdir output

python rpa_peoplesync.py

echo.
echo Codigo de salida: %ERRORLEVEL%
pause
