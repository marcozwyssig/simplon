"""Every file this kernel pulls over HTTP, with the transfer saying that it is alive (si#142).

WHY ONE FUNCTION. Three places downloaded a file and all three were a bare `urllib.request.urlretrieve`
- the static docker CLI bundle, the oras release archive, `get-pip.py`. A user waiting on the first of
those saw nothing at all: no bytes, no total, no indication the process was running rather than hung.
Three call sites is also three places where the same four questions were answered differently or not at
all, and the fourth answer was going to be written by a consuming product. So the function is PUBLIC:
`simplon.fetch.download` is what a product reaches for instead of writing a fourth silent one.

WHAT IT REFUSES, AND WHY THAT IS THE INTERESTING PART. `urlretrieve` opens `file://` and `ftp://`
without comment. Two of the three call sites carried a `# noqa: S310` with a comment arguing that their
URL was a pinned https asset, which was true of those three URLs and is a property of the CALL SITE
rather than of the code - it says nothing at all about the next caller. Here the argument is made once,
in code, for everybody: anything but https is refused, before a socket is opened, and on EVERY HOP of a
redirect chain. The last part is a review correction. The first draft checked the URL asked for and the
URL that answered, which leaves the middle of a chain to urllib's rule rather than to this one - and
urllib's admits `http`, `ftp` and an empty scheme, so `https -> http -> https` passed both checks with
one hop travelling in the clear.

THE THREE OTHER THINGS `urlretrieve` DOES NOT DO.

  - It has NO timeout. A server that accepts the connection and never answers hangs the command
    forever, with no output - which is the same complaint as the silence, arriving from the other side.
  - It writes straight to the destination, so an interrupted download leaves a file under the final
    name. A half-written `docker.tgz` that the next run reads as cached is a defect that hides for
    weeks. Here the bytes land on a temporary name in the same directory and are `os.replace`d into
    place only once the whole body has arrived.
  - It cannot tell a complete body from a truncated one, and neither can the layer under it. Measured:
    `http.client.HTTPResponse.read(amt)` on a connection that closed halfway returns `b""` and raises
    NOTHING. A loop that trusts EOF therefore renames a half file onto the final name - the very defect
    the temporary name exists to prevent, walking in through a door the temporary name was not
    watching. That is why what arrived is compared with what was announced.

NO NEW DEPENDENCY, AND `rich` IN PARTICULAR. `pyproject.toml` records the decision: this kernel imports
nothing from rich, and a floor of its own could only be tighter than typer's for no gain. A bar is about
thirty lines of standard library, and acquiring a dependency in a package every product installs in
order to draw one is the wrong trade. Importing an undeclared one would be worse, not better: a
dependency we do not import is a claim we cannot keep, and an import we do not declare is a claim we
cannot make.

WHAT si#176 ADDED, AND WHERE THE ARGUMENT FOR IT IS. `download(..., resume=True)` keeps what arrived
when a transfer dies mid-body and continues from there on the next call. It is opt-in: the three
artefacts this kernel fetches are small, and for them a clean retry beats the machinery. It exists
because the moment a product fetches something large - a five-gigabyte medium over a link that is
sometimes a VPN - discarding four and a half gigabytes stops being a retry policy and becomes a reason
to write a fourth downloader, which is the thing this module was made to prevent. A resume is also the
one change that can reopen the truncation hole above, so the rules it has to satisfy, and the case that
corrupts a file while looking like it worked, are written out above `_validator` rather than here.
"""
from __future__ import annotations

import http.client
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from simplon import log

#: How long a single socket operation may take. It bounds the connect AND every individual read, which
#: is the shape this needs: a slow 60 MB download is fine and a stall of half a minute is not.
DEFAULT_TIMEOUT_S = 30.0

#: THE ONE PLACE A SCHEME IS REFUSED, for every caller in this kernel and in every product that imports
#: this module. A frozenset rather than a literal because the refusal message reads it, so the rule and
#: what the rule says it is cannot disagree.
ALLOWED_SCHEMES = frozenset({"https"})

#: Read size. Large enough that the loop is not the bottleneck, small enough that a bar moves.
_CHUNK = 64 * 1024

