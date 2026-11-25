"""The product's `runner:` section, read by `simplon.tasks.cipipeline` (si#858)."""
from __future__ import annotations

import dataclasses
import textwrap

import pytest
import yaml

from simplon.manifest import artifactsection, catalogue, context, load as manifest_mod
from simplon.model import workflowschema
from simplon.tasks import cipipeline, workflowgen
from simplon.tasks import workflows as workflows_task


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
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED, data={})) == ["build one", "build two", "test three"]


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
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED, data={})) == [
        "build a", "build b-produce", "build t-consume", "build c"]


def test_aggregates_are_not_leaves():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              all: { depends_on: [one], help: "All." }
        """)
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED, data={})) == ["test one"]


def test_an_attended_leaf_is_skipped_with_the_reason():
    loaded = _load("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              walk: { task: ship, unattended: false }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED, data={})
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
    selection = cipipeline.select(loaded, artifacts=_DECLARED, data={})
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
        cipipeline.select(loaded, artifacts=_DECLARED, data={})


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
    assert _words(cipipeline.select(loaded, artifacts=_DECLARED, data={})) == ["test one", "test lab smoke"]


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
    selection = cipipeline.select(loaded, artifacts=_DECLARED, data={})
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
        cipipeline.select(loaded, artifacts=_DECLARED, data={})
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
        cipipeline.select(loaded, artifacts=_DECLARED, data={})


def test_an_artifact_with_a_registry_is_exempt_when_the_registry_is_known():
    body = _SKIPPED_PRODUCER.replace("file: doc", "file: note")
    loaded = _load(body)
    artifacts = artifactsection.declared(yaml.safe_load(_text(body)))
    assert _words(cipipeline.select(loaded, artifacts=artifacts, data={})) == ["test t-consume"]
    with pytest.raises(ValueError, match="consumes 'note'"):
        cipipeline.select(loaded, artifacts={}, data={})


def test_a_skip_wins_over_an_undeclared_unattended():
    loaded = _load("""
        ci:
          test:
            commands:
              lab: { task: ship, ci: { skip: "needs the lab" } }
              one: { task: ship, unattended: true }
        """)
    selection = cipipeline.select(loaded, artifacts=_DECLARED, data={})
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
        cipipeline.select(loaded, artifacts=_DECLARED, data={})


def test_a_leaf_that_consumes_what_it_produces_is_a_one_leaf_cycle():
    loaded = _load("""
        ci:
          build:
            commands:
              loop: { task: "toolchain:run", unattended: true, consumes: { source: doc }, produces: { out: doc } }
        """)
    with pytest.raises(ValueError, match="cycle.*'build loop' consumes 'doc' from 'build loop'"):
        cipipeline.select(loaded, artifacts=_DECLARED, data={})


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
    workflow = cipipeline.to_workflow(cipipeline.derive(loaded, data), loaded, data, product="demo")
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
    assert _runs(doc) == _words(cipipeline.select(loaded, artifacts=_DECLARED, data={}))


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


def test_a_consumer_is_skipped_when_its_producer_went_red():
    """si#858 final review: a consumer whose producer failed would go red on the missing file, so one cause
    showed as two red steps. The producer carries an id and the consumer waits for its success; a leaf that
    consumes nothing keeps the plain gate."""
    doc, _ = _rendered(_PORTS)
    assert _runs(doc) == ["build a", "build b-produce", "build t-consume", "build c"]
    assert _step(doc, "build b-produce")["id"] == "leaf_build_b_produce"
    assert "id" not in _step(doc, "build a") and "id" not in _step(doc, "build c")
    assert _step(doc, "build t-consume")["if"] == (
        "${{ !cancelled() && steps.leaf_build_b_produce.outcome == 'success' }}")
    assert _step(doc, "build c")["if"] == "${{ !cancelled() }}"


def test_a_consumer_waits_for_the_preparation_and_its_producer():
    doc, _ = _rendered(_PORTS, _TOOLCHAINS)
    assert _step(doc, "build t-consume")["if"] == (
        "${{ !cancelled() && steps.prepare_install.outcome == 'success' && "
        "steps.leaf_build_b_produce.outcome == 'success' }}")


def test_an_after_all_consumer_still_runs_always():
    body = """
        ci:
          build:
            commands:
              make: { task: "toolchain:run", unattended: true, produces: { out: doc } }
              late: { task: "toolchain:run", unattended: true, after_all: true, consumes: { source: doc } }
        """
    doc, _ = _rendered(body)
    assert _step(doc, "build late")["if"] == "always()"


def test_a_leaf_id_is_unique_in_the_job_and_valid_in_an_expression():
    ids = cipipeline._leaf_ids(["build b-produce", "build b_produce", "test lab.x"])
    assert ids == {"build b-produce": "leaf_build_b_produce", "build b_produce": "leaf_build_b_produce_2",
                   "test lab.x": "leaf_test_lab_x"}


def test_the_trigger_is_rendered_from_the_model():
    """si#858 final review: `derive` stores the triggers in the model, and the file says what the model says,
    so there is one source. The default set renders the kernel's `_CI_TRIGGER` unchanged."""
    text = _text(_THREE)
    loaded = manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")
    data = yaml.safe_load(text)
    derivation = cipipeline.derive(loaded, data)
    assert cipipeline.to_workflow(derivation, loaded, data, product="demo").on == workflowgen._CI_TRIGGER
    only_pr = derivation._replace(model=dataclasses.replace(
        derivation.model, trigger=(workflowschema.Trigger(event="pull_request"),)))
    assert cipipeline.to_workflow(only_pr, loaded, data, product="demo").on == {"pull_request": None}


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


# --- a `generated:` producer and the staleness gate (si#886) ---------------------------------------------

_PRODUCER = """
        ci:
          build:
            commands:
              x: { task: ship, unattended: true }
              other: { task: ship, unattended: true }
          test:
            commands:
              one: { task: ship, unattended: true }
              walk: { task: ship, unattended: false }
%s
        """

#: The `test:generated` leaf, named by a word of the product's own so the derivation has to match the task.
_STALENESS = "              check-contract: { task: \"test:generated\", unattended: true }"


def _generated_by(by: str) -> str:
    return f"""
        generated:
          spec:
            path: build/spec.json
            by: {by}
        """


def test_a_generated_producer_leaves_ci_when_the_staleness_gate_runs():
    """si#886: `test:generated` regenerates every `generated:` entry and compares it with the committed tree, so a
    producer run before it in the same job leaves it comparing the regenerated tree with itself. The derivation
    leaves the producer out and says why under "Left out"."""
    doc, text = _rendered(_PRODUCER % _STALENESS, _generated_by("build x"))
    assert _runs(doc) == ["build other", "test one", "test check-contract"]
    assert ("`build x` - it is the `by:` of a `generated:` entry, which `test check-contract` (`test:generated`) "
            "regenerates and compares with the committed tree itself; run before it in the same job, it would "
            "leave that gate comparing the regenerated tree with itself (si#886)") in _comments(text)
    # "Left out" keeps the manifest's order, as it does for every other reason.
    assert _comments(text).index("`build x`") < _comments(text).index("`test walk`")


def test_a_generated_producer_still_runs_without_the_staleness_gate():
    """si#886: with no `test:generated` leaf nothing compares the tree, so the producer is nothing's blind spot."""
    doc, text = _rendered(_PRODUCER % "", _generated_by("build x"))
    assert _runs(doc) == ["build x", "build other", "test one"]
    assert "si#886" not in text


def test_a_generated_producer_outside_the_ci_leaves_changes_nothing():
    """si#886: a `by:` naming no CI leaf (simplon's `support ...` entries) leaves every leaf where it was."""
    doc, text = _rendered(_PRODUCER % _STALENESS, _generated_by("support completion"))
    assert _runs(doc) == ["build x", "build other", "test one", "test check-contract"]
    assert "si#886" not in text


