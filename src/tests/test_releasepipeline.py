"""The release workflow derived through the firn workflow model (si#862).

The release job used to be assembled from `workflowgen`'s own dataclasses by `workflowgen._release`, beside
the model every other derived workflow is built from. It is now a `workflowschema.Workflow`, built by
`releasepipeline.derive` and converted by `releasepipeline.to_workflow`, as `cipipeline` does for ci.yml.
`test_release_workflow.py` holds the rendered file equal to the one the old path wrote.

Since si#862 task 3 the release is derived from the ReleaseCommand alone: `workflows: release:` no longer names
the aggregate, its `ci: { runner:, emulates:, timeout_minutes: }` say the machine, the emulation and the time
limit, and the entry only adds jobs beside the derived `release` job.

AAA throughout.
"""
import re

import pytest
import yaml

from simplon.manifest import catalogue as catalogue_mod
from simplon.manifest import load as manifest_mod
from simplon.model import workflowschema
from simplon.tasks import cipipeline, releasepipeline, workflowgen

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"


def _simplon():
    text = MANIFEST.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    entry = next(w for w in workflowgen.parse(data) if w.key == workflowgen.RELEASE_KEY)
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
    assert not hasattr(workflowgen, "_release_key")


# --- si#862 task 3: the release is the ReleaseCommand's -------------------------------------------------------

PRODUCT = """
product: app
artifacts:
  app-notes: { kind: release-notes, path: build/release/notes.md }
  app-tag: { kind: tag }
  app-release: { kind: release }
ci:
  release:
    commands:
      check: { task: "release:check" }
      notes: { task: "release:notes", produces: { release-notes: app-notes } }
      tag: { task: "release:tag", consumes: { release-notes: app-notes }, produces: { tag: app-tag } }
      all:
        depends_on: [check, notes, tag]
        passes: [tag]
        produces: { release: app-release }
        stop_on_failure: true
        help: "The release."
"""


def _with_ci(product: str, ci: str) -> str:
    return product.replace("        stop_on_failure: true\n", f"        stop_on_failure: true\n        ci: {ci}\n")


