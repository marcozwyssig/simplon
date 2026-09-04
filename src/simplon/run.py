"""The single subprocess seam for the *ctl orchestrators. Every external call (docker, colima,
containerlab, curl, git) goes through `run()`, which returns the REAL exit code instead of relying on
bash's implicit `$?`/`&&` chaining - the class of footgun (#95: `modprobe` without `-a` returning rc 0)
that motivated netctl #102. It also gives the Textual TUI one place to stream per-step output from.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Result:
    """The outcome of one subprocess: the real return code and (optionally captured) streams."""

    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


def run(argv: list[str], *, check: bool = False, capture: bool = True,
        timeout: float | None = None, input_text: str | None = None,
        cwd: str | None = None) -> Result:
    """Run `argv` (a list, never a shell string) and return a Result with the real rc.

    capture=True returns stdout/stderr as text; capture=False streams them to the terminal (used by the
    interactive flows). check=True raises CalledProcessError on a non-zero rc (use sparingly - the point
    of this wrapper is to inspect rc explicitly, not to let it explode). input_text, when given, is fed to
    the process's stdin (e.g. `tee`-ing a script into the VM). cwd runs the process from that directory
    (e.g. pytest from the test dir so conftest.py is importable).
    """
    proc = subprocess.run(
        argv,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
        input=input_text,
        cwd=cwd,
    )
    return Result(
        rc=proc.returncode,
        out=(proc.stdout or "") if capture else "",
        err=(proc.stderr or "") if capture else "",
    )


def stream(argv: list[str], *, cwd: str | None = None) -> int:
    """Run one external command with its output going STRAIGHT to the terminal, and return the real rc.

    The shape a command IMPL wants, and the one every adopting product kept rebuilding on top of `run`
    (platform#43): a tool's own output IS the user interface - a test runner's progress, a build's log, a
    compose bring-up - so capturing it would only hide it, and the rc is the single thing the caller needs
    back. `cwd` is where the command runs; a product passes its repo root
    (`delivery.context.current().root`) to reproduce what a Makefile recipe did from the top of the tree.
    """
    return run(argv, capture=False, cwd=cwd).rc


def chain(*commands: list[str], cwd: str | None = None) -> int:
    """Run commands in order, STOPPING at the first failure, and return ITS rc (0 when all succeed).

    The behaviour a `make` recipe's line-by-line execution had, and the reason a two-step gate cannot just
    run both and take the last rc: what the caller has to report is the step that actually failed, and
    what a developer needs is for the run to stop there rather than pile a second failure on top of the
    first one's cause.
    """
    for argv in commands:
        rc = stream(argv, cwd=cwd)
        if rc != 0:
            return rc
    return 0


def run_stream(argv: list[str], on_line: Callable[[str], None]) -> int:
    """Run `argv` and feed each output line (stdout+stderr merged) to `on_line` AS IT IS PRODUCED, then
    return the real exit code. This is what lets the TUI show a long step's output live (build/up/seed)
    instead of only on completion. Line-buffered; the caller decides what to do with each line (append to
    a RichLog, print indented, ...).
    """
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        on_line(line.rstrip("\n"))
    proc.stdout.close()
    return proc.wait()
