"""The release workflow derived through the firn workflow model (si#862, task 1).

The release job used to be assembled from `workflowgen`'s own dataclasses by `workflowgen._release`, beside
the model every other derived workflow is built from. It is now a `workflowschema.Workflow`, built by
`releasepipeline.derive` and converted by `releasepipeline.to_workflow`, as `cipipeline` does for ci.yml.
`test_release_workflow.py` holds the rendered file byte-identical to the one the old path wrote.

AAA throughout.
"""
import pytest
import yaml

from simplon.manifest import catalogue as catalogue_mod
from simplon.manifest import load as manifest_mod
from simplon.model import workflowschema
from simplon.tasks import releasepipeline, workflowgen

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"


def _simplon():
    text = MANIFEST.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    entry = next(w for w in workflowgen.parse(data) if w.release)
    return manifest_mod.load(text, catalogue=catalogue_mod.load()), data, entry


def test_the_release_is_a_model_instance():
    # arrange
    manifest, data, entry = _simplon()

    # act
    model = releasepipeline.derive(manifest, data, entry)

    # assert
    assert isinstance(model, workflowschema.Workflow)
    (trigger,) = model.trigger
    inputs = {i.input_name: i for i in trigger.dispatch_input}
    assert list(inputs) == ["version", "dry_run"]
    assert (inputs["version"].input_type, inputs["version"].required) == ("string", True)
    assert (inputs["dry_run"].input_type, inputs["dry_run"].required,
            inputs["dry_run"].default_value) == ("boolean", True, "true")
    (job,) = [job for job in model.job if job.key == "release"]
    assert {p.scope: p.access for p in job.permission} == {"contents": "write", "packages": "write"}
    assert job.timeout_minutes == workflowgen.RELEASE_TIMEOUT_MINUTES


def test_the_old_path_is_gone():
    # act / assert
    assert not hasattr(workflowgen, "_release")
    assert not hasattr(workflowgen, "_RELEASE_TRIGGER")


def test_a_release_entry_is_not_rendered_without_its_derived_job():
    """si#862: `render` no longer derives the release job, so an entry handed to it underived would be a release.yml
    with no release job in it; it is refused instead."""
    # arrange
    manifest, data, entry = _simplon()

    # act / assert
    with pytest.raises(ValueError, match="rendered from `releasepipeline.to_workflow`"):
        workflowgen.render(entry, manifest=manifest, product="simplon", source="simplon.yaml", artifacts={})
