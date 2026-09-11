"""The kernel's file checksum and the rule that decides when its sidecar may be believed (si#177).

WHY EVERY TEST HERE COUNTS THE READS. A cache test that only checks the returned digest passes whether
or not the cache works - the right answer comes back either way, once by memory and once by reading four
gigabytes - and this project has found that exact defect four times in the last release. So every test
below asserts how many times the file was actually opened, through `checksum._digest`, and a timing
comparison is used nowhere: a fast disk and a cache hit are indistinguishable on a clock.

THE ONE THAT MATTERS IS `test_a_rewrite_that_shares_one_whole_second_stamp_recomputes`. mtime and size
alone are fooled by two contents stamped with the same whole second, which is what a sync client,
`touch -d`, `unzip` and `tar` all produce, and si#86 and si#169 were both that class in one week. Delete
the `looked_at_ns` guard from `checksum._read` and that test returns the FIRST file's digest for the
second file's content - seen red, and recorded in the docstring there.

AND ONE OF THEM ONLY EXISTS BECAUSE 4 KB WAS NOT ENOUGH. Every test here hashes kilobytes, and the first
version of the module passed all of them while being wrong on a 2 GiB file: it stamped the sidecar AFTER
hashing, so a 0.68 s read carried the record past the one-second window that was supposed to distrust it.
`test_a_read_long_enough_to_leave_the_racy_second_still_distrusts_its_sidecar` is that finding, reproduced
through the `_now_ns` seam instead of through two real gigabytes.
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from simplon import bootstrap, checksum

#: Two payloads of the SAME length. Equal size is what makes the mtime rules load-bearing: a cheap size
#: check would otherwise catch every case below and nothing else would be under test.
A = b"a" * 4096
B = b"b" * 4096

DIGEST_A = hashlib.sha256(A).hexdigest()
DIGEST_B = hashlib.sha256(B).hexdigest()


@pytest.fixture
def reads(monkeypatch):
    """Every path `checksum._digest` was called on, in order - the only honest proof of a cache hit."""
    seen: list[Path] = []
    real = checksum._digest

    def counting(path: Path) -> str:
        seen.append(path)
        return real(path)

    monkeypatch.setattr(checksum, "_digest", counting)
    return seen


def _settled(path: Path, payload: bytes) -> Path:
    """Write `payload` and stamp the file far enough in the past that the racy-second guard is satisfied.

    Five seconds, so a sidecar written now is trusted on the next call. Without this every test that
    wants a HIT would have to sleep for a second, and a suite that sleeps is a suite nobody runs.
    """
    path.write_bytes(payload)
    stamp = time.time_ns() - 5 * checksum.RACY_WINDOW_NS
    os.utime(path, ns=(stamp, stamp))
    return path


def _sidecar_of(cache: Path) -> Path:
    found = sorted(cache.glob("*.json"))
    assert len(found) == 1, f"expected exactly one sidecar in {cache}, found {found}"
    return found[0]


# --- the hash itself ----------------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="coreutils sha256sum is not on PATH")
def test_the_digest_is_the_one_coreutils_computes(tmp_path):
    """A second source for the string, as CLAUDE.md asks: `hashlib` against itself would only prove that
    this module calls `hashlib`."""
    # arrange
    media = _settled(tmp_path / "media.iso", os.urandom(1 << 20))

    # act
    mine = checksum.sha256_of(media)
    theirs = subprocess.run(["sha256sum", str(media)], capture_output=True, text=True,
                            check=True).stdout.split()[0]

    # assert
    assert mine == theirs


def test_an_empty_file_has_the_empty_digest(tmp_path):
    """Zero bytes is a real answer, not an absence - the case a `if not size: return None` would break."""
    # arrange
    media = _settled(tmp_path / "empty.iso", b"")

    # act / assert
    assert checksum.sha256_of(media) == hashlib.sha256(b"").hexdigest()


def test_a_file_that_is_not_there_raises(tmp_path):
    """A checksum of a missing file has no answer; inventing one is the "cannot tell nothing-to-do from
    failed" defect this repository hunts."""
    with pytest.raises(FileNotFoundError):
        checksum.sha256_of(tmp_path / "gone.iso", cache=tmp_path / "cache")


def test_without_a_cache_every_call_hashes(tmp_path, reads):
    """`cache=None` is a plain hash: no sidecar read, no sidecar write, nothing left in the tree."""
    # arrange
    media = _settled(tmp_path / "media.iso", A)

    # act
    first, second = checksum.sha256_of(media), checksum.sha256_of(media)

    # assert
    assert (first, second) == (DIGEST_A, DIGEST_A)
    assert len(reads) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["media.iso"]


