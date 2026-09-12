@echo off
setlocal
rem simplon.cmd - the Windows entry point. Same parameters and the same
rem exec contract as simplon.sh; only the path separators differ.
rem
rem TWO ROUTES TO ONE CLI (si#199/si#201), the same pair the .sh offers: the
rem kernel is either Python in a venv on this host or a container, chosen with
rem DELIVERY_ROUTE and defaulting to `auto`. The container half of this file is
rem INHERITED rather than driven - there was no Windows on the machine si#201
rem was built on - and the two places it cannot be the .sh's are named where
rem they occur, below.
rem
rem The ensurepip/apt provisioning simplon.sh carries has no counterpart
rem here: the python.org and Store installers both ship a working venv module,
rem and there is no package manager to drive without a prompt. What DOES apply
rem is the broken-venv rebuild - an interrupted first run leaves the same
rem python-without-pip directory on any platform.

set "LAUNCH_PRODUCT=simplon"
set "LAUNCH_ROOT=%~dp0"
if "%LAUNCH_ROOT:~-1%"=="\" set "LAUNCH_ROOT=%LAUNCH_ROOT:~0,-1%"
set "LAUNCH_ORCH_DIR=%LAUNCH_ROOT%\deploy\orchestrator"
set "LAUNCH_MODULE=orchestrator"
rem The PUBLISHED KERNEL IMAGE this checkout runs on the container route (si#200), as a plain
rem line a shell can read before any Python exists. A checkout with no such file, or one whose
rem file carries no reference, has no container route.
set "LAUNCH_IMAGE_PIN=%LAUNCH_ROOT%\deploy\image\image.pin"

set "VENV=%LAUNCH_ORCH_DIR%\.venv"
set "REQ=%LAUNCH_ORCH_DIR%\requirements.txt"
set "STAMP=%VENV%\.deps-stamp"
set "VPY=%VENV%\Scripts\python.exe"
set "VPIP=%VENV%\Scripts\pip.exe"

rem WHERE THE ORCHESTRATOR IS EXPECTED - the same three paths simplon.sh checks, before anything
rem is provisioned, and for the same measured reason (#24): without it a missing block is either
rem manufactured by `python -m venv` or reported as "No module named orchestrator" with no path in the
rem message. The three `set` lines are separate statements, so the value is already there when the
rem block below is parsed - no delayed expansion needed.
set "ORCH_MISSING="
if not exist "%LAUNCH_ORCH_DIR%\" set "ORCH_MISSING=%LAUNCH_ORCH_DIR%"
if not defined ORCH_MISSING if not exist "%REQ%" set "ORCH_MISSING=%REQ%"
if not defined ORCH_MISSING if not exist "%LAUNCH_ORCH_DIR%\src\python\%LAUNCH_MODULE%\" set "ORCH_MISSING=%LAUNCH_ORCH_DIR%\src\python\%LAUNCH_MODULE%"
if defined ORCH_MISSING (
    >&2 echo simplon: no orchestrator here.
    >&2 echo simplon:   LAUNCH_ORCH_DIR = %LAUNCH_ORCH_DIR%
    >&2 echo simplon:   missing         = %ORCH_MISSING%
    >&2 echo simplon: the block holds requirements.txt and src\python\%LAUNCH_MODULE%. If it moved,
    >&2 echo simplon: point LAUNCH_ORCH_DIR ^(above, in this file^) at it, or write it again with
    >&2 echo simplon:   simplon init simplon --dir . --orch-dir ^<dir^> --force
    exit /b 1
)


rem --- WHICH ROUTE ---------------------------------------------------------------------------------
rem
rem `venv` is what this launcher has always done. `container` runs the pinned kernel image with this
rem checkout bind-mounted at /src. `auto`, the default, prefers the venv, so a host with a python keeps
rem the behaviour it had before si#201.
if not defined DELIVERY_ROUTE set "DELIVERY_ROUTE=auto"
set "ROUTE_OK="
if /i "%DELIVERY_ROUTE%"=="venv" set "ROUTE_OK=1"
if /i "%DELIVERY_ROUTE%"=="container" set "ROUTE_OK=1"
if /i "%DELIVERY_ROUTE%"=="auto" set "ROUTE_OK=1"
if /i "%DELIVERY_ROUTE%"=="inside" set "ROUTE_OK=1"
if not defined ROUTE_OK (
    >&2 echo simplon: DELIVERY_ROUTE is "%DELIVERY_ROUTE%"; it is one of venv, container, auto, inside
    exit /b 1
)

rem ALREADY INSIDE THE KERNEL CONTAINER - the value a user never types, set by the container route on the
rem way in so that an AGGREGATE command's nested launcher call stays in this container instead of
rem deciding the route again. That branch runs on Linux whichever launcher started the container, so it
rem is here only for completeness of the contract.
if /i "%DELIVERY_ROUTE%"=="inside" (
    python -u -m %LAUNCH_MODULE% %*
    exit /b %ERRORLEVEL%
)

rem THE PIN, READ WITHOUT PYTHON - the whole reason si#200 put the image reference in a plain file
rem rather than under a manifest key. findstr drops comment and blank lines; the first line left is the
rem reference.
set "KERNEL_IMAGE="
if exist "%LAUNCH_IMAGE_PIN%" (
    for /f "usebackq delims=" %%L in (`findstr /r /v /c:"^[ 	]*#" /c:"^[ 	]*$" "%LAUNCH_IMAGE_PIN%"`) do (
        if not defined KERNEL_IMAGE set "KERNEL_IMAGE=%%L"
    )
)

if /i "%DELIVERY_ROUTE%"=="auto" (
    where python >nul 2>&1
    if errorlevel 1 ( set "DELIVERY_ROUTE=container" ) else ( set "DELIVERY_ROUTE=venv" )
)

if /i not "%DELIVERY_ROUTE%"=="container" goto :venv_route

rem --- THE CONTAINER ROUTE -------------------------------------------------------------------------
rem
rem UNDRIVEN, and this file says so rather than implying otherwise. There is no Windows on the machine
rem si#201 was built on, so what follows is the shell half of the same route translated into batch, held
rem against the .sh by tests/test_launch_container.py for the things that CAN be checked without a
rem Windows - the same parameters, the same mount destinations, the same environment names - and
rem inherited for the rest. That is the evidence split this repository already keeps for the CRLF policy
rem in `simplon.bootstrap.newline_for`.
if not defined KERNEL_IMAGE (
    >&2 echo simplon: the container route needs a published kernel image, and
    >&2 echo simplon:   %LAUNCH_IMAGE_PIN%
    >&2 echo simplon: names none. Until one is published and pinned there, this checkout has no
    >&2 echo simplon: container route; DELIVERY_ROUTE=venv is the one that works.
    exit /b 1
)
where docker >nul 2>&1
if errorlevel 1 (
    >&2 echo simplon: the container route needs the docker CLI, which is not on PATH.
    exit /b 1
)

rem THE BLOCK DIR IN THE CONTAINER'S COORDINATES. Substituted rather than derived, unlike the .sh: cmd
rem strips a prefix off a variable only through delayed expansion, and the file already carries the block
rem dir in two spellings for exactly that class of reason (see `_render_launcher`).
set "ORCH_IN_SRC=/src/deploy/orchestrator"

rem THE HOST ROOT IS A DRIVE PATH HERE, AND THE KERNEL CANNOT USE IT YET. `%LAUNCH_ROOT%` is `C:\...`,
rem and the kernel reading it back is running in a LINUX container, where nothing joins a drive-letter
rem path onto a POSIX one - so `simplon.hostpath` refuses it BY NAME and says to use DELIVERY_ROUTE=venv.
rem That is the third and largest of this file's undriven gaps, and it is stated rather than papered
rem over: what Docker Desktop's daemon accepts as a `-v` source from inside a Linux container is a
rem measurement, and there was no Windows to take it on. Until somebody does, the Windows container route
rem reaches the CLI and refuses at the first task that mounts anything.
rem
rem THE SOCKET. On Windows the engine is a named pipe, but a LINUX container reaches it through the
rem socket Docker Desktop keeps inside its own VM, which is why this is the same path the .sh mounts and
rem not //./pipe/docker_engine - that pipe is for Windows containers. Inherited, not driven.
set "DOCKER_ARGS=--rm --init -i"
if defined DELIVERY_CONTAINER_TTY set "DOCKER_ARGS=%DOCKER_ARGS% -t"
set "DOCKER_ARGS=%DOCKER_ARGS% -v /var/run/docker.sock:/var/run/docker.sock"
set "DOCKER_ARGS=%DOCKER_ARGS% -v "%LAUNCH_ROOT%:/src" -w /src"

rem NO --user, and that is the same decision `simplon.docker.user_args` already takes for every toolchain
rem container: a Windows bind mount carries no ownership to get wrong, and there is no host uid to map.
rem NO -t BY DEFAULT either, and this is the one place the two launchers really differ. cmd.exe cannot
rem answer whether it has a terminal, and `docker run -t` without one fails outright with "the input
rem device is not a TTY" - so a wrong guess breaks every piped and every CI run, while the cost of not
rem guessing is only that the TUI degrades to the headless renderer it already falls back to. Set
rem DELIVERY_CONTAINER_TTY=1 at an interactive prompt to get the TUI.

rem THE HOST PATH OF THE MOUNT, which is the whole of si#201: the kernel is about to start sibling
rem containers through that socket, and the daemon resolves their `-v` sources against the HOST.
set "DOCKER_ENV=-e "DELIVERY_HOST_ROOT=%LAUNCH_ROOT%" -e DELIVERY_MOUNT_ROOT=/src"
set "DOCKER_ENV=%DOCKER_ENV% -e DELIVERY_ROUTE=inside"
set "DOCKER_ENV=%DOCKER_ENV% -e "LAUNCH_PRODUCT=%LAUNCH_PRODUCT%" -e LAUNCH_ROOT=/src"
set "DOCKER_ENV=%DOCKER_ENV% -e "LAUNCH_ORCH_DIR=%ORCH_IN_SRC%" -e "LAUNCH_MODULE=%LAUNCH_MODULE%""
set "DOCKER_ENV=%DOCKER_ENV% -e PYTHONPATH=%ORCH_IN_SRC%/src/python"
set "DOCKER_ENV=%DOCKER_ENV% -e PYTHONUSERBASE=/src/build/container/python -e HOME=/tmp"

rem WHICH VARIABLES CROSS: the kernel's own namespace, this product's, and the handful a CI runner
rem speaks. The venv route inherits the caller's whole environment and this one inherits nothing, so the
rem set is named rather than left to be discovered.
for /f "usebackq tokens=1 delims==" %%N in (`set DELIVERY_ 2^>nul`) do call :forward %%N
for /f "usebackq tokens=1 delims==" %%N in (`set SIMPLON_ 2^>nul`) do call :forward %%N
for %%N in (CI NO_COLOR TERM TZ GITHUB_TOKEN) do call :forward %%N

rem THE PRODUCT'S OWN ORCHESTRATOR DEPENDENCIES, on the same condition the venv route uses. The image
rem carries the KERNEL and nothing of any product (si#200/si#121), so this checkout still provides its
rem own - into the mount under build/, never into the venv, because the two routes' interpreters differ
rem and a venv built by one is a broken interpreter symlink to the other.
set "CSTAMP=%LAUNCH_ROOT%\build\container\python\.deps-stamp"
python -c "import os,sys; s,r=sys.argv[1],sys.argv[2]; sys.exit(0 if os.path.exists(s) and os.path.getmtime(s)>=os.path.getmtime(r) else 1)" "%CSTAMP%" "%REQ%" 2>nul
if errorlevel 1 (
    if not exist "%LAUNCH_ROOT%\build\container\python" mkdir "%LAUNCH_ROOT%\build\container\python"
    docker run %DOCKER_ARGS% %DOCKER_ENV% "%KERNEL_IMAGE%" pip install --user -q --disable-pip-version-check --root-user-action=ignore --no-warn-script-location -r "%ORCH_IN_SRC%/requirements.txt" || exit /b 1
    docker run %DOCKER_ARGS% %DOCKER_ENV% "%KERNEL_IMAGE%" python -c "import pathlib,os; p=pathlib.Path('/src/build/container/python/.deps-stamp'); p.touch()" || exit /b 1
)

docker run %DOCKER_ARGS% %DOCKER_ENV% "%KERNEL_IMAGE%" python -u -m %LAUNCH_MODULE% %*
exit /b %ERRORLEVEL%

:forward
if /i "%~1"=="DELIVERY_ROUTE" goto :eof
if /i "%~1"=="DELIVERY_HOST_ROOT" goto :eof
if /i "%~1"=="DELIVERY_MOUNT_ROOT" goto :eof
if not defined %~1 goto :eof
set "DOCKER_ENV=%DOCKER_ENV% -e %~1"
goto :eof

:venv_route
where python >nul 2>&1
if errorlevel 1 (
    >&2 echo simplon: python is required ^(the orchestrator is host-Python^)
    exit /b 1
)

rem Create the venv on first use, and REBUILD it when it is broken. The condition is
rem pip, not the directory and not the interpreter: an interrupted first run leaves a
rem venv that has python.exe and no pip.exe, and a check on either of those would call
rem that healthy and then fail on the install below, every run, forever. Remove the
rem tree first so nothing half-built survives the rebuild - that takes the stamp with
rem it, which is what forces the fresh dependency install afterwards.
if not exist "%VPIP%" (
    if exist "%VENV%" rmdir /s /q "%VENV%"
    python -m venv "%VENV%"
)
if not exist "%VPIP%" (
    >&2 echo simplon: could not provision pip into %VENV%. Check that this Python
    >&2 echo simplon: has venv support: python -m ensurepip --version
    exit /b 1
)

rem cmd.exe cannot compare file times; Python can.
python -c "import os,sys; s,r=sys.argv[1],sys.argv[2]; sys.exit(0 if os.path.exists(s) and os.path.getmtime(s)>=os.path.getmtime(r) else 1)" "%STAMP%" "%REQ%"
if errorlevel 1 (
    "%VPIP%" install -q --disable-pip-version-check -r "%REQ%" || exit /b 1
    python -c "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()" "%STAMP%"
)

set "PYTHONPATH=%LAUNCH_ORCH_DIR%\src\python;%PYTHONPATH%"
"%VPY%" -u -m %LAUNCH_MODULE% %*
exit /b %ERRORLEVEL%
