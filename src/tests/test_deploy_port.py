"""si#435 (decided 2026-10-15): `deploy:up`'s input port is bound by `deploy: source:`, the section that already
names what is deployed - never by `consumes:`, so the fact has one source and nothing guards two. No evidence
is asked of a deploy (that waits for si#450's gate).

AAA; the name states the behaviour under test.
"""
from pathlib import Path

import pytest

from simplon.manifest import catalogue
from simplon.manifest import load as manifest_mod

ARTIFACTS = """\
artifacts:
  kernel: { kind: image, registry: ghcr.io/o, repository: k, dockerfile: Dockerfile, context: . }
  bundle: { kind: directory, registry: ghcr.io/o, repository: b, media_type: text/plain, path: build/b }
"""

UP = '  deploy:\n    commands:\n      up: { task: "deploy:up" }\n'


def _load(cd: str = UP, *, deploy: str = "deploy: { kind: server, source: { artifacts: kernel } }\n",
          ci: str = "", artifacts: str = ARTIFACTS) -> manifest_mod.Manifest:
    text = (f"product: demo\nci:\n  build:\n    commands:\n"
            f'      image: {{ task: "build:image", produces: {{ image: kernel }} }}\n{ci}'
            f"cd:\n{cd}{deploy}{artifacts}")
    return manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")


def test_deploy_source_binds_the_source_port_of_deploy_up():
    # act
    spec = _load().spec_for("deploy", "up")

    # assert: bound as `consumes:` would bind it, and nothing reaches the body - it reads the section itself
    assert spec.consumes == {"source": ("kernel",)}
    assert [p.name for p in spec.ports] == ["source"]
    assert spec.with_ == {}


def test_a_client_deploy_binds_the_directory_it_installs():
    # act: the port accepts any artifact, because a client installs a directory and a server runs an image
    spec = _load(deploy="deploy: { kind: client, into: ~/apps, source: { artifacts: bundle } }\n"
                 ).spec_for("deploy", "up")

    # assert
    assert spec.consumes == {"source": ("bundle",)}


def test_deploy_down_takes_no_binding():
    # act: removing a deployment consumes nothing
    m = _load(UP + '      down: { task: "deploy:down" }\n')

    # assert
    assert m.spec_for("deploy", "down").consumes == {}
    assert m.spec_for("deploy", "down").ports == ()


def test_without_a_deploy_section_the_port_stays_unbound_and_the_manifest_loads():
    # act: no new load refusal - `deploy:up` refuses a missing `deploy: source:` itself when it runs, as before
    spec = _load(deploy="").spec_for("deploy", "up")

    # assert
    assert spec.consumes == {}


def test_consumes_on_deploy_up_is_refused_and_names_the_section():
    # act
    with pytest.raises(ValueError) as caught:
        _load('  deploy:\n    commands:\n      up: { task: "deploy:up", consumes: { source: kernel } }\n')

    # assert: the same refusal as before the port existed, now saying where the binding is written
    assert str(caught.value) == (
        "command 'deploy up' binds `consumes: source`, and task 'deploy:up' takes that port from "
        "`deploy: source:`, which already names what is deployed - name it there, once")


def test_consumes_on_deploy_up_is_refused_even_without_a_deploy_section():
    # act: the refusal is about where the fact is said, not about whether the section is there yet
    with pytest.raises(ValueError) as caught:
        _load('  deploy:\n    commands:\n      up: { task: "deploy:up", consumes: { source: kernel } }\n',
              deploy="")

    # assert
    assert "takes that port from `deploy: source:`" in str(caught.value)


def test_a_source_artifacts_does_not_declare_is_refused_at_load():
    # act: before si#435 this surfaced only when `deploy up` ran; the bound port is now held to `artifacts:`
    with pytest.raises(ValueError) as caught:
        _load(deploy="deploy: { kind: server, source: { artifacts: kernal } }\n")

    # assert
    assert str(caught.value) == (
        "command 'deploy up' binds 'kernal' to port 'source', and `artifacts:` declares no 'kernal' - "
        "declare it there with its `kind:`")


def test_a_plan_that_deploys_before_it_builds_is_refused():
    # act: the port puts a deploy into the plan rules, so a rollout planned ahead of the build of its image
    # is the consumer-before-producer refusal every other port already gets
    with pytest.raises(ValueError) as caught:
        _load(UP + '      rollout: { depends_on: [up, image], help: "Build, then deploy." }\n')

    # assert
    assert str(caught.value) == (
        "aggregate 'deploy rollout' plans 'up' before 'image', and 'up' consumes 'kernel', which 'image' "
        "produces - list 'image' first in `depends_on`")


def test_a_plan_that_builds_then_deploys_loads():
    # act
    m = _load(UP + '      rollout: { depends_on: [image, up], help: "Build, then deploy." }\n')

    # assert
    assert list(m.plan_for("rollout", group="deploy")) == ["image", "up"]


def test_the_manifest_page_quotes_the_refusal_as_it_is_raised():
    # arrange: a quoted error text is a second source for the string (CLAUDE.md)
    page = (Path(__file__).resolve().parents[2] / "src" / "site" / "content" / "how" / "manifest.md").read_text(
        encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        _load('  deploy:\n    commands:\n      up: { task: "deploy:up", consumes: { source: kernel } }\n')

    # act: the page's quote block after "The section is also the binding", unwrapped
    section = page.split("**The section is also the binding**", 1)[1]
    quoted = " ".join(line[2:] for line in section.splitlines() if line.startswith("> "))

    # assert
    assert quoted == str(caught.value)
