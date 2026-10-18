"""The kernel's two public surfaces, and the tombstones left where a module moved (#37).

`simplon.cli.surface` is a declaration, not a derivation - a promise is about tomorrow, so no import graph
can produce it. What these tests do is hold the declaration to the tree: every module is
classified, every classification names something real, and every tombstone still serves the names it
used to serve while saying where they went.

The last one is the assertion that matters, and it is the one that would otherwise never fail. A module
that moved silently still imports on the day it moves - the failure arrives weeks later, in somebody
else's repository, as an ImportError with no forwarding address.
"""
import importlib
import re
import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

import simplon
from simplon.kernel import log, moved
from simplon.cli import surface

import sitepages
from conftest import ROOT

SRC = ROOT / "src" / "simplon"

#: Not modules of the package's surface in either direction: the dunder file and the build output.
NOT_CLASSIFIED = {"__init__", "_version"}


def _top_level_names() -> set[str]:
    """Every module a product could import, read off the directory, as its path below `simplon`.

    Since si#399 the modules sit in one package per component, so the unit is the dotted path
    (`kernel.run`), not the file name beside `cli.py`. A component package's own `__init__` is a marker
    and is not a module of either surface - except `cli`, whose `__init__` IS the command line. Under
    `tasks/` the package is the unit, as before (`PACKAGES`): a module there is placed by the catalogue,
    unless the declaration names it on its own.

    The subpackages were the half the first version of this missed, and missing them was not a rounding
    error: a version that globbed `*.py` at the top called the declaration complete while the two biggest
    names in it were classified by nobody.
    """
    named = set(surface.LIBRARY | surface.INTERNAL)
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        parts = path.relative_to(SRC).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
            if parts != ("cli",):
                continue
        dotted = ".".join(parts)
        if dotted in NOT_CLASSIFIED or (parts[0] in surface.PACKAGES and dotted not in named):
            continue
        found.add(dotted)
    return found | {d.name for d in SRC.iterdir() if d.name in surface.PACKAGES}


def _declared() -> set[str]:
    """Every name the declaration places, whichever set it places it in."""
    return set(surface.LIBRARY | surface.INTERNAL | surface.PACKAGES)


# --- the declaration against the tree ---------------------------------------------------------------


def test_every_top_level_module_is_classified():
    """The point of the whole module: a new module cannot appear in the kernel without somebody saying
    which surface it is on. This is the test that makes the declaration a decision rather than a note -
    add a module and this goes red until it is placed."""
    # act
    unplaced = _top_level_names() - _declared()

    # assert
    assert not unplaced, (
        f"{sorted(unplaced)} are importable as simplon.<name> and are in none of "
        f"surface.LIBRARY / PACKAGES / INTERNAL / MOVED - decide whether a product may import them")


def test_the_declaration_names_nothing_that_has_gone():
    """The other direction: a module deleted or moved without touching the declaration leaves a promise
    pointing at nothing, which is worse than no promise at all."""
    # act
    phantom = _declared() - _top_level_names()

    # assert
    assert not phantom, f"surface declares {sorted(phantom)}, which are not importable as simplon.<name>"


def test_the_three_sets_do_not_overlap():
    """A module is on one surface. `library and also internal` is not a state anybody can act on."""
    # arrange / act
    sets = {"LIBRARY": set(surface.LIBRARY), "INTERNAL": set(surface.INTERNAL),
            "PACKAGES": set(surface.PACKAGES), "MOVED": set(surface.MOVED)}
    pairs = [(f"{a}/{b}", sets[a] & sets[b])
             for i, a in enumerate(sorted(sets)) for b in sorted(sets)[i + 1:]]

    # assert
    for names, overlap in pairs:
        assert not overlap, f"{sorted(overlap)} is in both halves of {names}"


def test_every_promised_name_imports():
    """A promised module or subpackage that does not import is a promise broken at the first line."""
    for name in sorted(surface.LIBRARY | surface.PACKAGES):
        importlib.import_module(f"simplon.{name}")


