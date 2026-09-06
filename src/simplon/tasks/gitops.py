"""Version-control commands (commit / push / prune-branches) and the git primitives the release tag is
cut with: git/gh subprocess wrappers.

The two pieces of real logic are pure and unit-tested. `prune_verdict` decides whether a local branch is
obsolete and why (merged into main, a merged PR's head branch, or kept because it is active/unmerged) -
the squash-merge workflow is why it matters, since a squash-merged branch is NOT an ancestor of main, so
the merged-PR-name check (via gh) is the authoritative signal. `tag_verdict` (#32/#23) decides what
`release:tag` may do before it touches the remote.

IT MOVED HERE FROM THE TOP LEVEL (#37). Nothing outside this directory ever imported it - measured
across every repository that installs simplon, the importers are `simplon.tasks.vcs` and
`simplon.tasks.release`, both neighbours - so it was the shared innards of two task bodies sitting where
the kernel lives. It also carried the name `simplon.vcs`, one character of path away from
`simplon.tasks.vcs`, the command body that calls it; `gitops` says which of the two is the mechanism
without anybody having to open both. A tombstone at the old path says where it went (`simplon.surface`).

WHY THE TAG PRIMITIVES ARE HERE AND THE COMMAND IS NOT. This module is the kernel's single `git -C
<ROOT>` seam, and a second one would be the drift every rule in this repository refuses; the pure
verdict belongs beside its primitives for the same reason `prune_verdict` does. The COMMAND, though,
lives in `simplon.tasks.release`, because its coordinate is `release:tag` - a phase command, not one of
the git helpers `simplon.tasks.vcs` places under `support git`.

The tag primitives below are also SILENT, unlike `commit`/`push`/`prune_branches` above, which log as
they go. That is deliberate rather than inconsistent: the message `release:tag` has to produce describes
a COMPOSITE state - whether the tag was cut by this run or left over from an earlier one, and whether it
survived a rejected push - and no single primitive knows it. One caller composes them, so one caller
owns every word about the outcome.

The git wrappers run `git -C <ROOT>`; a consuming product points ROOT at its repo root via configure().
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Sequence

from simplon import log
from simplon.run import Result, run

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


def require_git() -> None:
    """The tool gate as a PUBLIC name, for a caller outside this module.

    The commands below reach `_require` directly, but `simplon.tasks.release` composes the primitives
    itself and needs the same gate - and `run()` does not turn a missing binary into a return code, it
    raises FileNotFoundError from inside a wrapper the reader did not write. One named entry point beats
    either a second `shutil.which` or a sibling module reaching for a private.
    """
    _require("git")


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


def tag_verdict(*, carried_by_main: bool, local_tag_at: str, head: str) -> tuple[str, str]:
    """Decide what `release:tag` may do BEFORE it touches the remote (#32, guard #23):

    - ("refuse", "off-main")  - HEAD is not carried by the remote's default branch. #23's question, and
                               the state nothing stops anyone from tagging today: the release workflow
                               builds whatever the tag points at, so a feature branch would publish.
    - ("refuse", "moved")     - the tag already exists HERE, naming a different commit. Re-pointing it
                               silently would publish something other than the earlier run promised.
    - ("resume", "unpushed")  - the tag is already cut at HEAD. This is the state a REJECTED PUSH leaves
                               behind, and it is neither "nothing to do" nor "done" - which is exactly
                               why it needs a name (#32 acceptance 5). The answer is to push it, not to
                               read it as a release that already happened.
    - ("cut", "")             - no such tag here yet: the ordinary first run.

    Order matters: off-main > moved > resume > cut. The guard is first because a tag an earlier run cut
    on a feature branch is still a tag on a feature branch - resuming it would walk the guard's own
    refusal straight to the remote.

    WHAT IS NOT DECIDED HERE, deliberately: whether the REMOTE already carries the tag. That question is
    the remote's to answer, and #3's whole mechanism rests on it - a tag is unique on the remote,
    whoever pushes first has the number, and the loser is told by `git push` rather than by a reviewer.
    A pre-flight `ls-remote` would move that decision here, where it would be raced anyway (the answer
    can go stale between the check and the push) and where losing would look like this task's opinion
    rather than a fact about the world.
    """
    if not carried_by_main:
        return ("refuse", "off-main")
    if not local_tag_at:
        return ("cut", "")
    return ("resume", "unpushed") if local_tag_at == head else ("refuse", "moved")


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
    as a plain CLI command. `lib/platform` is only the family's conventional vendoring path
    (netctl#434/#435/#658), not this kernel: simplon is installed from PyPI, never vendored. A product
    vendoring something else passes its own path."""
    _require("git")
    return 0 if _git(["submodule", "update", "--init", path]).ok else 1


def default_branch() -> str:
    """The BARE name of the branch `origin/HEAD` points at, falling back to `main`.

    Extracted from `prune_branches`, which has asked this question since it existed, so `release:tag`
    asks it the same way rather than restating the expression. The fallback earns its place: a
    repository whose remote-tracking symbolic ref was never set - `git remote add` + `git push -u`,
    without a clone - has no `origin/HEAD` at all, which is the ordinary state of a repository created
    rather than cloned.
    """
    named = (_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]).out or "").strip()
    return named[len("origin/"):] if named.startswith("origin/") else (named or "main")


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

    main = default_branch()
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


