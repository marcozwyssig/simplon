"""si#344 C.3: test results, and the release rule (spec C.3, C.5 rule 6).

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.manifest import catalogue, load as manifest

HEAD = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
"""


def _load(text):
    return manifest.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")


def test_a_test_result_without_a_path_is_refused_by_name():
    # arrange
    text = HEAD.replace("{ kind: test-result, path: build/test/app.json }", "{ kind: test-result }") + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
"""

    # act / assert
    with pytest.raises(ValueError, match="which declares no `path:`"):
        _load(text)


def test_a_test_result_produced_outside_ci_test_is_refused():
    # arrange: a build command writes a result through toolchain:run's generic output port
    text = HEAD + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
      check: { task: "toolchain:run", consumes: { source: app }, produces: { out: app-checked } }
"""

    # act / assert
    with pytest.raises(ValueError, match="outside `ci: test:`"):
        _load(text)


CHAIN = HEAD + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
"""


def test_a_release_with_every_result_about_its_artifact_loads():
    # act
    loaded = _load(CHAIN)

    # assert
    assert loaded.spec_for("release", "image").consumes["evidence"] == ("app-checked",)


def test_an_untested_release_is_refused_naming_the_artifact():
    # arrange: no test consumes `app`
    text = HEAD + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: app } }
"""

    # act / assert
    with pytest.raises(ValueError, match="releases 'app', and no test produces a result about it"):
        _load(text)


def test_a_release_leaving_out_one_result_is_refused_naming_it():
    # arrange: a second test on `app`, and the release consumes only the first result
    text = CHAIN.replace("artifacts:\n", "artifacts:\n  app-ran: { kind: test-result, path: build/test/ran.json }\n").replace(
        "  release:\n",
        '      ran: { task: "test:image", consumes: { image: app }, produces: { test-result: app-ran } }\n  release:\n')

    # act / assert
    with pytest.raises(ValueError, match=r"without the test result\(s\) app-ran about it"):
        _load(text)


def test_a_test_of_what_the_artifact_was_built_from_is_not_about_it():
    # arrange: the only test consumes the SOURCE directory, not the image built from it
    # `src` names a registry, so rule 2 (a consumer without a producer) lets it through as an external input
    text = HEAD.replace("artifacts:\n", "artifacts:\n  src: { kind: directory, path: src, registry: ghcr.io/o }\n") + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      unit: { task: "toolchain:run", consumes: { source: src }, produces: { out: app-checked } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
"""

    # act / assert
    with pytest.raises(ValueError, match="releases 'app', and no test produces a result about it"):
        _load(text)


def test_a_release_command_consuming_only_its_own_kinds_needs_no_evidence():
    # arrange: a product task with an input port accepting release-notes stands in for release:tag
    text = HEAD.replace("artifacts:\n", "artifacts:\n  notes: { kind: release-notes, path: build/notes.md }\n") + """
tasks:
  announce: { impl: "simplon.test_impls:nullary", help: announce, input: { notes: { accepts: release-notes } } }
  write:    { impl: "simplon.test_impls:nullary", help: write, output: { notes: { accepts: release-notes } } }
ci:
  release:
    commands:
      notes:    { task: write, produces: { notes: notes } }
      announce: { task: announce, consumes: { notes: notes } }
"""

    # act / assert: loads
    _load(text)