# --- the hit, and what it costs ------------------------------------------------------------------------


def test_the_second_call_does_not_open_the_file_again(tmp_path, reads):
    """THE POINT OF THE TICKET. `test iso` reports what is present and would read five gigabytes to do
    it; driven on a real 2 GiB image on this box, 0.674 s to hash and 0.075 ms to answer from the
    sidecar. The assertion here is the read COUNT rather than the time, because only the count can tell a
    hit from a fast disk - the timing belongs in the ticket, not in a gate that would go red on a busy
    machine."""
    # arrange
    media = _settled(tmp_path / "media.iso", A)
    cache = tmp_path / "cache"

    # act
    first = checksum.sha256_of(media, cache=cache)
    second = checksum.sha256_of(media, cache=cache)

    # assert
    assert (first, second) == (DIGEST_A, DIGEST_A)
    assert reads == [media], "the second call re-read the file, so the sidecar bought nothing"


def test_the_sidecar_records_the_stat_it_hashed(tmp_path):
    """What is in the file is the whole of what the rule can consult later, so it is asserted here rather
    than inferred from behaviour: a field that stopped being written would otherwise only show up as a
    cache that never hits."""
    # arrange
    media = _settled(tmp_path / "media.iso", A)
    cache = tmp_path / "cache"
    stat = media.stat()

    # act
    checksum.sha256_of(media, cache=cache)
    record = json.loads(_sidecar_of(cache).read_text(encoding="utf-8"))

    # assert
    assert record["format"] == checksum.FORMAT
    assert record["path"] == str(media)
    assert record["sha256"] == DIGEST_A
    assert record["size"] == stat.st_size
    assert record["mtime_ns"] == stat.st_mtime_ns
    assert record["looked_at_ns"] - stat.st_mtime_ns >= checksum.RACY_WINDOW_NS
    assert not list(cache.glob("*.tmp")), "a temporary sidecar survived the write"


def test_two_files_do_not_share_a_sidecar(tmp_path):
    """A flat cache directory keyed on the path: the keying is what stops one file's digest answering for
    another, and one sidecar for two files would be a wrong answer rather than a miss."""
    # arrange
    cache = tmp_path / "cache"
    one = _settled(tmp_path / "one.iso", A)
    two = _settled(tmp_path / "two.iso", B)

    # act
    digests = (checksum.sha256_of(one, cache=cache), checksum.sha256_of(two, cache=cache))

    # assert
    assert digests == (DIGEST_A, DIGEST_B)
    assert len(sorted(cache.glob("*.json"))) == 2


def test_the_same_file_named_two_ways_shares_one_sidecar(tmp_path, reads, monkeypatch):
    """A relative path and its absolute spelling are one file, so they are one cache entry - otherwise a
    command run from a different directory pays the read again for nothing."""
    # arrange
    cache = tmp_path / "cache"
    media = _settled(tmp_path / "media.iso", A)
    checksum.sha256_of(media, cache=cache)

    # act
    monkeypatch.chdir(tmp_path)
    again = checksum.sha256_of(Path("media.iso"), cache=cache)

    # assert
    assert again == DIGEST_A
    assert reads == [media], "the relative spelling was hashed a second time"


# --- every way the rule invalidates ---------------------------------------------------------------------


def test_a_file_of_a_different_size_recomputes(tmp_path, reads):
    """Rule 1. The ordinary edit, and the cheapest of the three to check."""
    # arrange
    cache = tmp_path / "cache"
    media = _settled(tmp_path / "media.iso", A)
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A

    # act
    longer = B + b"!"
    _settled(media, longer)
    again = checksum.sha256_of(media, cache=cache)

    # assert
    assert again == hashlib.sha256(longer).hexdigest()
    assert len(reads) == 2


def test_a_rewrite_of_a_different_size_is_seen_even_with_the_mtime_restored(tmp_path, reads):
    """Rule 1 ON ITS OWN. The test above changes the size AND the mtime, so it passes with the size check
    deleted - which would make that check decoration. This is the case only the size can answer: an
    append followed by `touch -r`, the exact shape of the blind spot at the bottom of this file, one byte
    away from being invisible. Seen red by deleting `record.get("size") != stat.st_size`.
    """
    # arrange
    cache = tmp_path / "cache"
    media = _settled(tmp_path / "media.iso", A)
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A
    stat = media.stat()

    # act: longer, and stamped back to the mtime the sidecar recorded
    longer = A + b"!"
    media.write_bytes(longer)
    os.utime(media, ns=(stat.st_mtime_ns, stat.st_mtime_ns))
    again = checksum.sha256_of(media, cache=cache)

    # assert
    assert again == hashlib.sha256(longer).hexdigest()
    assert len(reads) == 2