@pytest.mark.parametrize("section", ["generated: {}\n", "generated:\n  spec: { path: build/spec.json }\n"])
def test_a_malformed_generated_section_is_not_read_without_the_staleness_gate(section):
    """si#886: the section is read only where a `test:generated` leaf runs, so a product without one generates its
    workflows as before, and `test generated` stays the one that refuses the section, at run time."""
    doc, _ = _rendered(_PRODUCER % "", section)
    assert _runs(doc) == ["build x", "build other", "test one"]


# --- a required parameter nothing binds (si#887) -----------------------------------------------------------

#: `build:model-binary` cannot run without `image` and `bootstrap` (`TaskParam.required` in the catalogue).
_BINARY = """
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
              binary: { task: "build:model-binary"%s }
        """


def test_a_leaf_whose_required_parameter_nothing_binds_is_refused():
    """si#887: the body refuses an empty `bootstrap`, so a derived step without it is red on every run. The
    refusal names the command, the parameter and both ways out."""
    with pytest.raises(ValueError) as refused:
        _rendered(_BINARY % ', with: { image: "ghcr.io/o/firn:1" }')
    message = str(refused.value)
    assert "'build binary'" in message and "`build:model-binary`" in message
    assert "`bootstrap`" in message and "`image`" not in message
    assert "`ci: { params: { bootstrap: ... } }`" in message and "`ci: { skip: <why> }`" in message


def test_every_unbound_required_parameter_is_named():
    with pytest.raises(ValueError, match=r"`image`, `bootstrap`"):
        _rendered(_BINARY % "")


def test_a_required_parameter_bound_by_with_renders():
    doc, _ = _rendered(_BINARY % ', with: { image: "ghcr.io/o/firn:1", bootstrap: "false" }')
    assert _runs(doc) == ["build one", "build binary"]


def test_a_required_parameter_bound_by_ci_params_renders():
    doc, _ = _rendered(_BINARY % ', with: { image: "ghcr.io/o/firn:1" }, ci: { params: { bootstrap: "false" } }')
    assert _runs(doc) == ["build one", "build binary --bootstrap false"]


def test_a_skipped_leaf_is_not_asked_for_its_required_parameters():
    """si#887: `ci: { skip: }` is one of the two ways out, so it must be one."""
    doc, _ = _rendered(_BINARY % ', ci: { skip: "built by hand" }')
    assert _runs(doc) == ["build one"]


def test_a_leaf_the_derivation_leaves_out_is_not_asked_for_its_required_parameters():
    """si#887 over si#886: a `generated:` producer the derivation leaves out runs nowhere, so nothing is asked of it."""
    doc, _ = _rendered(_BINARY % "" + """
          test:
            commands:
              check: { task: "test:generated", unattended: true }
        """, _generated_by("build binary"))
    assert _runs(doc) == ["build one", "test check"]


def test_test_unit_without_with_is_refused():
    """si#887, from si#859's review: `paths` and `requirements` have empty defaults in the signature, so "no
    default" would miss them; the body refuses both empty, and the model says so."""
    with pytest.raises(ValueError, match=r"'test unit'.*`test:unit`.*`paths`, `requirements`"):
        _rendered("""
            ci:
              test:
                commands:
                  unit: { task: "test:unit" }
            """)


def test_a_gate_member_whose_required_parameter_nothing_binds_is_refused():
    """si#887: a gate's members run in its own file, and the same step would refuse there."""
    loaded = _load("""
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
          test:
            commands:
              unit: { task: "test:unit" }
              all: { depends_on: [unit], help: "All.", ci: { gate: { label: lab } } }
        """)
    (run,) = cipipeline.gates(loaded)
    with pytest.raises(ValueError, match=r"'test unit'.*`paths`, `requirements`"):
        cipipeline.derive_gate(loaded, {}, run)


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


def test_the_release_archive_uploads_with_report_upload():
    """The release's own archive goes through the extracted `report_upload`; that release.yml's bytes did not
    move is `test_own_workflows.py::test_the_committed_workflows_agree_with_the_manifest`."""
    loaded = _load("""
        ci:
          test:
            commands:
              report: { task: "test:report" }
        """)
    archive, _ = workflowgen._release_archive(loaded, "tests/reports/")
    assert archive[-1] == workflowgen.report_upload("tests/reports/")
    assert archive[-1].verbatim["with"]["path"] == "tests/reports/*.html"


def test_the_derived_workflow_reads_the_repository_and_writes_nothing():
    doc, _ = _rendered(_THREE)
    assert doc["permissions"] == {"contents": "read"}
    assert "permissions" not in doc["jobs"]["ci"]


def test_an_after_all_leaf_that_produces_for_a_leaf_is_refused():
    loaded = _load("""
        ci:
          build:
            commands:
              late: { task: "toolchain:run", unattended: true, after_all: true, produces: { out: doc } }
              use: { task: "toolchain:run", unattended: true, consumes: { source: doc } }
        """)
    with pytest.raises(ValueError, match="'build use' consumes 'doc', which 'build late' produces.*after_all"):
        cipipeline.derive(loaded, {})


def test_a_report_without_suites_names_the_upload():
    body = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              report: { task: "test:report" }
        """
    loaded = _load(body)
    with pytest.raises(ValueError, match=r"report upload.*`suites: reports:`.*the 'suites' section is missing"):
        cipipeline.derive(loaded, yaml.safe_load(_text(body)))


# --- the switch: `support github workflows` derives ci.yml where no entry declares it (si#858 task 7) -----

_CI_PATH = ".github/workflows/ci.yml"

_DECLARED_CI = """
        workflows:
          ci:
            on: [push]
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - command: build one
        """


def _product(tmp_path, monkeypatch, body: str) -> context.ProductContext:
    """`tmp_path` as a product's repository root, `_HEAD` + `body` as its manifest, registered as current."""
    manifest_path = tmp_path / "demo.yaml"
    manifest_path.write_text(_text(body), encoding="utf-8")
    ctx = context.ProductContext(name="demo", root=tmp_path, manifest_path=manifest_path)
    monkeypatch.setattr(context, "_current", ctx)
    return ctx


def test_a_product_with_no_workflows_section_gets_ci(tmp_path, monkeypatch):
    _product(tmp_path, monkeypatch, _THREE)

    rc = workflows_task.generate()

    assert rc == 0
    text = (tmp_path / _CI_PATH).read_text(encoding="utf-8")
    assert text.startswith("# GENERATED from demo.yaml")
    assert workflows_task.generate(check=True) == 0


def test_a_declared_ci_switches_the_derivation_off(tmp_path, monkeypatch):
    ctx = _product(tmp_path, monkeypatch, _THREE + _DECLARED_CI)
    (declared,) = workflowgen.parse(ctx.manifest_data())

    assert workflows_task.generate() == 0

    expected = workflowgen.render(declared, manifest=ctx.manifest(), product="demo", source="demo.yaml",
                                  artifacts=artifactsection.declared(ctx.manifest_data()))
    assert (tmp_path / _CI_PATH).read_text(encoding="utf-8") == expected
    assert not declared.derived


@pytest.mark.parametrize("check", [False, True])
def test_a_hand_written_ci_file_is_not_overwritten(tmp_path, monkeypatch, check):
    """Review Focus 3: a product that wrote its own ci.yml and never declared it loses nothing to an upgrade."""
    _product(tmp_path, monkeypatch, _THREE)
    target = tmp_path / _CI_PATH
    target.parent.mkdir(parents=True)
    own = b"name: mine\non: [push]\njobs: {}\n"
    target.write_bytes(own)

    with pytest.raises(ValueError) as refused:
        workflows_task.generate(check=check)

    said = str(refused.value)
    assert _CI_PATH in said
    assert "handwritten:" in said and "workflows: ci:" in said
    assert "delete" in said
    assert target.read_bytes() == own


