@echo off
title Alliance War Room - back to plain http
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  This must run as administrator.
  echo  Close this, RIGHT-CLICK disable-https.bat, choose
  echo  "Run as administrator".
  echo.
  pause
  exit /b
)

echo.
echo  Turning encryption off and going back to http on port 80.
echo.

rem Keep the certificate rather than destroying it, in case it is wanted later.
if not exist "https-disabled" mkdir "https-disabled"
set MOVED=0
for %%F in (*.pem) do (
  move /y "%%F" "https-disabled\" >nul 2>&1
  set MOVED=1
)
if exist "https-disabled\*.pem" (
  echo   certificate files moved to https-disabled\
) else (
  echo   no certificate files were here
)

rem win-acme's renewal task would put new certificates back and quietly
rem switch the site to https again, so it goes too.
set FOUND=0
for /f "tokens=1 delims=," %%T in ('schtasks /query /fo csv /nh 2^>nul ^| findstr /i "win-acme"') do (
  schtasks /delete /tn %%T /f >nul 2>&1
  echo   removed the certificate renewal task
  set FOUND=1
)

rem Restart whichever way the site is running.
schtasks /query /tn "Alliance War Room" >nul 2>&1
if errorlevel 1 goto manual

schtasks /end /tn "Alliance War Room" >nul 2>&1
timeout /t 3 >nul
schtasks /run /tn "Alliance War Room" >nul 2>&1
timeout /t 6 >nul
echo   background task restarted
echo.
echo  ============================================
echo   Your site is back at:
echo      http://rokwarroom.duckdns.org
echo   (use your own address if it differs)
echo  ============================================
echo.
echo  Give it a few seconds, then reload the page in your browser.
echo  If it still shows https, the browser is remembering - open it
echo  in a new Incognito window to be sure.
echo.
pause
exit /b

:manual
echo.
echo  ============================================
echo   Done. Now close the black start.bat window
echo   and run start.bat again.
echo  ============================================
echo.
echo  Your site goes back to:
echo     http://rokwarroom.duckdns.org
echo  (use your own address if it differs)
echo.
pause
