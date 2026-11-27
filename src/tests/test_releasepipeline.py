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
    assert {p.scope: p.access for p in job.permission} == {"contents": "write", "packages": "write", "actions": "read"}
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
    assert doc["jobs"]["release"]["permissions"] == {"contents": "write", "id-token": "write", "packages": "write", "actions": "read"}
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
    ("    permissions: { id-token: write }\n", {"id-token": "write", "contents": "write", "packages": "write", "actions": "read"}),
    ("    note: the release\n", {"contents": "write", "packages": "write", "actions": "read"}),
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


# --- si#862 task 4: `website: { pages: release, by: }` derives the docs and pages jobs (si#851) ---------------

#: A ReleaseCommand, the site's leaves under `ci: build:` with the aggregate that plans both, and the switch.
WEB = PRODUCT.replace("ci:\n", """ci:
  build:
    commands:
      reference: { task: "docs:reference", with: { output: site/content/ref.md, title: Ref } }
      site: { task: "docs:site" }
      docs: { help: "The site.", depends_on: [reference, site] }
""", 1) + """tasks:
  ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
website: { image: "hugomods/hugo:exts-0.148.2", pages: release, by: "build docs" }
"""

#: Two jobs the product declares beside the release, as simplon's `publish` and `image` (D12, until #789).
DECLARED = """workflows:
  release:
    jobs:
      publish: { needs: release, runs-on: ubuntu-latest, steps: [{ run: echo publish }] }
      image: { needs: publish, runs-on: ubuntu-latest, steps: [{ run: echo image }] }
"""

_REAP = workflowgen.REAP_NAME


def _uses(job) -> list[str]:
    return [str(step.get("uses", "")) for step in job["steps"]]


#: `website: after:` names the declared release jobs `docs` waits for (Marco, 2026-11-26).
AFTER = WEB.replace('by: "build docs" }', 'by: "build docs", after: [publish, image] }')


def test_pages_release_derives_docs_after_the_named_jobs_and_pages_after_docs():
    """(a) `docs` waits for `release` and the declared release jobs `after:` names, in its order, and uploads the
    declared output LAST; `pages` deploys it alone."""
    # act
    doc = _rendered(AFTER, DECLARED)

    # assert
    jobs = doc["jobs"]
    assert list(jobs) == ["release", "publish", "image", "docs", "pages"]
    docs, pages = jobs["docs"], jobs["pages"]
    assert docs["needs"] == ["release", "publish", "image"]
    assert docs["runs-on"] == jobs["release"]["runs-on"]
    assert docs["permissions"] == {"contents": "read"}
    assert docs["env"] == {"RELEASE_VERSION": "${{ inputs.version }}"}
    assert docs["steps"][-1] == {"uses": workflowgen.UPLOAD_PAGES_ACTION, "with": {"path": "build/site"}}
    assert "exec ./app.sh build docs" in [step.get("run") for step in docs["steps"]]
    assert pages["runs-on"] == "ubuntu-latest" and pages["needs"] == "docs"
    assert pages["permissions"] == {"pages": "write", "id-token": "write"}
    assert pages["environment"] == {"name": "github-pages", "url": "${{ steps.deployment.outputs.page_url }}"}
    assert pages["concurrency"] == {"group": releasepipeline.PAGES_CONCURRENCY, "cancel-in-progress": False}
    assert pages["steps"] == [
        {"uses": workflowgen.CONFIGURE_PAGES_ACTION, "with": {"enablement": True}},
        {"id": "deployment", "uses": workflowgen.DEPLOY_PAGES_ACTION, "if": "${{ !inputs.dry_run }}"}]


def test_without_declared_jobs_docs_needs_the_release_only():
    """(b)"""
    # act
    doc = _rendered(WEB)

    # assert
    assert list(doc["jobs"]) == ["release", "docs", "pages"]
    assert doc["jobs"]["docs"]["needs"] == "release"


def test_without_after_docs_needs_the_release_only_beside_declared_jobs():
    """Marco, 2026-11-26: a declared job `after:` does not name is not waited for, so a red homebrew-tap (si#638's
    missing secret) does not skip the site."""
    # act
    doc = _rendered(WEB, DECLARED)

    # assert
    assert doc["jobs"]["docs"]["needs"] == "release"


