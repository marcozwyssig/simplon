"""Self-healing venv provisioning for the test venvs (netctl#475, extracted to the delivery kernel in
netctl#592 Train B).

Mirrors the shim's bootstrap: a venv whose bin/pip is missing counts as half-created and is rebuilt
(netctl#467), and a host python WITHOUT ensurepip (bare Debian/Ubuntu, CI runner containers) gets the
venv created --without-pip with pip fetched straight into it via get-pip.py - no root needed, only egress.
Product-agnostic: any *ctl orchestrator that spins its own test venvs reuses this.

THIS MODULE IS THE HOST DEPENDENCY si#199 NAMES, and si#202 measured exactly where it sits. `test:gate`
is the only caller, and the dependency is narrower than the ticket assumed: it is on PROVISIONING and not
on running. Driven on 2026-09-12 against a scaffolded product with every `python*` removed from PATH:

  * with the suite venv already built, the gate is GREEN - `1 passed`, rc 0. The venv's own interpreter
    is an absolute path, so nothing is looked up;
  * with the venv removed, the run ends in `FileNotFoundError: [Errno 2] No such file or directory:
    'python3'` and a rendered traceback. Not a diagnosis, and it names neither the tool nor the way out.

Both refusals below come from that run. What the module does NOT do is move into a container, and si#202
records why: `test:gate`'s runner is the kernel's own pytest, so a containerised suite is a `command:`
gate naming a `toolchain:run` command with `results_from:` (si#106, si#133), which needs no kernel change
and was driven green in si#197. Two routes to one verdict, and this one owes its user an honest refusal
rather than a stack trace.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from simplon import fetch
from simplon import log
from simplon.run import run

GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def _require_host_python(venv: Path) -> None:
    """Refuse, by name, when the one host tool this module needs is not there (si#202).

    BEFORE THE `rmtree`, and the order is the whole of it. Without this gate a host with no `python3` and
    a half-built venv had the venv WIPED and then met `FileNotFoundError: [Errno 2] No such file or
    directory: 'python3'` out of `subprocess`, so the run destroyed the only thing it might have reused
    on its way to a traceback that named nothing. Measured on a scaffolded product with every `python*`
    removed from PATH; with the venv intact the same run is green, which is why the check is here and not
    at the top of the module.

    It names the second route rather than only the missing package, because "install python3" is the
    wrong advice on the host si#199 is about: a machine with bash and docker runs a containerised suite
    as a `command:` gate today and needs no python at all.
    """
    if shutil.which("python3"):
        return
    log.die(f"python3 is not on PATH, so the suite venv at {venv} cannot be created - and a suite that "
            f"never ran is not a red suite. Either put a python3 with venv support on PATH (apt install "
            f"python3-venv), or run this level in a container instead: a `command:` gate naming a "
            f"`toolchain:run` command, with `results_from:` pointing at what the container wrote")


def ensure_venv(venv: Path) -> Path:
    """Ensure a usable venv (python + pip) at `venv` and return it. Idempotent: a healthy venv
    short-circuits; a half-created one is rebuilt; a venv-less host python falls back to get-pip."""
    pip = venv / "bin" / "pip"
    if os.access(pip, os.X_OK):
        return venv
    _require_host_python(venv)
    shutil.rmtree(venv, ignore_errors=True)
    if run(["python3", "-m", "ensurepip", "--version"]).ok:
        run(["python3", "-m", "venv", str(venv)])
    else:
        log.info(f"python3 lacks ensurepip; bootstrapping pip into {venv.name} via get-pip.py")
        run(["python3", "-m", "venv", "--without-pip", str(venv)])
        script = venv / "get-pip.py"
        fetch.download(GET_PIP_URL, script, label="get-pip.py")
        run([str(venv / "bin" / "python"), str(script), "-q"])
        script.unlink(missing_ok=True)
    if not os.access(pip, os.X_OK):
        log.die(f"could not provision pip into {venv} (ensurepip missing and get-pip.py failed); "
                f"install venv support: sudo apt install python3-venv")
    return venv


def venv_python_pip(directory: str | Path) -> tuple[str, str]:
    """Ensure a self-healing venv under ``<directory>/.venv``, install its ``requirements.txt`` into it,
    and return the ``(python, pip)`` executable paths. The one-call convenience a product's test runner
    uses to prepare a suite's venv (netctl#730, extracted from netctl's orchestrator testrun)."""
    directory = Path(directory)
    venv = ensure_venv(directory / ".venv")
    py = str(venv / "bin" / "python")
    pip = str(venv / "bin" / "pip")
    requirements = directory / "requirements.txt"
    installed = run([pip, "install", "-q", "--disable-pip-version-check", "-r", str(requirements)])
    if not installed.ok:
        # THE RC USED TO BE DROPPED, and si#202 measured what that costs. `run` captures, so pip's own
        # reason went nowhere; the venv came back without the suite's dependencies in it, and pytest was
        # then started out of it anyway. On a bad pin in a product's own requirements.txt the whole
        # transcript of the failure was one line - `.venv/bin/python: No module named pytest` - and the
        # gate recorded `unit: failed (rc 1) - the suite ran and reported failures`. The suite did not
        # run and reported nothing; the record named the product for the kernel's own silence, which is
        # this repository's hunted defect with the blame pointing the wrong way.
        #
        # So it dies here, before the gate clears anything, and it quotes pip rather than paraphrasing:
        # "could not find a version that satisfies" and "no matching distribution" are the product's to
        # fix and only pip can tell it which line of the file it was.
        said = (installed.err or installed.out).rstrip() or "(pip wrote nothing at all)"
        log.die(f"the suite's dependencies did not install from {requirements} (pip rc "
                f"{installed.rc}) - the suite cannot run, so nothing it might have reported would be "
                f"about the product:\n{said}")
    return py, pip
