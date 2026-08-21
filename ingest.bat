@echo off
title Kingdom War Room - upload a new scan
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 goto nopython

if not exist "inbox" mkdir "inbox"

echo.
echo  ============================================
echo   Uploading whatever is in the inbox folder
echo  ============================================
echo.

python ingest.py %*
set RESULT=%ERRORLEVEL%

echo.
if "%RESULT%"=="0" goto done
echo  It did not finish. The reason is in the message above.
echo.
echo  The usual ones:
echo    - the War Room site is not running
echo    - the password is wrong or missing
echo    - the file in inbox\ is not an activity export
echo.
pause
exit /b

:done
echo  Done. Reload the website to see it.
echo.
pause
exit /b

:nopython
echo.
echo  Python is not installed on this machine.
echo  Install it from https://www.python.org/downloads/ and tick
echo  "Add python.exe to PATH" on the first screen.
echo.
pause
exit /b
