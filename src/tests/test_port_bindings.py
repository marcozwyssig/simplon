"""si#344 C.2: a command binds its task's ports with `produces:` and `consumes:`; the loader holds every
binding to the task's ports, to the artifacts and to the plans (spec C.5 rules 1-5 and 7).

Decided 2026-10-14 (si#344): `with: { name: X }` alone, on the parameter a port binds, is read as that
port's binding; rule 1 is one producer per artifact PER PLAN.

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.domain import catalogue
from simplon.domain import manifest as manifest_mod

ARTIFACTS = """\
artifacts:
  kernel: { kind: image, registry: ghcr.io/o, repository: k, dockerfile: Dockerfile, context: . }
  local: { kind: image, dockerfile: Dockerfile, context: . }
  docs: { kind: directory, registry: ghcr.io/o, repository: d, media_type: text/html, path: build/site }
"""


def _load(commands: str, *, tasks: str = "", artifacts: str = ARTIFACTS) -> manifest_mod.Manifest:
    text = f"product: demo\n{tasks}ci:\n{commands}{artifacts}"
    return manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")


def _refusal(commands: str, *, tasks: str = "", artifacts: str = ARTIFACTS) -> str:
    with pytest.raises(ValueError) as caught:
        _load(commands, tasks=tasks, artifacts=artifacts)
    return str(caught.value)


def test_produces_binds_the_output_port_and_hands_the_name_to_its_parameter():
    # act
    spec = _load("  build:\n    commands:\n"
                 '      image: { task: "build:image", produces: { image: kernel } }\n').spec_for("build", "image")

    # assert: the body still receives `name`, which is how an artifact reaches it (spec C.1)
    assert spec.produces == {"image": ("kernel",)}
    assert spec.consumes == {}
    assert spec.with_ == {"name": "kernel"}
    assert spec.task == "build:image"
    assert [p.name for p in spec.ports] == ["image"]


def test_consumes_binds_the_input_port():
    # act
    m = _load("  build:\n    commands:\n"
              '      image: { task: "build:image", produces: { image: kernel } }\n'
              "  release:\n    commands:\n"
              '      image: { task: "release:image", consumes: { image: kernel } }\n')

    # assert
    assert m.spec_for("release", "image").consumes == {"image": ("kernel",)}
    assert m.spec_for("release", "image").with_ == {"name": "kernel"}


def test_with_name_alone_is_read_as_the_binding():
    # act: the form simplon and firn write today (decided 2026-10-14)
    spec = _load("  build:\n    commands:\n"
                 '      image: { task: "build:image", with: { name: kernel, platform: linux/amd64 } }\n'
                 ).spec_for("build", "image")

    # assert
    assert spec.produces == {"image": ("kernel",)}
    assert spec.with_ == {"name": "kernel", "platform": "linux/amd64"}


def test_with_name_that_is_not_a_string_is_left_as_it_was():
    # act: `name: 25` was never a binding the loader could read; the run-time reader rules on it as before
    spec = _load("  build:\n    commands:\n"
                 '      image: { task: "build:image", with: { name: 25 } }\n', artifacts="").spec_for("build", "image")

    # assert
    assert spec.produces == {}
    assert spec.with_ == {"name": 25}


def test_a_task_without_ports_binds_nothing_and_says_which_ports_it_has():
    # act
    message = _refusal("  build:\n    commands:\n"
                       '      wheel: { task: "build:nuget-config", produces: { nuget: kernel } }\n')

    # assert: rule 4, and the direction is part of the port's name
    assert message == ("command 'build wheel' binds `produces: nuget`, and task 'build:nuget-config' has no "
                       "output port 'nuget' - its output ports: none")


def test_a_port_name_the_task_does_not_have_is_refused_with_the_ones_it_has():
    # act
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { img: kernel } }\n')

    # assert
    assert message == ("command 'build image' binds `produces: img`, and task 'build:image' has no output "
                       "port 'img' - its output ports: image")


def test_a_binding_that_is_not_a_mapping_is_refused():
    # act
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: [kernel] }\n')

    # assert
    assert message.startswith("command 'build image' declares `produces:` as list, not a mapping. "
                              "`produces:` binds a port to an artifact")


@pytest.mark.parametrize("value", ["''", "7", "{ a: b }"])
def test_a_binding_to_something_that_is_not_an_artifact_name_is_refused(value):
    # act
    message = _refusal("  build:\n    commands:\n"
                       f'      image: {{ task: "build:image", produces: {{ image: {value} }} }}\n')

    # assert
    assert "command 'build image' binds port 'image' to" in message
    assert "names an artifact" in message


def test_a_list_on_a_port_that_hands_one_name_to_its_parameter_is_refused():
    # act
    message = _refusal("  release:\n    commands:\n"
                       '      image: { task: "release:image", consumes: { image: [kernel, local] } }\n')

    # assert
    assert message == ("command 'release image' binds port 'image' to a list, and that port hands ONE "
                       "artifact's name to `name` - bind one artifact")


def test_a_binding_beside_with_on_the_parameter_it_binds_is_refused():
    # act: rule 7, the one expression rule here - both say the same fact
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { image: kernel }, with: { name: kernel } }\n')

    # assert
    assert message == ("command 'build image' binds a port and also pins name with `with:`. The binding "
                       "hands the artifact's name to that parameter - drop it from `with:`")


def test_a_binding_on_a_parameter_the_command_presents_with_params_is_refused():
    # act: the bound parameter is off the command line, so its presentation renders nowhere
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { image: kernel },'
                       ' params: { name: { help: "x" } } }\n')

    # assert
    assert "pins name with `with:` and also declares `params:` for it" in message


PRODUCT_TASK = """\
tasks:
  pack:
    impl: "orchestrator.cli:pack"
    help: "Pack the site."
    input:
      site: { accepts: site }
    output:
      bundle: { accepts: directory, param: name }
