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
suite's outcome is meant to find it. `simplon.domain.catalogue` has no consumer either and is machinery. The
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
    "domain.artifactsection", "domain.carrierspec", "domain.context", "domain.deployment",
    "domain.environments", "domain.layout", "domain.manifest",
    # si#400 4d: netctl's tests read a loaded manifest's commands, which are these objects.
    "domain.command", "domain.outputs", "domain.treeform",
    # si#344 C.3: a GENERATED product module imports it, to hold a command's test results.
    "domain.results",
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
#: `artifactschema` (si#344 B2) is GENERATED by firn and rewritten whole on every `build model`; a product
#: reaches what it says through `artifactsection` (LIBRARY), never by importing the generated module, so a
#: regeneration can never break a product's import.
#: `yamlkeys` (si#344 B2) is the loader both manifest seams parse with; a product reads its manifest
#: through `context.manifest_data`, which uses it, and has no reason to import it.
#: `provenance` and `runhost` (si#391) are the kernel's side of two seams the cli used to be reached for
#: across: which simplon is answering, and what the layers above tell a run. `cli.main` registers the host;
#: a product has no reason to import either.
#: `task` (si#400 4b) is the base of the task classes firn generates; nothing runs them before 4c, and a
#: product's own classes (spec step 5) are where it moves to LIBRARY - promised then, not before.
INTERNAL = frozenset({
    "adapters.diskguard", "adapters.oras", "adapters.tools", "cli.bootstrap", "domain.artifactschema",
    "domain.catalogue", "domain.clitaxonomy", "domain.launcherenv", "domain.manifestmodel", "domain.ports", "domain.runners",
    "domain.signatures", "domain.task", "domain.yamlkeys", "kernel.moved", "kernel.provenance", "kernel.runhost", "kernel.steplog", "test_impls",
})

#: si#399 moved every module into the package of its component. Where each old path now lives, the alias
#: that keeps it importable, the wording it announces itself with and the release that removes it are in
#: `simplon.kernel.moved`, because `simplon/__init__.py` installs that alias and must not import the
#: command line to do it. They are named here too, because this is where a releaser is sent to look.
#:
#: THE 0.4 TOMBSTONES ARE NOT THE MECHANISM ANY MORE. They were modules of their own serving attributes
#: through `__getattr__`, and `moved_attr` stood here for them. A product that patches by string -
#: thirteen sites do, `patch("simplon.orchestrator.steps.run_stream")` - would have patched the stub and
#: left the real function in place, a green test that tests nothing. The alias answers an old path with the
#: same module object instead, so `moved_attr` went: a second mechanism nothing calls cannot be kept honest.
MOVED = moved.MOVED
MOVED_DUE_AFTER = moved.MOVED_DUE_AFTER
moved_message = moved.moved_message

