@echo off
REM Ejecuta la extraccion de tipo de cambio SUNAT (TAREA 2.py) de forma
REM desatendida, para uso manual o via Task Scheduler.

SET SCRIPT_DIR=C:\Users\Beca1\Documents\GitHub\Data-science-2026-II

cd /d "%SCRIPT_DIR%"

py -3.14 "%SCRIPT_DIR%\TAREA 2.py" --inicio 2024-01 --salida tipo_cambio_sunat.xlsx

echo.
echo Codigo de salida: %ERRORLEVEL%
pause