def test_the_declared_jobs_docs_waits_for_are_named_not_stood_in_for():
    """Review of si#862 task 4: a declared job is no model job (a model job has a step), so `docs` names it in
    `needs_declared` beside the model jobs it needs."""
    # arrange
    text = AFTER + DECLARED
    loaded = manifest_mod.load(text, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    data = yaml.safe_load(text)
    entry = next(w for w in workflowgen.parse(data) if w.key == workflowgen.RELEASE_KEY)

    # act
    model = releasepipeline.derive(loaded, data, entry)

    # assert
    docs = next(job for job in model.job if job.key == releasepipeline.DOCS_JOB)
    assert [need.key for need in docs.needs] == ["release"]
    assert docs.needs_declared == ("publish", "image")
    assert all(job.step for job in model.job)


def test_only_the_release_job_computes_the_test_archive(monkeypatch):
    # arrange
    asked = []
    real = workflowgen._release_archive
    monkeypatch.setattr(workflowgen, "_release_archive", lambda *a, **k: asked.append(a) or real(*a, **k))

    # act
    _workflows(WEB)

    # assert
    assert len(asked) == 1


@pytest.mark.parametrize("ci, limit", [(None, workflowgen.RELEASE_TIMEOUT_MINUTES), ("{ timeout_minutes: 45 }", 45)])
def test_the_docs_job_carries_the_releases_time_limit(ci, limit):
    """The docs job builds on the release's machine, so it is bounded like the release job: the release
    aggregate's `ci: timeout_minutes:`, or the release's own limit when unwritten. A run that hangs is no
    verdict."""
    # act
    jobs = _rendered(WEB if ci is None else _with_ci(WEB, ci))["jobs"]

    # assert
    assert jobs["docs"]["timeout-minutes"] == jobs["release"]["timeout-minutes"] == limit


def test_the_release_aggregate_is_looked_up_once_per_workflow(monkeypatch):
    """The jobs are converted with the spec `to_workflow` already holds, not by a lookup per job."""
    # arrange
    asked = []
    real = releasepipeline._the_release
    monkeypatch.setattr(releasepipeline, "_the_release", lambda *a, **k: asked.append(a) or real(*a, **k))
    text = WEB
    loaded = manifest_mod.load(text, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    data = yaml.safe_load(text)
    model = releasepipeline.derive(loaded, data, None)
    asked.clear()

    # act
    releasepipeline.to_workflow(model, loaded, data, None, product="app")

    # assert
    assert len(asked) == 1


def test_the_docs_job_runs_on_the_release_machine_and_pages_on_github_hosted():
    """Plan decision 2: `pages` takes no checkout and starts no container, so it needs none of a self-hosted kind's
    steps and gets no si#756 reap step beside `pages: write`; `docs` runs where the release ran."""
    # arrange
    product = _with_ci(WEB, "{ runner: { kind: self-hosted-debian, labels: ghr-9 } }")

    # act
    jobs = _rendered(product)["jobs"]

    # assert
    assert jobs["docs"]["runs-on"] == "ghr-9" and jobs["docs"]["env"]["DELIVERY_DOCKER_BOOTSTRAP"] == "1"
    assert jobs["pages"]["runs-on"] == "ubuntu-latest"
    assert not any(step.get("name") == _REAP for step in jobs["pages"]["steps"])
    assert not any(use.startswith("actions/checkout") for use in _uses(jobs["pages"]))


def test_after_the_upload_no_step_can_turn_docs_red():
    """si#851: on a kind with a disk the renderer appends its cleanup; it cannot change the verdict."""
    # arrange
    product = _with_ci(WEB, "{ runner: { kind: self-hosted-debian, labels: ghr-9 } }")

    # act
    steps = _rendered(product)["jobs"]["docs"]["steps"]

    # assert
    at = _uses({"steps": steps}).index(workflowgen.UPLOAD_PAGES_ACTION)
    assert all(step.get("continue-on-error") is True for step in steps[at + 1:])


@pytest.mark.parametrize("website", [
    'website: { image: "hugomods/hugo:exts-0.148.2" }\n',
    'website: { image: "hugomods/hugo:exts-0.148.2", base_url: "https://example.test/" }\n',
], ids=["firn", "biz-cockpit"])
def test_a_website_without_pages_derives_neither_job(website):
    """(c) firn's and biz-cockpit's shape: a website deployed elsewhere or nowhere."""
    # arrange
    product = WEB.replace('website: { image: "hugomods/hugo:exts-0.148.2", pages: release, by: "build docs" }\n',
                          website)

    # act
    doc = _rendered(product)

    # assert
    assert list(doc["jobs"]) == ["release"]


def test_only_the_deploy_is_skipped_on_a_dry_run():
    """(d) A rehearsal builds and uploads the site and configures Pages; it deploys nothing."""
    # act
    jobs = _rendered(WEB)["jobs"]

    # assert
    (upload,) = [s for s in jobs["docs"]["steps"] if s.get("uses") == workflowgen.UPLOAD_PAGES_ACTION]
    assert "if" not in upload
    conditions = [(s.get("uses"), s.get("if")) for s in jobs["pages"]["steps"]]
    assert conditions == [(workflowgen.CONFIGURE_PAGES_ACTION, None),
                          (workflowgen.DEPLOY_PAGES_ACTION, "${{ !inputs.dry_run }}")]


def test_the_docs_job_cuts_on_a_rehearsal_and_requires_the_pushed_tag_on_a_real_run():
    """(f) The release job's own cut, and the script simplon's hand-written jobs require the tag with."""
    # act
    steps = _rendered(WEB)["jobs"]["docs"]["steps"]

    # assert
    opening = [s for s in steps if s.get("name") != _REAP and not str(s.get("uses", "")).startswith("actions/")]
    cut, origin, build = opening[:3]
    assert (cut["run"], cut["if"]) == (workflowgen.RELEASE_CUT, "${{ inputs.dry_run }}")
    assert (origin["run"], origin["if"]) == (workflowgen.RELEASE_ON_ORIGIN, "${{ !inputs.dry_run }}")
    assert origin["name"] == "The tag is on origin at this commit"
    assert build["run"] == "exec ./app.sh build docs"


def test_the_origin_script_is_the_one_simplons_release_yml_requires_the_tag_with():
    # arrange
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))

    # act
    scripts = {step["run"] for job in doc["jobs"].values() for step in job["steps"]
               if step.get("name") == "The tag is on origin at this commit"}

    # assert
    assert scripts == {workflowgen.RELEASE_ON_ORIGIN}


