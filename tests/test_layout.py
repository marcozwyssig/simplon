"""Where a product's tree sits, said instead of assumed (si#250).

WHAT IS PINNED HERE IS THE TRAP, not the vocabulary. `workdir:` looks like it names a directory inside
your tree and does not - it is the path the tree is MOUNTED at - and a product that read it the obvious
way got a scaffolded command that ran at the wrong place and said nothing about it. The one place in this
family where that was written down was a comment in the affected product's own manifest.

The other half is that nothing here refuses a tree. Measured over six repositories in this family, six
different layouts; a kernel that prescribed one would refuse five of them and two could not comply at all.
`test_a_product_that_declares_no_layout_runs_exactly_what_it_ran_before` is that promise.

AAA throughout.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from simplon import layout
from simplon.tasks import toolchain


def test_a_product_that_declares_no_layout_runs_exactly_what_it_ran_before() -> None:
    """THE COMPATIBILITY PROMISE, and it is the reason this section could be added at all: six products
    predate it and none of them has a line to write."""
    # act
    declared = layout.declared({})

    # assert
    assert declared == layout.Layout(build_root="", tests="tests")
    assert declared.workdir("/work") == "/work", "byte-for-byte the working directory of yesterday"
    assert (declared.acceptance, declared.reports) == ("tests/acceptance", "tests/reports")


def test_the_build_root_descends_where_workdir_relocates() -> None:
    """THE TRAP, stated as a difference. `workdir: /work/kernel` would mount the whole tree AT
    /work/kernel rather than descend into it - the product root is still the root, and Gradle still runs
    beside the wrong build file. `build_root:` is the key that descends."""
    # arrange
    declared = layout.declared({"layout": {"build_root": "kernel"}})

    # act / assert
    assert declared.workdir("/work") == "/work/kernel"


def test_the_runner_mounts_the_root_and_runs_in_the_build_root(tmp_path) -> None:
    """The two ideas joined at the one seam that had conflated them: the mount is still the product root,
    so the whole tree is visible - which a build that walks up to find its fixtures needs - and only the
    working directory moves."""
    # arrange
    cfg = toolchain.Toolchain(image="gradle:jdk21", argv=["gradle", "assemble"], workdir="/work")

    # act
    line = toolchain.docker_argv(cfg, root=Path("/home/dev/firn"), product="firn", instance="",
                                 extra=[], build_root="kernel")

    # assert
    assert "-v" in line and f"{Path('/home/dev/firn')}:/work" in line, "the ROOT is what is mounted"
    assert line[line.index("-w") + 1] == "/work/kernel"


def test_without_a_build_root_the_line_is_the_one_it_always_was(tmp_path) -> None:
    """The half that must not move. Every scaffolded command in every product goes through here."""
    # arrange
    cfg = toolchain.Toolchain(image="python:3.12", argv=["pytest"], workdir="/src")

    # act
    line = toolchain.docker_argv(cfg, root=Path("/home/dev/p"), product="p", instance="", extra=[])

    # assert
    assert line[line.index("-w") + 1] == "/src"


@pytest.mark.parametrize("value", ["/kernel", "../sibling", "kernel/../.."])
def test_a_path_that_leaves_the_product_root_is_refused(value) -> None:
    """The product root is the only tree the runner mounts, so a path outside it is not there to run in -
    and the container would fail with a message about the IMAGE rather than about the manifest."""
    # act / assert
    with pytest.raises(ValueError) as refused:
        layout.declared({"layout": {"build_root": value}})

    assert "under the product root" in str(refused.value)


def test_a_key_this_section_does_not_read_is_refused_rather_than_ignored() -> None:
    """`build-root:` for `build_root:` would be read as declaring nothing, the command would run at the
    product root, and the product would be back in exactly the silent wrongness this ticket is about."""
    # act / assert
    with pytest.raises(ValueError) as refused:
        layout.declared({"layout": {"build-root": "kernel"}})

    message = str(refused.value)
    assert "build-root" in message and "build_root" in message, (
        f"the refusal has to name both what was written and what is taken: {message}")


def test_a_key_set_to_nothing_is_refused_rather_than_read_as_the_default() -> None:
    """"Leave it out" and "set it to empty" look the same afterwards and are two different statements.
    Refusing the second is what keeps the first meaning something."""
    # act / assert
    with pytest.raises(ValueError) as refused:
        layout.declared({"layout": {"tests": "  "}})

    assert "which says nothing" in str(refused.value)


def test_the_tests_directory_the_product_names_is_the_one_both_readers_use() -> None:
    """netctl's root is `test/`, three other products' is `tests/`. The spelling the KERNEL writes is
    `tests`, decided 2026-09-16; a product that differs says so here instead of working around it in
    every command that touches a path."""
    # arrange / act
    declared = layout.declared({"layout": {"tests": "test"}})

    # assert
    assert (declared.acceptance, declared.reports) == ("test/acceptance", "test/reports")


def test_a_section_that_is_not_a_mapping_is_refused_by_name() -> None:
    # act / assert
    with pytest.raises(ValueError) as refused:
        layout.declared({"layout": "kernel"}, "firn.yaml")

    assert "firn.yaml" in str(refused.value) and "must be a mapping" in str(refused.value)
