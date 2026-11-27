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


#: si#789: `build image` writes the image's OCI archive beside the image in one bake, and the release pushes the
#: archive. A test of the image is about the archive its producer wrote with it, when the release takes both.
ARCHIVED = CHAIN.replace("artifacts:\n", "artifacts:\n  app-oci: { kind: directory, path: build/image }\n", 1) \
    .replace("produces: { image: app } }", "produces: { image: app, archive: app-oci } }", 1) \
    .replace("consumes: { image: app, evidence: [app-checked] } }",
             "consumes: { image: app, archive: app-oci, evidence: [app-checked] } }", 1)


def test_a_test_of_an_image_is_about_the_archive_its_producer_wrote_beside_it():
    # act
    loaded = _load(ARCHIVED)

    # assert
    assert loaded.spec_for("release", "image").consumes["archive"] == ("app-oci",)


def test_a_directory_another_command_wrote_is_not_covered_by_the_images_test():
    # arrange: the same bindings on the release, but the directory comes from a command of its own, so no test
    # of the image says anything about it
    text = ARCHIVED.replace("produces: { image: app, archive: app-oci } }", """produces: { image: app } }
      pack: { task: pack, produces: { out: app-oci } }""", 1) + """tasks:
  pack: { impl: "simplon.test_impls:nullary", help: pack, output: { out: { accepts: directory } } }
"""

    # act / assert
    with pytest.raises(ValueError, match="releases 'app-oci', and no test produces a result about it"):
        _load(text)


def test_a_sibling_pair_under_a_port_that_does_not_verify_it_is_refused_as_on_main():
    """si#789 ruling: the widening holds only where the consuming release port declares that it verifies the
    sibling against the evidence (`release:image`'s `archive`). A product task taking the same pair on ports
    that declare nothing gets rule 6 exactly as strict as before."""
    # arrange
    text = ARCHIVED.replace('image: { task: "release:image", consumes: { image: app, archive: app-oci, evidence: [app-checked] } }',
                            "image: { task: ship, consumes: { image: app, archive: app-oci, evidence: [app-checked] } }") + """tasks:
  ship: { impl: "simplon.test_impls:nullary", help: ship, unattended: true,
          input: { image: { accepts: image }, archive: { accepts: directory }, evidence: { accepts: test-result } } }
"""
    assert text != ARCHIVED

    # act / assert
    with pytest.raises(ValueError, match="releases 'app-oci', and no test produces a result about it"):
        _load(text)


def test_simplons_image_release_needs_its_port_to_declare_the_verification(monkeypatch):
    """The declaration is what lets simplon's `release push-image` take `kernel-oci` on `kernel-checked`: without
    it, simplon's own manifest is refused by rule 6."""
    # arrange
    from conftest import ROOT
    from simplon.model import artifactschema
    text = (ROOT / "simplon.yaml").read_text(encoding="utf-8")
    _load(text)  # loads as it is
    monkeypatch.setattr(artifactschema, "VERIFIED_AGAINST_EVIDENCE", frozenset())

    # act / assert
    with pytest.raises(ValueError, match="releases 'kernel-oci', and no test produces a result about it"):
        _load(text)


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
