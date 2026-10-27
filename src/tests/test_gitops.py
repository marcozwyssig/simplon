"""Unit tests for gitops.prune_verdict - the squash-aware keep/delete decision behind prune-branches.
No git, no subprocess; AAA throughout. Moved here from netctl - the git wrappers are platform's now."""
from simplon.tasks import gitops


def test_main_or_current_branch_is_skipped():
    # arrange / act / assert: main and the current branch are never touched
    assert gitops.prune_verdict(is_main_or_current=True, in_worktree=False,
                             is_ancestor=True, in_merged_prs=True) == ("skip", "")


def test_worktree_branch_is_kept_even_if_merged():
    # arrange: a branch checked out in a worktree but also an ancestor of main
    # act
    action, reason = gitops.prune_verdict(is_main_or_current=False, in_worktree=True,
                                       is_ancestor=True, in_merged_prs=True)

    # assert: worktree wins over the merged signals (git would refuse to delete it anyway)
    assert action == "keep"
    assert reason == "worktree"


def test_ancestor_of_main_is_deleted():
    # arrange / act: a normally-merged (ancestor) branch
    action, reason = gitops.prune_verdict(is_main_or_current=False, in_worktree=False,
                                       is_ancestor=True, in_merged_prs=False)

    # assert
    assert action == "delete"
    assert reason == "ancestor"


def test_squash_merged_branch_is_deleted_via_pr_name():
    # arrange: NOT an ancestor (squash merge rewrites history) but its PR is merged
    action, reason = gitops.prune_verdict(is_main_or_current=False, in_worktree=False,
                                       is_ancestor=False, in_merged_prs=True)

    # assert: the gh PR-name signal catches the squash case
    assert action == "delete"
    assert reason == "pr-merged"


def test_unmerged_branch_is_kept():
    # arrange / act: real work in progress
    action, reason = gitops.prune_verdict(is_main_or_current=False, in_worktree=False,
                                       is_ancestor=False, in_merged_prs=False)

    # assert: kept, never silently lost
    assert action == "keep"
    assert reason == "unmerged"


def test_ancestor_takes_precedence_over_pr_merged():
    # arrange: both signals true -> the ancestor reason wins (it is checked first)
    action, reason = gitops.prune_verdict(is_main_or_current=False, in_worktree=False,
                                       is_ancestor=True, in_merged_prs=True)

    # assert
    assert action == "delete"
    assert reason == "ancestor"


# --- #1136: the opt-in that also clears what cannot be PROVEN merged --------------------------------

def test_the_unmerged_bucket_is_deleted_only_when_explicitly_asked_for():
    # arrange / act: the same branch, both ways round
    kept = gitops.prune_verdict(is_main_or_current=False, in_worktree=False,
                             is_ancestor=False, in_merged_prs=False)
    pruned = gitops.prune_verdict(is_main_or_current=False, in_worktree=False,
                               is_ancestor=False, in_merged_prs=False, prune_unmerged=True)

    # assert: the default is unchanged - this flag may never become the quiet default
    assert kept == ("keep", "unmerged")
    assert pruned == ("delete", "unmerged")


def test_main_and_the_current_branch_are_protected_even_with_the_flag():
    # arrange / act: the flag is about the LAST bucket, not about weakening the guards above it
    action, reason = gitops.prune_verdict(is_main_or_current=True, in_worktree=False,
                                       is_ancestor=False, in_merged_prs=False, prune_unmerged=True)

    # assert
    assert action == "skip"
    assert reason == ""


def test_a_worktree_branch_is_protected_even_with_the_flag():
    # arrange / act: git refuses to delete it anyway, so turning this into a delete would only produce a
    # failure the caller has to interpret
    action, reason = gitops.prune_verdict(is_main_or_current=False, in_worktree=True,
                                       is_ancestor=False, in_merged_prs=False, prune_unmerged=True)

    # assert
    assert action == "keep"
    assert reason == "worktree"


def test_a_provably_merged_branch_keeps_its_own_reason_under_the_flag():
    # arrange / act: the flag must not relabel branches the command could already explain, because the
    # reason is what tells the operator which deletions were risk-free
    ancestor = gitops.prune_verdict(is_main_or_current=False, in_worktree=False,
                                 is_ancestor=True, in_merged_prs=False, prune_unmerged=True)
    pr = gitops.prune_verdict(is_main_or_current=False, in_worktree=False,
                           is_ancestor=False, in_merged_prs=True, prune_unmerged=True)

    # assert
    assert ancestor == ("delete", "ancestor")
    assert pr == ("delete", "pr-merged")


# --- init_submodule (netctl#1280): git submodule update --init, no real subprocess ----------------------

class _FakeResult:
    def __init__(self, ok):
        self.ok = ok


def test_init_submodule_runs_git_submodule_update_init_at_the_configured_root(monkeypatch, tmp_path):
    # arrange
    gitops.configure(tmp_path)
    calls = []
    monkeypatch.setattr(gitops, "run", lambda args, capture=True: calls.append(args) or _FakeResult(True))
    monkeypatch.setattr(gitops.shutil, "which", lambda tool: "/usr/bin/git")

    # act
    rc = gitops.init_submodule()

    # assert
    assert rc == 0
    assert calls == [["git", "-C", str(tmp_path), "submodule", "update", "--init", "lib/platform"]]


