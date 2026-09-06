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

from simplon import surface

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


# --- the tombstones ---------------------------------------------------------------------------------


@pytest.mark.parametrize("old", sorted(surface.MOVED))
def test_a_moved_module_still_imports(old):
    """Acceptance 3, first half: the old path has not simply gone."""
    importlib.import_module(f"simplon.{old}")


@pytest.mark.parametrize("old, new", sorted(surface.MOVED.items()))
def test_a_moved_module_points_at_a_real_home(old, new):
    """A forwarding address that forwards nowhere is the silent break with extra steps."""
    importlib.import_module(new)


@pytest.mark.parametrize("old, new", sorted(surface.MOVED.items()))
def test_a_moved_module_announces_the_move_on_use(old, new):
    """ACCEPTANCE 4, and the assertion the ticket was written for: reaching a moved module through its
    old path works and SAYS where the module went. Seen red before the tombstones existed - the probe
    imported `simplon.images.hub_repo` against the unchanged tree and no warning was raised at all.

    The warning is pinned against `surface.moved_message`, not retyped, because a quoted message is a
    second source for a string."""
    # arrange: a name the new module really has and the tombstone does NOT define itself - otherwise
    # the lookup never reaches `__getattr__` and this would assert nothing. `annotations` is the one
    # that bites: every module here does `from __future__ import annotations`, tombstones included.
    target = importlib.import_module(new)
    tombstone = importlib.import_module(f"simplon.{old}")
    attribute = next(n for n in sorted(vars(target))
                     if not n.startswith("_") and n not in vars(tombstone))

    # act
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        value = getattr(tombstone, attribute)

    # assert: the same object, and a warning naming both ends of the move
    assert value is getattr(target, attribute)
    messages = [str(w.message) for w in caught if issubclass(w.category, FutureWarning)]
    assert surface.moved_message(f"simplon.{old}", new) in messages, (
        f"using simplon.{old}.{attribute} said {messages or 'nothing'}; it has to name {new}")


def test_the_move_is_announced_where_python_will_actually_show_it(tmp_path):
    """WHY FutureWarning AND NOT DeprecationWarning, and this measures it rather than asserting it.

    Python's default filters ignore a DeprecationWarning unless the frame that triggered it is
    `__main__`. The frame that triggers this one is a product's own task body, which never is - so a
    DeprecationWarning here would be shown to NOBODY, which is exactly the silent disappearance
    acceptance 3 forbids. A test that raised the warning in-process could not see that difference,
    because pytest installs its own filters; this one runs a fresh interpreter with the defaults and
    reads what actually reached stderr.
    """
    # arrange: a LIBRARY module (never __main__) that uses the tombstone, plus a DeprecationWarning
    # raised from the same depth, so the only thing differing between the two is the category
    consumer = tmp_path / "consumer.py"
    consumer.write_text("import warnings\n"
                        "from simplon import images\n"
                        "images.hub_repo\n"
                        # stacklevel=1: attributed to consumer.py itself, which is where
                        # `moved_attr`'s stacklevel=3 lands too - same frame, so only the CATEGORY
                        # differs between the two notices below.
                        "warnings.warn('DEPRECATION-COMPARISON', DeprecationWarning, stacklevel=1)\n")
    (tmp_path / "main.py").write_text("import consumer\n")

    # act: default filters (no -W), fresh interpreter
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC.parent), str(tmp_path)])}
    done = subprocess.run([sys.executable, str(tmp_path / "main.py")],
                          capture_output=True, text=True, env=env, cwd=tmp_path)

    # assert: the move was announced, and the same notice as a DeprecationWarning would have vanished
    assert done.returncode == 0, done.stderr
    assert "simplon.imagenames" in done.stderr, (
        f"the move was not announced under Python's DEFAULT filters; stderr was {done.stderr!r}")
    assert "consumer.py" in done.stderr, (
        f"the notice was blamed on the wrong frame, so `moved_attr`'s stacklevel is off; "
        f"stderr was {done.stderr!r}")
    assert "DEPRECATION-COMPARISON" not in done.stderr, (
        "a DeprecationWarning WAS shown here, so the reason for choosing FutureWarning no longer holds")


def test_a_tombstone_does_not_announce_a_move_for_a_dunder_probe():
    """`inspect`, `pytest` and `importlib` ask any module they touch for `__path__`, `__spec__` and
    friends. Answering those with a move notice would report a migration no product code asked for -
    and, worse, teach the reader to ignore the message. `__all__` is the deliberate exception and has
    its own test below."""
    # arrange
    tombstone = importlib.import_module(f"simplon.{sorted(surface.MOVED)[0]}")

    # act
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(AttributeError):
            tombstone.__path__

    # assert
    assert not caught, [str(w.message) for w in caught]


@pytest.mark.parametrize("old, new", sorted(surface.MOVED.items()))
def test_a_star_import_through_a_tombstone_binds_what_the_real_module_binds(old, new, tmp_path):
    """A star-import is the one shape that fails SILENTLY through a forwarding module, which makes it
    this project's recurring defect in miniature: `from simplon.images import *` asks for `__all__`,
    and a tombstone that refuses it falls back to its own module dict - binding `Any`, `annotations`
    and `surface` while raising no warning at all. The caller then has none of the names it asked for
    and no statement that anything is wrong.

    Measured before the fix: exactly those three names, zero warnings. So `__all__` is answered, and
    answered with the TARGET's star-import surface, which is what this pins - not a hand-written list.
    """
    # arrange
    reference: dict[str, object] = {}
    exec(f"from {new} import *", reference)
    expected = {k for k in reference if not k.startswith("__")}

    # act
    through_tombstone: dict[str, object] = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        exec(f"from simplon.{old} import *", through_tombstone)
    bound = {k for k in through_tombstone if not k.startswith("__")}

    # assert: the same names, the same objects, and the move was not passed over in silence
    assert bound == expected, f"star-import through simplon.{old} bound {sorted(bound)}"
    assert all(through_tombstone[k] is reference[k] for k in expected)
    assert any(surface.moved_message(f"simplon.{old}", new) == str(w.message)
               for w in caught if issubclass(w.category, FutureWarning)), (
        f"a star-import through simplon.{old} said nothing about the move")


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
