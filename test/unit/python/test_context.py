"""Unit tests for the ProductContext bootstrap convention (netctl#592 Train B): a product hands its ROOT
+ manifest to the kernel through this seam, DELIVERY_* env vars override the derived defaults, and the
kernel reads it back without ever naming a product. AAA throughout; goal-stating names, incl. negatives.
"""
import pytest

from delivery import context
from delivery.context import ProductContext

_SAMPLE_MANIFEST = """\
product: sample
images:
  web: sample:local
groups:
  code:
    lint: { impl: "sample.cli:lint", help: "Lint the thing." }
env_groups: []
"""


def test_resolve_uses_the_product_defaults_when_no_env_override(monkeypatch, tmp_path):
    # arrange: neither DELIVERY_* var set
    monkeypatch.delenv(context.ROOT_ENV, raising=False)
    monkeypatch.delenv(context.MANIFEST_ENV, raising=False)
    root = tmp_path / "repo"
    manifest_path = root / "product.yaml"

    # act
    ctx = ProductContext.resolve("sample", root, manifest_path)

    # assert: the product-derived values pass through byte-identical
    assert ctx == ProductContext(name="sample", root=root, manifest_path=manifest_path)


def test_resolve_lets_delivery_env_vars_override_root_and_manifest(monkeypatch, tmp_path):
    # arrange: both DELIVERY_* overrides point elsewhere (a relocated checkout / fixture tree)
    override_root = tmp_path / "relocated"
    override_manifest = tmp_path / "other.yaml"
    monkeypatch.setenv(context.ROOT_ENV, str(override_root))
    monkeypatch.setenv(context.MANIFEST_ENV, str(override_manifest))

    # act
    ctx = ProductContext.resolve("sample", tmp_path / "derived", tmp_path / "derived.yaml")

    # assert: the env overrides win over the product-derived defaults
    assert ctx.root == override_root
    assert ctx.manifest_path == override_manifest


def test_manifest_data_reads_the_raw_product_sections(tmp_path):
    # arrange: a manifest carrying product build-data the CLI engine ignores
    manifest_path = tmp_path / "product.yaml"
    manifest_path.write_text(_SAMPLE_MANIFEST, encoding="utf-8")
    ctx = ProductContext("sample", tmp_path, manifest_path)

    # act
    data = ctx.manifest_data()

    # assert: the raw sections are available for the product's own paths adapter
    assert data["product"] == "sample"
    assert data["images"]["web"] == "sample:local"


def test_manifest_parses_and_validates_the_command_taxonomy(tmp_path):
    # arrange: the same manifest, now consumed as the validated command manifest
    manifest_path = tmp_path / "product.yaml"
    manifest_path.write_text(_SAMPLE_MANIFEST, encoding="utf-8")
    ctx = ProductContext("sample", tmp_path, manifest_path)

    # act
    mf = ctx.manifest()

    # assert: the CLI engine gets the parsed taxonomy
    assert mf.groups == {"code": ("lint",)}
    assert mf.spec_for("code", "lint").help == "Lint the thing."


def test_manifest_data_fails_loudly_on_a_missing_file(tmp_path):
    # arrange: a manifest path that does not exist
    ctx = ProductContext("sample", tmp_path, tmp_path / "absent.yaml")

    # act / assert: a clear RuntimeError, never a bare traceback deep in a command
    with pytest.raises(RuntimeError, match="cannot read manifest"):
        ctx.manifest_data()


def test_current_raises_until_a_context_is_registered(monkeypatch):
    # arrange: no context registered in this process
    monkeypatch.setattr(context, "_current", None)

    # act / assert: current() refuses loudly rather than returning a silent None
    with pytest.raises(RuntimeError, match="no ProductContext registered"):
        context.current()


def test_set_current_registers_and_returns_the_context(monkeypatch, tmp_path):
    # arrange
    monkeypatch.setattr(context, "_current", None)
    ctx = ProductContext("sample", tmp_path, tmp_path / "product.yaml")

    # act
    returned = context.set_current(ctx)

    # assert: the same context is registered and handed back for the adapter's one-liner
    assert returned is ctx
    assert context.current() is ctx
