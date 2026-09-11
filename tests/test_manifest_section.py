"""Unit tests for `simplon.context.section` - the ONE walk from a manifest document to a data section
(si#175).

The accessor ANSWERS and the caller REFUSES, so these tests are about the answer: which step a broken
path blames, how an absent step is told from a malformed one, and that a nested path is the same walk as
a flat one. The messages the nine migrated readers produce are held where they are raised, by each
reader's own tests. AAA throughout.
"""
import pytest

from simplon.context import Section, section


def test_a_declared_section_comes_back_with_nothing_to_blame():
    # arrange
    document = {"nexus": {"cli": "nexus", "http_port": 8181}}

    # act
    found = section(document, "nexus")

    # assert
    assert found == Section({"cli": "nexus", "http_port": 8181}, "", None)
    assert not found.blame


def test_a_section_declared_empty_is_found_rather_than_blamed():
    """`site: {}` IS a declaration, and every reader that took it through `isinstance(..., Mapping)`
    went on to complain about the key it wanted. An accessor that called an empty mapping 'missing'
    would move that complaint to the wrong sentence."""
    # arrange
    document = {"site": {}}

    # act
    found = section(document, "site")

    # assert
    assert found.data == {}
    assert found.blame == ""


def test_an_absent_step_is_blamed_by_name_and_holds_nothing():
    # arrange
    document = {"product": "demo"}

    # act
    found = section(document, "instance")

    # assert
    assert found.blame == "instance"
    assert found.got is None
    assert found.data == {}


def test_a_step_declared_null_answers_exactly_like_an_absent_one():
    """`build:` with no value has always reached a reader as None through `.get()`, and every one of them
    treated it as 'not declared'. The walk keeps that, so no reader changes behaviour on a bare key."""
    # arrange
    document = {"build": None}

    # act
    found = section(document, "build")

    # assert
    assert (found.blame, found.got) == ("build", None)


def test_a_step_declared_as_something_else_is_blamed_and_hands_back_what_it_held():
    """`got` is what a caller's 'got {type}' sentence prints. Without it `tasks/buildfiles.py` could not
    say which shape arrived, which is the half of its message that identifies the typo."""
    # arrange
    document = {"build": 5}

    # act
    found = section(document, "build")

    # assert
    assert (found.blame, found.got) == ("build", 5)
    assert type(found.got).__name__ == "int"


def test_a_nested_path_walks_both_steps():
    # arrange
    document = {"build": {"targets": {"core": {"kind": "lib"}}}}

    # act
    found = section(document, "build", "targets")

    # assert
    assert found.data == {"core": {"kind": "lib"}}
    assert found.blame == ""


def test_a_typo_in_the_OUTER_key_blames_the_outer_key_not_the_inner_one():
    """si#175's first ask. `buidl: targets:` is a typo in `build`, and a walk that reported `targets` as
    absent would send the reader looking inside a section that is not there."""
    # arrange
    document = {"buidl": {"targets": {"core": {}}}}

    # act
    found = section(document, "build", "targets")

    # assert
    assert found.blame == "build"


def test_a_malformed_inner_step_blames_the_inner_key():
    # arrange: `targets: core` is a plausible typo for `core: { depends: [...] }`
    document = {"build": {"targets": "core"}}

    # act
    found = section(document, "build", "targets")

    # assert
    assert (found.blame, found.got) == ("targets", "core")


def test_an_absent_inner_step_is_told_apart_from_a_malformed_one():
    """The distinction `tasks/buildfiles.py` decides on: a `build:` that exists for the product's own
    reason and declares no `targets:` means what an absent `build:` means, while a `targets:` of the
    wrong shape is refused."""
    # arrange
    document = {"build": {"packer": {"cpus": 4}}}

    # act
    found = section(document, "build", "targets")

    # assert
    assert found.blame == "targets"
    assert found.got is None


def test_the_walk_never_raises_on_a_document_of_any_shape():
    """The accessor is a QUESTION. Every refusal in the kernel's manifest path is raised by the reader
    that wanted the section, in its own words - which is what `tests/test_refusal_census.py` counts and
    pins, and why this function carries no `raise` at all."""
    # arrange
    shapes = [{}, {"a": []}, {"a": {"b": 3}}, {"a": "text"}]

    # act / assert
    for document in shapes:
        assert section(document, "a", "b").blame in ("a", "b")


def test_an_empty_path_hands_the_document_back_unchanged():
    """The degenerate case, held so a caller that builds its path from a variable gets the document
    rather than a blame on a step nobody named."""
    # arrange
    document = {"product": "demo"}

    # act
    found = section(document)

    # assert
    assert found == Section(document, "", None)
