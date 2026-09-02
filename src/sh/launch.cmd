@echo off
REM launch.cmd - the Windows counterpart of launch.sh.
REM
REM Same contract, same four LAUNCH_* variables, same three jobs: (1) provision the host venv next to
REM the product's orchestrator requirements, (2) keep it fresh against requirements.txt, and (3) run
REM `python -u -m <module> %*`. It lives beside launch.sh because a product's shim should differ
REM between the two platforms by its extension and nothing else.
REM
REM It is far shorter than launch.sh: the whole ensurepip/apt/get-pip rescue there exists because some
REM Linux distributions ship python3 without venv support. The python.org installer for Windows always
REM carries venv and pip, so there is nothing to repair.
setlocal

if "%LAUNCH_PRODUCT%"=="" ( echo launch.cmd: LAUNCH_PRODUCT is required ^(product name for diagnostics^) 1>&2 & exit /b 1 )
if "%LAUNCH_ROOT%"=="" ( echo launch.cmd: LAUNCH_ROOT is required ^(product repo root^) 1>&2 & exit /b 1 )
if "%LAUNCH_ORCH_DIR%"=="" ( echo launch.cmd: LAUNCH_ORCH_DIR is required ^(dir holding .venv + requirements.txt^) 1>&2 & exit /b 1 )
if "%LAUNCH_MODULE%"=="" ( echo launch.cmd: LAUNCH_MODULE is required ^(python module to exec^) 1>&2 & exit /b 1 )

cd /d "%LAUNCH_ROOT%" || exit /b 1

set "VENV=%LAUNCH_ORCH_DIR%\.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "VPIP=%VENV%\Scripts\pip.exe"
set "REQ=%LAUNCH_ORCH_DIR%\requirements.txt"
set "STAMP=%VENV%\.deps-stamp"

REM The launcher is host-Python: it has to exist before anything else can be provisioned.
where python >nul 2>&1
if errorlevel 1 (
    echo %LAUNCH_PRODUCT%: python is required ^(the orchestrator is host-Python^); install it from python.org 1>&2
    exit /b 1
)

REM A venv without a usable pip is worse than none: rebuild rather than limp along with half of one.
if not exist "%VPIP%" (
    if exist "%VENV%" rmdir /s /q "%VENV%"
    python -m venv "%VENV%" || exit /b 1
)
if not exist "%VPIP%" (
    echo %LAUNCH_PRODUCT%: could not provision pip into %VENV% 1>&2
    exit /b 1
)

REM Reinstall when requirements.txt is newer than the stamp -- the same rule as launch.sh's
REM `[ requirements.txt -nt .deps-stamp ]`. Comparing timestamps in batch needs forfiles or robocopy
REM tricks that differ across Windows versions; python is guaranteed present by now, so it does the
REM comparison and the semantics stay identical on both platforms.
python -c "import os,sys; s,r=sys.argv[1],sys.argv[2]; sys.exit(0 if os.path.exists(s) and os.path.getmtime(s)>=os.path.getmtime(r) else 1)" "%STAMP%" "%REQ%"
if errorlevel 1 (
    "%VPIP%" install -q --disable-pip-version-check -r "%REQ%" || exit /b 1
    python -c "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()" "%STAMP%"
)

REM cmd has no exec: run it and hand the child's exit code back unchanged, so a failing command still
REM fails the caller's script.
"%VPY%" -u -m %LAUNCH_MODULE% %*
exit /b %ERRORLEVEL%
