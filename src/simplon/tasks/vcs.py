"""The version-control command surface (commit / push / prune-branches / submodules), netctl#1280 (epic
#1274 slice S6): the bodies a product's manifest points its `impl:` straight at.

FRAMEWORK-FREE since netctl#1444: plain functions with plain parameters, returning an exit code. The
option declarations that used to live here as `typer.Option`/`typer.Argument` defaults are manifest
`params:` data now, and the generated CLI module renders them - so these functions are callable from
anything, not only from a Click parser, and the decorator lives only in generated code.

The mechanism - git/gh subprocess wrappers and the pure `prune_verdict` decision - already lives in
`simplon.tasks.gitops`; this module is the thin layer that points it at the calling product's repo root. ROOT
comes from `simplon.context.current().root`, never from a product import: this module knows no product
name and no product layout. The one exception is `submodules`, which carries a conventional default
path - a convention, not a claim about what any particular product vendors there.
"""
from __future__ import annotations

import os
import sys

from simplon import context, githubpackages, log
from simplon.tasks import gitops


def _configure() -> None:
    """Point the simplon.tasks.gitops wrappers at the calling product's repo root."""
    gitops.configure(context.current().root)


def commit(message: list[str] | None = None) -> int:
    """git add -A + git commit -m."""
    _configure()
    return gitops.commit(" ".join(message or []))


def push() -> int:
    """git pull --rebase then push (current branch)."""
    _configure()
    return gitops.push()


def prune_branches(dry_run: bool = False, remote: bool = False, unmerged: bool = False) -> int:
    """Delete local branches already merged into main (squash-aware via gh).

    `--unmerged` additionally clears the branches the squash-aware check cannot PROVE are merged. That
    bucket never empties on its own - a branch whose PR branch was deleted on the remote, or that never
    had one, looks exactly like work in progress - so finished work accumulates there indefinitely.
    Destructive by nature, hence opt-in: those deletions are listed apart from the provably merged ones
    and each prints its tip sha, so a change of mind is a `git branch <name> <sha>` away. main, the
    current branch and any worktree's branch stay protected regardless."""
    _configure()
    return gitops.prune_branches(dry=dry_run, remote=remote, unmerged=unmerged)


def submodules() -> int:
    """git submodule update --init lib/platform - init the submodule a fresh worktree/clone needs.

    A product that vendors nothing at that path simply has no use for this command; the kernel itself
    is a PyPI dependency and is never what gets initialised here."""
    _configure()
    return gitops.init_submodule()


def auth_scopes() -> int:
    """Grant the stored `gh` token the package permissions GHCR needs; idempotent.

    `gh auth login` asks for gist, read:org, repo and workflow - never read:packages/write:packages - so
    a developer who is fully logged in still cannot pull or publish a package, and the registry says so
    in terms of the package rather than of the token. This is that one command, with the scope list
    taken from githubpackages rather than restated, so the two cannot drift apart.

    Three things it deliberately does NOT do. It does not refresh when the scopes are already there (it
    is run before a publish, and a browser opening every time is a reason to stop running it). It does
    not refresh when GITHUB_TOKEN is set, because githubpackages.token() prefers the environment and the
    refreshed token would never be read - the fix there is a token minted WITH the scopes. And it does
    not start the device flow without a terminal: in CI that does not fail, it HANGS until the job times
    out, and CI has the workflow token anyway.
    """
    if (os.getenv("GITHUB_TOKEN") or "").strip():
        log.warn("GITHUB_TOKEN is set and wins over the gh token, so refreshing gh would change "
                 "nothing. Unset it, or mint that token with "
                 f"{', '.join(githubpackages.PACKAGE_SCOPES)}.")
        return 0
    if not sys.stdin.isatty():
        log.info("no terminal: `gh auth refresh` is an interactive device flow. In CI the workflow "
                 "token already carries its package scopes - nothing to do.")
        return 0
    missing = [s for s in githubpackages.PACKAGE_SCOPES if s not in gitops.gh_scopes()]
    if not missing:
        log.ok(f"the gh token already carries {', '.join(githubpackages.PACKAGE_SCOPES)}")
        return 0
    return gitops.refresh_scopes(githubpackages.PACKAGE_SCOPES)
