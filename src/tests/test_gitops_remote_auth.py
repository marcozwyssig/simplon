"""si#507: a git call that talks to origin authenticates itself from GITHUB_TOKEN, and no other call does.

A derived release job checks out with `persist-credentials: false`, so `.git/config` carries no token for a
build or test step to read. `release:tag` pushes, and `release:check` and `release:tag` fetch and ask origin,
so those calls bring their own credential. These tests ask a REAL git, against a real HTTP listener on this
machine, which headers it sent - a stub of `run` would only confirm the env this module wrote, not that git
reads it.

The listener answers 404 to everything, so git fails after its first request; what is recorded is the
`Authorization` header that request carried. That is all the seam promises: GitHub's acceptance of the
header is GitHub's, and is not measured here.
"""
from __future__ import annotations

import base64
import http.server
import subprocess
import threading

import pytest

from simplon.tasks import gitops

TOKEN = "ghs_not-a-real-token"
WANTED = "basic " + base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()


class _Recorder(http.server.BaseHTTPRequestHandler):
    seen: list[list[str]] = []

    def _answer(self) -> None:
        self.seen.append(self.headers.get_all("Authorization") or [])
        self.send_response(404)
        self.end_headers()

    do_GET = do_POST = _answer

    def log_message(self, *args) -> None:  # the test's output is the assertion, not the access log
        pass


@pytest.fixture
def origin(tmp_path, monkeypatch):
    """A clone whose origin is an HTTP listener on 127.0.0.1 that records the Authorization headers.

    Returns (clone, seen, server URL). Global and system git config are shut out, so a developer's own
    credential helper cannot answer for the test, and git never prompts."""
    _Recorder.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True)
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GITHUB_SERVER_URL": url}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    subprocess.run(["git", "-C", str(clone), "commit", "-q", "--allow-empty", "-m", "root"], check=True)
    subprocess.run(["git", "-C", str(clone), "tag", "v1.0.0"], check=True)
    subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", f"{url}/owner/repo.git"], check=True)
    monkeypatch.setattr(gitops, "ROOT", clone)
    yield clone, _Recorder.seen, url
    server.shutdown()


#: Every gitops call a release task makes to origin. A new one that forgets `remote=True` reaches origin
#: with nothing, which a private repository answers with a refusal and a public one with a quiet read.
REMOTE_CALLS = {
    "push_tag": lambda: gitops.push_tag("v1.0.0"),
    "push_branch": lambda: gitops.push_branch("main", force=True),
    "fetch_branches": gitops.fetch_branches,
    "remote_tag_commit": lambda: gitops.remote_tag_commit("v1.0.0"),
    "remote_default_branch": gitops.remote_default_branch,
}


@pytest.mark.parametrize("call", sorted(REMOTE_CALLS))
def test_a_call_to_origin_carries_the_token_as_one_authorization_header(origin, monkeypatch, call):
    _, seen, _ = origin
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)

    REMOTE_CALLS[call]()

    assert seen, f"{call} never reached the listener"
    assert seen[0] == [WANTED]


@pytest.mark.parametrize("call", sorted(REMOTE_CALLS))
def test_without_a_token_nothing_is_invented(origin, monkeypatch, call):
    _, seen, _ = origin
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    REMOTE_CALLS[call]()

    assert seen and seen[0] == []


def test_a_persisted_checkout_credential_is_replaced_not_doubled(origin, monkeypatch):
    """A job that DID persist its credential (any product job; `checkout: false` with a checkout of its
    own) holds an extraheader in `.git/config` already. Without git's reset, git sends both."""
    clone, seen, url = origin
    subprocess.run(["git", "-C", str(clone), "config", f"http.{url}/.extraheader",
                    "AUTHORIZATION: basic cGVyc2lzdGVk"], check=True)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)

    gitops.push_tag("v1.0.0")

    assert seen[0] == [WANTED]


def test_the_token_reaches_git_through_its_environment_not_its_argv(origin, monkeypatch):
    """argv is readable by every process on the machine (`ps`); the child's environment is not."""
    argvs: list[list[str]] = []
    real = gitops.run
    monkeypatch.setattr(gitops, "run", lambda argv, **kw: argvs.append(argv) or real(argv, **kw))
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)

    gitops.push_tag("v1.0.0")

    assert argvs and not any(TOKEN in arg or WANTED in arg for argv in argvs for arg in argv)


def test_a_local_call_carries_no_credential(origin, monkeypatch):
    """Only a call to origin is handed the token: a local `git tag` has no use for it."""
    envs: list[object] = []
    real = gitops.run
    monkeypatch.setattr(gitops, "run", lambda argv, **kw: envs.append(kw.get("env")) or real(argv, **kw))
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)

    gitops.create_tag("v2.0.0")

    assert envs == [None]
