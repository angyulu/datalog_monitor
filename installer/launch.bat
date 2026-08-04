@echo off
setlocal
cd /d "%~dp0"

echo Checking for updates...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_check.ps1"

echo.
echo Starting Datalog Monitor -- your browser will open automatically.
echo Close this window to stop the app.
echo.
"%~dp0python\python.exe" -m streamlit run "%~dp0app.py"

endlocal
