"""The product's `runner:` section, read by `simplon.tasks.cipipeline` (si#858)."""
from __future__ import annotations

import textwrap

import pytest
import yaml

from simplon.manifest import artifactsection, catalogue, load as manifest_mod
from simplon.model import workflowschema
from simplon.tasks import cipipeline, workflowgen


def test_no_runner_means_github_ubuntu() -> None:
    runner, labels = cipipeline.runner_of({})
    assert runner.kind == "github-ubuntu"
    assert labels == ("ubuntu-latest",)


def test_a_self_hosted_runner_names_its_labels() -> None:
    runner, labels = cipipeline.runner_of({"runner": {"kind": "self-hosted-debian", "labels": "ghr-8"}})
    assert runner.kind == "self-hosted-debian"
    assert labels == ("ghr-8",)


def test_a_self_hosted_runner_without_labels_is_refused() -> None:
    with pytest.raises(ValueError, match="carries no label of its own"):
        cipipeline.runner_of({"runner": "self-hosted-debian"})


# --- the leaves, and their order (si#858 task 5) ---------------------------------------------------------

_HEAD = """
tasks:
  ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
artifacts:
  doc: { kind: file, path: build/doc.txt }
  note: { kind: file, path: build/note.txt, registry: ghcr.io/o/note }
  img: { kind: image, dockerfile: Dockerfile, context: ., registry: ghcr.io/o, repository: img }
"""


def _text(body: str) -> str:
    return _HEAD + textwrap.dedent(body)


def _load(body: str):
    return manifest_mod.load(_text(body), catalogue=catalogue.load(), manifest_path="demo.yaml")


_DECLARED = artifactsection.declared(yaml.safe_load(_HEAD))


def _words(selection) -> list[str]:
    return [leaf.words for leaf in selection.leaves]


def test_leaves_come_in_manifest_order():
    loaded = _load("""
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
              two: { task: ship, unattended: true }
          test:
            commands:
              three: { task: ship, unattended: true }
        """)
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED)) == ["build one", "build two", "test three"]


_PORTS = """
        ci:
          build:
            commands:
              t-consume: { task: "toolchain:run", unattended: true, consumes: { source: doc } }
              a: { task: ship, unattended: true }
              b-produce: { task: "toolchain:run", unattended: true, produces: { out: doc } }
              c: { task: ship, unattended: true }
        """


def test_a_consumer_moves_after_its_producer_and_nothing_else_moves():
    loaded = _load(_PORTS)
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED)) == [
        "build a", "build b-produce", "build t-consume", "build c"]


def test_aggregates_are_not_leaves():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              all: { depends_on: [one], help: "All." }
        """)
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED)) == ["test one"]


def test_an_attended_leaf_is_skipped_with_the_reason():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              walk: { task: ship, unattended: false }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED)
    assert _words(selection) == ["test one"]
    assert [(s.words, s.reason) for s in selection.skipped] == [("test walk", cipipeline.ATTENDED)]


def test_a_ci_skip_is_skipped_with_its_reason():
    loaded = _load("""
        ci:
          test:
            commands:
              lab: { task: ship, unattended: true, ci: { skip: "needs the lab" } }
              walk: { task: ship, unattended: false }
              one: { task: ship, unattended: true }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED)
    assert _words(selection) == ["test one"]
    assert [(s.words, s.reason) for s in selection.skipped] == [
        ("test lab", "needs the lab"), ("test walk", cipipeline.ATTENDED)]


def test_an_undeclared_unattended_is_refused():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship }
        """)
    with pytest.raises(ValueError, match="'test one' does not say whether it can run with nobody watching"):
        cipipeline.select(loaded, artifacts=_DECLARED)


def test_a_nested_group_leaf_is_selected():
    nested = catalogue.loads(textwrap.dedent("""
        groups:
          ci:
            transparent: true
            groups:
              build: { help: "Produce the artefacts." }
              test:
                help: "Verify them."
                groups:
                  lab: { help: "Needs the lab." }
        """))
    loaded = manifest_mod.load(_text("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
            groups:
              lab:
                commands:
                  smoke: { task: ship, unattended: true }
        """), catalogue=nested, manifest_path="demo.yaml")
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED)) == ["test one", "test lab smoke"]


def test_cd_groups_are_not_selected():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
        cd:
          deploy:
            commands:
              up: { task: ship, unattended: true }
              walk: { task: ship, unattended: false }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED)
    assert _words(selection) == ["test one"]
    assert selection.skipped == ()


def test_a_port_cycle_is_refused_naming_the_loop():
    loaded = _load("""
        ci:
          build:
            commands:
              pack: { task: "toolchain:run", unattended: true, consumes: { source: img }, produces: { out: doc } }
              image: { task: "toolchain:run", unattended: true, consumes: { source: doc }, produces: { out: img } }
        """)
    with pytest.raises(ValueError, match="cycle") as raised:
        cipipeline.select(loaded, artifacts=_DECLARED)
    for named in ("'build pack'", "'build image'", "'doc'", "'img'"):
        assert named in str(raised.value)


