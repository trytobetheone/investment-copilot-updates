@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Investment Committee Copilot - Local AI Setup

echo =============================================================
echo  Investment Committee Copilot - LOCAL AI Setup
echo =============================================================
echo.
echo Recommended for this PC: Qwen3 8B, GGUF Q4_K_M, context 8192.
echo Approximate model download: several GB. Close games such as NIKKE first.
echo.

where lms >nul 2>&1
if errorlevel 1 goto :need_lmstudio

echo [1/4] LM Studio CLI found.
echo.
echo [2/4] Downloading recommended local model...
echo       qwen/qwen3-8b @ Q4_K_M
lms get qwen/qwen3-8b@q4_k_m --gguf
if errorlevel 1 (
  echo.
  echo Automatic model download did not complete.
  echo Open LM Studio ^> Discover and search for: qwen3 8b
  echo Choose a GGUF Q4_K_M / 4-bit variant, then run this helper again.
  pause
  exit /b 1
)

echo.
echo [3/4] Locating and loading the model with an 8192-token context...
set "MODELKEY="
for /f "usebackq delims=" %%M in (`powershell -NoProfile -Command "$raw = (lms ls --json ^| Out-String); $j = $raw ^| ConvertFrom-Json; if ($j.models) { $items = $j.models } else { $items = $j }; $m = $items ^| Where-Object { $_.modelKey -match 'qwen.*3.*8b' } ^| Select-Object -First 1; if ($m) { Write-Output $m.modelKey }"`) do set "MODELKEY=%%M"
if not defined MODELKEY (
  echo Could not identify the downloaded Qwen3 8B model key.
  echo Open LM Studio and load the model manually, then start the server.
  pause
  exit /b 1
)
echo Found model key: %MODELKEY%
lms unload --all >nul 2>&1
lms load "%MODELKEY%" --identifier investment-local --context-length 8192 --gpu 0.5
if errorlevel 1 (
  echo.
  echo Automatic load failed. In LM Studio, load the downloaded Qwen3 8B model manually.
  echo Recommended context length: 8192. GPU offload: about 50%%.
  pause
  exit /b 1
)

echo.
echo [4/4] Starting the local API server on port 1234...
lms server start
if errorlevel 1 (
  echo.
  echo Start the server manually in LM Studio: Developer ^> Start server.
  pause
  exit /b 1
)

echo.
echo =============================================================
echo  LOCAL AI is ready.
echo  Model identifier: investment-local
echo  API address: http://127.0.0.1:1234/v1
echo =============================================================
echo.
echo Return to Investment Committee Copilot ^> Settings:
echo   1. Choose LOCAL
echo   2. Click Local AI connection check
echo   3. Select investment-local
echo   4. Save AI engine settings
pause
exit /b 0

:need_lmstudio
echo LM Studio CLI was not found.
echo.
echo LM Studio must be installed and opened once before the lms command is available.
echo The official download page will open now.
echo.
start "" "https://lmstudio.ai/download"
echo After installing LM Studio, OPEN IT ONCE, close this window,
echo then run LOCAL_AI_SETUP.bat again.
pause
exit /b 2
