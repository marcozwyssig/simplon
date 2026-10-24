"""A local stand-in for the part of the GitHub REST API the release coordinates speak (si#486).

Real HTTP on 127.0.0.1, so PyGithub really runs: a mock of PyGithub would test our assumption about it,
not its behaviour. One repository, `o/n`, and only the five routes the adapter calls:

    GET   /repos/o/n                         the repository (404 when `state["repo"]` is None)
    GET   /repos/o/n/releases/tags/<tag>     PUBLISHED releases only, as GitHub answers it
    GET   /repos/o/n/releases?per_page&page  every release, drafts included, paged
    POST  /repos/o/n/releases                create
    PATCH /repos/o/n/releases/<id>           update

`state["fail"]` forces a status for a `(method, path prefix)`; `state["keep_draft"]` makes a PATCH answer
200 while leaving `draft` as it was (a proxy, a race); `state["force_public"]` makes a PATCH answer with the release public whatever was asked;
`state["requests"]` records every call as (method, path, body) and `state["auth"]` the Authorization header of
each, at the same index.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

REPO = "o/n"


def state(**overrides: Any) -> dict:
    """A fresh state: a visible repository with no releases."""
    fresh: dict[str, Any] = {"repo": {"full_name": REPO}, "releases": [], "fail": {}, "requests": [],
                             "auth": [], "keep_draft": False}
    fresh.update(overrides)
    return fresh


def release(rid: int, tag: str, *, draft: bool, body: str = "", name: str = "") -> dict:
    return {"id": rid, "tag_name": tag, "draft": draft, "body": body, "name": name or tag}


def serve(shared: dict) -> tuple[str, Callable[[], None]]:
    """Start the stand-in over `shared`; returns (base url, stop)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:   # quiet: pytest captures, the noise helps nobody
            pass

        def _send(self, status: int, payload: object) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _base(self) -> str:
            return f"http://127.0.0.1:{self.server.server_address[1]}"

        def _dressed(self, rel: dict) -> dict:
            base = self._base()
            # `prerelease` always, as GitHub sends it: without it PyGithub completes the object with a GET of
            # the release's own url, which is a request the real API never needs
            return {"prerelease": False, **rel, "url": f"{base}/repos/{REPO}/releases/{rel['id']}",
                    # A draft's page is not under its tag, as on GitHub: `releases/tag/untagged-<hash>`.
                    "html_url": f"https://github.example/{REPO}/releases/tag/"
                                + (f"untagged-{rel['id']}" if rel["draft"] else rel["tag_name"])}

        def _handle(self, method: str) -> None:
            split = urlsplit(self.path)
            path = split.path
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"null") if length else None
            shared["requests"].append((method, path, body))
            shared["auth"].append(self.headers.get("Authorization"))   # parallel to "requests", same index
            for (m, prefix), status in shared["fail"].items():
                if m == method and path.startswith(prefix):
                    self._send(status, {"message": f"forced {status}"})
                    return
            repo_path = f"/repos/{REPO}"
            if not path.startswith(repo_path) or shared["repo"] is None:
                self._send(404, {"message": "Not Found"})
                return
            rest = path[len(repo_path):]
            releases = shared["releases"]
            if method == "GET" and rest == "":
                self._send(200, {**shared["repo"], "url": f"{self._base()}{repo_path}", "id": 1})
            elif method == "GET" and rest.startswith("/releases/tags/"):
                tag = unquote(rest[len("/releases/tags/"):])
                found = [r for r in releases if r["tag_name"] == tag and not r["draft"]]
                if found:
                    self._send(200, self._dressed(found[0]))
                else:
                    self._send(404, {"message": "Not Found"})
            elif method == "GET" and rest == "/releases":
                query = parse_qs(split.query)
                per_page = int(query.get("per_page", ["30"])[0])
                page = int(query.get("page", ["1"])[0])
                chunk = releases[(page - 1) * per_page:page * per_page]
                self._send(200, [self._dressed(r) for r in chunk])
            elif method == "POST" and rest == "/releases":
                assert isinstance(body, dict)
                made = release(max([r["id"] for r in releases], default=0) + 1, body["tag_name"],
                               draft=bool(body.get("draft")), body=body.get("body", ""),
                               name=body.get("name", ""))
                made["target_commitish"] = body.get("target_commitish", "")
                releases.append(made)
                self._send(201, self._dressed(made))
            elif method == "PATCH" and rest.startswith("/releases/"):
                rid = int(rest[len("/releases/"):])
                target = next((r for r in releases if r["id"] == rid), None)
                if target is None:
                    self._send(404, {"message": "Not Found"})
                    return
                assert isinstance(body, dict)
                for key in ("body", "name", "tag_name", "prerelease"):
                    if key in body:
                        target[key] = body[key]
                if "draft" in body and not shared["keep_draft"]:
                    target["draft"] = bool(body["draft"])
                if shared.get("force_public"):
                    target["draft"] = False
                self._send(200, self._dressed(target))
            else:
                self._send(404, {"message": "Not Found"})

        def do_GET(self) -> None:                         # noqa: N802 - BaseHTTPRequestHandler's name
            self._handle("GET")

        def do_POST(self) -> None:                        # noqa: N802
            self._handle("POST")

        def do_PATCH(self) -> None:                       # noqa: N802
            self._handle("PATCH")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def stop() -> None:
        httpd.shutdown()
        httpd.server_close()

    return f"http://127.0.0.1:{httpd.server_address[1]}", stop