def test_init_submodule_honours_a_custom_path(monkeypatch, tmp_path):
    # arrange
    gitops.configure(tmp_path)
    calls = []
    monkeypatch.setattr(gitops, "run", lambda args, capture=True: calls.append(args) or _FakeResult(True))
    monkeypatch.setattr(gitops.shutil, "which", lambda tool: "/usr/bin/git")

    # act
    gitops.init_submodule("lib/other")

    # assert
    assert calls == [["git", "-C", str(tmp_path), "submodule", "update", "--init", "lib/other"]]


def test_init_submodule_returns_1_when_git_fails(monkeypatch, tmp_path):
    # arrange
    gitops.configure(tmp_path)
    monkeypatch.setattr(gitops, "run", lambda args, capture=True: _FakeResult(False))
    monkeypatch.setattr(gitops.shutil, "which", lambda tool: "/usr/bin/git")

    # act
    rc = gitops.init_submodule()

    # assert
    assert rc == 1


# --- the gh token's scopes --------------------------------------------------------------------------

def test_the_reported_scopes_are_read_off_the_status_line():
    status = ("github.com\n"
              "  - Active account: true\n"
              "  - Token: gho_************\n"
              "  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'\n")

    scopes = gitops.parse_scopes(status)

    assert scopes == ("gist", "read:org", "repo", "workflow")


def test_a_status_without_a_scope_line_reports_no_scopes():
    # `gh auth status` prints this shape when nobody is logged in - an empty tuple, never a crash.
    scopes = gitops.parse_scopes("You are not logged into any GitHub hosts.\n")

    assert scopes == ()


def test_the_refresh_asks_for_exactly_the_scopes_it_was_given(monkeypatch):
    argv_seen = []
    monkeypatch.setattr(gitops.shutil, "which", lambda tool: "/usr/bin/gh")
    monkeypatch.setattr(gitops, "run", lambda argv, **kw: argv_seen.append(argv) or _FakeResult(True))

    gitops.refresh_scopes(("read:packages", "write:packages"))

    assert argv_seen == [["gh", "auth", "refresh", "-h", "github.com",
                          "-s", "read:packages,write:packages"]]


# --- prune_branches against real repositories: the origin-only case (si#555) -------------------------
#
# A merged branch deleted locally after its merge stays on origin, and `--remote` used to reach origin
# only as a side effect of deleting the LOCAL branch. These run real git against a bare origin in
# tmp_path; gh is replaced by `_pr_heads`, the one seam the PR lists come through.

import subprocess

import pytest


def _sh(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _origin_heads(origin):
    out = subprocess.run(["git", "-C", str(origin), "for-each-ref", "--format=%(refname:short)",
                          "refs/heads/"], check=True, capture_output=True, text=True).stdout
    return set(out.split())


@pytest.fixture
def _repos(tmp_path, monkeypatch):
    """A bare origin with main, `done` (merged into main, deleted locally) and `wip` (pushed, unmerged,
    deleted locally). Returns (clone, origin)."""
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    _sh(clone, "commit", "-q", "--allow-empty", "-m", "root")
    _sh(clone, "push", "-q", "origin", "main")
    _sh(clone, "remote", "set-head", "origin", "main")
    _sh(clone, "switch", "-q", "-c", "done")
    _sh(clone, "commit", "-q", "--allow-empty", "-m", "done")
    _sh(clone, "push", "-q", "origin", "done")
    _sh(clone, "switch", "-q", "main")
    _sh(clone, "merge", "-q", "--ff-only", "done")
    _sh(clone, "push", "-q", "origin", "main")
    _sh(clone, "switch", "-q", "-c", "wip")
    _sh(clone, "commit", "-q", "--allow-empty", "-m", "wip")
    _sh(clone, "push", "-q", "origin", "wip")
    _sh(clone, "switch", "-q", "main")
    _sh(clone, "branch", "-q", "-D", "done", "wip")
    monkeypatch.setattr(gitops, "ROOT", clone)
    monkeypatch.setattr(gitops, "_pr_heads", lambda state: set(), raising=False)
    return clone, origin


def test_remote_deletes_a_merged_branch_that_exists_only_on_origin(_repos):
    clone, origin = _repos

    assert gitops.prune_branches(remote=True) == 0

    assert _origin_heads(origin) == {"main", "wip"}


def test_a_dry_run_names_the_origin_branch_and_deletes_nothing(_repos, capsys):
    clone, origin = _repos

    gitops.prune_branches(dry=True, remote=True)

    assert "would delete origin/done" in capsys.readouterr().out
    assert _origin_heads(origin) == {"main", "done", "wip"}


def test_unmerged_never_reaches_a_branch_that_exists_only_on_origin(_repos):
    clone, origin = _repos

    gitops.prune_branches(remote=True, unmerged=True)

    assert "wip" in _origin_heads(origin)


def test_a_merged_origin_branch_that_heads_an_open_pr_is_kept(_repos, monkeypatch):
    clone, origin = _repos
    monkeypatch.setattr(gitops, "_pr_heads", lambda state: {"done"} if state == "open" else set())

    gitops.prune_branches(remote=True)

    assert "done" in _origin_heads(origin)


def test_without_the_open_pr_list_no_origin_only_branch_is_deleted(_repos, monkeypatch, capsys):
    # A failed `gh pr list --state open` is not "no open PR": it must not license a deletion.
    clone, origin = _repos
    monkeypatch.setattr(gitops, "_pr_heads", lambda state: None if state == "open" else set())

    gitops.prune_branches(remote=True)

    assert "done" in _origin_heads(origin)
    assert "open pull requests" in capsys.readouterr().out
