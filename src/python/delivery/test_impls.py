"""Importable bodies for the manifest and generator unit tests (netctl#1434).

Not part of any product's surface. They exist so a test can exercise signature introspection against a
REAL callable: introspecting a mock would verify the mock, not the generator.

Each returns an EXIT CODE and records its call in `CALLS`, because the generated wrapper coerces the
return value with `_rc` - a body returning anything else is a defect the wrapper refuses to paper over,
so a fixture returning a tuple would be testing a shape no real body may have.
"""

CALLS: list[tuple] = []


def seed(ctx, sites="all", dry_run=False):
    """Seed the lab and run the smoke test."""
    CALLS.append(("seed", sites, dry_run))
    return 0


def gradle(ctx, *args):
    """Run gradle tasks in the containerised toolchain."""
    CALLS.append(("gradle", args))
    return 0


def needs_site(ctx, site):
    """Pin a site. Has a REQUIRED parameter, which must not gain a default."""
    CALLS.append(("needs_site", site))
    return 0


def no_context(message=None):
    """A body whose first parameter is its PAYLOAD, not a context (as delivery.commands.vcs:commit)."""
    CALLS.append(("no_context", message))
    return 0


def nullary():
    """A body taking nothing at all (as delivery.commands.vcs:push)."""
    CALLS.append(("nullary",))
    return 0


def pruner(dry_run=False, remote=False):
    """Delete local branches already merged into main. Two plain bools, for the `params:` cases."""
    CALLS.append(("pruner", dry_run, remote))
    return 0
