@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Investment Committee Copilot

if not exist ".venv\Scripts\python.exe" (
  echo First install has not been completed. Running install.bat...
  call install.bat
  if errorlevel 1 exit /b 1
)

echo.
echo Checking agent output schemas...
".venv\Scripts\python.exe" scripts\schema_preflight.py >nul 2>&1
if errorlevel 1 (
  echo Preflight self-check failed. Details:
  ".venv\Scripts\python.exe" scripts\schema_preflight.py
  echo.
  echo Send a screenshot of this window for diagnosis.
  pause
  exit /b 1
)

echo ================================================
echo  Investment Committee Copilot - Starting
echo ================================================
echo.
echo The browser will open automatically when the server is ready.
echo Please keep this window open while using the app.
echo.

".venv\Scripts\python.exe" -m streamlit run app.py ^
  --server.address 127.0.0.1 ^
  --server.port 8501 ^
  --server.headless false ^
  --server.showEmailPrompt false ^
  --browser.gatherUsageStats false

set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo The app stopped with error code %RC%.
  echo Send a screenshot of the messages above for diagnosis.
) else (
  echo The app has stopped.
)
pause
exit /b %RC%
