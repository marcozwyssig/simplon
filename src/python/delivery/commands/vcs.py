"""The version-control command surface (commit / push / prune-branches / submodules), netctl#1280 (epic
#1274 slice S6): the bodies a product's manifest points its `impl:` straight at.

FRAMEWORK-FREE since netctl#1444: plain functions with plain parameters, returning an exit code. The
option declarations that used to live here as `typer.Option`/`typer.Argument` defaults are manifest
`params:` data now, and the generated CLI module renders them - so these functions are callable from
anything, not only from a Click parser, and the decorator lives only in generated code.

The mechanism - git/gh subprocess wrappers and the pure `prune_verdict` decision - already lives in
`delivery.vcs`; this module is the thin layer that points it at the calling product's repo root. ROOT
comes from `delivery.context.current().root`, never from a product import: this module knows no product
name and no product layout beyond the one path every product in the family vendors this repo at
(`lib/platform`).
"""
from __future__ import annotations

from delivery import context, vcs


def _configure() -> None:
    """Point the delivery.vcs wrappers at the calling product's repo root."""
    vcs.configure(context.current().root)


def commit(message: list[str] | None = None) -> int:
    """git add -A + git commit -m."""
    _configure()
    return vcs.commit(" ".join(message or []))


def push() -> int:
    """git pull --rebase then push (current branch)."""
    _configure()
    return vcs.push()


def prune_branches(dry_run: bool = False, remote: bool = False, unmerged: bool = False) -> int:
    """Delete local branches already merged into main (squash-aware via gh).

    `--unmerged` additionally clears the branches the squash-aware check cannot PROVE are merged. That
    bucket never empties on its own - a branch whose PR branch was deleted on the remote, or that never
    had one, looks exactly like work in progress - so finished work accumulates there indefinitely.
    Destructive by nature, hence opt-in: those deletions are listed apart from the provably merged ones
    and each prints its tip sha, so a change of mind is a `git branch <name> <sha>` away. main, the
    current branch and any worktree's branch stay protected regardless."""
    _configure()
    return vcs.prune_branches(dry=dry_run, remote=remote, unmerged=unmerged)


def submodules() -> int:
    """git submodule update --init lib/platform - init the delivery-kernel submodule a fresh
    worktree/clone needs before the product's CLI can boot."""
    _configure()
    return vcs.init_submodule()
