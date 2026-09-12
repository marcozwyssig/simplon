#!/usr/bin/env bash
#
# simplon.sh - the simplon entry point.
#
# It declares simplon's parameters, provisions the kernel, and execs the
# CLI. The kernel arrives as an ordinary dependency (simplon on PyPI), so there
# is nothing to vendor and no submodule to init: a fresh clone plus this script
# is the whole setup.
#
# TWO ROUTES TO ONE CLI (si#199/si#201). The kernel is either Python in a venv
# on this host, or a container. The user chooses with DELIVERY_ROUTE; the
# default is `auto`, which takes the venv when there is a python3 and the
# container when there is not - so a machine with bash and docker runs this
# product, and a machine with a python keeps exactly the behaviour it had.
# Both routes reach the same `python -m simplon` with the same parameters,
# and the acceptance criterion is that their verdicts are indistinguishable.
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
# The PUBLISHED KERNEL IMAGE this checkout runs on the container route, as a plain line a shell can read
# (si#200). It is a parameter like the four above: move the file and point this at it. A checkout with no
# such file, or one whose file carries no reference, has no container route - which is a statement rather
# than a gap, and the refusals below say so.
LAUNCH_IMAGE_PIN="$ROOT/deploy/image/image.pin"

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


# --- WHICH ROUTE ------------------------------------------------------------------------------------
#
# `venv` is what this launcher has always done. `container` runs the pinned kernel image with this
# checkout bind-mounted at /src. `auto`, the default, prefers the venv: a host that has a python3 keeps
# byte-for-byte the behaviour it had before si#201, and only a host without one reaches for the image.
DELIVERY_ROUTE="${DELIVERY_ROUTE:-auto}"
case "$DELIVERY_ROUTE" in
    venv|container|auto|inside) ;;
    *)
        printf '%s: DELIVERY_ROUTE is "%s"; it is one of venv, container, auto, inside\n' \
            "$LAUNCH_PRODUCT" "$DELIVERY_ROUTE" >&2
        exit 1 ;;
esac

# ALREADY INSIDE THE KERNEL CONTAINER, and this is the value a user never types: the container route
# below sets it on the way in. It exists because an AGGREGATE command re-invokes this launcher once per
# step - that is how `simplon test all` streams its children - and without it the nested call would
# decide the route again from scratch.
#
# MEASURED, and it is the failure that made this branch: with the route not carried, the nested call took
# the VENV route (there is a python3 in the image) and found the host's venv through the bind mount. Its
# `bin/python` is a symlink to the HOST's interpreter, which does not exist in the container, so all three
# steps of `test all` died identically with `.venv/bin/python: No such file or directory`, rc 127, in
# under a tenth of a second. Three red steps that never ran anything.
#
# Nothing to provision here: the environment the container route wrote - PYTHONPATH, PYTHONUSERBASE and
# the four launch parameters - is already this process' own.
if [ "$DELIVERY_ROUTE" = inside ]; then
    exec python -u -m "$LAUNCH_MODULE" "$@"
fi

# THE PIN, READ BY A SHELL. This is the whole reason si#200 put the reference in a plain file instead of
# under an `images:` key: bash has to know which kernel to run BEFORE any Python exists to parse the
# manifest with. Comments and blank lines out, first line left is the reference; `grep` exits 1 on no
# match, which under `set -e` would end the run, hence the `|| true`.
KERNEL_IMAGE=""
if [ -f "$LAUNCH_IMAGE_PIN" ]; then
    KERNEL_IMAGE="$(grep -v '^[[:space:]]*#' "$LAUNCH_IMAGE_PIN" 2>/dev/null \
        | grep -v '^[[:space:]]*$' | head -n1 | tr -d '[:space:]' || true)"
fi

