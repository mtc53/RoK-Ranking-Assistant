@echo off
title Kingdom War Room - start automatically
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  This must run as administrator.
  echo  Close this window, RIGHT-CLICK install-autostart.bat and
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

echo Using Python at: %PY%
echo.

> "%~dp0service-run.bat" echo @echo off
>> "%~dp0service-run.bat" echo cd /d "%~dp0"
>> "%~dp0service-run.bat" echo "%PY%" server.py ^>^> server.log 2^>^&1

rem remove any task from before this was renamed, plus the current one

schtasks /delete /tn "Alliance War Room" /f >nul 2>&1

schtasks /delete /tn "Kingdom War Room" /f >nul 2>&1
schtasks /create /tn "Kingdom War Room" /tr "\"%~dp0service-run.bat\"" ^
  /sc onstart /ru SYSTEM /rl HIGHEST /f
if errorlevel 1 goto failed

echo.
echo  ============================================
echo   The site will now start by itself on boot
echo  ============================================
echo.
echo  Close any black start.bat window first, then press a key
echo  and it will start in the background right now.
echo.
pause
schtasks /run /tn "Kingdom War Room" >nul 2>&1
timeout /t 6 >nul

echo  Checking that it really came up...
"%PY%" -c "import socket,sys; s=socket.socket(); s.settimeout(3); sys.exit(0 if s.connect_ex(('127.0.0.1',443))==0 or s.connect_ex(('127.0.0.1',80))==0 else 1)"
if errorlevel 1 goto notup
echo.
echo  CONFIRMED - the site is running in the background.
echo  It will come back by itself after a reboot.
echo.
echo  Anything it prints goes to:
echo     %~dp0server.log
echo.
echo  To stop it:      schtasks /end /tn "Kingdom War Room"
echo  To remove it:    schtasks /delete /tn "Kingdom War Room" /f
echo.
pause
exit /b

:notup
echo.
echo  The task was created, but the site did not answer.
echo  Look in  %~dp0server.log  for the reason. The usual one is
echo  that a start.bat window is still open and holding the port -
echo  close it, then run:
echo     schtasks /run /tn "Kingdom War Room"
echo.
pause
exit /b

:failed
echo.
echo  The scheduled task could not be created.
echo.
pause
