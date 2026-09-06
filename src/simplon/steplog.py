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


def existing_log(command: str) -> Path | None:
    """The file a step's output really landed in, or None when there is none.

    It answers the question a red run asks - "where do I read the whole of it?" - and it answers it by
    LOOKING, not by computing a name. Not every step writes a log: `argv_step` does, on every run and
    whatever the rc, while a hand-built `action` step keeps its output in the Outcome. A summary that
    printed `build/logs/<step>.log` for all of them would hand a reader a path to nothing, which is worse
    than saying nothing - the reader spends the trip before finding out. The two answers are therefore
    kept apart: a path that exists, or None so the caller can say it does not know (#49).
    """
    directory = log_directory()
    if directory is None:
        return None
    path = directory / log_name(command)
    return path if path.is_file() else None


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
