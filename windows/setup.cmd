@echo off
cd /d "%~dp0.."
python -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\package.py
if errorlevel 1 goto failed
echo Setup complete. Run windows\start.cmd or windows\service.cmd.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.11+ with Add Python to PATH, then retry.
pause
exit /b 1
