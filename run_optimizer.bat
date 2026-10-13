@echo off
chcp 65001 > nul
setlocal

echo ======================================================
echo  New Andicator - Indicator Input Optimizer
echo ======================================================
echo.

cd /d "%~dp0"

set "VENV_DIR=C:\venvs\new_andicator"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
rem Background data update while the optimizer is open: minutes between updates (0 = off)
set "AUTO_UPDATE_MINUTES=2"

if not exist "%VENV_PY%" (
  echo [ERROR] Venv not found: %VENV_PY%
  echo Run install.bat first.
  pause
  exit /b 1
)

if not exist "optimizer\gui.py" (
  echo [ERROR] Missing optimizer\gui.py
  pause
  exit /b 1
)

"%VENV_PY%" -c "import optuna" >nul 2>&1
if errorlevel 1 (
  echo Installing optuna into the venv...
  "%VENV_PY%" -m pip install optuna
)

echo Using venv: %VENV_DIR%
echo Opening optimizer...
echo.

"%VENV_PY%" "optimizer\gui.py"

echo.
pause
endlocal