"""


def test_a_product_task_declares_ports_and_its_command_binds_them():
    # act
    spec = _load("  build:\n    commands:\n"
                 "      pack: { task: pack, consumes: { site: web }, produces: { bundle: docs } }\n",
                 tasks=PRODUCT_TASK,
                 artifacts=ARTIFACTS + "  web: { kind: site, path: build/site }\n").spec_for("build", "pack")

    # assert: the port with `param:` hands the name over; the one without is checked only
    assert [(p.name, p.direction, p.accepts, p.param) for p in spec.ports] == [
        ("site", "input", "site", ""), ("bundle", "output", "directory", "name")]
    assert spec.consumes == {"site": ("web",)}
    assert spec.produces == {"bundle": ("docs",)}
    assert spec.with_ == {"name": "docs"}


@pytest.mark.parametrize("ports,fragment", [
    ("    output: [bundle]\n", "declares `output:` as list, not a mapping of port name to port"),
    ("    output:\n      bundle: directory\n", "port 'bundle' is not a mapping: it takes `accepts:`"),
    ("    output:\n      bundle: { accepts: directory, kind: x }\n", "port 'bundle' declares unknown key `kind:`"),
    ("    output:\n      bundle: { param: name }\n", "port 'bundle' declares no `accepts:`"),
    ("    output:\n      bundle: { accepts: directory, param: 3 }\n", "`param:` is the name of a body parameter"),
    ("    input:\n      bundle: { accepts: site }\n    output:\n      bundle: { accepts: directory }\n",
     "declares port 'bundle' as an input and an output"),
])
def test_a_port_declaration_the_loader_cannot_read_is_refused(ports, fragment):
    # arrange
    tasks = ('tasks:\n  pack:\n    impl: "orchestrator.cli:pack"\n    help: "Pack."\n' + ports)

    # act
    message = _refusal("  build:\n    commands:\n      pack: { task: pack }\n", tasks=tasks)

    # assert
    assert message.startswith("task 'pack' ")
    assert fragment in message
