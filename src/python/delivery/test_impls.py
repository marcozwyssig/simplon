"""Importable bodies for the manifest and generator unit tests (netctl#1434).

Not part of any product's surface. They exist so a test can exercise signature introspection against a
REAL callable: introspecting a mock would verify the mock, not the generator.
"""


def seed(c, sites="all", dry_run=False):
    """Seed the lab and run the smoke test."""
    return (sites, dry_run)


def gradle(c, *args):
    """Run gradle tasks in the containerised toolchain."""
    return args


def needs_site(c, site):
    """Pin a site. Has a REQUIRED parameter, which must not gain a default."""
    return site


def no_context(message=None):
    """A body whose first parameter is its PAYLOAD, not an Invoke Context (as delivery.commands.vcs:commit)."""
    return message


def nullary():
    """A body taking nothing at all (as delivery.commands.vcs:push)."""
    return 0
