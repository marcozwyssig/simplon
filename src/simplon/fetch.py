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
"""
from __future__ import annotations

import http.client
import os
import shutil
import sys
import tempfile
import time
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
    """`947 B`, `2.4 MB`, `1.1 GB` - decimal, not 1024-based.

    Decimal because the number beside it is a `Content-Length`, which is what a server advertises and
    what a release page prints. `MB` meaning `MiB` is the ambiguity worth avoiding, and writing `MiB`
    everywhere is louder than a progress bar deserves.
    """
    for unit, scale in (("GB", 1_000_000_000), ("MB", 1_000_000), ("kB", 1_000)):
        if count >= scale:
            return f"{count / scale:.1f} {unit}"
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


def download(url: str, dest: str | Path, *, label: str = "",
             timeout: float = DEFAULT_TIMEOUT_S) -> Path:
    """Fetch `url` to `dest`, saying how far along it is, and return `dest`.

    `label` is what the progress line calls the thing; it defaults to the last segment of the URL,
    which is the file name in every case this kernel has. `timeout` bounds each socket operation
    rather than the whole transfer, so a large download over a slow link is fine and a stall is not.

    Raises `DownloadError` - and only `DownloadError` - for a refused scheme, an HTTP error, a timeout,
    a truncated body or any transport failure, with the original exception attached as its cause.

    On any of those, nothing is left on disk: not under `dest`, and not under the temporary name
    either.
    """
    _refuse_other_schemes(url)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    name = label or urlsplit(url).path.rsplit("/", 1)[-1] or dest.name

    # Unique within the destination directory, so two runs cannot land on one another, and IN that
    # directory, so the rename at the end is a rename rather than a copy across filesystems.
    handle, temporary = tempfile.mkstemp(dir=dest.parent, prefix=f"{dest.name}.", suffix=".part")
    started = time.monotonic()
    progress: _Progress | None = None
    received = 0
    try:
        with os.fdopen(handle, "wb") as sink:
            with _opener().open(url, timeout=timeout) as response:
                _refuse_other_schemes(response.url, after_redirect=True)
                total = _announced_length(response)
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
                f"{url} announced {total} bytes and sent {received}; the partial file was discarded. "
                f"A truncated body is not an error urllib reports - the read simply ends - so this is "
                f"the check between a short download and a file the next run would treat as cached.")
        os.replace(temporary, dest)
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
        Path(temporary).unlink(missing_ok=True)

    # OUTSIDE the wrapping, deliberately. The file is in place by the time this runs, so an exception
    # from the closing line - a broken stdout is an OSError - would otherwise be re-raised as "could
    # not download" about a download that had already succeeded.
    if progress is not None:
        progress.done(received, time.monotonic())
    return dest
