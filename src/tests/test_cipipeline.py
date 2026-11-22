"""The product's `runner:` section, read by `simplon.tasks.cipipeline` (si#858)."""
from __future__ import annotations

import textwrap

import pytest
import yaml

from simplon.manifest import artifactsection, catalogue, load as manifest_mod
from simplon.tasks import cipipeline


def test_no_runner_means_github_ubuntu() -> None:
    runner, labels = cipipeline.runner_of({})
    assert runner.kind == "github-ubuntu"
    assert labels == ("ubuntu-latest",)


def test_a_self_hosted_runner_names_its_labels() -> None:
    runner, labels = cipipeline.runner_of({"runner": {"kind": "self-hosted-debian", "labels": "ghr-8"}})
    assert runner.kind == "self-hosted-debian"
    assert labels == ("ghr-8",)


def test_a_self_hosted_runner_without_labels_is_refused() -> None:
    with pytest.raises(ValueError, match="carries no label of its own"):
        cipipeline.runner_of({"runner": "self-hosted-debian"})


# --- the leaves, and their order (si#858 task 5) ---------------------------------------------------------

_HEAD = """
tasks:
  ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
artifacts:
  doc: { kind: file, path: build/doc.txt }
  note: { kind: file, path: build/note.txt, registry: ghcr.io/o/note }
  img: { kind: image, dockerfile: Dockerfile, context: ., registry: ghcr.io/o, repository: img }
"""


def _text(body: str) -> str:
    return _HEAD + textwrap.dedent(body)


def _load(body: str):
    return manifest_mod.load(_text(body), catalogue=catalogue.load(), manifest_path="demo.yaml")


_DECLARED = artifactsection.declared(yaml.safe_load(_HEAD))


def _words(selection) -> list[str]:
    return [leaf.words for leaf in selection.leaves]


def test_leaves_come_in_manifest_order():
    loaded = _load("""
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
              two: { task: ship, unattended: true }
          test:
            commands:
              three: { task: ship, unattended: true }
        """)
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED)) == ["build one", "build two", "test three"]


_PORTS = """
        ci:
          build:
            commands:
              t-consume: { task: "toolchain:run", unattended: true, consumes: { source: doc } }
              a: { task: ship, unattended: true }
              b-produce: { task: "toolchain:run", unattended: true, produces: { out: doc } }
              c: { task: ship, unattended: true }
        """


def test_a_consumer_moves_after_its_producer_and_nothing_else_moves():
    loaded = _load(_PORTS)
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED)) == ["build a", "build b-produce", "build t-consume", "build c"]


def test_aggregates_are_not_leaves():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              all: { depends_on: [one], help: "All." }
        """)
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED)) == ["test one"]


def test_an_attended_leaf_is_skipped_with_the_reason():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              walk: { task: ship, unattended: false }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED)
    assert _words(selection) == ["test one"]
    assert [(s.words, s.reason) for s in selection.skipped] == [("test walk", cipipeline.ATTENDED)]


def test_a_ci_skip_is_skipped_with_its_reason():
    loaded = _load("""
        ci:
          test:
            commands:
              lab: { task: ship, unattended: true, ci: { skip: "needs the lab" } }
              walk: { task: ship, unattended: false }
              one: { task: ship, unattended: true }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED)
    assert _words(selection) == ["test one"]
    assert [(s.words, s.reason) for s in selection.skipped] == [
        ("test lab", "needs the lab"), ("test walk", cipipeline.ATTENDED)]


def test_an_undeclared_unattended_is_refused():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship }
        """)
    with pytest.raises(ValueError, match="'test one' does not say whether it can run with nobody watching"):
        cipipeline.select(loaded, artifacts=_DECLARED)


def test_a_nested_group_leaf_is_selected():
    nested = catalogue.loads(textwrap.dedent("""
        groups:
          ci:
            transparent: true
            groups:
              build: { help: "Produce the artefacts." }
              test:
                help: "Verify them."
                groups:
                  lab: { help: "Needs the lab." }
        """))
    loaded = manifest_mod.load(_text("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
            groups:
              lab:
                commands:
                  smoke: { task: ship, unattended: true }
        """), catalogue=nested, manifest_path="demo.yaml")
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED)) == ["test one", "test lab smoke"]


def test_cd_groups_are_not_selected():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
        cd:
          deploy:
            commands:
              up: { task: ship, unattended: true }
              walk: { task: ship, unattended: false }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED)
    assert _words(selection) == ["test one"]
    assert selection.skipped == ()


def test_a_port_cycle_is_refused_naming_the_loop():
    loaded = _load("""
        ci:
          build:
            commands:
              pack: { task: "toolchain:run", unattended: true, consumes: { source: img }, produces: { out: doc } }
              image: { task: "toolchain:run", unattended: true, consumes: { source: doc }, produces: { out: img } }
        """)
    with pytest.raises(ValueError, match="cycle") as raised:
        cipipeline.select(loaded, artifacts=_DECLARED)
    for named in ("'build pack'", "'build image'", "'doc'", "'img'"):
        assert named in str(raised.value)


_SKIPPED_PRODUCER = """
        ci:
          test:
            commands:
              t-consume: { task: "test:file", unattended: true, consumes: { file: doc } }
          build:
            commands:
              b-produce: { task: "build:fetch", unattended: true, produces: { file: doc }, ci: { skip: "needs the lab" } }
        """


def test_a_consumer_of_a_skipped_producer_is_refused():
    loaded = _load(_SKIPPED_PRODUCER)
    with pytest.raises(ValueError, match="'test t-consume' consumes 'doc'.*'build b-produce'.*needs the lab"):
        cipipeline.select(loaded, artifacts=_DECLARED)


def test_an_artifact_with_a_registry_is_exempt_when_the_registry_is_known():
    body = _SKIPPED_PRODUCER.replace("file: doc", "file: note")
    loaded = _load(body)
    artifacts = artifactsection.declared(yaml.safe_load(_text(body)))
    assert _words(cipipeline.select(loaded, artifacts=artifacts)) == ["test t-consume"]
    with pytest.raises(ValueError, match="consumes 'note'"):
        cipipeline.select(loaded, artifacts={})


def test_a_skip_wins_over_an_undeclared_unattended():
    loaded = _load("""
        ci:
          test:
            commands:
              lab: { task: ship, ci: { skip: "needs the lab" } }
              one: { task: ship, unattended: true }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED)
    assert _words(selection) == ["test one"]
    assert [(s.words, s.reason) for s in selection.skipped] == [("test lab", "needs the lab")]


def test_a_consumer_whose_only_producer_is_in_cd_is_refused():
    loaded = _load("""
        ci:
          test:
            commands:
              t-consume: { task: "test:file", unattended: true, consumes: { file: doc } }
        cd:
          deploy:
            commands:
              b-produce: { task: "toolchain:run", unattended: true, produces: { out: doc } }
        """)
    with pytest.raises(ValueError, match="'test t-consume' consumes 'doc'.*'deploy b-produce'.*not a CI leaf "
                                         r"\(it is in the 'deploy' group\)"):
        cipipeline.select(loaded, artifacts=_DECLARED)


def test_a_leaf_that_consumes_what_it_produces_is_a_one_leaf_cycle():
    loaded = _load("""
        ci:
          build:
            commands:
              loop: { task: "toolchain:run", unattended: true, consumes: { source: doc }, produces: { out: doc } }
        """)
    with pytest.raises(ValueError, match="cycle.*'build loop' consumes 'doc' from 'build loop'"):
        cipipeline.select(loaded, artifacts=_DECLARED)
