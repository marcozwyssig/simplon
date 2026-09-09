"""Importable bodies for the manifest and generator unit tests (netctl#1434).

Not part of any product's surface. They exist so a test can exercise signature introspection against a
REAL callable: introspecting a mock would verify the mock, not the generator.

Each returns an EXIT CODE and records its call in `CALLS`, because the generated wrapper coerces the
return value with `_rc` - a body returning anything else is a defect the wrapper refuses to paper over,
so a fixture returning a tuple would be testing a shape no real body may have.
"""

import os

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
    """A body whose first parameter is its PAYLOAD, not a context (as simplon.tasks.vcs:commit)."""
    CALLS.append(("no_context", message))
    return 0


def nullary():
    """A body taking nothing at all (as simplon.tasks.vcs:push)."""
    CALLS.append(("nullary",))
    return 0


def pruner(dry_run=False, remote=False):
    """Delete local branches already merged into main. Two plain bools, for the `params:` cases."""
    CALLS.append(("pruner", dry_run, remote))
    return 0


def member_dispatch(member: str | None = None):
    """Drive a group by member name; omit to list them (as simplon.tasks.nexus:nexus_cmd).

    An OPTIONAL positional whose annotation is `str | None`, for the `argument:` + `metavar:` cases.
    """
    CALLS.append(("member_dispatch", member))
    return 0


def pinned_rc(rc: int = 0, tag: str = "", marker: str = ""):
    """A body whose EXIT CODE the manifest pins with `with:` (si#106).

    It stands in for a containerised toolchain command - `ctest`, `dotnet test`, `gradle test` - where
    the test cares about the rc the command hands back and about whether it ran at all, not about what
    it ran. Both are recorded, so a test can assert that a command did NOT run, which is what the wrong
    green si#106 measured is made of.

    `marker`, when pinned, is written into the setup-marker file the kernel offers a runner that knows
    its own preparation fell over - the same three lines a product's own runner writes.
    """
    from simplon.tasks.testrun import SETUP_MARKER_ENV     # lazy: this module must stay import-cheap

    CALLS.append(("pinned_rc", tag, rc))
    path = os.environ.get(SETUP_MARKER_ENV, "")
    if marker and path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(marker)
    return rc


def needs_a_value(value):
    """A body with a REQUIRED payload parameter and NO context (si#106).

    `needs_site` is the same shape with a context in front, and the two are not interchangeable: a gate
    refuses a context-taking body before it ever looks at what is pinned, so the unpinned-parameter rule
    needs a body the first refusal does not catch.
    """
    CALLS.append(("needs_a_value", value))
    return 0
