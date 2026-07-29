@echo off
cd /d "%~dp0"
title eBay Profit Calculator

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

echo Starting eBay profit calculator on http://localhost:8501
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',8501); exit 0}catch{exit 1}finally{$c.Dispose()}" >nul 2>&1
if errorlevel 1 (
    %PYTHON_CMD% -m streamlit run "%~dp0streamlit_app.py" --server.address 0.0.0.0 --server.port 8501
) else (
    echo Profit calculator is already running on port 8501. A duplicate was not started.
)
pause
