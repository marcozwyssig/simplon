"""Type-check a product's Python sources with mypy, in the host venv the CLI already runs in.

WHY THIS IS THE KERNEL'S. Running a type checker needs no product knowledge. mypy reads its own config
file, resolves its own roots from it, and reports against its own rules - none of that is a *ctl
convention. What IS the product's is the DATA: which sources are covered, which third-party modules have
no stubs, and which module is exempt and why. All of it lives in the product's `mypy.ini`, so a
per-product function forwarding this call would be a shim rather than a seam.

WHY AN INTERPRETER, not Docker. The checker needs to SEE the product's installed dependencies, or every
third-party import degrades into a blanket exception and the gate stops meaning anything. So the one
thing this task has to get right is WHICH interpreter it asks. Two shapes exist among the *ctl products
and both are served by one parameter:

  - the HOST VENV, which is the default. The orchestrator itself runs in it, so `sys.executable` is
    already the right answer and there is nothing to bootstrap. A product whose Python IS the host venv
    (netctl: sidecar + orchestrator + labgen) names nothing at all.
  - a BLOCK'S OWN venv, named with `with: { python: ... }`. A product that manages a block's
    dependencies separately (cockpit: the backend is a uv project) has its installed set there and not
    on the host, and pointing the checker at the host venv would type a program nobody ships.

Either way this stays the cheapest gate in the catalogue - no image, no daemon, no lab.

WHY A WORKING DIRECTORY. mypy resolves the source roots in its config against the CURRENT directory, not
against the config's own location. A product whose config sits inside a block therefore needs the gate to
run there, which is `with: { workdir: ... }`. It defaults to the product root, so a product with one
config at the top names nothing.

WHY A CONFIG FILE IS REQUIRED. mypy without one checks whatever it is pointed at, with defaults nobody
wrote down. A gate whose rules are implicit cannot be argued with when it goes red, and the first
argument it loses is its own existence. The file is the product's stated position - which layers are
covered, what is exempt, and the reason for each - so this task refuses rather than inventing one.
"""
from __future__ import annotations

import sys
from pathlib import Path

from delivery import context, log
from delivery.run import run

#: mypy's own convention, not a product's. A product that wants another name pins it with
#: `with: { config: <path> }` on its command; the path is read relative to the product root.
DEFAULT_CONFIG = "mypy.ini"


def _config_path(where: Path, config: str) -> Path:
    """The product's mypy configuration, or a loud failure naming what is missing."""
    path = where / (config or DEFAULT_CONFIG)
    if not path.is_file():
        raise ValueError(
            f"mypy: no configuration at {path} - a type gate states which sources it covers and what "
            f"is exempt; without that file there is nothing to enforce"
        )
    return path


def _interpreter(workdir: Path, python: str) -> str:
    """The interpreter to run mypy with: the one the CLI runs in, or the one the product names.

    A named interpreter that is not there is an ERROR, not a fallback to the host venv. Falling back
    would run the checker against a different installed set than the product declares and still report
    success, which is the one outcome a gate must never produce.
    """
    if not python:
        return sys.executable
    named = workdir / python
    if not named.is_file():
        raise ValueError(
            f"mypy: no interpreter at {named} - the gate must read the product's OWN installed set, "
            f"so it will not silently fall back to the host venv"
        )
    return str(named)


def mypy_argv(python_exe: str, config: Path) -> list[str]:
    """PURE: the argv for the type gate. Separated so the wiring is assertable without running mypy."""
    return [python_exe, "-m", "mypy", "--config-file", str(config)]


def check(config: str = DEFAULT_CONFIG, workdir: str = "", python: str = "") -> int:
    """Type-check the product's Python sources (mypy) using its own configuration.

    ``workdir`` is where mypy runs, relative to the product root (default: the root itself), because
    mypy resolves its source roots against the current directory. ``config`` and ``python`` are read
    relative to THAT directory, so a block-local gate names its block once and everything else stays
    relative to it. A product with one config at the top and its dependencies in the host venv pins
    nothing at all.
    """
    ctx = context.current()
    where = ctx.root / workdir if workdir else ctx.root
    resolved = _config_path(where, config)
    python_exe = _interpreter(where, python)

    log.info(f"typecheck-python: mypy --config-file {resolved.relative_to(ctx.root)} "
             f"({'host venv' if not python else python})")
    rc = run(mypy_argv(python_exe, resolved), cwd=str(where), capture=False).rc
    if rc != 0:
        log.die("mypy reported findings (see output above)")
    log.ok("typecheck-python passed")
    return 0