def test_no_module_is_promised_under_a_task_body_s_name():
    """The collision this ticket exists for. A top-level module sharing a name with a task body is the
    shape the #31 review lost time to - `simplon.images` against `simplon.tasks.image`. The library
    surface is the half that may not collide, because it is the half a product types."""
    # arrange: compare the two sides on a NORMALISED spelling, in both directions. An earlier version
    # only added the plural of each body, so a body named `hosts` against the library's `host` - the
    # mirror image of the original defect - went green. Normalising instead of expanding one side
    # cannot be one-sided.
    def singular(name: str) -> str:
        return name[:-1] if name.endswith("s") and not name.endswith("ss") else name

    # si#399 put `taskgen`, `completiongen` and `workflowgen` under tasks/ as library modules; a module is
    # no collision with itself, so the bodies are the modules there the declaration does not promise.
    promised = {m for m in surface.LIBRARY if m.startswith("tasks.")}
    bodies = {p.stem for p in (SRC / "tasks").glob("*.py")} - {"__init__"} - {m[len("tasks."):] for m in promised}
    by_body = {singular(b): b for b in bodies}

    # act
    collisions = {f"simplon.{m} / simplon.tasks.{by_body[singular(m.rpartition('.')[2])]}"
                  for m in surface.LIBRARY - promised if singular(m.rpartition(".")[2]) in by_body}

    # assert
    assert not collisions, (
        f"{sorted(collisions)} name the same thing on two levels - one of each pair has to be "
        f"renamed, because nothing at the call site says which is which")


# --- the alias, with no move standing (si#399, si#470) ---------------------------------------------------
#
# The 0.4 tombstones were stub modules, and `moved_attr` served their attributes. si#399 replaced both with
# an alias in `simplon.kernel.moved`: an old path is the SAME module object as its new one. si#470 emptied
# `MOVED` on its deadline, so nothing in the tree reaches the alias any more - and a mechanism nothing
# reaches is one that rots between moves. These hold it against a SYNTHETIC move instead: `simplon.gone` is a
# dissolved package and `simplon.gone.steps` an old path to `simplon.kernel.steps`, and no old module has to
# exist for either.

#: The synthetic move. Its names are chosen so no real module can ever stand at them.
SYNTHETIC_MOVED = {"gone.steps": "simplon.kernel.steps", "gonelog": "simplon.kernel.log"}
SYNTHETIC_DISSOLVED = frozenset({"gone"})


@pytest.fixture
def synthetic_move(monkeypatch):
    """Stand the synthetic move up for one test, and take every trace of it down again: the import system
    leaves the aliases in `sys.modules` and binds each as an attribute of its parent package."""
    from simplon.kernel import moved

    monkeypatch.setattr(moved, "MOVED", dict(SYNTHETIC_MOVED))
    monkeypatch.setattr(moved, "DISSOLVED", SYNTHETIC_DISSOLVED)
    yield SYNTHETIC_MOVED
    for old in [*SYNTHETIC_MOVED, *SYNTHETIC_DISSOLVED]:
        sys.modules.pop(f"simplon.{old}", None)
    for top in {old.split(".")[0] for old in [*SYNTHETIC_MOVED, *SYNTHETIC_DISSOLVED]}:
        if hasattr(simplon, top):
            delattr(simplon, top)


@pytest.mark.parametrize("old, new", sorted(SYNTHETIC_MOVED.items()))
def test_an_old_path_is_the_very_module_at_its_new_home(synthetic_move, old, new):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        aliased = importlib.import_module(f"simplon.{old}")

    assert aliased is importlib.import_module(new)
    assert aliased.__spec__.name == new, "the alias rewrote where the module says it lives"


