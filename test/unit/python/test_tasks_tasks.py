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


def test_catalogue_marks_the_namespaces_a_task_coordinate_actually_reaches(tmp_path, monkeypatch, capsys):
    # arrange: a new-form command tree naming a platform coordinate under `task:` (netctl#1469 plan 2) -
    # the marker no longer comes from a separate `import:` declaration
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
    assert "vcs (imported)" in out
    assert "test (imported)" not in out


def test_catalogue_marks_nothing_for_a_bare_task_name_with_no_namespace(tmp_path, monkeypatch, capsys):
    # arrange: a `task:` naming a task the manifest defines ITSELF carries no colon and no namespace -
    # only a platform coordinate is a namespace reference
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

    # assert
    assert rc == 0
    assert "(imported)" not in capsys.readouterr().out


def test_catalogue_marks_nothing_for_a_product_that_imports_no_coordinate(product, capsys):
    # arrange: naming no coordinate is a legitimate state - netctl's own manifest is in it - so the
    # listing is still printed rather than failing on a missing section
    # act
    rc = tasks.catalogue()

    # assert
    assert rc == 0
    assert "(imported)" not in capsys.readouterr().out
