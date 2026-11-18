"""si#760: the callers that never need a terminal declare `terminal=False` (si#739), and the ones that do,
do not. Decided by Marco 2026-11-18: git's remote operations are declared AND run with
`GIT_TERMINAL_PROMPT=0`, so a missing credential fails at once with git's own words, and the kernel says the
way out.

The git half runs on a REAL pty, because that is the only place the question exists: without a controlling
terminal every child already gets its own group (si#739) and git has nowhere to prompt. The kernel is a
child of this test sitting on the pty as somebody's shell would run it, and the git it starts is real, against
a listener on this machine. The gh, oras and docker calls were measured the same way, on a pty and without a
credential, and that measurement is in the PR of si#760: it needs their binaries and a registry, which a
unit suite cannot assume.
"""
from __future__ import annotations

import ast
import http.server
import json
import os
import pty
import select
import signal
import subprocess
import sys
import threading
import time

import pytest

from conftest import ROOT
from simplon.adapters import tracker
from simplon.kernel import run as run_module
from simplon.tasks import gitops, imagefile
from test_run_process_groups import _gone_within, _pids_running, silent_remote  # noqa: F401  (a fixture)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="a pty and process groups are POSIX")

_SRC = str(ROOT / "src")


class _Refusing(http.server.BaseHTTPRequestHandler):
    """A remote that wants a credential: 401 with a Basic challenge, which is what makes git ask for one."""

    def _answer(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="si760"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = _answer

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def refusing_remote():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Refusing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/product.git"
    finally:
        server.shutdown()


@pytest.fixture
def clone(tmp_path):
    """A repository with one commit, and the environment its kernel runs git in: nobody's own git config, no
    credential helper, no askpass - so the only way git could get a credential is to ask the terminal."""
    repo = tmp_path / "clone"
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_TERMINAL_PROMPT", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_CONFIG_COUNT", "GITHUB_TOKEN")}
    env.update({"HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "PYTHONPATH": os.pathsep.join([_SRC, *filter(None, [os.environ.get("PYTHONPATH")])])})
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "root"], check=True, env=env)
    return repo, env


def _on_a_terminal(code: str, env: dict[str, str], within: float = 30) -> str:
    """Run `code` in a kernel whose controlling terminal is a real pty, and return what it wrote there.

    Nobody types: a child that prompts waits until its limit. `within` bounds the whole run, so the red
    run of a test fails here instead of hanging the suite."""
    pid, fd = pty.fork()
    if pid == 0:                                                       # the kernel, on the pty
        os.execve(sys.executable, [sys.executable, "-c", code], env)
    said = b""
    deadline = time.monotonic() + within
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:                                            # the pty closed: the kernel ended
                break
            if not chunk:
                break
            said += chunk
        else:
            os.killpg(pid, signal.SIGKILL)
    finally:
        os.waitpid(pid, 0)
        os.close(fd)
    return said.decode(errors="replace").replace("\r\n", "\n")


def _verdict(said: str) -> dict:
    lines = [line for line in said.splitlines() if "VERDICT " in line]     # a prompt shares its line
    assert lines, f"the kernel gave no verdict; it said:\n{said}"
    return json.loads(lines[-1].split("VERDICT ", 1)[1])


_LS_REMOTE = """
import json, sys, time
from simplon.kernel import limits, run
from simplon.tasks import gitops
assert run._has_terminal(), "the kernel is not on a terminal"
limits.GIT_REMOTE = {limit}
gitops.configure(sys.argv[1] if len(sys.argv) > 1 else {root!r})
started = time.monotonic()
res = gitops._git(["ls-remote", "origin"])
print("VERDICT " + json.dumps(dict(timed_out=res.timed_out, rc=res.rc, err=res.err,
                                   secs=time.monotonic() - started)), flush=True)
"""


# --- git's remote operations: declared, and asking nobody ------------------------------------------------

def test_a_remote_git_operation_on_a_terminal_fails_at_once_and_names_the_way_out(clone, refusing_remote):
    # arrange: origin wants a credential, git has none, and the kernel sits on a terminal git could ask on
    repo, env = clone
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", refusing_remote], check=True, env=env)

    # act
    said = _on_a_terminal(_LS_REMOTE.format(limit=10.0, root=str(repo)), env)

    # assert: git's own words at once, not a prompt that waits for the limit; then the way out
    verdict = _verdict(said)
    assert not verdict["timed_out"], f"git waited on the terminal instead of failing; it said:\n{said}"
    assert "terminal prompts disabled" in verdict["err"]
    assert not any(line.startswith("Username for") for line in said.splitlines()), "git prompted"
    assert gitops.NO_CREDENTIAL in said


