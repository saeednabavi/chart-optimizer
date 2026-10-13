@echo off
chcp 65001 > nul
setlocal

echo ======================================================
echo  New Andicator - Download Watchlist CSV
echo ======================================================
echo.

cd /d "%~dp0"

set "VENV_DIR=C:\venvs\new_andicator"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

if not exist "%VENV_PY%" (
  echo [ERROR] Venv not found: %VENV_PY%
  echo Run install.bat first.
  pause
  exit /b 1
)

if not exist "extract\fetch_watchlist.py" (
  echo [ERROR] Missing extract\fetch_watchlist.py
  pause
  exit /b 1
)

echo Using venv: %VENV_DIR%
echo.
echo Downloading all symbols / all timeframes / all adj modes...
echo ------------------------------------------------------

"%VENV_PY%" "extract\fetch_watchlist.py" --workers 8

echo.
echo ======================================================
echo  Download finished. Data: data\csv_data
echo ======================================================
echo.
pause
endlocal