def test_the_notes_carry_si851s_lessons():
    # act
    workflow = _workflows(WEB)["release"]

    # assert
    notes = {job.name: job.note for job in workflow.jobs}
    assert "LAST" in notes["docs"] and "si#851" in notes["docs"]
    for said in ("44901604309", "44938156739", "Re-run failed jobs", "delete the run's `github-pages` artifacts first"):
        assert said in " ".join(notes["pages"].split()), said


@pytest.mark.parametrize("product, extra, said", [
    ("product: app\nwebsite: { image: \"hugomods/hugo:exts-0.148.2\", pages: release, by: \"support install\" }\n",
     "", "declares no ReleaseCommand"),
    (WEB, 'workflows:\n  release: { handwritten: "ours" }\n', "is `handwritten:`"),
    (WEB.replace('by: "build docs"', 'by: "build nothing"'), "", "names no command in group 'build'"),
    (WEB.replace('by: "build docs"', 'by: "publish docs"'), "", "names group 'publish', which this manifest"),
    (WEB.replace('by: "build docs"', 'by: "support ship"') + "support:\n  commands:\n    ship: { task: ship }\n",
     "", "does not say whether it can run"),
    (WEB.replace('by: "build docs"', 'by: "support ship"')
     + "support:\n  commands:\n    ship: { task: ship, unattended: false }\n", "",
     "'support ship' cannot run in the docs job unattended"),
    (WEB.replace('by: "build docs"', 'by: "build reference"'), "", "plans no `docs:site` leaf"),
    (WEB, DECLARED.replace("      image:", "      docs:"), "declares a job 'docs'"),
    (WEB, DECLARED.replace("      image:", "      pages:"), "declares a job 'pages'"),
    (WEB.replace('by: "build docs" }', 'by: "build docs", after: [publsh] }'), DECLARED,
     "names 'publsh', which is no job declared beside the release - declared: publish, image"),
    (WEB.replace('by: "build docs" }', 'by: "build docs", after: [publish] }'), "",
     "names 'publish', which is no job declared beside the release - declared: (none)"),
], ids=["no-release-command", "handwritten", "no-such-command", "no-such-group", "unattended-unsaid",
        "attended", "no-site-leaf", "job-docs", "job-pages", "after-misspelt", "after-without-jobs"])
def test_a_pages_switch_the_release_cannot_derive_is_refused(product, extra, said):
    """(e) Each is a DIAGNOSIS: a switch that would derive nothing, or a docs job that would publish a site nobody
    built, never run, or collide with a job of the product's."""
    # act / assert
    with pytest.raises(ValueError) as refused:
        _workflows(product, extra)
    assert said in str(refused.value), str(refused.value)


