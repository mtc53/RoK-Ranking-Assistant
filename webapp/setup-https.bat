@echo off
title Alliance War Room - turn on encryption
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  This must run as administrator.
  echo  Close this window, RIGHT-CLICK setup-https.bat and choose
  echo  "Run as administrator".
  echo.
  pause
  exit /b
)

if not exist "win-acme\wacs.exe" goto nowacs

set /p DOMAIN=Your web address (for example rokwarroom.duckdns.org): 
if "%DOMAIN%"=="" goto nodomain
set /p EMAIL=Your email (only used to warn you if the certificate expires): 

echo.
echo  Checking that %DOMAIN% reaches this machine...
echo  (start.bat must be running in another window right now)
echo.

win-acme\wacs.exe --target manual --host %DOMAIN% --validation filesystem ^
  --webroot "%~dp0." --store pemfiles --pemfilespath "%~dp0." ^
  --accepttos --emailaddress "%EMAIL%"

echo.
if exist "%DOMAIN%-key.pem" goto done
echo  No certificate was created. The usual reasons:
echo    - start.bat was not running, so the check could not reach the site
echo    - the address does not point at this machine yet
echo    - port 80 is not open to the internet
echo.
pause
exit /b

:done
echo  ============================================
echo   Certificate installed for %DOMAIN%
echo  ============================================
echo.
echo  Now close the black start.bat window and run start.bat again.
echo  The site moves to https:// and renews itself every 90 days.
echo.
pause
exit /b

:nowacs
echo.
echo  win-acme is not here yet. It is the free tool that gets the
echo  certificate. To install it:
echo.
echo    1. Go to  https://github.com/win-acme/win-acme/releases/latest
echo    2. Download the file ending in  x64.pluggable.zip
echo    3. Right-click it - Extract All
echo    4. Put the extracted files in a folder called  win-acme
echo       directly inside %~dp0
echo       so that this exists:  %~dp0win-acme\wacs.exe
echo    5. Run setup-https.bat again
echo.
pause
exit /b

:nodomain
echo.
echo  No address entered - nothing to do.
echo.
pause