# --- the gh token's scopes --------------------------------------------------------------------------
#
# `gh auth login` requests gist, read:org, repo and workflow - never the package scopes GHCR needs, so
# the first publish from a fresh login fails at the REGISTRY with "permission_denied" and reads like a
# problem with the package rather than with the token. Reading and refreshing them is a git-host chore,
# which is why it lives beside the other gh wrappers; WHICH scopes are wanted is the caller's business
# (simplon.tasks.vcs takes them from githubpackages).

_SCOPE_LINE = re.compile(r"Token scopes:\s*(.+)")


def parse_scopes(status_text: str) -> tuple[str, ...]:
    """The scopes named on `gh auth status`' "Token scopes:" line, in order. Pure.

    An empty tuple when there is no such line: nobody logged in is a state to report, not to crash on.
    """
    match = _SCOPE_LINE.search(status_text)
    if match is None:
        return ()
    return tuple(part.strip().strip("'\"") for part in match.group(1).split(",") if part.strip())


def gh_scopes(host: str = "github.com") -> tuple[str, ...]:
    """The scopes the stored gh token actually carries."""
    _require("gh")
    result = run(["gh", "auth", "status", "-h", host])
    return parse_scopes(f"{result.out}\n{result.err}")


def refresh_scopes(scopes: Sequence[str], host: str = "github.com") -> int:
    """Ask gh to re-authorise its token WITH `scopes` added; 0 on success.

    Interactive by nature - gh opens a browser and waits for a one-time code - so a caller without a
    terminal must not reach this. capture=False for the same reason: the code has to be visible.
    """
    _require("gh")
    log.info(f"refreshing the gh token with: {', '.join(scopes)}")
    return 0 if run(["gh", "auth", "refresh", "-h", host, "-s", ",".join(scopes)],
                    capture=False).ok else 1


# --- the release tag (#32; the guard it carries is #23) ---------------------------------------------
#
# Silent by design - see this module's head. `simplon.tasks.release` composes them and owns every word
# printed about the outcome, because the outcome is a composite of what these each answer separately.

def head_commit() -> str:
    """The full sha of HEAD, or "" when this is not a git repository (or has no commit yet)."""
    result = _git(["rev-parse", "--verify", "--quiet", "HEAD"])
    return (result.out or "").strip() if result.ok else ""


def describe(commit: str) -> str:
    """`<short sha> ("<subject>")` for a commit, or the bare ref when git cannot resolve it.

    Both messages that report a refusal print two commits against each other, and a bare sha pair does
    not let a human see which is which - the subject line is what makes "this is my feature commit" and
    "this is what main carries" tell themselves apart (#23's third open question).
    """
    result = _git(["log", "-1", "--format=%h (%s)", commit])
    return (result.out or "").strip() if result.ok else commit


def current_branch() -> str:
    """The branch name HEAD is on, or "HEAD" on a detached checkout - git's own word for it."""
    return (_git(["rev-parse", "--abbrev-ref", "HEAD"]).out or "").strip()


def ref_exists(ref: str) -> bool:
    """Whether `ref` resolves here. Used on `origin/<branch>`, where the distinction matters: a ref that
    does not exist is not an ancestor of anything, so without this check a repository with no remote
    would be diagnosed as a feature branch."""
    return _git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).ok


def valid_tag_name(name: str) -> bool:
    """Whether git itself would accept `name` as a tag - `git check-ref-format`, not a convention.

    The kernel deliberately validates nothing beyond this. WHICH tags publish is the product's own
    statement, made in its release workflow's trigger (`tags: ["v*"]` here) and in its setuptools-scm
    configuration; a kernel that enforced a shape would be imposing simplon's convention on every
    product, and the one it enforced could disagree with the workflow that actually listens.
    """
    return bool(name) and _git(["check-ref-format", f"refs/tags/{name}"]).ok


