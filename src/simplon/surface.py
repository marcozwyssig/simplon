"""Which modules a product may import, and which are the kernel's own machinery (#37).

THE PROBLEM THIS SOLVES. The kernel has two public surfaces, not one. The first is the task catalogue:
a product writes `<namespace>:<name>` in its manifest and never names a module path - `catalogue.yaml`
says so in its own head, which is what lets a body move inside the kernel without breaking anybody. The
second surface is ordinary Python: a product imports `simplon.log`, `simplon.run`, `simplon.host` and
calls them from its own task bodies. That surface is real - the products in `CONSUMERS` below use it, and
so does this repository's own orchestrator - and until this module existed **nothing said which modules
belonged to it**. Every module sat at the top
level side by side - the ones a product may rely on, the ones the kernel merely happens to share
between its own task bodies, and the ones that are pure internal machinery.

That is not a tidiness complaint. Somebody extending the kernel has to know what they may import, and
somebody changing the kernel has to know what they may break. Both questions had the same answer
before: read every consumer and guess.

WHY A DECLARATION AND NOT A DERIVATION. Everywhere else this repository can derive a fact, it does -
the command reference is read off the assembled app, the version comes off the tag. This one cannot be
derived, and the reason is worth stating because it looks derivable: you can measure who imports what
today, but a promise is about tomorrow. `simplon.verdict` has no consumer in any repository right now
and is still a library - it was written as one, it names no product, and the next product to read a
suite's outcome is meant to find it. `simplon.catalogue` has no consumer either and is machinery. The
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

All four were reachable at their old paths for one release, announcing the move. That period ended at
0.5.0 and the tombstones are gone; an old import is now a `ModuleNotFoundError`. What the period was,
and what ending it cost, is under `MOVED` below.

Both rules are held by `tests/test_surface.py`, and that makes them SELF-BINDING in the sense
`CLAUDE.md` uses (kind 2): a future kernel author may no longer place a module wherever they like, or
name a library module after a task body. It costs a product nothing - no manifest, no command and no
import of theirs is affected - but calling it "no rule at all" would be two posts too generous.

WHAT `simplon/tasks/` IS, STATED CAREFULLY, because the obvious phrasing is false. A task body is
NORMALLY reached by coordinate: a product writes `<namespace>:<name>` and the kernel resolves the
`impl:`. But "a product may not import a task body" is not true and never was - four of the five products
do it today, across sixteen import sites, and the kernel is the one that taught them:

  - a hand-written composition root imports a body to call or wrap it (`from simplon.tasks import
    image` in agile-cockpit, `from simplon.tasks import artifact` in cleon);
  - the GENERATED CLI imports every body it registers, and that generator is the kernel's own
    `templates/cli.py.j2` - twelve such lines across netctl and asbundle, written by us.

So the honest line inside `simplon/tasks/` is not "body versus product" but NAMED versus UNNAMED: a
module some catalogue coordinate points its `impl:` at is reachable, by coordinate first and by import
where a composition root has reason to. A module in there that NO coordinate names is innards -
`allure` and `gitops` today - and nothing outside the directory imports either. That split is
derivable from `catalogue.yaml` rather than declared, so `test_surface.py` derives it.

NAMING A CONSUMER IN A MODULE HEAD (#51), decided once here so it is not decided again per module. A
module head may say WHY a module is product-agnostic without naming anybody: that is a property of the
code in front of you, and it stands on its own. It may name a consumer only where the name is the
reason - "two products reuse this gate unchanged" is an argument, "a second one could" is not - and
then the name has to be one of `CONSUMERS` below, because that is the list that was measured.

An ANTICIPATED consumer gets no name. "A second consumer" says exactly as much as "(infractl)" and
cannot become false. The name was not decoration: five module heads named infractl, a repository that
does not install this kernel at all, and in #37 that claim decided where a module lived. `allure.py`
stayed at the top level because its head said netctl and infractl reused it; neither did, and once
that was measured the module moved. The same defect put infractl.yaml into #47's zero-violations bar,
where it stood for a manifest this kernel never sees.

So: the truth about a consumer lives in another repository, the copy lives in a comment, and nothing
compares them - #46's second-source problem at a new place. The cheap half of the fix is not to keep
the copy: heads point HERE instead of reciting a list. What is left here is one datum with the date it
was taken on, and `test_surface.py` holds the kernel's own prose to it.

THE TOMBSTONES HAD A DEADLINE, IT WAS TRACKED HERE (#50), AND IT HELD. `MOVED` promised that the four
old paths came out at the next minor. That promise was written in five places and quoted on the
website, and for a while it was written in none of them WHO would notice when it came due. That is how
a transition period turns into a permanent one: not by a decision, but because at the next minor nobody
thought of it, and then it lasts one more, and one more.

IT CAME DUE AT 0.5.0 AND THE MECHANISM DID ITS JOB, which is worth recording because a gate that has
never fired is a claim rather than a guarantee. `test_surface.py` went red on the release run, after
the tag and before the publish, exactly where `MOVED_DUE_AFTER` said it would - so v0.5.0 was cut,
published nothing, and the period ended in the same afternoon instead of quietly lasting a fifth
release. It cost one tag its publish. That was the design.

WHAT THE REMOVAL ACTUALLY TOOK, since the instruction this docstring used to carry named the files
first and the measurement last, and the measurement was the half that mattered. The record said six
import lines in three repositories; re-measured on the day, it was three lines in ONE, and none of them
a consumer this period ever protected - see `MOVED_CONSUMERS`. Two of the recorded lines had never been
simplon's at all. A count taken once decays, and this one decayed inside a day.

The three records below stay, empty, for the next move: `MOVED` (what is promised), `MOVED_CONSUMERS`
(who still uses the old path, measured down to the line) and `MOVED_DUE_AFTER` (the release the promise
names). `moved_attr` stays with them. Re-measure FIRST when the next deadline comes: the acceptance is
that no consumer still imports an old path, measured on the day, not remembered from the day the
tombstone was written.
"""
from __future__ import annotations

