"""The single subprocess seam for the *ctl orchestrators. Every external call (docker, colima,
containerlab, curl, git) goes through `run()`, which returns the REAL exit code instead of relying on
bash's implicit `$?`/`&&` chaining - the class of footgun (#95: `modprobe` without `-a` returning rc 0)
that motivated netctl #102. It also gives the Textual TUI one place to stream per-step output from.

WHEN TO CAPTURE, decided once here rather than per call site (si#143).

    Capture (`run`, the default) when the CALLER INSPECTS the output and reports its own verdict.
    Do not capture (`stream`) when the step's whole content is a transfer somebody is waiting on.

The second half is the one that goes wrong quietly, because capturing never fails - it only makes a
long step silent, and silence looks the same as speed until somebody is four minutes into it wondering
whether the process is alive. This kernel uploads no bytes itself: every upload is `oras push`,
`gh release upload`, `docker push` or `dotnet nuget push`, so the tool's own reporting is the ONLY
thing there is, and capturing it leaves the user with nothing while the tool talks to a string.

There is a second reason, and it is the one that rules out the clever middle - `run_stream` below, which
looks like it would give live output AND a captured reason. It gives neither, measured on one child
that prints `a  17%\r` and then `b 100%\n`:

    run_stream   the child reports PIPE, and the caller receives ['a  17%', 'b 100%']
    stream       the child reports TTY,  and the caller receives b'a  17%\rb 100%\n'

Two things go at once. A repaint ends a SEGMENT, so a bar arrives as a page of lines - si#144 measured
405 carriage returns in one `git clone --progress` coming out as 412 of them. And the child is looking
at a pipe, which is what every tool that renders progress checks before deciding whether to render any;
`gh` writes nothing at all to one. `capture=False` inherits the real descriptors, and that is the only
arrangement in which the tool is even asked.

The two halves sit four lines apart in `simplon/tasks/asset.py`, which is where the rule is easiest to
read. `gh release create` is captured, because `_already_there()` reads "already exists" out of the text
to tell a lost race from a real failure - a verdict nothing else can reach. `gh release upload` is not,
because nobody reads its text and everybody waits for its bytes. A failure there says the rc and points
at the output directly above it, the way `tasks/image.py` and `tasks/nuget.py` already do; quoting text
the kernel no longer holds would be the trade this rule exists to avoid, one silence for another.
"""
from __future__ import annotations

import codecs
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable

#: How long the reader waits for a line to FINISH before handing over what it already has.
#:
#: The measurement that chose it (si#144), on `./simplon.sh test all` - this kernel's own longest step.
#: pytest writes one dot per test and flushes it, and the line completes every 72 tests, so the child's
#: 2865 writes reached `on_line` as 126 lines and a byte waited up to 11.37s. With this flush the worst
#: wait is 1.50s and the mean falls from 0.203s to 0.032s. The price is paid in the step log, in lines
#: the child did not end itself: 126 -> 190 for that step. 0.05s buys 0.65s worst for 210 lines, 0.20s
#: gives 1.76s for 159. This is the knee.
LIVE_FLUSH = 0.1

#: A line break as a child writes one: CRLF FIRST, so a Windows ending is one break rather than a break
#: and an empty line. A bare `\r` is a repaint, and it ends a segment for the same reason a newline
#: does - what came before it is finished text a reader can see.
_BREAK = re.compile(r"\r\n|\r|\n")

#: The reader thread's name. Named rather than anonymous so a test can make `os.read` fail for THIS
#: thread and no other - patching it globally in a test process breaks whatever else is reading a pipe.
_PUMP_THREAD = "run_stream"

#: How long the unwind waits for the reader thread after killing the child. Only the exception path ever
#: waits at all; see `run_stream`'s `finally`.
_UNWIND_GRACE = 5.0


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
    (`simplon.context.current().root`) to reproduce what a Makefile recipe did from the top of the tree.
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


