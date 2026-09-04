"""Unit tests for delivery.context.bootstrap - the marker walk every scaffolded `paths.py` carried.
AAA throughout, including the negatives that decide whether a broken checkout fails early or late.
"""
import pytest

from delivery import context

_MARKER = """\
product: sample
groups:
  code:
    lint: { impl: "sample.cli:lint", help: "Lint it." }
env_groups: []
"""


def test_the_root_is_the_directory_holding_the_products_manifest(monkeypatch, tmp_path):
    # arrange: the adapter package sits several levels below the marker
    monkeypatch.delenv(context.ROOT_ENV, raising=False)
    monkeypatch.delenv(context.MANIFEST_ENV, raising=False)
    (tmp_path / "sample.yaml").write_text(_MARKER)
    deep = tmp_path / "deploy" / "provision" / "orchestrator" / "src"
    deep.mkdir(parents=True)

    ctx = context.bootstrap("sample", deep)

    assert ctx.root == tmp_path
    assert ctx.manifest_path == tmp_path / "sample.yaml"


def test_the_marker_defaults_to_the_products_own_name(monkeypatch, tmp_path):
    # arrange: nothing names the file, only the product
    monkeypatch.delenv(context.ROOT_ENV, raising=False)
    monkeypatch.delenv(context.MANIFEST_ENV, raising=False)
    (tmp_path / "othername.yaml").write_text(_MARKER)

    with pytest.raises(RuntimeError, match="sample.yaml"):
        context.bootstrap("sample", tmp_path)


def test_a_named_marker_overrides_the_derived_one(monkeypatch, tmp_path):
    # arrange: a product whose manifest is not named after it
    monkeypatch.delenv(context.ROOT_ENV, raising=False)
    monkeypatch.delenv(context.MANIFEST_ENV, raising=False)
    (tmp_path / "othername.yaml").write_text(_MARKER)

    ctx = context.bootstrap("sample", tmp_path, "othername.yaml")

    assert ctx.manifest_path == tmp_path / "othername.yaml"


def test_a_checkout_without_the_marker_fails_at_import_not_mid_command(monkeypatch, tmp_path):
    # arrange: a partial checkout - the marker is nowhere up the tree
    monkeypatch.delenv(context.ROOT_ENV, raising=False)
    monkeypatch.delenv(context.MANIFEST_ENV, raising=False)
    empty = tmp_path / "nothing" / "here"
    empty.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="is the checkout intact"):
        context.bootstrap("sample", empty)


def test_the_bootstrapped_context_is_the_one_the_kernel_reads_back(monkeypatch, tmp_path):
    # arrange: registration is the whole point - kernel code never receives the context, it looks it up
    monkeypatch.delenv(context.ROOT_ENV, raising=False)
    monkeypatch.delenv(context.MANIFEST_ENV, raising=False)
    (tmp_path / "sample.yaml").write_text(_MARKER)

    bootstrapped = context.bootstrap("sample", tmp_path)

    assert context.current() is bootstrapped


def test_the_delivery_override_still_wins_over_the_walk(monkeypatch, tmp_path):
    # arrange: a relocated checkout points the kernel elsewhere
    (tmp_path / "sample.yaml").write_text(_MARKER)
    monkeypatch.setenv(context.ROOT_ENV, str(tmp_path / "relocated"))
    monkeypatch.delenv(context.MANIFEST_ENV, raising=False)

    ctx = context.bootstrap("sample", tmp_path)

    assert ctx.root == tmp_path / "relocated"