def _workflows(product: str = PRODUCT, extra: str = "") -> dict[str, workflowgen.Workflow]:
    text = product + extra
    loaded = manifest_mod.load(text, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    return {w.key: w for w in cipipeline.workflows(loaded, yaml.safe_load(text), product="app")}


def _rendered(product: str = PRODUCT, extra: str = "") -> dict:
    text = product + extra
    loaded = manifest_mod.load(text, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    release = _workflows(product, extra)["release"]
    return yaml.safe_load(workflowgen.render(release, manifest=loaded, product="app", source="app.yaml", artifacts={}))


def test_a_release_command_and_no_workflows_entry_derives_release_yml_on_the_product_runner():
    """(a) The ReleaseCommand alone derives release.yml: the dispatch with its two inputs, and the `release` job
    on the product's top-level `runner:`."""
    # arrange
    product = PRODUCT + "runner: { kind: self-hosted-debian, labels: ghr-9 }\n"

    # act
    release = _workflows(product)["release"]
    doc = _rendered(product)

    # assert
    assert release.path == ".github/workflows/release.yml" and release.derived and release.release == "release all"
    assert list(doc[True]["workflow_dispatch"]["inputs"]) == ["version", "dry_run"]
    assert list(doc["jobs"]) == ["release"]
    assert doc["jobs"]["release"]["runs-on"] == "ghr-9"
    assert doc["permissions"] == {"contents": "read"}


def test_without_a_product_runner_the_release_runs_on_github_ubuntu():
    # act
    doc = _rendered()

    # assert
    assert doc["jobs"]["release"]["runs-on"] == "ubuntu-latest"
    assert doc["jobs"]["release"]["timeout-minutes"] == workflowgen.RELEASE_TIMEOUT_MINUTES


def test_the_release_aggregates_ci_names_the_machine_and_the_time_limit():
    # arrange
    product = _with_ci(PRODUCT + "runner: { kind: self-hosted-debian, labels: ghr-9 }\n",
                       "{ runner: { kind: self-hosted-container, labels: firn }, timeout_minutes: 45 }")

    # act
    job = _rendered(product)["jobs"]["release"]

    # assert: the kind's own env beside the version's
    assert job["runs-on"] == "firn" and job["timeout-minutes"] == 45
    assert job["env"] == {"RELEASE_VERSION": "${{ inputs.version }}", "DELIVERY_DOCKER_BOOTSTRAP": "1"}


def test_a_declared_release_entry_adds_its_jobs_after_the_derived_one():
    """(b) `workflows: release:` holds jobs only; they land in release.yml after `release`."""
    # arrange
    extra = """workflows:
  release:
    permissions: { contents: read, id-token: write }
    jobs:
      extra:
        needs: release
        runs-on: ubuntu-latest
        steps: [{ run: echo released }]
"""

    # act
    doc = _rendered(extra=extra)

    # assert
    assert list(doc["jobs"]) == ["release", "extra"]
    assert doc["permissions"] == {"contents": "read", "id-token": "write"}
    assert doc["jobs"]["release"]["permissions"] == {"contents": "write", "id-token": "write", "packages": "write"}
    assert list(doc[True]) == ["workflow_dispatch"]


#: firn's `workflows: release:` as it stands on its main (fetched 2026-11-25), shortened to the keys that matter.
FIRN_ENTRY = {"release": "release all", "timeout_minutes": 120, "runs-on": "firn",
              "env": {"DELIVERY_DOCKER_BOOTSTRAP": "1"},
              "jobs": {"builder": {"needs": "release", "runs-on": "firn", "steps": [{"run": "echo"}]}}}
_JOBS = {"jobs": {"a": {"runs-on": "x", "steps": [{"run": "y"}]}}}


@pytest.mark.parametrize("key, body, said", [
    ("release", {"release": "release all", **_JOBS}, ["`release:` is retired"]),
    ("release", {"emulates": ["linux/arm64"], **_JOBS}, ["`emulates:` is retired"]),
    ("release", {"timeout_minutes": 30, **_JOBS}, ["`timeout_minutes:` is retired"]),
    ("release", {"runs-on": "ubuntu-latest", **_JOBS}, ["`runs-on:` is retired here"]),
    ("release", {"runs_on": "ubuntu-latest", **_JOBS}, ["`runs_on:` is retired here"]),
    ("release", {"runner": "github-ubuntu", **_JOBS}, ["`runner:` is retired here"]),
    ("rel", {"release": "release all", **_JOBS}, ["`release:` is retired"]),
    ("ci", {"on": ["push"], "emulates": ["linux/arm64"], **_JOBS}, ["`emulates:` is retired"]),
    ("ci", {"on": ["push"], "timeout_minutes": 30, **_JOBS}, ["`timeout_minutes:` is retired"]),
    ("release", FIRN_ENTRY, ["`release:` is retired", "`timeout_minutes:` is retired", "`runs-on:` is retired here"]),
], ids=["release", "emulates", "timeout", "runs-on", "runs_on", "runner", "release-elsewhere", "emulates-elsewhere",
        "timeout-elsewhere", "firn"])
def test_a_retired_key_is_refused_naming_its_new_place(key, body, said):
    """(c) Diagnosis: nothing reads these keys any more. Each is named with the place that now says it, all of
    them in one message, so firn's entry learns its whole move from one run."""
    # act
    with pytest.raises(ValueError) as refused:
        workflowgen.parse({"workflows": {key: body}})

    # assert
    message = str(refused.value)
    assert f"workflow '{key}'" in message and "si#862" in message
    for words in said:
        assert words in message, message
    assert ("ReleaseCommand under `ci: release:`" in message) or ("from the ReleaseCommand" in message)
    if "runs-on" in body:
        assert "`ci: { runner: }` on the ReleaseCommand" in message


def test_a_rollouts_machine_is_still_read_under_any_key():
    # act
    (parsed,) = workflowgen.parse({"workflows": {"release": {"on": {"push": None}, "flow": [{"to": "prod"}],
                                                             "runs-on": "ubuntu-latest"}}})

    # assert
    assert parsed.rollout_runs_on == "ubuntu-latest"


def test_emulates_on_a_runner_that_cannot_register_it_is_refused_naming_722():
    """(d) The release job's machine is the product's ghr-8-like LXC runner; `ci: emulates:` cannot register there."""
    # arrange
    product = _with_ci(PRODUCT + "runner: { kind: self-hosted-container, labels: ghr-8 }\n",
                       "{ emulates: [linux/arm64] }")

    # act / assert
    with pytest.raises(ValueError) as refused:
        _workflows(product)
    message = str(refused.value)
    assert "release aggregate 'release all'" in message and "#722" in message
    assert "runner kind `self-hosted-container` cannot register emulation" in message
    assert "`ci: { runner: }`" in message


def test_emulates_with_a_runner_that_can_renders_the_qemu_step():
    # arrange
    product = _with_ci(PRODUCT + "runner: { kind: self-hosted-container, labels: ghr-8 }\n",
                       "{ runner: github-ubuntu, emulates: [linux/arm64] }")

    # act
    steps = _rendered(product)["jobs"]["release"]["steps"]

    # assert
    (qemu,) = [s for s in steps if s.get("uses") == workflowgen.QEMU_ACTION]
    assert qemu["with"]["platforms"] == "linux/arm64"
    assert _rendered(product)["jobs"]["release"]["runs-on"] == "ubuntu-latest"


def test_two_release_commands_are_refused_naming_both():
    """(e) Expression rule: each would derive release.yml."""
    # arrange
    product = PRODUCT.replace("artifacts:\n", "artifacts:\n  app-release2: { kind: release }\n") + """      again:
        depends_on: [check, notes, tag]
        passes: [tag]
        produces: { release: app-release2 }
        stop_on_failure: true
        help: "The release again."
"""

    # act / assert
    with pytest.raises(ValueError, match=re.escape("more than one release aggregate ('release all', 'release again')")):
        _workflows(product)


def test_a_handwritten_release_derives_no_release_yml():
    """(f) `handwritten:` switches the derivation off."""
    # arrange
    extra = 'workflows:\n  release: { handwritten: "ours" }\n'

    # act
    release = _workflows(extra=extra)["release"]

    # assert
    assert not release.generated and not release.derived


def test_a_release_ci_key_beside_a_handwritten_release_is_refused():
    # arrange
    extra = 'workflows:\n  release: { handwritten: "ours" }\n'

    # act / assert
    with pytest.raises(ValueError, match=r"'release all' declares `ci: runner:`.*`handwritten:`.*shape nothing"):
        _workflows(_with_ci(PRODUCT, "{ runner: github-ubuntu }"), extra)


def test_without_a_release_command_a_release_entry_is_an_ordinary_workflow():
    # arrange
    product = "product: app\n"
    extra = ("workflows:\n  release:\n    on: { push: { tags: ['v*'] } }\n"
             "    jobs: { a: { runs-on: x, steps: [{ run: y }] } }\n")

    # act
    release = _workflows(product, extra)["release"]

    # assert
    assert not release.derived and release.on == {"push": {"tags": ["v*"]}}


@pytest.mark.parametrize("extra, complaint", [
    ("    on: [push]\n", "the trigger is derived from the release aggregate 'release all'"),
    ("    concurrency: { group: x }\n", "`concurrency:` is derived from the release aggregate 'release all'"),
    ("    on: [push]\n    flow: [{ to: prod }]\n    runs-on: x\n", "a rollout or a release, not both"),
    ("    jobs: { release: { runs-on: x, steps: [{ run: y }] } }\n", "the derived job is named 'release'"),
    ("    env: { RELEASE_VERSION: x }\n", "RELEASE_VERSION is the dispatch input's"),
    ("    permissions: read-all\n", "is a mapping of scope -> level"),
])
def test_what_the_release_derives_may_not_be_declared_beside_it(extra, complaint):
    # arrange
    jobs = "" if "jobs:" in extra or "flow:" in extra else "    jobs: { a: { runs-on: x, steps: [{ run: y }] } }\n"

    # act / assert
    with pytest.raises(ValueError, match=re.escape(complaint)):
        _workflows(extra="workflows:\n  release:\n" + extra + jobs)


def test_a_release_command_whose_plan_does_not_start_with_the_check_is_refused_at_load():
    """(g) si#487 holds every ReleaseCommand, with no `workflows:` entry naming it."""
    # arrange
    product = PRODUCT.replace("depends_on: [check, notes, tag]", "depends_on: [notes, check, tag]")

    # act / assert
    with pytest.raises(ValueError, match=re.escape("the release aggregate 'release all' (it produces 'app-release' "
                                                   "and derives release.yml) starts its plan with 'notes'")):
        manifest_mod.load(product, catalogue=catalogue_mod.load(), manifest_path="app.yaml")


@pytest.mark.parametrize("entry, expected", [
    ("    permissions: { id-token: write }\n", {"id-token": "write", "contents": "write", "packages": "write"}),
    ("    note: the release\n", {"contents": "write", "packages": "write"}),
], ids=["permissions", "note"])
def test_a_release_entry_without_jobs_shapes_the_derived_release(entry, expected):
    """Review of si#862 task 3: an entry that adds no job but a scope (PyPI's Trusted Publishing needs
    `id-token: write`) is a statement about the derived release, not an empty workflow."""
    # act
    doc = _rendered(extra="workflows:\n  release:\n" + entry)

    # assert
    assert list(doc["jobs"]) == ["release"]
    assert doc["jobs"]["release"]["permissions"] == expected


def test_a_release_entry_without_jobs_and_without_a_release_command_is_refused_naming_it():
    with pytest.raises(ValueError, match=r"`jobs:` must be a non-empty mapping.*ReleaseCommand"):
        _workflows("product: app\n", "workflows:\n  release:\n    permissions: { id-token: write }\n")


def test_each_command_step_of_the_model_carries_its_command_words():
    """Review of si#862 (Task 1, item b): the converter reads the words off the model step, not off a lookup keyed
    by the spec's identity."""
    # arrange
    loaded = manifest_mod.load(PRODUCT, catalogue=catalogue_mod.load(), manifest_path="app.yaml")

    # act
    model = releasepipeline.derive(loaded, yaml.safe_load(PRODUCT), None)

    # assert
    (job,) = model.job
    assert [s.command_words for s in job.step if s.command is not None] == [
        "release check", "release notes", "release tag"]
    assert not hasattr(releasepipeline, "_words")
