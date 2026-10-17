"""Which modules a product may import, and which are the kernel's own machinery (#37).

THE PROBLEM THIS SOLVES. The kernel has two public surfaces, not one. The first is the task catalogue:
a product writes `<namespace>:<name>` in its manifest and never names a module path - `catalogue.yaml`
says so in its own head, which is what lets a body move inside the kernel without breaking anybody. The
second surface is ordinary Python: a product imports `simplon.kernel.log`, `simplon.kernel.run`, `simplon.adapters.host` and
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
today, but a promise is about tomorrow. `simplon.kernel.verdict` has no consumer in any repository right now
and is still a library - it was written as one, it names no product, and the next product to read a
suite's outcome is meant to find it. `simplon.manifest.catalogue` has no consumer either and is machinery. The
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

THE SECOND PERIOD ENDED THE SAME WAY, ON TIME. si#399 moved every module into the package of its
component and kept the old paths as aliases through 0.32; si#470 removed them for 0.33.0, before the tag
rather than after it. Re-measured on the day, six of the seven consumers still imported an old path - and
not one of them was a consumer the aliases protected, because every one pins a simplon from before the
move. The lesson of 0.5.0, measured a second time: a grace period reaches only a product that runs the
release carrying it.

The three records below stay, empty, for the next move: `MOVED` (what is promised), `MOVED_CONSUMERS`
(who still uses the old path, measured down to the line) and `MOVED_DUE_AFTER` (the release the promise
names). The alias in `simplon.kernel.moved` stays with them. Re-measure FIRST when the next deadline
comes: the acceptance is that no consumer still imports an old path, measured on the day, not remembered
from the day the tombstone was written.

What 0.33.0 does leave behind is a NOTICE, not a way in (si#473): `simplon.kernel.moved.GONE` names the new
home of every si#399 path and of every module of the `domain` package si#473 split, and an import of one
fails with that home in the message. The notices have their own deadline, `GONE_DUE_AFTER`.
"""
from __future__ import annotations

from simplon.kernel import moved