def test_an_edit_that_keeps_the_size_recomputes(tmp_path, reads):
    """Rule 2. Same length, different content - what a size-only cache would serve stale forever."""
    # arrange
    cache = tmp_path / "cache"
    media = _settled(tmp_path / "media.iso", A)
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A

    # act
    _settled(media, B)
    again = checksum.sha256_of(media, cache=cache)

    # assert
    assert again == DIGEST_B
    assert len(reads) == 2


def test_a_rewrite_that_shares_one_whole_second_stamp_recomputes(tmp_path, reads):
    """RULE 3, AND THE CASE THIS REPOSITORY KEEPS MEETING. Two contents of equal length carrying one
    whole-second mtime: a sync client stamping whole seconds, `touch -d`, `unzip`, `tar`. Rules 1 and 2
    cannot tell them apart, and si#86 and si#169 were both that class in one week.

    What saves it is that the sidecar was WRITTEN inside the second it records, so it cannot prove it
    hashed that second's final content and is not believed.

    SEEN RED: with the `looked_at_ns` comparison deleted from `checksum._read`, this returns DIGEST_A for
    a file holding B, and it is the only test in the file that goes red - which is what makes it the
    assertion and not the decoration.
    """
    # arrange: both writes stamped with the same whole second, and the first hash taken inside it
    cache = tmp_path / "cache"
    media = tmp_path / "media.iso"
    for attempt in range(4):
        shutil.rmtree(cache, ignore_errors=True)
        reads.clear()
        second = time.time_ns() // checksum.RACY_WINDOW_NS * checksum.RACY_WINDOW_NS
        media.write_bytes(A)
        os.utime(media, ns=(second, second))
        assert checksum.sha256_of(media, cache=cache) == DIGEST_A
        record = json.loads(_sidecar_of(cache).read_text(encoding="utf-8"))
        # The precondition of the act, not a property under test: the clock may have crossed into the
        # next second between the stamp and the hash, which is a different arrangement than the one this
        # test is about. Retry rather than assert, because the crossing is real and rare.
        if record["looked_at_ns"] - second < checksum.RACY_WINDOW_NS:
            break
    else:
        pytest.fail("could not take four hashes inside the second they were stamped with")

    # act: the same second, the same length, different bytes
    media.write_bytes(B)
    os.utime(media, ns=(second, second))
    again = checksum.sha256_of(media, cache=cache)

    # assert
    assert again == DIGEST_B, "the cache served a digest of what the file used to hold"
    assert len(reads) == 2


def test_a_sidecar_written_inside_the_racy_second_is_not_used_and_then_is(tmp_path, reads):
    """The guard from the other side: the cost is exactly ONE extra hash, and it heals itself. A file
    hashed the moment it was written is hashed once more; once its mtime is a second in the past, the
    sidecar sticks. A guard that never stopped costing would be a cache that never hits."""
    # arrange: mtime is now, so the first sidecar records a gap below the window
    cache = tmp_path / "cache"
    media = tmp_path / "media.iso"
    media.write_bytes(A)
    now = time.time_ns()
    os.utime(media, ns=(now, now))

    # act
    checksum.sha256_of(media, cache=cache)
    distrusted = checksum.sha256_of(media, cache=cache)
    os.utime(media, ns=(now - 5 * checksum.RACY_WINDOW_NS,) * 2)
    trusted = checksum.sha256_of(media, cache=cache)
    reused = checksum.sha256_of(media, cache=cache)

    # assert
    assert (distrusted, trusted, reused) == (DIGEST_A, DIGEST_A, DIGEST_A)
    assert len(reads) == 3, "either the racy sidecar was trusted, or the settled one was not"


