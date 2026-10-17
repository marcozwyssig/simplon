"""Unit tests for the ProductContext bootstrap convention (netctl#592 Train B): a product hands its ROOT
+ manifest to the kernel through this seam, DELIVERY_* env vars override the derived defaults, and the
kernel reads it back without ever naming a product. AAA throughout; goal-stating names, incl. negatives.
"""
import pytest

from simplon.manifest import context
from simplon.manifest.context import ProductContext

_SAMPLE_MANIFEST = """product: sample
artifacts:
  web: { kind: image, local: "sample:local" }
tasks:
  lint: { impl: "sample.cli:lint", help: "Lint the thing." }

ci:
  test:
    commands:
      lint: { task: "lint" }
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
    assert data["artifacts"]["web"]["local"] == "sample:local"


def test_manifest_parses_and_validates_the_command_taxonomy(tmp_path):
    # arrange: the same manifest, now consumed as the validated command manifest
    manifest_path = tmp_path / "product.yaml"
    manifest_path.write_text(_SAMPLE_MANIFEST, encoding="utf-8")
    ctx = ProductContext("sample", tmp_path, manifest_path)

    # act
    mf = ctx.manifest()

    # assert: the CLI engine gets the parsed taxonomy - the product's own command, plus the baseline
    # commands the kernel's catalogue places in every product (`ctx.manifest()` always passes it, which
    # is exactly what makes the loop the platform's rather than each manifest's)
    assert mf.groups["test"] == ("lint",)
    assert mf.spec_for("test", "lint").help == "Lint the thing."
    assert mf.groups["support.git"][0] == "commit"


def test_manifest_names_the_file_when_the_document_does_not_parse(tmp_path):
    # arrange: a manifest that stopped parsing - the file `load` is handed the TEXT of (si#222)
    manifest_path = tmp_path / "swi.yaml"
    manifest_path.write_text("00# the header comment\n\nproduct: swi\n", encoding="utf-8")
    ctx = ProductContext("swi", tmp_path, manifest_path)

    # act / assert: the file is named, which the text alone cannot say - all every other command is
    # gone at this point, so there is no `--help` left to consult
    with pytest.raises(ValueError) as caught:
        ctx.manifest()
    assert str(manifest_path) in str(caught.value)
    assert "line 3, column 8" in str(caught.value)


_GROUPS_MANIFEST = "product: sample\ngroups:\n  test:\n    commands:\n      lint: { task: lint }\n"


def test_the_cut_message_names_the_launchers_real_paths(monkeypatch, tmp_path):
    """si#344: the loader is handed text and writes `<orch-dir>` and `<kernel image>`; the product's load
    is where the launcher's exports are, so the commands a person copies are the ones that run here."""
    # arrange
    (tmp_path / "image.pin").write_text("# pin\nghcr.io/marcozwyssig/simplon:v0.28.0\n", encoding="utf-8")
    monkeypatch.setenv("LAUNCH_ORCH_DIR", str(tmp_path / "deploy" / "orchestrator"))
    monkeypatch.setenv("LAUNCH_IMAGE_PIN", str(tmp_path / "image.pin"))
    path = tmp_path / "sample.yaml"
    path.write_text(_GROUPS_MANIFEST, encoding="utf-8")

    # act
    with pytest.raises(ValueError) as caught:
        ProductContext("sample", tmp_path, path).manifest()

    # assert: every path relative to the product root the two commands are run from
    message = str(caught.value)
    assert "  venv:      deploy/orchestrator/.venv/bin/simplon manifest migrate sample.yaml\n" in message
    assert "-w /src ghcr.io/marcozwyssig/simplon:v0.28.0 simplon manifest migrate sample.yaml" in message
    # and the subject still names the file the reader has open
    assert message.startswith(f"{path} declares `groups:`")
    # and the cause is not printed twice: the loader's own wording is replaced, not chained
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_a_path_with_no_relative_spelling_leaves_the_placeholder_and_the_cut_message(monkeypatch, tmp_path):
    # arrange: `os.path.relpath` raises across Windows drives; that must not replace the cut's refusal
    monkeypatch.setenv("LAUNCH_ORCH_DIR", str(tmp_path / "deploy" / "orchestrator"))
    monkeypatch.delenv("LAUNCH_IMAGE_PIN", raising=False)

    def no_relative_path(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(context.os.path, "relpath", no_relative_path)
    path = tmp_path / "sample.yaml"
    path.write_text(_GROUPS_MANIFEST, encoding="utf-8")

    # act
    with pytest.raises(ValueError) as caught:
        ProductContext("sample", tmp_path, path).manifest()

    # assert: still the cut, the placeholder left, and the manifest named as the loader named it
    message = str(caught.value)
    assert "declares `groups:`, which si#344 replaced" in message
    assert f"<orch-dir>/.venv/bin/simplon manifest migrate {path}\n" in message


def test_a_placeholder_with_nothing_to_fill_it_is_left_rather_than_emptied(monkeypatch, tmp_path):
    # arrange: no launcher exports (a kernel driven directly), and a pin that names a missing file
    monkeypatch.delenv("LAUNCH_ORCH_DIR", raising=False)
    monkeypatch.setenv("LAUNCH_IMAGE_PIN", str(tmp_path / "absent.pin"))
    path = tmp_path / "sample.yaml"
    path.write_text(_GROUPS_MANIFEST, encoding="utf-8")

    # act
    with pytest.raises(ValueError) as caught:
        ProductContext("sample", tmp_path, path).manifest()

    # assert
    message = str(caught.value)
    assert "<orch-dir>/.venv/bin/simplon manifest migrate sample.yaml" in message
    assert "-w /src <kernel image> simplon manifest migrate" in message


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


_IMPORT_TIME_LOAD = """
import sys
from pathlib import Path
from simplon.manifest import context
ctx = context.set_current(context.ProductContext("sample", Path(sys.argv[1]).parent, Path(sys.argv[1])))
{body}
"""


def _run_a_product_import(tmp_path, body: str):
    """A product's composition root in miniature: register the context the way `paths.py` does, then do
    at module level what the scaffolded `cli.py` does (`_MANIFEST = paths.CONTEXT.manifest()`) - in a
    process of its own, because what is under test is what Python prints when nothing catches it."""
    import subprocess
    import sys

    return subprocess.run([sys.executable, "-c", _IMPORT_TIME_LOAD.format(body=body),
                           str(tmp_path / "sample.yaml")], capture_output=True, text=True, check=False)


def test_a_manifest_refused_at_import_prints_the_diagnosis_without_a_traceback(tmp_path):
    """si#405: the refusal is raised while the product's `cli.py` imports, so no `main` is there to catch
    it; the traceback above it says nothing the diagnosis does not, and buries the line to act on."""
    # arrange
    (tmp_path / "sample.yaml").write_text(_GROUPS_MANIFEST, encoding="utf-8")

    # act
    done = _run_a_product_import(tmp_path, "_MANIFEST = ctx.manifest()")

    # assert: the diagnosis alone, and still a failure - a refused manifest is not "nothing to do"
    assert done.returncode == 1
    assert "Traceback" not in done.stderr
    assert done.stderr.startswith(f"{tmp_path / 'sample.yaml'} declares `groups:`, which si#344 replaced")


def test_every_manifest_diagnosis_at_import_drops_the_traceback_not_only_the_cut(tmp_path):
    # arrange: a manifest that does not parse - a diagnosis that is not the si#344 cut
    (tmp_path / "sample.yaml").write_text("00# the header comment\n\nproduct: sample\n", encoding="utf-8")

    # act
    done = _run_a_product_import(tmp_path, "_MANIFEST = ctx.manifest()")

    # assert
    assert done.returncode == 1
    assert "Traceback" not in done.stderr
    assert "line 3, column 8" in done.stderr


def test_an_exception_that_is_not_a_manifest_refusal_keeps_its_traceback(tmp_path):
    # arrange: the hook a registered context installs must not swallow a real defect's traceback
    (tmp_path / "sample.yaml").write_text(_SAMPLE_MANIFEST, encoding="utf-8")

    # act
    done = _run_a_product_import(tmp_path, "ctx.manifest()\nraise ValueError('a defect, not a diagnosis')")

    # assert
    assert done.returncode == 1
    assert "Traceback" in done.stderr
    assert "ValueError: a defect, not a diagnosis" in done.stderr


def test_a_manifest_refusal_is_still_a_value_error_to_a_caller(tmp_path):
    # arrange: every caller and test that catches the load's ValueError keeps catching it
    path = tmp_path / "sample.yaml"
    path.write_text(_GROUPS_MANIFEST, encoding="utf-8")

    # act
    with pytest.raises(context.ManifestRefused) as caught:
        ProductContext("sample", tmp_path, path).manifest()

    # assert
    assert isinstance(caught.value, ValueError)
