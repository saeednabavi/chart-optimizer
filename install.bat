@echo off
chcp 65001 > nul
setlocal EnableExtensions EnableDelayedExpansion

echo ======================================================
echo  New Andicator - Install
echo ======================================================
echo.

cd /d "%~dp0"

set "VENV_DIR=C:\venvs\new_andicator"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

REM ---- Find any working CPython 3.8+ (do not call quoted "py") ----
REM Python 3.11.0's launcher breaks on: "py" -3 --version
REM and looks for Python311\py instead of python.exe.
set "PY_EXE="
set "PY_VER=0"

REM Unquoted "py" on purpose. Quoted "py" breaks the Python 3.11.0 launcher.
where py >nul 2>&1 && (
  for %%V in (3.14 3.13 3.12 3.11 3.10 3.9 3.8 3) do call :from_py_ver %%V
)

for /f "tokens=2,*" %%A in ('reg query HKCU\Software\Python\PythonCore /s /v ExecutablePath 2^>nul') do (
  if /i "%%A"=="REG_SZ" call :try_exe "%%B"
)
for /f "tokens=2,*" %%A in ('reg query HKLM\Software\Python\PythonCore /s /v ExecutablePath 2^>nul') do (
  if /i "%%A"=="REG_SZ" call :try_exe "%%B"
)
for /f "tokens=2,*" %%A in ('reg query HKLM\Software\Wow6432Node\Python\PythonCore /s /v ExecutablePath 2^>nul') do (
  if /i "%%A"=="REG_SZ" call :try_exe "%%B"
)

call :scan_python_dirs "%LOCALAPPDATA%\Programs\Python"
call :scan_python_dirs "%ProgramFiles%"
call :scan_python_dirs "%ProgramFiles(x86)%"
call :scan_python_dirs "C:\"
call :scan_nested "%ProgramFiles%\Python"
call :scan_nested "%ProgramFiles(x86)%\Python"
call :scan_nested "%LOCALAPPDATA%\Programs\Python"

call :try_exe "%USERPROFILE%\anaconda3\python.exe"
call :try_exe "%USERPROFILE%\miniconda3\python.exe"
call :try_exe "%LOCALAPPDATA%\anaconda3\python.exe"
call :try_exe "%LOCALAPPDATA%\miniconda3\python.exe"
call :try_exe "%USERPROFILE%\miniforge3\python.exe"
call :try_exe "C:\ProgramData\anaconda3\python.exe"
call :try_exe "C:\ProgramData\miniconda3\python.exe"
for /d %%D in ("%USERPROFILE%\.pyenv\pyenv-win\versions\*") do (
  if exist "%%D\python.exe" call :try_exe "%%D\python.exe"
)

for /f "delims=" %%P in ('where python 2^>nul') do call :try_exe "%%P"
for /f "delims=" %%P in ('where python3 2^>nul') do call :try_exe "%%P"

if not defined PY_EXE (
  echo [ERROR] No working Python 3.8+ found.
  echo Install any Python 3.8 or newer from:
  echo   https://www.python.org/downloads/
  echo   Enable: Add python.exe to PATH
  pause
  exit /b 1
)

echo [1/4] System Python:
echo   !PY_EXE!
"!PY_EXE!" --version
if errorlevel 1 (
  echo [ERROR] Failed to run Python.
  pause
  exit /b 1
)

REM ---- Create parent folder + venv on C: ----
if not exist "C:\venvs" (
  echo Creating C:\venvs ...
  mkdir "C:\venvs"
)

if exist "%VENV_PY%" (
  echo [2/4] Virtual env already exists: %VENV_DIR%
) else (
  echo [2/4] Creating virtual env: %VENV_DIR%
  "!PY_EXE!" -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
  )
)

if not exist "%VENV_PY%" (
  echo [ERROR] Missing %VENV_PY%
  pause
  exit /b 1
)

echo [3/4] Upgrading pip inside env...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] Failed to upgrade pip.
  pause
  exit /b 1
)

if not exist "requirements.txt" (
  echo [ERROR] Missing requirements.txt
  pause
  exit /b 1
)

echo [4/4] Installing packages into env from requirements.txt ...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Failed to install packages.
  pause
  exit /b 1
)

echo.
echo Verifying dependencies...
"%VENV_PY%" -c "import requests, pandas; from Crypto.Cipher import AES; import lightweight_charts; print('OK: requests, pandas, pycryptodome, lightweight-charts')"
if errorlevel 1 (
  echo [ERROR] Dependencies incomplete.
  pause
  exit /b 1
)

echo.
echo ======================================================
echo  Install complete. Venv: %VENV_DIR%
echo  Next:
echo    download.bat
echo    run_chart.bat
echo ======================================================
echo.
pause
endlocal
exit /b 0

:from_py_ver
set "FOUND="
py -%~1 -c "import sys; print(sys.executable)" > "%TEMP%\new_andicator_pyexe.txt" 2>nul
if errorlevel 1 exit /b 0
set /p FOUND=<"%TEMP%\new_andicator_pyexe.txt"
if not defined FOUND exit /b 0
call :try_exe "!FOUND!"
exit /b 0

:scan_python_dirs
if not exist "%~1\" exit /b 0
for /d %%D in ("%~1\Python*") do (
  if exist "%%D\python.exe" call :try_exe "%%D\python.exe"
)
exit /b 0

:scan_nested
if not exist "%~1\" exit /b 0
for /d %%D in ("%~1\Python*") do (
  if exist "%%D\python.exe" call :try_exe "%%D\python.exe"
)
exit /b 0

:try_exe
set "CAND=%~1"
if "!CAND!"=="" exit /b 1
if not exist "!CAND!" exit /b 1
echo !CAND!| findstr /i "WindowsApps" >nul && exit /b 1
echo !CAND!| findstr /i /c:"%VENV_DIR%" >nul && exit /b 1
"!CAND!" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 8) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "CAND_VER="
"!CAND!" -c "import sys; print(sys.version_info[0] * 100 + sys.version_info[1])" > "%TEMP%\new_andicator_pyver.txt" 2>nul
set /p CAND_VER=<"%TEMP%\new_andicator_pyver.txt"
if not defined CAND_VER exit /b 1
if !CAND_VER! GTR !PY_VER! (
  set "PY_VER=!CAND_VER!"
  set "PY_EXE=!CAND!"
)
exit /b 0
