"""si#344 C.1: the catalogue's tasks carry ports, modelled in firn and generated into artifactschema.

Every property is pinned on the committed generated module, without docker - firn v0.1.0 loses output
with rc 0 (firn#966), so the committed file is what has to be right.

AAA; the name states the behaviour under test.
"""
import importlib
import inspect

from simplon.domain import artifactschema, catalogue

P = artifactschema.Port
IMAGE_NEEDS = ("registry", "repository", "dockerfile", "context")
OCI_NEEDS = ("registry", "repository", "media_type", "path")


def test_the_ports_are_the_ones_measured_from_the_bodies():
    # assert: pinned as a literal - built from READERS on both sides, this could not see a wrong direction
    assert artifactschema.PORTS == {
        "build:image": (P("image", "output", "image", "name", IMAGE_NEEDS),),
        "test:image": (P("image", "input", "image", "name", IMAGE_NEEDS),),
        "release:image": (P("image", "input", "image", "name", IMAGE_NEEDS),),
        "release:artifact": (P("directory", "input", "directory", "name", OCI_NEEDS),),
        "build:conan-cache": (P("conan", "input", "conan", "name", OCI_NEEDS),),
        "release:conan": (P("conan", "input", "conan", "name", OCI_NEEDS),),
        "build:nuget-config": (P("nuget", "input", "nuget", "name", ("registry",)),),
        "build:nuget-restore": (P("nuget", "input", "nuget", "name", ("registry", "image", "project")),),
        "release:nuget": (P("nuget", "input", "nuget", "name", ("registry", "image", "project")),),
        "release:maven": (P("maven", "input", "maven", "name", ("registry", "image", "group", "modules")),),
        "docs:site": (P("site", "output", "site", "", ()),),
        "toolchain:run": (P("source", "input", "artifact", "", ()), P("out", "output", "artifact", "", ())),
    }


def test_every_modelled_task_is_a_catalogue_coordinate_with_the_body_the_catalogue_names():
    # arrange
    tasks = catalogue.load().tasks

    # act
    unknown = sorted(c for c in artifactschema.BODIES if c not in tasks)
    wrong = {c: (body, tasks[c]["impl"]) for c, body in artifactschema.BODIES.items()
             if c in tasks and tasks[c]["impl"] != body}

    # assert: the model and the hand-written catalogue are two sources for one body until si#400
    assert set(artifactschema.BODIES) == set(artifactschema.PORTS)
    assert unknown == []
    assert wrong == {}


def test_a_port_that_binds_a_parameter_names_one_its_body_takes():
    # arrange
    tasks = catalogue.load().tasks

    # act: the body's real signature, imported - a `param:` the body lacks would bind nothing at run time
    missing = {}
    for coordinate, ports in artifactschema.PORTS.items():
        module, function = tasks[coordinate]["impl"].split(":")
        params = inspect.signature(getattr(importlib.import_module(module), function)).parameters
        lost = [p.param for p in ports if p.param and p.param not in params]
        if lost:
            missing[coordinate] = lost

    # assert
    assert any(p.param for ports in artifactschema.PORTS.values() for p in ports), "no port binds anything"
    assert missing == {}


def test_every_port_accepts_a_kind_and_needs_only_keys_that_kind_has():
    # act
    unknown = {(c, p.name): p.accepts for c, ports in artifactschema.PORTS.items() for p in ports
               if p.accepts not in artifactschema.REFINES}
    stray = {(c, p.name): [k for k in p.needs if k not in type(artifactschema.validate(p.accepts, {"kind": p.accepts})).SHAPES]
             for c, ports in artifactschema.PORTS.items() for p in ports}

    # assert
    assert unknown == {}
    assert stray == {key: [] for key in stray}
    assert {p.direction for ports in artifactschema.PORTS.values() for p in ports} == {"input", "output"}


def test_a_task_has_no_two_ports_of_one_name_on_one_side():
    # act
    doubled = {c: names for c, ports in artifactschema.PORTS.items()
               for names in [[p.name for p in ports]] if len(names) != len(set(names))}

    # assert: `consumes: { image: ... }` must name exactly one port
    assert doubled == {}


def test_the_model_has_no_second_source_for_what_a_reader_reads():
    # arrange: KindReader was B2's placeholder ("Part C's ports replace it"); once ports exist it is a
    # second statement of the same fact, and two statements drift
    from pathlib import Path
    model = Path(__file__).resolve().parents[1] / "firn" / "model"
    template = Path(__file__).resolve().parents[1] / "firn" / "templates" / "schema.firnt"

    # act
    mentions = sorted(str(p.relative_to(model)) for p in model.rglob("*.firn") if "KindReader" in p.read_text())

    # assert
    assert mentions == []
    assert "KindReader" not in template.read_text()
    assert artifactschema.READERS == {c: p.accepts for c, ports in artifactschema.PORTS.items()
                                      for p in ports if p.param == "name"}
