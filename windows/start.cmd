@echo off
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
  echo Run windows\setup.cmd first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m paperdownloader.cli desktop
if errorlevel 1 pause