def run_stream(argv: list[str], on_line: Callable[[str], None],
               *, flush_after: float = LIVE_FLUSH) -> int:
    """Run `argv` and feed each output SEGMENT (stdout+stderr merged) to `on_line` AS IT IS PRODUCED,
    then return the real exit code. This is what lets the TUI show a long step's output live
    (build/up/seed) instead of only on completion.

    A SEGMENT, not a line, and that is the whole of si#144. `for line in proc.stdout` hands over on a
    terminator, and the tools here write output that has none yet: pytest writes one dot per test and
    completes the line every 72 of them. Measured on `./simplon.sh test all`, the child wrote 2865 times
    and the reader handed over 126 times, a byte waiting up to 11.37 seconds - the pane frozen for
    eleven seconds while the child was writing every few milliseconds. So this reads CHUNKS, splits on
    `\r` and `\n`, and hands over the partial line it is holding when the child has written nothing for
    `flush_after` seconds. The same measurement after: 1.50s worst, 0.032s mean.

    The carriage return was the ticket's own first suspect and is NOT the cause: `text=True` used to
    turn on universal newlines, which already made `\r` a terminator, and a `git clone --progress`
    writing 405 of them came out as 412 lines with nothing delayed. It is the un-terminated tail. The
    `\r` split is kept here because dropping `text=True` would otherwise lose it.

    What this is NOT is a pty. A pty is the general answer to a child that BLOCK-BUFFERS, and no child
    here does: docker, containerlab, oras, curl, git and this kernel's own `python -u` child all deliver
    as they write into a plain pipe. What a pty would add is 45x the bytes and 397 carriage returns on
    one `docker build`, into `steplog`'s file and into the run transcript somebody attaches to a ticket.

    A PUMP THREAD rather than `select`, because `select.select` accepts only sockets on Windows and this
    kernel runs there (`simplon.cmd`, and cleon's Windows cell in `product.StepFactoryContext`). It
    reads bytes and nothing else, so `on_line` stays on the CALLER's thread - which is what the TUI's
    `call_from_thread` assumes. The loop ends on a zero-length read and NOT on `proc.poll()`: today's
    reader runs until the pipe closes, so a child that hands stdout to something it spawned is still
    waited for, and ending on the exit status would drop that output silently.
    """
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    chunks: queue.Queue[bytes] = queue.Queue()
    # What the pump could not read. A read that FAILED is not a stream that ended, and the two are
    # otherwise indistinguishable here: `proc.wait()` still returns the child's real exit code, so a
    # green rc would be reported over half a log. Collected rather than raised in the thread, because a
    # thread cannot raise into its caller, and re-raised below - after the sentinel, so the reader is
    # never left waiting on a queue nothing will fill.
    unread: list[OSError] = []

    def pump() -> None:
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError as error:
                unread.append(error)
                chunk = b""
            chunks.put(chunk)
            if not chunk:
                return

    thread = threading.Thread(target=pump, name=_PUMP_THREAD, daemon=True)
    thread.start()
    # An INCREMENTAL decoder: a chunk boundary can fall inside a multi-byte character, which `text=True`
    # used to hide. `errors="replace"` keeps the old contract - output is shown, never raised on.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending = ""
    try:
        while True:
            try:
                chunk = chunks.get(timeout=flush_after)
            except queue.Empty:
                if pending:                    # the child went quiet holding an unfinished line
                    on_line(pending)
                    pending = ""
                continue
            if not chunk:
                break
            pending += decoder.decode(chunk)
            parts = _BREAK.split(pending)
            pending = parts.pop()              # what follows the last break is not finished yet
            for part in parts:
                on_line(part)
        pending += decoder.decode(b"", True)
        if pending:
            on_line(pending)
        if unread:
            raise unread[0]
    except BaseException:
        # `on_line` raised (in the TUI it is a `call_from_thread`, which can), or the pipe could not be
        # read. Either way the caller has abandoned this run, and without the kill the child KEEPS
        # RUNNING and is never reaped - measured on both this reader and the one it replaces, `ps
        # --ppid` still showing the child after the exception had propagated.
        proc.kill()
        proc.wait()
        raise
    finally:
        # Instant on the ordinary path - the pump returned before it sent the sentinel this loop broke
        # on. The grace is for the unwind, where a grandchild holding the write end could otherwise turn
        # a raised exception into a hang; the thread is a daemon, so abandoning it costs nothing.
        thread.join(_UNWIND_GRACE)
        proc.stdout.close()
    return proc.wait()
