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
                  is_ancestor: bool, in_merged_prs: bool,
                  prune_unmerged: bool = False) -> tuple[str, str]:
    """Decide what to do with a local branch during prune-branches:

    - ("skip", "")            - it is main or the current branch: never touch.
    - ("keep", "worktree")    - checked out in some worktree (git refuses to delete it anyway).
    - ("delete", "ancestor")  - its tip is an ancestor of origin/main: a normal (fast-forward/merge) merge.
    - ("delete", "pr-merged") - it is the head branch of a MERGED PR: the squash-merge case (NOT an
                                ancestor of main, so only the PR-name check catches it).
    - ("keep", "unmerged")    - none of the above: keep it, because it cannot be PROVEN merged.

    Order matters: skip > worktree > ancestor > pr-merged > the unmerged bucket.

    `prune_unmerged` turns that last bucket into ("delete", "unmerged"). It exists because the bucket
    never empties on its own: a branch whose PR branch was deleted on the remote, or that never had a PR,
    is indistinguishable from work in progress, so finished work accumulates until someone types a raw
    `git branch -D` loop. It is a PARAMETER rather than a second function so the ordering above has one
    definition and one set of tests.

    The three protections above it are deliberately NOT weakened by the flag: they are about correctness,
    not caution. Deleting the current branch or a worktree's branch is something git refuses anyway, and
    a flag that turned those into silent failures would be worse than no flag.
    """
    if is_main_or_current:
        return ("skip", "")
    if in_worktree:
        return ("keep", "worktree")
    if is_ancestor:
        return ("delete", "ancestor")
    if in_merged_prs:
        return ("delete", "pr-merged")
    return ("delete", "unmerged") if prune_unmerged else ("keep", "unmerged")


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


def init_submodule(path: str = "lib/platform") -> int:
    """`git submodule update --init <path>` - init a vendored submodule a fresh worktree/clone needs
    before the product's CLI can boot. git no-ops on an already-initialised checkout, so this composes
    as a plain CLI command. The default path is the platform kernel's own vendored location, shared by
    every product in the family (netctl#434/#435/#658)."""
    _require("git")
    return 0 if _git(["submodule", "update", "--init", path]).ok else 1


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


def prune_branches(dry: bool = False, remote: bool = False, unmerged: bool = False) -> int:
    """Delete local branches already merged into main - including SQUASH-merged ones, detected via the
    merged-PR head-branch names (gh). main + the current branch + any worktree-checked-out branch are kept.
    --dry-run previews; --remote also deletes them on origin.

    `unmerged` additionally clears the branches that cannot be PROVEN merged (#1136). That bucket never
    empties on its own, so finished work piles up in it. It is reported separately from the provably
    merged ones and each deletion prints its tip sha, because the two carry completely different risk:
    one is bookkeeping, the other may be the last copy of something. The sha makes it recoverable from
    the reflog by whoever realises a minute later."""
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
    unproven: list[str] = []   # deleted WITHOUT proof of merge (#1136): reported apart from the rest
    deleted_preview = 0        # what a --dry-run WOULD delete, so its summary can say something
    deleted = 0
    for b in branches:
        action, reason = prune_verdict(
            is_main_or_current=(b == main or b == cur),
            in_worktree=(b in worktree_branches),
            is_ancestor=_git(["merge-base", "--is-ancestor", b, f"origin/{main}"]).ok,
            in_merged_prs=(b in merged_prs),
            prune_unmerged=unmerged,
        )
        if action == "skip":
            continue
        if action == "keep":
            kept.append(b)
            continue
        # The unmerged bucket carries its tip sha, and only it: for a merged branch the sha is noise, for
        # this one it is the difference between "recoverable from the reflog" and "gone".
        if reason == "unmerged":
            tip = (_git(["rev-parse", "--short", b]).out or "").strip()
            why = f"NOT proven merged - tip {tip}"
        else:
            why = f"merged into {main}" if reason == "ancestor" else "PR merged"
        if dry:
            log.info(f"would delete {b} ({why})")
            deleted_preview += 1
            if reason == "unmerged":
                unproven.append(b)
            continue
        if _git(["branch", "-D", b]).ok:
            log.ok(f"deleted {b} ({why})")
            deleted += 1
            if reason == "unmerged":
                unproven.append(b)
            if remote and _git(["ls-remote", "--exit-code", "--heads", "origin", b]).ok:
                if _git(["push", "origin", "--delete", b]).ok:
                    log.ok(f"deleted origin/{b}")
                else:
                    log.warn(f"could not delete origin/{b}")
        else:
            log.warn(f"could not delete {b} (left in place)")

    if dry and not deleted_preview and not kept:
        # A dry run that prints nothing cannot be told apart from a dry run that failed to look.
        log.ok("nothing to prune: no local branch besides main and the current one")
    if not dry:
        log.ok(f"pruned {deleted} obsolete local branch(es)")
    if unproven:
        verb = "would delete" if dry else "deleted"
        log.warn(f"{verb} {len(unproven)} branch(es) that could NOT be proven merged (--unmerged): "
                 f"{', '.join(unproven)}")
        log.warn("  recover one with `git branch <name> <tip-sha>` from the lines above, or `git reflog`")
    if kept:
        log.info(f"kept {len(kept)} active/unmerged branch(es):")
        for b in kept:
            print(f"  {b}")
    return 0
