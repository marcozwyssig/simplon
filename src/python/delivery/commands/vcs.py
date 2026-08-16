"""The version-control command surface (commit / push / prune-branches / submodules), netctl#1280 (epic
#1274 slice S6): real Typer callbacks a product's manifest points its `impl:` straight at.

The mechanism - git/gh subprocess wrappers and the pure `prune_verdict` decision - already lives in
`delivery.vcs`; a manifest-resolved impl must be an actual callable Typer introspects for its
`Option`/`Argument` signatures, so this module cannot be a bare `commit = delivery.vcs.commit` delegate -
that would silently drop every flag. ROOT comes from `delivery.context.current().root`, never from a
product import: this module knows no product name and no product layout beyond the one path every
product in the family vendors this repo at (`lib/platform`).
"""
from __future__ import annotations

from typing import Optional

import typer

from delivery import context, vcs


def _configure() -> None:
    """Point the delivery.vcs wrappers at the calling product's repo root."""
    vcs.configure(context.current().root)


def commit(message: Optional[list[str]] = typer.Argument(None, help="commit message")) -> None:
    """git add -A + git commit -m."""
    _configure()
    raise typer.Exit(vcs.commit(" ".join(message or [])))


def push() -> None:
    """git pull --rebase then push (current branch)."""
    _configure()
    raise typer.Exit(vcs.push())


def prune_branches(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="preview only"),
    remote: bool = typer.Option(False, "--remote", help="also delete merged branches on origin"),
    unmerged: bool = typer.Option(False, "--unmerged",
                                  help="ALSO delete branches that cannot be proven merged (destructive)"),
) -> None:
    """Delete local branches already merged into main (squash-aware via gh).

    `--unmerged` additionally clears the branches the squash-aware check cannot PROVE are merged. That
    bucket never empties on its own - a branch whose PR branch was deleted on the remote, or that never
    had one, looks exactly like work in progress - so finished work accumulates there indefinitely.
    Destructive by nature, hence opt-in: those deletions are listed apart from the provably merged ones
    and each prints its tip sha, so a change of mind is a `git branch <name> <sha>` away. main, the
    current branch and any worktree's branch stay protected regardless."""
    _configure()
    raise typer.Exit(vcs.prune_branches(dry=dry_run, remote=remote, unmerged=unmerged))


def submodules() -> None:
    """git submodule update --init lib/platform - init the delivery-kernel submodule a fresh
    worktree/clone needs before the product's CLI can boot."""
    _configure()
    raise typer.Exit(vcs.init_submodule())
