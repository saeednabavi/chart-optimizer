@echo off
setlocal EnableExtensions
cd /d "%~dp0"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "DEST=backups\farayand%STAMP%"

if not exist "backups" mkdir "backups"
if exist "%DEST%" (
  echo ERROR: Destination already exists: %DEST%
  pause
  exit /b 1
)

echo ========================================
echo   Building hard copy
echo   Destination: %DEST%
echo ========================================
echo.

mkdir "%DEST%"

robocopy . "%DEST%" /E ^
  /XD backups data node_modules venv .venv __pycache__ .git dist .vite .pytest_cache ^
  /XF *.pyc *.log ^
  /NFL /NDL /NJH /NJS /NC /NS

set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERROR: robocopy failed with code %RC%.
  pause
  exit /b 1
)

echo.
echo Hard copy created:
echo   %CD%\%DEST%
echo.
pause
endlocal