def test_a_declared_remote_git_operation_leaves_no_descendant_at_its_limit_on_a_terminal(clone, silent_remote):
    # arrange: origin accepts and never answers; on a terminal, so nothing but the declaration gives git a
    # group of its own
    repo, env = clone
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", silent_remote], check=True, env=env)

    # act
    said = _on_a_terminal(_LS_REMOTE.format(limit=1.0, root=str(repo)), env)

    # assert: the limit's verdict, and no `git remote-http` / `git-remote-http` left holding the socket
    verdict = _verdict(said)
    assert verdict["timed_out"]
    assert "was left running" not in verdict["err"]
    assert _gone_within(_pids_running(silent_remote), 2), "a remote helper outlived the limit"


_PUSH = """
import sys
from simplon.kernel import limits, run
from simplon.tasks import gitops
assert run._has_terminal(), "the kernel is not on a terminal"
limits.GIT_REMOTE = 10.0
gitops.configure({root!r})
gitops.push()
"""


def test_a_push_without_a_credential_says_so_and_not_that_it_conflicted(clone, refusing_remote):
    """`pull --rebase` exits 1 for a refused credential AND for a conflict (measured on git 2.47), so the
    rc cannot tell them apart; git's words can, and the push has to read them to say the right thing."""
    # arrange
    repo, env = clone
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", refusing_remote], check=True, env=env)

    # act
    said = _on_a_terminal(_PUSH.format(root=str(repo)), env)

    # assert
    assert "terminal prompts disabled" in said
    assert gitops.NO_CREDENTIAL in said
    assert "could not authenticate" in said
    assert "conflicts?" not in said


def test_every_remote_git_operation_is_declared_and_asks_nobody_and_no_local_one_is(monkeypatch):
    # arrange
    seen: list = []
    monkeypatch.setattr(gitops, "run", lambda argv, **kw: seen.append((argv[3], kw)) or run_module.Result(0, "", ""))

    # act
    for op in sorted(gitops.limits.GIT_REMOTE_OPS):
        gitops._git([op])
    gitops._git(["status"])

    # assert
    for op, kw in seen[:-1]:
        assert kw.get("terminal") is False, op
        assert (kw.get("env") or {}).get("GIT_TERMINAL_PROMPT") == "0", op
    op, kw = seen[-1]
    assert kw.get("terminal", True) is True and not (kw.get("env") or {}), "a local git call is undeclared"


# --- the calls whose argv the network-limit scan cannot read ---------------------------------------------

def test_the_trackers_gh_call_is_declared(monkeypatch):
    # arrange
    seen: list = []
    monkeypatch.setattr(tracker.run, "run", lambda argv, **kw: seen.append(kw) or run_module.Result(0, "", ""))

    # act
    tracker._gh(["gh", "issue", "list"])

    # assert
    assert [kw.get("terminal") for kw in seen] == [False]


def test_the_file_test_images_warm_up_pull_is_declared(monkeypatch):
    # arrange
    seen: list = []
    monkeypatch.setattr(imagefile, "run", lambda argv, **kw: seen.append((argv[:2], kw)) or run_module.Result(0, "", ""))

    # act
    imagefile._warm_up("")

    # assert
    assert [(argv, kw.get("terminal")) for argv, kw in seen] == [(["docker", "pull"], False)]


# --- what may need the terminal stays undeclared ---------------------------------------------------------

#: Callers that may prompt on the terminal, each with why. Declaring one would stop its prompt (SIGTTIN)
#: until its limit and take a typed Ctrl-C away from it (si#739).
INTERACTIVE = {
    ("tasks/gitops.py", "refresh_scopes"): "gh auth refresh: a browser and a one-time code the person types",
    ("adapters/docker.py", "run_engine_installer"): "sudo -E sh: a sudo password prompt",
    ("adapters/labhost.py", "_install_linux"): "sudo -E bash: a sudo password prompt",
    ("adapters/labhost.py", "_install_macos"): "brew install: Homebrew's own sudo prompt",
    ("adapters/oras.py", "_run_installer"): "a package manager, which may ask for a sudo password",
    ("kernel/steps.py", "argv_step"): "any manifest command as a TUI step, including the ones above",
}


def _runs_in(module: str, function: str) -> list[ast.Call]:
    tree = ast.parse((ROOT / "src" / "simplon" / module).read_text(encoding="utf-8"))
    [body] = [node for node in ast.walk(tree)
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function]
    return [node for node in ast.walk(body) if isinstance(node, ast.Call)
            and (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) in ("run", "run_stream")]


@pytest.mark.parametrize("module,function", sorted(INTERACTIVE))
def test_a_caller_that_may_prompt_stays_on_the_terminals_group(module, function):
    # arrange: the function is there and starts a child, or this test would pass on nothing
    calls = _runs_in(module, function)
    assert calls, f"{module}:{function} starts no child through run()/run_stream() any more"

    # assert
    declared = [call.lineno for call in calls
                if any(kw.arg == "terminal" and not (isinstance(kw.value, ast.Constant) and kw.value.value is True)
                       for kw in call.keywords)]
    assert declared == [], f"{module}:{function} may prompt ({INTERACTIVE[module, function]})"