def test_another_entry_writing_ci_yml_is_refused(tmp_path, monkeypatch):
    """Review Focus 4: an entry under another key that writes ci.yml would collide with the derived one."""
    _product(tmp_path, monkeypatch, _THREE + """
        workflows:
          checks:
            path: .github/workflows/ci.yml
            on: [push]
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - command: build one
        """)

    with pytest.raises(ValueError, match=r"workflows 'checks' and 'ci' both declare '\.github/workflows/ci\.yml'"):
        workflows_task.generate()


def test_check_reports_a_stale_derived_file(tmp_path, monkeypatch, capsys):
    _product(tmp_path, monkeypatch, _THREE)
    assert workflows_task.generate() == 0
    target = tmp_path / _CI_PATH
    target.write_text(target.read_text(encoding="utf-8") + "# edited by hand\n", encoding="utf-8")
    capsys.readouterr()

    rc = workflows_task.generate(check=True)

    assert rc == 1
    captured = capsys.readouterr()
    assert f"{_CI_PATH} disagrees with demo.yaml" in captured.out + captured.err


_NO_LEAF = """
        ci:
          test:
            commands:
              walk: { task: ship, unattended: false }
        """

_OTHER_WORKFLOW = """
        workflows:
          release:
            handwritten: two shell scripts and a great deal of reasoning
        """


def test_declared_workflows_and_no_runnable_leaf_derive_no_ci(tmp_path, monkeypatch, capsys):
    """Fix round 1: a product that declares other workflows and has no leaf a machine may run gets its declared
    workflows and no ci.yml, and the run says why in one line rather than refusing what it can generate."""
    _product(tmp_path, monkeypatch, _NO_LEAF + _OTHER_WORKFLOW)
    release = tmp_path / ".github/workflows/release.yml"
    release.parent.mkdir(parents=True)
    release.write_text("name: release\n", encoding="utf-8")

    rc = workflows_task.generate()

    assert rc == 0
    assert not (tmp_path / _CI_PATH).exists()
    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert "no ci.yml is derived" in said and "workflows: ci:" in said


def test_no_workflows_section_and_no_runnable_leaf_is_refused(tmp_path, monkeypatch):
    """With nothing declared there would be nothing to generate at all: the refusal stays."""
    _product(tmp_path, monkeypatch, _NO_LEAF)

    with pytest.raises(ValueError, match="hold no leaf a machine may run"):
        workflows_task.generate()
    assert not (tmp_path / _CI_PATH).exists()


def test_declared_workflows_do_not_swallow_the_other_refusals_of_the_derivation(tmp_path, monkeypatch):
    """Only the no-runnable-leaf case is told apart; a cycle stays a refusal beside declared workflows."""
    _product(tmp_path, monkeypatch, """
        ci:
          build:
            commands:
              loop: { task: "toolchain:run", unattended: true, consumes: { source: doc }, produces: { out: doc } }
        """ + _OTHER_WORKFLOW)

    with pytest.raises(ValueError, match="cycle"):
        workflows_task.generate()


def test_check_before_any_generate_reports_the_absent_derived_file(tmp_path, monkeypatch, capsys):
    _product(tmp_path, monkeypatch, _THREE)

    rc = workflows_task.generate(check=True)

    assert rc == 1
    assert not (tmp_path / _CI_PATH).exists()
    captured = capsys.readouterr()
    assert f"{_CI_PATH} disagrees with demo.yaml" in captured.out + captured.err


def test_platform_cells_are_the_measured_five() -> None:
    # act: the cells cleon ci.yml and asbundle build-matrix.yml carry (si#860, measured 2026-11-23)
    cells = workflowschema.PLATFORMS

    # assert
    assert tuple(cells) == ("linux-x64", "linux-arm64", "macos-x64", "macos-arm64", "windows-x64")
    assert [c.label for c in cells.values()] == [
        "ubuntu-24.04", "ubuntu-24.04-arm", "macos-15-intel", "macos-15", "windows-2025"]
    assert [c.arch for c in cells.values()] == ["x86_64", "aarch64", "x86_64", "arm64", "x86_64"]
    assert [c.shell for c in cells.values()] == ["bash", "bash", "bash", "bash", "cmd"]
    assert [name for name, c in cells.items() if c.windows] == ["windows-x64"]


def test_a_step_may_carry_a_time_limit() -> None:
    # assert: absent by default, an int when set
    assert workflowschema.Step().timeout_minutes is None
    assert workflowschema.Step(timeout_minutes=75).timeout_minutes == 75


# --- one workflow per `cadence:` (si#860 task 3) ---------------------------------------------------------

_NIGHTLY_PATH = ".github/workflows/ci-nightly.yml"
_MANUAL_PATH = ".github/workflows/ci-manual.yml"
_SCHEDULED_PATH = ".github/workflows/ci-scheduled.yml"


def _generated(tmp_path, monkeypatch, body: str) -> dict[str, tuple[dict, str]]:
    """Every workflow `support github workflows` writes for `_HEAD` + `body`, read back by path: the real
    path, so the `on:` trap and the notes are the renderer's, not a model's."""
    _product(tmp_path, monkeypatch, body)
    assert workflows_task.generate() == 0
    out = {}
    for path in sorted((tmp_path / ".github/workflows").iterdir()):
        text = path.read_text(encoding="utf-8")
        out[f".github/workflows/{path.name}"] = (yaml.safe_load(text), text)
    return out


def _job_runs(doc: dict, job: str) -> list[str]:
    return [step["run"].removeprefix("exec ./demo.sh ") for step in doc["jobs"][job]["steps"]
            if step.get("name") != workflowgen.REAP_NAME and "run" in step]


def _comments(text: str) -> str:
    return " ".join(line.strip().removeprefix("#").strip() for line in text.splitlines()
                    if line.strip().startswith("#"))


_NIGHTLY = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              late: { task: ship, unattended: true, ci: { cadence: nightly } }
        """


def test_nightly_leaf_leaves_the_push_workflow(tmp_path, monkeypatch):
    # act
    files = _generated(tmp_path, monkeypatch, _NIGHTLY)

    # assert: the push file lost the leaf, the nightly file has it, on the kernel's cron and on dispatch
    assert set(files) == {_CI_PATH, _NIGHTLY_PATH}
    push, _ = files[_CI_PATH]
    nightly, _ = files[_NIGHTLY_PATH]
    assert _job_runs(push, "ci") == ["test one"]
    assert _job_runs(nightly, "ci") == ["test late"]
    assert nightly["name"] == "ci-nightly"
    assert nightly[True] == {"schedule": [{"cron": cipipeline.NIGHTLY_CRON}], "workflow_dispatch": None}
    assert cipipeline.NIGHTLY_CRON == "17 2 * * *"
    assert push[True] == workflowgen._CI_TRIGGER


def test_manual_cadence_is_dispatch_only(tmp_path, monkeypatch):
    files = _generated(tmp_path, monkeypatch, _NIGHTLY.replace("cadence: nightly", "cadence: manual"))

    assert set(files) == {_CI_PATH, _MANUAL_PATH}
    manual, _ = files[_MANUAL_PATH]
    assert manual["name"] == "ci-manual"
    assert manual[True] == {"workflow_dispatch": None}
    assert _job_runs(manual, "ci") == ["test late"]


def test_cron_strings_share_one_file_one_job_each(tmp_path, monkeypatch):
    """Review Focus 5: the same cron is one job, a different cron another, each gated on its own schedule and
    both run on dispatch."""
    body = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              a: { task: ship, unattended: true, ci: { cadence: "0 3 * * *" } }
              b: { task: ship, unattended: true, ci: { cadence: "*/30 4 * * 1" } }
              c: { task: ship, unattended: true, ci: { cadence: "0  3 * * *" } }
        """
    files = _generated(tmp_path, monkeypatch, body)

    assert set(files) == {_CI_PATH, _SCHEDULED_PATH}
    scheduled, _ = files[_SCHEDULED_PATH]
    assert scheduled["name"] == "ci-scheduled"
    assert list(scheduled["jobs"]) == ["ci-1", "ci-2"]
    assert _job_runs(scheduled, "ci-1") == ["test a", "test c"]
    assert _job_runs(scheduled, "ci-2") == ["test b"]
    assert scheduled["jobs"]["ci-1"]["if"] == (
        "${{ github.event_name == 'workflow_dispatch' || github.event.schedule == '0 3 * * *' }}")
    assert scheduled["jobs"]["ci-2"]["if"] == (
        "${{ github.event_name == 'workflow_dispatch' || github.event.schedule == '*/30 4 * * 1' }}")
    assert scheduled[True] == {"schedule": [{"cron": "0 3 * * *"}, {"cron": "*/30 4 * * 1"}],
                               "workflow_dispatch": None}
    push, _ = files[_CI_PATH]
    assert _job_runs(push, "ci") == ["test one"]