#: How often the two output modes are allowed to say something. A terminal repaints ten times a second
#: because that is what looks alive; a log gets a line every ten seconds, so a download that finishes
#: inside that budget puts TWO lines in a CI log - the opening one, which carries the size, and the
#: closing one - and a long one adds a heartbeat per interval between them.
_TTY_REPAINT_S = 0.1
_LOG_INTERVAL_S = 10.0

_BAR_CELLS = 20
_SPINNER = "-\\|/"

#: The narrowest line worth drawing. `shutil.get_terminal_size` reports a zero for a terminal that has
#: never been sized (a fresh pty, some CI shells) and passes it straight through, so without a floor a
#: perfectly ordinary situation truncates every line to nothing.
_MIN_WIDTH = 20

#: What a line may occupy when nothing is watching it. A log file has no width, and truncating there
#: would cut off the rate for no reader's benefit.
_UNBOUNDED = 10_000

#: Where a RESUMABLE transfer parks its bytes, and the sidecar saying what those bytes are (si#176).
#: Derived from the destination rather than random, because a name the next run cannot predict is a name
#: the next run cannot resume - which is the whole difference between this and the temporary file below.
_PART_SUFFIX = ".part"
_SOURCE_SUFFIX = ".part.source"

#: `bytes 4096-8191/8192`, the only header that says which part of the object a `206` is actually
#: carrying. Parsed rather than trusted: a status line says "partial" and says nothing about WHICH part.
_CONTENT_RANGE = re.compile(r"^\s*bytes\s+(\d+)-(\d+)/(\d+|\*)\s*$")

#: The status a server sends when the range asked for starts past the end of the object. It is the
#: answer to a stale partial file that claims more bytes than the thing it claims to be, and without a
#: reply to it that file wedges the download for good: every run asks the same impossible question.
_RANGE_NOT_SATISFIABLE = 416


class DownloadError(RuntimeError):
    """Anything that stopped a download from finishing, with the original cause attached.

    ONE type on purpose. Underneath are `urllib.error.HTTPError`, `URLError`, `TimeoutError`,
    `ssl.SSLError` and `http.client.HTTPException`, which share no base a caller can name in one
    `except` (three of them are `OSError`s, one is not, and catching `OSError` would also swallow the
    caller's own file handling). A consuming product should not have to know that list to write a
    sensible message, so it is collapsed here and the cause is kept with `raise ... from`.
    """


# --- what the numbers look like -------------------------------------------------------------------


def human_bytes(count: float) -> str:
    """`947 B`, `2.4 MB`, `1.1 GB`, `5,000.0 GB` - decimal, not 1024-based.

    Decimal because the number beside it is a `Content-Length`, which is what a server advertises and
    what a release page prints. `MB` meaning `MiB` is the ambiguity worth avoiding, and writing `MiB`
    everywhere is louder than a progress bar deserves. si#178 arrived with the measurement that settles
    it: the product it came from caps a channel at 450'000'000 bytes because the channel rejects at
    500 MB decimal, and a 1024-based helper called that `429.2 MB` - comfortably under a cap it was in
    fact sitting on. That confusion cost it a failed publish. So the scale does not move.

    WHAT DID MOVE, AND WHY IT IS WORTH TWO CHARACTERS (si#178). `kB` is the strictly correct spelling -
    SI says the lower-case k - and it is now `KB` anyway. The reason is that this function exists to be
    the only one: three products had written it, each with the argument above in its own words, and the
    one that has published fact sheets beside every medium it ships could not adopt this copy without
    every one of those numbers changing shape. `KB` costs a character of pedantry the reader has never
    needed; not adopting costs a fourth implementation, which is the thing this function was made to
    prevent. The ambiguity actually being defended is decimal against binary, and `KB` here is a
    thousand bytes, said in the line above and driven in the tests.

    The thousands separator is the other half of the same request, and it reaches less than the ticket
    implies - measured on this function rather than on the product's. Every unit but the largest hands
    over at the next 1000, so `KB` and `MB` carry three digits and never a separator, and the bare-byte
    step stops at `999 B`, so si#178's `11,240,000,000 B` cannot arise here at all (that count is
    `11.2 GB`). `GB` has nothing above it, which is the one place the separator is both reachable and
    wanted: the terabyte totals a run of 5 GB media adds up to. Hence the format below carries it in the
    scaled branch only - putting it on a number that can never exceed three digits would be decoration
    claiming to be a feature.
    """
    for unit, scale in (("GB", 1_000_000_000), ("MB", 1_000_000), ("KB", 1_000)):
        if count >= scale:
            return f"{count / scale:,.1f} {unit}"
    return f"{int(count)} B"


