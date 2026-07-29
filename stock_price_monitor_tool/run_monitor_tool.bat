@echo off
cd /d "%~dp0"
title Stock Price Monitor Tool

set "PYTHON_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    set "PYTHON_CMD=py"
    py --version >nul 2>&1
)

if errorlevel 1 (
    echo Python was not found or could not be started.
    echo Please install Python, then run this file again.
    pause
    exit /b 1
)

echo Starting stock price monitor tool on http://localhost:8504
%PYTHON_CMD% -m streamlit run "%CD%\streamlit_app.py" --server.port 8504
pause
