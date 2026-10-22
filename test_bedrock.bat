@echo off
setlocal
chcp 65001 >nul
title MuleTrace AI - Bedrock Connection Test
pushd "%~dp0"

echo ============================================================
echo   MuleTrace AI - One-Click Bedrock Setup ^& Test
echo ============================================================
echo.

set "PY_CMD="
for %%P in (python py python3) do (
    if not defined PY_CMD (
        %%P -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=%%P"
    )
)

if not defined PY_CMD (
    if exist ".venv\Scripts\python.exe" set "PY_CMD=.venv\Scripts\python.exe"
)

if not defined PY_CMD (
    echo [ERROR] Python 3.10+ was not found in PATH or .venv.
    pause
    popd
    exit /b 1
)

echo [*] Checking boto3 library...
%PY_CMD% -c "import boto3" >nul 2>&1
if errorlevel 1 (
    echo [*] boto3 is not installed. Installing boto3 now via pip...
    %PY_CMD% -m pip install boto3
    if errorlevel 1 (
        echo [ERROR] Failed to install boto3.
        pause
        popd
        exit /b 1
    )
    echo [+] boto3 installed successfully!
    echo.
) else (
    echo [+] boto3 is already installed.
    echo.
)

%PY_CMD% scripts\test_bedrock_connection.py

echo.
pause
popd
exit /b %ERRORLEVEL%