def tag_commit(name: str) -> str:
    """The commit a LOCAL tag names, or "" when there is no such tag.

    `^{commit}` peels an annotated tag to the commit it points at, so an annotated and a lightweight tag
    on the same commit compare equal - the verdict is about which commit is being released, not about
    which of the two shapes somebody used.
    """
    result = _git(["rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{commit}}"])
    return (result.out or "").strip() if result.ok else ""


def carried_by(commit: str, ref: str) -> bool:
    """Whether `ref` contains `commit` - `git merge-base --is-ancestor`, the expression #23 named.

    Note what this is NOT: a check that the tag matches a file. It asks whether the version being cut is
    built from a commit the default branch carries, which is the same question netctl has asked of its
    container images since #1088.
    """
    return _git(["merge-base", "--is-ancestor", commit, ref]).ok


def fetch_branches() -> bool:
    """Refresh the remote-tracking branches - and NOT the tags.

    `--no-tags` is load-bearing rather than tidy. A plain fetch brings down every tag reachable from
    what it fetched, so a rival's tag would land here as a LOCAL tag, and the collision would then be
    refused by `git tag` ("already exists") instead of by the remote. That is precisely the pre-flight
    check #32's acceptance 3 forbids, arrived at by accident - the remote must be what says no.

    The refresh itself is worth having because the guard judges against `origin/<branch>`: a stale one
    can only make the guard refuse a commit main really does carry (a false red, annoying), never let
    an off-main commit through (a false green, the thing being guarded against). A failure to reach the
    remote is therefore reported and survivable, not fatal.
    """
    return _git(["fetch", "--quiet", "--no-tags", "origin"]).ok


def create_tag(name: str) -> bool:
    """Cut a LIGHTWEIGHT tag at HEAD.

    Lightweight because that is what `git tag vX.Y.Z` - the two-command route this command replaces, and
    the one the README documents - produces, and what every tag in this repository already is. The
    command and the hand-typed route have to be the same act; a command that produced a different KIND
    of object would make "the freedom is two typed git commands" quietly untrue.
    """
    return _git(["tag", name]).ok


def push_tag(name: str) -> Result:
    """`git push origin <tag>` - ONE tag, named.

    NEVER `--tags`, and the difference is not cosmetic: `--tags` pushes every local tag, including
    whatever somebody cut to try something out. Measured in this repository: 14 local tags, none
    missing from origin, so today it is harmless - and a `--dry-run --tags` in a scratch pair with two
    stray tags offers both of them to the remote. The blast radius is a property of the flag, not of
    today's tag list.

    Captured rather than streamed, unlike the branch `push` above, because the caller must both SHOW
    what git said and read WHY it said it - a rejection because the number is taken needs different
    advice from a rejection because the network is down, and one message for both would say nothing.
    """
    return _git(["push", "origin", f"refs/tags/{name}"])


def remote_tag_commit(name: str) -> str | None:
    """What `origin` has under this tag, asked of the REMOTE. THREE answers, not two:

      - a commit sha - origin carries the tag, there;
      - `""`         - origin was asked and has no such tag;
      - `None`       - origin could not be asked at all (no remote, no network, no permission).

    The third is not pedantry. Both callers change their mind on it: a read-back that cannot reach the
    remote has not verified anything, and a diagnosis that treats "could not ask" as "origin does not
    have it" would tell somebody a rival's tag is their own leftover. Measured: `ls-remote` exits 0 with
    empty output for a tag that is absent, and 128 when it cannot reach the remote, so `result.ok` is
    exactly this distinction.

    The read-back after the push exists for the reason `release:image` states about its own: a push
    nobody verifies is the same defect as a report nobody reads, and this project has shipped that
    twice. `ls-remote` talks to the remote over the wire and keeps no local store, so it cannot answer
    out of a cache the way a local ref could.

    The peeled `^{}` line wins where there is one: an annotated tag's own line carries the tag OBJECT's
    id, and comparing that with a commit would report a mismatch for a tag that is perfectly correct.
    """
    result = _git(["ls-remote", "--tags", "origin", f"refs/tags/{name}"])
    if not result.ok:
        return None
    found = ""
    for line in (result.out or "").splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == f"refs/tags/{name}^{{}}":
            return sha.strip()
        if ref.strip() == f"refs/tags/{name}":
            found = sha.strip()
    return found
