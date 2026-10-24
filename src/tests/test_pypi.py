"""adapters.pypi against a real local server: the adapter takes `index=`, nothing is mocked (si#536)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from simplon.adapters import pypi

RELEASE = {
    "urls": [
        {"filename": "simplon-1.0-py3-none-any.whl", "url": "https://files.example/simplon-1.0-py3-none-any.whl",
         "digests": {"sha256": "aa" * 32}, "packagetype": "bdist_wheel"},
        {"filename": "simplon-1.0.tar.gz", "url": "https://files.example/simplon-1.0.tar.gz",
         "digests": {"sha256": "bb" * 32}, "packagetype": "sdist"},
    ]
}

ROUTES = {
    "/pypi/simplon/1.0/json": (200, json.dumps(RELEASE)),
    "/pypi/broken/1.0/json": (500, "boom"),
    "/pypi/nourls/1.0/json": (200, json.dumps({"info": {}})),
    "/pypi/garbage/1.0/json": (200, "not json"),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/pypi/slow/1.0/json":
            time.sleep(1.5)
        status, body = ROUTES.get(self.path, (404, "not found"))
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def index():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_files_lists_wheel_and_sdist(index):
    got = pypi.files("simplon", "1.0", index=index)
    assert got == (
        pypi.File("simplon-1.0-py3-none-any.whl", "https://files.example/simplon-1.0-py3-none-any.whl",
                  "aa" * 32, "bdist_wheel"),
        pypi.File("simplon-1.0.tar.gz", "https://files.example/simplon-1.0.tar.gz", "bb" * 32, "sdist"),
    )


def test_an_unlisted_version_says_not_listed(index):
    with pytest.raises(pypi.PyPIError, match=r"simplon 9\.9 is not listed on .*rerun"):
        pypi.files("simplon", "9.9", index=index)


def test_a_500_is_an_error_not_an_empty_list(index):
    with pytest.raises(pypi.PyPIError, match="500"):
        pypi.files("broken", "1.0", index=index)


def test_a_body_without_urls_is_an_error(index):
    with pytest.raises(pypi.PyPIError, match="urls"):
        pypi.files("nourls", "1.0", index=index)


def test_a_body_that_is_not_json_is_an_error(index):
    with pytest.raises(pypi.PyPIError, match="JSON"):
        pypi.files("garbage", "1.0", index=index)


def test_a_timeout_names_the_limit(index):
    with pytest.raises(pypi.PyPIError, match=r"0\.2"):
        pypi.files("slow", "1.0", index=index, timeout=0.2)