def test_cadence_workflow_carries_the_report_last(tmp_path, monkeypatch):
    """A report with no cadence of its own is a verdict over whichever run it ends: it closes every workflow."""
    body = """
        ci:
          test:
            commands:
              report: { task: "test:report" }
              one: { task: ship, unattended: true }
              late: { task: ship, unattended: true, ci: { cadence: nightly } }
        """ + textwrap.indent(textwrap.dedent(_SUITES), " " * 8)
    files = _generated(tmp_path, monkeypatch, body)

    for path, leaf in ((_CI_PATH, "test one"), (_NIGHTLY_PATH, "test late")):
        doc, _ = files[path]
        assert _job_runs(doc, "ci") == [leaf, "test report"]
        steps = [step for step in doc["jobs"]["ci"]["steps"] if step.get("name") != workflowgen.REAP_NAME]
        report = next(at for at, step in enumerate(steps) if step.get("run") == "exec ./demo.sh test report")
        assert steps[report]["if"] == "always()"
        assert steps[report + 1]["uses"] == workflowgen.UPLOAD_ACTION
        assert steps[report + 1]["if"] == "always()"


def test_cadence_workflow_does_not_cancel_in_progress(tmp_path, monkeypatch):
    files = _generated(tmp_path, monkeypatch, _NIGHTLY)

    nightly, _ = files[_NIGHTLY_PATH]
    assert nightly["concurrency"] == {"group": "ci-nightly", "cancel-in-progress": False}
    assert nightly["permissions"] == {"contents": "read"}
    push, _ = files[_CI_PATH]
    assert "concurrency" not in push


def test_consumer_of_a_nightly_producer_is_refused():
    """Review Focus 4: the push run has no producer, so the consumer would fail on a missing file."""
    loaded = _load("""
        ci:
          build:
            commands:
              b-produce:
                { task: "toolchain:run", unattended: true, produces: { out: doc }, ci: { cadence: nightly } }
              t-consume: { task: "toolchain:run", unattended: true, consumes: { source: doc } }
        """)
    with pytest.raises(ValueError, match=r"'build t-consume' consumes 'doc', which 'build b-produce' produces.*"
                                         r"cadence: nightly"):
        cipipeline.derive(loaded, {})


def test_consumers_on_different_crons_are_refused():
    """The same check per job: two crons fire apart, so a producer on one is absent from the other's run."""
    loaded = _load("""
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
              b-produce:
                { task: "toolchain:run", unattended: true, produces: { out: doc }, ci: { cadence: "0 3 * * *" } }
              t-consume:
                { task: "toolchain:run", unattended: true, consumes: { source: doc }, ci: { cadence: "0 4 * * *" } }
        """)
    with pytest.raises(ValueError, match=r"'build t-consume' consumes 'doc'.*'build b-produce'.*0 3 \* \* \*"):
        cipipeline.derive_all(loaded, {})


def test_all_leaves_scheduled_refuses_the_push_workflow():
    """Review Focus 2: ci.yml would verify nothing on a push, and the refusal says where the leaves went."""
    loaded = _load("""
        ci:
          test:
            commands:
              late: { task: ship, unattended: true, ci: { cadence: nightly } }
        """)
    with pytest.raises(ValueError, match="the push path verifies nothing") as raised:
        cipipeline.derive(loaded, {})
    assert "ci-nightly.yml" in str(raised.value)


def test_skipped_and_cadence_notes(tmp_path, monkeypatch):
    files = _generated(tmp_path, monkeypatch, _NIGHTLY)

    _, push = files[_CI_PATH]
    _, nightly = files[_NIGHTLY_PATH]
    assert "Left out:" in push
    assert "`test late` - it has `cadence: nightly`, so it runs in ci-nightly.yml" in _comments(push)
    said = _comments(nightly)
    assert "`cadence: nightly`" in said and cipipeline.NIGHTLY_CRON in said
    assert "`test one`" not in said  # a push leaf is not listed in every cadence file


def test_derive_all_puts_the_push_workflow_first():
    loaded = _load("""
        ci:
          test:
            commands:
              d: { task: ship, unattended: true, ci: { cadence: "0 3 * * *" } }
              m: { task: ship, unattended: true, ci: { cadence: manual } }
              one: { task: ship, unattended: true }
              n: { task: ship, unattended: true, ci: { cadence: nightly } }
        """)
    derivations = cipipeline.derive_all(loaded, {})
    assert [d.model.path for d in derivations] == [
        cipipeline.CADENCE_PATHS[""], cipipeline.CADENCE_PATHS["nightly"], cipipeline.CADENCE_PATHS["manual"],
        _SCHEDULED_PATH]
    assert [d.model.title for d in derivations] == ["ci", "ci-nightly", "ci-manual", "ci-scheduled"]
    assert cipipeline.derive(loaded, {}).model == derivations[0].model


def test_declared_workflows_and_only_cadence_leaves_still_derive_them(tmp_path, monkeypatch):
    """With other workflows declared and no push leaf, no ci.yml is derived (#858), and the nightly file still
    is: it has something to run."""
    _product(tmp_path, monkeypatch, """
        ci:
          test:
            commands:
              late: { task: ship, unattended: true, ci: { cadence: nightly } }
        """ + _OTHER_WORKFLOW)
    release = tmp_path / ".github/workflows/release.yml"
    release.parent.mkdir(parents=True)
    release.write_text("name: release\n", encoding="utf-8")

    assert workflows_task.generate() == 0
    assert not (tmp_path / _CI_PATH).exists()
    assert (tmp_path / _NIGHTLY_PATH).exists()


def test_each_scheduled_job_uploads_its_report_under_its_own_name(tmp_path, monkeypatch):
    """A dispatch runs every job of ci-scheduled.yml in one run, and upload-artifact@v4 refuses a second
    artifact of the same name in a run: each job's report is named after the job."""
    body = """
        ci:
          test:
            commands:
              report: { task: "test:report" }
              one: { task: ship, unattended: true }
              a: { task: ship, unattended: true, ci: { cadence: "0 3 * * *" } }
              b: { task: ship, unattended: true, ci: { cadence: "0 4 * * *" } }
        """ + textwrap.indent(textwrap.dedent(_SUITES), " " * 8)
    files = _generated(tmp_path, monkeypatch, body)

    def uploaded(doc: dict, job: str) -> list[str]:
        return [step["with"]["name"] for step in doc["jobs"][job]["steps"]
                if step.get("uses") == workflowgen.UPLOAD_ACTION]

    scheduled, _ = files[_SCHEDULED_PATH]
    assert uploaded(scheduled, "ci-1") == ["allure-report-ci-1"]
    assert uploaded(scheduled, "ci-2") == ["allure-report-ci-2"]
    push, _ = files[_CI_PATH]
    assert uploaded(push, "ci") == ["allure-report"]


