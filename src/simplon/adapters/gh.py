"""The `gh` toolchain's gate (si#526): the GitHub CLI is there by the time `support install` finishes, or the
person hears why not.

WHY. `release:asset`, the GitHub release coordinates, `vcs:auth-scopes`, the tracker and
`vcs:prune-branches` shell out to `gh`, and the `github` Claude plugin uses it. Before si#526 a fresh host
reported a green setup and failed on the first of them, or pruned less without a word.

SYSTEM-WIDE, THROUGH THE PLATFORM'S PACKAGE MANAGER (Marco, 2026-10-24). gh lands where every later process
finds it on PATH, so the call sites stay as they are. The first route that applies is taken: brew where it
is on PATH (after the `brew` gate, which runs first), winget on Windows, the official signed apt repository
on the Debian family. Anything else is NO_ROUTE with the manual link; dnf, zypper and pacman have no route
until a developer of a reachable product works on one.

THE APT KEYRING IS CHECKED BEFORE ANYTHING IS WRITTEN. It is downloaded by the kernel and compared with the
sha256 cli/cli publishes in docs/install_linux.md; a mismatch writes nothing under /etc/apt. The steps are
the official ones, run as root directly or behind sudo, uncaptured, so a password prompt reaches the person.

PROVISIONING ONLY. The token and its scopes are `vcs auth-scopes`'s.

MEASURED (2026-10-24, the local `python:3.12-slim` image, Debian 13 trixie, amd64; Docker Hub itself was
unreachable from the measuring host, so `debian:trixie` was not pulled):
- root: INSTALLED "through apt" in 14.3 s (gh 2.103.2), the list line and a 0644 keyring as above; a second
  run PRESENT in 0.0 s.
- a user with passwordless sudo: INSTALLED in 11.8 s, then PRESENT.
- a user and no sudo on PATH: NO_ROUTE, nothing downloaded or written.
- a user not in sudoers, no terminal: FAILED "sudo exited 1", with sudo's own "a terminal is required to read
  the password" on the line above, because the command runs uncaptured.
- after the `brew` gate in the same process: INSTALLED "through brew" in 4.3 s.
Not measured: winget on a real Windows host, and macOS.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Mapping

from simplon.adapters import fetch, hostinstall
from simplon.adapters.hostinstall import Outcome, State, machine_skip_reason, privileged, runs
from simplon.kernel import log
from simplon.kernel.run import run

KEYRING_URL = "https://cli.github.com/packages/githubcli-archive-keyring.gpg"
KEYRING_SHA256 = "6084d5d7bd8e288441e0e94fc6275570895da18e6751f70f057485dc2d1a811b"
KEYRING_PATH = "/etc/apt/keyrings/githubcli-archive-keyring.gpg"
LIST_PATH = "/etc/apt/sources.list.d/github-cli.list"
WINGET_ARGV = ["winget", "install", "--id", "GitHub.cli", "-e", "--source", "winget",
               "--accept-package-agreements", "--accept-source-agreements"]
MANUAL = "https://github.com/cli/cli#installation"


def route(system: str, have: Callable[[str], bool]) -> str:
    """"brew", "winget", "apt" or "" (no route). Pure given `have`."""
    if have("brew"):
        return "brew"
    if system.lower() == "windows" and have("winget"):
        return "winget"
    if system.lower() == "linux" and have("apt-get") and have("dpkg"):
        return "apt"
    return ""


def _act(argv: list[str]) -> str:
    # The limit is read when the command runs, so a test (or an operator) can lower it.
    return hostinstall.act(argv, timeout_s=hostinstall.INSTALL_TIMEOUT_S)


def _apt_install(euid: int | None) -> Outcome | None:
    """The official Debian steps; None when they all ran, else the outcome that stopped them."""
    if privileged(["true"], euid=euid) is None:
        return Outcome(State.NO_ROUTE, f"the apt route needs root or sudo, and there is no sudo on PATH; "
                                       f"see {MANUAL}")
    with tempfile.TemporaryDirectory() as scratch:
        keyring = Path(scratch) / "keyring.gpg"
        try:
            fetch.download(KEYRING_URL, keyring, label="GitHub CLI keyring")
        except fetch.DownloadError as exc:
            return Outcome(State.FAILED, str(exc))
        got = hashlib.sha256(keyring.read_bytes()).hexdigest()
        if got != KEYRING_SHA256:
            return Outcome(State.FAILED, f"the keyring from {KEYRING_URL} has sha256 {got}, expected "
                                         f"{KEYRING_SHA256}; nothing was written")
        arch = run(["dpkg", "--print-architecture"])
        if not arch.answered:
            return Outcome(State.FAILED, f"dpkg --print-architecture answered nothing (rc {arch.rc})")
        listing = Path(scratch) / "github-cli.list"
        listing.write_text(f"deb [arch={arch.out.strip()} signed-by={KEYRING_PATH}] "
                           f"https://cli.github.com/packages stable main\n", encoding="utf-8")
        log.info("gh missing; adding GitHub's apt repository and installing gh")
        for argv in (["install", "-D", "-m", "0644", str(keyring), KEYRING_PATH],
                     ["install", "-D", "-m", "0644", str(listing), LIST_PATH],
                     ["apt-get", "update"],
                     ["apt-get", "install", "-y", "gh"]):
            full = privileged(argv, euid=euid)
            assert full is not None  # checked above
            reason = _act(full)
            if reason:
                return Outcome(State.FAILED, reason)
    return None


def _reachable(outcome: Outcome) -> Outcome:
    """`outcome`, saying so when gh runs here only because a gate put its directory on this process' PATH
    (a brew prefix off the person's PATH): the next command starts from their shell and would not find it."""
    if hostinstall.reachable_later("gh"):
        return outcome
    where = os.path.dirname(shutil.which("gh") or "")
    hint = (f"gh is in {where}, which your shell's PATH does not reach; add brew's shellenv line (printed "
            f"above) to your shell profile, or later commands will not find gh")
    return Outcome(outcome.state, f"{outcome.detail}; {hint}" if outcome.detail else hint)


def ensure(*, env: Mapping[str, str] | None = None, container: bool = False, system: str | None = None,
           euid: int | None = None) -> Outcome:
    """gh PRESENT, INSTALLED, or why not. Every parameter defaults to this host; tests pass them."""
    env = os.environ if env is None else env
    system = system or platform.system()
    skip = machine_skip_reason(env, container)
    if skip:
        return Outcome(State.SKIPPED, skip)
    if runs("gh"):
        return _reachable(Outcome(State.PRESENT))
    chosen = route(system, lambda tool: shutil.which(tool) is not None)
    if not chosen:
        return Outcome(State.NO_ROUTE, f"no brew, winget or apt on this machine; install gh by hand: {MANUAL}")
    if chosen == "brew":
        log.info("gh missing; installing it with brew")
        reason = _act(["brew", "install", "gh"])
        if reason:
            return Outcome(State.FAILED, reason)
    elif chosen == "winget":
        log.info("gh missing; installing it with winget")
        reason = _act(list(WINGET_ARGV))
        if reason:
            return Outcome(State.FAILED, reason)
        if not runs("gh"):
            # Unmeasured on a real Windows host: winget's PATH change reaches new shells, not this process.
            return Outcome(State.INSTALLED, "open a new shell so PATH picks gh up")
    else:
        stopped = _apt_install(euid)
        if stopped is not None:
            return stopped
    if not runs("gh"):
        return Outcome(State.FAILED, f"the {chosen} install finished but gh does not run")
    return _reachable(Outcome(State.INSTALLED, f"through {chosen}"))
