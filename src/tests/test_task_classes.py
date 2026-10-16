"""si#400 part 4b: one generated class per catalogue task, held to the catalogue it is generated from.

Pure: no docker. The classes are committed generated files (`build model`), so the committed files are
what has to be right, as test_catalogue_ports.py says of artifactschema.

AAA; the name states the behaviour under test.
"""
import importlib
import re
from pathlib import Path

import pytest

from simplon.domain import artifactschema, catalogue, signatures
from simplon.domain.manifestmodel import mangle
from simplon.domain.task import Task

TASKS = Path(__file__).resolve().parents[1] / "simplon" / "tasks"
COORDINATES = sorted(catalogue.load().tasks)


def _class_of(coordinate: str) -> type[Task]:
    module = importlib.import_module(f"simplon.tasks.{mangle(coordinate)}")
    found = [v for v in vars(module).values()
             if isinstance(v, type) and issubclass(v, Task) and v is not Task and v.__module__ == module.__name__]
    assert len(found) == 1, f"{module.__name__} defines {found}"
    return found[0]


def _impl(coordinate: str):
    module, function = catalogue.load().tasks[coordinate]["impl"].split(":")
    return getattr(importlib.import_module(module), function)


@pytest.mark.parametrize("coordinate", COORDINATES)
def test_every_catalogue_task_has_one_generated_class_carrying_its_coordinate(coordinate):
    # act
    cls = _class_of(coordinate)

    # assert
    assert cls.KEY == coordinate


@pytest.mark.parametrize("coordinate", COORDINATES)
def test_a_class_carries_the_ports_the_model_gives_its_task_inputs_first(coordinate):
    # act
    ports = tuple(v for v in vars(_class_of(coordinate)).values() if isinstance(v, artifactschema.Port))

    # assert: the same values PORTS holds, from the same instance (4c derives PORTS from these)
    assert ports == artifactschema.PORTS.get(coordinate, ())


@pytest.mark.parametrize("coordinate", COORDINATES)
def test_the_wrapper_binds_exactly_what_the_impl_binds(coordinate):
    # arrange: 4c runs cls().run where it runs the impl today; any difference changes the CLI it renders
    body, impl = _class_of(coordinate)().run, _impl(coordinate)

    # act / assert
    assert signatures.bindable(body) == signatures.bindable(impl)
    assert signatures.takes_context(body) == signatures.takes_context(impl)


def test_the_class_names_are_distinct():
    # act
    names = [_class_of(c).__name__ for c in COORDINATES]

    # assert
    assert len(set(names)) == len(names)


def test_no_generated_task_file_is_left_over_from_a_task_the_catalogue_no_longer_has():
    # arrange: firn KEEPS a file whose task was renamed or removed, with rc 0 (W301, measured), and that
    # file still defines a class with a live KEY - two classes on one coordinate
    ids = {p.name: re.search(r"id=\[Tasks:simplon\.catalogue\.(\w+),", p.read_text())
           for p in TASKS.glob("*.py")}

    # act
    generated = {name: m.group(1) for name, m in ids.items() if m}

    # assert
    assert generated, "no generated task file found - the template wrote nothing, or its id line changed"
    assert sorted(generated.values()) == sorted(mangle(c) for c in COORDINATES)
    assert all(name == f"{instance}.py" for name, instance in generated.items())


def test_every_generated_file_keeps_its_body_in_two_named_regions():
    # act
    missing = [c for c in COORDINATES
               for region in (f"[{mangle(c)}.imports]", f"[{mangle(c)}.run]")
               if f"Begin Protected Region {region}" not in (TASKS / f"{mangle(c)}.py").read_text()]

    # assert
    assert missing == []