def test_a_read_long_enough_to_leave_the_racy_second_still_distrusts_its_sidecar(tmp_path, monkeypatch):
    """THE 2 GiB FINDING, in microseconds. Rule 3 asks whether the file was modified within a second of
    the moment we LOOKED - not of the moment we finished reading, which on a large file is a different
    second entirely. Driven on a real 2 GiB image, the hash takes 0.68 s: a sidecar begun 0.4 s into the
    racy second was stamped 1.08 s after the mtime, sailed past the window on the next call, and served
    the previous content's digest for a file rewritten under the same stamp.

    The read is what moves the clock here, because that is what a slow read really does: `_digest` costs
    two seconds of simulated time. Stamp the sidecar AFTER the read - which is where this module had it -
    and the record lands 2 s past an mtime it was looking at 0 s after, the guard never fires, and the
    assertion below fails with A where B was written. Seen red exactly that way.
    """
    # arrange: mtime is now, so an honest reading of the clock is inside the racy second
    cache = tmp_path / "cache"
    media = tmp_path / "media.iso"
    media.write_bytes(A)
    now = time.time_ns()
    os.utime(media, ns=(now, now))

    clock = [now]
    hashed: list[Path] = []
    real = checksum._digest

    def slow(path: Path) -> str:
        hashed.append(path)
        digest = real(path)
        clock[0] += 2 * checksum.RACY_WINDOW_NS   # a 2 GiB read, without the 2 GiB
        return digest

    monkeypatch.setattr(checksum, "_now_ns", lambda: clock[0])
    monkeypatch.setattr(checksum, "_digest", slow)

    # act
    checksum.sha256_of(media, cache=cache)
    media.write_bytes(B)
    os.utime(media, ns=(now, now))
    again = checksum.sha256_of(media, cache=cache)

    # assert
    assert again == DIGEST_B, "a long read moved the sidecar out of the window that had to distrust it"
    assert len(hashed) == 2


def test_an_mtime_in_the_future_is_never_trusted(tmp_path, reads):
    """The same guard covering a clock that disagrees - media on a remote filesystem whose server runs
    ahead. The cache then never hits: slow, and never wrong."""
    # arrange
    cache = tmp_path / "cache"
    media = tmp_path / "media.iso"
    media.write_bytes(A)
    ahead = time.time_ns() + 3600 * checksum.RACY_WINDOW_NS
    os.utime(media, ns=(ahead, ahead))

    # act
    checksum.sha256_of(media, cache=cache)
    again = checksum.sha256_of(media, cache=cache)

    # assert
    assert again == DIGEST_A
    assert len(reads) == 2


# --- a sidecar that cannot be believed --------------------------------------------------------------


def _tamper(cache: Path, **fields: object) -> None:
    record = json.loads(_sidecar_of(cache).read_text(encoding="utf-8"))
    record.update(fields)
    _sidecar_of(cache).write_text(json.dumps(record), encoding="utf-8")


@pytest.mark.parametrize("why, fields", [
    ("an unknown format", {"format": checksum.FORMAT + 1}),
    ("no format at all, as an older writer left it", {"format": None}),
    ("a path naming another file", {"path": "/elsewhere/media.iso"}),
    ("a digest that is not a digest", {"sha256": "not-a-digest"}),
    ("a digest of the wrong length", {"sha256": "ab" * 16}),
    ("a digest in upper case, which this module never writes", {"sha256": DIGEST_A.upper()}),
    ("no looked_at_ns, as an older writer left it", {"looked_at_ns": None}),
    ("a looked_at_ns that is not a number", {"looked_at_ns": "yesterday"}),
])
def test_a_sidecar_this_version_cannot_fully_check_recomputes(tmp_path, reads, why, fields):
    """"Written by an older version", "edited by somebody", "truncated": one instruction covers all of
    them, and it is recompute. The alternative - trusting a record whose meaning this version does not
    know - is the only way a checksum comes back confidently wrong."""
    # arrange
    cache = tmp_path / "cache"
    media = _settled(tmp_path / "media.iso", A)
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A
    _tamper(cache, **fields)

    # act
    again = checksum.sha256_of(media, cache=cache)

    # assert
    assert again == DIGEST_A, why
    assert len(reads) == 2, why


@pytest.mark.parametrize("why, content", [
    ("not JSON at all", "}{ truncated"),
    ("JSON, but not an object", "[1, 2, 3]"),
    ("an empty file, as an interrupted write would leave it", ""),
])
def test_a_malformed_sidecar_recomputes(tmp_path, reads, why, content):
    # arrange
    cache = tmp_path / "cache"
    media = _settled(tmp_path / "media.iso", A)
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A
    _sidecar_of(cache).write_text(content, encoding="utf-8")

    # act / assert
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A, why
    assert len(reads) == 2, why


