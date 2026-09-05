"""Every step's output on disk, next to the build it came from.

WHY. The step TUI is a Textual app, and Textual takes the mouse while it runs - so the terminal's own
selection stops working and a step's output is visible and unreachable at the same time. Redirecting
the whole command (`> file`) sidesteps the TUI entirely and works, but only for someone who already
knows to do it, and only if they knew BEFORE the run they would want the text. A file written every
time is the answer for everyone else, and it survives the TUI being closed.

WHERE. `<repo>/build/logs/`, the same `build/` a product's `clean` removes - a step log is a build
output, not something to keep. The repo root comes from the registered product context, so the
convention is the kernel's and identical in every product.

WHAT IT IS NOT: a transcript of the whole run, and not appended to. The interesting run is the last
one; a file holding four of them makes finding it the reader's job.
"""
from __future__ import annotations

import re
from pathlib import Path

from simplon import context

# Everything a filesystem would rather not see in a name. A step's identity is usually a dotted command
# (`build.compile`), but it FALLS BACK to the shlex-joined argv, which carries slashes and spaces -
# `/venv/bin/python -u -m orchestrator build` must not become a path four directories deep.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def log_name(command: str) -> str:
    """The file name for a step identity. Pure."""
    safe = _UNSAFE.sub("-", command).strip("-/")
    return f"{safe or 'step'}.log"


def log_directory() -> Path | None:
    """`<repo>/build/logs`, or None when no product is registered."""
    try:
        root = context.current().root
    except RuntimeError:
        return None
    return root / "build" / "logs"


def write(command: str, output: str) -> Path | None:
    """Write one step's output; returns the path, or None when there was nowhere to put it.

    A missing product context is not an error here: the kernel is imported in places that never
    register one - a unit test, a scaffolder run - and writing a log is a courtesy. A courtesy that
    raises is a defect.
    """
    directory = log_directory()
    if directory is None:
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / log_name(command)
        path.write_text(output.rstrip("\n") + "\n", encoding="utf-8")
    except OSError:
        return None       # a read-only checkout is a reason to lose the log, never the run
    return path