# --- si#789 task 4a: the producers run once more, on the tag, in the derived `artifacts` job --------------------


def _simplon_jobs() -> dict:
    """simplon's release.yml as the renderer writes it, parsed: the `artifacts` job beside the others."""
    from simplon.manifest import artifactsection
    manifest, data, entry = _simplon()
    release = releasepipeline.to_workflow(releasepipeline.derive(manifest, data, entry), manifest, data, entry,
                                          product="simplon")
    text = workflowgen.render(release, manifest=manifest, product="simplon", source="simplon.yaml",
                              artifacts=artifactsection.declared(data), reports=workflowgen.report_dir(data))
    return yaml.safe_load(text)["jobs"]


def _leaf_runs(job) -> list[str]:
    return [str(step.get("run", "")) for step in job["steps"] if str(step.get("run", "")).startswith("exec ./")]


def test_simplons_producers_on_tag_are_wheel_image_and_its_test():
    """Design 4.3: the leaves whose artifact a release step consumes, and the test whose evidence one consumes.
    The suite, the type gate and the model tests do not run again; the green `main` run is their evidence."""
    # arrange
    manifest, data, _ = _simplon()

    # act
    words = [leaf.words for leaf in releasepipeline.producers_on_tag(manifest, data)]

    # assert
    assert words == ["build wheel", "build image", "test image"]


def test_the_artifacts_job_builds_without_ci_params():
    """No `ci: params:`: the image builds and is tested on every platform the release publishes, so
    `kernel-checked` is about what goes out. The release's own parameter, the tag, is bound as in `release`."""
    # act
    runs = _leaf_runs(_simplon_jobs()[releasepipeline.ARTIFACTS_JOB])

    # assert
    assert runs == ["exec ./simplon.sh build wheel",
                    'exec ./simplon.sh build image --tag "$RELEASE_VERSION"',
                    'exec ./simplon.sh test image --tag "$RELEASE_VERSION"']
    assert not any("--platform" in run for run in runs)


def test_the_artifacts_job_runs_where_the_release_runs():
    """The release aggregate's `ci: { runner: github-ubuntu, emulates: [linux/arm64] }`, not the CI default:
    ghr-8 is LXC and cannot register emulation (#722). The claim Task 3's deleted release-job test made."""
    # act
    jobs = _simplon_jobs()
    job = jobs[releasepipeline.ARTIFACTS_JOB]

    # assert
    assert job["runs-on"] == "ubuntu-latest" == jobs["release"]["runs-on"]
    assert job["needs"] == "release"
    assert job["timeout-minutes"] == jobs["release"]["timeout-minutes"]
    steps = job["steps"]
    qemu = next(i for i, s in enumerate(steps) if s.get("uses") == workflowgen.QEMU_ACTION)
    build = next(i for i, s in enumerate(steps) if str(s.get("run", "")).startswith("exec ./simplon.sh build image"))
    assert steps[qemu]["with"]["platforms"] == "linux/arm64"
    assert qemu < build


def test_the_artifacts_job_cuts_on_a_rehearsal_and_requires_the_tag_on_a_real_run():
    """Design 4.3: a real run builds the pushed tag, a rehearsal cuts it locally; the stamp before the first leaf,
    so the rehearsal also builds with the real version (Review Focus 3)."""
    # act
    steps = _simplon_jobs()[releasepipeline.ARTIFACTS_JOB]["steps"]

    # assert
    runs = [s.get("run") for s in steps]
    cut = runs.index(workflowgen.RELEASE_CUT)
    origin = runs.index(workflowgen.RELEASE_ON_ORIGIN)
    stamp = runs.index(workflowgen.RELEASE_STAMP)
    first = next(i for i, run in enumerate(runs) if str(run).startswith("exec ./simplon.sh build "))
    assert steps[cut]["if"] == "${{ inputs.dry_run }}"
    assert steps[origin]["if"] == "${{ !inputs.dry_run }}"
    assert "if" not in steps[stamp]
    assert cut < origin < stamp < first


