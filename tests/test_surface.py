"""The kernel's two public surfaces, and the tombstones left where a module moved (#37).

`simplon.surface` is a declaration, not a derivation - a promise is about tomorrow, so no import graph
can produce it. What these tests do is hold the declaration to the tree: every top-level module is
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
from simplon import log, surface

SRC = Path(__file__).resolve().parents[1] / "src" / "simplon"

#: Not modules of the package's surface in either direction: the dunder file and the build output.
NOT_CLASSIFIED = {"__init__", "_version"}


def _top_level_names() -> set[str]:
    """Every name importable as `simplon.<x>`, read off the directory - MODULES and SUBPACKAGES both.

    The subpackages are the half this originally missed, and missing them was not a rounding error:
    `simplon.orchestrator` and `simplon.tasks` are the second and third most imported things the kernel
    offers. A version of this that globbed `*.py` called the declaration complete while the two biggest
    names in it were classified by nobody, and a new subpackage beside `cli.py` passed in silence.
    """
    modules = {p.stem for p in SRC.glob("*.py")} - NOT_CLASSIFIED
    packages = {d.name for d in SRC.iterdir() if d.is_dir() and (d / "__init__.py").exists()}
    return modules | packages


def _declared() -> set[str]:
    """Every name the declaration places, whichever set it places it in."""
    return set(surface.LIBRARY | surface.INTERNAL | surface.PACKAGES) | set(surface.MOVED)


# --- the declaration against the tree ---------------------------------------------------------------


def test_every_top_level_module_is_classified():
    """The point of the whole module: a new file beside `cli.py` cannot appear without somebody saying
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

    bodies = {p.stem for p in (SRC / "tasks").glob("*.py")} - {"__init__"}
    by_body = {singular(b): b for b in bodies}

    # act
    collisions = {f"simplon.{m} / simplon.tasks.{by_body[singular(m)]}"
                  for m in surface.LIBRARY if singular(m) in by_body}

    # assert
    assert not collisions, (
        f"{sorted(collisions)} name the same thing on two levels - one of each pair has to be "
        f"renamed, because nothing at the call site says which is which")


# --- the tombstone machinery, with no tombstone standing ---------------------------------------------
#
# `MOVED` is empty since 0.5.0 and the four modules are gone, so nothing in the tree reaches `moved_attr`
# any more. The machinery stays because the next move needs it, and it is measured rather than obvious -
# FutureWarning over DeprecationWarning, and `__all__` answered rather than refused, each cost a defect
# to find. Kept untested it would rot silently, so these three exercise it against a SYNTHETIC pair
# instead of a real tombstone: `simplon.log` stands in for the new home, and no old module has to exist.


def test_a_move_is_announced_when_an_attribute_is_served_through_it():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        served = surface.moved_attr("simplon.gone", "simplon.log", "info")

    assert served is log.info
    assert [str(w.message) for w in caught] == [surface.moved_message("simplon.gone", "simplon.log")]


def test_a_dunder_probe_is_refused_rather_than_announced():
    """`inspect`, `pytest` and `importlib` probe every module they touch. Announcing a move for those
    would report a migration no product code asked for, and teach the reader to ignore the message."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(AttributeError):
            surface.moved_attr("simplon.gone", "simplon.log", "__path__")

    assert not caught, [str(w.message) for w in caught]


def test_a_star_import_gets_the_targets_own_surface_and_is_still_announced():
    """The recurring defect in miniature: refuse `__all__` and a star-import falls back to the
    tombstone's own module dict, binding the wrong names while warning about nothing."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        names = surface.moved_attr("simplon.gone", "simplon.log", "__all__")

    assert set(names) == {n for n in vars(log) if not n.startswith("_")}
    assert [str(w.message) for w in caught] == [surface.moved_message("simplon.gone", "simplon.log")]


