"""Network-bound subprocess calls run with a time limit, one default per tool class (si#654).

A hung remote is a hung run: "a missing time limit is a missing verdict". The defaults live in
`simplon.kernel.limits`; these tests hold the three halves of the ticket - a timed-out call says which
tool, which operation and which limit; a remote git operation against a remote that never answers ends
with that verdict instead of hanging; and no `run()` of a network-bound tool class joins the kernel
without a limit.
"""
from __future__ import annotations

import ast
import socket
import subprocess
import threading

import pytest

from conftest import ROOT
from simplon.kernel import limits
from simplon.kernel import run as run_module
from simplon.tasks import gitops


def test_a_timed_out_run_names_the_tool_the_operation_and_the_limit():
    # act
    res = run_module.run(["sleep", "30"], timeout=0.3)

    # assert: not a bare non-zero
    assert res.timed_out
    assert "`sleep 30` gave no answer within 0.3 s" in res.err


def test_the_operation_skips_git_s_own_options():
    # act
    shown = run_module.shown(["git", "-C", "/some/root", "ls-remote", "--symref", "origin", "HEAD"])

    # assert
    assert shown == "git ls-remote origin"


# --- a remote that accepts and never answers ---------------------------------------------------------

@pytest.fixture
def silent_remote():
    """A listener that accepts every connection and never says a word, as a stalled remote does."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            held.append(conn)

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}/product.git"
    finally:
        stop.set()
        thread.join(5)
        for conn in held:
            conn.close()                # a hung git (the red run) gets its EOF and ends
        listener.close()


def test_a_remote_git_operation_against_a_silent_remote_times_out(tmp_path, monkeypatch, silent_remote):
    # arrange: a repository whose origin never answers, and a short class default
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", silent_remote], check=True)
    monkeypatch.setattr(limits, "GIT_REMOTE", 1.0)
    monkeypatch.setattr(gitops, "ROOT", tmp_path)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    got: list = []

    # act: in a thread, so the red run (no limit: it hangs) fails here rather than hanging the suite
    worker = threading.Thread(target=lambda: got.append(gitops.git(gitops.ROOT, "ls-remote", "origin")), daemon=True)
    worker.start()
    worker.join(20)

    # assert: the verdict came, and it says what timed out and after how long
    assert got, "git ls-remote against a silent remote did not return within 20 s"
    [res] = got
    assert res.timed_out and not res.ok
    assert "`git ls-remote origin` gave no answer within 1 s" in res.err


# --- the scan: no network-bound run() without a limit ------------------------------------------------

#: The tool class of a literal argv, or "" when it is not network-bound. Only literal lists are seen: an
#: argv built in a variable is outside this scan (a known limit of an AST scan, not a claim about it).
def _tool_class(argv: list[ast.expr]) -> str:
    words = [each.value if isinstance(each, ast.Constant) and isinstance(each.value, str) else None
             for each in argv]
    if not words or words[0] is None:
        return ""
    tool, rest = words[0], words[1:]
    if tool == "gh":
        return "GH"
    if tool == "oras":
        return "ORAS"
    if tool == "docker":
        return "DOCKER_PULL" if rest[:1] == ["pull"] else ""
    if tool == "git":
        while rest[:1] in (["-C"], ["-c"]):
            rest = rest[2:]
        return "GIT_REMOTE" if rest[:1] and rest[0] in limits.GIT_REMOTE_OPS else ""
    return ""


#: Network-bound calls that carry no class default, each with its reason. A new entry is a decision.
EXEMPT = {
    ("tasks/gitops.py", "gh auth refresh"):
        "interactive: gh opens a browser and waits for a person's one-time code",
}


def _calls() -> list[tuple[str, int, str, str, ast.Call]]:
    """(module, line, tool class, the argv's leading words, call) for every literal-argv `run` in the kernel."""
    found = []
    src = ROOT / "src" / "simplon"
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args or not isinstance(node.args[0], ast.List):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name != "run":
                continue
            kind = _tool_class(node.args[0].elts)
            if kind:
                lead = " ".join(each.value for each in node.args[0].elts[:3]
                                if isinstance(each, ast.Constant) and isinstance(each.value, str))
                found.append((path.relative_to(src).as_posix(), node.lineno, kind, lead, node))
    return found


def test_the_scan_sees_the_calls_it_is_about():
    # assert: a scan that matched nothing would pass every rule below; it must see each class
    assert {kind for _, _, kind, _, _ in _calls()} == {"GH", "ORAS", "DOCKER_PULL"}


def test_every_network_bound_run_carries_its_class_default():
    # act
    missing = []
    for module, line, kind, lead, call in _calls():
        if any(module == m and lead.startswith(prefix) for m, prefix in EXEMPT):
            continue
        given = next((kw.value for kw in call.keywords if kw.arg == "timeout"), None)
        if not (isinstance(given, ast.Attribute) and isinstance(given.value, ast.Name)
                and given.value.id == "limits" and given.attr == kind):
            missing.append(f"{module}:{line} `{lead}` needs timeout=limits.{kind} (or an override with its reason)")

    # assert
    assert missing == []


def test_every_network_bound_run_needs_no_terminal():
    """si#760: each of these reads no terminal, measured on a pty without a credential (the PR of si#760), so
    each runs in a group of its own and its limit kills everything it started. git's remote operations are
    declared in `gitops._git`, whose argv this scan cannot read; `EXEMPT` is the one that prompts."""
    # act
    undeclared = [f"{module}:{line} `{lead}` reads no terminal: declare terminal=False"
                  for module, line, _, lead, call in _calls()
                  if not any(module == m and lead.startswith(prefix) for m, prefix in EXEMPT)
                  and not any(kw.arg == "terminal" and isinstance(kw.value, ast.Constant) and kw.value.value is False
                              for kw in call.keywords)]

    # assert
    assert undeclared == []


def test_gitops_gives_every_remote_operation_the_git_default(monkeypatch):
    # arrange
    seen: list = []
    monkeypatch.setattr(gitops, "run", lambda argv, **kw: seen.append((argv[3], kw.get("timeout")))
                        or run_module.Result(0, "", ""))

    # act
    for op in sorted(limits.GIT_REMOTE_OPS):
        gitops.git(gitops.ROOT, op)
    gitops.git(gitops.ROOT, "status")

    # assert
    assert seen == [(op, limits.GIT_REMOTE) for op in sorted(limits.GIT_REMOTE_OPS)] + [("status", None)]



def test_init_submodule_against_a_silent_remote_times_out(tmp_path, monkeypatch, silent_remote):
    # arrange: a checkout that names a submodule whose remote never answers (si#741)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "-f", ".gitmodules",
                    "submodule.lib/platform.path", "lib/platform"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "-f", ".gitmodules",
                    "submodule.lib/platform.url", silent_remote], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "update-index", "--add", "--cacheinfo",
                    f"160000,{'1' * 40},lib/platform"], check=True)
    monkeypatch.setattr(limits, "GIT_REMOTE", 1.0)
    monkeypatch.setattr(gitops, "ROOT", tmp_path)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    seen: list = []
    real_run = gitops.run
    monkeypatch.setattr(gitops, "run", lambda argv, **kw: seen.append(real_run(argv, **kw)) or seen[-1])
    got: list = []

    # act: in a thread, so the red run (no limit: it hangs) fails here rather than hanging the suite
    worker = threading.Thread(target=lambda: got.append(gitops.init_submodule()), daemon=True)
    worker.start()
    worker.join(20)

    # assert: the verdict came, and it is a timeout, not a plain git failure
    assert got, "git submodule update --init against a silent remote did not return within 20 s"
    assert got == [1]
    assert seen[-1].timed_out
    assert "`git submodule update` gave no answer within 1 s" in seen[-1].err
