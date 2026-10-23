"""Put text on the desktop clipboard, and say whether it got there (si#516).

Textual's `copy_to_clipboard` writes an OSC 52 escape to the terminal and nothing comes back, so a terminal
that ignores it - VTE does, and Tilix and GNOME Terminal are VTE - turns "copied" into a claim about a copy
that never happened. That is this project's recurring defect at one more seam, and the resolution is the
usual one: widen the outcome so each meaning gets its own value. A copy is CONFIRMED (a clipboard tool took
the text and exited 0), FAILED (it did not, and here is why) or UNCONFIRMED (no tool to hand it to, so the
caller falls back to OSC 52 and must say that nobody can tell whether it landed).

The route is chosen from the session, not from what is installed: `WAYLAND_DISPLAY` before `DISPLAY`,
because under XWayland both are set and the Wayland clipboard is the one the desktop pastes from.
"""
from __future__ import annotations

import enum
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass

#: How long a clipboard tool may take to read its stdin and fork its selection server. Generous: it is a
#: local process, and the only cost of the bound is that a hung tool reads as FAILED instead of freezing
#: the UI.
TIMEOUT_S = 5.0

#: (session variable, tool, argv after the tool's name), in the order they are tried.
_ROUTES = (
    ("WAYLAND_DISPLAY", "wl-copy", ()),
    ("DISPLAY", "xclip", ("-selection", "clipboard")),
    ("DISPLAY", "xsel", ("--clipboard", "--input")),
)


class State(enum.Enum):
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class Result:
    state: State
    route: str          # the tool's name, or "osc52"
    detail: str = ""    # why, when FAILED


def route(env: Mapping[str, str] | None = None) -> list[str] | None:
    """The argv of the clipboard tool this session can reach, or None when only OSC 52 is left."""
    env = os.environ if env is None else env
    for variable, tool, args in _ROUTES:
        if not env.get(variable):
            continue
        found = shutil.which(tool, path=env.get("PATH"))
        if found:
            return [found, *args]
    return None


def copy(text: str, *, env: Mapping[str, str] | None = None) -> Result:
    """Hand `text` to the session's clipboard tool. Never raises: every way it can go wrong is a FAILED.

    UNCONFIRMED means nothing was done here - the caller owns the OSC 52 fallback, because writing to the
    terminal is the UI's business and not this module's.
    """
    env = os.environ if env is None else env
    argv = route(env)
    if argv is None:
        return Result(State.UNCONFIRMED, "osc52")
    name = os.path.basename(argv[0])
    # stdout to /dev/null and stderr to a FILE, never to pipes: xclip and wl-copy fork a server that keeps
    # the selection alive and inherits both descriptors, so a pipe would not close until that server exits
    # - which is when somebody else copies something.
    with tempfile.TemporaryFile() as err:
        try:
            done = subprocess.run(argv, input=text.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=err,
                                  env=dict(env), timeout=TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            return Result(State.FAILED, name, f"{name} did not finish within {TIMEOUT_S:g}s")
        except OSError as exc:
            return Result(State.FAILED, name, f"{name} could not be started: {exc}")
        if done.returncode == 0:
            return Result(State.CONFIRMED, name)
        err.seek(0)
        said = err.read().decode("utf-8", "replace").strip()
    return Result(State.FAILED, name, f"{name} exited {done.returncode}" + (f": {said}" if said else ""))
