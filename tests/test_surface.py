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


def _top_level_modules() -> set[str]:
    """Every module that actually sits at the top level of the package, read off the directory."""
    return {p.stem for p in SRC.glob("*.py")} - NOT_CLASSIFIED


# --- the declaration against the tree ---------------------------------------------------------------


def test_every_top_level_module_is_classified():
    """The point of the whole module: a new file beside `cli.py` cannot appear without somebody saying
    which surface it is on. This is the test that makes the declaration a decision rather than a note -
    add a module and this goes red until it is placed."""
    # arrange
    classified = surface.LIBRARY | surface.INTERNAL | set(surface.MOVED)

    # act
    unplaced = _top_level_modules() - classified

    # assert
    assert not unplaced, (
        f"{sorted(unplaced)} sit at the top level of simplon and are in none of "
        f"surface.LIBRARY / INTERNAL / MOVED - decide whether a product may import them")


def test_the_declaration_names_nothing_that_has_gone():
    """The other direction: a module deleted or moved without touching the declaration leaves a promise
    pointing at nothing, which is worse than no promise at all."""
    # arrange
    declared = surface.LIBRARY | surface.INTERNAL | set(surface.MOVED)

    # act
    phantom = declared - _top_level_modules()

    # assert
    assert not phantom, f"surface declares {sorted(phantom)}, which are not top-level simplon modules"


def test_the_three_sets_do_not_overlap():
    """A module is on one surface. `library and also internal` is not a state anybody can act on."""
    # arrange / act
    pairs = [("LIBRARY/INTERNAL", surface.LIBRARY & surface.INTERNAL),
             ("LIBRARY/MOVED", surface.LIBRARY & set(surface.MOVED)),
             ("INTERNAL/MOVED", surface.INTERNAL & set(surface.MOVED))]

    # assert
    for names, overlap in pairs:
        assert not overlap, f"{sorted(overlap)} is in both halves of {names}"


def test_every_library_module_imports():
    """A promised module that does not import is a promise broken at the first line."""
    for name in sorted(surface.LIBRARY):
        importlib.import_module(f"simplon.{name}")


def test_no_module_is_promised_under_a_task_body_s_name():
    """The collision this ticket exists for. A top-level module sharing a name with a task body is the
    shape the #31 review lost time to - `simplon.images` against `simplon.tasks.image`. The library
    surface is the half that may not collide, because it is the half a product types."""
    # arrange: task bodies, and the singular/plural spellings that read as the same word
    bodies = {p.stem for p in (SRC / "tasks").glob("*.py")} - {"__init__"}
    spellings = bodies | {b + "s" for b in bodies}

    # act
    collisions = surface.LIBRARY & spellings

    # assert
    assert not collisions, (
        f"{sorted(collisions)} is promised to products AND names a task body in simplon/tasks/ - "
        f"one of the two has to be renamed, because nothing at the call site says which is which")


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
    """`inspect`, `pytest` and `importlib` ask any module they touch for `__path__`, `__all__` and
    friends. Answering those with a move notice would report a migration no product code asked for -
    and, worse, teach the reader to ignore the message."""
    # arrange
    tombstone = importlib.import_module(f"simplon.{sorted(surface.MOVED)[0]}")

    # act
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(AttributeError):
            tombstone.__all__

    # assert
    assert not caught, [str(w.message) for w in caught]


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
