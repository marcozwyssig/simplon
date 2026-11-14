"""si#657: every way a Proxmox answer can go wrong reaches the caller as `ProxmoxError`.

The callers in `tasks/carrier.py` catch `ProxmoxError` and nothing else, so anything else that leaves
`_get` is a traceback where a sentence was owed. Each case runs against a real local listener rather
than a stub: the defect lives in what urllib does NOT wrap, and a stub only knows what it was told.
"""
from __future__ import annotations

import http.server
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from simplon.tasks import proxmoxapi


@contextmanager
def _serve(handler: type[http.server.BaseHTTPRequestHandler]) -> Iterator[str]:
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _answering(body: bytes, content_length: int | None = None) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body) if content_length is None else content_length))
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def log_message(self, *args: object) -> None:
            pass

    return Handler


@pytest.fixture
def silent(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A listener that accepts the connection and never answers - a hung API or a proxy holding on.

    The test cannot hang: `_TIMEOUT_S` is the socket timeout urllib applies to the read as well.
    """
    monkeypatch.setattr(proxmoxapi, "_TIMEOUT_S", 1.0)
    held: list[socket.socket] = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def accept() -> None:
            try:
                held.append(listener.accept()[0])
            except OSError:
                pass

        threading.Thread(target=accept, daemon=True).start()
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    for connection in held:
        connection.close()


def _refusal(endpoint: str) -> str:
    with pytest.raises(proxmoxapi.ProxmoxError) as caught:
        proxmoxapi.storages(endpoint, "tok", "pve-2", insecure=False)
    return str(caught.value)


def test_an_endpoint_that_never_answers_is_a_proxmox_error(silent):
    message = _refusal(silent)

    assert silent in message and "/nodes/pve-2/storage" in message
    assert "did not answer within 1.0s" in message


@pytest.mark.parametrize(("body", "what"), [
    (b"<html>please log in</html>", "not JSON"),
    (b"\xff\xfe\x00", "not JSON"),
    (b"[1, 2]", "not a JSON object"),
])
def test_an_answer_that_is_not_the_api_is_a_proxmox_error(body, what):
    with _serve(_answering(body)) as endpoint:
        message = _refusal(endpoint)

        assert endpoint in message and "/nodes/pve-2/storage" in message
        assert what in message and "/api2/json" in message


def test_an_answer_cut_short_is_a_proxmox_error():
    with _serve(_answering(b'{"da', content_length=100)) as endpoint:
        message = _refusal(endpoint)

        assert endpoint in message and "/nodes/pve-2/storage" in message
        assert "IncompleteRead" in message


def test_a_good_answer_still_reads():
    body = b'{"data": [{"storage": "local", "content": "rootdir,images", "enabled": 1, "active": 1}]}'
    with _serve(_answering(body)) as endpoint:
        assert proxmoxapi.storages(endpoint, "tok", "pve-2", insecure=False) == [
            proxmoxapi.Storage("local", ("rootdir", "images"), True, True)]