if [ "$DELIVERY_ROUTE" = auto ]; then
    if command -v python3 >/dev/null 2>&1; then
        DELIVERY_ROUTE=venv
    elif [ -n "$KERNEL_IMAGE" ] && command -v docker >/dev/null 2>&1; then
        DELIVERY_ROUTE=container
    else
        printf '%s: neither route is available here.\n' "$LAUNCH_PRODUCT" >&2
        printf '%s:   venv      needs python3, which is not on PATH\n' "$LAUNCH_PRODUCT" >&2
        printf '%s:   container needs docker (%s) and a kernel image pinned in\n' "$LAUNCH_PRODUCT" \
            "$(command -v docker >/dev/null 2>&1 && echo 'present' || echo 'not on PATH')" >&2
        printf '%s:             %s (%s)\n' "$LAUNCH_PRODUCT" "$LAUNCH_IMAGE_PIN" \
            "$([ -n "$KERNEL_IMAGE" ] && echo "pins $KERNEL_IMAGE" || echo 'names no image')" >&2
        exit 1
    fi
fi

if [ "$DELIVERY_ROUTE" = container ]; then
    # DERIVED FROM THE ONE PARAMETER, not substituted a second time. LAUNCH_ORCH_DIR is where the block
    # is, and everything the container needs to know about it - the requirements file, PYTHONPATH, the
    # block dir in the container's own coordinates - comes out of that variable, exactly as the venv
    # route below derives VENV, REQ and PYTHONPATH from it. A launcher that carried the block path twice
    # would be half-parametrised: `--orch-dir` would move one route and not the other.
    ORCH_IN_SRC="/src/${LAUNCH_ORCH_DIR#"$ROOT/"}"

    # THE CONTAINER ROUTE. The kernel runs in the image si#200 builds, this checkout is bind-mounted at
    # /src, and the host's docker socket comes with it so the kernel can still start the toolchain
    # containers every task is made of.
    [ -n "$KERNEL_IMAGE" ] || {
        printf '%s: the container route needs a published kernel image, and\n' "$LAUNCH_PRODUCT" >&2
        printf '%s:   %s\n' "$LAUNCH_PRODUCT" "$LAUNCH_IMAGE_PIN" >&2
        printf '%s: %s. Until one is published and pinned there, this checkout has\n' "$LAUNCH_PRODUCT" \
            "$([ -f "$LAUNCH_IMAGE_PIN" ] && echo 'carries no reference' || echo 'does not exist')" >&2
        printf '%s: no container route; DELIVERY_ROUTE=venv is the one that works.\n' "$LAUNCH_PRODUCT" >&2
        exit 1
    }
    command -v docker >/dev/null 2>&1 || {
        printf '%s: the container route needs the docker CLI, which is not on PATH.\n' "$LAUNCH_PRODUCT" >&2
        exit 1
    }
    # A LINKED GIT WORKTREE CANNOT TAKE THIS ROUTE, and it is said here rather than discovered three
    # commands later. Measured: such a checkout's `.git` is a FILE naming a gitdir under the MAIN
    # checkout, which is outside the mount, so `git log` inside the container answers `fatal: not a git
    # repository: /root/git/<product>/.git/worktrees/<name>` - and with it go the release-notes guard,
    # `release tag`, the image's provenance and any editable install of the tree.
    [ -f "$ROOT/.git" ] && {
        printf '%s: this checkout is a LINKED GIT WORKTREE, so the container route cannot run here.\n' \
            "$LAUNCH_PRODUCT" >&2
        printf '%s:   .git is a file naming %s,\n' "$LAUNCH_PRODUCT" \
            "$(sed -n 's/^gitdir: //p' "$ROOT/.git" | head -n1)" >&2
        printf '%s:   which lives outside the tree that gets mounted, so git inside the container sees\n' \
            "$LAUNCH_PRODUCT" >&2
        printf '%s:   no repository at all. Use DELIVERY_ROUTE=venv here, or the main checkout.\n' \
            "$LAUNCH_PRODUCT" >&2
        exit 1
    }

    # WHERE THE PRODUCT'S OWN ORCHESTRATOR DEPENDENCIES GO. The image carries the KERNEL and nothing of
    # any product (si#200/si#121), so `build` and `pytest` and whatever else this product's requirements
    # name are still this checkout's to provide - the same install the venv route does, into the mount
    # instead of into a venv. Under build/, so `clean` takes it and .gitignore already covers it; NOT
    # into $LAUNCH_ORCH_DIR/.venv, because the two routes' interpreters differ and a venv built by one
    # is a broken interpreter symlink to the other.
    CDEPS="$ROOT/build/container/python"
    CSTAMP="$CDEPS/.deps-stamp"

    # docker run arguments that depend on the caller, assembled before the run so each can carry its own
    # reason.
    DOCKER_RUN=(docker run --rm --init -i)
    # A TTY ONLY WHEN THERE IS ONE. `docker run -t` without one fails outright ("the input device is not
    # a TTY"), and CI has none - so the flag is conditional and the headless path is reached the same way
    # it is on the venv route, through the TUI's own `sys.stdout.isatty()` check.
    if [ -t 0 ] && [ -t 1 ]; then DOCKER_RUN+=(-t); fi
    # AS THE CALLER. A bind mount hands the container the host's inodes, so a container running as root
    # leaves root-owned build outputs the caller cannot delete - which is the rule `simplon.docker.user_args`
    # already carries for every toolchain container, applied to the kernel's own. It also makes that
    # function's `os.getuid()` answer the caller's uid inside the container, so the sibling containers
    # inherit the right owner for free.
    DOCKER_RUN+=(--user "$(id -u):$(id -g)")
    # THE SOCKET, WHEN THERE IS ONE. Every task in this kernel is a `docker run`, so without it the
    # container route can only do the work that needs no container. It is not made mandatory: the pytest
    # suite and the release-notes guard need no daemon, and refusing them would be refusing a run that
    # works. `--group-add` is what lets a non-root caller write a socket that is root:docker 0660; the
    # `stat` runs twice because GNU spells the format `-c` and BSD spells it `-f`.
    #
    # THE DEFAULT SOCKET AND NO OTHER, deliberately. A daemon reached over tcp or ssh would break this
    # route for a reason no flag here can fix: the host paths si#201 translates to are this machine's,
    # and a remote daemon would resolve them against its own filesystem - which is the empty-directory
    # failure again, one hop further away.
    if [ -S /var/run/docker.sock ]; then
        DOCKER_RUN+=(-v /var/run/docker.sock:/var/run/docker.sock)
        SOCK_GID="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || stat -f '%g' /var/run/docker.sock 2>/dev/null || true)"
        [ -n "$SOCK_GID" ] && DOCKER_RUN+=(--group-add "$SOCK_GID")
    fi
    # THE HOST PATH OF THE MOUNT, which is the whole of si#201. The kernel is about to start sibling
    # containers through that socket, and the daemon resolves their `-v` sources against the HOST - so a
    # kernel that passed on its own `/src` would hand the daemon a path that does not exist there.
    # Measured: the daemon CREATES it, empty, and the run is green over nothing. This launcher is the one
    # process that provably knows the answer, because it is the one writing the mount.
    DOCKER_RUN+=(-v "$ROOT:/src" -w /src)
    # BOTH SIDES OF THE MAPPING, because a bind mount is two paths and the kernel must not have to infer
    # either. Inferring the container side from the product root was measured wrong: a product scaffolded
    # into a subdirectory of the mount would be flattened onto the host root and a sibling container
    # handed the wrong tree.
    DOCKER_RUN+=(-e "DELIVERY_HOST_ROOT=$ROOT" -e DELIVERY_MOUNT_ROOT=/src)
    # The route itself, so the nested launcher an aggregate step runs stays in this container instead of
    # deciding again (see the `inside` branch above).
    #
    # NO DELIVERY_DOCKER_BOOTSTRAP, and si#201 measured why not: the image now carries the pinned docker
    # client (deploy/image/Dockerfile says what that cost and what leaving it out cost), so
    # `ensure_docker` finds one on PATH and is the no-op it is on any developer's host. Setting the flag
    # anyway would put the gate into its self-healing mode inside a container that has no systemd and no
    # engine to heal.
    DOCKER_RUN+=(-e DELIVERY_ROUTE=inside)
    # The four launch parameters, restated in the container's own coordinates.
    DOCKER_RUN+=(-e "LAUNCH_PRODUCT=$LAUNCH_PRODUCT" -e LAUNCH_ROOT=/src \
                 -e "LAUNCH_ORCH_DIR=$ORCH_IN_SRC" -e "LAUNCH_MODULE=$LAUNCH_MODULE")
    DOCKER_RUN+=(-e "PYTHONPATH=$ORCH_IN_SRC/src/python")
    DOCKER_RUN+=(-e PYTHONUSERBASE=/src/build/container/python -e HOME=/tmp)
    # The caller's git identity, read-only, because `release tag` and every commit the kernel makes want
    # a name and a mail and the image has neither. Only this one file: copying a whole home directory
    # into a container is how a credential reaches a place nobody looked.
    [ -f "${HOME:-}/.gitconfig" ] && DOCKER_RUN+=(-v "$HOME/.gitconfig:/tmp/.gitconfig:ro")
    # WHICH VARIABLES CROSS. The venv route inherits the caller's whole environment and this one inherits
    # nothing, so the difference has to be named rather than left to be discovered. Two namespaces plus
    # the handful of variables a CI runner speaks: the kernel's own DELIVERY_*, this product's, and
    # CI/NO_COLOR/TERM/TZ/GITHUB_TOKEN. Anything else stays on the host on purpose - PATH and HOME from
    # the host mean nothing in the image, and forwarding an unbounded environment is how a secret travels
    # somewhere nobody meant it to.
    ENV_PREFIX="$(printf '%s' "$LAUNCH_PRODUCT" | tr '[:lower:]-' '[:upper:]_')"
    while read -r _name; do
        case "$_name" in
            DELIVERY_ROUTE|DELIVERY_HOST_ROOT|DELIVERY_MOUNT_ROOT|PYTHONPATH|PYTHONUSERBASE|HOME) ;;
            DELIVERY_*|CI|NO_COLOR|TERM|TZ|GITHUB_TOKEN) DOCKER_RUN+=(-e "$_name") ;;
            "$ENV_PREFIX"_*) DOCKER_RUN+=(-e "$_name") ;;
        esac
    done < <(compgen -e)

    # THE PRODUCT'S DEPENDENCIES, installed on the same condition the venv route uses: only when
    # requirements.txt is newer than the last successful install. The stamp is on the host side of the
    # mount, so this comparison costs no container at all on the normal run.
    if [ ! -f "$CSTAMP" ] || [ "$REQ" -nt "$CSTAMP" ]; then
        mkdir -p "$CDEPS"
        "${DOCKER_RUN[@]}" "$KERNEL_IMAGE" \
            pip install --user -q --disable-pip-version-check --root-user-action=ignore \
                --no-warn-script-location -r "$ORCH_IN_SRC/requirements.txt"
        touch "$CSTAMP"
    fi

    # -u for the reason the venv route gives: unbuffered, so streamed output stays live and correctly
    # ordered when piped.
    exec "${DOCKER_RUN[@]}" "$KERNEL_IMAGE" python -u -m "$LAUNCH_MODULE" "$@"
fi

command -v python3 >/dev/null 2>&1 || {
    printf '%s: python3 is required for the venv route (the orchestrator is host-Python).\n' \
        "$LAUNCH_PRODUCT" >&2
    printf '%s: DELIVERY_ROUTE=container runs the kernel in a container instead; it needs docker and\n' \
        "$LAUNCH_PRODUCT" >&2
    printf '%s: an image pinned in %s.\n' "$LAUNCH_PRODUCT" "$LAUNCH_IMAGE_PIN" >&2
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
