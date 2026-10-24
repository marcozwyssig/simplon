"""What every host-install gate of `support install` shares (si#526): six outcomes, and one way to run a
command that may need root.

SIX OUTCOMES, BECAUSE FIVE OF THEM ARE DIFFERENT ANSWERS. OFF (the product does not use the tool) says
nothing. PRESENT, INSTALLED and SKIPPED (the container route, CI, a platform the tool does not run on) are
fine and exit 0. NO_ROUTE (declared, missing, and this machine offers no way to install it) and FAILED (an
install command failed, timed out, or left a tool that does not run) exit 1. "Cannot here" exiting 0 would
be the recurring defect: a green setup and a red first release.

PRESENCE IS NOT CAPABILITY. A tool counts as there only when `<tool> --version` exits 0, so a broken
binary on PATH is not PRESENT.

UNCAPTURED ON PURPOSE. `support install` is a command a person runs on a terminal, not a pipeline, so no
TUI is in the way. A sudo password prompt, apt's progress and Homebrew's RETURN prompt reach that person.
Every command still has a time limit: a run that hangs is neither green nor red.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping

from simplon.kernel import log
from simplon.kernel.run import run

#: The time limit of one install command. A sudo prompt is inside it, so it is generous.
INSTALL_TIMEOUT_S = 600
#: The time limit of `<tool> --version`.
VERSION_TIMEOUT_S = 30


class State(Enum):
    OFF = "off"
    PRESENT = "present"
    INSTALLED = "installed"
    SKIPPED = "skipped"
    NO_ROUTE = "no route"
    FAILED = "failed"


@dataclass(frozen=True)
class Outcome:
    state: State
    detail: str = ""


def rc(outcome: Outcome) -> int:
    """1 for NO_ROUTE and FAILED, 0 for everything else."""
    return 1 if outcome.state in (State.NO_ROUTE, State.FAILED) else 0


def report(name: str, outcome: Outcome) -> None:
    """One line per gate, in words no other outcome uses; nothing at all for OFF."""
    suffix = f" ({outcome.detail})" if outcome.detail else ""
    if outcome.state is State.PRESENT:
        log.ok(f"{name} is present{suffix}")
    elif outcome.state is State.INSTALLED:
        log.ok(f"{name} installed{suffix}")
    elif outcome.state is State.SKIPPED:
        log.info(f"{name} skipped: {outcome.detail}")
    elif outcome.state is State.NO_ROUTE:
        log.error(f"{name}: no way to install it here: {outcome.detail}")
    elif outcome.state is State.FAILED:
        log.error(f"{name}: install failed: {outcome.detail}")


def machine_skip_reason(env: Mapping[str, str], container: bool) -> str:
    """Why this machine is not one to provision, or "" when it is."""
    if container:
        return "the container route: host tools are installed on the host"
    for variable in ("CI", "GITHUB_ACTIONS"):
        if env.get(variable, "").lower() == "true":
            return f"{variable}=true: host tools are for a machine somebody develops on"
    return ""


def runs(tool: str, env: Mapping[str, str] | None = None) -> bool:
    """True when `tool --version` exits 0 within the time limit, with `env`'s PATH (default: this process')."""
    path = (env if env is not None else os.environ).get("PATH")
    found = shutil.which(tool, path=path)
    if found is None:
        return False
    try:
        return run([found, "--version"], timeout=VERSION_TIMEOUT_S).rc == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def privileged(argv: list[str], *, euid: int | None = None,
               have: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    """`argv` as root would run it: as-is for root (and on Windows, which has no euid), behind `sudo`
    otherwise, None when there is no sudo to go through."""
    if euid is None:
        geteuid = getattr(os, "geteuid", None)
        if geteuid is None:
            return list(argv)
        euid = geteuid()
    if euid == 0:
        return list(argv)
    if have("sudo") is None:
        return None
    return ["sudo", *argv]


def act(argv: list[str], timeout_s: float = INSTALL_TIMEOUT_S, env: Mapping[str, str] | None = None) -> str:
    """Run one install command uncaptured; "" on success, else why, in words a person can act on."""
    try:
        code = subprocess.run(argv, env=None if env is None else dict(env), timeout=timeout_s,
                              check=False).returncode
    except subprocess.TimeoutExpired:
        return f"{argv[0]} timed out after {timeout_s:g} s"
    except OSError as exc:
        return f"{argv[0]} could not be started: {exc}"
    return "" if code == 0 else f"{argv[0]} exited {code}"
