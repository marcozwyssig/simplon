"""A file held by another process, and the sentence the kernel answers with (si#193).

WHICH HALF IS REAL AND WHICH IS CONSTRUCTED, stated here rather than discovered per test, because this
repository has no Windows runner and si#161 is the precedent for building one condition instead of
acquiring the platform.

REAL, and measured on this box by `test_a_byte_range_lock_is_a_real_object_here`: a byte-range lock is
an ordinary thing on Linux. A second process holding `fcntl.lockf(fd, LOCK_EX, 4096, 0)` makes a
conflicting request from this one fail with `BlockingIOError`, errno 11 `EAGAIN`. The same test records
the two facts that decide the shape of every other test in this file - two descriptors inside ONE
process do NOT conflict, because POSIX record locks are owned by the process, and the locked bytes read
back fine anyway, because Linux advisory locks do not stop `read()`.

CONSTRUCTED, and it has to be: that the operation which fails is the READ, and that the failure carries
`winerror`. Linux cannot produce either. So every test of the classification injects an `OSError` with
`winerror` set, exactly the way si#161 injected a `cp1252` stream, and what is under test is simplon's
reading of that error - never the operating system's enforcement of a lock.

WHAT THAT DIVISION MEANS FOR THE VERDICT. These tests prove the kernel names the condition correctly
when it meets it. They do not prove Windows raises what `HOLDS` says it raises; that is read off the
Win32 error table and off the message `secure-windows-images` quotes verbatim in its troubleshooting
table, and it is a second source for a string rather than a measurement of this repository.
"""
import errno
import fcntl
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from simplon import checksum, filelock

#: An error that is NOT one of the two, to prove the recognition is a table lookup and not "any Windows
#: error while touching a file". 2 is `ERROR_FILE_NOT_FOUND`.
_NOT_A_HOLD = 2


def _windows_error(code: int, *, filename: str | None = None) -> OSError:
    """A Windows `OSError` as CPython would hand one over, built on Linux.

    `winerror` is set as an attribute because that is precisely what CPython does on Windows and what
    does not exist here. `errno` is `EACCES` for both holds, which is the whole reason this module keys
    on the other field: see `test_a_posix_permission_denied_is_not_dressed_up_as_a_lock`.
    """
    failure = OSError(errno.EACCES, "Permission denied")
    failure.winerror = code            # type: ignore[attr-defined]
    if filename is not None:
        failure.filename = filename
    return failure


# --- the real half ------------------------------------------------------------------------------------


def test_a_byte_range_lock_is_a_real_object_here(tmp_path):
    """THE MEASUREMENT this file's constructions are allowed to stand on, and the three facts it takes.

    A lock held by a second PROCESS really conflicts, and the conflict is a real `OSError` from a real
    kernel: `BlockingIOError`, errno 11 `EAGAIN`. Two descriptors in ONE process do not conflict at all,
    which is the trap - a same-process version of this test passes while locking nothing anybody could
    notice. And the locked bytes still read back, which is exactly why the rest of this file has to
    construct the Windows outcome instead of provoking it: Linux advisory locks bind lock takers, not
    readers.

    SEEN RED by taking the lock in this process before asking for it again: the request no longer fails,
    and the test takes thirty seconds rather than milliseconds. That second number is the reason the
    probe is `LOCK_NB` - a blocking `lockf` does not fail on a held range, it WAITS, so a version of this
    test without the flag would sit until the holder's sleep expired and then pass for the wrong reason.
    """
    # arrange
    media = tmp_path / "win11.iso"
    media.write_bytes(b"x" * 8192)
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import fcntl, sys, time
            handle = open({str(media)!r}, "r+b")
            fcntl.lockf(handle.fileno(), fcntl.LOCK_EX, 4096, 0)
            sys.stdout.write("held\\n")
            sys.stdout.flush()
            time.sleep(30)
        """)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held", "the second process never took the lock"

        # act / assert: another process's lock is met
        with open(media, "r+b") as ours, pytest.raises(OSError) as met:
            fcntl.lockf(ours.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 4096, 0)
        assert met.value.errno == errno.EAGAIN, f"expected EAGAIN, got {met.value!r}"

        # assert: and neither of the two things Windows would do
        with open(media, "rb") as ours:
            assert len(ours.read()) == 8192, "Linux stopped a read at an advisory lock"
        with open(media, "r+b") as one, open(media, "r+b") as two:
            fcntl.lockf(one.fileno(), fcntl.LOCK_EX, 4096, 4096)
            fcntl.lockf(two.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 4096, 4096)
    finally:
        holder.kill()
        holder.wait()


# --- the constructed half: what the kernel makes of a hold ----------------------------------------------


@pytest.mark.parametrize("code, label", sorted(filelock.HOLDS.items()))
def test_a_hold_becomes_a_sentence_naming_the_holder_class_and_the_remedy(code, label, tmp_path):
    """Both recognised codes, read off the table rather than typed twice, and the four things the
    sentence has to carry: the file, the holder class, what to change, and that no retry is coming."""
    # act
    note = filelock.explain(_windows_error(code), tmp_path / "win11.iso")

    # assert
    assert note is not None, f"Windows error {code} was not recognised as a hold"
    assert str(tmp_path / "win11.iso") in note
    assert label[0] in note and f"Windows error {code}" in note
    assert "synchronisation" in note and "virus scanner" in note
    assert "does not retry" in note, "the declined retry has to be where the reader meets the failure"


def test_the_sentence_names_the_file_the_error_named_rather_than_the_one_asked_about(tmp_path):
    """A download stages through a temporary and renames it, so the file the caller passed and the file
    the OS refused are not always the same one. The error's own `filename` wins when it has one."""
    # act
    note = filelock.explain(_windows_error(33, filename=r"C:\lib\win11.iso.part"),
                            tmp_path / "win11.iso")

    # assert
    assert note is not None and r"C:\lib\win11.iso.part" in note
    assert "win11.iso is held" not in note, "the caller's path was printed over the OS's own"