def test_a_sidecar_that_cannot_be_read_recomputes(tmp_path, reads):
    """Unreadable rather than malformed, and driven as a DIRECTORY standing where the file belongs
    because this suite runs as root on this box and a mode of 000 would not stop it."""
    # arrange
    cache = tmp_path / "cache"
    media = _settled(tmp_path / "media.iso", A)
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A
    sidecar = _sidecar_of(cache)
    sidecar.unlink()
    sidecar.mkdir()

    # act / assert
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A
    assert len(reads) == 2


def test_a_cache_that_cannot_be_written_still_answers(tmp_path, reads):
    """Read-only media directory, full disk: the caller asked for a digest and gets one. A cache is an
    optimisation, and an optimisation that can fail a command is a liability."""
    # arrange: a FILE where the cache directory would go, so the mkdir cannot succeed
    blocked = tmp_path / "cache"
    blocked.write_text("not a directory", encoding="utf-8")
    media = _settled(tmp_path / "media.iso", A)

    # act
    first = checksum.sha256_of(media, cache=blocked)
    second = checksum.sha256_of(media, cache=blocked)

    # assert
    assert (first, second) == (DIGEST_A, DIGEST_A)
    assert len(reads) == 2
    assert blocked.read_text(encoding="utf-8") == "not a directory"


# --- the blind spot, recorded rather than discovered -------------------------------------------------


def test_a_rewrite_that_restores_both_size_and_mtime_is_not_seen(tmp_path, reads):
    """THE DOCUMENTED HOLE, asserted so it stays documented. An in-place patch followed by `touch -r`, or
    an `rsync --times` carrying an older stamp onto new content of the same length, leaves nothing for a
    metadata rule to notice - and reading the file to find out is the work the cache exists to avoid.

    This is also the cleanest possible proof that a hit really does not read: the answer is the OLD
    content's digest, which nothing that opened the file could have produced.
    """
    # arrange
    cache = tmp_path / "cache"
    media = _settled(tmp_path / "media.iso", A)
    assert checksum.sha256_of(media, cache=cache) == DIGEST_A
    stat = media.stat()

    # act: same length, same mtime, different bytes
    media.write_bytes(B)
    os.utime(media, ns=(stat.st_mtime_ns, stat.st_mtime_ns))
    again = checksum.sha256_of(media, cache=cache)

    # assert
    assert again == DIGEST_A, "the rule grew an ability it is documented not to have"
    assert reads == [media]


# --- where the sidecars live, held to git's own verdict (si#155) -------------------------------------


pytestmark_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _ignored(repo: Path, relative: str) -> bool:
    done = _git("check-ignore", "-q", "--", relative, cwd=repo)
    assert done.returncode in (0, 1), f"{relative}: rc {done.returncode} {done.stderr}"
    return done.returncode == 0


def test_the_cache_directory_is_a_product_root_plus_build_checksums(tmp_path):
    """Stated once, in code, so a product does not invent a path per product for a directory the KERNEL
    chose - which is the mistake si#155 was written about."""
    assert checksum.cache_dir(tmp_path) == tmp_path / "build" / "checksums"


@pytestmark_git
def test_the_scaffolded_gitignore_already_hides_the_cache(tmp_path):
    """ACCEPTANCE FOR THE PLACEMENT. si#155 measured what the kernel writes into a product tree and gave
    it a block; this module had to fit that list rather than extend it. Asserted through `git
    check-ignore`, because an ignore rule is a verdict over a path and not a line in a file - the same
    standard si#155 set for itself."""
    # arrange: a scaffolded product, exactly as `simplon init` leaves it
    repo = tmp_path / "fooctl"
    repo.mkdir()
    assert _git("init", "-q", ".", cwd=repo).returncode == 0
    bootstrap.write("fooctl", repo)
    sidecar = checksum._sidecar(checksum.cache_dir(repo), repo / "media.iso")

    # act
    relative = sidecar.relative_to(repo).as_posix()

    # assert
    assert _ignored(repo, relative), (
        f"{relative} is not ignored by the block si#155 scaffolds, so this module adds a line to a "
        f"list that was measured without it")


@pytestmark_git
def test_without_that_block_git_would_see_every_sidecar(tmp_path):
    """The half that makes the test above an assertion rather than a coincidence: in a repository with no
    `.gitignore`, the same path is visible."""
    # arrange
    repo = tmp_path / "bare"
    repo.mkdir()
    assert _git("init", "-q", ".", cwd=repo).returncode == 0
    sidecar = checksum._sidecar(checksum.cache_dir(repo), repo / "media.iso")

    # act / assert
    assert not _ignored(repo, sidecar.relative_to(repo).as_posix())