_SKIPPED_PRODUCER = """
        ci:
          test:
            commands:
              t-consume: { task: "test:file", unattended: true, consumes: { file: doc } }
          build:
            commands:
              b-produce:
                { task: "build:fetch", unattended: true, produces: { file: doc }, ci: { skip: "needs the lab" } }
        """


def test_a_consumer_of_a_skipped_producer_is_refused():
    loaded = _load(_SKIPPED_PRODUCER)
    with pytest.raises(ValueError, match="'test t-consume' consumes 'doc'.*'build b-produce'.*needs the lab"):
        cipipeline.select(loaded, artifacts=_DECLARED)


def test_an_artifact_with_a_registry_is_exempt_when_the_registry_is_known():
    body = _SKIPPED_PRODUCER.replace("file: doc", "file: note")
    loaded = _load(body)
    artifacts = artifactsection.declared(yaml.safe_load(_text(body)))
    assert _words(cipipeline.select(loaded, artifacts=artifacts)) == ["test t-consume"]
    with pytest.raises(ValueError, match="consumes 'note'"):
        cipipeline.select(loaded, artifacts={})


def test_a_skip_wins_over_an_undeclared_unattended():
    loaded = _load("""
        ci:
          test:
            commands:
              lab: { task: ship, ci: { skip: "needs the lab" } }
              one: { task: ship, unattended: true }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED)
    assert _words(selection) == ["test one"]
    assert [(s.words, s.reason) for s in selection.skipped] == [("test lab", "needs the lab")]


def test_a_consumer_whose_only_producer_is_in_cd_is_refused():
    loaded = _load("""
        ci:
          test:
            commands:
              t-consume: { task: "test:file", unattended: true, consumes: { file: doc } }
        cd:
          deploy:
            commands:
              b-produce: { task: "toolchain:run", unattended: true, produces: { out: doc } }
        """)
    with pytest.raises(ValueError, match="'test t-consume' consumes 'doc'.*'deploy b-produce'.*not a CI leaf "
                                         r"\(it is in the 'deploy' group\)"):
        cipipeline.select(loaded, artifacts=_DECLARED)


def test_a_leaf_that_consumes_what_it_produces_is_a_one_leaf_cycle():
    loaded = _load("""
        ci:
          build:
            commands:
              loop: { task: "toolchain:run", unattended: true, consumes: { source: doc }, produces: { out: doc } }
        """)
    with pytest.raises(ValueError, match="cycle.*'build loop' consumes 'doc' from 'build loop'"):
        cipipeline.select(loaded, artifacts=_DECLARED)


# --- the derived workflow, as a model and as a rendered file (si#858 task 6) -----------------------------

_SUITES = """
suites:
  reports: tests/reports
  gates:
    - { name: unit, command: "test one", results: clear }
"""

_SELF_HOSTED = """
runner: { kind: self-hosted-debian, labels: ghr-8 }
support:
  commands:
    ci-docker-preflight: { task: "support:ci-docker-preflight" }
    ci-disk-preflight: { task: "support:ci-disk-preflight" }
    ci-disk-cleanup: { task: "support:ci-disk-cleanup" }
"""

_TOOLCHAINS = """
toolchains:
  - python
"""


def _rendered(body: str, *extra: str) -> tuple[dict, str]:
    """The derived ci.yml for `_HEAD` + `body` + `extra`, rendered and read back."""
    text = _text(body) + "".join(textwrap.dedent(part) for part in extra)
    loaded = manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")
    data = yaml.safe_load(text)
    workflow = cipipeline.to_workflow(cipipeline.derive(loaded, data), loaded, data)
    out = workflowgen.render(workflow, manifest=loaded, product="demo", source="demo.yaml",
                             artifacts={}, reports="tests/reports")
    return yaml.safe_load(out), out


def _steps(doc: dict) -> list[dict]:
    return [step for step in doc["jobs"]["ci"]["steps"] if step.get("name") != workflowgen.REAP_NAME]


def _runs(doc: dict) -> list[str]:
    return [step["run"].removeprefix("exec ./demo.sh ") for step in _steps(doc) if "run" in step]


def _step(doc: dict, words: str) -> dict:
    return next(step for step in _steps(doc) if step.get("run") == f"exec ./demo.sh {words}")


_THREE = """
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
          test:
            commands:
              two: { task: ship, unattended: true }
              three: { task: ship, unattended: true }
        """


def test_the_derived_job_runs_every_leaf_in_order():
    loaded = _load(_PORTS)
    doc, _ = _rendered(_PORTS)
    assert _runs(doc) == _words(cipipeline.select(loaded, artifacts=_DECLARED))


def test_every_leaf_after_the_first_runs_unless_cancelled():
    doc, _ = _rendered(_THREE)
    assert _runs(doc) == ["build one", "test two", "test three"]
    assert "if" not in _step(doc, "build one")
    assert _step(doc, "test two")["if"] == "${{ !cancelled() }}"
    assert _step(doc, "test three")["if"] == "${{ !cancelled() }}"


def test_a_red_preparation_stops_the_leaves():
    doc, _ = _rendered(_THREE, _SELF_HOSTED, _TOOLCHAINS)
    assert _runs(doc)[:3] == ["support ci-docker-preflight", "support ci-disk-preflight", "support install"]
    prepared = [_step(doc, words) for words in _runs(doc)[:3]]
    assert [step["id"] for step in prepared] == ["prepare_docker", "prepare_disk", "prepare_install"]
    assert all("if" not in step for step in prepared)
    assert "if" not in _step(doc, "build one")
    gate = ("${{ !cancelled() && steps.prepare_docker.outcome == 'success' && "
            "steps.prepare_disk.outcome == 'success' && steps.prepare_install.outcome == 'success' }}")
    assert _step(doc, "test two")["if"] == gate
    assert _step(doc, "test three")["if"] == gate
    cleanup = _step(doc, "support ci-disk-cleanup")
    assert cleanup["if"] == "always()" and cleanup["continue-on-error"] is True
    assert _runs(doc)[-1] == "support ci-disk-cleanup"


def test_the_report_runs_last_and_always():
    body = """
        ci:
          test:
            commands:
              report: { task: "test:report" }
              one: { task: ship, unattended: true }
              two: { task: ship, unattended: true }
        """
    doc, _ = _rendered(body, _SUITES)
    assert _runs(doc) == ["test one", "test two", "test report"]
    steps = _steps(doc)
    report = steps.index(_step(doc, "test report"))
    upload = steps[report + 1]
    assert steps[report]["if"] == "always()"
    assert upload["uses"] == workflowgen.UPLOAD_ACTION
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "allure-report"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["path"] == "tests/reports/*.html"


def test_install_comes_first_when_the_product_declares_toolchains():
    doc, _ = _rendered(_THREE, _TOOLCHAINS)
    assert _runs(doc)[0] == "support install"
    assert _step(doc, "support install")["id"] == "prepare_install"
    assert _step(doc, "test two")["if"] == "${{ !cancelled() && steps.prepare_install.outcome == 'success' }}"


def test_no_install_without_toolchains():
    doc, _ = _rendered(_THREE)
    assert "support install" not in _runs(doc)


def test_every_skipped_leaf_is_named_with_its_reason_in_the_file():
    body = """
        ci:
          test:
            commands:
              lab: { task: ship, unattended: true, ci: { skip: "needs the lab" } }
              walk: { task: ship, unattended: false }
              one: { task: ship, unattended: true }
        """
    doc, text = _rendered(body)
    assert _runs(doc) == ["test one"]
    comment = " ".join(line.strip().removeprefix("#").strip() for line in text.splitlines()
                       if line.strip().startswith("#"))
    assert "`test lab` - needs the lab" in comment
    assert f"`test walk` - {cipipeline.ATTENDED}" in comment
    assert comment.index("`test lab`") < comment.index("`test walk`")
    assert "manifest order" in comment


def test_the_job_is_keyed_ci_and_runs_on_the_product_runner():
    doc, _ = _rendered(_THREE, _SELF_HOSTED)
    assert list(doc["jobs"]) == ["ci"]
    assert doc["jobs"]["ci"]["runs-on"] == "ghr-8"
    assert doc["jobs"]["ci"]["env"]["DELIVERY_DOCKER_BOOTSTRAP"] == "1"


def test_the_model_carries_the_steps_and_no_conditions():
    text = _text(_THREE)
    loaded = manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")
    derivation = cipipeline.derive(loaded, yaml.safe_load(text))
    assert derivation.model.path == cipipeline.PATH
    (job,) = derivation.model.job
    assert job.key == cipipeline.JOB
    assert job.runner.kind is workflowschema.RUNNER_KINDS["github-ubuntu"]
    assert [step.command for step in job.step] == [leaf.spec for leaf in derivation.selection.leaves]
    assert [t.event for t in derivation.model.trigger] == ["pull_request", "push_main", "dispatch"]


@pytest.mark.parametrize("body", [
    """
        ci:
          test:
            commands:
              walk: { task: ship, unattended: false }
              lab: { task: ship, unattended: true, ci: { skip: "needs the lab" } }
              all: { depends_on: [walk], help: "All." }
        """,
    """
        cd:
          deploy:
            commands:
              up: { task: ship, unattended: true }
        """,
])
def test_a_product_with_no_runnable_leaf_is_refused(body):
    text = _text(body)
    loaded = manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")
    with pytest.raises(ValueError, match="no leaf a machine may run") as raised:
        cipipeline.derive(loaded, yaml.safe_load(text))
    assert "green tick over nothing" in str(raised.value)
    if "walk" in body:
        assert "`test`" in str(raised.value) and "`test walk`" in str(raised.value)


def test_the_release_archive_is_unchanged():
    upload = workflowgen.report_upload("tests/reports/")
    assert upload.verbatim == {"uses": workflowgen.UPLOAD_ACTION, "if": "always()",
                               "with": {"name": workflowgen.RELEASE_ARCHIVE, "path": "tests/reports/*.html",
                                        "if-no-files-found": "error", "retention-days": 90}}
