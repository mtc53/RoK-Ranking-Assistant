@echo off
title Kingdom War Room - diagnosis
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python is not installed, so nothing can run yet.
  echo  Get it from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" during install.
  echo.
  pause
  exit /b
)
python check.py