def test_a_release_consuming_nothing_built_gets_no_artifacts_job():
    """Review Focus 4: a build leaf whose artifact no release step consumes is not run on the tag, and with
    nothing selected there is no job, rather than a job of kernel steps that builds nothing."""
    # arrange
    product = PRODUCT.replace("artifacts:\n", "artifacts:\n  app-dist: { kind: directory, path: dist }\n", 1).replace(
        "ci:\n", "ci:\n  build:\n    commands:\n      wheel: { task: pack, produces: { directory: app-dist } }\n", 1
    ) + ('tasks:\n  pack: { impl: "simplon.test_impls:nullary", help: "Pack.", unattended: true,\n'
         '          output: { directory: { accepts: directory } } }\n')
    loaded = manifest_mod.load(product, catalogue=catalogue_mod.load(), manifest_path="app.yaml")

    # act
    selected = releasepipeline.producers_on_tag(loaded, yaml.safe_load(product))
    doc = _rendered(product)

    # assert
    assert selected == ()
    assert list(doc["jobs"]) == ["release"]


def test_an_artifact_the_release_workflow_produces_is_not_rebuilt():
    """Design 4.3's rule: whatever a step of release.yml produces is not rebuilt on the tag. `publish` renders the
    formula and tests it after the upload, so the formula's leaves stay out even where ci.yml WOULD run them: the
    `ci: skip:` that keeps them out of ci.yml is taken away here, so only the rule can hold them out."""
    # arrange
    text = MANIFEST.read_text(encoding="utf-8")
    skip = re.compile(r'\n        ci: \{ skip: "needs a tagged commit: the formula[^\n]*')
    assert len(skip.findall(text)) == 2
    candidate = skip.sub("", text)
    manifest = manifest_mod.load(candidate, catalogue=catalogue_mod.load())

    # act
    words = [leaf.words for leaf in releasepipeline.producers_on_tag(manifest, yaml.safe_load(candidate))]

    # assert
    assert "build homebrew-formula" not in words and "test homebrew-formula" not in words
    assert words == ["build wheel", "build image", "test image"]


def test_the_jobs_stand_in_the_order_release_artifacts_declared_website():
    # act
    jobs = list(_simplon_jobs())

    # assert
    assert jobs[:2] == ["release", releasepipeline.ARTIFACTS_JOB]
    assert jobs[-2:] == [releasepipeline.DOCS_JOB, releasepipeline.PAGES_JOB]


def test_what_the_release_aggregate_builds_is_not_rebuilt():
    """An aggregate that still builds and tests what it publishes (the demo product of the golden) has it on the
    tag before `artifacts` would start: the `release` job ran the plan. Rebuilding it would be a second build of
    one artifact in one run."""
    # arrange
    from test_workflowgen import _RELEASE_PRODUCT
    loaded = manifest_mod.load(_RELEASE_PRODUCT, catalogue=catalogue_mod.load(), manifest_path="app.yaml")

    # act
    selected = releasepipeline.producers_on_tag(loaded, yaml.safe_load(_RELEASE_PRODUCT))

    # assert
    assert selected == ()
    assert list(_rendered(_RELEASE_PRODUCT)["jobs"]) == ["release"]


