@echo off
REM Duplakattintasos belepesi pont. Minden kapcsolot atad az install.ps1-nek,
REM pl.:  install.bat -NoAdmin -SkipNav
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
