"""simplon's own `release push-pin` (si#622): the push of the kernel-image pin branch, with the run's token.

No generated checkout persists the job's token any more, so release.yml's `image` job pushes its pin branch
through this command, which goes through `gitops.push_branch`. That the push carries the token as one
`Authorization` header is `test_gitops_remote_auth.py`'s, against a real HTTP listener; this holds what the
product body adds: only the pin branch a release tag names, and by force, against a real git and a real (local, bare) origin.

AAA; the name states the behaviour under test.
"""
import subprocess
import sys

import pytest

from conftest import ROOT  # noqa: E402 - the one product-root anchor (si#283)

sys.path.insert(0, str(ROOT / "deploy" / "orchestrator" / "src" / "python"))
from orchestrator import cli  # noqa: E402 - the product's own module, only reachable from here

TAG = "v1.2.3"
BRANCH = f"pin/kernel-image-{TAG}"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path, monkeypatch):
    """A clone on BRANCH with one commit, whose origin is a bare repository beside it."""
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git("init", "-q", "--bare", str(origin))
    _git("init", "-q", "-b", BRANCH, str(work))
    _git("-C", str(work), "commit", "-q", "--allow-empty", "-m", "pin")
    _git("-C", str(work), "remote", "add", "origin", str(origin))
    monkeypatch.setattr(cli, "ROOT", work)
    return work, origin


def test_the_pin_branch_reaches_origin(clone):
    # arrange
    work, origin = clone

    # act
    rc = cli.push_pin(TAG)

    # assert
    assert rc == 0
    assert _git("-C", str(origin), "rev-parse", BRANCH) == _git("-C", str(work), "rev-parse", "HEAD")


def test_a_rerun_replaces_the_pin_branch_by_force(clone):
    """A rerun of the job remakes the branch from origin/main, which is not a fast-forward of the last push."""
    # arrange
    work, origin = clone
    assert cli.push_pin(TAG) == 0
    _git("-C", str(work), "commit", "-q", "--amend", "--allow-empty", "-m", "pin again")

    # act
    rc = cli.push_pin(TAG)

    # assert
    assert rc == 0
    assert _git("-C", str(origin), "rev-parse", BRANCH) == _git("-C", str(work), "rev-parse", "HEAD")


@pytest.mark.parametrize("tag", ["", "main", "latest", "v1.2", "v1.2.3/x", BRANCH,
                                 # si#660: what `release.VERSION` refuses names no release, so no pin branch
                                 "v01.2.3", "v1.2.03", "v١.2.3"])
def test_anything_but_a_release_tag_is_refused_and_nothing_is_pushed(clone, tag):
    """The branch is named from the tag, so a tag that is no vX.Y.Z could name some other branch."""
    # arrange
    _, origin = clone

    # act
    rc = cli.push_pin(tag)

    # assert
    assert rc == 2
    assert _git("-C", str(origin), "for-each-ref") == ""
