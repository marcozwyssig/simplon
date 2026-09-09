"""Every step's output on disk, next to the build it came from.

WHY. The step TUI is a Textual app, and Textual takes the mouse while it runs - so the terminal's own
selection stops working and a step's output is visible and unreachable at the same time. Redirecting
the whole command (`> file`) sidesteps the TUI entirely and works, but only for someone who already
knows to do it, and only if they knew BEFORE the run they would want the text. A file written every
time is the answer for everyone else, and it survives the TUI being closed.

WHERE. `<repo>/build/logs/`, the same `build/` a product's `clean` removes - a step log is a build
output, not something to keep. The repo root comes from the registered product context, so the
convention is the kernel's and identical in every product.

WHAT A STEP LOG IS NOT: the whole run. Since si#148 that second artefact exists beside them, in the
same directory and under the same overwrite rule - `run_header` + `write_run` keep `run-transcript.log`,
which is every step in order with its rc and its duration under a header that identifies the run. The
two are deliberately separate files: the transcript is what somebody attaches to a ticket, and a step
log is the whole of one step's output, which is usually far too much of it.

NEITHER IS APPENDED TO. The interesting run is the last one; a file holding four of them makes finding
it the reader's job.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
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


# --- the run transcript's own file and header (si#148 items 3 and 4) ----------------------------------

#: The transcript's file name. ONE file, overwritten per run, beside the per-step logs and under the same
#: `clean` - for the reasons this module's own docstring gives about appending.
#:
#: The collision is real and accepted: a step whose identity normalises to `run-transcript` would write
#: over it. Defending against that would mean a second directory, which is a second thing to explain and
#: a second thing to clean, bought against a command nobody has named in any product measured.
RUN_TRANSCRIPT = "run-transcript.log"

#: How wide the header's labels are padded, so the four facts line up and can be read as a column rather
#: than as four sentences.
_LABEL = 14


def _environment_name() -> str:
    """The environment this run targeted, or `not set`.

    Read from `context.ENVIRONMENT_ENV`, the kernel's own mirror of what `cli.main` selected - see that
    constant for why the product's own variable cannot be read here. Unset is an ANSWER: a pipeline built
    outside `main` targeted no environment, and printing the manifest's default would state a fact the
    run did not produce.
    """
    return os.environ.get(context.ENVIRONMENT_ENV, "").strip() or "not set"


def _instance_id() -> str:
    """The lab instance this run acted on, or `not declared`.

    `labinstance.resolve` fails loudly on a manifest with no `instance:` section, which is right for a lab
    command - a typo there silently targets the wrong tenant - and wrong here. simplon's own manifest
    declares none, and a transcript that refuses to be written because the run had no lab would be a
    courtesy that raises. Every other failure degrades the same way and for the same reason.
    """
    from simplon import labinstance      # local: labinstance reads the manifest, this module is a leaf

    try:
        return labinstance.resolve()
    except Exception:  # noqa: BLE001 - a missing/invalid section, an unreadable manifest, no product
        return "not declared"


def _provenance() -> str:
    """si#125's line: which simplon assembled this CLI, and from where.

    The import is function-local and that is not a style preference: `simplon.cli` imports
    `orchestrator.product`, which imports `orchestrator.steps`, which imports THIS module, so a
    module-level import would close a cycle. Calling it rather than restating it is the point of item 4 -
    the help screen and the transcript have to answer this question identically or one of them is wrong.
    """
    try:
        from simplon.cli import provenance_line
        return provenance_line()
    except Exception:  # noqa: BLE001 - a header is a courtesy; typer missing must not cost the file
        return "unknown"


def run_header(name: str, started: datetime) -> list[str]:
    """The transcript's first lines: which run, when it started, in which environment and instance, and
    which simplon answered (si#148 item 4).

    This is what turns a pasted excerpt from anecdote into evidence. `_step_header` gives the command and
    its help, which says WHAT ran; none of it says when, where, or which installation - and si#125 has
    just established that the third of those is the one that silently differs between a pinned wheel, an
    agent's venv and a maintainer's editable checkout.

    EVERY FIELD DEGRADES TO A PHRASE. The same rule as `write` below and as `cli._install_marker`: a
    header is written so a red run can be attached to a ticket, and a header that raises loses the file
    on exactly the runs that needed it.

    The start time is WALL time and the durations beside the steps are monotonic, deliberately: a reader
    correlates the header against a CI log, a chat message or a deployment window, and a monotonic
    instant correlates with nothing outside this process.
    """
    return [f"=== simplon run transcript: {name} ===",
            f"{'started:':<{_LABEL}}{started:%Y-%m-%d %H:%M:%S}",
            f"{'environment:':<{_LABEL}}{_environment_name()}",
            f"{'instance:':<{_LABEL}}{_instance_id()}",
            f"{'tooling:':<{_LABEL}}{_provenance()}"]


def write_run(text: str) -> Path | None:
    """Write the run transcript; returns the path, or None when there was nowhere to put it.

    A sibling of `write` above and degrading identically - it is the same directory, the same
    overwrite-per-run rule and the same "a courtesy that raises is a defect". What differs is only that
    there is one of these per RUN rather than one per step.
    """
    directory = log_directory()
    if directory is None:
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / RUN_TRANSCRIPT
        path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    except OSError:
        return None       # a read-only checkout is a reason to lose the transcript, never the run
    return path
