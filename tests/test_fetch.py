"""`simplon.fetch` - the kernel's one download, driven rather than described.

WHY THIS FILE LOOKS LIKE WORK. A progress bar is display, so the cheap test is an assertion over a
format string, and si#142 says in as many words that such a test proves nothing about the case that
matters. So nothing here stubs the transport. A real HTTPS server on a real socket serves a real file,
the download runs for real, and the two output modes are told apart by what file descriptor 1 REALLY is
- a pty for the terminal half, a pipe for the CI half - rather than by a `StringIO` with a lying
`isatty`. That distinction is the whole ticket: a test over a fake `isatty` proves the branch is
reachable and says nothing about whether the branch is ever taken.

WHY THE SERVER SPEAKS TLS. `download` refuses anything but https, one place, for every caller. The
obvious way to test its mechanics is to turn that guard off for localhost; the cost is that every
mechanics test then runs down a path production never takes. A self-signed certificate plus
`SSL_CERT_FILE` costs one fixture, and it was measured BEFORE it was chosen: all four served
behaviours - a whole body, no `Content-Length`, a truncated body, a server that never answers - come
out of urllib identically over TLS and in the clear, because Python's `SSLSocket` is built with
`suppress_ragged_eofs=True` and returns `b""` on a close carrying no `close_notify`. The guard keeps its
own tests, against `http://`, `file://` and `ftp://`, which is where its evidence belongs.

THE ONE THING THE SERVER TAUGHT THE IMPLEMENTATION. `/half` announces a length and sends half of it.
`HTTPResponse.read(amt)` on that returns `b""` and raises NOTHING, so a loop that trusts EOF finishes
happily and renames a half file onto the final name - the very defect the temporary-name rule exists to
prevent, walking in through a door that rule was not watching. That is why `download` compares what it
received against what was announced.

WHAT si#176 ADDED TO THAT, AND WHY IT IS THE SAME PROOF STANDARD. A resume is the one change that can
reopen the hole above: appending to bytes nobody proved anything about produces a file of exactly the
right length made of two different objects, which no length check can see. So the server below grew a
VERSION - an ETag and a body that a test can change between two calls - and four range behaviours a real
server really has: one that honours a `Range`, one that says `Accept-Ranges: none`, one that ignores the
header without a word, and one that answers `206` confirming a range it did not serve. The dropped
connection is produced rather than simulated: a request with no `Range` announces the whole length and
sends half of it, then closes. What every resume test finally asserts is the file, byte for byte.
"""
import datetime
import fcntl
import os
import pty
import re
import ssl
import struct
import sys
import termios
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from simplon import fetch

#: Big enough that a bar has something to repaint over, small enough that the suite does not notice.
#: The handler spends it in eight slices with a pause between them, so a transfer takes ~0.4s and the
#: 0.1s repaint interval produces several paints rather than exactly one.
BODY = b"simplon-" * 32_000        # 256000 bytes

#: Where a redirecting path sends the caller next. Filled by the test that needs the hop, because the
#: ports only exist once the server fixtures have run.
ROUTES: dict = {}
SLICES = 8
PAUSE_S = 0.05

#: A second body, DIFFERENT from `BODY` in every byte and of the same length. Same length on purpose:
#: an object that changed under a resume must be caught by the validator and not by arithmetic that
#: happens to disagree, so the test cannot pass for the wrong reason.
OTHER = b"changed!" * 32_000

#: The object `/resumable`, `/norange` and `/ignores-range` are serving RIGHT NOW. A dict rather than a
#: constant because "the object changed between the two halves of a resume" is the case that corrupts a
#: file, and the only way to drive it is to change it.
VERSION: dict = {"etag": '"v1"', "body": BODY}

#: Every `(path, Range, If-Range)` the server was asked for. A resume that is really a silent full
#: download produces the same file, so the file alone cannot tell the two apart; this can.
SEEN: list = []


