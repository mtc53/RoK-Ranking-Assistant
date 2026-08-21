@echo off
title Open the firewall for Kingdom War Room
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  This must run as administrator.
  echo  Close this, RIGHT-CLICK open-firewall.bat, and choose
  echo  "Run as administrator".
  echo.
  pause
  exit /b
)

if not "%1"=="" goto oneport

echo.
echo  Opening the two ports a website uses:
echo     80   plain http  (also needed to renew the certificate)
echo    443   https       (the encrypted site)
echo.
call :open 80
call :open 443
goto after

:oneport
call :open %1
goto after

:after
echo.
echo  Done. If the site is still unreachable from outside, the block
echo  is your VPS provider's own firewall, not Windows. Log in to the
echo  Solid VPS control panel and allow inbound TCP on 80 and 443.
echo.
pause
exit /b

:open
netsh advfirewall firewall delete rule name="Kingdom War Room %1" >nul 2>&1
netsh advfirewall firewall add rule name="Kingdom War Room %1" dir=in action=allow protocol=TCP localport=%1 >nul
if errorlevel 1 (echo   port %1 FAILED) else (echo   port %1 open)
exit /b
