"""The real `fetch.download`, answered from memory rather than from the network (si#668).

Not a stand-in for `download`: the code under test runs the whole of it - the scheme check, the temporary
name, the length comparison and the sha256 pin - and only the socket is replaced, at `fetch._opener`. A
stub of `download` itself would confirm exactly the assumption written into it, which for a pinned hash
is the one assumption worth testing: that a tampered body is refused before anything reads it.

What it cannot show is a real server: no redirect, no range, no TLS. `test_fetch.py` drives those
against a real HTTPS server; this exists so an adapter's test can watch its own pin refuse.
"""
from __future__ import annotations

import http.client
import io

from simplon.adapters import fetch


class _Response(io.BytesIO):
    def __init__(self, url: str, body: bytes):
        super().__init__(body)
        self.url = url
        self.status = 200
        self.headers = http.client.HTTPMessage()
        self.headers["Content-Length"] = str(len(body))


class _Opener:
    def __init__(self, body: bytes, asked: list[str]):
        self._body = body
        self._asked = asked

    def open(self, request, timeout=None):
        self._asked.append(request.full_url)
        return _Response(request.full_url, self._body)


def serve(monkeypatch, body: bytes) -> list[str]:
    """Every download in this test receives `body`; returns the list the requested URLs land in."""
    asked: list[str] = []
    monkeypatch.setattr(fetch, "_opener", lambda: _Opener(body, asked))
    return asked