#: The products that install this kernel and import it as ordinary Python. MEASURED, and the method
#: matters because the previous list was not: on 2026-09-06 (#51) every repository this account can read
#: was fetched and searched for `from simplon ...` / `import simplon ...`, rather than for the phrase
#: "simplon", which is what the earlier count did and why it missed one. The kernel's own
#: `deploy/orchestrator/` is a consumer too and is deliberately NOT in this tuple - it is in this
#: repository, so no measurement of another repository can go stale about it.
#:
#: Re-measured on 2026-10-13 for si#399 by parsing every `.py` file of every repository: firn and
#: secure-windows-images import the kernel too (5 and 11 lines), and neither was in this tuple.
#:
#: This is a snapshot and it ages. What it is good for is not proving who consumes the kernel tomorrow,
#: but keeping the kernel's prose from inventing somebody today; that much a test can hold without a
#: network (`test_surface.py`).
CONSUMERS = ("agile-cockpit", "asbundle", "biz-cockpit", "cleon", "firn", "netctl", "secure-windows-images")

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
#:
#: `artifactsection` (si#344 B2) is promised for one question, `is_a(kind, wanted)`: a product that reads an
#: `artifacts:` entry itself asks it rather than restating which kinds refine which. Its name is not
#: `artifacts` on purpose - `test_no_module_is_promised_under_a_task_body_s_name` refuses a library module
#: named like the task body `simplon.tasks.artifact`.
LIBRARY = frozenset({
    "adapters.backend", "adapters.checksum", "adapters.clablifecycle", "adapters.clabrender",
    "adapters.compose", "adapters.credentials", "adapters.devcontainer", "adapters.disk", "adapters.docker",
    "adapters.fetch", "adapters.githubpackages", "adapters.healthgate", "adapters.host", "adapters.hostpath",
    "adapters.imagenames", "adapters.interact", "adapters.labegress", "adapters.labhost",
    "adapters.labinstance", "adapters.labnet", "adapters.linux", "adapters.nexusproxy", "adapters.portainer",
    "adapters.ports", "adapters.pyvenv", "adapters.topology", "adapters.tracker", "cli", "cli.surface",
    "manifest.artifactsection", "model.carrierspec", "manifest.context", "manifest.deployment",
    "manifest.environments", "manifest.layout", "manifest.load",
    # si#400 4d: netctl's tests read a loaded manifest's commands, which are these objects.
    "model.command", "manifest.outputs", "manifest.treeform",
    # si#344 C.3: a GENERATED product module imports it, to hold a command's test results.
    "manifest.results",
    # si#473 (Marco, 2026-10-16): every task class firn generates - the kernel's and, from `tasks.firnt`,
    # a product's - imports `model.task.Task`, and each class with ports `model.artifactschema.Port`, so a
    # product's generated code bakes both paths in and both are promised. `task` is also where a product's
    # own task class (spec step 5) comes from. `artifactschema` stays GENERATED and rewritten whole by
    # `build model`: what is promised is its names (`Port` and the kinds' entry classes), not its text; a
    # product still asks `artifactsection.is_a` which kinds refine which. Promoting `task` collided with the
    # body module `simplon.tasks.tasks` under `test_no_module_is_promised_under_a_task_body_s_name`; the
    # body module gave way and is `tasks.taskverbs` (Marco, 2026-10-17).
    "model.task", "model.artifactschema",
    "kernel.awake", "kernel.degraded", "kernel.filelock", "kernel.log", "kernel.plan", "kernel.product",
    "kernel.run", "kernel.steps", "kernel.verdict", "kernel.waits", "tasks.completiongen", "tasks.taskgen",
    "tasks.workflowgen", "ui.tui",
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
PACKAGES = frozenset({"tasks"})

#: The kernel's own machinery. No product imports these, and they may change without notice.
#:
#: `bootstrap` is the one that needs a word: it carries the `simplon` console script
#: (`[project.scripts]` in pyproject.toml), so `simplon.cli.bootstrap:main` IS a promised entry point. What
#: is not promised is importing the module for its other functions, which is why it sits here.
#: `runners` is the newest, and it is INTERNAL on purpose although `workflowgen` beside it is LIBRARY
#: (si#267). It is a TABLE of facts about kinds of CI machine, and a product reaches those facts by
#: naming a kind in its manifest - never by importing the table. That is the whole point of carrying it
#: here: the kernel learns a machine once, for everybody, and is free to add a kind or correct a
#: measured field without that being a promise it broke.
#: `manifestmodel` (si#346) is the bridge to firn's M1 model; nobody outside the kernel's own tooling
#: has a reason to import it, so it is not promised.
#: `yamlkeys` (si#344 B2) is the loader both manifest seams parse with; a product reads its manifest
#: through `context.manifest_data`, which uses it, and has no reason to import it.
#: `provenance` and `runhost` (si#391) are the kernel's side of two seams the cli used to be reached for
#: across: which simplon is answering, and what the layers above tell a run. `cli.main` registers the host;
#: a product has no reason to import either.
INTERNAL = frozenset({
    "adapters.diskguard", "adapters.oras", "adapters.tools", "cli.bootstrap",
    "manifest.catalogue", "manifest.clitaxonomy", "manifest.launcherenv", "manifest.manifestmodel", "manifest.ports", "manifest.runners",
    "manifest.signatures", "manifest.yamlkeys", "kernel.moved", "kernel.provenance", "kernel.runhost", "kernel.steplog", "test_impls",
})

#: Where each old path of a move lives now, the alias that keeps it importable, the wording it announces
#: itself with and the release that removes it are in `simplon.kernel.moved`, because `simplon/__init__.py`
#: installs that alias and must not import the command line to do it. They are named here too, because
#: this is where a releaser is sent to look. `MOVED` is empty since 0.33.0: si#399's 65 old paths were
#: promised through 0.32 and came out on time (si#470).
#:
#: THE 0.4 TOMBSTONES ARE NOT THE MECHANISM ANY MORE. They were modules of their own serving attributes
#: through `__getattr__`, and `moved_attr` stood here for them. A product that patches by string -
#: thirteen sites do, `patch("simplon.orchestrator.steps.run_stream")` - would have patched the stub and
#: left the real function in place, a green test that tests nothing. The alias answers an old path with the
#: same module object instead, so `moved_attr` went: a second mechanism nothing calls cannot be kept honest.
MOVED = moved.MOVED
MOVED_DUE_AFTER = moved.MOVED_DUE_AFTER
moved_message = moved.moved_message

#: Who still imports each old path, and from which line. EMPTY SINCE 0.33.0, with the aliases it recorded.
#: si#399's record (2026-10-13) named 65 old paths; si#470 re-measured it on 2026-10-16, the day
#: `MOVED_DUE_AFTER` came due, the same way: the default branch of each repository in `CONSUMERS`, every
#: `.py` file parsed for an import of an old path or a string naming one. The finding is worth keeping
#: although the record is empty, because it is what the removal cost:
#:
#:   - firn had migrated (0 imports; firn#1015 is closed). The other six had not, and each has its open
#:     issue from 2026-10-15 listing its lines. Old paths imported (an import line naming two counts
#:     twice): netctl 124 on 110 lines plus 13 `monkeypatch.setattr` strings, biz-cockpit 20 on 16 lines,
#:     asbundle 16, secure-windows-images 7, cleon 6, agile-cockpit 5.
#:   - None of the six breaks on the day 0.33.0 is published, and none of them was ever protected by the
#:     aliases: each pins a simplon from before the move (0.3.0 to 0.22.0) in its `requirements.txt`,
#:     where the old paths are the real modules. A grace period reaches only a product that runs the
#:     release carrying it, so their migration is part of whatever bump takes them to 0.33.0 or later -
#:     exactly netctl's position at 0.5.0. firn, the one consumer on 0.32, is the one that migrated.
#:   - The per-line list and the commit each repository was measured at are in the si#470 pull request,
#:     not here: a copy of it would be the record this comment says ages.
MOVED_CONSUMERS: dict[str, tuple[str, ...]] = {}