import warnings
from importlib import import_module
from typing import Any

#: The products that install this kernel and import it as ordinary Python. MEASURED, and the method
#: matters because the previous list was not: on 2026-09-06 (#51) every repository this account can read
#: was fetched and searched for `from simplon ...` / `import simplon ...`, rather than for the phrase
#: "simplon", which is what the earlier count did and why it missed one. The kernel's own
#: `deploy/orchestrator/` is a consumer too and is deliberately NOT in this tuple - it is in this
#: repository, so no measurement of another repository can go stale about it.
#:
#: This is a snapshot and it ages. What it is good for is not proving who consumes the kernel tomorrow,
#: but keeping the kernel's prose from inventing somebody today; that much a test can hold without a
#: network (`test_surface.py`).
CONSUMERS = ("agile-cockpit", "asbundle", "biz-cockpit", "cleon", "netctl")

#: Repositories in the same family that do NOT install this kernel, with the measurement that says so.
#: They are here because naming one as a consumer is the defect #51 exists for, and this is what lets a
#: test catch it: no kernel source, README or site page outside THIS module may name one of these. That
#: is an assurance with no network in it, and it is deliberately the smaller half of the problem - it
#: cannot tell whether the measurement above is still current, only that the prose does not contradict
#: the last one taken. The larger half stays care rather than assurance: a test that asks four other
#: repositories what they import would hang on the network and on access rights.
NOT_CONSUMERS = {
    "infractl": "measured 2026-09-06 (#51) over the GitHub API: zero occurrences of `simplon` in the "
                "whole repository - it still hangs on the old `lib/platform` submodule, not on the "
                "PyPI kernel. Five kernel module heads named it as a consumer anyway.",
}

#: Modules a product may import. Promised: a rename or a signature change here is a breaking change and
#: gets a tombstone in `MOVED` plus a release note. Who the consumers are is `CONSUMERS` above, measured
#: rather than recited here; the modules with no consumer yet are library by INTENT - each says so in its
#: own head and names no product.
LIBRARY = frozenset({
    "awake", "backend", "checksum", "clablifecycle", "clabrender", "cli", "completiongen", "compose",
    "context",
    "credentials", "degraded", "disk", "docker", "environments", "fetch", "filelock",
    "githubpackages", "healthgate", "host", "hostpath",
    "imagenames", "interact", "labegress", "labhost", "labinstance", "labnet", "linux", "log",
    "nexusproxy", "portainer", "ports", "pyvenv", "run", "surface", "taskgen", "topology", "tracker",
    "verdict", "waits", "workflowgen",
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

#: Old import path -> where it lives now. EMPTY SINCE 0.5.0, and empty is the finished state rather
#: than an unused feature: four modules (`allure`, `images`, `nexus`, `vcs`) stood here as tombstones
#: through 0.4.x and came out on the deadline `MOVED_DUE_AFTER` names. `moved_attr` below is what they
#: delegated to and stays for the next move; `test_surface.py` exercises it against a synthetic pair, so
#: it cannot rot between moves.
#:
#: WHAT ENDING THE PERIOD ACTUALLY COST, because the record said one thing and the day said another. The
#: measurement below recorded six import lines in three repositories; re-measured on the day, it was
#: three lines in ONE. Two were never simplon's - asbundle reads `from delivery import images`, a
#: different kernel with the same module name - and biz-cockpit had already migrated. That is why the
#: removal instruction says re-measure FIRST: a count taken once decays, and this one decayed in a day.
MOVED: dict[str, str] = {}

#: Who still imports each old path, and from which line. EMPTY SINCE 0.5.0, with the tombstones it
#: recorded. Re-measured on 2026-09-07 before the removal, and the finding is worth keeping even though
#: the record is now empty: netctl still reads `simplon.images` and `simplon.nexus` at three lines, and
#: it is NOT a consumer the tombstones ever protected. It pins `simplon==0.3.0`, where those two are the
#: real modules and `imagenames`/`nexusproxy` do not exist yet. A grace period only reaches a product
#: that runs the release carrying it; netctl skipped 0.4.x entirely, so its migration is part of
#: whatever upgrade takes it past 0.3.0, not of this removal.
MOVED_CONSUMERS: dict[str, tuple[str, ...]] = {}

#: The last release the tombstones were promised to survive: 0.4.0, the one that introduced them. "The
#: next minor" is what the warning said, and a moving phrase cannot be checked - this is the same
#: sentence as a pair of numbers, so a test could read it. It DID: the gate went red on 0.5.0's release
#: run, cost that tag its publish, and is the only reason the period ended on time.
#:
#: WHEN IT FIRES, stated exactly, because the timing is the whole value and it is not the timing anybody
#: would assume. setuptools-scm is on `no-guess-dev`, so every commit after v0.4.0 calls itself
#: `0.4.0.postN.devM` - the minor does not move until a `v0.5.0` tag exists. The test therefore goes red
#: on the RELEASE RUN of the next minor, not before: `.github/workflows/release.yml` runs `test all`
#: after the tag and before the publish, so the tag is cut and nothing is published. That is the LAST
#: moment, deliberately, and it is loud; the FIRST moment is `docs/site/content/how/releasing.md`,
#: which
#: tells whoever is about to type a minor to look here.
MOVED_DUE_AFTER = (0, 4)


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
