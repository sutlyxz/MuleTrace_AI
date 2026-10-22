@echo off
setlocal
chcp 65001 >nul
title MuleTrace AI Launcher
pushd "%~dp0"
if errorlevel 1 exit /b 1

if /i "%~1"=="docker" goto docker
set "LAUNCH_ARGS="
if "%~1"=="" goto python
if /i "%~1"=="--help" (
    set "LAUNCH_ARGS=--help"
    goto python
)
if /i "%~1"=="--no-browser" (
    set "LAUNCH_ARGS=--no-browser"
    goto python
)
echo [ERROR] Usage: run.bat [docker / --help / --no-browser]
set "RESULT=1"
goto cleanup

:python

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
    if not errorlevel 1 goto venv
)

for %%P in (python py python3 python3.14 python3.13 python3.12 python3.11) do (
    %%P -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
    if not errorlevel 1 (
        %%P -m scripts.run %LAUNCH_ARGS%
        goto finished
    )
)

echo [ERROR] Install Python 3.11+ or use run.bat docker with Docker Desktop.
set "RESULT=1"
goto cleanup

:venv
".venv\Scripts\python.exe" -m scripts.run %LAUNCH_ARGS%
goto finished

:docker
where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not installed. Install and start Docker Desktop.
    set "RESULT=1"
    goto cleanup
)
if not exist ".env" (
    copy /b ".env.example" ".env" >nul
    if errorlevel 1 (
        set "RESULT=1"
        goto cleanup
    )
)
docker compose --profile analysis up --build --force-recreate

:finished
set "RESULT=%ERRORLEVEL%"

:cleanup
popd
if not "%RESULT%"=="0" pause
exit /b %RESULT%