def human_rate(per_second: float) -> str:
    return f"{human_bytes(per_second)}/s"


def render(label: str, received: int, total: int | None, elapsed: float, width: int, tick: int,
           *, bar: bool = True) -> str:
    """One progress line, at most `width` characters. Pure, which is what makes the arithmetic testable
    apart from the socket - and the arithmetic is the only part of a display worth a unit test.

    `total is None` is the honest answer to a server that sent no length, or a length describing a body
    it also said was compressed. In that state there is no percentage and no bar, because there is no
    denominator; what is left is the count, the rate and a spinner, which together still answer the
    question the whole ticket is about - is this thing moving.

    `bar=False` drops the drawn cells and the spinner, keeping the numbers. It is what a LOG gets. Bar
    cells are a thing a reader watches move; in a file where each line stands alone they are twenty-two
    characters saying what the percentage beside them already said, and they are what makes a bar look
    bolted onto a log rather than written for it.

    The truncation is not cosmetic. A line longer than the terminal wraps, and a wrapped line that is
    then repainted with `\\r` leaves a trail of half-lines behind it - the exact failure the terminal
    branch exists to avoid.
    """
    rate = received / elapsed if elapsed > 0 else 0.0
    parts = [label]
    if total is not None and total > 0:
        share = min(received / total, 1.0)
        if bar:
            filled = int(share * _BAR_CELLS)
            parts.append(f"[{'#' * filled}{'-' * (_BAR_CELLS - filled)}]")
        # FLOORED, not rounded. Measured on the real 87.3 MB docker bundle: `%3.0f` printed
        # `100%  87.0 MB/87.3 MB`, which says finished while 300 kB are still coming. A percentage
        # that cannot tell "nearly" from "done" is the defect this repository hunts, in miniature.
        parts.append(f"{int(share * 100):3d}%")
        parts.append(f" {human_bytes(received)}/{human_bytes(total)}")
    else:
        if bar:
            parts.append(_SPINNER[tick % len(_SPINNER)])
        parts.append(f" {human_bytes(received)}")
    parts.append(f" {human_rate(rate)}")
    return " ".join(parts)[:max(width, 0)]


class _Progress:
    """One transfer's reporting, and the ONE place the terminal question is asked.

    The two modes are not two styles of the same thing. A terminal gets a line repainted over itself,
    ten times a second, and one closing line. A pipe gets ordinary log lines and NEVER a carriage
    return: si#142 names this as the main correctness question, because this code runs in CI far more
    often than in a terminal, and a bar repainting into a GitHub Actions log is either thousands of
    lines or an unreadable smear. Degrading to silence is not the answer either - that would settle the
    ticket's complaint by making it true everywhere - so a pipe gets a heartbeat instead, rare enough
    that a short download costs a log two lines and no more: the opening one, which is where the size
    is, and the closing one. Counted by a test, because the first draft of this paragraph said ONE and
    nothing disagreed with it.
    """

    def __init__(self, label: str, total: int | None, started: float) -> None:
        self.label = label
        self.total = total
        self.started = started
        self.terminal = sys.stdout.isatty()
        self.painted: float | None = None
        self.tick = 0
        self.closed = False

    def _width(self) -> int:
        if not self.terminal:
            return _UNBOUNDED
        columns = shutil.get_terminal_size((80, 24)).columns
        return max(columns - log.PREFIX_WIDTH - 1, _MIN_WIDTH)

    def step(self, received: int, now: float) -> None:
        """Say where we are, unless we said so too recently."""
        interval = _TTY_REPAINT_S if self.terminal else _LOG_INTERVAL_S
        if self.painted is not None and now - self.painted < interval:
            return
        self.painted = now
        line = render(self.label, received, self.total, now - self.started, self._width(), self.tick,
                      bar=self.terminal)
        self.tick += 1
        if self.terminal:
            log.inplace(line)
        else:
            log.info(line)

    def close(self) -> None:
        """Leave the terminal line ready for whatever prints next, on EVERY path out.

        The failure path is why this is not simply the first line of `done`. A paint leaves the cursor
        at column one with the bar still standing to the right of it, so the exception message a caller
        prints lands ON the remains of a progress bar and is legible up to the point the bar is longer.
        A download that failed is exactly the moment its message has to be readable.
        """
        if self.terminal and not self.closed:
            log.clear_line()
        self.closed = True

    def done(self, received: int, now: float) -> None:
        """The one line both modes end on, and the only line a fast download in CI produces."""
        self.close()
        elapsed = now - self.started
        rate = received / elapsed if elapsed > 0 else 0.0
        log.ok(f"{self.label}  {human_bytes(received)} in {elapsed:.1f}s ({human_rate(rate)})")


