@echo off
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
  echo Run windows\setup.cmd first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -e ".[captcha]"
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\setup_captcha.py
if errorlevel 1 goto failed
echo Auto-login components installed. Configure JACCOUNT_USERNAME and JACCOUNT_PASSWORD in .env.
pause
exit /b 0
:failed
echo Auto-login setup failed. Manual login is still available.
pause
exit /b 1
