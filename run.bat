@echo off
setlocal enabledelayedexpansion
title CodeChef Autonomous Solver
echo ========================================================
echo         CodeChef Autonomous Course Solver
echo ========================================================
echo.

:: 1. Detect Python command
set "PY_CMD="

:: Check standard 'python'
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python"
    goto :PYTHON_FOUND
)

:: Check Windows Python Launcher 'py'
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py -3"
    goto :PYTHON_FOUND
)

:: Check common Python installation paths if not in PATH
for /d %%I in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%I\python.exe" (
        set "PY_CMD=%%I\python.exe"
        goto :PYTHON_FOUND
    )
)
for /d %%I in ("%ProgramFiles%\Python3*") do (
    if exist "%%I\python.exe" (
        set "PY_CMD=%%I\python.exe"
        goto :PYTHON_FOUND
    )
)

:PYTHON_NOT_FOUND
echo [ERROR] Python is not installed or not configured in your system PATH.
echo.

:: Check if winget is available to install Python automatically
winget --version >nul 2>&1
if %errorlevel% neq 0 goto :MANUAL_INSTALL

echo Windows Package Manager [winget] is available on this system.
set /p AUTO_INSTALL="Would you like to automatically install Python 3.12 now? [Y/N]: "
if /i not "!AUTO_INSTALL!"=="Y" goto :MANUAL_INSTALL

echo.
echo [INFO] Installing Python 3.12 via winget...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if !errorlevel! equ 0 (
    echo.
    echo [SUCCESS] Python 3.12 installed successfully!
    echo Please close this window and double-click run.bat again.
    pause
    exit /b 0
) else (
    echo [WARNING] Automatic installation failed or was cancelled.
)

:MANUAL_INSTALL
echo.
echo --------------------------------------------------------
echo How to install Python manually:
echo 1. Download Python 3.10+ from: https://www.python.org/downloads/
echo 2. IMPORTANT: On the first screen of the installer, check:
echo    [X] "Add python.exe to PATH"
echo --------------------------------------------------------
echo.
set /p OPEN_WEB="Open Python download page in your browser? [Y/N]: "
if /i "!OPEN_WEB!"=="Y" start https://www.python.org/downloads/
pause
exit /b 1

:PYTHON_FOUND
echo [INFO] Python found: %PY_CMD%
%PY_CMD% --version
echo.

:: 2. Check if .env exists
if exist ".env" goto :ENV_EXISTS
echo [SETUP] No .env file found. Creating from .env.example...
copy .env.example .env >nul
echo.
echo [ACTION REQUIRED] Please edit .env and insert your API key:
echo OpenRouter, Groq, or Gemini
echo.
notepad .env
pause

:ENV_EXISTS
:: 3. Setup Virtual Environment (isolates packages from global python)
if not exist ".venv" (
    echo [INFO] Initializing virtual environment in .venv...
    %PY_CMD% -m venv .venv
)

if exist ".venv\Scripts\python.exe" (
    set "RUN_PY=.venv\Scripts\python.exe"
) else (
    set "RUN_PY=%PY_CMD%"
)

:: 4. Install dependencies if needed
echo [INFO] Ensuring dependencies are installed...
%RUN_PY% -m pip install -r requirements.txt --quiet
%RUN_PY% -m playwright install chromium

echo.
echo ========================================================
echo [INFO] Starting solver...
echo ========================================================
%RUN_PY% main.py %*

pause


