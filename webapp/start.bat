@echo off
title Kingdom War Room
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 goto nopython
if not exist index.html goto nopage

set PORT=%1
if "%PORT%"=="" set PORT=80

echo.
echo  ============================================
echo   Kingdom War Room is starting on port %PORT%
echo  ============================================
echo.
echo   Leave this window OPEN. Closing it stops the site.
echo.
python server.py %1
echo.
echo  The server stopped. If it said "permission denied" or
echo  "address already in use", try a different port:
echo     start.bat 8000
pause
exit /b

:nopython
echo.
echo  Python is not installed on this machine.
echo.
echo   1. Go to  https://www.python.org/downloads/
echo   2. Download and run the Windows installer
echo   3. IMPORTANT: tick "Add python.exe to PATH" on the first screen
echo   4. Restart this window and run start.bat again
echo.
pause
exit /b

:nopage
echo.
echo  index.html is missing from this folder.
echo  It must sit right next to start.bat and server.py.
echo.
pause
exit /b
