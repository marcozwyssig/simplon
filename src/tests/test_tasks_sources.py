"""`support sources` (si#873): the manifest's `sources:` submodules checked out at their pinned commits.

Real git against a local bare repository, no stub, in `tmp_path` with HOME pointed there. The submodule's URL
is the real shape (`https://github.com/x/platform.git`); the one thing redirected is where the production
rewrite points (`sources.REWRITE`), so the test exercises the same mechanism with a target it can reach. A
stub of `run` appears only where the question is what the call CARRIES, never whether git works.
"""
import os
import subprocess
from pathlib import Path

import pytest

from simplon.kernel import run as runmod
from simplon.kernel import secrets
from simplon.manifest import context
from simplon.manifest.context import ProductContext
from simplon.tasks import gitops, sources

TOKEN = "tok-3f9a7c1d-secret"
URL = "https://github.com/x/platform.git"


def _git(cwd, *args, env=None):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A bare `platform` repo with two commits, and a superproject that pins the FIRST of them."""
    home = tmp_path / "home"
    home.mkdir()
    for key, value in {"HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_ALLOW_PROTOCOL": "file:https",
                       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@t", "PLATFORM_TOKEN": TOKEN}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)

    remote = tmp_path / "remote"
    bare = remote / "x" / "platform.git"
    bare.mkdir(parents=True)
    _git(bare, "init", "--bare", "-b", "main")
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(bare), str(work))
    (work / "a").write_text("one")
    _git(work, "add", "a")
    _git(work, "commit", "-m", "one")
    pinned = _git(work, "rev-parse", "HEAD")
    (work / "a").write_text("two")
    _git(work, "commit", "-am", "two")
    _git(work, "push", "origin", "HEAD:main")

    root = tmp_path / "super"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "-c", "protocol.file.allow=always", "submodule", "add", str(bare), "lib/platform")
    _git(root / "lib" / "platform", "checkout", pinned)
    _git(root, "config", "-f", ".gitmodules", "submodule.lib/platform.url", URL)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "pin")
    _git(root, "submodule", "deinit", "-f", "lib/platform")
    subprocess.run(["rm", "-rf", str(root / ".git" / "modules"), str(root / "lib" / "platform")], check=True)
    # the production rewrite, pointed at the local remote
    monkeypatch.setattr(sources, "REWRITE", f"file://{remote}/")
    return {"root": root, "pinned": pinned, "tip": _git(work, "rev-parse", "HEAD"), "home": home}


def _manifest(monkeypatch, world, body):
    manifest = world["root"].parent / "sample.yaml"
    manifest.write_text("product: sample\n" + body, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("sample", world["root"], manifest))


SOURCES = "sources:\n  - submodule: lib/platform\n    secret: PLATFORM_TOKEN\n"


def test_checks_out_the_pinned_commit(monkeypatch, world):
    _manifest(monkeypatch, world, SOURCES)

    rc = sources.sources_cmd()

    assert rc == 0
    head = _git(world["root"] / "lib" / "platform", "rev-parse", "HEAD")
    assert head == world["pinned"] != world["tip"]


def _stale_global(world):
    (world["home"] / ".gitconfig").write_text(
        f'[url "file:///nowhere/"]\n\tinsteadOf = https://github.com/\n', encoding="utf-8")


def test_a_stale_global_rewrite_does_not_win(monkeypatch, world):
    _manifest(monkeypatch, world, SOURCES)
    _stale_global(world)

    rc = sources.sources_cmd()

    assert rc == 0
    assert _git(world["root"] / "lib" / "platform", "rev-parse", "HEAD") == world["pinned"]


def test_without_hiding_the_global_config_the_stale_rewrite_wins(monkeypatch, world):
    """The red twin: pins WHY `GIT_CONFIG_GLOBAL` is in the environment."""
    _manifest(monkeypatch, world, SOURCES)
    _stale_global(world)
    real = sources.git_env
    monkeypatch.setattr(sources, "git_env",
                        lambda token: {k: v for k, v in real(token).items() if k != "GIT_CONFIG_GLOBAL"})

    rc = sources.sources_cmd()

    assert rc == 1


def _recording(monkeypatch, then=None):
    calls = []
    real = gitops.run

    def spy(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return then(argv, kwargs) if then else real(argv, **kwargs)

    monkeypatch.setattr(gitops, "run", spy)
    return calls


def test_the_token_never_reaches_argv(monkeypatch, world):
    _manifest(monkeypatch, world, SOURCES)
    calls = _recording(monkeypatch)

    sources.sources_cmd()

    assert calls
    assert all(TOKEN not in arg for argv, _ in calls for arg in argv)


def test_the_production_rewrite_carries_the_token_in_the_environment_only(monkeypatch):
    monkeypatch.undo()  # the fixture's local target is not the production one

    env = sources.git_env(TOKEN)

    assert env["GIT_CONFIG_KEY_0"] == f"url.https://x-access-token:{TOKEN}@github.com/.insteadOf"
    assert env["GIT_CONFIG_VALUE_0"] == "https://github.com/"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null" and env["GIT_CONFIG_COUNT"] == "1"


def test_the_token_is_registered(monkeypatch, world):
    monkeypatch.setattr(secrets, "_values", {})
    _manifest(monkeypatch, world, SOURCES)

    sources.sources_cmd()

    assert secrets.redact(TOKEN) == "***"


def test_empty_secret_under_actions_is_refused(monkeypatch, world, capsys):
    _manifest(monkeypatch, world, SOURCES)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("PLATFORM_TOKEN")
    calls = _recording(monkeypatch)

    rc = sources.sources_cmd()

    out = capsys.readouterr()
    assert rc == 1
    assert "PLATFORM_TOKEN" in out.out + out.err
    assert "fork" in out.out + out.err
    assert not any("submodule" in argv for argv, _ in calls)


def test_empty_secret_outside_actions_uses_the_users_git(monkeypatch, world, capsys):
    _manifest(monkeypatch, world, SOURCES)
    monkeypatch.setenv("PLATFORM_TOKEN", "")
    real = gitops.run
    calls = _recording(monkeypatch, then=lambda argv, kw: runmod.Result(0, "", "")
                       if "submodule" in argv else real(argv, **kw))

    rc = sources.sources_cmd()

    update = [kw for argv, kw in calls if "submodule" in argv]
    assert rc == 0 and len(update) == 1
    assert "GIT_CONFIG_GLOBAL" not in (update[0].get("env") or {})
    assert "no token" in capsys.readouterr().out


def test_not_a_submodule_is_refused(monkeypatch, world, capsys):
    _manifest(monkeypatch, world, "sources:\n  - submodule: lib/other\n")

    rc = sources.sources_cmd()

    out = capsys.readouterr()
    assert rc == 1
    assert "lib/other" in out.out + out.err and "lib/platform" in out.out + out.err


def test_secret_with_a_non_github_url_is_refused(monkeypatch, world, capsys):
    _git(world["root"], "config", "-f", ".gitmodules", "submodule.lib/platform.url", "https://example.org/x.git")
    _manifest(monkeypatch, world, SOURCES)
    calls = _recording(monkeypatch)

    rc = sources.sources_cmd()

    out = capsys.readouterr()
    assert rc == 1
    assert "https://github.com/" in out.out + out.err
    assert not any("submodule" in argv for argv, _ in calls)


def test_git_failure_reports_path_and_redacted_output(monkeypatch, world, capsys):
    _manifest(monkeypatch, world, SOURCES)
    monkeypatch.setattr(secrets, "_values", {})
    monkeypatch.setattr(sources, "REWRITE", "file:///nowhere/")
    real = gitops.run
    _recording(monkeypatch, then=lambda argv, kw: runmod.Result(128, "", f"fatal: could not read {TOKEN}@host")
               if "submodule" in argv else real(argv, **kw))

    rc = sources.sources_cmd()

    out = capsys.readouterr()
    text = out.out + out.err
    assert rc == 1
    assert "lib/platform" in text and TOKEN not in text and "***" in text


def test_no_sources_says_so(monkeypatch, world, capsys):
    _manifest(monkeypatch, world, "")

    rc = sources.sources_cmd()

    assert rc == 0
    assert "declares no `sources:`" in capsys.readouterr().out
