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

THE EXTENSIONS A PRODUCT DECLARES (si#630, Marco, 2026-11-11). A top-level `gh:` section with `extensions:`,
a list of `owner/repo` or `owner/repo@<version>`, is product data: `support install` installs each one after
the gate above, and only when that gate left a gh that runs. The pin is optional: with `@<version>` the
install is `gh extension install <owner/repo> --pin <version>`; without one the latest release is installed
once and left alone. `gh extension list` is the probe, so a second run installs nothing. Every extension is
attempted even when an earlier one failed, and each is reported in its own words.

RE-PINNED, NOT REFUSED, BECAUSE `--pin` OVER AN INSTALL IS A SILENT NO-OP. MEASURED (2026-11-11, gh 2.103.3,
a throwaway GH_CONFIG_DIR and XDG_DATA_HOME, `github/gh-stack`): with v0.2.1 installed, `gh extension install
github/gh-stack --pin v0.3.0` printed "! Extension github/gh-stack is already installed", exited 0, and the
list still said v0.2.1; the same for no pin and for a pin no release has (v9.9.9). On a fresh directory the
missing release exits 1 ("Could not find a release of github/gh-stack for v9.9.9"). So rc 0 from the install
says nothing about the version, and the list has to decide. An extension listed at another version than its
pin is removed (`gh extension remove <owner/repo>`, rc 0) and installed at the pin, because a pin bumped in the
manifest should reach every machine without a hand on each one, which is what si#630 is for. WHAT THAT COSTS,
said rather than left to be found: when the install after the remove fails (a pin no release has), the
extension is gone until the manifest is fixed, and the run says so.

A LIMIT OF THE PROBE, MEASURED THE SAME DAY: a script (git) extension pinned to a tag is listed at a commit
prefix, not the tag (`gennaro-tedesco/gh-f --pin v1.8.0` lists `59a2c598`), so such a pin never reads as
matching and is re-pinned on every run, visibly. A precompiled extension (gh-stack is one) is listed at its
release tag; a pin that is a full commit sha matches the listed prefix.

AND A gh WITH NO TOKEN CANNOT LIST: `gh extension list` exits 4 ("To get started with GitHub CLI, please run:
gh auth login"), measured the same day. Every declared extension is then FAILED in gh's own words, because a
failed probe is not an empty list; logging in is `vcs auth-scopes`'s, not this gate's. Against the real gh
with a token, `ensure_extensions` for gh-stack went INSTALLED at v0.2.1, PRESENT, re-pinned to v0.3.0, and
FAILED for v9.9.9 with "it is not installed now".
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
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


# --- the extensions a product declares (si#630) -----------------------------------------------------

#: The top-level manifest section, and the keys it reads.
SECTION = "gh"
READ_KEYS = ("extensions",)

#: `owner/repo` or `owner/repo@<version>`: GitHub's owner and repository characters, a version without
#: whitespace.
_ENTRY = re.compile(r"(?P<repo>[A-Za-z0-9-]+/[A-Za-z0-9._-]+)(?:@(?P<pin>\S+))?")

#: The time limit of `gh extension list`; an install or a remove gets the install limit.
LIST_TIMEOUT_S = 60


@dataclass(frozen=True)
class Extension:
    repo: str
    pin: str = ""   # "" when the manifest leaves the version to the latest release

    def __str__(self) -> str:
        return f"{self.repo}@{self.pin}" if self.pin else self.repo


def declared_extensions(data: Mapping[str, object], toolchains: tuple[str, ...],
                        source: str = "manifest") -> tuple[Extension, ...]:
    """The extensions the manifest's `gh:` section names, in its order; `()` when it names none.

    `toolchains` is the product's validated `toolchains:` list: a `gh:` section without the `gh` toolchain
    is a declaration nothing reads, and saying nothing about it would be the recurring defect."""
    raw = data.get(SECTION)
    if raw is None:
        return ()
    if "gh" not in toolchains:
        raise ValueError(f"{source}: the manifest has a '{SECTION}:' section, but 'gh' is not in 'toolchains:', "
                         f"so nothing installs its extensions - add `gh` to 'toolchains:' (`support toolchain "
                         f"gh`), or remove the section")
    if not isinstance(raw, Mapping):
        raise ValueError(f"{source}: '{SECTION}:' must be a mapping with 'extensions:', got {raw!r}")
    unknown = sorted(str(key) for key in raw if key not in READ_KEYS)
    if unknown:
        raise ValueError(f"{source}: '{SECTION}:' declares unknown key(s) {', '.join(unknown)} - it reads "
                         f"{', '.join(READ_KEYS)}")
    entries = raw.get("extensions")
    if entries is None:
        return ()
    if not isinstance(entries, (list, tuple)):
        raise ValueError(f"{source}: '{SECTION}.extensions' must be a list of 'owner/repo' or "
                         f"'owner/repo@<version>', got {entries!r}")
    seen: dict[str, Extension] = {}
    for entry in entries:
        match = _ENTRY.fullmatch(entry) if isinstance(entry, str) else None
        if match is None:
            raise ValueError(f"{source}: '{SECTION}.extensions': {entry!r} is not 'owner/repo' or "
                             f"'owner/repo@<version>'")
        extension = Extension(match["repo"], match["pin"] or "")
        if extension.repo.lower() in seen:
            raise ValueError(f"{source}: '{SECTION}.extensions' names '{extension.repo}' twice")
        seen[extension.repo.lower()] = extension
    return tuple(seen.values())


def _installed(listing: str) -> dict[str, str]:
    """`gh extension list` (captured, so tab-separated: name, owner/repo, version) as {owner/repo: version},
    keys lower-cased because GitHub's names are case-insensitive."""
    found: dict[str, str] = {}
    for line in listing.splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            found[fields[1].strip().lower()] = fields[2].strip()
    return found


def _at_pin(listed: str, pin: str) -> bool:
    """True when the listed version is the pin: the tag itself, or the commit prefix a git extension pinned
    to a full sha is listed at (measured, see the module docstring)."""
    return listed == pin or (re.fullmatch(r"[0-9a-f]{7,}", listed) is not None and pin.startswith(listed))


def _gh(runner: Callable[..., object], argv: list[str], timeout_s: float) -> str:
    """Run one gh command; "" on success, else why, with gh's own last words."""
    try:
        result = runner(["gh", *argv], timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return f"gh {argv[0]} {argv[1]} timed out after {timeout_s:g} s"
    except OSError as exc:
        return f"gh could not be started: {exc}"
    if result.rc == 0:
        return ""
    said = (result.err or result.out).strip().splitlines()
    return f"gh {argv[0]} {argv[1]} exited {result.rc}" + (f": {said[-1]}" if said else "")


def ensure_extensions(extensions: tuple[Extension, ...], *,
                      runner: Callable[..., object] = run) -> list[tuple[Extension, Outcome]]:
    """Each declared extension PRESENT, INSTALLED, or FAILED with why; every one attempted.

    `runner` is `simplon.kernel.run.run`'s shape; tests pass a fake. Assumes a gh that runs: the caller asks
    only after the gate left one."""
    if not extensions:
        return []
    timeout_s = hostinstall.INSTALL_TIMEOUT_S
    try:
        listing = runner(["gh", "extension", "list"], timeout=LIST_TIMEOUT_S)
        listed_ok = listing.rc == 0
        why = "" if listed_ok else f"gh extension list exited {listing.rc}: {(listing.err or '').strip()}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        listed_ok, why = False, f"gh extension list failed: {exc}"
    if not listed_ok:
        # Without the list nothing is known to be installed or not: a failed probe is not an empty result.
        return [(extension, Outcome(State.FAILED, why)) for extension in extensions]
    installed = _installed(listing.out)
    outcomes: list[tuple[Extension, Outcome]] = []
    for extension in extensions:
        install = ["extension", "install", extension.repo, *(["--pin", extension.pin] if extension.pin else [])]
        listed = installed.get(extension.repo.lower())
        if listed is not None and (not extension.pin or _at_pin(listed, extension.pin)):
            outcomes.append((extension, Outcome(State.PRESENT, listed)))
            continue
        if listed is not None:
            reason = _gh(runner, ["extension", "remove", extension.repo], timeout_s)
            if reason:
                outcomes.append((extension, Outcome(State.FAILED, f"at {listed}, not the pin; {reason}")))
                continue
            reason = _gh(runner, install, timeout_s)
            outcomes.append((extension, Outcome(State.FAILED, f"removed {listed} to re-pin, then {reason}; "
                                                              f"it is not installed now") if reason
                             else Outcome(State.INSTALLED, f"re-pinned from {listed}")))
            continue
        reason = _gh(runner, install, timeout_s)
        outcomes.append((extension, Outcome(State.FAILED, reason) if reason else Outcome(State.INSTALLED)))
    return outcomes
