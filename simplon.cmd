@echo off
setlocal
rem simplon.cmd - the Windows entry point. Same four parameters and the
rem same exec contract as simplon.sh; only the path separators differ.

set "LAUNCH_PRODUCT=simplon"
set "LAUNCH_ROOT=%~dp0"
if "%LAUNCH_ROOT:~-1%"=="\" set "LAUNCH_ROOT=%LAUNCH_ROOT:~0,-1%"
set "LAUNCH_ORCH_DIR=%LAUNCH_ROOT%\orchestrator"
set "LAUNCH_MODULE=orchestrator"

set "VENV=%LAUNCH_ORCH_DIR%\.venv"
set "REQ=%LAUNCH_ORCH_DIR%\requirements.txt"
set "STAMP=%VENV%\.deps-stamp"
set "VPY=%VENV%\Scripts\python.exe"
set "VPIP=%VENV%\Scripts\pip.exe"

if not exist "%VPY%" python -m venv "%VENV%" || exit /b 1

rem cmd.exe cannot compare file times; Python can.
python -c "import os,sys; s,r=sys.argv[1],sys.argv[2]; sys.exit(0 if os.path.exists(s) and os.path.getmtime(s)>=os.path.getmtime(r) else 1)" "%STAMP%" "%REQ%"
if errorlevel 1 (
    "%VPIP%" install -q --disable-pip-version-check -r "%REQ%" || exit /b 1
    python -c "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()" "%STAMP%"
)

set "PYTHONPATH=%LAUNCH_ORCH_DIR%\src\python;%PYTHONPATH%"
"%VPY%" -u -m %LAUNCH_MODULE% %*
exit /b %ERRORLEVEL%
