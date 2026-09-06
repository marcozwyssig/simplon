#!/usr/bin/env bash
#
# simplon.sh - the simplon entry point.
#
# It declares simplon's four parameters, provisions the host venv, and
# execs the CLI. The kernel arrives as an ordinary dependency (simplon on
# PyPI), so there is nothing to vendor and no submodule to init: a fresh
# clone plus this script is the whole setup.
#
# Provisioning is written to survive a BARE host, because that is what a fresh
# CI runner is: it requires python3, makes sure that python3 can actually
# create a venv (Debian and Ubuntu ship one that cannot), and rebuilds a venv
# that a previous run left half-finished.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

LAUNCH_PRODUCT=simplon
LAUNCH_ROOT="$ROOT"
LAUNCH_ORCH_DIR="$ROOT/deploy/orchestrator"
LAUNCH_MODULE=orchestrator

VENV="$LAUNCH_ORCH_DIR/.venv"
REQ="$LAUNCH_ORCH_DIR/requirements.txt"
STAMP="$VENV/.deps-stamp"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

# WHERE THE ORCHESTRATOR IS EXPECTED, checked before anything is provisioned. LAUNCH_ORCH_DIR is a
# PARAMETER (#4), so pointing it at nothing is an ordinary mistake and not a hypothetical: a
# half-finished move, a partial checkout, a value edited by hand. Measured with this check removed
# (#24): with the directory gone, `python3 -m venv` CREATES it and pip then complains about a missing
# requirements file -- the launcher manufactures the very directory it was supposed to find; with the
# sources gone, python answers "No module named orchestrator" and names no path at all. Both are
# failures that decline to say what they already know, and this file knows exactly where it looked.
# So it says so, names every path it needed, and touches nothing on the way out.
for _needed in "$LAUNCH_ORCH_DIR" "$REQ" "$LAUNCH_ORCH_DIR/src/python/$LAUNCH_MODULE"; do
    [ -e "$_needed" ] || {
        printf '%s: no orchestrator here.\n' "$LAUNCH_PRODUCT" >&2
        printf '%s:   LAUNCH_ORCH_DIR = %s\n' "$LAUNCH_PRODUCT" "$LAUNCH_ORCH_DIR" >&2
        printf '%s:   missing         = %s\n' "$LAUNCH_PRODUCT" "$_needed" >&2
        printf '%s: the block holds requirements.txt and src/python/%s. If it moved, point\n' \
            "$LAUNCH_PRODUCT" "$LAUNCH_MODULE" >&2
        printf '%s: LAUNCH_ORCH_DIR (above, in this file) at it, or write it again with\n' "$LAUNCH_PRODUCT" >&2
        printf '%s:   simplon init %s --dir . --orch-dir <dir> --force\n' "$LAUNCH_PRODUCT" "$LAUNCH_PRODUCT" >&2
        exit 1
    }
done

command -v python3 >/dev/null 2>&1 || {
    printf '%s: python3 is required (the orchestrator is host-Python)\n' "$LAUNCH_PRODUCT" >&2
    exit 1
}

# Create the venv on first use, and REBUILD it when it is broken. The condition is
# pip, not the directory and not the interpreter: an interrupted first run leaves a
# venv that has python and no pip, and a check on either of those would call that
# healthy and then fail on the install below, every run, forever. `rm -rf` first so
# no half-built tree survives into the rebuild - it takes the stamp with it, which
# is what forces the fresh dependency install afterwards.
if [ ! -x "$PIP" ]; then
    rm -rf "$VENV"

    # python3 has to be able to CREATE a venv, which is not the same as being
    # installed. Debian and Ubuntu strip ensurepip out of the core python3 package
    # (python3-venv carries it), so a bare host gets a half-created venv and a
    # cryptic ensurepip stacktrace instead of an answer. Probe for it first, and
    # deal with its absence rather than reporting it.
    if ! python3 -m ensurepip --version >/dev/null 2>&1; then
        PYVENV_PKG="$(python3 -c 'import sys; print("python%d.%d-venv" % sys.version_info[:2])')"
        # Self-install the INTERPRETER-MATCHED venv package where apt can be driven
        # without a prompt. Root calls apt-get directly, because a container runner
        # is usually root WITHOUT sudo installed; a non-root user needs `sudo -n`,
        # which fails silently rather than blocking on a password. This is what keeps
        # an EPHEMERAL runner green: it heals itself on every job instead of relying
        # on a manual install that dies with the container.
        APT=""
        if command -v apt-get >/dev/null 2>&1; then
            if [ "$(id -u)" = 0 ]; then APT="env";
            elif sudo -n true 2>/dev/null; then APT="sudo -n"; fi
        fi
        if [ -n "$APT" ]; then
            printf '%s: python3 venv support missing; installing %s via apt\n' "$LAUNCH_PRODUCT" "$PYVENV_PKG" >&2
            $APT apt-get update -qq >/dev/null 2>&1 || true
            $APT DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$PYVENV_PKG" >/dev/null 2>&1 \
                || $APT DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv >/dev/null 2>&1 || true
        fi
        # Still missing - a non-root user without sudo, a host without apt, or a
        # python that did not come from a distro package. Fall back to fetching pip
        # into the venv directly: that needs neither root nor apt, only egress. The
        # diagnostic names WHY the apt path was skipped, so a CI log answers that
        # question on its own, without anyone getting onto the host.
        if ! python3 -m ensurepip --version >/dev/null 2>&1; then
            printf '%s: ensurepip still missing (uid=%s apt=%s sudo=%s); bootstrapping pip via get-pip.py\n' \
                "$LAUNCH_PRODUCT" \
                "$(id -u)" \
                "$(command -v apt-get >/dev/null 2>&1 && echo yes || echo no)" \
                "$(sudo -n true 2>/dev/null && echo yes || echo no)" >&2
            VENV_WITHOUT_PIP=1
        fi
    fi

    if [ -n "${VENV_WITHOUT_PIP:-}" ]; then
        # Create the venv shell without pip, then fetch pip straight into it.
        # Unprivileged, and works on any host with network access.
        python3 -m venv --without-pip "$VENV"
        curl -fsSL https://bootstrap.pypa.io/get-pip.py | "$PY" - -q || true
    else
        python3 -m venv "$VENV"
    fi

    # Every path above can fail quietly (apt did nothing, no curl, no egress), so
    # state the outcome rather than the attempt, and name the one command that fixes
    # it by hand.
    [ -x "$PIP" ] || {
        printf '%s: could not provision pip into the venv. Install venv support: sudo apt install %s\n' \
            "$LAUNCH_PRODUCT" \
            "$(python3 -c 'import sys; print("python%d.%d-venv" % sys.version_info[:2])')" >&2
        exit 1
    }
fi

# Reinstall only when requirements.txt is newer than the last successful
# install. Without the stamp every invocation pays a pip resolve.
if [ ! -f "$STAMP" ] || [ "$REQ" -nt "$STAMP" ]; then
    "$PIP" install -q --disable-pip-version-check -r "$REQ"
    touch "$STAMP"
fi

export PYTHONPATH="$LAUNCH_ORCH_DIR/src/python${PYTHONPATH:+:$PYTHONPATH}"
export LAUNCH_PRODUCT LAUNCH_ROOT LAUNCH_ORCH_DIR LAUNCH_MODULE
# -u: unbuffered, so streamed output stays live and correctly ordered when piped
# (CI, nohup, tee).
exec "$PY" -u -m "$LAUNCH_MODULE" "$@"
