"""Self-healing venv provisioning for the test venvs (netctl#475, extracted to the delivery kernel in
netctl#592 Train B).

Mirrors the shim's bootstrap: a venv whose bin/pip is missing counts as half-created and is rebuilt
(netctl#467), and a host python WITHOUT ensurepip (bare Debian/Ubuntu, CI runner containers) gets the
venv created --without-pip with pip fetched straight into it via get-pip.py - no root needed, only egress.
Product-agnostic: any *ctl orchestrator that spins its own test venvs reuses this.
"""
from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path

from delivery import log
from delivery.run import run

GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def ensure_venv(venv: Path) -> Path:
    """Ensure a usable venv (python + pip) at `venv` and return it. Idempotent: a healthy venv
    short-circuits; a half-created one is rebuilt; a venv-less host python falls back to get-pip."""
    pip = venv / "bin" / "pip"
    if os.access(pip, os.X_OK):
        return venv
    shutil.rmtree(venv, ignore_errors=True)
    if run(["python3", "-m", "ensurepip", "--version"]).ok:
        run(["python3", "-m", "venv", str(venv)])
    else:
        log.info(f"python3 lacks ensurepip; bootstrapping pip into {venv.name} via get-pip.py")
        run(["python3", "-m", "venv", "--without-pip", str(venv)])
        script = venv / "get-pip.py"
        urllib.request.urlretrieve(GET_PIP_URL, script)
        run([str(venv / "bin" / "python"), str(script), "-q"])
        script.unlink(missing_ok=True)
    if not os.access(pip, os.X_OK):
        log.die(f"could not provision pip into {venv} (ensurepip missing and get-pip.py failed); "
                f"install venv support: sudo apt install python3-venv")
    return venv
