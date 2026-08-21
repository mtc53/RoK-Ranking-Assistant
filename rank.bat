@echo off
cd /d "%~dp0"
python rank.py %*
if errorlevel 1 pause