# --- matrix cells: `ci: { python: }` and `ci: { platforms: }` (si#860 task 4) ----------------------------

_PYTHON = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              suite: { task: ship, unattended: true, ci: { python: ["3.12", "3.13"] } }
        """

_PLATFORMS = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              suite: { task: ship, unattended: true, ci: { platforms: [linux-x64, macos-arm64, windows-x64] } }
        """


def _top(*parts: str) -> str:
    """Top-level manifest sections, indented to sit beside an 8-space-indented body before `_text` dedents."""
    return "".join(textwrap.indent(textwrap.dedent(part), " " * 8) for part in parts)


def _cell_steps(doc: dict, job: str) -> list[dict]:
    return [step for step in doc["jobs"][job]["steps"] if step.get("name") != workflowgen.REAP_NAME]


def _cell_runs(doc: dict, job: str) -> list[str]:
    return [step["run"] for step in _cell_steps(doc, job) if "run" in step]


def test_python_cells_add_a_job_and_keep_the_main_run(tmp_path, monkeypatch):
    # act
    files = _generated(tmp_path, monkeypatch, _PYTHON)

    # assert: decision 5, the leaf runs in the main job AND once per version in a job of its own
    push, text = files[_CI_PATH]
    assert list(push["jobs"]) == ["ci", "test-suite-python"]
    assert _job_runs(push, "ci") == ["test one", "test suite"]
    cell = push["jobs"]["test-suite-python"]
    assert cell["runs-on"] == "ubuntu-latest"
    assert cell["strategy"] == {"fail-fast": False, "matrix": {"python": ["3.12", "3.13"]}}
    setup = [step for step in cell["steps"] if step.get("uses") == workflowgen.SETUP_PYTHON_ACTION]
    assert setup == [{"uses": workflowgen.SETUP_PYTHON_ACTION, "with": {"python-version": "${{ matrix.python }}"}}]
    assert any(step.get("uses") == workflowgen.CHECKOUT_ACTION for step in cell["steps"])
    assert _job_runs(push, "test-suite-python") == ["test suite"]
    # a cell carries no report: its result is its job's colour, and the file says so
    assert not any(step.get("uses") == workflowgen.UPLOAD_ACTION for step in cell["steps"])
    assert "carries no report" in _comments(text)


def test_python_cell_runs_on_github_ubuntu_under_a_self_hosted_runner(tmp_path, monkeypatch):
    """A cell is a hosted machine whatever the product's `runner:` is: no disk preflight, no docker probe, no
    bootstrap env; `support install` it does get, like the main job, where the product declares toolchains."""
    files = _generated(tmp_path, monkeypatch, _PYTHON + _top(_SELF_HOSTED, _TOOLCHAINS))

    push, _ = files[_CI_PATH]
    assert push["jobs"]["ci"]["runs-on"] == "ghr-8"
    assert "support ci-disk-preflight" in _job_runs(push, "ci")
    cell = push["jobs"]["test-suite-python"]
    assert cell["runs-on"] == "ubuntu-latest"
    assert "env" not in cell
    assert _job_runs(push, "test-suite-python") == ["support install", "test suite"]


def test_platform_cells_replace_the_main_run(tmp_path, monkeypatch):
    files = _generated(tmp_path, monkeypatch, _PLATFORMS)

    # assert: decision 6, the leaf runs only in its cells
    push, text = files[_CI_PATH]
    assert list(push["jobs"]) == ["ci", "test-suite-platforms"]
    assert _job_runs(push, "ci") == ["test one"]
    cell = push["jobs"]["test-suite-platforms"]
    assert cell["runs-on"] == "${{ matrix.os }}"
    assert cell["defaults"] == {"run": {"shell": "${{ matrix.shell }}"}}
    rows = cell["strategy"]["matrix"]["include"]
    assert cell["strategy"]["fail-fast"] is False
    assert [row["cell"] for row in rows] == ["linux-x64", "macos-arm64", "windows-x64"]
    for row in rows:
        platform = workflowschema.PLATFORMS[row["cell"]]
        assert (row["os"], row["arch"], row["shell"]) == (platform.label, platform.arch, platform.shell)
    assert rows[0]["entry"] == f"exec {context.launcher('demo')}"
    assert _cell_runs(push, "test-suite-platforms")[-1] == "${{ matrix.entry }} test suite"
    assert not any(step.get("uses") == workflowgen.UPLOAD_ACTION for step in cell["steps"])
    assert "carries no report" in _comments(text)


def test_a_workflow_of_only_platform_cells_runs_no_main_job(tmp_path, monkeypatch):
    """cleon's and asbundle's measured shape: the cells run by dispatch alone. The manual workflow has no leaf
    for a main job, and the cells are something to run, so it is the cell job alone rather than a refusal."""
    body = _PLATFORMS.replace("platforms: [", "cadence: manual, platforms: [")

    files = _generated(tmp_path, monkeypatch, body)

    manual, _ = files[_MANUAL_PATH]
    assert list(manual["jobs"]) == ["test-suite-platforms"]
    push, _ = files[_CI_PATH]
    assert list(push["jobs"]) == ["ci"]


def test_windows_cell_runs_the_cmd_launcher(tmp_path, monkeypatch):
    files = _generated(tmp_path, monkeypatch, _PLATFORMS)

    push, _ = files[_CI_PATH]
    rows = {row["cell"]: row for row in push["jobs"]["test-suite-platforms"]["strategy"]["matrix"]["include"]}
    assert rows["windows-x64"]["shell"] == "cmd"
    assert rows["windows-x64"]["entry"] == "demo.cmd"
    # si#666: every bash row execs the launcher; cmd has no exec builtin
    assert rows["linux-x64"]["entry"] == "exec ./demo.sh"
    assert rows["macos-arm64"]["entry"] == "exec ./demo.sh"


def test_platform_job_asserts_the_architecture(tmp_path, monkeypatch):
    """A cell that silently runs the wrong architecture looks complete: the job checks `uname -m` against the
    cell's expected value before the leaf, in bash on every cell (Git Bash on windows-2025 prints x86_64)."""
    files = _generated(tmp_path, monkeypatch, _PLATFORMS)

    push, _ = files[_CI_PATH]
    steps = _cell_steps(push, "test-suite-platforms")
    (check,) = [step for step in steps if "uname -m" in step.get("run", "")]
    assert check["shell"] == "bash"
    assert "${{ matrix.arch }}" in str(check.get("env", {})) + check["run"]
    assert "::error::" in check["run"] and "exit 1" in check["run"]
    assert steps.index(check) < steps.index(next(s for s in steps if s.get("run", "").endswith("test suite")))


def test_platform_arch_check_fails_on_a_mismatch_and_passes_on_a_match(tmp_path, monkeypatch):
    """The assertion's script, run in bash with the cell's value and a wrong one: see it red."""
    import subprocess
    files = _generated(tmp_path, monkeypatch, _PLATFORMS)
    push, _ = files[_CI_PATH]
    (check,) = [s for s in _cell_steps(push, "test-suite-platforms") if "uname -m" in s.get("run", "")]
    here = subprocess.run(["uname", "-m"], capture_output=True, text=True, check=True).stdout.strip()

    def run(arch: str) -> subprocess.CompletedProcess[str]:
        env = {name: str(value).replace("${{ matrix.arch }}", arch).replace("${{ matrix.cell }}", "x")
               for name, value in check.get("env", {}).items()}
        script = check["run"].replace("${{ matrix.arch }}", arch).replace("${{ matrix.cell }}", "x")
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", **env})

    assert run(here).returncode == 0
    wrong = run("not-" + here)
    assert wrong.returncode == 1
    assert "::error::" in wrong.stdout


