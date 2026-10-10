@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-WordXmlProbe.ps1"
set "probe_result=%errorlevel%"
echo.
echo Probe finished with exit code %probe_result%.
echo Results are in the results folder beside this file.
pause
exit /b %probe_result%
