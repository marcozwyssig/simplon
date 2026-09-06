"""Which modules a product may import, and which are the kernel's own machinery (#37).

THE PROBLEM THIS SOLVES. The kernel has two public surfaces, not one. The first is the task catalogue:
a product writes `<namespace>:<name>` in its manifest and never names a module path - `catalogue.yaml`
says so in its own head, which is what lets a body move inside the kernel without breaking anybody. The
second surface is ordinary Python: a product imports `simplon.log`, `simplon.run`, `simplon.host` and
calls them from its own task bodies. That surface is real, it is used by five repositories today, and
until this module existed **nothing said which modules belonged to it**. Every module sat at the top
level side by side - the ones a product may rely on, the ones the kernel merely happens to share
between its own task bodies, and the ones that are pure internal machinery.

That is not a tidiness complaint. Somebody extending the kernel has to know what they may import, and
somebody changing the kernel has to know what they may break. Both questions had the same answer
before: read every consumer and guess.

WHY A DECLARATION AND NOT A DERIVATION. Everywhere else this repository can derive a fact, it does -
the command reference is read off the assembled app, the version comes off the tag. This one cannot be
derived, and the reason is worth stating because it looks derivable: you can measure who imports what
today, but a promise is about tomorrow. `simplon.compose` has no consumer in any repository right now
and is still a library - it was written as one, it names no product, and the next product to deploy a
compose stack is meant to find it. `simplon.catalogue` has no consumer either and is machinery. The
import graph cannot tell those two apart, because the difference is an intention. So the intention is
written down, once, here - and `tests/test_surface.py` holds it to the tree: every top-level module has
to appear in exactly one of the three sets below, so a module cannot be added without somebody deciding
which surface it is on.

THE TWO RULES THAT FOLLOW. Both are placements, not refusals: nothing here rejects a manifest,
nothing fails at load, and no PRODUCT may say less than it could before.

  1. A module only the kernel's own task bodies use is not library, and it does not belong beside
     `cli.py` and `context.py` where the kernel lives - it belongs under `simplon/tasks/`, with the
     bodies that use it. `allure` and `vcs` were on the wrong side of that line.
  2. A promised module may not share a name with a task body. `simplon.images` against
     `simplon.tasks.image` and `simplon.nexus` against `simplon.tasks.nexus` were one character of path
     apart, and the reader at the call site had nothing to go on. The library half is the half that
     gets renamed, because it is the half a product types.

All four are reachable at their old paths, announcing the move; see `MOVED`.

Both rules are held by `tests/test_surface.py`, and that makes them SELF-BINDING in the sense
`CLAUDE.md` uses (kind 2): a future kernel author may no longer place a module wherever they like, or
name a library module after a task body. It costs a product nothing - no manifest, no command and no
import of theirs is affected - but calling it "no rule at all" would be two posts too generous.

WHAT `simplon/tasks/` IS, STATED CAREFULLY, because the obvious phrasing is false. A task body is
NORMALLY reached by coordinate: a product writes `<namespace>:<name>` and the kernel resolves the
`impl:`. But "a product may not import a task body" is not true and never was - five consumers do it
today, and the kernel is the one that taught them:

  - a hand-written composition root imports a body to call or wrap it (`from simplon.tasks import
    image` in agile-cockpit, `from simplon.tasks import artifact` in cleon);
  - the GENERATED CLI imports every body it registers, and that generator is the kernel's own
    `templates/cli.py.j2` - twelve such lines across netctl and asbundle, written by us.

So the honest line inside `simplon/tasks/` is not "body versus product" but NAMED versus UNNAMED: a
module some catalogue coordinate points its `impl:` at is reachable, by coordinate first and by import
where a composition root has reason to. A module in there that NO coordinate names is innards -
`allure` and `gitops` today - and nothing outside the directory imports either. That split is
derivable from `catalogue.yaml` rather than declared, so `test_surface.py` derives it.
"""
from __future__ import annotations

import warnings
from importlib import import_module
from typing import Any

#: Modules a product may import. Promised: a rename or a signature change here is a breaking change and
#: gets a tombstone in `MOVED` plus a release note. Measured consumers today are simplon's own
#: orchestrator, agile-cockpit, netctl, asbundle and cleon; the ones with no consumer yet are library by
#: intent - each says so in its own head and names no product.
LIBRARY = frozenset({
    "awake", "backend", "clablifecycle", "clabrender", "cli", "compose", "context", "credentials",
    "degraded", "disk", "docker", "environments", "githubpackages", "healthgate", "host", "imagenames",
    "interact", "labegress", "labhost", "labinstance", "labnet", "linux", "log", "nexusproxy",
    "portainer", "ports", "pyvenv", "run", "surface", "taskgen", "topology", "verdict", "waits",
})