def test_a_posix_permission_denied_is_not_dressed_up_as_a_lock(tmp_path):
    """The reason the recognition keys on `winerror` and not on `errno`. Both Windows holds arrive as
    `EACCES`, and so does a chmod, a root-owned directory and a read-only mount. Explaining those as a
    sync client would send an operator hunting a process that is not there."""
    # act
    plain = filelock.explain(OSError(errno.EACCES, "Permission denied"), tmp_path / "f")

    # assert
    assert plain is None


def test_an_unrelated_windows_error_is_left_alone(tmp_path):
    """`winerror` present is not enough - the recognition is a table of two, not "a Windows error while
    touching a file"."""
    # act / assert
    assert filelock.explain(_windows_error(_NOT_A_HOLD), tmp_path / "f") is None


def test_nothing_at_all_is_explained_on_this_platform(tmp_path):
    """The claim the head makes about misfiring, held rather than asserted in prose: no error CPython
    raises on Linux carries `winerror`, so this module is inert here by construction.

    Driven on errors this box really produces rather than on one built by hand, and the choice of which
    ones is not free: the obvious candidate, a `chmod 000` read, does not fail at all when the suite runs
    as root, which is how this repository's own container runs it. What is left is every real `OSError`
    a file path can raise regardless of privilege.
    """
    # arrange
    directory = tmp_path / "media"
    directory.mkdir()
    plain = tmp_path / "win11.iso"
    plain.write_bytes(b"x")
    attempts = [lambda: (tmp_path / "not-here").open("rb"),      # ENOENT
                lambda: directory.open("rb"),                    # EISDIR
                lambda: (plain / "deeper").open("wb")]           # ENOTDIR

    for attempt in attempts:
        # act
        with pytest.raises(OSError) as raised:
            attempt()

        # assert
        assert not hasattr(raised.value, "winerror"), (
            f"{raised.value!r} carries winerror on Linux, which the recognition assumes cannot happen")
        assert filelock.explain(raised.value, tmp_path) is None


# --- the two call sites take the same position ----------------------------------------------------------


def test_sha256_of_names_the_hold_instead_of_reraising_the_bare_oserror(monkeypatch, tmp_path):
    """The read seam, with the Windows outcome injected at the one place a Windows kernel would put it.

    Driven with `cache=None`, which is the plain-hash path and the one every one-shot caller uses.
    """
    # arrange
    media = tmp_path / "win11.iso"
    media.write_bytes(b"x" * 16)

    def held(path):
        raise _windows_error(33, filename=str(path))

    monkeypatch.setattr(checksum, "_digest", held)

    # act
    with pytest.raises(filelock.FileLockedError) as raised:
        checksum.sha256_of(media)

    # assert
    assert "does not retry" in str(raised.value)
    assert str(raised.value).startswith(str(media)), (
        f"the message leads with something other than the file: {raised.value}")


def test_the_named_error_is_still_an_oserror_so_an_existing_except_still_catches_it(monkeypatch,
                                                                                   tmp_path):
    """The compatibility half of the type choice. `sha256_of` has always documented that it raises what
    `stat` and `open` raise; a product catching `OSError` today has to keep catching this."""
    # arrange
    media = tmp_path / "win11.iso"
    media.write_bytes(b"x" * 16)
    monkeypatch.setattr(checksum, "_digest",
                        lambda path: (_ for _ in ()).throw(_windows_error(32)))

    # act: through a bare `except OSError`, which is the line a product already has
    caught: OSError | None = None
    try:
        checksum.sha256_of(media)
    except OSError as failure:
        caught = failure
    assert caught is not None, "nothing was raised"

    # assert
    assert isinstance(caught, filelock.FileLockedError)
    assert isinstance(caught.__cause__, OSError), "the raw error was not kept as the cause"
    assert getattr(caught.__cause__, "winerror", None) == 32, (
        "the Windows error number is only reachable through the cause, and it was dropped")


def test_a_missing_file_is_still_a_missing_file(tmp_path):
    """The other direction of the same seam. The wrapper may only rename what it recognises - a
    `FileNotFoundError` turned into "a sync client is probably holding it" would be this repository's
    own defect class, wearing a helpful voice."""
    # act / assert
    with pytest.raises(FileNotFoundError):
        checksum.sha256_of(tmp_path / "not-here.iso")


def test_a_stat_that_meets_a_hold_is_named_too(monkeypatch, tmp_path):
    """`sha256_of` stats before it reads when a cache is in play, and a held file fails at whichever of
    the two touches it first. The wrap is around both, so the answer does not depend on which."""
    # arrange
    media = tmp_path / "win11.iso"
    media.write_bytes(b"x" * 16)
    real = Path.stat

    def held(self, **kwargs):
        if self == media:
            raise _windows_error(33, filename=str(self))
        return real(self, **kwargs)

    monkeypatch.setattr(Path, "stat", held)

    # act / assert
    with pytest.raises(filelock.FileLockedError):
        checksum.sha256_of(media, cache=tmp_path / "cache")