def test_a_handwritten_release_has_no_producers_on_tag():
    """No release.yml is derived, so nothing is run on the tag by the kernel; the same aggregate derived selects
    the build and the test whose evidence it consumes."""
    # arrange
    product = CLOSURE.split("workflows:\n")[0].replace("depends_on: [check, notes, tag]",
                                                       "depends_on: [check, notes, ship, tag]")
    loaded = manifest_mod.load(product, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    derived = yaml.safe_load(product)
    handwritten = {**derived, "workflows": {"release": {"handwritten": "ours"}}}

    # act
    selected = [leaf.words for leaf in releasepipeline.producers_on_tag(loaded, derived)]

    # assert
    assert selected == ["build bin", "test bin"]
    assert releasepipeline.producers_on_tag(loaded, handwritten) == ()


#: A release step that consumes only a test's evidence, and the test consumes a file a build leaf makes: the build
#: is selected through the test, and the evidence crosses to the declared job by the hand-off.
CLOSURE = PRODUCT.replace("artifacts:\n", "artifacts:\n  app-bin: { kind: file, path: build/app.bin }\n"
                          "  app-checked: { kind: test-result, path: build/test/app.json }\n", 1).replace("ci:\n", """ci:
  build:
    commands:
      bin: { task: make, produces: { file: app-bin } }
  test:
    commands:
      bin: { task: check, consumes: { file: app-bin }, produces: { result: app-checked } }
""", 1) + """tasks:
  make: { impl: "simplon.test_impls:nullary", help: "Make.", unattended: true, output: { file: { accepts: file } } }
  check: { impl: "simplon.test_impls:nullary", help: "Check.", unattended: true, input: { file: { accepts: file } },
           output: { result: { accepts: test-result } } }
  ship: { impl: "simplon.test_impls:nullary", help: "Ship.", unattended: true,
          input: { evidence: { accepts: test-result } } }
support:
  commands:
    ship: { task: ship, consumes: { evidence: app-checked } }
workflows:
  release:
    jobs:
      ship: { needs: release, runs-on: ubuntu-latest, steps: [{ command: support ship }] }
"""


def test_the_producer_of_what_a_selected_test_consumes_is_selected_and_the_evidence_crosses():
    # arrange
    from simplon.manifest import artifactsection
    loaded = manifest_mod.load(CLOSURE, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
    data = yaml.safe_load(CLOSURE)

    # act
    words = [leaf.words for leaf in releasepipeline.producers_on_tag(loaded, data)]
    release = _workflows(CLOSURE)["release"]
    jobs = yaml.safe_load(workflowgen.render(release, manifest=loaded, product="app", source="app.yaml",
                                             artifacts=artifactsection.declared(data)))["jobs"]

    # assert
    assert words == ["build bin", "test bin"]
    assert list(jobs) == ["release", releasepipeline.ARTIFACTS_JOB, "ship"]
    assert jobs["ship"]["needs"] == ["release", releasepipeline.ARTIFACTS_JOB]
    assert any(s.get("with", {}).get("name") == "app-checked" for s in jobs[releasepipeline.ARTIFACTS_JOB]["steps"]
               if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert any(s.get("with", {}).get("name") == "app-checked" for s in jobs["ship"]["steps"]
               if str(s.get("uses", "")).startswith("actions/download-artifact"))


@pytest.mark.parametrize("product", [PRODUCT, CLOSURE.split("workflows:\n")[0]], ids=["nothing-selected", "selected"])
def test_a_declared_release_job_named_artifacts_is_refused(product):
    """A DIAGNOSIS, as for `release`, `docs` and `pages`: two jobs under one key, one would silently replace the
    other. Refused whether or not `producers_on_tag` selects anything, so the rule does not hide behind it."""
    # arrange
    extra = """workflows:
  release:
    jobs:
      artifacts: { needs: release, runs-on: ubuntu-latest, steps: [{ run: echo mine }] }
"""

    # act / assert
    with pytest.raises(ValueError) as refused:
        _workflows(product, extra)
    message = str(refused.value)
    assert "declares a job 'artifacts', the name of the derived job that runs the release's producers" in message, \
        message
    assert "rename yours" in message


@pytest.mark.parametrize("old, new, named", [
    # the build leaf may not run unattended, so `producers_on_tag` leaves it out and its file is made nowhere
    ('make: { impl: "simplon.test_impls:nullary", help: "Make.", unattended: true,',
     'make: { impl: "simplon.test_impls:nullary", help: "Make.", unattended: false,', "'app-bin'"),
    # no leaf produces what the release step consumes at all
    ("ship: { task: ship, consumes: { evidence: app-checked } }",
     "ship: { task: ship, consumes: { evidence: app-orphan } }", "'app-orphan'"),
], ids=["only-producer-not-unattended", "no-producer"])
def test_a_release_consumed_artifact_nothing_on_the_tag_produces_is_refused_naming_it(old, new, named):
    """si#789 (4a's silent drop): an artifact a release step consumes that no CI candidate and no release step
    produces is not dropped quietly - generation refuses, naming the artifact and the step that consumes it. The
    refusals are the existing ones (the derived CI's, and `handoff.plan`'s "no job in this workflow produces
    it"); no second rule."""
    # arrange
    from simplon.manifest import artifactsection
    product = CLOSURE.replace(old, new, 1).replace(
        "artifacts:\n", "artifacts:\n  app-orphan: { kind: test-result, path: build/test/orphan.json }\n", 1)
    assert product != CLOSURE

    # act
    with pytest.raises(ValueError) as refused:
        loaded = manifest_mod.load(product, catalogue=catalogue_mod.load(), manifest_path="app.yaml")
        release = _workflows(product)["release"]
        workflowgen.render(release, manifest=loaded, product="app", source="app.yaml",
                           artifacts=artifactsection.declared(yaml.safe_load(product)))

    # assert
    message = str(refused.value)
    assert named in message and ("produces it" in message or "is not run by the CI" in message), message