# --- the server ---------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    """Four behaviours a real server really has, one per path."""

    protocol_version = "HTTP/1.1"

    def do_GET(self):                                    # noqa: N802 - BaseHTTPRequestHandler's name
        if self.path == "/whole":
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self._slowly()
        elif self.path == "/nolength":
            # HTTP/1.0 so there is no keep-alive to need a length: the close IS the end of the body.
            # Sent slowly like /whole, because the indeterminate path is only exercised by a transfer
            # that lasts longer than one repaint - a body that arrives in one gulp would let a bar that
            # never advances pass this test.
            self.protocol_version = "HTTP/1.0"
            self.send_response(200)
            self.end_headers()
            self._slowly()
            self.close_connection = True
        elif self.path == "/gzipped":
            # A length that describes the COMPRESSED body. urllib does not ask for gzip and does not
            # decode it, so the bytes on the wire match this number - but a caller that unpacks them
            # would not, and a bar has no way to know which of the two it is measuring.
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)
        elif self.path == "/half":
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY[:len(BODY) // 2])
            self.wfile.flush()
            self.close_connection = True
        elif self.path == "/resumable":
            self._object(honour_range=True, accept_ranges="bytes")
        elif self.path == "/norange":
            self._object(honour_range=False, accept_ranges="none")
        elif self.path == "/ignores-range":
            self._object(honour_range=False, accept_ranges=None)
        elif self.path == "/wrongrange":
            # `206`, and a `Content-Range` saying it is serving from zero whatever was asked for. The
            # status line says "partial" and the only header that says WHICH part disagrees with the
            # request, so a client that reads the status and not the header appends the whole object
            # onto its own partial copy.
            SEEN.append((self.path, self.headers.get("Range"), self.headers.get("If-Range")))
            self.send_response(206)
            self.send_header("ETag", VERSION["etag"])
            self.send_header("Content-Range", f"bytes 0-{len(BODY) - 1}/{len(BODY)}")
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)
        elif self.path in ROUTES:
            # A redirect to wherever a test has pointed this path. The handlers are shared classes and
            # the ports are only known once the fixtures have run, so where a hop leads is data rather
            # than something written into the handler.
            self.send_response(302)
            self.send_header("Location", ROUTES[self.path])
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/blackhole":
            # Accepts, answers nothing. Bounded so a broken test cannot wedge the suite for a minute.
            time.sleep(20)
        else:
            self.send_error(404)

    def _object(self, *, honour_range, accept_ranges):
        """One versioned object, served the four ways a real server serves one.

        NO `Range` AT ALL: announce the whole length and send HALF of it, then close. That is the
        dropped connection the whole ticket is about, produced rather than simulated - and it is what
        leaves a `.part` for the next call to resume.

        A `Range` THIS SERVER HONOURS, with an `If-Range` naming the version it still has: `206` and a
        `Content-Range` saying which bytes are coming.

        A `Range` IT DOES NOT HONOUR, or an `If-Range` naming a version it no longer has: `200` and the
        WHOLE body again. RFC 9110 requires exactly this of the second case, and the first is what a
        server with no range support does anyway - which is why the client has one rule for both.

        A `Range` STARTING PAST THE END: `416`. A partial file longer than the object it claims to be
        can only come from a stale one, and without this the download would be wedged forever.
        """
        body = VERSION["body"]
        etag = VERSION["etag"]
        wanted = self.headers.get("Range")
        conditional = self.headers.get("If-Range")
        SEEN.append((self.path, wanted, conditional))

        start = None
        if wanted and honour_range and conditional in (None, etag):
            start = int(wanted.removeprefix("bytes=").split("-")[0])

        if start is not None and start >= len(body):
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(body)}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if start is not None:
            self.send_response(206)
            self.send_header("ETag", etag)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
            self.send_header("Content-Length", str(len(body) - start))
            self.end_headers()
            self.wfile.write(body[start:])
            return

        self.send_response(200)
        self.send_header("ETag", etag)
        if accept_ranges is not None:
            self.send_header("Accept-Ranges", accept_ranges)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if wanted is None:
            self.wfile.write(body[:len(body) // 2])
            self.wfile.flush()
            self.close_connection = True
        else:
            self.wfile.write(body)

    def _slowly(self):
        """The body in eight slices with a pause between them, so a bar has time to be a bar."""
        step = len(BODY) // SLICES
        for start in range(0, len(BODY), step):
            self.wfile.write(BODY[start:start + step])
            self.wfile.flush()
            time.sleep(PAUSE_S)

    def log_message(self, *args):                        # noqa: A002 - silence the stderr access log
        pass


def _certificate(directory: Path) -> tuple[Path, Path]:
    """A self-signed cert for `localhost`, EC rather than RSA because a 2048-bit keygen is a tenth of a
    second the suite has no reason to spend. `cryptography` is already a kernel dependency."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    certificate = directory / "cert.pem"
    private = directory / "key.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return certificate, private


class _CleartextHandler(BaseHTTPRequestHandler):
    """A plaintext hop that sends the chain back to https - the middle of the attack, in miniature."""

    def do_GET(self):                                    # noqa: N802
        self.send_response(302)
        self.send_header("Location", ROUTES.get("cleartext-onward", "https://localhost/whole"))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def cleartext():
    """A real `http://` server, so the middle hop is genuinely in the clear rather than simulated."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _CleartextHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """(base url, path to the CA the client has to trust). One server for the whole module."""
    directory = tmp_path_factory.mktemp("tls")
    certificate, private = _certificate(directory)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"https://localhost:{httpd.server_address[1]}", certificate
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def base(server, monkeypatch):
    """The base URL, with this module's CA trusted for the duration of ONE test.

    Set per test rather than per session on purpose: `SSL_CERT_FILE` is read by OpenSSL whenever a
    default context is built, so a session-wide value would quietly be in force for every other suite
    in the run.
    """
    url, certificate = server
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    return url


# --- what file descriptor 1 really received -------------------------------------------------------


class _Captured:
    """Filled once the block has ended, because a pty is drained after the writer is done with it."""

    text = ""


@contextmanager
def _capture(*, tty: bool):
    """Run the block with fd 1 REALLY being a terminal, or really not being one.

    The kernel's log functions `print`, and `print` writes through `sys.stdout`'s own buffered wrapper
    over whatever fd 1 was when the interpreter started. So both have to move: the descriptor, because
    that is what `isatty()` and `shutil.get_terminal_size` ask about, and the wrapper, because that is
    where the bytes actually go.

    ONLCR is turned off on the pty. A terminal in its default mode rewrites every `\\n` on the way out
    as `\\r\\n`, which would put carriage returns into the capture that the code under test never wrote -
    and a carriage return is precisely what the terminal half is asserting about.
    """
    if tty:
        read_fd, write_fd = pty.openpty()
        attributes = termios.tcgetattr(write_fd)
        attributes[1] &= ~termios.ONLCR
        termios.tcsetattr(write_fd, termios.TCSANOW, attributes)
        # A fresh pty reports 0x0, and `shutil.get_terminal_size` passes a zero straight through. A
        # real terminal has a size; this one gets 100 columns so the bar has room to be a bar.
        fcntl.ioctl(write_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
    else:
        read_fd, write_fd = os.pipe()

    captured = _Captured()
    saved = os.dup(1)
    stashed = sys.stdout
    os.dup2(write_fd, 1)
    sys.stdout = os.fdopen(os.dup(1), "w", buffering=1)
    try:
        yield captured
    finally:
        sys.stdout.flush()
        sys.stdout.close()
        sys.stdout = stashed
        os.dup2(saved, 1)
        os.close(saved)
        blocks = []
        os.set_blocking(read_fd, False)
        while True:
            try:
                block = os.read(read_fd, 65536)
            except BlockingIOError:
                break
            except OSError:                      # a pty with no writer left answers EIO, not EOF
                break
            if not block:
                break
            blocks.append(block)
        os.close(read_fd)
        os.close(write_fd)
        captured.text = b"".join(blocks).decode("utf-8", "replace")


def test_the_harness_reports_a_terminal_as_a_terminal_and_a_pipe_as_a_pipe():
    """The harness is the whole proof standard, so it is checked before anything is proved with it. A
    harness nobody verified is where a green suite that means nothing comes from."""
    # act
    with _capture(tty=True) as terminal:
        print("hello", end="", flush=True)
        was_a_tty = sys.stdout.isatty()
    with _capture(tty=False) as pipe:
        print("hello", end="", flush=True)
        was_a_pipe = not sys.stdout.isatty()

    # assert
    assert was_a_tty and was_a_pipe
    assert terminal.text == "hello"
    assert pipe.text == "hello"


# --- the four driven behaviours -------------------------------------------------------------------


def test_a_terminal_gets_one_line_repainted_rather_than_a_page_of_them(base, tmp_path):
    """The terminal half. A bar is only a bar if it paints over itself, MORE THAN ONCE, with a
    different number each time.

    Counting carriage returns alone was the first version of this and it was weaker than it looked:
    the closing `clear_line` writes one of its own, so a bar that painted exactly once and then
    finished would have passed a `>= 2` count while being no bar at all. What is asserted instead is
    the property with no way to fake it - several paints, several distinct percentages, and still only
    one line on the screen.
    """
    # act
    with _capture(tty=True) as shown:
        fetch.download(f"{base}/whole", tmp_path / "f.bin")

    # assert
    text = shown.text
    assert text.count("==>") >= 3, f"the bar painted fewer than three times: {text!r}"
    assert text.count("\r") >= text.count("==>"), "a paint left the cursor where the next one starts"
    advanced = set(re.findall(r"(\d+)%", text))
    assert len(advanced) >= 2, f"the bar never advanced; it showed {sorted(advanced)}: {text!r}"
    assert len([line for line in text.split("\n") if line.strip()]) <= 2, (
        f"a terminal got more than the bar line and the line that closes it: {text!r}")
    assert (tmp_path / "f.bin").read_bytes() == BODY


def human_bytes_of(body: bytes) -> str:
    """What the closing line has to say the transfer was, computed rather than typed."""
    return fetch.human_bytes(len(body))


def test_a_pipe_gets_no_carriage_return_at_all(base, tmp_path):
    """THE MAIN CORRECTNESS QUESTION of si#142. This runs in CI far more often than in a terminal, and
    a bar repainting with `\\r` into a GitHub Actions log is either thousands of lines or a smear.

    The other half of the assertion matters as much: a pipe must still be told SOMETHING. Degrading to
    silence would answer the ticket's complaint by making it true everywhere.
    """
    # act
    with _capture(tty=False) as shown:
        fetch.download(f"{base}/whole", tmp_path / "f.bin")

    # assert
    text = shown.text
    assert "\r" not in text, f"a carriage return reached a log file: {text!r}"
    assert "\033[K" not in text, f"a cursor-movement escape reached a log file: {text!r}"
    assert text.strip(), "a pipe was told nothing at all, which is the defect this ticket is about"
    assert "[####" not in text and "[----" not in text, (
        f"bar cells were drawn into a log file, where nobody watches them move: {text!r}")
    assert (tmp_path / "f.bin").read_bytes() == BODY


@pytest.mark.parametrize("path", ["nolength", "gzipped"])
def test_a_length_that_cannot_be_trusted_never_becomes_a_percentage(path, base, tmp_path):
    """A server may send no `Content-Length`, or send one describing a compressed body. Both are
    "unknown" to a bar, and the second is the one that looks knowable: the number is right there, it
    just is not the number of bytes the caller ends up with."""
    # act
    with _capture(tty=True) as shown:
        fetch.download(f"{base}/{path}", tmp_path / "f.bin")

    # assert
    assert "%" not in shown.text, f"a percentage was claimed that nobody could know: {shown.text!r}"
    assert shown.text.strip(), "an unknown length is not a reason to say nothing"
    assert human_bytes_of(BODY) in shown.text, "the count nobody needs a total for was not shown either"
    assert (tmp_path / "f.bin").read_bytes() == BODY


def test_a_body_that_stops_halfway_leaves_nothing_at_all_behind(base, tmp_path):
    """A half-written docker.tgz that a later run reads as cached is a defect that hides for weeks.

    Two claims, and the second is the one the server had to teach us: nothing under the FINAL name, and
    nothing under the temporary one either. `HTTPResponse.read` returns `b""` on a truncated body and
    raises nothing, so without the length check this download reports success.
    """
    # arrange
    dest = tmp_path / "docker.tgz"

    # act
    with _capture(tty=True) as shown:
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/half", dest)

    # assert
    assert not dest.exists(), "a partial file is sitting under the name a cache check looks for"
    assert list(tmp_path.iterdir()) == [], "a temporary file was left behind"
    # A third claim, about the moment a message matters most: a paint leaves the cursor at column one
    # with the bar still standing to its right, so a failure that did not close the line would have its
    # reason printed ON the remains of a progress bar.
    assert shown.text.endswith("\r\033[K"), f"the bar was left on the screen: {shown.text!r}"


def test_a_server_that_accepts_and_never_answers_fails_instead_of_hanging(base, tmp_path):
    """`urlretrieve` has no timeout, so a hung server hangs the command forever with no output at all -
    the second half of the same complaint that motivates the ticket."""
    # arrange
    started = time.monotonic()

    # act / assert
    with pytest.raises(fetch.DownloadError):
        fetch.download(f"{base}/blackhole", tmp_path / "f.bin", timeout=0.5)

    assert time.monotonic() - started < 10, "the timeout did not fire; the server sleeps for 20s"
    assert list(tmp_path.iterdir()) == []


# --- the one place a scheme is refused ------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://download.docker.com/x.tgz",
    "file:///etc/passwd",
    "ftp://ftp.gnu.org/x.tgz",
    "/etc/passwd",
])
def test_only_https_is_ever_fetched(url, tmp_path):
    """The argument both `# noqa: S310` comments used to make in prose, made once in code instead.

    `urlretrieve` opens `file://` and `ftp://` without comment, so "the URL is a pinned https asset" was
    a property of the call site rather than of the code - true of the three call sites that existed and
    of no call site a consuming product writes.
    """
    # act / assert
    with pytest.raises(fetch.DownloadError, match="https"):
        fetch.download(url, tmp_path / "f.bin")

    assert list(tmp_path.iterdir()) == [], "a refused download still created a file"


# --- every hop of a redirect, not the first and the last ------------------------------------------
#
# The headers below are how the servers are told where to send the chain next: the handlers are shared
# module-level classes and the ports are only known at fixture time, so the URL travels with the
# request instead of being baked into the handler.


def test_an_ordinary_https_redirect_is_still_followed(base, tmp_path, monkeypatch):
    """The guard below must not become "refuse every redirect". The oras release asset IS one - GitHub
    redirecting to objects.githubusercontent.com - and it is one of the three call sites."""
    # arrange
    monkeypatch.setitem(ROUTES, "/hop", f"{base}/whole")

    # act
    with _capture(tty=False):
        fetch.download(f"{base}/hop", tmp_path / "f.bin")

    # assert
    assert (tmp_path / "f.bin").read_bytes() == BODY


def test_a_redirect_chain_may_not_pass_through_cleartext(base, cleartext, tmp_path, monkeypatch):
    """THE HOLE REVIEW FOUND, and the reason this file has a plaintext server in it.

    Checking the URL that was asked for and the URL that answered leaves the MIDDLE of the chain
    unchecked, and urllib's own rule there is not this module's: it admits `http`, `ftp` and even an
    empty scheme, and follows the whole thing before a caller sees anything. This chain starts on
    https and ENDS on https, so both checks passed while one hop travelled in the clear - and whoever
    is on the path for that hop writes the Location of the next one. What these call sites then do
    with what arrives is `chmod 0755` and run it.
    """
    # arrange: https -> http -> https, all three real
    monkeypatch.setitem(ROUTES, "/hop", f"{cleartext}/onward")
    monkeypatch.setitem(ROUTES, "cleartext-onward", f"{base}/whole")

    # act / assert
    with pytest.raises(fetch.DownloadError, match="https"):
        with _capture(tty=False):
            fetch.download(f"{base}/hop", tmp_path / "f.bin")

    assert list(tmp_path.iterdir()) == []


# --- what a CI log actually costs ------------------------------------------------------------------


def test_a_short_download_costs_a_log_two_lines(base, tmp_path):
    """The claim the module docstring makes, held to a count.

    Its first draft said ONE line and nothing disagreed - the opening paint happens before the
    throttle can suppress anything, so there were always two. Two is the right number (the opening
    line is where the size is), and now it is the number that is written down.
    """
    # act
    with _capture(tty=False) as shown:
        fetch.download(f"{base}/whole", tmp_path / "f.bin")

    # assert
    assert len([line for line in shown.text.split("\n") if line.strip()]) == 2, repr(shown.text)


def test_a_long_download_leaves_a_heartbeat_between_those_two(base, tmp_path, monkeypatch):
    """And the other half: a log is not left silent for the length of a 20-minute transfer. The
    interval is a module constant precisely so this can be driven without the function growing a
    parameter nobody asked for."""
    # arrange
    monkeypatch.setattr(fetch, "_LOG_INTERVAL_S", 0.05)

    # act
    with _capture(tty=False) as shown:
        fetch.download(f"{base}/whole", tmp_path / "f.bin")

    # assert
    assert len([line for line in shown.text.split("\n") if line.strip()]) > 2, repr(shown.text)
    assert "\r" not in shown.text, "the heartbeat is still ordinary log lines"


# --- the arithmetic, which is the only part worth a unit test -------------------------------------


def test_a_server_that_over_sends_cannot_produce_a_hundred_and_one_percent():
    """Clamped rather than trusted: the number is the server's, and the bar is ours."""
    line = fetch.render("x", received=120, total=100, elapsed=1.0, width=200, tick=0)

    assert "100%" in line and "101%" not in line


def test_all_but_the_last_bytes_is_not_a_hundred_percent():
    """Measured on the real 87.3 MB docker bundle, where a rounded percentage said `100%` beside
    `87.0 MB/87.3 MB`. An outcome that cannot tell "nearly" from "done" is the defect this repository
    hunts, and a bar is not exempt from it because it is only a display."""
    line = fetch.render("x", received=99_600, total=100_000, elapsed=1.0, width=200, tick=0)

    assert "100%" not in line
    assert " 99%" in line


def test_an_unknown_total_produces_no_percentage_and_no_bar():
    line = fetch.render("x", received=120, total=None, elapsed=1.0, width=200, tick=0)

    assert "%" not in line and "[" not in line


def test_no_elapsed_time_yet_is_not_a_division_by_zero():
    line = fetch.render("x", received=120, total=1000, elapsed=0.0, width=200, tick=0)

    assert "0 B/s" in line


def test_the_line_never_outgrows_the_room_it_was_given():
    """A wrapped `\\r` line is not a cosmetic problem: the terminal leaves a trail of half-lines behind,
    which is the exact failure the terminal branch exists to avoid."""
    line = fetch.render("a-long-label-for-a-narrow-window", received=1, total=2, elapsed=1.0,
                        width=20, tick=0)

    assert len(line) <= 20


# --- a short read can be resumed (si#176) ---------------------------------------------------------
#
# The discard this replaces exists for a measured reason and the replacement may not soften it: a
# `.part` that is resumed has to be provably the same object it was. So every test below ends on the
# FILE, byte for byte, and the three refusal shapes are driven against real servers rather than argued
# about - a server with no range support, a server that ignores the header without a word, and a `.part`
# that nothing proves anything about.


@pytest.fixture
def versioned():
    """The served object back at v1, and the request log empty. Both are module state, because the case
    worth driving is the object CHANGING between the two halves of one resume."""
    VERSION["etag"], VERSION["body"] = '"v1"', BODY
    SEEN.clear()
    yield VERSION
    VERSION["etag"], VERSION["body"] = '"v1"', BODY
    SEEN.clear()


def _ranges_asked_for():
    return [asked for _, asked, _ in SEEN if asked]


def test_a_dropped_connection_leaves_a_part_that_the_next_call_finishes(base, tmp_path, versioned):
    """THE TICKET. Five gigabytes over a VPN that drops at four and a half is not a retry policy.

    Both halves are real: the server announces the whole length and closes after half of it, and the
    second call carries a `Range` the server honours. The last assertion is the only one that settles
    it - the finished file against the original, byte for byte, because a resume that appends the wrong
    bytes produces a file of exactly the right length.
    """
    # arrange
    dest = tmp_path / "big.iso"

    # act: the drop
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/resumable", dest, resume=True)
    part = tmp_path / "big.iso.part"
    kept = part.stat().st_size

    # act: the resume
    with _capture(tty=False):
        fetch.download(f"{base}/resumable", dest, resume=True)

    # assert
    assert kept == len(BODY) // 2, "the part did not keep what arrived before the drop"
    assert _ranges_asked_for() == [f"bytes={kept}-"], f"the second call did not resume: {SEEN}"
    assert dest.read_bytes() == BODY, "the finished file is not the object that was served"
    assert not part.exists(), "the part outlived the file it became"
    assert not (tmp_path / "big.iso.part.source").exists(), "the sidecar was left behind"


def test_the_bytes_already_on_disk_are_not_fetched_a_second_time(base, tmp_path, versioned):
    """The property the ticket is actually buying, and the file alone cannot show it: a silent full
    re-download produces exactly the same file. What separates them is what crossed the wire."""
    # arrange
    dest = tmp_path / "big.iso"
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/resumable", dest, resume=True)

    # act
    with _capture(tty=False) as shown:
        fetch.download(f"{base}/resumable", dest, resume=True)

    # assert
    assert _ranges_asked_for() == [f"bytes={len(BODY) // 2}-"]
    # And the reporting counts the bytes already on disk: a resume that started its percentage at zero
    # would tell the operator it is doing the whole thing again.
    assert "50%" in shown.text or "51%" in shown.text, (
        f"the resumed transfer did not start from what it already had: {shown.text!r}")


def test_a_server_with_no_range_support_is_downloaded_again_rather_than_appended_to(
        base, tmp_path, versioned):
    """The decision si#176 asks for out loud: no range support means a FRESH download, in the same call.

    It is the same rule as the case below and that is deliberate - `Accept-Ranges: none` is a claim, and
    a claim is not what this reads. The status line is: anything that is not a `206` is the whole object
    again, so the part is truncated before a byte of it is written.
    """
    # arrange
    dest = tmp_path / "tool.tgz"
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/norange", dest, resume=True)
    assert (tmp_path / "tool.tgz.part").stat().st_size == len(BODY) // 2

    # act
    with _capture(tty=False):
        fetch.download(f"{base}/norange", dest, resume=True)

    # assert
    assert _ranges_asked_for() == [f"bytes={len(BODY) // 2}-"], "no range was ever asked for"
    assert dest.read_bytes() == BODY, "half a body was left in front of a whole one"
    assert len(dest.read_bytes()) == len(BODY), "the file grew by the half that was already there"


def test_a_server_that_ignores_range_without_a_word_is_detected_rather_than_appended_to(
        base, tmp_path, versioned):
    """THE CASE THAT CORRUPTS A FILE WHILE LOOKING LIKE IT WORKED, and the reason the rule is the status
    line rather than a header.

    This server says nothing at all: no `Accept-Ranges`, no `Content-Range`, no `206`. It just sends the
    whole body to a request that asked for the tail of it. A client that trusts its own `Range` and
    appends ends up with 384000 bytes where 256000 were served - the right file nowhere inside it - and
    no length check can see it, because the length it compares against is the one the server announced
    for the part it never sent.
    """
    # arrange
    dest = tmp_path / "tool.tgz"
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/ignores-range", dest, resume=True)

    # act
    with _capture(tty=False):
        fetch.download(f"{base}/ignores-range", dest, resume=True)

    # assert
    assert _ranges_asked_for() == [f"bytes={len(BODY) // 2}-"]
    assert dest.read_bytes() == BODY
    assert BODY[:len(BODY) // 2] + BODY != dest.read_bytes(), "the naive append is what landed"


def test_a_range_the_server_confirms_but_did_not_serve_is_refused(base, tmp_path, versioned):
    """A `206` whose `Content-Range` starts somewhere else is not a partial response to THIS request.

    Nothing here can guess what to do with it: the bytes may be the whole object, they may be a
    different window, and the only honest answer is to refuse rather than to decide. Driven because a
    client that reads the status and skips the header treats this exactly like a good resume.
    """
    # arrange
    dest = tmp_path / "tool.tgz"
    part = tmp_path / "tool.tgz.part"
    part.write_bytes(BODY[:len(BODY) // 2])
    (tmp_path / "tool.tgz.part.source").write_text(f"{base}/wrongrange\n\"v1\"\n")

    # act / assert
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError, match="Content-Range"):
            fetch.download(f"{base}/wrongrange", dest, resume=True)

    assert not dest.exists(), "a body nobody could place was written to the final name"
    assert part.read_bytes() == BODY[:len(BODY) // 2], (
        "bytes that were already proven were deleted over a failure that said nothing about them")


def test_a_part_the_object_no_longer_matches_is_thrown_away_rather_than_completed(
        base, tmp_path, versioned):
    """The `.part` that does not match. The bytes are half of one object, the server now has another,
    and the two are the same length so no arithmetic will ever notice.

    What notices is `If-Range`: the sidecar recorded the version those bytes came from, the server no
    longer has it, and RFC 9110 says the answer is the whole current object with a `200`. Which is the
    same rule as the two tests above, arriving from a third direction.
    """
    # arrange
    dest = tmp_path / "big.iso"
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/resumable", dest, resume=True)
    VERSION["etag"], VERSION["body"] = '"v2"', OTHER

    # act
    with _capture(tty=False):
        fetch.download(f"{base}/resumable", dest, resume=True)

    # assert
    assert SEEN[-1][2] == '"v1"', f"the resume did not say which version it had: {SEEN}"
    assert dest.read_bytes() == OTHER, "the object that is actually there is not what landed"
    assert dest.read_bytes() != BODY[:len(BODY) // 2] + OTHER[len(OTHER) // 2:], (
        "two different objects were spliced into one file of exactly the right length")


def test_a_part_nothing_proves_anything_about_is_not_resumed(base, tmp_path, versioned):
    """A `.part` with no sidecar beside it - left by an older version, a crash between the two writes,
    or a completely different URL. There is no validator, so there is no way to ask the server whether
    those bytes are still the right ones, and a resume that cannot ask is a guess.

    Discarded locally, before a socket is opened: the request that follows carries no `Range` at all.
    """
    # arrange
    dest = tmp_path / "f.bin"
    part = tmp_path / "f.bin.part"
    part.write_bytes(b"garbage" * 1000)

    # act: this server drops halfway whenever it is asked without a `Range`, which is exactly what has
    # to happen here - so the first call is the proof and the second one only shows the recovery works.
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/resumable", dest, resume=True)
    with _capture(tty=False):
        fetch.download(f"{base}/resumable", dest, resume=True)

    # assert
    assert _ranges_asked_for() == [f"bytes={len(BODY) // 2}-"], (
        f"bytes nobody vouched for were resumed: {SEEN}")
    assert dest.read_bytes() == BODY
    assert b"garbage" not in dest.read_bytes()


def test_a_part_recorded_against_another_url_is_not_resumed(base, tmp_path, versioned):
    """The same rule with the sidecar present and naming somewhere else. One destination, two sources,
    and the bytes belong to the one that is not being asked for."""
    # arrange
    dest = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(BODY[:1000])
    (tmp_path / "f.bin.part.source").write_text('https://elsewhere.test/f.bin\n"v1"\n')

    # act
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/resumable", dest, resume=True)
    first = list(SEEN)
    with _capture(tty=False):
        fetch.download(f"{base}/resumable", dest, resume=True)

    # assert
    assert [asked for _, asked, _ in first if asked] == [], (
        f"a part recorded against another URL was resumed: {first}")
    assert dest.read_bytes() == BODY


def test_a_part_longer_than_the_object_does_not_wedge_the_download_forever(
        base, tmp_path, versioned):
    """`416 Range Not Satisfiable`, which is what a server answers when the part claims more bytes than
    the object has. Without an answer to it the retry asks the same impossible question every run and
    the download never completes again - a resume that cannot recover is worse than no resume."""
    # arrange
    dest = tmp_path / "big.iso"
    part = tmp_path / "big.iso.part"
    part.write_bytes(BODY + b"and then some")
    (tmp_path / "big.iso.part.source").write_text(f"{base}/resumable\n\"v1\"\n")

    # act: the impossible range is asked once, refused with 416, and the same call asks again for the
    # whole object - which this server answers by dropping halfway, so the recovery takes two calls.
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/resumable", dest, resume=True)
    after_the_416 = part.stat().st_size
    with _capture(tty=False):
        fetch.download(f"{base}/resumable", dest, resume=True)

    # assert
    assert _ranges_asked_for()[0] == f"bytes={len(BODY) + 13}-", f"the 416 was never provoked: {SEEN}"
    assert after_the_416 == len(BODY) // 2, "the part that cannot exist survived the refusal"
    assert dest.read_bytes() == BODY
    assert not part.exists()


def test_without_resume_nothing_survives_a_failed_download(base, tmp_path, versioned):
    """The promise si#142 made and si#176 may not quietly withdraw. `resume` is opt-in precisely so the
    three call sites this kernel has - a docker bundle, an oras archive, `get-pip.py`, all small - keep
    the behaviour they were given: a failure leaves the destination directory as it found it.
    """
    # act
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/resumable", tmp_path / "small.tgz")

    # assert
    assert list(tmp_path.iterdir()) == [], "a partial file survived a download that did not ask to"


def test_a_resume_that_fails_again_keeps_what_it_got_and_says_so(base, tmp_path, versioned):
    """The message, because the discard's message is what the ticket quoted. A failure that kept the
    bytes must not print the sentence that says it threw them away."""
    # act
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError) as refusal:
            fetch.download(f"{base}/resumable", tmp_path / "big.iso", resume=True)

    # assert
    assert "discarded" not in str(refusal.value), str(refusal.value)
    assert "resume" in str(refusal.value).lower(), str(refusal.value)
    assert (tmp_path / "big.iso.part").read_bytes() == BODY[:len(BODY) // 2]


def test_a_resume_still_refuses_a_chain_through_cleartext(base, cleartext, tmp_path, monkeypatch,
                                                          versioned):
    """si#176 changed HOW the request is built - a `Request` carrying headers instead of a bare URL -
    and the scheme guard rides on the opener, not on the argument. So the hop rule is re-driven on the
    resumed path, because a guard that used to hold and is never asked again is how one quietly stops.
    """
    # arrange: a part to resume, then a chain https -> http -> https
    dest = tmp_path / "big.iso"
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/resumable", dest, resume=True)
    monkeypatch.setitem(ROUTES, "/hop", f"{cleartext}/onward")
    monkeypatch.setitem(ROUTES, "cleartext-onward", f"{base}/resumable")
    (tmp_path / "big.iso.part.source").write_text(f"{base}/hop\n\"v1\"\n")

    # act / assert
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError, match="https"):
            fetch.download(f"{base}/hop", dest, resume=True)

    assert not dest.exists()
    assert (tmp_path / "big.iso.part").read_bytes() == BODY[:len(BODY) // 2], (
        "the proven bytes were deleted over a redirect that said nothing about them")


def test_a_resume_survives_an_ordinary_https_redirect(base, tmp_path, monkeypatch, versioned):
    """And the other half, which the oras call site actually needs: GitHub redirects its release assets
    to objects.githubusercontent.com, so a resume that lost its `Range` on the hop would silently
    re-download the whole thing every time and nothing would ever say so."""
    # arrange
    dest = tmp_path / "big.iso"
    monkeypatch.setitem(ROUTES, "/hop", f"{base}/resumable")
    with _capture(tty=False):
        with pytest.raises(fetch.DownloadError):
            fetch.download(f"{base}/hop", dest, resume=True)

    # act
    with _capture(tty=False):
        fetch.download(f"{base}/hop", dest, resume=True)

    # assert
    assert _ranges_asked_for() == [f"bytes={len(BODY) // 2}-"], (
        f"the Range did not survive the redirect: {SEEN}")
    assert dest.read_bytes() == BODY


# --- what the numbers look like (si#178) ----------------------------------------------------------


@pytest.mark.parametrize("count, shown", [
    (0, "0 B"),
    (947, "947 B"),
    (999, "999 B"),
    (1_000, "1.0 KB"),
    (1_024_000, "1.0 MB"),
    (2_400_000, "2.4 MB"),
    (450_000_000, "450.0 MB"),
    (1_100_000_000, "1.1 GB"),
    (11_240_000_000, "11.2 GB"),
    (5_000_000_000_000, "5,000.0 GB"),
])
def test_the_rendered_strings(count, shown):
    """Every string this function can produce a shape of, written out rather than described. si#178 is
    a request about two characters, and two characters are only arguable against the actual output."""
    assert fetch.human_bytes(count) == shown


def test_the_unit_stays_decimal_which_is_the_half_of_the_argument_that_does_not_move():
    """si#178 asks for `KB` and a separator. It does NOT ask for 1024, and the ticket is the best
    argument against it: the product it came from caps a channel at 450'000'000 bytes because the
    channel rejects at 500 MB decimal, and its 1024-based helper called that `429.2 MB` - comfortably
    under a cap it was in fact sitting on. That confusion cost it a failed publish."""
    assert fetch.human_bytes(450_000_000) == "450.0 MB"
    assert fetch.human_bytes(450_000_000) != "429.2 MB"
    assert fetch.human_bytes(1_024) == "1.0 KB", "1024 bytes is a kilobyte and a bit, not a kibibyte"


def test_a_thousands_separator_is_reachable_in_the_top_unit_and_at_one_rounding_edge():
    """Worth writing down because si#178's two examples imply a separator is everywhere, and it is not.

    Every unit but the largest hands over at the next 1000, so `KB` and `MB` carry three digits and no
    separator - `450.0 MB`, `999.9 MB`. `GB` has nothing above it, which is where a separator is both
    reachable and wanted: a run that moves twelve 5 GB media says `60.0 GB` and a year of them says
    `5,000.0 GB`.

    The one exception is arithmetic rather than design and it predates this change: `.1f` rounds
    `999.999` up, so the fifty byte counts just under a megabyte render as `1,000.0 KB` instead of
    handing over to `1.0 MB`. Recorded rather than fixed - si#178 asked for two characters, the wart is
    a scale boundary, and a display that rounds is allowed to round.
    """
    assert fetch.human_bytes(999_499) == "999.5 KB"
    assert fetch.human_bytes(999_499_000) == "999.5 MB"
    assert fetch.human_bytes(999_999) == "1,000.0 KB"
    assert fetch.human_bytes(1_000_000_000_000) == "1,000.0 GB"


def test_the_rate_carries_the_same_shape():
    assert fetch.human_rate(2_400_000) == "2.4 MB/s"
    assert fetch.human_rate(5_000_000_000_000) == "5,000.0 GB/s"