@pytest.mark.parametrize("variant, job", [('python: ["3.12"]', "test-t-consume-python"),
                                          ("platforms: [linux-x64]", "test-t-consume-platforms")])
def test_cell_consumer_of_a_main_job_artifact(tmp_path, monkeypatch, variant, job):
    """Review Focus 1: a cell leaf that consumes what a main-job leaf produces.

    MEASURED FIRST (2026-11-23, `handoff.plan` read and run): a matrix CONSUMER is not refused - only a matrix
    PRODUCER is ("runs once per matrix entry"). The plan gives the consumer's job `needs:` on the producer's
    job and a download before the consuming step, and the producer's job an upload after its producing step;
    every cell downloads the same archive, which download-artifact allows. So the cell job gets `needs: ci`
    and the download, rather than a refusal, and never fails on a missing file."""
    body = f"""
        ci:
          build:
            commands:
              b-produce: {{ task: "toolchain:run", unattended: true, produces: {{ out: doc }} }}
          test:
            commands:
              t-consume: {{ task: "test:file", unattended: true, consumes: {{ file: doc }}, ci: {{ {variant} }} }}
        """

    files = _generated(tmp_path, monkeypatch, body)

    push, _ = files[_CI_PATH]
    cell = push["jobs"][job]
    assert cell["needs"] == "ci"
    steps = _cell_steps(push, job)
    download = next(at for at, s in enumerate(steps)
                    if s.get("uses") == workflowgen.DOWNLOAD_ACTION and s["with"]["name"] == "doc")
    leaf = next(at for at, s in enumerate(steps) if s.get("run", "").endswith("test t-consume"))
    assert download < leaf
    uploads = [s["with"]["name"] for s in push["jobs"]["ci"]["steps"] if s.get("uses") == workflowgen.UPLOAD_ACTION]
    assert uploads == ["doc"]


def test_a_cell_job_on_a_cron_carries_its_schedule_gate(tmp_path, monkeypatch):
    body = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              a: { task: ship, unattended: true, ci: { cadence: "0 3 * * *" } }
              suite: { task: ship, unattended: true, ci: { cadence: "0 3 * * *", python: ["3.13"] } }
        """
    files = _generated(tmp_path, monkeypatch, body)

    scheduled, _ = files[_SCHEDULED_PATH]
    assert list(scheduled["jobs"]) == ["ci-1", "test-suite-python"]
    assert scheduled["jobs"]["test-suite-python"]["if"] == scheduled["jobs"]["ci-1"]["if"]


def test_the_model_carries_the_cell_matrix():
    loaded = _load(_PLATFORMS)
    (main, cell) = cipipeline.derive(loaded, {}).model.job
    assert main.matrix is None
    assert cell.key == "test-suite-platforms"
    assert cell.matrix == workflowschema.Matrix(platform=("linux-x64", "macos-arm64", "windows-x64"))
    loaded = _load(_PYTHON)
    (_, cell) = cipipeline.derive(loaded, {}).model.job
    assert cell.matrix == workflowschema.Matrix(python=("3.12", "3.13"))


def test_a_run_with_no_main_job_names_what_it_does_not_run(tmp_path, monkeypatch):
    """Review fix: with every leaf in platform cells there is no main job, and the file still says what the
    derived note says (the left-out leaves) and names the `after_all` report that has no main job to end."""
    body = """
        ci:
          test:
            commands:
              report: { task: "test:report" }
              idle: { task: ship, unattended: false }
              suite: { task: ship, unattended: true, ci: { platforms: [linux-x64] } }
        """ + _top(_SUITES)

    files = _generated(tmp_path, monkeypatch, body)

    push, text = files[_CI_PATH]
    assert list(push["jobs"]) == ["test-suite-platforms"]
    said = _comments(text)
    assert "`test report` runs after all the other leaves" in said and "does not run here" in said
    assert "`test idle` - " + cipipeline.ATTENDED in said


def test_a_windows_cell_that_downloads_a_handoff_says_the_unpack_is_unmeasured(tmp_path, monkeypatch):
    """Review ruling: recorded, not refused. Only a job with a Windows cell AND a download says it."""
    body = """
        ci:
          build:
            commands:
              b-produce: { task: "toolchain:run", unattended: true, produces: { out: doc } }
          test:
            commands:
              t-consume:
                { task: "test:file", unattended: true, consumes: { file: doc }, ci: { platforms: [PLATS] } }
        """
    unmeasured = " ".join(cipipeline.WINDOWS_HANDOFF_UNMEASURED.split())
    for sub in "wln":
        (tmp_path / sub).mkdir()

    with_windows = _generated(tmp_path / "w", monkeypatch, body.replace("PLATS", "linux-x64, windows-x64"))
    assert unmeasured in _comments(with_windows[_CI_PATH][1])
    linux_only = _generated(tmp_path / "l", monkeypatch, body.replace("PLATS", "linux-x64"))
    assert unmeasured not in _comments(linux_only[_CI_PATH][1])
    no_download = _generated(tmp_path / "n", monkeypatch, _PLATFORMS)
    assert unmeasured not in _comments(no_download[_CI_PATH][1])


# --- `ci: { timeout_minutes: }` and `ci: { emulates: }` (si#860 task 5) -----------------------------------

_TIMEOUT = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              lab: { task: ship, unattended: true, ci: { timeout_minutes: 95 } }
        """

_EMULATES = """
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
          test:
            commands:
              arm: { task: ship, unattended: true, ci: { emulates: [linux/arm64] } }
              more: { task: ship, unattended: true, ci: { emulates: [linux/arm64, linux/arm/v7] } }
        """


def _emulations(doc: dict, job: str) -> list[dict]:
    return [step for step in doc["jobs"][job]["steps"] if step.get("uses") == workflowgen.QEMU_ACTION]


def test_timeout_is_a_step_limit_in_a_shared_job(tmp_path, monkeypatch):
    files = _generated(tmp_path, monkeypatch, _TIMEOUT)

    # assert: decision 4, the leaf's own step carries the limit, the job and the other leaves none
    push, _ = files[_CI_PATH]
    steps = _cell_steps(push, "ci")
    lab = next(step for step in steps if step.get("run", "").endswith("test lab"))
    assert lab["timeout-minutes"] == 95
    one = next(step for step in steps if step.get("run", "").endswith("test one"))
    assert "timeout-minutes" not in one
    assert "timeout-minutes" not in push["jobs"]["ci"]
    lab_step = next(s for s in cipipeline.derive(_load(_TIMEOUT), {}).model.job[0].step
                    if s.command is not None and s.command.ci.timeout_minutes)
    assert lab_step.timeout_minutes == 95