def test_a_patch_through_an_old_path_patches_the_code_that_runs(synthetic_move):
    """THE DEFECT THE ALIAS WAS CHOSEN FOR. Thirteen product sites patched by string. On a stub module the
    patch would land on the stub, the real `run_stream` would run, and the product's test would stay green
    testing nothing. Seen red by having the alias hand back a copy of the module instead of the module
    itself."""
    from unittest import mock

    from simplon.kernel import steps

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        with mock.patch("simplon.gone.steps.run_stream") as patched:
            assert steps.run_stream is patched


def test_a_dissolved_package_still_reaches_its_children(synthetic_move):
    """`from simplon.orchestrator import product` was the line every scaffolded product carried."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        from simplon.gone import steps

    from simplon.kernel import steps as new_steps
    assert steps is new_steps


def test_importing_an_old_path_says_where_it_went_at_the_line_that_imported(tmp_path):
    """A fresh interpreter, because an alias warns once per process: the first import of the old name.
    The warning has to point at the product's line, not at importlib - a FutureWarning attributed to
    `<frozen importlib._bootstrap>` tells the reader nothing they can change. The move is the synthetic
    one, stood up in the child before the line that imports."""
    script = tmp_path / "product.py"
    script.write_text("from simplon.kernel import moved\n"
                      f"moved.MOVED.update({SYNTHETIC_MOVED!r})\n"
                      f"moved.DISSOLVED = {SYNTHETIC_DISSOLVED!r}\n"
                      "from simplon.gone import steps\n", encoding="utf-8")

    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                            env={**os.environ, "PYTHONWARNINGS": "default"})

    assert result.returncode == 0, result.stderr
    assert f"{script}:4: FutureWarning: " + surface.moved_message(
        "simplon.gone.steps", "simplon.kernel.steps") in result.stderr, result.stderr


#: si#399's old paths, a sample spanning both shapes: a module that moved, a child of a dissolved package,
#: the dissolved package itself - and, since si#473, `domain`'s and the renamed `tasks.tasks`.
SI399_GONE = ("orchestrator", "orchestrator.model", "orchestrator.steps", "orchestrator.product", "run", "log",
              "context", "surface", "docker", "domain", "domain.context", "domain.manifest", "domain.task",
              "tasks.tasks")

#: `domain`'s split (si#473) as it stood in `moved.GONE` until 0.34.0, frozen here: the split never had an
#: alias window, so the website's table is the whole migration for a product, and it must stay complete
#: after the tombstones went (si#485).
DOMAIN_SPLIT = (
    ('domain.artifactschema', 'simplon.model.artifactschema'),
    ('domain.artifactsection', 'simplon.manifest.artifactsection'),
    ('domain.carrierspec', 'simplon.model.carrierspec'),
    ('domain.catalogue', 'simplon.manifest.catalogue'),
    ('domain.clitaxonomy', 'simplon.manifest.clitaxonomy'),
    ('domain.command', 'simplon.model.command'),
    ('domain.context', 'simplon.manifest.context'),
    ('domain.deployment', 'simplon.manifest.deployment'),
    ('domain.environments', 'simplon.manifest.environments'),
    ('domain.layout', 'simplon.manifest.layout'),
    ('domain.manifest', 'simplon.manifest.load'),
    ('domain.manifestmodel', 'simplon.manifest.manifestmodel'),
    ('domain.outputs', 'simplon.manifest.outputs'),
    ('domain.ports', 'simplon.manifest.ports'),
    ('domain.results', 'simplon.manifest.results'),
    ('domain.runners', 'simplon.manifest.runners'),
    ('domain.signatures', 'simplon.manifest.signatures'),
    ('domain.task', 'simplon.model.task'),
    ('domain.treeform', 'simplon.manifest.treeform'),
    ('domain.yamlkeys', 'simplon.manifest.yamlkeys'),
)


@pytest.mark.parametrize("old", SI399_GONE)
def test_an_old_path_is_a_plain_miss_since_the_tombstones_went(old):
    """si#470 removed si#399's aliases for 0.33.0; si#473's tombstones named the new home through 0.33;
    si#485 removed them for 0.34.0. An old path is now what any unknown name is - a `ModuleNotFoundError`
    naming it - and nothing answers it, quietly or loudly. Seen red with `GONE` still filled: the message
    named the new home."""
    with pytest.raises(ModuleNotFoundError) as caught:
        importlib.import_module(f"simplon.{old}")

    assert caught.value.name is not None and caught.value.name.startswith("simplon."), caught.value
    assert not isinstance(caught.value, moved.GoneError), caught.value


@pytest.mark.parametrize("old", ["run", "log", "context", "domain", "orchestrator"])
def test_from_simplon_import_an_old_module_is_a_plain_import_error(old):
    """`from simplon import run`, the spelling most products used: Python's own "cannot import name" now,
    since `simplon.__getattr__` has no tombstone left to raise."""
    with pytest.raises(ImportError) as caught:
        exec(f"from simplon import {old}", {})

    assert not isinstance(caught.value, moved.GoneError), caught.value


def test_the_tombstone_mechanism_still_names_a_new_home(monkeypatch):
    """The tables are empty, the mechanism is not: the next removal fills `GONE` and nothing else (as si#470
    left `MOVED`). Held on a synthetic pair, through both doors - the finder and `simplon.__getattr__`."""
    monkeypatch.setitem(moved.GONE, "gonetest", "simplon.kernel.steps")
    for name in [n for n in sys.modules if n == "simplon.gonetest"]:
        monkeypatch.delitem(sys.modules, name)

    with pytest.raises(ModuleNotFoundError, match=re.escape(moved.gone_message("simplon.gonetest"))):
        importlib.import_module("simplon.gonetest")
    with pytest.raises(ModuleNotFoundError, match=re.escape(moved.gone_message("simplon.gonetest"))):
        exec("from simplon import gonetest", {})


def test_no_tombstone_shadows_a_module_that_exists():
    """The finder sits first on `sys.meta_path`, so a tombstone named like a real module would make that
    module unimportable - `simplon.manifest` is one such name, and it is a package now (si#473)."""
    real = {".".join(p.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__")
            for p in SRC.rglob("*.py")}
    assert not (set(moved.GONE) | moved.GONE_PACKAGES) & real
    assert all(any(child.startswith(package + ".") for child in moved.GONE) for package in moved.GONE_PACKAGES)


def test_a_name_that_never_existed_is_still_not_found():
    """The alias answers the old paths and only them; anything else stays a ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("simplon.nosuchmodule")


def test_the_innards_under_tasks_are_exactly_the_modules_no_coordinate_names():
    """The claim the website makes about `simplon/tasks/`, derived rather than restated.

    The tempting phrasing - "a product may not import a task body" - is FALSE, and the kernel is what
    made it false: five consumers import one, and the generated CLI (`templates/cli.py.j2`, ours)
    emits twelve such imports. The line that does hold is named versus unnamed: a module some
    catalogue coordinate points its body at is reachable; one no coordinate names is innards.

    This derives both sides from the catalogue's model so the page cannot drift away from the catalogue.
    """
    # arrange
    # the body each coordinate names - since si#400 4c in the model (`BODIES`), no longer in catalogue.yaml
    from simplon.model.artifactschema import BODIES
    named = {body.split(":")[0][len("simplon.tasks."):] for body in BODIES.values()
             if body.startswith("simplon.tasks.")}
    # si#400 4b: a generated task class is its coordinate's own class (its KEY names it), not innards
    generated = {p.stem for p in (SRC / "tasks").glob("*.py") if "id=[Tasks:" in p.read_text(encoding="utf-8")}
    assert generated, "no generated task class found - the exclusion below would exclude nothing"
    present = ({p.stem for p in (SRC / "tasks").glob("*.py")} - {"__init__"} - generated
               - {m[len("tasks."):] for m in surface.LIBRARY if m.startswith("tasks.")})

    # act
    innards = present - named

    # assert: every module the catalogue names is really there, and the innards are exactly these
    assert named <= present, f"the catalogue names {sorted(named - present)}, which is not in tasks/"
    assert innards == {"allure", "gitops", "handoff", "profiles", "proxmoxapi"}, (
        f"the innards of simplon/tasks/ are now {sorted(innards)}; the website names allure, gitops, "
        f"handoff, profiles and proxmoxapi, and one of the two has to change - the page FIRST, then this list")


# --- the tombstones have a deadline, and something has to notice it (#50) --------------------------


def _release_number() -> tuple[int, int]:
    """The (major, minor) of the version this checkout would publish as.

    Read off `simplon.__version__`, which setuptools-scm derives from the tag. Between releases it is
    `0.4.0.postN.devM` under `no-guess-dev`, so the pair below does not move until the next tag exists -
    which is exactly what makes it usable as a due date rather than as a nuisance on every commit.

    An unparseable version answers (0, 0) rather than raising. The fallback in `simplon/__init__.py` is
    `0.0.0.dev0+unknown`, reached when the package is neither built nor installed; a checkout in that
    state knows nothing about releases, and inventing a due date from it would fail a suite for a reason
    that has nothing to do with tombstones.
    """
    found = re.match(r"(\d+)\.(\d+)", simplon.__version__)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def test_every_tombstone_records_who_still_uses_the_old_path():
    """The promise had a deadline and no owner (#50), and the missing half was never the date - it was
    who pays for it. A tombstone with no record beside it is a removal nobody can cost, so the next
    minor arrives, nobody knows whether it is safe, and the safe move is always to wait one more.

    An EMPTY tuple is an answer here, and a valuable one: 29 of si#399's 65 moves have no consumer at all.
    What this forbids is a move appearing with nothing said about it.
    """
    # act
    unrecorded = set(surface.MOVED) - set(surface.MOVED_CONSUMERS)
    phantom = set(surface.MOVED_CONSUMERS) - set(surface.MOVED)

    # assert
    assert not unrecorded, (
        f"{sorted(unrecorded)} is a tombstone with no entry in surface.MOVED_CONSUMERS - say who "
        f"still imports the old path, measured, or say that nobody does with an empty tuple")
    assert not phantom, (
        f"surface.MOVED_CONSUMERS records {sorted(phantom)}, which is not a tombstone any more")


@pytest.mark.parametrize("old", sorted(surface.MOVED_CONSUMERS))
def test_a_recorded_consumer_line_names_a_repository_a_file_and_a_line(old):
    """"netctl uses it" is the shape of statement this whole pair of tickets exists to stop. What makes
    the record actionable - and what makes ending the transition a morning's work rather than a
    project - is that each entry is one line somebody can open."""
    for entry in surface.MOVED_CONSUMERS[old]:
        repository, _, location = entry.partition(" ")
        assert repository in surface.CONSUMERS, (
            f"{entry!r} names {repository!r}, which is not a measured consumer of this kernel")
        assert re.search(r"\.py:\d+$", location.strip()), (
            f"{entry!r} does not end in a file and a line number, so nobody can open it")


def test_the_tombstones_are_gone_by_the_release_they_were_promised_for():
    """THE THING THAT NOTICES, and the reason #50 was a ticket rather than a note.

    Every tombstone says it is removed at the next minor. Nothing enforced that, and a transition
    period nobody is reminded of does not end by decision - it ends by being forgotten into permanence,
    one release at a time, each of which looks like the cheap choice on its own.

    This is the last moment rather than the best one, and the difference is worth knowing before
    relying on it. `no-guess-dev` keeps the version at `0.4.0.postN` until a `v0.5.0` tag exists, so
    this cannot warn the person who is ABOUT to cut the minor - the release page does that. What it can
    do is stop the publish: `release.yml` runs `test all` after the tag and before the upload, so a
    minor that still carries tombstones costs a tag number and ships nothing. Loud, and recoverable.

    Seen red by moving `MOVED_DUE_AFTER` back a minor: it named all four modules and both files.
    Seen red again for si#470 as 0.33.0 with si#399's 65 old paths still in `MOVED`.
    """
    # arrange
    due = _release_number() > surface.MOVED_DUE_AFTER

    # assert
    assert not (due and surface.MOVED), (
        f"this is {simplon.__version__}, past {'.'.join(map(str, surface.MOVED_DUE_AFTER))}, and the "
        f"old paths {sorted(surface.MOVED)} still import - they were promised to go at this "
        f"release. Removing them is: empty simplon.kernel.moved.MOVED and DISSOLVED and "
        f"surface.MOVED_CONSUMERS, and drop the migration table and the "
        f"deadline sentence from {PAGE.relative_to(sitepages.ROOT)}. Re-measure "
        f"MOVED_CONSUMERS first - "
        f"the record says {sum(len(v) for v in surface.MOVED_CONSUMERS.values())} import lines are "
        f"still out there.")


def test_the_tombstones_of_removed_paths_go_by_their_own_deadline():
    """si#473: the tombstones are a second promise with their own date - they name the new home through
    the release that removed the paths, and go after it. The same gate as the aliases': red on the release
    run of the first minor past `GONE_DUE_AFTER` while `GONE` still holds anything. Seen red by setting
    `GONE_DUE_AFTER` to (0, 31)."""
    due = _release_number() > moved.GONE_DUE_AFTER

    assert not (due and moved.GONE), (
        f"this is {simplon.__version__}, past {'.'.join(map(str, moved.GONE_DUE_AFTER))}, and "
        f"{len(moved.GONE)} tombstones still stand. Removing them is: empty simplon.kernel.moved.GONE and "
        f"GONE_PACKAGES, and drop the tombstone paragraph from {PAGE.relative_to(sitepages.ROOT)}.")


def test_the_release_page_sends_a_minor_release_to_the_record():
    """The FIRST moment, the one the version cannot reach: somebody about to type a minor. A deadline
    that is only enforced by a red publish is enforced too late to be kind, so the page a releaser
    reads has to carry it - and pointing at the record beats copying it, because a copy of a list of
    six import lines is a second source with a shelf life."""
    # arrange
    page = sitepages.chapter("releasing.md").read_text(encoding="utf-8")

    # assert: the record by name, not a retyped copy of what is in it
    for named in ("simplon.cli.surface", "MOVED_CONSUMERS", "MOVED_DUE_AFTER"):
        assert named in page, (
            f"the release page does not name {named}, so a minor release is sent nowhere and the "
            f"only thing that notices the tombstone deadline is a failed publish")


# --- the consumers a module head is allowed to name (#51) -------------------------------------------


#: Everything a reader of this kernel could mistake for a statement about who uses it: the package, the
#: front page and the site. Tests are NOT in here - a fixture may need a product name that is nobody.
def _prose_files() -> list[Path]:
    root = ROOT
    return [p for p in [*SRC.rglob("*.py"), root / "README.md", *(root / "src" / "site").rglob("*.md")]
            if p.resolve() != (SRC / "cli" / "surface.py").resolve()]


def test_no_kernel_prose_names_a_repository_measured_not_to_use_the_kernel():
    """THE ASSERTION #51 EXISTS FOR, and the whole of what can be held without a network.

    Five module heads named `infractl` as a consumer of this kernel. It installs no part of it - zero
    occurrences of the string in the whole repository - and that was not harmless prose: in #37 the
    claim decided where `allure` lived, and in #47 an `infractl.yaml` stood in the zero-violations bar
    for an expression rule, as a manifest this kernel never sees.

    What a test can do about that offline is the smaller half, and it is worth stating which half.
    It CANNOT re-measure another repository - that would hang on the network and on access rights, and
    a green run would then mean "GitHub answered" as often as "the claim holds". It CAN hold the
    kernel's own prose to the last measurement that WAS taken, which is exactly the step that was
    missing: the name went into five heads and nothing ever compared it with anything.

    `surface.py` itself is exempt, because it is where the measurement is written down; every other
    file has to point there rather than keep a copy.
    """
    # arrange
    offenders: dict[str, list[str]] = {}

    # act
    for name in surface.NOT_CONSUMERS:
        hits = [str(p) for p in _prose_files() if name in p.read_text(encoding="utf-8")]
        if hits:
            offenders[name] = hits

    # assert
    assert not offenders, (
        f"{offenders} name a repository that does not install this kernel; "
        f"surface.NOT_CONSUMERS says how that was measured, and a head that needs the fact "
        f"points there instead of repeating the name")


def test_the_two_consumer_lists_do_not_overlap():
    """A repository is measured to use the kernel or measured not to. Both at once is not a finding,
    it is two measurements that were never compared - which is the defect one level up."""
    # act
    both = set(surface.CONSUMERS) & set(surface.NOT_CONSUMERS)

    # assert
    assert not both, f"{sorted(both)} is in surface.CONSUMERS and in surface.NOT_CONSUMERS"


def test_every_measured_non_consumer_says_how_that_was_measured():
    """A bare name would be the same unchecked assertion in a new place. The value beside it is the
    measurement - what was looked at, and when - so the next reader can tell a fact from a memory."""
    for name, reason in surface.NOT_CONSUMERS.items():
        assert "measured" in reason.lower(), f"{name}: {reason!r} does not say how it was measured"
        assert re.search(r"\b20\d\d-\d\d-\d\d\b", reason), (
            f"{name}: {reason!r} carries no date, so nobody can tell how old the measurement is")


# --- the website says the same thing --------------------------------------------------------------


PAGE = sitepages.chapter("surface.md")


def test_the_website_names_the_same_internals():
    """ACCEPTANCE 1. The separation is only useful if a reader can find it, so it is on the site - and a
    list typed into prose is a second source for a string, which is the shape that rots quietly. This
    pins the page to the declaration instead of hoping somebody edits both."""
    # arrange
    page = PAGE.read_text(encoding="utf-8")

    # act
    named = {n.strip("`") for n in re.findall(r"`[a-z_.]+`(?= ·|\n)", page)}

    # assert
    assert surface.INTERNAL <= named, (
        f"{sorted(surface.INTERNAL - named)} is internal and the page does not say so: {PAGE}")


@pytest.mark.parametrize("old, new", sorted(surface.MOVED.items()))
def test_the_website_carries_every_move(old, new):
    """The migration table is what a product owner reads when their run starts warning. A move missing
    from it is a message pointing at a page that does not mention it."""
    # arrange
    page = PAGE.read_text(encoding="utf-8")

    # assert: both ends of the move, on one row of the table
    assert any(f"`simplon.{old}`" in line and f"`{new}`" in line
               for line in page.splitlines() if line.startswith("|")), (
        f"the move simplon.{old} -> {new} is in no row of the table in {PAGE}")


@pytest.mark.parametrize("old, new", DOMAIN_SPLIT)
def test_the_website_carries_every_module_of_the_domain_split(old, new):
    """si#473: the split shipped with no alias window, so the table is the whole migration for a product.
    A module missing from it is an error message pointing at a page that does not mention it."""
    page = PAGE.read_text(encoding="utf-8")

    assert any(f"`simplon.{old}`" in line and f"`{new}`" in line
               for line in page.splitlines() if line.startswith("|")), (
        f"the move simplon.{old} -> {new} is in no row of the table in {PAGE}")


def test_the_website_no_longer_promises_a_tombstone():
    """si#485: the page said the tombstones stand through 0.33 and quoted one. A quoted error text is a
    second source for a string, and this one no longer exists - the page must not show it."""
    page = PAGE.read_text(encoding="utf-8")
    assert "The old path was removed in 0.33.0." not in page
    assert "0.34.0" in page
