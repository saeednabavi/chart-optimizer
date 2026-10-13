@echo off
chcp 65001 > nul
setlocal

echo ======================================================
echo  New Andicator - Chart
echo ======================================================
echo.

cd /d "%~dp0"

set "VENV_DIR=C:\venvs\new_andicator"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
rem Background data update while the chart is open: minutes between updates (0 = off)
set "AUTO_UPDATE_MINUTES=2"

if not exist "%VENV_PY%" (
  echo [ERROR] Venv not found: %VENV_PY%
  echo Run install.bat first.
  pause
  exit /b 1
)

if not exist "chart\app.py" (
  echo [ERROR] Missing chart\app.py
  pause
  exit /b 1
)

echo Using venv: %VENV_DIR%
echo Opening chart...
echo.

"%VENV_PY%" "chart\app.py"

echo.
pause
endlocal
