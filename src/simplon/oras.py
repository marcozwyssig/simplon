"""The oras gate: the host has the OCI-artifact CLI by the time a package operation needs it.

WHY A GATE AND NOT A README LINE. `oras` is what moves a plain file in and out of a registry as an OCI
artifact (see githubpackages), so every GHCR push and pull in the family goes through it - and no host
ships it. Until now a missing oras failed a build halfway through with an install instruction, which is
a fine message and still a stopped build: the same command works in CI, where the workflow adds
oras-project/setup-oras, and fails on the developer's machine. A tool the kernel cannot work without is
the kernel's to provide.

PACKAGE MANAGER FIRST, PINNED RELEASE AS THE FALLBACK. Where a host already has a manager that carries
oras, using it leaves the binary somewhere the operator can see, update and remove by the usual means -
it is their machine. That is Homebrew, on macOS AND on Linux. Everywhere else the release archive from
oras-project/oras is unpacked into the product's own build/tools/bin, which needs no manager and no
administrator.

WINDOWS HAS NO MANAGER TO TRY, and this was checked rather than assumed: winget carries no
`manifests/o/oras`, Chocolatey has no package, the Scoop main bucket has no manifest. So on Windows the
download is not the fallback, it is the path. `_MANAGERS` is a table for exactly that reason - the day
a winget manifest exists, it is one row.

WHAT THIS MODULE DOES NOT DO: verify a checksum. The archive comes from the pinned release over HTTPS,
which is the same trust the docker static-CLI bootstrap and every `curl | sh` installer in this repo
already extend. Naming it here so the next reader knows it is a decision, not an oversight.
"""
from __future__ import annotations

import platform
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Callable

from simplon import fetch, log, tools
from simplon.run import run

# Pinned release; bump deliberately. The tag carries no host in it - one version, every platform.
ORAS_VERSION = "1.3.4"
_RELEASES = "https://github.com/oras-project/oras/releases/download"

# platform.machine() spellings -> the two architecture names oras publishes under.
_ARCHES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
# platform.system() -> the archive kind that host's asset uses.
_ARCHIVES = {"darwin": "tar.gz", "linux": "tar.gz", "windows": "zip"}
# platform.system() -> (the manager's own binary, the argv that installs oras with it). A host is only
# offered a manager it actually has; see the module docstring for why Windows has no row.
_MANAGERS: dict[str, tuple[str, list[str]]] = {
    "darwin": ("brew", ["brew", "install", "oras"]),
    "linux": ("brew", ["brew", "install", "oras"]),
}


class OrasError(RuntimeError):
    """oras could not be provided. The message names what a human does about it."""


def tools_bin() -> Path:
    """The product-owned directory a downloaded oras lands in."""
    return tools.bin_dir()


def binary_name(system: str) -> str:
    """The file name oras has on that host. Pure."""
    return "oras.exe" if system.lower() == "windows" else "oras"


def release_url(system: str, machine: str, version: str = ORAS_VERSION) -> str:
    """The pinned release asset for a platform.system() / platform.machine() pair. Pure.

    Both halves are validated rather than pasted into a URL: an unsupported host would otherwise fail as
    a 404 in the middle of a download, which names neither the host nor the fix.
    """
    os_name = system.lower()
    archive = _ARCHIVES.get(os_name)
    if archive is None:
        raise OrasError(f"oras publishes no release for '{system}'; supported are "
                        f"{', '.join(sorted(_ARCHIVES))}")
    arch = _ARCHES.get(machine.lower())
    if arch is None:
        raise OrasError(f"oras publishes no release for architecture '{machine}'; supported are "
                        "x86_64/amd64 and aarch64/arm64")
    return f"{_RELEASES}/v{version}/oras_{version}_{os_name}_{arch}.{archive}"


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def installer_argv(system: str, *, have: Callable[[str], bool] | None = None) -> list[str] | None:
    """The command that installs oras with a package manager this host HAS, or None. Pure given `have`.

    None is an ordinary answer, not a failure: it means the download path, which every host can take.
    """
    look = have or _have
    manager = _MANAGERS.get(system.lower())
    if manager is None:
        return None
    tool, argv = manager
    return list(argv) if look(tool) else None


def _run_installer(argv: list[str]) -> bool:
    """Run the package manager and answer whether an oras ACTUALLY appeared.

    The verification is the point. `brew install` exits 0 on a formula it could not link, on a tap that
    resolved to nothing useful, and on an install into a prefix that is not on this PATH - and a gate
    that trusts the exit code then reports success to a build that has no oras.
    """
    log.info(f"oras missing; installing it with {argv[0]}")
    run(argv, capture=False)
    return _have("oras")


def _fetch_release(dest: Path) -> None:
    """Download the pinned archive and extract ONLY the oras binary to `dest`.

    The archive also carries a LICENSE and a README, which have no business in a bin directory.
    """
    url = release_url(platform.system(), platform.machine())
    log.info(f"oras missing and no package manager carries it; fetching {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    archive = dest.parent / f"oras-download{'.zip' if url.endswith('.zip') else '.tgz'}"
    try:
        fetch.download(url, archive, label=f"oras {ORAS_VERSION}")
        member = dest.name
        if url.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                dest.write_bytes(zf.read(member))
        else:
            with tarfile.open(archive) as tar:
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise OrasError(f"the oras archive at {url} holds no '{member}'")
                dest.write_bytes(extracted.read())
    finally:
        archive.unlink(missing_ok=True)
    dest.chmod(0o755)


def ensure_oras() -> None:
    """oras on PATH by the time this returns, or an OrasError saying what a human does about it.

    The order is deliberate: an oras the host already has wins over anything this installs, a package
    manager wins over a private copy, and the private copy in build/tools/bin is the last resort that
    always works. A copy from an earlier run is reused rather than re-downloaded.
    """
    if shutil.which("oras"):
        return

    system = platform.system()
    argv = installer_argv(system)
    if argv is not None and _run_installer(argv):
        return

    dest = tools_bin() / binary_name(system)
    if not dest.is_file():
        _fetch_release(dest)
    if not dest.is_file():
        raise OrasError(
            f"could not provide oras: nothing was installed and no binary is at {dest}. Install it by "
            "hand from https://github.com/oras-project/oras/releases, or add oras-project/setup-oras "
            "to the workflow.")
    tools.prepend_to_path(dest.parent)
