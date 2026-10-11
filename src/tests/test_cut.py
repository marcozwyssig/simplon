"""The cut (si#344, spec A.6): every key of the old form is refused by name, with the way out - never
silently ignored, which is what `extra="ignore"` would otherwise do to it. AAA throughout."""
import textwrap

import pytest

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod

MIGRATE = (
    "Rewrite it with the migration, which loads no manifest and so works on this one:\n"
    "  venv:      <orch-dir>/.venv/bin/simplon manifest migrate demo.yaml\n"
    "  container: docker run --rm --user \"$(id -u):$(id -g)\" -v \"$PWD:/src\" -w /src "
    "<kernel image> simplon manifest migrate demo.yaml")


def _load(text: str):
    return manifest_mod.load(textwrap.dedent(text), catalogue=catalogue_mod.load(),
                             manifest_path="demo.yaml")


def test_groups_is_refused_with_the_new_form_and_both_routes():
    # act / assert
    with pytest.raises(ValueError) as caught:
        _load("""\
            product: demo
            groups:
              build:
                commands:
                  w: { task: "build:image" }
        """)
    assert str(caught.value) == (
        "demo.yaml declares `groups:`, which si#344 replaced: commands stand under `ci:` (build, test, "
        "release), `cd:` (deploy, monitor) and `support:`, and the command line does not change:\n"
        "  ci:\n    build:\n      commands: { ... }\n" + MIGRATE)


def test_groups_beside_ci_is_refused_too_not_merged():
    # act / assert: half-migrated by hand (Review Focus 1)
    with pytest.raises(ValueError, match="declares `groups:`, which si#344 replaced"):
        _load("""\
            product: demo
            ci:
              build:
                commands:
                  w: { task: "build:image", with: { name: k } }
            groups:
              test:
                commands:
                  t: { task: "test:typecheck-python" }
        """)


def test_env_groups_is_refused():
    with pytest.raises(ValueError) as caught:
        _load("product: demo\nenv_groups: [deploy]\nci:\n  build:\n    commands:\n      w: { task: \"build:image\" }\n")
    assert str(caught.value) == (
        "demo.yaml declares `env_groups:`, which si#344 deleted: everything under `cd:` takes an "
        "environment and nothing under `ci:` does, so the structure says it. Delete the key.\n" + MIGRATE)


@pytest.mark.parametrize("key", ["default", "environments"])
def test_a_top_level_matrix_key_is_refused(key):
    with pytest.raises(ValueError) as caught:
        _load(f"product: demo\n{key}: x\nci:\n  build:\n    commands:\n      w: {{ task: \"build:image\" }}\n")
    assert str(caught.value) == (
        f"demo.yaml declares `{key}:` at the top level; since si#344 it stands under `cd:`, beside the "
        f"commands that take an environment.\n" + MIGRATE)


def test_a_docs_site_section_is_refused_as_website():
    with pytest.raises(ValueError) as caught:
        _load("product: demo\nsite:\n  theme: x\nci:\n  build:\n    commands:\n      w: { task: \"build:image\" }\n")
    assert str(caught.value) == (
        "demo.yaml declares a top-level `site:` with the documentation site's keys; since si#344 that "
        "section is `website:`, and `site:` is the deployment location under `cd:`.\n" + MIGRATE)


def test_a_location_site_at_the_top_level_is_refused_toward_cd():
    # act / assert (Review Focus 2)
    with pytest.raises(ValueError) as caught:
        _load("product: demo\nsite:\n  central: {}\nci:\n  build:\n    commands:\n      w: { task: \"build:image\" }\n")
    assert str(caught.value) == (
        "demo.yaml declares a top-level `site:`. The deployment location stands under `cd: site:` "
        "(si#344), and the documentation site is `website:` - move it to whichever it is")


def test_a_manifest_with_no_commands_anywhere_says_where_they_go():
    with pytest.raises(ValueError) as caught:
        manifest_mod.load("product: demo\n")
    assert str(caught.value) == "manifest declares no commands under ci:, cd: or support:"


@pytest.mark.parametrize("document, found", [("just a string", "str"), ("- a\n- list\n", "list")],
                         ids=["scalar", "list"])
def test_a_document_that_is_not_a_mapping_is_refused_by_name(document, found):
    # act / assert: not `"groups" in data` matching a SUBSTRING of a string, and not an AttributeError
    # from the first `.get` after it - the shape is named
    with pytest.raises(ValueError) as caught:
        manifest_mod.load(document, manifest_path="demo.yaml")
    assert str(caught.value) == (
        f"demo.yaml is not a mapping: found {found} instead. A manifest maps its top-level keys "
        f"(product, tasks, ci, cd, support, ...) to their values")
