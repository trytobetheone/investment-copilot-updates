@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Investment Committee Copilot - Install

 echo ================================================
 echo  Investment Committee Copilot - First Install
 echo ================================================
 echo.
 echo Looking for an installed Python 3.11 - 3.14 runtime...
 echo.

set "PYEXE="
for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\find_python.ps1"`) do (
    if not defined PYEXE set "PYEXE=%%P"
)

if not defined PYEXE goto :python_not_found
if not exist "%PYEXE%" goto :python_not_found

 echo Python found:
 echo   %PYEXE%
"%PYEXE%" --version
if errorlevel 1 goto :python_not_found

 echo.
 echo [1/4] Creating virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo Existing virtual environment found. Reusing it.
) else (
    if exist ".venv" rmdir /s /q ".venv"
    "%PYEXE%" -m venv .venv
    if errorlevel 1 goto :fail
)

if not exist ".venv\Scripts\python.exe" goto :fail

 echo [2/4] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check
if errorlevel 1 goto :fail

 echo [3/4] Installing packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto :fail

 echo [4/4] Optional API key setup...
".venv\Scripts\python.exe" scripts\setup_key.py

 echo.
 echo ================================================
 echo  Installation complete.
 echo  From now on, double-click START_HERE.bat.
 echo ================================================
pause
exit /b 0

:python_not_found
 echo.
 echo ================================================
 echo  Python 3.11 - 3.14 was not detected.
 echo ================================================
 echo.
 echo This installer will NOT start another automatic Python download.
 echo The previous version could hang during that download.
 echo.
 echo If you already installed Python, close this window once,
 echo restart Windows, and double-click START_HERE.bat again.
 echo.
 echo Otherwise install the current 64-bit Python from python.org,
 echo then run START_HERE.bat again.
 echo.
 echo Opening the official Python download page...
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1

:fail
 echo.
 echo Installation failed. Review the messages above.
 echo You can send a screenshot of this window for diagnosis.
pause
exit /b 1
