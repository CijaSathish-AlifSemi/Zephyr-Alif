@echo off
rem Starts the Alif Zephyr installer. Usage: alif-setup install ^| verify ^| uninstall
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0alif-setup.ps1" %*
exit /b %ERRORLEVEL%
