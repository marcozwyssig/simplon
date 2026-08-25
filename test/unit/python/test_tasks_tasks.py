"""Unit tests for delivery.tasks.tasks (netctl#1444): the two verbs that make the task machinery
addressable - `generate` (write the product's committed CLI module) and `catalogue` (print the coordinate
space).

The generator itself is covered by test_taskgen.py. What is asserted here is the seam: that the verbs read
the product's root, manifest and manifest FILENAME from `delivery.context` rather than knowing a product,
that `--check` reports drift as a non-zero exit so one command serves both a gate and a hook, and that the
listing survives a product importing nothing.

AAA throughout, including the negative cases.
"""
import textwrap

import pytest

from delivery import context
from delivery.tasks import tasks

_MANIFEST = """
groups:
  support.git:
    push: { impl: "delivery.test_impls:nullary", help: "Push." }
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
    # because the reference lives in the KERNEL's delivery.yaml, never in this file.
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
    assert "support (reached)" not in out
    assert "test (reached)" not in out


def test_catalogue_marks_a_namespace_reached_via_a_raw_impl_naming_a_kernel_module(
        tmp_path, monkeypatch, capsys):
    # arrange: `test` mid-migration (netctl#1469 plan 2, task 3) - `build` has converted to a command
    # tree, `test` has not, and `report` inlines the kernel's module path directly as `impl:` rather than
    # naming `task: "test:report"` (a group converts as a whole, so this is the accepted exception while
    # the group stays old-form). There is no `task:` coordinate anywhere for `report` - `test` is reached
    # only because the ASSEMBLED command still resolves to the same impl the catalogue's `test:report`
    # coordinate names.
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(textwrap.dedent("""
        tasks:
          local-task: { impl: "demo.tooling:noop", help: "Do nothing." }
        groups:
          build:
            commands:
              noop: { task: local-task, help: "Do nothing." }
          test:
            report: { impl: "delivery.tasks.testrun:report_cmd", help: "Merge results." }
        generate: [build]
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
    assert "support (reached)" not in out


def test_catalogue_marks_a_namespace_placed_via_the_old_import_mechanism(tmp_path, monkeypatch, capsys):
    # arrange: the pre-#1469 mechanism, still live for as long as a migration takes - `import:` makes a
    # namespace's coordinates available, and a bare `tasks:` entry keyed by the coordinate PLACES one
    # (`_expand_imports`). Wholly old-form (no `groups:` node uses tree keys), so the platform's own
    # command-tree merge never runs and cannot be the reason `vcs` shows up here.
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(textwrap.dedent("""
        import:
          delivery: [vcs]
        tasks:
          vcs:push: { group: support }
        groups:
          build:
            frr-image: { impl: "delivery.test_impls:nullary", help: "Build the FRR image." }
        generate: [build]
        env_groups: []
    """), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(
        name="sample", root=tmp_path, manifest_path=manifest_path))

    # act
    rc = tasks.catalogue()

    # assert: reached because the import was actually PLACED, not merely declared - and none of the
    # command-tree-only namespaces leak in, because no group here is a command tree
    out = capsys.readouterr().out
    assert rc == 0
    assert "vcs (reached)" in out
    assert "tasks (reached)" not in out
    assert "test (reached)" not in out
    assert "support (reached)" not in out


def test_catalogue_marks_nothing_for_a_product_that_reaches_no_coordinate(product, capsys):
    # arrange: naming no coordinate is a legitimate state - netctl's own manifest is in it - so the
    # listing is still printed rather than failing on a missing section. Negative case: a namespace
    # nothing reaches must stay unmarked, otherwise a fix that marked every namespace would pass too.
    # act
    rc = tasks.catalogue()

    # assert
    assert rc == 0
    assert "(reached)" not in capsys.readouterr().out