def test_the_innards_under_tasks_are_exactly_the_modules_no_coordinate_names():
    """The claim the website makes about `simplon/tasks/`, derived rather than restated.

    The tempting phrasing - "a product may not import a task body" - is FALSE, and the kernel is what
    made it false: five consumers import one, and the generated CLI (`templates/cli.py.j2`, ours)
    emits twelve such imports. The line that does hold is named versus unnamed: a module some
    catalogue coordinate points its `impl:` at is reachable; one no coordinate names is innards.

    This derives both sides from `catalogue.yaml` so the page cannot drift away from the catalogue.
    """
    # arrange
    catalogue = (SRC / "catalogue.yaml").read_text(encoding="utf-8")
    named = set(re.findall(r"impl:\s*\"?simplon\.tasks\.([a-z_]+):", catalogue))
    present = {p.stem for p in (SRC / "tasks").glob("*.py")} - {"__init__"}

    # act
    innards = present - named

    # assert: every module the catalogue names is really there, and the innards are the two that moved
    assert named <= present, f"the catalogue names {sorted(named - present)}, which is not in tasks/"
    assert innards == {"allure", "gitops"}, (
        f"the innards of simplon/tasks/ are now {sorted(innards)}; the website names allure and "
        f"gitops, and one of the two has to change")


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

    An EMPTY tuple is an answer here, and a valuable one: `allure` and `vcs` have no consumer at all.
    What this forbids is a fifth tombstone appearing with nothing said about it.
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
    """
    # arrange
    due = _release_number() > surface.MOVED_DUE_AFTER

    # assert
    assert not (due and surface.MOVED), (
        f"this is {simplon.__version__}, past {'.'.join(map(str, surface.MOVED_DUE_AFTER))}, and the "
        f"tombstones {sorted(surface.MOVED)} are still here - they were promised to go at this "
        f"release. Removing them is: delete src/simplon/{{{','.join(sorted(surface.MOVED))}}}.py, "
        f"empty surface.MOVED and surface.MOVED_CONSUMERS, and drop the migration table and the "
        f"deadline sentence from site/content/building/surface.md. Re-measure MOVED_CONSUMERS first - "
        f"the record says {sum(len(v) for v in surface.MOVED_CONSUMERS.values())} import lines are "
        f"still out there.")


def test_the_release_page_sends_a_minor_release_to_the_record():
    """The FIRST moment, the one the version cannot reach: somebody about to type a minor. A deadline
    that is only enforced by a red publish is enforced too late to be kind, so the page a releaser
    reads has to carry it - and pointing at the record beats copying it, because a copy of a list of
    six import lines is a second source with a shelf life."""
    # arrange
    page = (Path(__file__).resolve().parents[1] / "site" / "content" / "using"
            / "releasing.md").read_text(encoding="utf-8")

    # assert: the record by name, not a retyped copy of what is in it
    for named in ("simplon.surface", "MOVED_CONSUMERS", "MOVED_DUE_AFTER"):
        assert named in page, (
            f"the release page does not name {named}, so a minor release is sent nowhere and the "
            f"only thing that notices the tombstone deadline is a failed publish")


# --- the consumers a module head is allowed to name (#51) -------------------------------------------


#: Everything a reader of this kernel could mistake for a statement about who uses it: the package, the
#: front page and the site. Tests are NOT in here - a fixture may need a product name that is nobody.
def _prose_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [p for p in [*SRC.rglob("*.py"), root / "README.md", *(root / "site").rglob("*.md")]
            if p.resolve() != (SRC / "surface.py").resolve()]


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


PAGE = Path(__file__).resolve().parents[1] / "site" / "content" / "building" / "surface.md"


def test_the_website_names_the_same_internals():
    """ACCEPTANCE 1. The separation is only useful if a reader can find it, so it is on the site - and a
    list typed into prose is a second source for a string, which is the shape that rots quietly. This
    pins the page to the declaration instead of hoping somebody edits both."""
    # arrange
    page = PAGE.read_text(encoding="utf-8")

    # act
    named = {n.strip("`") for n in re.findall(r"`[a-z_]+`(?= ·|\n)", page)}

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
