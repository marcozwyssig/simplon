"""Unit tests for simplon.tasks.tasks (netctl#1444): the two verbs that make the task machinery
addressable - `generate` (write the product's committed CLI module) and `catalogue` (print the coordinate
space).

The generator itself is covered by test_taskgen.py. What is asserted here is the seam: that the verbs read
the product's root, manifest and manifest FILENAME from `simplon.context` rather than knowing a product,
that `--check` reports drift as a non-zero exit so one command serves both a gate and a hook, and that the
listing survives a product importing nothing.

AAA throughout, including the negative cases.
"""
import textwrap

import pytest

from simplon import context
from simplon.tasks import tasks

# `stamp` rather than any of the catalogue's own git verbs: the catalogue PLACES commit/push/... under
# `support.git`, so reusing one of those names here would be a second body under a placed name - which
# `treeform.merge` refuses by design, and which has nothing to do with what these tests are about.
_MANIFEST = """
tasks:
  stamp: { impl: "simplon.test_impls:nullary", help: "Stamp the tree." }

groups:
  support:
    groups:
      git:
        commands:
          stamp: { task: "stamp" }
generate: [support.git]
env_groups: []
"""


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A throwaway product: a repo root, a manifest with a name of its own, and a registered context."""
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(_MANIFEST, encoding="utf-8")
    ctx = context.ProductContext(name="sample", root=tmp_path, manifest_path=manifest_path)
    monkeypatch.setattr(context, "_current", ctx)
    return ctx


# --- generate -----------------------------------------------------------------------------------------

def test_generate_writes_the_module_at_the_target_the_manifest_pinned(product):
    # arrange: `target` is a manifest-pinned parameter (`with:`), resolved against the product's ROOT -
    # the kernel must not know where a product keeps its generated module
    # act
    rc = tasks.generate("pkg/_generated_cli.py")

    # assert
    assert rc == 0
    assert (product.root / "pkg" / "_generated_cli.py").exists()


def test_generate_names_the_manifest_file_in_the_module_it_writes(product):
    # arrange: the header says which manifest the module came from, and that filename is the CONTEXT's,
    # not a constant - a second product's module must not claim it was generated from netctl.yaml
    # act
    tasks.generate("pkg/_generated_cli.py")

    # assert
    assert "sample.yaml" in (product.root / "pkg" / "_generated_cli.py").read_text(encoding="utf-8")


def test_generate_is_idempotent(product):
    # arrange: a second run must not rewrite an identical file - the drift gate compares TEXT, so a render
    # that varied between runs would make it a permanent false green
    tasks.generate("pkg/_generated_cli.py")
    first = (product.root / "pkg" / "_generated_cli.py").read_text(encoding="utf-8")

    # act
    rc = tasks.generate("pkg/_generated_cli.py")

    # assert
    assert rc == 0
    assert (product.root / "pkg" / "_generated_cli.py").read_text(encoding="utf-8") == first


def test_check_passes_on_a_module_that_agrees_with_the_manifest(product):
    # arrange
    tasks.generate("pkg/_generated_cli.py")

    # act
    rc = tasks.generate("pkg/_generated_cli.py", check=True)

    # assert
    assert rc == 0


def test_check_reports_drift_as_a_failing_exit_code_and_writes_nothing(product):
    # arrange: one command serving both a unit gate and a pre-commit hook is why this returns 1 rather
    # than printing and succeeding
    tasks.generate("pkg/_generated_cli.py")
    target = product.root / "pkg" / "_generated_cli.py"
    target.write_text("# hand-edited\n", encoding="utf-8")

    # act
    rc = tasks.generate("pkg/_generated_cli.py", check=True)

    # assert
    assert rc == 1
    assert target.read_text(encoding="utf-8") == "# hand-edited\n"


def test_check_reports_a_module_that_was_never_generated_rather_than_creating_it(product):
    # arrange: a missing file is drift, not a reason to silently succeed - a gate that generates what it
    # was asked to verify can never fail
    # act
    rc = tasks.generate("pkg/_generated_cli.py", check=True)

    # assert
    assert rc == 1
    assert not (product.root / "pkg" / "_generated_cli.py").exists()




# --- catalogue ----------------------------------------------------------------------------------------

def test_catalogue_prints_every_namespace_the_kernel_offers(product, capsys):
    # arrange / act: the real shipped catalogue, not a fixture - a listing that disagrees with the file is
    # worse than no listing
    rc = tasks.catalogue()

    # assert
    out = capsys.readouterr().out
    assert rc == 0
    for namespace in ("support", "tasks", "test", "vcs"):
        assert namespace in out
    assert "prune-branches" in out


def test_catalogue_marks_the_namespace_a_task_coordinate_reaches(tmp_path, monkeypatch, capsys):
    # arrange: a new-form command tree naming a platform coordinate under `task:` (netctl#1469 plan 2)
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(textwrap.dedent("""
        groups:
          support:
            commands:
              push: { task: "vcs:push", help: "Push." }
        generate: [support]
        env_groups: []
    """), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(
        name="sample", root=tmp_path, manifest_path=manifest_path))

    # act
    tasks.catalogue()

    # assert
    out = capsys.readouterr().out
    assert "vcs (reached)" in out
    assert "test (reached)" not in out


def test_catalogue_marks_a_namespace_the_platform_places_with_no_task_ref_anywhere_in_the_product(
        tmp_path, monkeypatch, capsys):
    # arrange: this product's manifest names not a single platform coordinate - the one command it
    # declares refers to a task it defines ITSELF (no colon, no namespace). But `build` is written as a
    # command TREE, so loading it merges the platform's OWN `groups:` (netctl#1444) onto it - and that
    # block PLACES `support.git.*` and `tasks.catalogue`/`tasks.generate` itself, unconditionally, in
    # every product that has migrated even one group. `vcs` and `tasks` are therefore reached even though
    # this manifest's own text never says so; a walk over the RAW manifest (the bug) cannot see that,
    # because the reference lives in the KERNEL's catalogue.yaml, never in this file.
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(textwrap.dedent("""
        tasks:
          lab-image: { impl: "demo.tooling:image", help: "Build an image." }
        groups:
          build:
            commands:
              frr-image: { task: lab-image, help: "Build the FRR image." }
        generate: [build]
        env_groups: []
    """), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(
        name="sample", root=tmp_path, manifest_path=manifest_path))

    # act
    rc = tasks.catalogue()

    # assert: the platform-placed namespaces are marked, but the bare task itself introduces none of its
    # own - a fix that marked everything once any group migrated would also pass the two lines above, so
    # the two lines below are what actually pin the behaviour down
    out = capsys.readouterr().out
    assert rc == 0
    assert "vcs (reached)" in out
    assert "tasks (reached)" in out
    # `support` joins them, and for the same reason: the kernel's own groups block now PLACES
    # `support:install`. `docs` is the namespace that stays unreached - the kernel declares `docs:render`
    # as a task and places no command for it - so it is what pins the behaviour down here: a fix that
    # marked everything once any group migrated would light `docs` up too.
    assert "support (reached)" in out
    assert "docs (reached)" not in out
    assert "test (reached)" not in out


def test_catalogue_marks_a_namespace_reached_via_a_raw_impl_naming_a_kernel_module(
        tmp_path, monkeypatch, capsys):
    # arrange: a product task that inlines the kernel's module path as its own `impl:` rather than
    # naming `task: "test:report"`. There is no coordinate anywhere for `report` - `test` is reached only
    # because the ASSEMBLED command resolves to the same impl the catalogue's `test:report` coordinate
    # names, which is the case that keeps this listing honest about what a product actually runs.
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(textwrap.dedent("""
        tasks:
          local-task: { impl: "demo.tooling:noop", help: "Do nothing." }
          report: { impl: "simplon.tasks.testrun:report_cmd", help: "Merge results." }

        groups:
          build:
            commands:
              noop: { task: "local-task", help: "Do nothing." }
          test:
            commands:
              report: { task: "report" }
        generate: [test]
        env_groups: []
    """), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(
        name="sample", root=tmp_path, manifest_path=manifest_path))

    # act
    rc = tasks.catalogue()

    # assert
    out = capsys.readouterr().out
    assert rc == 0
    assert "test (reached)" in out
    assert "docs (reached)" not in out


def test_catalogue_marks_a_namespace_a_command_names_a_coordinate_from(tmp_path, monkeypatch, capsys):
    # arrange: the one remaining way in - a command names a coordinate with `task: "vcs:push"`. It is
    # marked because the coordinate is actually PLACED, not merely offered.
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(textwrap.dedent("""
        tasks:
          frr-image: { impl: "simplon.test_impls:nullary", help: "Build the FRR image." }

        groups:
          build:
            commands:
              frr-image: { task: "frr-image" }
          support:
            commands:
              push: { task: "vcs:push" }
        generate: [build]
        env_groups: []
    """), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(
        name="sample", root=tmp_path, manifest_path=manifest_path))

    # act
    rc = tasks.catalogue()

    # assert: `vcs` is reached because a command names one of its coordinates. `docs` is what pins the
    # behaviour down - the kernel declares `docs:render`/`docs:site` and places no command for either, so
    # a fix that marked everything the catalogue offers would light it up too.
    out = capsys.readouterr().out
    assert rc == 0
    assert "vcs (reached)" in out
    assert "docs (reached)" not in out


def test_catalogue_leaves_a_namespace_nothing_reaches_unmarked(product, capsys):
    # arrange: this manifest names not one coordinate - its single command runs a body of its own. What
    # it still reaches is what the CATALOGUE places into every product by merging its own tree (`vcs`,
    # `tasks`, `support`, `release`), and that is the point of the loop being the platform's. So the
    # honest negative is a namespace the catalogue offers and places nothing from: `docs` declares
    # `docs:render`/`docs:site` as tasks only, and `test` likewise. A fix that marked every namespace
    # would light both up.
    # act
    rc = tasks.catalogue()

    # assert
    out = capsys.readouterr().out
    assert rc == 0
    assert "docs (reached)" not in out
    assert "test (reached)" not in out
    assert "vcs (reached)" in out
