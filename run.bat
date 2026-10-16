@echo off
title CodeChef Autonomous Solver
echo ========================================================
echo         CodeChef Autonomous Course Solver
echo ========================================================
echo.

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

:: Check if .env exists
if not exist ".env" (
    echo [SETUP] No .env file found. Creating from .env.example...
    copy .env.example .env >nul
    echo.
    echo [ACTION REQUIRED] Please edit .env and insert your API key:
    echo (OpenRouter, Groq, or Gemini)
    echo.
    notepad .env
    pause
)

:: Install dependencies if needed
echo [INFO] Ensuring dependencies are installed...
python -m pip install -r requirements.txt --quiet
python -m playwright install chromium

echo.
echo [INFO] Starting solver...
python main.py %*

pause
