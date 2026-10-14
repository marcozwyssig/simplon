"""si#344 C.3: a release is one aggregate that names one `kind: release` bundle (spec C.4, C.5 rule 8).

AAA; the name states the behaviour under test.
"""
from pathlib import Path

import pytest

from simplon.domain import catalogue, manifest

ROOT = Path(__file__).resolve().parents[2]

HEAD = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
  app-notes: { kind: release-notes, path: build/release/notes.md }
  app-tag: { kind: tag }
  app-release: { kind: release }
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      notes: { task: "release:notes", produces: { release-notes: app-notes } }
      publish:  { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
      tag:   { task: "release:tag", consumes: { release-notes: app-notes }, produces: { tag: app-tag } }
"""
# The publish leaf is `publish`, not `image` or `push` (`support git push` owns that): `depends_on` names a leaf by a bare name one group owns (#519),
# and `image` is also `build image` and `test image` here.


def _load(text):
    return manifest.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")


def test_a_release_aggregate_names_its_bundle():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, publish, tag], help: 'h', produces: { release: app-release } }\n"

    # act
    loaded = _load(text)

    # assert
    assert loaded.spec_for("release", "all").produces == {"release": ("app-release",)}


def test_an_aggregate_outside_ci_release_naming_an_output_is_refused():
    # arrange
    text = HEAD.replace("  test:\n    commands:\n",
                        "  test:\n    commands:\n      all: { depends_on: [publish], help: 'h', produces: { release: app-release } }\n")

    # act / assert
    with pytest.raises(ValueError, match="only an aggregate under `ci: release:` does"):
        _load(text)


def test_a_release_aggregate_naming_two_outputs_is_refused():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, publish, tag], help: 'h', produces: { release: app-release, tag: app-tag } }\n"

    # act / assert
    with pytest.raises(ValueError, match="a release aggregate names exactly one output"):
        _load(text)


def test_a_bundle_that_is_not_a_release_is_refused():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, publish, tag], help: 'h', produces: { release: app-tag } }\n"

    # act / assert
    with pytest.raises(ValueError, match="the bundle is a `kind: release`"):
        _load(text)


def test_a_tag_planned_before_a_publish_is_refused():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, tag, publish], help: 'h', produces: { release: app-release } }\n"

    # act / assert
    with pytest.raises(ValueError, match="plans 'tag' before 'publish'"):
        _load(text)


def test_an_aggregate_consuming_is_still_refused():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, publish, tag], help: 'h', consumes: { image: app } }\n"

    # act / assert
    with pytest.raises(ValueError, match="an aggregate runs no task"):
        _load(text)


def test_the_kernels_own_release_aggregate_loads():
    # act
    loaded = _load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))

    # assert
    spec = loaded.spec_for("release", "all")
    assert spec.produces == {"release": ("kernel-release",)}
    assert loaded.plan_for("all", group="release")[-1] == "tag"
