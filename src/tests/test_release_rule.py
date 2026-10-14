"""si#344 C.3: test results, and the release rule (spec C.3, C.5 rule 6).

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.domain import catalogue, manifest

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