def test_timeout_is_the_job_limit_in_a_cell_job(tmp_path, monkeypatch):
    body = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              suite: { task: ship, unattended: true, ci: { timeout_minutes: 40, platforms: [linux-x64, macos-arm64] } }
        """
    files = _generated(tmp_path, monkeypatch, body)

    # assert: decision 4, the same limit for every cell, as the job's; the step carries none of its own
    push, _ = files[_CI_PATH]
    cell = push["jobs"]["test-suite-platforms"]
    assert cell["timeout-minutes"] == 40
    assert not any("timeout-minutes" in step for step in _cell_steps(push, "test-suite-platforms"))
    (_, model_cell) = cipipeline.derive(_load(body), {}).model.job
    assert model_cell.timeout_minutes == 40


def test_emulation_registered_once_before_the_leaves(tmp_path, monkeypatch):
    from simplon.adapters.labhost import BINFMT_IMAGE

    files = _generated(tmp_path, monkeypatch, _EMULATES + _top(_SELF_HOSTED, _TOOLCHAINS))

    # assert: decision 7, one step for the job, every platform once in first-written order, the release's shape
    push, _ = files[_CI_PATH]
    (emulation,) = _emulations(push, "ci")
    assert emulation["with"] == {"image": BINFMT_IMAGE, "platforms": "linux/arm64,linux/arm/v7"}
    assert emulation["id"] == cipipeline.PREPARE["emulation"]
    # after every preparation step, before the first leaf
    steps = _cell_steps(push, "ci")
    at = steps.index(emulation)
    assert [s.get("id") for s in steps[:at] if s.get("id")] == [
        cipipeline.PREPARE["docker"], cipipeline.PREPARE["disk"], cipipeline.PREPARE["install"]]
    assert steps[at + 1]["run"].endswith("build one")
    # and a red registration skips every later leaf, like any preparation step
    arm = next(step for step in steps if step.get("run", "").endswith("test arm"))
    assert f"steps.{cipipeline.PREPARE['emulation']}.outcome == 'success'" in arm["if"]


def test_no_emulation_step_where_no_leaf_asks(tmp_path, monkeypatch):
    push, _ = _generated(tmp_path, monkeypatch, _THREE)[_CI_PATH]
    assert _emulations(push, "ci") == []


def test_emulation_in_the_python_cell_job(tmp_path, monkeypatch):
    """simplon's hand-written `suite-python-3-14`: a python cell whose leaf runs linux/arm64 files."""
    body = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              suite: { task: ship, unattended: true, ci: { python: ["3.14"], emulates: [linux/arm64] } }
        """
    files = _generated(tmp_path, monkeypatch, body)

    push, _ = files[_CI_PATH]
    (emulation,) = _emulations(push, "test-suite-python")
    assert emulation["with"]["platforms"] == "linux/arm64"
    steps = _cell_steps(push, "test-suite-python")
    assert steps.index(emulation) < next(i for i, s in enumerate(steps) if s.get("run", "").endswith("test suite"))
    # the main job runs the leaf too (decision 5), so it registers there as well
    assert len(_emulations(push, "ci")) == 1


def test_no_emulation_on_a_kind_that_cannot(tmp_path, monkeypatch):
    """#722, si#863: `self-hosted-container` (an LXC runner, `can_emulate = false`) registers nothing, and the
    file names the gap rather than a step that cannot work there."""
    container = _SELF_HOSTED.replace("self-hosted-debian", "self-hosted-container")

    files = _generated(tmp_path, monkeypatch, _EMULATES + _top(container, _TOOLCHAINS))

    push, text = files[_CI_PATH]
    assert push["jobs"]["ci"]["runs-on"] == "ghr-8"
    assert _emulations(push, "ci") == []
    assert not any(str(step.get("uses", "")).startswith("docker/setup-qemu-action@")
                   for job in push["jobs"].values() for step in job["steps"])
    said = _comments(text)
    assert "self-hosted-container" in said and "cannot register emulation" in said, said
    assert "`support:ci-arm64`" in said, said
    assert "#722" in said and "linux/arm64, linux/arm/v7" in said
    # two leaves, so the plural verb; simplon's own ci.yml holds the singular (test_own_workflows)
    assert "`test arm`, `test more` name `ci: emulates:`" in said, said


# --- the final review of si#860: one switch rule, inert keys, the empty push run ---------------------------

_HANDWRITTEN_NIGHTLY = """
        workflows:
          ci-nightly: { handwritten: "ours" }
        """


def test_a_declared_cadence_key_switches_off_only_that_derived_file(tmp_path, monkeypatch):
    """Final review item 1: `workflows: ci-nightly:` is the product's own nightly file, so the derived one is not
    written and nothing is refused as two owners; ci.yml is still derived beside it."""
    _product(tmp_path, monkeypatch, _NIGHTLY + _HANDWRITTEN_NIGHTLY)
    own = tmp_path / _NIGHTLY_PATH
    own.parent.mkdir(parents=True)
    own.write_text("name: mine\n", encoding="utf-8")

    assert workflows_task.generate() == 0

    assert own.read_text(encoding="utf-8") == "name: mine\n"
    assert (tmp_path / _CI_PATH).read_text(encoding="utf-8").startswith("# GENERATED from demo.yaml")
    keys = [w.key for w in cipipeline.workflows(_load(_NIGHTLY + _HANDWRITTEN_NIGHTLY),
                                                yaml.safe_load(_text(_NIGHTLY + _HANDWRITTEN_NIGHTLY)),
                                                product="demo")]
    assert keys == ["ci-nightly", "ci"]
    assert workflows_task.generate(check=True) == 0


def test_a_declared_ci_keeps_the_derived_cadence_files(tmp_path, monkeypatch):
    """Final review item 1: `workflows: ci:` switches off ci.yml and only ci.yml, so a nightly leaf still gets
    its ci-nightly.yml rather than being dropped without a word."""
    body = """
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
              late: { task: ship, unattended: true, ci: { cadence: nightly } }
        """ + _DECLARED_CI
    ctx = _product(tmp_path, monkeypatch, body)
    (declared,) = workflowgen.parse(ctx.manifest_data())

    assert workflows_task.generate() == 0

    assert not declared.derived
    assert "cipipeline" not in (tmp_path / _CI_PATH).read_text(encoding="utf-8")
    nightly = yaml.safe_load((tmp_path / _NIGHTLY_PATH).read_text(encoding="utf-8"))
    assert _job_runs(nightly, "ci") == ["build late"]


@pytest.mark.parametrize("key", ['python: ["3.14"]', "platforms: [linux-arm64]", "timeout_minutes: 30",
                                 "emulates: [linux/arm64]"])
def test_a_variant_key_on_a_push_leaf_under_a_declared_ci_is_refused(tmp_path, monkeypatch, key):
    """Final review item 2: ci.yml is the product's own, so a variant key on a leaf that would run there shapes
    nothing - a diagnosis, as `ci:` on a command no derived CI selects is (si#858)."""
    name = key.split(":", 1)[0]
    _product(tmp_path, monkeypatch, f"""
        ci:
          build:
            commands:
              one: {{ task: ship, unattended: true, ci: {{ {key} }} }}
        """ + _DECLARED_CI)

    with pytest.raises(ValueError) as refused:
        workflows_task.generate()

    said = str(refused.value)
    assert "'build one'" in said and f"`ci: {name}:`" in said
    assert "workflows: ci:" in said and "Take the key off" in said


def test_a_cadence_leaf_keeps_its_variant_keys_under_a_declared_ci(tmp_path, monkeypatch):
    """The refusal is for a key nothing reads: a nightly leaf's keys shape ci-nightly.yml, and an `after_all`
    leaf without a cadence ends every cadence file, so its keys are read there."""
    body = """
        ci:
          build:
            commands:
              one: { task: ship, unattended: true }
              late: { task: ship, unattended: true, ci: { cadence: nightly, timeout_minutes: 20 } }
          test:
            commands:
              report: { task: "test:report", ci: { timeout_minutes: 5 } }
        """ + textwrap.indent(textwrap.dedent(_SUITES), " " * 8) + _DECLARED_CI
    _product(tmp_path, monkeypatch, body)

    assert workflows_task.generate() == 0

    nightly = yaml.safe_load((tmp_path / _NIGHTLY_PATH).read_text(encoding="utf-8"))
    assert _job_runs(nightly, "ci") == ["build late", "test report"]


def test_a_push_run_emptied_by_cadences_says_where_the_leaves_went():
    """Final review item 3: the leaves are not missing, they run on a cadence; the push path verifies nothing,
    and the way out is a leaf without `cadence:` or a push CI of the product's own."""
    loaded = _load("""
        ci:
          test:
            commands:
              late: { task: ship, unattended: true, ci: { cadence: nightly } }
              weekly: { task: ship, unattended: true, ci: { cadence: "0 3 * * 1" } }
        """)

    with pytest.raises(ValueError) as refused:
        cipipeline.derive(loaded, {})

    said = str(refused.value)
    assert "run in ci-nightly.yml, ci-scheduled.yml" in said
    assert "the push path verifies nothing" in said
    assert "without `cadence:`" in said
    assert "`workflows: ci:`" in said and "switches off only ci.yml" in said
    assert "hold no leaf a machine may run" not in said


def test_scheduled_concurrency_is_keyed_on_the_schedule(tmp_path, monkeypatch):
    """Final review item 9: GitHub keeps one pending run per concurrency group, so with one group a pending run
    of one cron would replace another cron's; each schedule, and dispatch, queues in a group of its own."""
    body = """
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              a: { task: ship, unattended: true, ci: { cadence: "0 3 * * *" } }
              b: { task: ship, unattended: true, ci: { cadence: "0 4 * * *" } }
        """
    files = _generated(tmp_path, monkeypatch, body)

    scheduled, text = files[_SCHEDULED_PATH]
    assert scheduled["concurrency"] == {"group": "ci-scheduled-${{ github.event.schedule || 'dispatch' }}",
                                        "cancel-in-progress": False}
    assert "one pending run per schedule" in _comments(text)
    (tmp_path / "n").mkdir()
    nightly = _generated(tmp_path / "n", monkeypatch, _NIGHTLY)[_NIGHTLY_PATH][0]
    assert nightly["concurrency"] == {"group": "ci-nightly", "cancel-in-progress": False}


_DATA = yaml.safe_load(_HEAD)

_CELL_PRODUCER = """
        ci:
          build:
            commands:
              b-produce: {{ task: "toolchain:run", unattended: true, produces: {{ out: {artifact} }}, ci: {{ {variant} }} }}
          test:
            commands:
              t-consume: {{ task: "test:file", unattended: true, consumes: {{ file: {artifact} }}{consumer} }}
        """


@pytest.mark.parametrize(("variant", "consumer", "key"), [
    ("platforms: [linux-x64]", "", "platforms"),
    ('python: ["3.14"]', ', ci: { python: ["3.14"] }', "python"),
])
def test_a_cell_leaf_that_produces_for_another_leaf_is_refused(variant, consumer, key):
    """Final review item 5: a cell job runs its leaf once per cell, so its artifact would be produced once per cell
    (and once more in the main job for `python:`), and the run uploads an artifact once. Refused before the
    hand-off plan, in the manifest's words."""
    loaded = _load(_CELL_PRODUCER.format(artifact="doc", variant=variant, consumer=consumer))

    with pytest.raises(ValueError) as refused:
        cipipeline.derive(loaded, _DATA)

    said = str(refused.value)
    assert said.startswith("derived CI: 'build b-produce' declares `ci: " + key + ":`")
    assert "'doc'" in said and "'test t-consume'" in said
    assert "Take `ci: " + key + ":` off 'build b-produce'" in said and "`registry:`" in said


def test_a_cell_leaf_producing_a_fetched_artifact_is_not_refused():
    """An artifact with a `registry:` is fetched by its consumer, not handed over from the cell job."""
    loaded = _load(_CELL_PRODUCER.format(artifact="note", variant="platforms: [linux-x64]", consumer=""))

    derivation = cipipeline.derive(loaded, _DATA)

    assert [job.key for job in derivation.model.job] == ["ci", "build-b-produce-platforms"]


# --- si#863: `ci: params:`, a parameter bound where the kernel derives the leaf -----------------------------

_PICK = _HEAD.replace("tasks:\n", 'tasks:\n  pick: { impl: "simplon.test_impls:target_and_mode", help: "Pick." }\n')


def _rendered_with_pick(body: str) -> tuple[dict, manifest_mod.Manifest]:
    text = _PICK + textwrap.dedent(body)
    loaded = manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml", validate_with=True)
    data = yaml.safe_load(text)
    workflow = cipipeline.to_workflow(cipipeline.derive(loaded, data), loaded, data, product="demo")
    out = workflowgen.render(workflow, manifest=loaded, product="demo", source="demo.yaml",
                             artifacts={}, reports="tests/reports")
    return yaml.safe_load(out), loaded


def test_ci_params_render_as_a_declared_step_s_params_in_every_job_the_leaf_runs_in():
    """Task 2b (a): the derived step hands the command what a declared step's `params:` would, by the same
    function, so `target` (no default in the body) is positional and `mode` an option - in the main job and in
    the python cell alike. The command's interactive form is untouched: `ci:` is read by no CLI."""
    doc, loaded = _rendered_with_pick("""
        ci:
          test:
            commands:
              one: { task: ship, unattended: true }
              pick: { task: pick, unattended: true, ci: { params: { mode: slow, target: "a b" }, python: ["3.14"] } }
        """)

    declared = workflowgen._parameters(loaded, "test", "pick", {"mode": "slow", "target": "a b"}, where="declared")
    assert declared == " --mode slow -- 'a b'"
    assert _runs(doc) == ["test one", "test pick" + declared]
    assert _job_runs(doc, "test-pick-python") == ["test pick" + declared]


def test_a_leaf_without_ci_params_renders_bare():
    doc, _ = _rendered_with_pick("""
        ci:
          test:
            commands:
              pick: { task: pick, unattended: true }
        """)
    assert _runs(doc) == ["test pick"]


def test_ci_params_on_a_push_leaf_under_a_declared_ci_is_refused(tmp_path, monkeypatch):
    """`_refuse_variants_nobody_derives` over the new key: the product's own ci.yml reads no `ci:`."""
    _product(tmp_path, monkeypatch, """
        ci:
          build:
            commands:
              one: { task: ship, unattended: true, ci: { params: { anything: x } } }
        """ + _DECLARED_CI)

    with pytest.raises(ValueError, match=r"'build one' declares `ci: params:` and has no `cadence:`"):
        workflows_task.generate()


def test_an_env_ci_param_naming_a_variable_github_sets_renders_as_the_shell_expands_it():
    """Task 2b review: `{ env: NAME }` takes a declared step's form and its rendering (si#488)."""
    doc, _ = _rendered_with_pick("""
        ci:
          test:
            commands:
              pick: { task: pick, unattended: true, ci: { params: { target: { env: GITHUB_SHA } } } }
        """)
    assert _runs(doc) == ['test pick -- "$GITHUB_SHA"']


def test_an_env_ci_param_naming_a_variable_nothing_sets_is_refused_at_generation():
    """`_parameters`' own diagnosis, asked per job: nothing in the derived job sets `NOPE`, so it would expand to
    nothing and the command would run as if no value were given."""
    with pytest.raises(ValueError, match=r"`params: target` reads \$NOPE, and NOPE is set by no `env:`"):
        _rendered_with_pick("""
            ci:
              test:
                commands:
                  pick: { task: pick, unattended: true, ci: { params: { target: { env: NOPE } } } }
            """)


def test_the_model_step_carries_the_params():
    """The firn model's `Step.params` (si#863) is what the renderer reads, not the spec behind it."""
    loaded = manifest_mod.load(_PICK + textwrap.dedent("""
        ci:
          test:
            commands:
              pick: { task: pick, unattended: true, ci: { params: { mode: slow, target: { env: GITHUB_SHA } } } }
        """), catalogue=catalogue.load(), manifest_path="demo.yaml")
    (job,) = cipipeline.derive(loaded, {}).model.job
    (step,) = [step for step in job.step if step.command is not None]
    assert step.params == (workflowschema.StepParam(param_name="mode", param_value="slow"),
                           workflowschema.StepParam(param_name="target", param_env="GITHUB_SHA"))