# --- the download ----------------------------------------------------------------------------------


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """urllib's redirect handler, with the scheme rule applied to EVERY hop.

    Checking the URL that was asked for and the URL that answered leaves the MIDDLE of a redirect chain
    unchecked, and urllib's own rule there is not this module's: `HTTPRedirectHandler.http_error_302`
    admits `http`, `ftp` and even an empty scheme, and follows the whole chain before a caller sees
    anything at all. So `https -> http -> https` was accepted, and the check on `response.url` passed
    because the chain ended where it was supposed to. Whoever is on the path for the cleartext hop
    writes the `Location` of the next one, and what these three call sites do with what arrives is
    `chmod 0755` and run it, or hand it to the venv's own interpreter.

    Found in review, after this module had claimed in three places to have vetted the redirect - which
    was true of the last hop only.
    """

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> Any:
        _refuse_other_schemes(newurl, after_redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    """An opener carrying that handler. `urllib.request.urlopen` would use the default one, whose
    redirect handler is exactly what is being replaced.

    Built per call rather than once at import, and that is not tidiness. `HTTPSHandler.__init__`
    creates its SSL context eagerly, so an opener built at import freezes whatever certificate
    authorities were configured at import - a process that sets `SSL_CERT_FILE` afterwards, which is
    how a corporate proxy's CA usually arrives, would be ignored. Building one costs a few objects;
    a download costs a network round trip.
    """
    return urllib.request.build_opener(_HttpsOnlyRedirects)


def _refuse_other_schemes(url: str, *, after_redirect: bool = False) -> None:
    scheme = urlsplit(url).scheme.lower()
    if scheme in ALLOWED_SCHEMES:
        return
    allowed = "/".join(sorted(ALLOWED_SCHEMES))
    where = "the redirect led to" if after_redirect else "this is"
    raise DownloadError(
        f"refusing to download {url}: only {allowed} is fetched, and {where} "
        f"'{scheme or 'no scheme at all'}'. This is the kernel's one place to say so, so the answer is "
        f"the same for every caller rather than an argument in a comment beside each of them.")


def _announced_length(response: http.client.HTTPResponse) -> int | None:
    """How many bytes are coming, or None when nobody can know.

    A `Content-Length` beside a `Content-Encoding` is the interesting case: the number is right there
    and it describes the COMPRESSED body, so a caller that unpacks the bytes ends up with a different
    total than the one the bar was counting towards. urllib neither asks for nor decodes an encoding,
    so what lands on disk does match - but a bar has no way to tell which of the two it is measuring,
    and a percentage nobody can stand behind is worse than no percentage at all.
    """
    encoding = (response.headers.get("Content-Encoding") or "").strip().lower()
    if encoding not in ("", "identity"):
        return None
    declared = response.headers.get("Content-Length")
    if declared is None:
        return None
    try:
        return int(declared)
    except ValueError:
        return None


# --- resuming what a dropped connection left behind (si#176) ---------------------------------------
#
# THE HOLE THIS MAY NOT REOPEN. The discard above exists because `HTTPResponse.read(amt)` returns `b""`
# on a truncated body and raises nothing, so before si#142 a short download reported success and the
# next run treated a half file as cached. A resume is the one change that can walk straight back into
# that: appending to bytes nobody proved anything about produces a file of exactly the right LENGTH made
# of two different objects, which the length check cannot see and no later step will either.
#
# So a resume is allowed only when three things hold, and each is checked against what the server
# actually said rather than against what it supports in general:
#
#   1. the partial file carries a sidecar naming the URL it came from and the VERSION of the object it
#      was - the `ETag`, or the `Last-Modified` if that is all there is. Without one there is nothing to
#      ask the server about, so those bytes are discarded before a socket is opened;
#   2. the request carries `If-Range` with that version beside the `Range`, so the decision about whether
#      the bytes are still current is made by the only party that can make it. RFC 9110 requires a server
#      whose validator no longer matches to answer `200` with the whole object;
#   3. the answer is a `206` whose `Content-Range` starts at exactly the offset asked for. Anything else
#      is not a partial response to THIS request.
#
# AND THE CASE THAT CORRUPTS A FILE WHILE LOOKING LIKE IT WORKED: a server that ignores `Range` and sends
# the whole body again, saying nothing about it. Detected by the same rule as (3) and answered by
# TRUNCATING the partial file rather than appending to it - which is also the answer to a server with no
# range support at all, deliberately. `Accept-Ranges` is a claim; the status line is what happened, and
# only one of those two can be wrong about the bytes now arriving.
#
# WHAT IS DELIBERATELY NOT HERE: a retry loop. The product this came from wraps its resume in three
# attempts, and that is a policy - how many, how long between them, which failures are worth repeating -
# that belongs to whoever is watching the transfer. A partial file that SURVIVES the call is what makes
# calling again cheap, and that is the whole of what this adds.


def _validator(response: http.client.HTTPResponse) -> str:
    """Which version of the object answered, in the one form a later request can quote back.

    `ETag` first because it is exact; `Last-Modified` because a surprising number of asset hosts send
    only that, and a one-second-granularity timestamp is still a validator the SERVER compares - the
    client never has to reason about it. Empty means the server offered neither, and then no resume is
    possible at all: there is no question to ask, so the bytes cannot be vouched for.
    """
    for header in ("ETag", "Last-Modified"):
        value = (response.headers.get(header) or "").strip()
        if value:
            return value
    return ""


def _remember(source: Path, url: str, validator: str) -> None:
    """Two lines beside the partial file: where the bytes came from, and which version they are.

    Written as soon as the headers are in rather than when the transfer fails, because the failure this
    is for is a socket dying mid-body - there is no later moment that reliably runs.
    """
    source.write_text(f"{url}\n{validator}\n", encoding="utf-8")


def _resume_point(part: Path, source: Path, url: str) -> tuple[int, str]:
    """How many bytes may be kept, and the validator that lets the server rule on them. `(0, "")` means
    start over, and every path that cannot PROVE otherwise ends there."""
    try:
        have = part.stat().st_size
    except OSError:
        return 0, ""
    if have <= 0:
        return 0, ""
    try:
        recorded = source.read_text(encoding="utf-8").split("\n")
    except OSError:
        return 0, ""          # bytes with no provenance at all - an older version, or a crash between
    if len(recorded) < 2 or recorded[0] != url or not recorded[1]:
        return 0, ""          # a different URL, or a version the server was never asked to confirm
    return have, recorded[1]


def _request(url: str, offset: int, validator: str) -> urllib.request.Request:
    request = urllib.request.Request(url)
    if offset > 0:
        request.add_header("Range", f"bytes={offset}-")
        request.add_header("If-Range", validator)
    return request


def _respond(url: str, timeout: float, offset: int, validator: str) -> Any:
    """Open the transfer, and answer a `416` by asking again for the whole thing.

    The one retry is not a retry policy. `416` says the partial file is at least as long as the object
    it claims to be, which no amount of asking again will change - so the second request is a DIFFERENT
    question, and there is no third.
    """
    try:
        return _opener().open(_request(url, offset, validator), timeout=timeout)
    except urllib.error.HTTPError as refusal:
        if refusal.code != _RANGE_NOT_SATISFIABLE or offset == 0:
            raise
        refusal.close()
        return _opener().open(_request(url, 0, ""), timeout=timeout)


def _served_offset(response: http.client.HTTPResponse, asked: int) -> int:
    """Where the body about to arrive actually starts, which is not what was asked for.

    `0` for anything that is not a `206`: the server sent the whole object, either because it has no
    range support or because `If-Range` told it the caller's bytes are stale. Both mean the partial file
    is truncated, and BOTH ARE THE POINT - a client that assumed its own `Range` had been honoured would
    append a whole object onto half of one and produce a file that passes every check it has left.
    """
    if asked == 0 or getattr(response, "status", None) != 206:
        return 0
    served = _CONTENT_RANGE.match(response.headers.get("Content-Range") or "")
    if served is None or int(served.group(1)) != asked:
        raise DownloadError(
            f"{response.url} answered 206 for bytes {asked}- with Content-Range "
            f"{response.headers.get('Content-Range')!r}, which is not the range that was asked for. "
            f"Where those bytes belong in the file is exactly what a resume may not guess, so nothing "
            f"is written.")
    return asked


def _served_total(response: http.client.HTTPResponse, offset: int) -> int | None:
    """The size of the WHOLE object, which is what `received` is compared against at the end.

    For a `206` it is the third field of the `Content-Range`, because `Content-Length` there describes
    the slice and comparing against that would let a resume off the truncation check the whole module
    exists for.
    """
    if offset == 0:
        return _announced_length(response)
    served = _CONTENT_RANGE.match(response.headers.get("Content-Range") or "")
    if served is not None and served.group(3) != "*":
        return int(served.group(3))
    announced = _announced_length(response)
    return None if announced is None else offset + announced


def _staging(dest: Path, resume: bool) -> tuple[Path, Any, Path | None]:
    """Where the bytes land before they are the file, and the trade between the two answers.

    WITHOUT `resume`: a unique `mkstemp` name, so two runs downloading the same destination cannot land
    on one another. That is si#142's answer and it stays the default.

    WITH `resume`: `<dest>.part`, derived rather than random, because a name the next run cannot predict
    is a name the next run cannot resume. The cost is the uniqueness: two processes resuming the same
    destination at the same time would write into one file. That is the reason `resume` is opt-in rather
    than the default, and the reason this says so here - the caller asking for it is fetching one large
    medium into its own directory, not racing itself.
    """
    if resume:
        return (dest.parent / f"{dest.name}{_PART_SUFFIX}", None,
                dest.parent / f"{dest.name}{_SOURCE_SUFFIX}")
    # The descriptor is opened here and not at the point of writing, because `mkstemp` hands back a
    # descriptor to the file it created and nothing else may open that name in between. The caller
    # closes it on every path out, including the ones that never write a byte into it.
    handle, temporary = tempfile.mkstemp(dir=dest.parent, prefix=f"{dest.name}.", suffix=".part")
    return Path(temporary), os.fdopen(handle, "r+b"), None


def _sink(part: Path, opened: Any, offset: int) -> Any:
    """The file the body is written into, positioned where the body actually starts.

    A seek rather than append mode: `ab` ignores where the handle is pointed, so a server that answered
    `200` to a ranged request would have its whole body appended to the partial file by the one mode
    that cannot be told not to. Truncating at offset zero is the same rule stated once - whatever was
    in that file, the body now arriving replaces all of it.
    """
    stream = opened if opened is not None else open(part, "r+b" if offset > 0 else "wb")
    stream.seek(offset)
    if offset == 0:
        stream.truncate(0)
    return stream


def download(url: str, dest: str | Path, *, label: str = "",
             timeout: float = DEFAULT_TIMEOUT_S, resume: bool = False) -> Path:
    """Fetch `url` to `dest`, saying how far along it is, and return `dest`.

    `label` is what the progress line calls the thing; it defaults to the last segment of the URL,
    which is the file name in every case this kernel has. `timeout` bounds each socket operation
    rather than the whole transfer, so a large download over a slow link is fine and a stall is not.

    `resume` (si#176) keeps what arrived when a transfer dies mid-body, under `<dest>.part`, and
    continues from there the next time this is called with the same URL and destination. It is OPT-IN,
    and the default is the behaviour every caller in this kernel has today - a failure leaves the
    destination directory as it found it. The three artefacts this kernel fetches are small enough that
    a clean retry beats any of the machinery below; the caller it is for is fetching a five-gigabyte
    medium over a link that is sometimes a VPN, where discarding four and a half gigabytes is not a
    retry policy. The comment block above `_validator` carries the rules a resume has to satisfy and
    why none of them may be softened.

    A server with no range support is downloaded AGAIN, whole, inside the same call: the partial file is
    truncated first, so the fallback is a fresh download and never an append.

    Raises `DownloadError` - and only `DownloadError` - for a refused scheme, an HTTP error, a timeout,
    a truncated body or any transport failure, with the original exception attached as its cause.

    On any of those, nothing is left on disk: not under `dest`, and not under the temporary name
    either. The ONE exception is the point of `resume=True`, where a failed transfer deliberately leaves
    `<dest>.part` and `<dest>.part.source` behind - never under `dest` itself, which is the name a later
    run reads as cached.
    """
    _refuse_other_schemes(url)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    name = label or urlsplit(url).path.rsplit("/", 1)[-1] or dest.name

    # In the destination directory either way, so the rename at the end is a rename rather than a copy
    # across filesystems. Whether the name is unique or predictable is the resume trade; see `_staging`.
    temporary, handle, source = _staging(dest, resume)
    offset, validator = _resume_point(temporary, source, url) if source is not None else (0, "")
    started = time.monotonic()
    progress: _Progress | None = None
    received = 0
    # Bytes that were ALREADY proven before this call survive it whatever goes wrong here: a refused
    # redirect, a 503, a server answering nonsense. None of those says anything about what is on disk,
    # and deleting four and a half gigabytes over somebody else's misconfiguration is the behaviour this
    # whole change exists to stop.
    keep = offset > 0
    try:
        with _respond(url, timeout, offset, validator) as response:
            _refuse_other_schemes(response.url, after_redirect=True)
            offset = _served_offset(response, offset)
            total = _served_total(response, offset)
            if source is not None:
                # As soon as the headers are in, not when the body ends: the failure this exists for is
                # a socket dying mid-body, and there is no later moment that reliably runs. An empty
                # validator leaves no sidecar, so the bytes below are kept by nobody and discarded.
                served_by = _validator(response)
                if served_by:
                    _remember(source, url, served_by)
                    keep = True
            received = offset
            with _sink(temporary, handle, offset) as sink:
                progress = _Progress(name, total, started)
                progress.step(received, time.monotonic())
                while True:
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    sink.write(chunk)
                    received += len(chunk)
                    progress.step(received, time.monotonic())
        if total is not None and received != total:
            raise DownloadError(
                f"{url} announced {total} bytes and sent {received}; " + (
                    f"the {received} bytes that did arrive are kept in {temporary.name} and the next "
                    f"call with resume=True continues from there."
                    if keep else
                    "the partial file was discarded.") +
                f" A truncated body is not an error urllib reports - the read simply ends - so this is "
                f"the check between a short download and a file the next run would treat as cached.")
        os.replace(temporary, dest)
        keep = False          # the part IS the file now; the sweep below takes the sidecar with it
    except DownloadError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as failure:
        # ValueError is not decoration. `https://` plus a 300-character host is a syntactically fine
        # URL that urllib rejects with a UnicodeEncodeError out of the idna codec - which is a
        # ValueError and neither of the other two, so it escaped this function unwrapped, past a
        # docstring promising it could not. Found in review.
        raise DownloadError(f"could not download {url}: "
                            f"{type(failure).__name__}: {failure}") from failure
    finally:
        if progress is not None:
            progress.close()
        if handle is not None and not handle.closed:
            handle.close()          # the paths that failed before `_sink` ever took it over
        if not keep:
            temporary.unlink(missing_ok=True)
            if source is not None:
                source.unlink(missing_ok=True)

    # OUTSIDE the wrapping, deliberately. The file is in place by the time this runs, so an exception
    # from the closing line - a broken stdout is an OSError - would otherwise be re-raised as "could
    # not download" about a download that had already succeeded.
    if progress is not None:
        progress.done(received, time.monotonic())
    return dest
