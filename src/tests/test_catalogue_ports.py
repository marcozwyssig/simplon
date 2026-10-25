"""si#344 C.1: the catalogue's tasks carry ports, modelled in firn and generated into artifactschema.

Every property is pinned on the committed generated module, without docker - firn v0.1.0 loses output
with rc 0 (firn#966), so the committed file is what has to be right.

AAA; the name states the behaviour under test.
"""
import importlib
import inspect

from simplon.model import artifactschema
from simplon.manifest import catalogue

P = artifactschema.Port
IMAGE_NEEDS = ("registry", "repository", "dockerfile", "context")
OCI_NEEDS = ("registry", "repository", "media_type", "path")
EVIDENCE = P("evidence", "input", "test-result", "", ())


def test_the_ports_are_the_ones_measured_from_the_bodies():
    # assert: pinned as a literal - built from READERS on both sides, this could not see a wrong direction
    assert artifactschema.PORTS == {
        "build:image": (P("file", "input", "file", "", ()), P("image", "output", "image", "name", IMAGE_NEEDS)),
        "build:fetch": (P("file", "output", "file", "name", ("path", "url", "sha256")),),
        "test:image": (P("image", "input", "image", "name", IMAGE_NEEDS),
                       P("test-result", "output", "test-result", "results", ("path",))),
        "release:image": (P("image", "input", "image", "name", IMAGE_NEEDS), EVIDENCE),
        "release:artifact": (P("directory", "input", "directory", "name", OCI_NEEDS), EVIDENCE),
        "build:conan-cache": (P("conan", "input", "conan", "name", OCI_NEEDS),),
        "release:conan": (P("conan", "input", "conan", "name", OCI_NEEDS), EVIDENCE),
        "build:nuget-config": (P("nuget", "input", "nuget", "name", ("registry",)),),
        "build:nuget-restore": (P("nuget", "input", "nuget", "name", ("registry", "image", "project")),),
        "build:nuget-pack": (P("nuget", "output", "nuget", "name", ("image", "project", "path")),),
        "release:notes": (P("release-notes", "output", "release-notes", "name", ("path",)),),
        "release:tag": (P("release-notes", "input", "release-notes", "", ()), P("tag", "output", "tag", "", ())),
        "release:github-draft": (P("release-notes", "input", "release-notes", "name", ("path",)),),
        "release:github-publish": (P("github-release", "output", "github-release", "", ()),),
        "release:nuget": (P("nuget", "input", "nuget", "name", ("registry", "image", "path")), EVIDENCE),
        "build:maven-pack": (P("maven", "output", "maven", "name", ("image", "group", "modules", "path")),),
        # si#536: two artifact ports on one body, so each binds a parameter of its own name, not `name`
        "build:homebrew-formula": (P("wheel", "input", "directory", "wheel", ("path",)),
                                   P("formula", "output", "homebrew-formula", "formula", ("path",))),
        "test:homebrew-formula": (P("formula", "input", "homebrew-formula", "formula", ("path",)),
                                  P("wheel", "input", "directory", "wheel", ("path",)),
                                  P("test-result", "output", "test-result", "results", ("path",))),
        "release:homebrew-tap": (P("formula", "input", "homebrew-formula", "formula", ("path",)), EVIDENCE),
        "release:maven": (P("maven", "input", "maven", "name", ("registry", "group", "modules", "path")),
                          EVIDENCE),
        "docs:site": (P("site", "output", "site", "", ()),),
        # si#435: bound by `deploy: source:`, so no `param:` - the body reads the section itself
        "deploy:up": (P("source", "input", "artifact", "", ()),),
        "toolchain:run": (P("source", "input", "artifact", "", ()), P("out", "output", "artifact", "", ())),
    }


