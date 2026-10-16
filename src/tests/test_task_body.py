"""si#400 4c: every command's body runs through a Task class - the generated one for a catalogue coordinate,
one the kernel builds from `impl:` for a product task.

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.domain import catalogue, signatures, task
from simplon.domain.manifestmodel import mangle
from simplon.tasks.image import build


def test_a_catalogue_coordinate_names_its_generated_class():
    # act / assert
    assert task.class_ref("build:image") == "simplon.tasks.build_image:BuildImage"
    assert task.class_ref("support:ci-arm64") == "simplon.tasks.support_ci_arm64:SupportCiArm64"


@pytest.mark.parametrize("coordinate", sorted(catalogue.load().tasks))
def test_every_class_ref_resolves_to_the_class_carrying_that_coordinate(coordinate):
    # act
    cls = task.task_class(task.class_ref(coordinate), coordinate, where=coordinate)

    # assert
    assert issubclass(cls, task.Task) and cls.KEY == coordinate


def test_a_generated_class_is_returned_as_it_is():
    # arrange
    from simplon.tasks.build_image import BuildImage

    # act / assert
    assert task.task_class("simplon.tasks.build_image:BuildImage", "build:image", where="x") is BuildImage


def test_a_product_function_becomes_a_class_whose_run_binds_what_the_function_binds():
    # act
    cls = task.task_class("simplon.tasks.image:build", "pack", where="build pack")

    # assert
    assert issubclass(cls, task.Task) and cls.KEY == "pack"
    assert signatures.bindable(cls().run) == signatures.bindable(build)


def test_two_product_tasks_on_one_function_are_two_classes():
    # act: si#420 - one body, two tasks; keyed by impl, the second would borrow the first's KEY
    a = task.task_class("simplon.tasks.image:build", "pack-a", where="a")
    b = task.task_class("simplon.tasks.image:build", "pack-b", where="b")

    # assert
    assert a is not b and (a.KEY, b.KEY) == ("pack-a", "pack-b")


def test_a_reference_to_something_that_is_no_body_is_refused_naming_the_command():
    # act / assert: a module constant is neither a Task nor a function - running it is not an option
    with pytest.raises(ValueError, match=r"build pack.*PORTS"):
        task.task_class("simplon.domain.artifactschema:PORTS", "pack", where="build pack")


def test_the_class_name_follows_firns_class_name():
    # act / assert: the Tasks template's className, in Python (4b holds the generated side)
    assert [task.class_name(mangle(c)) for c in ("build:image", "test:typecheck-python", "vcs:auth-scopes")] == [
        "BuildImage", "TestTypecheckPython", "VcsAuthScopes"]


def test_assembling_the_cli_imports_no_more_task_modules_than_before():
    # arrange: measured 2026-10-16 - `./simplon.sh --help` imports 8 simplon.tasks modules; importing every
    # class module on start would cost +0.19 s and 411 modules (si#400 4c keeps resolution lazy)
    import os
    import re
    import subprocess
    from conftest import ROOT

    # act
    run = subprocess.run([str(ROOT / "simplon.sh"), "--help"], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPROFILEIMPORTTIME": "1"})
    imported = set(re.findall(r"\|\s*(simplon\.tasks\.[a-z_]+)$", run.stderr, re.MULTILINE))

    # assert
    assert run.returncode == 0, run.stderr[-2000:]
    assert imported, "no import was profiled - the measurement measured nothing"
    assert len(imported) <= 8, sorted(imported)