#: Who still imports each old path, and from which line. MEASURED on 2026-10-13 for si#399: the default
#: branch of each repository in `CONSUMERS` was cloned and every `.py` file parsed for an import of an old
#: path, or a string naming one (`patch("simplon.run.run")`). An old path no line imports has an EMPTY
#: tuple, which is an answer ("nobody") rather than a gap - 29 of the 65 have one.
#:
#: This is the record the removal is costed against, and it ages: re-measure on the day `MOVED_DUE_AFTER`
#: comes due rather than trusting it - the last record of this kind had decayed inside a day.
MOVED_CONSUMERS: dict[str, tuple[str, ...]] = {
    "artifactschema": (),
    "artifactsection": (),
    "awake": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:573",
    ),
    "backend": (
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/cli.py:28",
        "biz-cockpit deploy/provision/orchestrator/test/unit/test_portainer_objects.py:17",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/backends.py:29",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_backends.py:10",
    ),
    "bootstrap": (),
    "carrierspec": (),
    "catalogue": (),
    "checksum": (),
    "clablifecycle": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:31",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_lab_down.py:20",
    ),
    "clabrender": (
        "netctl deploy/provision/labgen/src/python/labgen/generate.py:40",
        "netctl deploy/provision/labgen/test/unit/python/test_generate_manifest.py:14",
        "netctl deploy/provision/labgen/test/unit/python/test_sidecar_mtls_wiring.py:15",
    ),
    "clitaxonomy": (),
    "completiongen": (),
    "compose": (
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/cli.py:29",
        "biz-cockpit deploy/provision/orchestrator/test/unit/test_deployment_files.py:16",
        "biz-cockpit deploy/provision/orchestrator/test/unit/test_stack.py:18",
    ),
    "context": (
        "agile-cockpit deploy/orchestrator/src/python/orchestrator/paths.py:14",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/config.py:13",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/container.py:19",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/paths.py:14",
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/paths.py:14",
        "cleon deploy/provision/orchestrator/src/python/orchestrator/paths.py:14",
        "firn deploy/provision/orchestrator/src/python/orchestrator/paths.py:15",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/environments.py:15",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/paths.py:20",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:24",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_environments.py:105",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_environments.py:115",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_environments.py:125",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_environments.py:68",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_environments.py:85",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_iol_image_build.py:11",
        "secure-windows-images deploy/provision/orchestrator/src/python/orchestrator/paths.py:14",
        "secure-windows-images deploy/provision/orchestrator/src/python/packer/manifest.py:50",
    ),
    "credentials": (
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/artifacts.py:29",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/cli.py:26",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/eclipse.py:21",
    ),
    "degraded": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/devicegate.py:40",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/guard.py:26",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:28",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:24",
        "netctl deploy/provision/orchestrator/test/unit/python/conftest.py:150",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_container_capability_guards.py:17",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_guard.py:11",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_lab_up_preflight.py:285",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_degraded_file.py:15",
    ),
    "deployment": (
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/backends.py:26",
        "biz-cockpit deploy/provision/orchestrator/test/unit/test_environments.py:89",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/backends.py:33",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_backends.py:11",
    ),
    "devcontainer": (),
    "disk": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/guard.py:55",
    ),
    "diskguard": (),
    "docker": (
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/container.py:20",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:178",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:152",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_lab_up_preflight.py:244",
    ),
    "environments": (
        "agile-cockpit deploy/orchestrator/src/python/orchestrator/environments.py:16",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/environments.py:16",
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/backends.py:23",
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/environments.py:38",
        "biz-cockpit deploy/provision/orchestrator/test/unit/test_compose_parity.py:26",
        "biz-cockpit deploy/provision/orchestrator/test/unit/test_portainer_objects.py:18",
        "biz-cockpit deploy/provision/orchestrator/test/unit/test_stack_variables.py:35",
        "cleon deploy/provision/orchestrator/src/python/orchestrator/environments.py:16",
        "firn deploy/provision/orchestrator/src/python/orchestrator/environments.py:18",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/backends.py:30",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/environments.py:17",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_backends.py:12",
        "secure-windows-images deploy/provision/orchestrator/src/python/orchestrator/environments.py:16",
    ),
    "fetch": (
        "secure-windows-images deploy/provision/orchestrator/src/python/packer/media.py:23",
    ),
    "filelock": (),
    "githubpackages": (
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/config.py:15",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/release.py:15",
        "cleon deploy/provision/orchestrator/src/python/orchestrator/cli.py:28",
    ),
    "healthgate": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:31",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/uphealth.py:34",
    ),
    "host": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/cli.py:24",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/clientops.py:18",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/devicegate.py:38",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/doctor.py:10",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/guard.py:31",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/hostsetup.py:16",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/iolrecover.py:21",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:32",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/rescue.py:17",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/status.py:14",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/steps.py:16",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:28",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_lab_down.py:19",
    ),
    "hostpath": (),
    "imagenames": (
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/cli.py:29",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:32",
    ),
    "interact": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/cli.py:23",
    ),
    "labegress": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:31",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_lab_egress_manifest.py:14",
    ),
    "labhost": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/guard.py:27",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/hostsetup.py:15",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:31",
    ),
    "labinstance": (
        "netctl deploy/provision/labgen/src/python/labgen/generate.py:40",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/cli.py:23",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/guard.py:27",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/paths.py:20",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_instance_cli_option.py:25",
    ),
    "labnet": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/labnet.py:10",
    ),
    "layout": (),
    "linux": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/modules.py:19",
    ),
    "log": (
        "agile-cockpit deploy/orchestrator/src/python/orchestrator/cli.py:25",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/logshim.py:16",
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/cli.py:29",
        "cleon deploy/provision/orchestrator/src/python/orchestrator/cli.py:30",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/backends.py:28",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/check.py:10",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/cli.py:23",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/clientops.py:17",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/clusterhealth.py:22",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/devicegate.py:37",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/environments.py:16",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/guard.py:30",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/hostsetup.py:15",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/iolrecover.py:20",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:31",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/rescue.py:16",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/status.py:13",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:27",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/uphealth.py:33",
    ),
    "manifestmodel": (),
    "nexusproxy": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/guard.py:55",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_nexus_manifest.py:20",
    ),
    "oras": (),
    "orchestrator.manifest": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/steps.py:12",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_cli_wiring.py:7",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_manifest_flag_agreement.py:27",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_manifest_parity.py:10",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_rescue.py:9",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_suites_taxonomy.py:17",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_taxonomy.py:6",
        "secure-windows-images tests/unit/test_the_suites_wiring.py:20",
    ),
    "orchestrator.model.treeform": (),
    "orchestrator.plan": (),
    "orchestrator.product": (
        "agile-cockpit deploy/orchestrator/src/python/orchestrator/cli.py:27",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/cli.py:27",
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/cli.py:30",
        "cleon deploy/provision/orchestrator/src/python/orchestrator/cli.py:32",
        "firn deploy/provision/orchestrator/src/python/orchestrator/cli.py:33",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/cli.py:22",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/steps.py:13",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:1926",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_backends.py:87",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_cli_wiring.py:145",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:13",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:33",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:35",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:63",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:64",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:80",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:81",
        "secure-windows-images deploy/provision/orchestrator/src/python/orchestrator/cli.py:26",
    ),
    "orchestrator.steps": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/cli.py:808",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/doctor.py:11",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/steps.py:11",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:1333",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_composite_manifest_labels.py:123",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_steps.py:12",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:115",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:14",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:62",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_up_aggregate.py:78",
        "secure-windows-images deploy/provision/orchestrator/src/python/packer/pipeline.py:65",
    ),
    "orchestrator.tui": (),
    "outputs": (),
    "portainer": (
        "biz-cockpit deploy/provision/orchestrator/test/unit/test_portainer_objects.py:120",
    ),
    "ports": (
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/cli.py:29",
    ),
    "provenance": (),
    "pyvenv": (
        "netctl deploy/provision/orchestrator/src/python/orchestrator/cli.py:571",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:617",
    ),
    "run": (
        "agile-cockpit deploy/orchestrator/src/python/orchestrator/cli.py:26",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/config.py:16",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/container.py:22",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/eclipse.py:22",
        "asbundle deploy/provision/orchestrator/src/python/orchestrator/release.py:16",
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/cli.py:32",
        "cleon deploy/provision/orchestrator/src/python/orchestrator/cli.py:31",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/check.py:11",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/cli.py:26",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/clientops.py:20",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/clusterhealth.py:23",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/guard.py:38",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/hostsetup.py:17",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/iolsource.py:22",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:34",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/status.py:16",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/steps.py:17",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/tooling.py:33",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_clientops.py:10",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_container_capability_guards.py:18",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_guard.py:10",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_hostsetup.py:9",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_iolsource.py:12",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_lab_down.py:21",
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_tooling.py:6",
    ),
    "runhost": (),
    "runners": (),
    "signatures": (),
    "steplog": (),
    "surface": (),
    "taskgen": (
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_generated_cli.py:30",
    ),
    "tools": (),
    "topology": (
        "netctl deploy/provision/labgen/src/python/labgen/generate.py:40",
        "netctl deploy/provision/labgen/test/unit/python/test_generate_manifest.py:14",
        "netctl deploy/provision/labgen/test/unit/python/test_topology_manifest.py:14",
    ),
    "tracker": (),
    "verdict": (
        "netctl deploy/provision/orchestrator/test/unit/python/orchestrator/test_suites_taxonomy.py:16",
    ),
    "waits": (
        "biz-cockpit deploy/provision/orchestrator/src/python/orchestrator/cli.py:29",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:635",
        "netctl deploy/provision/orchestrator/src/python/orchestrator/lab.py:725",
    ),
    "workflowgen": (),
    "yamlkeys": (),
}
