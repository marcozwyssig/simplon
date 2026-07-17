"""Version-control commands (commit / push / prune-branches): git/gh subprocess wrappers.

The one piece of real logic - whether a local branch is obsolete and why (merged into main, a merged PR's
head branch, or kept because it is active/unmerged) - is the pure, unit-tested prune_verdict. The
squash-merge workflow is why this matters: a squash-merged branch is NOT an ancestor of main, so the
merged-PR-name check (via gh) is the authoritative signal.

The git wrappers run `git -C <ROOT>`; a consuming product points ROOT at its repo root via configure().
"""
from __future__ import annotations

import shutil
from pathlib import Path

from delivery import log
from delivery.run import run

ROOT = Path.cwd()


def configure(root: Path | str) -> None:
    """Point the git wrappers at the product's repo root (they run `git -C <root>`)."""
    global ROOT
    ROOT = Path(root)


def _git(args: list[str], *, capture: bool = True):
    return run(["git", "-C", str(ROOT), *args], capture=capture)


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        log.die(f"missing required tool: {tool}")


# --- pure decision (unit-tested) --------------------------------------------------------------------

def prune_verdict(*, is_main_or_current: bool, in_worktree: bool,
                  is_ancestor: bool, in_merged_prs: bool) -> tuple[str, str]:
    """Decide what to do with a local branch during prune-branches:

    - ("skip", "")            - it is main or the current branch: never touch.
    - ("keep", "worktree")    - checked out in some worktree (git refuses to delete it anyway).
    - ("delete", "ancestor")  - its tip is an ancestor of origin/main: a normal (fast-forward/merge) merge.
    - ("delete", "pr-merged") - it is the head branch of a MERGED PR: the squash-merge case (NOT an
                                ancestor of main, so only the PR-name check catches it).
    - ("keep", "unmerged")    - none of the above: real work in progress, keep it.

    Order matters: skip > worktree > ancestor > pr-merged > keep.
    """
    if is_main_or_current:
        return ("skip", "")
    if in_worktree:
        return ("keep", "worktree")
    if is_ancestor:
        return ("delete", "ancestor")
    if in_merged_prs:
        return ("delete", "pr-merged")
    return ("keep", "unmerged")


# --- commands ---------------------------------------------------------------------------------------

def commit(message: str) -> int:
    """git add -A + commit -m, a no-op (warn) when the tree is clean."""
    _require("git")
    if not message:
        log.die("commit message must not be empty")
    _git(["add", "-A"])
    if _git(["diff", "--cached", "--quiet"]).ok:
        log.warn("nothing to commit (working tree clean)")
        return 0
    if not _git(["commit", "-m", message], capture=False).ok:
        log.die("git commit failed")
    short = (_git(["rev-parse", "--short", "HEAD"]).out or "").strip()
    log.ok(f"committed {short}: {message}")
    return 0


def push() -> int:
    """git pull --rebase then push (current branch); abort the rebase + die on conflicts."""
    _require("git")
    branch = (_git(["rev-parse", "--abbrev-ref", "HEAD"]).out or "").strip()
    if not branch:
        log.die("not a git repository")
    log.info(f"pull --rebase + push ({branch})")
    if not _git(["pull", "--rebase"], capture=False).ok:
        _git(["rebase", "--abort"])
        log.die("pull --rebase failed (conflicts?); resolve them, then re-run the push")
    if not _git(["push"], capture=False).ok:
        log.die("git push failed")
    log.ok(f"pushed {branch}")
    return 0


def prune_branches(dry: bool = False, remote: bool = False) -> int:
    """Delete local branches already merged into main - including SQUASH-merged ones, detected via the
    merged-PR head-branch names (gh). main + the current branch + any worktree-checked-out branch are kept.
    --dry-run previews; --remote also deletes them on origin."""
    _require("git")
    log.info("fetching + pruning stale remote-tracking refs")
    if not _git(["fetch", "--prune", "--quiet"]).ok:
        log.die("git fetch failed")

    main = (_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]).out or "").strip()
    main = main[len("origin/"):] if main.startswith("origin/") else (main or "main")
    cur = (_git(["rev-parse", "--abbrev-ref", "HEAD"]).out or "").strip()

    wt = _git(["worktree", "list", "--porcelain"]).out or ""
    worktree_branches = {ln[len("branch refs/heads/"):] for ln in wt.splitlines()
                         if ln.startswith("branch refs/heads/")}

    merged_prs: set[str] = set()
    if shutil.which("gh") is not None:
        res = run(["gh", "pr", "list", "--state", "merged", "--limit", "300",
                   "--json", "headRefName", "-q", ".[].headRefName"])
        if res.ok:
            merged_prs = {ln.strip() for ln in (res.out or "").splitlines() if ln.strip()}
        else:
            log.warn("gh pr list failed; using the ancestor check only (squash-merged branches may be kept)")
    else:
        log.warn("gh not found; using the ancestor check only (squash-merged branches may be kept - install gh for full cleanup)")

    branches = [ln.strip() for ln in (_git(["for-each-ref", "--format=%(refname:short)",
                                            "refs/heads/"]).out or "").splitlines() if ln.strip()]
    kept: list[str] = []
    deleted = 0
    for b in branches:
        action, reason = prune_verdict(
            is_main_or_current=(b == main or b == cur),
            in_worktree=(b in worktree_branches),
            is_ancestor=_git(["merge-base", "--is-ancestor", b, f"origin/{main}"]).ok,
            in_merged_prs=(b in merged_prs),
        )
        if action == "skip":
            continue
        if action == "keep":
            kept.append(b)
            continue
        why = f"merged into {main}" if reason == "ancestor" else "PR merged"
        if dry:
            log.info(f"would delete {b} ({why})")
            continue
        if _git(["branch", "-D", b]).ok:
            log.ok(f"deleted {b} ({why})")
            deleted += 1
            if remote and _git(["ls-remote", "--exit-code", "--heads", "origin", b]).ok:
                if _git(["push", "origin", "--delete", b]).ok:
                    log.ok(f"deleted origin/{b}")
                else:
                    log.warn(f"could not delete origin/{b}")
        else:
            log.warn(f"could not delete {b} (left in place)")

    if not dry:
        log.ok(f"pruned {deleted} obsolete local branch(es)")
    if kept:
        log.info(f"kept {len(kept)} active/unmerged branch(es):")
        for b in kept:
            print(f"  {b}")
    return 0
