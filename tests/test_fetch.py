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
SLICES = 8
PAUSE_S = 0.05


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
        elif self.path == "/blackhole":
            # Accepts, answers nothing. Bounded so a broken test cannot wedge the suite for a minute.
            time.sleep(20)
        else:
            self.send_error(404)

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

    # act / assert
    with pytest.raises(fetch.DownloadError):
        fetch.download(f"{base}/half", dest)

    assert not dest.exists(), "a partial file is sitting under the name a cache check looks for"
    assert list(tmp_path.iterdir()) == [], "a temporary file was left behind"


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
