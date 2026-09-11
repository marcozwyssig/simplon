"""The kernel's one file checksum, with a sidecar so a command that only REPORTS does not re-read
gigabytes to do it (si#177).

WHY THIS IS HERE AT ALL. Every `sha256` in this package before today was an image digest - `docker.py`,
`labhost.py`, `clabrender.py`, `tasks/allure.py`, `tasks/site.py` all pin or compare a registry
reference. None of them hashes a file. A product that pins MEDIA by hash (the Windows/Packer product
si#177 came from ships ISOs) therefore had to write its own, and the version it wrote is the one being
lifted here, invalidation rule and all - which is the part worth arguing about, because
`test iso`, a command whose whole job is to say what is present, would otherwise read five gigabytes to
answer.

WHY A CACHE NEEDS A BETTER RULE THAN "MTIME AND SIZE". A cache that can be wrong is worse than no cache,
and a checksum is the one place where being wrong is silent: the caller gets a hex string either way, and
nothing downstream can tell a current digest from a digest of what the file used to hold. So the
invalidation rule IS the design, and it is three conditions, not two:

  1. `st_size` is unchanged. Cheap, and it catches the ordinary edit.
  2. `st_mtime_ns` is unchanged. Catches every edit a size check does not.
  3. The sidecar was written at least one second AFTER the mtime it records.

THE THIRD ONE IS THE ONE THE PORTED CODE DID NOT HAVE, and it is what makes the rule survive a
same-second write. Measured on this repository's own box (tmpfs, ext4-class nanosecond timestamps): two
`write_bytes` calls back to back land in the same WALL-CLOCK SECOND and still differ in `st_mtime_ns`, by
24 microseconds - so on a filesystem with nanosecond stamps, rule 2 alone already sees them. The hazard
is not the filesystem, it is every tool that STAMPS a whole second: `os.utime(path, (1789162057, ...))`,
`touch -d`, `unzip`, `tar`, and the sync client si#177 names, which rewrites mtimes to whole seconds. Two
different contents of the same length, both stamped `...057.000000000`, are indistinguishable under rules
1 and 2 - and si#86 and si#169 were both that class of defect in this repository, in one week.

Rule 3 closes it without needing to know the filesystem's granularity, and it is git's answer to its own
"racily clean" index entries rather than an invention here: a sidecar whose stat was taken less than a
second after the mtime it records CANNOT prove it hashed the final content of that timestamp tick, so it
is not trusted - whatever the tick's width. The cost is bounded and self-healing: a file hashed
immediately after it was written is hashed once more on the next call, and from then on the sidecar
sticks, because by then the recorded mtime is comfortably in the past.

AND THE TIMESTAMP IS TAKEN BEFORE THE READ, WHICH IS NOT WHERE IT STARTED. The first version stamped the
sidecar after hashing, and a 4 KB unit test cannot tell the difference. Driven on a real 2 GiB image it
was wrong: the hash takes 0.68 s, so a file stamped `...057.000000000` and hashed at `...057.4` recorded
`...058.08` - 1.08 s after its own mtime, comfortably past the window - and the next call trusted a
sidecar that had begun reading INSIDE the racy second. It then served the previous content's digest for a
file that had been rewritten under the same stamp: the exact defect rule 3 exists for, reintroduced by
where the clock was read. `looked_at_ns` is therefore taken before the stat, so it can only ever be
earlier than the moment the content was read, and the guard is conservative in the direction that
recomputes.

WHAT THE RULE STILL MISSES, stated rather than discovered later:

  * A write that restores BOTH size and mtime - an in-place patch followed by `touch -r`, or an
    `rsync --times` that carries an older source stamp onto new content of the same length. Nothing
    short of reading the file can see that, which is the thing the cache exists not to do.
    `test_checksum.py` drives exactly this case and asserts the stale answer, so the blind spot is a
    recorded measurement and not a surprise. A concurrent writer racing the read reaches the same
    precondition by a different door and with a worse payload: the stat is taken once, the read happens
    after it, and a rewrite that lands mid-read and then restores the stat leaves a digest of NEITHER
    version cached. Same rule, same answer - out of reach of anything that does not read the file.
  * A clock that runs backwards, or media on a remote filesystem whose server clock is AHEAD of this
    one. Rule 3 is then never satisfied and the cache simply never hits: slow, never wrong. A server
    clock more than a second BEHIND weakens rule 3 by that much.
  * The stat is taken BEFORE the read, on purpose. A file rewritten WHILE it is being hashed yields a
    digest of neither version, and recording the pre-read stat is what makes the next call see a
    different mtime and recompute. Recording the post-read stat would have stored the new file's stat
    beside the mixed digest and cached it forever.

WHAT MAKES A SIDECAR UNUSABLE. Unreadable, not JSON, not an object, a `format` this version does not
know, a digest that is not 64 hex characters, or a `path` naming a different file: every one of them
means recompute, and none of them raises. There is no path through this module that trusts a sidecar it
could not fully check, because the only thing a wrong trust produces is a confident wrong answer. A
sidecar that cannot be WRITTEN (read-only media directory, full disk) is not an error either - the caller
asked for a digest, and it gets one.

WHAT IS DELIBERATELY NOT HERE. No algorithm choice - one function, sha256, because a second algorithm has
no caller and `hashlib` is one line away for anybody who needs one. No retry around the read: the ported
version had one because a Windows sync client can hold a file open, and that is a measurement from
another operating system that this repository has not taken. And no dependency; si#142 records why the
kernel adds none.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from pathlib import Path

#: How far the sidecar's `looked_at_ns` has to sit AFTER the mtime it records before the pair is
#: trusted (rule 3 in the head). One second, because that is the coarsest timestamp granularity a tool
#: in this path realistically stamps - whole seconds - and the guard has to be at least as wide as the
#: tick it cannot see inside of. Narrower and a `touch -d`-stamped rewrite slips through; wider and a
#: file written once a minute never caches at all.
RACY_WINDOW_NS = 1_000_000_000

#: The sidecar layout this version writes and is willing to read. Bumped when a FIELD changes meaning;
#: an unknown value recomputes rather than guessing, which is the whole reason the field exists.
FORMAT = 1

#: A sha256 as it is written down. Checked on the way OUT of a sidecar, not only on the way in: the file
#: is editable by anyone who can reach the cache directory, and a caller that pins media by hash must
#: not be handed something that is not a digest at all.
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _now_ns() -> int:
    """The clock rule 3 is measured on, read BEFORE the stat and factored out so a test can make a read
    appear to take two seconds without taking two seconds.

    A seam for one test would normally be over-engineering. This one is here because the defect it holds
    was invisible to every 4 KB test in the suite and took a 2 GiB file to find: stamp the sidecar after
    the read instead of before, and a hash long enough to cross the second boundary turns rule 3 off for
    exactly the file it matters on. The suite now fails that in microseconds.
    """
    return time.time_ns()


def cache_dir(root: Path) -> Path:
    """Where sidecars go for a product rooted at `root`: `build/checksums/`.

    UNDER `build/`, and that is the whole decision. The obvious placement - a `<name>.sha256` beside the
    media - puts kernel state in a directory the product owns, next to files it may be serving or
    syncing, and si#155 had just finished measuring what the kernel writes into a product tree and giving
    it a scaffolded `.gitignore` block. `/build/` is the first anchored line in that block. Choosing it
    means this module adds NO line to the list si#155 published and no surprise to a product that already
    ignores what the kernel writes; `test_checksum.py` proves that against `git check-ignore` on a real
    scaffold rather than against the text of the block.

    Nothing in this module calls it. It is the kernel saying where the answer belongs for a caller that
    has a product root and no opinion - passing a different directory stays legal, because a caller
    hashing media outside any checkout has no root to be relative to.
    """
    return root / "build" / "checksums"


def sha256_of(path: Path, *, cache: Path | None = None) -> str:
    """The sha256 of `path`, as 64 lowercase hex characters, read from a sidecar in `cache` when that
    sidecar is still valid and recomputed (and rewritten) when it is not.

    `cache=None` is a plain hash with no sidecar read and no sidecar write, which is what a one-shot
    caller wants and what every test of the hashing itself uses.

    THE NUMBER THE CACHE IS FOR, driven on a real 2 GiB image on this box: 0.674 s to hash it, 0.075 ms
    to answer from the sidecar - a factor of about 9000, and the sidecar is 223 bytes. That is 2.9 GB/s
    over page cache on tmpfs, so a cold read off real media is slower and the factor larger, never
    smaller. The five-gigabyte inventory si#177 describes is the same ratio at two and a half times the
    size.

    Raises whatever `stat`/`open` raise for a path that is missing or unreadable: a checksum of a file
    that is not there has no answer, and returning one would be the "cannot tell nothing-to-do from
    failed" defect this repository hunts.
    """
    if cache is None:
        return _digest(path)

    sidecar = _sidecar(cache, path)
    looked_at = _now_ns()
    stat = path.stat()

    cached = _read(sidecar, path, stat)
    if cached is not None:
        return cached

    digest = _digest(path)
    _write(sidecar, path, stat, digest, looked_at)
    return digest


def _digest(path: Path) -> str:
    """The read, factored out so a test can COUNT it: proving a cache hit means proving the file was not
    opened, and a timing comparison alone cannot tell a hit from a fast disk."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _sidecar(cache: Path, path: Path) -> Path:
    """The sidecar file for `path` inside `cache`, named by the hash of the path rather than by the path.

    A flat directory needs a key that is a legal filename on every platform, and an absolute POSIX path
    is not one. The absolute path is stored INSIDE the file as well and compared on read, so the naming
    scheme cannot be the thing that makes a wrong digest trusted.
    """
    key = hashlib.sha256(str(_absolute(path)).encode("utf-8")).hexdigest()
    return cache / f"{key}.json"


