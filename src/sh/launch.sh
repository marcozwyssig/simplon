#!/usr/bin/env bash
#
# launch.sh - the product-agnostic host-venv bootstrap + exec launcher for the *ctl family
# (extracted verbatim from netctl's netctl.sh in netctl#592 Train C).
#
# A product ships a ~5-line shim that resolves its ROOT, exports the PYTHONPATH it wants, and execs
# this launcher with four parameters. The launcher owns ALL the generic host-venv bootstrap so the
# product shim carries none of it: it (1) requires python3, (2) bootstraps the host venv idempotently
# (the ensurepip probe, the apt pythonX.Y-venv self-install as root or via `sudo -n`, the get-pip.py
# fallback, the requirements.txt-stamp reinstall), and (3) execs `python -u -m <module> "$@"`. Nothing
# here is product-specific: the paths, the product name and the module all arrive as parameters.
#
# Parameters (env vars, so the product's command args stay clean in "$@"):
#   LAUNCH_PRODUCT   product name, used only as the stderr diagnostic prefix (e.g. "netctl")
#   LAUNCH_ROOT      the product repo root (the launcher cd's there before bootstrapping)
#   LAUNCH_ORCH_DIR  the orchestrator dir that holds the .venv and requirements.txt
#   LAUNCH_MODULE    the python module to exec (`python -u -m <module>`)
# PYTHONPATH is set + exported by the product shim and inherited here; "$@" are the command args.
#
set -euo pipefail

PRODUCT="${LAUNCH_PRODUCT:?launch.sh: LAUNCH_PRODUCT is required (product name for diagnostics)}"
ROOT="${LAUNCH_ROOT:?launch.sh: LAUNCH_ROOT is required (product repo root)}"
ORCH_DIR="${LAUNCH_ORCH_DIR:?launch.sh: LAUNCH_ORCH_DIR is required (dir holding .venv + requirements.txt)}"
MODULE="${LAUNCH_MODULE:?launch.sh: LAUNCH_MODULE is required (python module to exec)}"
cd "$ROOT"

VENV="$ORCH_DIR/.venv"

command -v python3 >/dev/null 2>&1 || { printf '%s: python3 is required (the orchestrator is host-Python)\n' "$PRODUCT" >&2; exit 1; }

# python3 must be able to CREATE a venv: Debian/Ubuntu strip ensurepip out of the core python3
# package (python3-venv carries it), so a bare host fails the bootstrap below with a half-created
# venv and a cryptic ensurepip stacktrace (netctl#475). Probe up front; on apt hosts with non-interactive
# sudo (CI runners) self-install the interpreter-matched venv package, otherwise die with the fix.
# This must live HERE, not in `install`: the orchestrator's install command itself needs the venv.
if ! python3 -m ensurepip --version >/dev/null 2>&1; then
    PYVENV_PKG="$(python3 -c 'import sys; print("python%d.%d-venv" % sys.version_info[:2])')"
    # Root (container CI runners typically run as root WITHOUT sudo) calls apt-get directly; a
    # non-root user needs non-interactive sudo. This keeps an EPHEMERAL runner container green:
    # it self-heals on every job instead of depending on a manual install that dies with the pod.
    APT=""
    if command -v apt-get >/dev/null 2>&1; then
        if [ "$(id -u)" = 0 ]; then APT="env";
        elif sudo -n true 2>/dev/null; then APT="sudo -n"; fi
    fi
    if [ -n "$APT" ]; then
        printf '%s: python3 venv support missing; installing %s via apt\n' "$PRODUCT" "$PYVENV_PKG" >&2
        $APT apt-get update -qq >/dev/null 2>&1 || true
        $APT DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$PYVENV_PKG" >/dev/null 2>&1 \
            || $APT DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv >/dev/null 2>&1 || true
    fi
    # Still missing (non-root without sudo, no apt, or a non-apt python): fall back to bootstrapping
    # pip into the venv via get-pip.py below - needs neither root nor apt, only network. The diag
    # tuple names WHY the apt path was skipped, so a CI log answers it without host access.
    if ! python3 -m ensurepip --version >/dev/null 2>&1; then
        printf '%s: ensurepip still missing (uid=%s apt=%s sudo=%s); bootstrapping pip via get-pip.py\n' \
            "$PRODUCT" \
            "$(id -u)" \
            "$(command -v apt-get >/dev/null 2>&1 && echo yes || echo no)" \
            "$(sudo -n true 2>/dev/null && echo yes || echo no)" >&2
        VENV_WITHOUT_PIP=1
    fi
fi

# Create the venv on first use; rebuild it when it is broken (an interrupted first run can leave the
# directory without pip, so a directory-only check would never self-heal). Deps (re)install only when
# requirements.txt is newer than the stamp; a rebuild drops the stamp, forcing a fresh install.
if [ ! -x "$VENV/bin/pip" ]; then
    rm -rf "$VENV"
    if [ -n "${VENV_WITHOUT_PIP:-}" ]; then
        # No ensurepip on the host python (netctl#475): create the venv shell without pip, then fetch pip
        # straight into it. Works unprivileged on any host with egress.
        python3 -m venv --without-pip "$VENV"
        curl -fsSL https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python" - -q || true
    else
        python3 -m venv "$VENV"
    fi
    [ -x "$VENV/bin/pip" ] || {
        printf '%s: could not provision pip into the venv. Install venv support: sudo apt install %s\n' \
            "$PRODUCT" \
            "$(python3 -c 'import sys; print("python%d.%d-venv" % sys.version_info[:2])')" >&2
        exit 1
    }
fi
if [ ! -f "$VENV/.deps-stamp" ] || [ "$ORCH_DIR/requirements.txt" -nt "$VENV/.deps-stamp" ]; then
    "$VENV/bin/pip" install -q --disable-pip-version-check -r "$ORCH_DIR/requirements.txt"
    touch "$VENV/.deps-stamp"
fi

# -u: unbuffered, so streamed output stays live + correctly ordered when piped (CI/nohup/tee).
exec "$VENV/bin/python" -u -m "$MODULE" "$@"
