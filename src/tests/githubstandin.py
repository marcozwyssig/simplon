"""A local stand-in for the part of the GitHub REST API the release coordinates speak (si#486).

Real HTTP on 127.0.0.1, so PyGithub really runs: a mock of PyGithub would test our assumption about it,
not its behaviour. One repository, `o/n`, and only the routes the adapters call:

    GET   /repos/o/n                         the repository (404 when `state["repo"]` is None)
    GET   /repos/o/n/releases/tags/<tag>     PUBLISHED releases only, as GitHub answers it
    GET   /repos/o/n/releases?per_page&page  every release, drafts included, paged
    POST  /repos/o/n/releases                create
    PATCH /repos/o/n/releases/<id>           update
    GET   /repos/o/n/contents/<path>?ref=<r> a file (base64 `content`, blob `sha`), or a JSON list when
                                             `path` is a directory of stored paths; `r` is a branch
                                             (default `main`) or a commit sha a PUT answered; 404 for a
                                             missing file, branch or commit (si#535)
    PUT   /repos/o/n/contents/<path>         create or update on `branch`: 404 for an unknown branch (the
                                             stand-in's assumption, not measured against real GitHub; the
                                             adapter refuses on any error status either way),
                                             409 when `sha` is not the stored blob's, 422 when the file
                                             exists and no `sha` was sent; answers the new commit's sha

`state["files"]` holds `{(branch, path): bytes}` and `state["branches"]` the branches that exist;
`state["commits"]` maps each commit sha a PUT answered to that branch's files at that commit.
`state["race"]`, when set to bytes, is written to the file by "another writer" just before the next PUT
is handled, so the PUT's sha is stale; `state["corrupt_readback"]` makes a GET by commit sha answer
different bytes than were stored, and `state["fail_readback"]` (a status) makes it fail.
`state["large"]` names the kinds of ref, `"branch"` and/or `"commit"`, at which a file answers as one over
1 MB does: `encoding: "none"`, `content` empty.
`state["fail"]` forces a status for a `(method, path prefix)`; `state["keep_draft"]` makes a PATCH answer
200 while leaving `draft` as it was (a proxy, a race); `state["force_public"]` makes a PATCH answer with the release public whatever was asked;
`state["requests"]` records every call as (method, path, body) and `state["auth"]` the Authorization header of
each, at the same index.
"""
from __future__ import annotations

import base64
import hashlib
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
                             "auth": [], "keep_draft": False,
                             "files": {}, "branches": {"main"}, "commits": {}, "race": None,
                             "corrupt_readback": False, "fail_readback": None, "large": set()}
    fresh.update(overrides)
    return fresh


def release(rid: int, tag: str, *, draft: bool, body: str = "", name: str = "") -> dict:
    return {"id": rid, "tag_name": tag, "draft": draft, "body": body, "name": name or tag}


def blob_sha(content: bytes) -> str:
    """Git's blob sha, as GitHub names a file's content."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


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
            elif method == "GET" and rest.startswith("/contents/"):
                self._contents_get(unquote(rest[len("/contents/"):]), parse_qs(split.query))
            elif method == "PUT" and rest.startswith("/contents/"):
                assert isinstance(body, dict)
                self._contents_put(unquote(rest[len("/contents/"):]), body)
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

        def _files_at(self, ref: str) -> dict[str, bytes] | None:
            if ref in shared["branches"]:
                return {p: c for (b, p), c in shared["files"].items() if b == ref}
            if ref in shared["commits"]:
                at = dict(shared["commits"][ref])
                if shared["corrupt_readback"]:
                    at = {p: c + b"corrupted" for p, c in at.items()}
                return at
            return None

        def _file(self, path: str, content: bytes) -> dict:
            return {"type": "file", "encoding": "base64", "size": len(content), "name": path.rsplit("/", 1)[-1],
                    "path": path, "sha": blob_sha(content), "content": base64.b64encode(content).decode("ascii"),
                    "url": f"{self._base()}/repos/{REPO}/contents/{path}"}

        def _contents_get(self, path: str, query: dict) -> None:
            ref = query.get("ref", ["main"])[0]
            kind = "commit" if ref in shared["commits"] else "branch"
            files = self._files_at(ref)
            if kind == "commit" and shared["fail_readback"]:
                self._send(shared["fail_readback"], {"message": f"forced {shared['fail_readback']}"})
            elif files is None:
                self._send(404, {"message": "No commit found for the ref"})
            elif path in files and kind in shared["large"]:
                self._send(200, {**self._file(path, files[path]), "encoding": "none", "content": "",
                                 "size": 2 * 1024 * 1024})
            elif path in files:
                self._send(200, self._file(path, files[path]))
            elif below := sorted(p for p in files if not path or p.startswith(path.rstrip("/") + "/")):
                self._send(200, [{**self._file(p, files[p]), "content": None} for p in below])
            else:
                self._send(404, {"message": "Not Found"})

        def _contents_put(self, path: str, body: dict) -> None:
            branch = body.get("branch", "main")
            if branch not in shared["branches"]:
                self._send(404, {"message": f"Branch {branch} not found"})
                return
            if shared["race"] is not None:                # one other writer, once
                shared["files"][(branch, path)], shared["race"] = shared["race"], None
            stored = shared["files"].get((branch, path))
            if stored is not None and "sha" not in body:
                self._send(422, {"message": "Invalid request.\n\n\"sha\" wasn't supplied."})
                return
            if body.get("sha") is not None and (stored is None or body["sha"] != blob_sha(stored)):
                self._send(409, {"message": f"{path} does not match {body['sha']}"})
                return
            content = base64.b64decode(body["content"])
            shared["files"][(branch, path)] = content
            commit = hashlib.sha1(b"commit %d" % len(shared["commits"]) + content).hexdigest()
            shared["commits"][commit] = {p: c for (b, p), c in shared["files"].items() if b == branch}
            self._send(201 if stored is None else 200,
                       {"commit": {"sha": commit, "message": body.get("message", "")},
                        "content": self._file(path, content)})

        def do_GET(self) -> None:                         # noqa: N802 - BaseHTTPRequestHandler's name
            self._handle("GET")

        def do_POST(self) -> None:                        # noqa: N802
            self._handle("POST")

        def do_PATCH(self) -> None:                       # noqa: N802
            self._handle("PATCH")

        def do_PUT(self) -> None:                         # noqa: N802
            self._handle("PUT")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def stop() -> None:
        httpd.shutdown()
        httpd.server_close()

    return f"http://127.0.0.1:{httpd.server_address[1]}", stop