def _absolute(path: Path) -> Path:
    """The identity a sidecar is keyed and checked on. `absolute()` rather than `resolve()`: two paths
    reaching one file through different symlinks then keep separate entries, which costs a second hash
    and avoids having to decide what a link retargeted between calls means."""
    return path if path.is_absolute() else Path(os.getcwd()) / path


def _exact_int(value: object) -> int | None:
    """`value` when it is really an integer, else None - and `True` is NOT one.

    JSON's `true` decodes to a Python bool, `bool` is a subclass of `int`, and `True == 1`. So a record
    carrying `"format": true` compares equal to `FORMAT` under a plain `==` and a sidecar this version
    cannot read is read anyway. Every numeric field goes through here for that reason, rather than the
    one field somebody thought of. Found in review.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read(sidecar: Path, path: Path, stat: os.stat_result) -> str | None:
    """The digest in `sidecar` when every condition in this module's head holds, else None.

    One return path for all of them, because "the sidecar is unusable" and "the sidecar is stale" are the
    same instruction to the caller - recompute - and splitting them would invite a branch that recomputes
    for one and trusts for the other.
    """
    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or _exact_int(record.get("format")) != FORMAT:
        return None
    if record.get("path") != str(_absolute(path)):
        return None
    if _exact_int(record.get("size")) != stat.st_size:
        return None
    if _exact_int(record.get("mtime_ns")) != stat.st_mtime_ns:
        return None
    looked_at = _exact_int(record.get("looked_at_ns"))
    if looked_at is None or looked_at - stat.st_mtime_ns < RACY_WINDOW_NS:
        return None
    digest = record.get("sha256")
    return digest if isinstance(digest, str) and _HEX.match(digest) else None


def _write(sidecar: Path, path: Path, stat: os.stat_result, digest: str, looked_at: int) -> bool:
    """Record the digest with the stat it belongs to; return whether it was written.

    Through a temporary name in the same directory and a rename, which is the same discipline
    `simplon.fetch` applies to a download and for the same reason: a half-written sidecar that a later
    run reads as valid is the one failure mode a cache may not have. The temporary carries the pid, so
    two processes hashing the same file do not rename each other's half.

    An OSError is swallowed and reported as False - a read-only media directory or a full disk means no
    caching, not a failed checksum.
    """
    record = {
        "format": FORMAT,
        "path": str(_absolute(path)),
        "sha256": digest,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "looked_at_ns": looked_at,
    }
    temporary = sidecar.with_name(f"{sidecar.name}.{os.getpid()}.tmp")
    try:
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(record), encoding="utf-8")
        temporary.replace(sidecar)
    except OSError:
        # The write can succeed and the rename still fail - something that is not a file standing where
        # the sidecar goes, a directory that stopped being writable between the two. Swallowing that
        # without removing the temporary would leak one file per call for as long as the condition
        # lasts, which is a cache directory that grows without ever answering anything. Found in review.
        #
        # The cleanup is suppressed in turn, because the thing that broke the write can equally break the
        # removal: with a FILE standing where the cache directory goes, `unlink` raises NotADirectoryError
        # on a path whose parent is not a directory. A cache tidying itself up may not be the reason a
        # command fails - the suite caught that one line after it was written.
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        return False
    return True
