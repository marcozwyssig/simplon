"""The `brew` toolchain's gate (si#526): Homebrew is there by the time `support install` moves on, or the
person hears why not.

WHY HOMEBREW FIRST. With `brew` in `toolchains:`, the gates after this one (oras, gh) install through it,
so `support install` runs this gate before them, and puts a freshly installed brew on this process' PATH.

WHAT HOMEBREW'S OWN INSTALLER REFUSES, measured on 2026-10-24 in its install.sh, and said here before it
runs rather than after it fails:
- Windows: "Homebrew is only supported on macOS and Linux". SKIPPED, not a failure: a Windows developer in
  a product that declares `brew` for its Mac and Linux developers must not get a red setup.
- Intel macOS: "only supported on Apple Silicon". SKIPPED, for the same reason.
- root on a plain host: "Don't run this as root!", unless inside a container (`/.dockerenv`,
  `/run/.containerenv`). NO_ROUTE: the person can fix it by running as their own user.

PINNED, NEVER HEAD. install.sh is fetched from one commit of Homebrew/install and checked against its
sha256 before it runs; a mismatch runs nothing. Bump both together, deliberately.

THE SHELL PROFILE IS THE PERSON'S. After an install, `brew` is not on PATH until the shell evaluates
`brew shellenv`. This gate prints the line to add and never edits a dotfile.
"""
from __future__ import annotations

import hashlib
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Mapping

from simplon.adapters import fetch, tools
from simplon.adapters.hostinstall import Outcome, State, act, machine_skip_reason, runs
from simplon.kernel import log

INSTALL_COMMIT = "8ab1549dfa1189fd4d818a2116592d8f0ee06d8c"  # 2026-10-07
INSTALL_SHA256 = "5f333bbe53bc490e51e7ccb1df8779b3dd6ee73a1a7379efda216edb08ccb148"
INSTALL_URL = f"https://raw.githubusercontent.com/Homebrew/install/{INSTALL_COMMIT}/install.sh"
MANUAL = "https://brew.sh"
BASH = "/bin/bash"

#: Where Homebrew's installer lets root run: the same markers its own `check_run_command_as_root` reads.
ROOT_ALLOWED_MARKERS = ("/.dockerenv", "/run/.containerenv")


def prefix(system: str, machine: str) -> str | None:
    """Homebrew's default prefix on this platform, or None where it does not run. Pure."""
    os_name = system.lower()
    if os_name == "darwin":
        return "/opt/homebrew" if machine.lower() == "arm64" else None
    if os_name == "linux":
        return "/home/linuxbrew/.linuxbrew"
    return None


def unsupported(system: str, machine: str) -> str:
    """Why Homebrew does not run on this platform, or "" when it does. Pure."""
    os_name = system.lower()
    if os_name == "darwin" and machine.lower() != "arm64":
        return "Homebrew on macOS runs only on Apple Silicon"
    if os_name not in ("darwin", "linux"):
        return f"Homebrew does not run on {system}"
    return ""


def shellenv_line(where: str) -> str:
    return f'eval "$({where}/bin/brew shellenv)"'


def _at_prefix(where: str | None) -> bool:
    """True when the prefix holds a brew that runs; it is then put first on this process' PATH."""
    if where is None or not runs("brew", {"PATH": f"{where}/bin"}):
        return False
    if not runs("brew"):
        tools.prepend_to_path(f"{where}/bin")
        log.info(f"brew is at {where} but not on your PATH; add this line to your shell profile: "
                 f"{shellenv_line(where)}")
    return True


def _install(where: str | None, interactive: bool) -> Outcome:
    with tempfile.TemporaryDirectory() as scratch:
        script = Path(scratch) / "install.sh"
        try:
            fetch.download(INSTALL_URL, script, label="Homebrew install.sh")
        except fetch.DownloadError as exc:
            return Outcome(State.FAILED, str(exc))
        got = hashlib.sha256(script.read_bytes()).hexdigest()
        if got != INSTALL_SHA256:
            return Outcome(State.FAILED, f"install.sh from {INSTALL_URL} has sha256 {got}, expected "
                                         f"{INSTALL_SHA256}; nothing was run")
        env = dict(os.environ)
        if not interactive:
            env["NONINTERACTIVE"] = "1"
        log.info("brew missing; running Homebrew's install.sh")
        reason = act([BASH, str(script)], env=env)
    if reason:
        return Outcome(State.FAILED, reason)
    if not _at_prefix(where):
        return Outcome(State.FAILED, f"install.sh finished but {where}/bin/brew does not run")
    return Outcome(State.INSTALLED, f"add to your shell profile: {shellenv_line(str(where))}")


def ensure(*, env: Mapping[str, str] | None = None, container: bool = False, system: str | None = None,
           machine: str | None = None, euid: int | None = None, interactive: bool | None = None) -> Outcome:
    """Homebrew PRESENT, INSTALLED, or why not. Every parameter defaults to this host; tests pass them."""
    env = os.environ if env is None else env
    system = system or platform.system()
    machine = machine or platform.machine()
    skip = machine_skip_reason(env, container) or unsupported(system, machine)
    if skip:
        return Outcome(State.SKIPPED, skip)
    if runs("brew"):
        return Outcome(State.PRESENT)
    where = prefix(system, machine)
    if _at_prefix(where):
        return Outcome(State.PRESENT, f"at {where}")
    if euid is None:
        euid = os.geteuid() if hasattr(os, "geteuid") else 1
    if euid == 0 and not any(os.path.exists(marker) for marker in ROOT_ALLOWED_MARKERS):
        return Outcome(State.NO_ROUTE, f"Homebrew refuses to install as root; run support install as your "
                                       f"own user (see {MANUAL})")
    return _install(where, sys.stdin.isatty() if interactive is None else interactive)
