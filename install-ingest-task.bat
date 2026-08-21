@echo off
title Kingdom War Room - watch the inbox automatically
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  This must run as administrator.
  echo  Close this window, RIGHT-CLICK install-ingest-task.bat and
  echo  choose "Run as administrator".
  echo.
  pause
  exit /b
)

for /f "delims=" %%P in ('where python 2^>nul') do set PY=%%P& goto gotpy
:gotpy
if "%PY%"=="" (
  echo.
  echo  Python was not found. Install it from
  echo  https://www.python.org/downloads/ and tick
  echo  "Add python.exe to PATH", then run this again.
  echo.
  pause
  exit /b
)

set MINUTES=%1
if "%MINUTES%"=="" set MINUTES=15

if not exist "inbox" mkdir "inbox"

echo.
echo  Python:        %PY%
echo  Checking every %MINUTES% minutes
echo  Inbox:         %~dp0inbox
echo.

rem A tiny wrapper so the task has somewhere to send its output.
> "%~dp0ingest-run.bat" echo @echo off
>> "%~dp0ingest-run.bat" echo cd /d "%~dp0"
>> "%~dp0ingest-run.bat" echo "%PY%" ingest.py ^>^> ingest.log 2^>^&1

rem schtasks wants a path with spaces wrapped in SINGLE quotes inside the
rem double-quoted /tr value. Backslash is not an escape character to cmd, so
rem the \" form some examples use arrives at schtasks as a broken path.
schtasks /delete /tn "Kingdom War Room Ingest" /f >nul 2>&1
schtasks /create /tn "Kingdom War Room Ingest" /tr "'%~dp0ingest-run.bat'" /sc minute /mo %MINUTES% /ru SYSTEM /rl HIGHEST /f
if errorlevel 1 goto failed

echo.
echo  ============================================
echo   The inbox is now watched automatically
echo  ============================================
echo.
echo  Drop the spreadsheet from Discord into:
echo     %~dp0inbox
echo.
echo  Within %MINUTES% minutes it is filed, uploaded and the file
echo  disappears from inbox\ - that is how you know it worked.
echo.
echo  Anything it says goes to:
echo     %~dp0ingest.log
echo.
echo  To run it right now:   schtasks /run /tn "Kingdom War Room Ingest"
echo  To stop watching:      schtasks /delete /tn "Kingdom War Room Ingest" /f
echo.
echo  NOTE: if the site has a password, this task needs it. Put it in
echo  password.txt next to ingest.py, or the uploads will be refused.
echo.
pause
exit /b

:failed
echo.
echo  The scheduled task could not be created - the line just above this
echo  says why. The usual reason is that this was not really run as
echo  administrator.
echo.
echo  You can always skip the task and run ingest.bat by hand after
echo  dropping a file in; the task only saves you that click.
echo.
pause
