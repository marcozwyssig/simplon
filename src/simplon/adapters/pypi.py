"""One release's files, as PyPI's JSON API lists them (si#536).

`files("simplon", "1.2.3")` reads `GET <index>/pypi/<name>/<version>/json` and returns each file's name,
URL, sha256 and package type ("bdist_wheel" or "sdist"). A generated formula takes its URLs and hashes
from here rather than from a build, so the formula names what PyPI serves.

NO RETRY, AND "NOT LISTED" IS ITS OWN ANSWER. PyPI can answer 404 for a minute after an upload. That is
raised as "not listed", with the way out (rerun), and is never an empty tuple: "nothing there" and
"failed" must not look alike. Every other status, a timeout and a malformed body raise `PyPIError` too.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import NamedTuple


class PyPIError(RuntimeError):
    pass


class File(NamedTuple):
    filename: str
    url: str
    sha256: str
    packagetype: str


def files(name: str, version: str, *, index: str = "https://pypi.org", timeout: float = 30.0) -> tuple[File, ...]:
    url = f"{index.rstrip('/')}/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - index is the caller's
            body = response.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise PyPIError(f"{name} {version} is not listed on {index} (GET {url} answered 404). PyPI can lag "
                            "a minute behind an upload; if the release was just published, rerun is safe.") from e
        raise PyPIError(f"GET {url} answered {e.code} {e.reason}; nothing was read. Rerun once PyPI is back.") from e
    except (TimeoutError, socket.timeout) as e:
        raise PyPIError(f"GET {url} did not answer within {timeout}s; raise the timeout or rerun.") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise PyPIError(f"GET {url} did not answer within {timeout}s; raise the timeout or rerun.") from e
        raise PyPIError(f"GET {url} failed: {e.reason}. Check the index address and the network.") from e
    try:
        data = json.loads(body)
    except ValueError as e:
        raise PyPIError(f"GET {url} did not return JSON ({e}); is {index} a PyPI index?") from e
    urls = data.get("urls") if isinstance(data, dict) else None
    if not isinstance(urls, list):
        raise PyPIError(f"GET {url} returned JSON without a `urls` list; is {index} a PyPI index?")
    try:
        return tuple(File(u["filename"], u["url"], u["digests"]["sha256"], u["packagetype"]) for u in urls)
    except (KeyError, TypeError) as e:
        raise PyPIError(f"GET {url} listed a file without {e}; the response is not PyPI's release JSON.") from e
