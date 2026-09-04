"""Where a bootstrapped binary lands, and how it comes within reach of the process that fetched it.

Two gates now provision a tool the host did not have - docker's static CLI (netctl#477) and oras
(simplon: the OCI-artifact CLI every GHCR push and pull needs). Both answered the same two questions,
and a convention restated in two modules is a convention that drifts in one of them: the directory is
`<repo>/build/tools/bin` because a fetched binary is a BUILD OUTPUT and must die with `clean`, and the
process that fetched it has to prepend that directory to its own PATH, since a child `oras` or `docker`
resolves through PATH like any other.

The repo root comes from the registered product context, never from an import: the same body serves
every product in the family.
"""
from __future__ import annotations

import os
from pathlib import Path

from simplon import context


def bin_dir() -> Path:
    """The product-owned tool directory a bootstrap installs into (wiped by `clean` with build/)."""
    return context.current().root / "build" / "tools" / "bin"


def prepend_to_path(directory: Path | str) -> None:
    """Put `directory` FIRST on this process' PATH, once.

    Idempotent on purpose: several gates may run in one process (a build that fetches a bundle and later
    publishes one calls the oras gate twice), and a PATH that grows a duplicate per call is a variable
    that eventually stops fitting in an exec's environment.
    """
    entry = str(directory)
    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []
    if entries and entries[0] == entry:
        return
    os.environ["PATH"] = os.pathsep.join([entry, *[e for e in entries if e != entry]])
