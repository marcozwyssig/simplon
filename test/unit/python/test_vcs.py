"""Unit tests for vcs.prune_verdict - the squash-aware keep/delete decision behind prune-branches.
No git, no subprocess; AAA throughout. Moved here from netctl - the vcs wrappers are platform's now."""
from platformcore import vcs


def test_main_or_current_branch_is_skipped():
    # arrange / act / assert: main and the current branch are never touched
    assert vcs.prune_verdict(is_main_or_current=True, in_worktree=False,
                             is_ancestor=True, in_merged_prs=True) == ("skip", "")


def test_worktree_branch_is_kept_even_if_merged():
    # arrange: a branch checked out in a worktree but also an ancestor of main
    # act
    action, reason = vcs.prune_verdict(is_main_or_current=False, in_worktree=True,
                                       is_ancestor=True, in_merged_prs=True)

    # assert: worktree wins over the merged signals (git would refuse to delete it anyway)
    assert action == "keep"
    assert reason == "worktree"


def test_ancestor_of_main_is_deleted():
    # arrange / act: a normally-merged (ancestor) branch
    action, reason = vcs.prune_verdict(is_main_or_current=False, in_worktree=False,
                                       is_ancestor=True, in_merged_prs=False)

    # assert
    assert action == "delete"
    assert reason == "ancestor"


def test_squash_merged_branch_is_deleted_via_pr_name():
    # arrange: NOT an ancestor (squash merge rewrites history) but its PR is merged
    action, reason = vcs.prune_verdict(is_main_or_current=False, in_worktree=False,
                                       is_ancestor=False, in_merged_prs=True)

    # assert: the gh PR-name signal catches the squash case
    assert action == "delete"
    assert reason == "pr-merged"


def test_unmerged_branch_is_kept():
    # arrange / act: real work in progress
    action, reason = vcs.prune_verdict(is_main_or_current=False, in_worktree=False,
                                       is_ancestor=False, in_merged_prs=False)

    # assert: kept, never silently lost
    assert action == "keep"
    assert reason == "unmerged"


def test_ancestor_takes_precedence_over_pr_merged():
    # arrange: both signals true -> the ancestor reason wins (it is checked first)
    action, reason = vcs.prune_verdict(is_main_or_current=False, in_worktree=False,
                                       is_ancestor=True, in_merged_prs=True)

    # assert
    assert action == "delete"
    assert reason == "ancestor"
