@echo off
rem Starts the Alif Zephyr installer. Usage: alif-setup install ^| verify ^| uninstall
rem -ExecutionPolicy Bypass: no "Security warning" prompt for files downloaded as a zip.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0alif-setup-windows.ps1" %*
exit /b %ERRORLEVEL%