#: The subpackages beside those modules. Both are on the library surface and are among the most
#: imported things the kernel has (`simplon.orchestrator` at 21 consumer import sites,
#: `simplon.tasks` at 16), which is exactly why leaving them unclassified was a hole: the completeness
#: test read `*.py` only, so a new subpackage could appear beside `cli.py` and be classified by nobody.
#:
#: They are declared apart from `LIBRARY` rather than folded into it because their rule differs. A
#: LIBRARY module is promised whole. `simplon.orchestrator` is too. `simplon.tasks` is a directory of
#: task BODIES, where the coordinate is the front door and a direct import is the deliberate exception
#: described in this module's head - and where the modules no coordinate names are innards.
PACKAGES = frozenset({"orchestrator", "tasks"})

#: The kernel's own machinery. No product imports these, and they may change without notice.
#:
#: `bootstrap` is the one that needs a word: it carries the `simplon` console script
#: (`[project.scripts]` in pyproject.toml), so `simplon.bootstrap:main` IS a promised entry point. What
#: is not promised is importing the module for its other functions, which is why it sits here.
INTERNAL = frozenset({
    "bootstrap", "catalogue", "clitaxonomy", "diskguard", "oras", "signatures", "steplog",
    "test_impls", "tools",
})

#: Old import path -> where it lives now. Each key is a module that stayed behind as a tombstone: it
#: still imports, and it says on use where the thing went (see `moved_attr`). They come out at the next
#: MINOR release, which is the whole point of announcing rather than deleting - a product gets a working
#: run with a message in it, not a stack trace, and has until then to change the line.
#:
#: Two of them moved because nothing outside `simplon/tasks/` imported them - `allure` and `vcs` were
#: the innards of a task sitting where the kernel lives. The other two are library and were RENAMED
#: where they stood, because each shared a name with a task body and nothing at a call site said which
#: was which: `simplon.images` against `simplon.tasks.image` (unrelated modules - the body has never
#: imported the other) and `simplon.nexus` against `simplon.tasks.nexus` (the body calls it). That pair
#: of near-identical names is what the #31 review lost time to; `test_surface.py` now holds the property
#: rather than the three instances.
MOVED = {
    "allure": "simplon.tasks.allure",
    "images": "simplon.imagenames",
    "nexus": "simplon.nexusproxy",
    "vcs": "simplon.tasks.gitops",
}


def moved_message(old: str, new: str) -> str:
    """The one wording a tombstone announces itself with. Single source, pinned by the tests."""
    return (f"{old} has moved to {new}; import it from there. "
            f"The old path still works and is removed at the next minor release.")


def moved_attr(old: str, new: str, name: str) -> Any:
    """Serve `name` from the module's new home, saying so on the way through.

    This is what a tombstone module's `__getattr__` delegates to, so the wording and the warning
    category live in one place rather than once per tombstone.

    FutureWarning, not DeprecationWarning, and that is measured rather than preferred. Python's default
    filters ignore a DeprecationWarning unless the code that triggered it is `__main__` - and the code
    that triggers this one is a product's own task body, which never is. A DeprecationWarning here would
    therefore be shown to nobody, which is precisely the silent disappearance this is meant to prevent.
    FutureWarning is shown by default whoever triggers it.

    Dunder lookups are refused rather than announced: `inspect`, `pytest` and `importlib` probe for
    `__path__`, `__spec__` and friends on any module they touch, and answering those with a warning
    would report a move that no product code asked for.

    `__all__` IS THE EXCEPTION, and it is not a technicality. `from simplon.images import *` asks a
    module for `__all__` and then for each name in it. Refuse `__all__` and the star-import falls back
    to "every public name in the module dict" - which, for a tombstone, is `Any`, `annotations` and
    `surface`: the star-import silently binds the wrong three names and warns about nothing. That is
    this project's recurring defect exactly - an outcome that cannot tell "nothing to do" from "wrong"
    - so `__all__` is answered, with the move announced like any other use, and the answer is the
    TARGET's own star-import surface so the tombstone behaves precisely like the module it stands for.
    """
    if name == "__all__":
        warnings.warn(moved_message(old, new), FutureWarning, stacklevel=3)
        target = import_module(new)
        return list(getattr(target, "__all__",
                            [n for n in vars(target) if not n.startswith("_")]))
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(f"module {old!r} has no attribute {name!r}")
    warnings.warn(moved_message(old, new), FutureWarning, stacklevel=3)
    return getattr(import_module(new), name)