def test_every_wrapper_wraps_the_body_the_model_names():
    # arrange: since si#400 4c the catalogue names no body; the model's `body` seeds each class's
    # `<task>.imports` region, and while that region holds the wrapper, the two are two sources for one body
    from pathlib import Path
    from simplon.model.task import mangle
    tasks = catalogue.load().tasks
    classes = Path(__file__).resolve().parents[1] / "simplon" / "tasks"

    # act
    wrong = {c: body for c, body in artifactschema.BODIES.items()
             if f"from {body.replace(':', ' import ')} as _body" not in (classes / f"{mangle(c)}.py").read_text()}

    # assert: since si#400 4a EVERY catalogue task is an instance in the model, not only those with ports
    assert set(artifactschema.BODIES) == set(tasks)
    assert set(artifactschema.PORTS) <= set(artifactschema.BODIES)
    assert wrong == {}


def test_every_catalogue_instance_is_named_as_the_export_references_it():
    # arrange: manifestmodel writes `task = simplon.catalogue.<mangle(coordinate)>`; a misnamed instance
    # passes every pure test and is firn's E200 only where docker runs
    import re
    from pathlib import Path
    from simplon.model.task import mangle
    text = (Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "catalogue" / "tasks.firn").read_text()

    # act
    declared = dict(re.findall(
        r'^(\w+) typeOf simplon\.pipeline\.CatalogueTask \{\n  key = "([^"]+)"$', text, re.MULTILINE))

    # assert
    assert declared == {mangle(c): c for c in catalogue.load().tasks}


def test_a_port_that_binds_a_parameter_names_one_its_body_takes():
    # arrange
    tasks = catalogue.load().tasks

    # act: the body's real signature, imported - a `param:` the body lacks would bind nothing at run time
    missing = {}
    for coordinate, ports in artifactschema.PORTS.items():
        module, function = artifactschema.BODIES[coordinate].split(":")
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


def test_the_kinds_page_lists_every_port_the_module_has():
    # arrange
    import re
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / "site" / "content" / "with-what" / "kinds.md").read_text()
    row = re.compile(r"^\| `([a-z-]+:[a-z-]+)` \| `([a-z-]+)` \| (input|output) \| `([a-z-]+)` \| (`[a-z_]+`|) \|$", re.M)

    # act
    listed = {(c, n, d, a, b.strip("`")) for c, n, d, a, b in row.findall(page)}
    expected = {(c, p.name, p.direction, p.accepts, p.param)
                for c, ports in artifactschema.PORTS.items() for p in ports}

    # assert: the page is a second rendering of one model, so it is held to the module both ways
    assert expected, "no ports - the comparison would mean nothing"
    assert listed == expected


def test_each_generated_file_names_both_models_it_is_generated_from():
    # arrange: since C.1 the ports come from simplon/catalogue/tasks.firn, not only from the vocabulary;
    # a header naming one would send whoever changes a port to a file that has none
    from pathlib import Path
    src = Path(__file__).resolve().parents[1]
    files = [src / "simplon" / "model" / "artifactschema.py", src / "site" / "content" / "with-what" / "kinds.md"]

    # act
    missing = {f.name: [m for m in ("vocabulary/kinds.firn", "catalogue/tasks.firn") if m not in f.read_text()]
               for f in files}

    # assert
    assert missing == {f.name: [] for f in files}


def test_the_kinds_page_says_how_a_command_binds_a_port():
    # arrange: since si#344 C.2 a command binds a port; the page says how, and no longer that it cannot
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / "site" / "content" / "with-what" / "kinds.md").read_text()

    # act
    ports = page[page.index("## Ports"):]

    # assert
    assert "A manifest cannot bind a port yet" not in ports
    assert "`produces: { <port>: <artifact> }`" in ports
    assert "`consumes: { <port>: <artifact> }`" in ports


def test_the_kinds_page_says_a_release_consumes_the_test_results():
    # arrange
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "site" / "content" / "with-what" / "kinds.md").read_text(encoding="utf-8")

    # assert
    assert "`evidence`" in text
    assert "every test result about" in text
