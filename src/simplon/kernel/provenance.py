"""Which simplon is answering: the line the top-level `--help` ends with, and the run transcript's header
repeats (si#125, si#148 item 4).

KERNEL, NOT CLI (si#391). The help screen is the cli's and the transcript is the kernel's, and the two have
to answer this question identically or one of them is wrong. The answer depends on nothing but `simplon`
itself and its installed distribution, so it lives at the bottom, where both may import it.
"""
from __future__ import annotations

import json
import os
from importlib.metadata import PackageNotFoundError, distribution as _distribution

import simplon

# --- which simplon is answering (si#125) --------------------------------------------------------------
#
# THE GAP. `<product> --help` names every command the manifest declares and said nothing about the tooling
# that assembled it. A product pins the kernel in its requirements, an agent installs it into a venv, and a
# maintainer keeps an editable checkout on the same machine - and all three printed a byte-identical help
# screen. netctl had to close that from the outside (netctl#1644 asserts in a test that the pinned version,
# the installed version and the imports present in the wheel agree), because nothing the CLI printed could
# have told anyone.
#
# WHY THE WORDING NAMES THE TOOL AND NOT A NUMBER. The kernel renders help for the PRODUCT's app, so a bare
# `simplon 0.9.0` sits under the product's own commands and is read as the product's version. "assembled by"
# says whose provenance this is, and it is literally what `assemble` below did.


def _install_marker() -> str:
    """What the installed DISTRIBUTION adds to the location, or "" when it adds nothing.

    Two facts are worth a word, and both are read from the distribution rather than guessed from the path.
    `pip install -e` records PEP 610 `direct_url.json` with `dir_info.editable`, which is the authoritative
    answer to the question si#125 is actually about - an editable checkout of a TAGGED tree resolves a
    clean release version, so the version alone says nothing and only the path differs, and a path is read
    as noise. A missing distribution is the other: nothing installed this kernel at all, which is the bare
    `sys.path` state `simplon.__init__` reports as `0.0.0.dev0+unknown`.

    Everything else is silence, on purpose. A half-written dist-info, an unreadable file, a
    `direct_url.json` in a shape no packaging tool here predicted: the marker is a decoration on a help
    screen and the help screen has to render, so each of those degrades to "no marker" rather than to a
    traceback. The location is read off the imported module and cannot fail the same way, so the line
    still carries the answer.
    """
    try:
        dist = _distribution("simplon")
    except PackageNotFoundError:
        return "no installed distribution"
    except Exception:  # a broken installation is still an installation - say nothing rather than raise
        return ""
    try:
        editable = bool(json.loads(dist.read_text("direct_url.json") or "{}")["dir_info"]["editable"])
    except (OSError, ValueError, TypeError, KeyError):
        # Every shape the file can arrive in and not answer the question. OSError is the read itself,
        # and it is insurance rather than a live path: the stock `PathDistribution.read_text` already
        # suppresses a missing or unreadable file and answers None, so only a non-stock finder gets
        # here. ValueError covers both undecodable (a `UnicodeDecodeError` IS one) and not-JSON,
        # TypeError a payload that is not an object, and KeyError a missing `dir_info` - which is the
        # released wheel carrying no `direct_url.json` at all, the COMMON case rather than an error.
        editable = False
    return "editable install" if editable else ""


def provenance_line() -> str:
    """The single line the top-level `--help` ends with: which simplon assembled this CLI, and from where.

    Both halves can be absent and neither absence may cost the reader their help screen, so each degrades
    to a phrase instead of to an exception. `simplon.__version__` already has a fallback of its own, so an
    empty one means the module is not what it should be - rendering `assembled by simplon  (...)` would
    read as a formatting bug, naming it reads as the fact it is. The location comes off the imported
    module: `__file__` where there is one, otherwise every entry of `__path__` (a namespace package has no
    single location, and naming them all beats guessing at the first).

    The location is read off the IMPORTED MODULE and the marker off the INSTALLED DISTRIBUTION, and on a
    machine where both a checkout and an install of the same name sit on `sys.path` those are not
    necessarily the same copy - the path then names the code that is answering, which is the half that
    matters, while the marker describes the dist-info that was found. Nothing here can resolve that, and
    the path is the one a reader acts on.
    """
    version = str(getattr(simplon, "__version__", "") or "").strip()
    head = f"assembled by simplon {version}" if version else "assembled by simplon, version unknown"
    file = getattr(simplon, "__file__", None)
    location = (os.path.dirname(str(file)) if file
                else ", ".join(str(entry) for entry in getattr(simplon, "__path__", ())))
    where = ", ".join(part for part in (_install_marker(), location or "location unknown") if part)
    return f"{head} ({where})"
