"""What the kernel says when a file it has to read or write is held by another process (si#193).

WHY THIS EXISTS AT ALL, AND WHY IT IS NOT A RETRY. `checksum.sha256_of` reads a file and
`fetch.download` writes one, and on Windows either can meet a byte-range lock taken by something that
is not simplon. The failure is OBSERVED rather than imagined: `secure-windows-images`, the Windows and
Packer product si#177 lifted the checksum from, records it in its own troubleshooting table -

    cannot access the file because another process has locked a portion of it

- against a `lib\\` directory that lives under a synchronisation client, holding 5 GB ISOs and 11 GB
  OVAs while it uploads them. Its reader already opens with sharing allowed for writers, which is not
enough: a sharing mode says who may open the file, a byte-range lock says who may touch the bytes.

That product answers the condition with `RETRY_DELAYS = (5, 10, 20, 30, 30)`. This kernel does not, and
declining is the decision this module records rather than an omission it forgot to fix. Ninety-five
seconds over six attempts is a number with no comment beside it, nothing deriving it and no measurement
under it, in a codebase where 450 MB is decimal because a channel rejects at 500 decimal and a 4 MB
chunk says "few reads on a 5 GB file, no real memory cost". Its own maintainer put it best: the tuple
says nothing, which on inspection is the tell that somebody picked it. **Nobody has timed how long a
sync client actually holds a byte range on a file that size.** Until somebody does, a retry loop here
would be the same unjustified number in a worse place - inside a kernel where every other number carries
its reason, and inside a wait a caller cannot see, cannot shorten and cannot interrupt.

WHAT IS DONE INSTEAD, and why it needs no measurement to be worth doing. The raw failure is a Windows
`OSError` whose `strerror` names no path a human can act on: it says a process has locked a portion of
the file and stops there, and the operator's next question - which process, and what do I change - is
exactly the one the reporting product already answered in prose. So the error is renamed and the answer
is put in the message. `FileLockedError` is a type a caller can name in an `except`, and its text says
which process class is likely holding the file, what to exclude, and that no retry is coming. That is a
diagnosis in this repository's sense: without it the failure is not silent, merely unhelpful, and the
cost is one branch on a path that is already failing.

HOW IT IS RECOGNISED, and why the recognition cannot misfire off Windows. The key is `OSError.winerror`,
which CPython sets only on Windows and which does not exist as an attribute anywhere else. Two values
are claimed:

  * 33, `ERROR_LOCK_VIOLATION` - another process holds a byte range. This is the observed one, and the
    quoted sentence above is its `strerror`.
  * 32, `ERROR_SHARING_VIOLATION` - another process has the file open in a mode that excludes this one.
    Same holder, same remedy, one door further out; a scanner that opens without `FILE_SHARE_READ`
    produces this where the sync client produces 33.

`errno` is deliberately NOT consulted. Windows reports both of these as `EACCES`, and so does an
ordinary POSIX permission denial - a chmod, a root-owned media directory, a read-only mount. Keying on
errno would print "a sync client is probably holding this file" at somebody whose real problem is a
missing `r` bit, which is worse than the raw error it replaced. On Linux this module therefore explains
nothing at all, by construction, and `tests/test_filelock.py` holds that.

WHAT LINUX CAN AND CANNOT PROVE, because this repository has no Windows runner and si#161 set the
precedent for that (a `cp1252` `TextIOWrapper` reproduced a Windows-only crash here). Two halves, and
only one of them is real:

  * REAL. A byte-range lock is an ordinary object on this box. A second PROCESS holding
    `fcntl.lockf(fd, LOCK_EX, 4096, 0)` makes a conflicting request from this one fail with a real
    `BlockingIOError`, errno 11 `EAGAIN`, measured. Two file descriptors inside ONE process do not
    conflict at all - POSIX record locks are owned by the process - which is a trap worth knowing
    before writing the test, not after.
  * CONSTRUCTED. That the conflicting operation is the READ, and that it arrives carrying `winerror`.
    Linux advisory locks do not stop `read()`: with the range locked by another process, the same bytes
    still come back. So the Windows outcome is injected - an `OSError` with `winerror` set - and what is
    under test is this module's classification of it, never the operating system's enforcement.

WHERE THE POSITION IS TAKEN, and why the two call sites do not spell it the same way. `explain` is the
one rule; how each caller shows it follows what that caller already promised.

  * `checksum.sha256_of` wraps its stat and its read in `explained` and raises `FileLockedError`. It
    documents that it raises whatever `stat` and `open` raise, so the type has to stay an `OSError` -
    narrowing a promise keeps it, replacing it does not, and a product catching `OSError` today keeps
    catching this.
  * `fetch.download` raises `DownloadError` and nothing else, on purpose and with a docstring arguing
    why. So it does not grow a second class to catch: it appends the sentence to the message it was
    going to raise anyway, behind the URL and the operating system's own wording, both of which are
    still worth reading on a transfer.

One rule, two spellings, and the difference is a caller's contract rather than a second opinion.

The third place si#193 names, si#155's `.simplon-toolchain` under a synchronised tree, is NOT touched
here. It is a different failure (a pip install into a held directory, not a read of a held file) on a
module another change owns this round, and taking a position on it from here would be guessing at both.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

#: The two Windows error numbers that mean "another process is holding this file", with the wording
#: each one gets. Numbers rather than names because that is what `OSError` carries, and a table rather
#: than an `in` test because the two are not the same story and a message that blurs them sends the
#: reader looking for the wrong thing.
HOLDS = {
    33: ("ERROR_LOCK_VIOLATION", "another process has locked a portion of it"),
    32: ("ERROR_SHARING_VIOLATION", "another process has it open and is not sharing it"),
}


class FileLockedError(OSError):
    """A file simplon had to read or write is held by another process, with the remedy in the message.

    An `OSError` on purpose, so that the two things already true of the paths that raise it stay true:
    `sha256_of` documents that it raises what `stat` and `open` raise, and `fetch.download` funnels
    `OSError` into `DownloadError`. Narrowing a type is a promise kept; replacing it is not.

    Constructed with the sentence as its ONLY argument, so `str(error)` is that sentence and nothing
    else. A two-argument `OSError` would prefix `[Errno 13]`, which is the number that made the original
    message useless. The raw failure stays reachable as `__cause__` either way.

    `errno`, `strerror` and `filename` ARE carried over, because a caller that inspects them on a caught
    `OSError` would otherwise find three `None`s where the failure used to have values - a silent
    narrowing, found in review. That is also the whole reason `__str__` below exists; see the measurement
    there.
    """

    def __str__(self) -> str:
        """The sentence, and only the sentence.

        `OSError.__str__` does not print its arguments: it REBUILDS its text out of `errno`, `strerror`
        and `filename` the moment those are set. Measured - setting them on an instance built from one
        argument turns `str()` from the explanation into
        `[Errno 13] Permission denied: 'C:/lib/win11.iso'`, which is exactly the message this class
        exists to replace. So the fields are kept for whoever reads them and the text is taken from the
        argument instead.
        """
        return str(self.args[0]) if self.args else super().__str__()


def explain(failure: BaseException, path: Path | str) -> str | None:
    """The sentence for `failure` when it is a file held by another process, else None.

    None is the answer for everything else, including a POSIX `EACCES`: see this module's head for why
    errno is not consulted. `path` is the file the CALLER was working on and is used only when the error
    does not name one itself.
    """
    code = getattr(failure, "winerror", None)
    if not isinstance(code, int) or code not in HOLDS:
        return None
    label, what = HOLDS[code]
    named = getattr(failure, "filename", None) or path
    return (
        f"{named} is held by another process: {what} (Windows error {code}, {label}). "
        f"A file synchronisation client or an on-access virus scanner is the usual holder, and on a "
        f"multi-gigabyte medium it can hold one for minutes rather than moments. Exclude the directory "
        f"from synchronisation and from on-access scanning, or run again once the holder has finished. "
        f"Simplon does not retry this: nobody has measured how long such a hold lasts, and a retry "
        f"schedule nobody derived would be a guess in a wait the caller cannot see (si#193)."
    )


@contextlib.contextmanager
def explained(path: Path | str) -> Iterator[None]:
    """Run the block, and re-raise a held-file `OSError` as `FileLockedError` with that sentence.

    Everything else passes through untouched, including every `OSError` this module declines to
    recognise - a missing file is still a missing file, and dressing one up as a lock would be the
    "cannot tell nothing-to-do from failed" defect wearing a helpful voice.
    """
    try:
        yield
    except OSError as failure:
        note = explain(failure, path)
        if note is None:
            raise
        held = FileLockedError(note)
        held.errno, held.strerror, held.filename = failure.errno, failure.strerror, failure.filename
        raise held from failure
