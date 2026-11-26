"""si#873: every job of every workflow `support github workflows` writes checks the manifest's `sources:` out
right after its checkout, through the command the product placed `support:sources` at."""
from __future__ import annotations

import textwrap

import yaml

from simplon.manifest import context
from simplon.tasks import cipipeline, workflowgen
from simplon.tasks import workflows as workflows_task

_HEAD = """
tasks:
  ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
runner: { kind: self-hosted-debian, labels: ghr-8 }
support:
  commands:
    ci-docker-preflight: { task: "support:ci-docker-preflight" }
    ci-disk-preflight: { task: "support:ci-disk-preflight" }
    ci-disk-cleanup: { task: "support:ci-disk-cleanup" }
"""

_SOURCES = """
sources:
  - { submodule: lib/platform, secret: PLATFORM_REPO_TOKEN }
"""

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

_DECLARED = """
workflows:
  release:
    on: [push]
    jobs:
      build:
        runner: { kind: self-hosted-debian, labels: ghr-8 }
        steps:
          - command: test two
      lint:
        runs-on: ubuntu-latest
        python: "3.12"
        steps:
          - command: test three
      own:
        runs-on: ubuntu-latest
        checkout: false
        steps:
          - command: test three
"""

_ENV = {"PLATFORM_REPO_TOKEN": "${{ secrets.PLATFORM_REPO_TOKEN }}"}


def _generated(tmp_path, monkeypatch, *parts: str) -> dict[str, tuple[dict, str]]:
    """Every workflow the real `support github workflows` writes for the joined manifest, read back by path."""
    manifest_path = tmp_path / "demo.yaml"
    manifest_path.write_text(_HEAD + "".join(textwrap.dedent(part) for part in parts), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(name="demo", root=tmp_path,
                                                                     manifest_path=manifest_path))
    assert workflows_task.generate() == 0
    return {path.name: (yaml.safe_load(text), text)
            for path in sorted((tmp_path / ".github/workflows").iterdir())
            for text in (path.read_text(encoding="utf-8"),)}


def _steps(doc: dict, job: str) -> list[dict]:
    return [step for step in doc["jobs"][job]["steps"] if step.get("name") != workflowgen.REAP_NAME]


def _is_sources(step: dict) -> bool:
    return str(step.get("run", "")).endswith(" support sources")


def test_declared_job_gets_the_sources_step_after_checkout(tmp_path, monkeypatch):
    files = _generated(tmp_path, monkeypatch, _THREE, _SOURCES, _DECLARED)
    doc, _ = files["release.yml"]

    build = _steps(doc, "build")
    assert build[0]["uses"] == workflowgen.CHECKOUT_ACTION
    assert build[1] == {"env": _ENV, "run": "exec ./demo.sh support sources"}
    assert [step.get("run") for step in build[2:4]] == ["exec ./demo.sh support ci-docker-preflight",
                                                       "exec ./demo.sh support ci-disk-preflight"]

    lint = _steps(doc, "lint")
    assert [step.get("uses") for step in lint[:2]] == [workflowgen.CHECKOUT_ACTION, workflowgen.SETUP_PYTHON_ACTION]
    assert lint[2] == {"env": _ENV, "run": "exec ./demo.sh support sources"}
    assert lint[3]["run"] == "exec ./demo.sh test three"


def test_a_public_source_gets_no_env(tmp_path, monkeypatch):
    files = _generated(tmp_path, monkeypatch, _THREE, "sources:\n  - { submodule: lib/open }\n", _DECLARED)
    doc, text = files["release.yml"]
    assert _steps(doc, "build")[1] == {"run": "exec ./demo.sh support sources"}
    assert "secrets." not in text


def test_derived_job_gates_leaves_on_sources(tmp_path, monkeypatch):
    """Review Focus 4: a red sources step skips every leaf after it; the first leaf waits on GitHub's
    default `success()`."""
    files = _generated(tmp_path, monkeypatch, _THREE, _SOURCES)
    doc, _ = files["ci.yml"]
    steps = _steps(doc, "ci")
    assert steps[0]["uses"] == workflowgen.CHECKOUT_ACTION
    assert steps[1] == {"id": "prepare_sources", "env": _ENV, "run": "exec ./demo.sh support sources"}
    prepared = [step["id"] for step in steps if str(step.get("id", "")).startswith("prepare_")]
    assert prepared[0] == "prepare_sources"
    leaves = [step for step in steps if step.get("run", "").split()[-2:-1] in (["build"], ["test"])]
    assert [step["run"] for step in leaves] == ["exec ./demo.sh build one", "exec ./demo.sh test two",
                                                "exec ./demo.sh test three"]
    assert "if" not in leaves[0]
    for leaf in leaves[1:]:
        assert "steps.prepare_sources.outcome == 'success'" in leaf["if"]


def test_cell_job_gets_sources(tmp_path, monkeypatch):
    cells = """
    ci:
      test:
        commands:
          one: { task: ship, unattended: true }
          py: { task: ship, unattended: true, ci: { python: ["3.12", "3.13"] } }
          plat: { task: ship, unattended: true, ci: { platforms: [linux-x64, windows-x64] } }
    """
    files = _generated(tmp_path, monkeypatch, cells, _SOURCES)
    doc, _ = files["ci.yml"]
    python = _steps(doc, "test-py-python")
    assert [step.get("uses") for step in python[:2]] == [workflowgen.CHECKOUT_ACTION, workflowgen.SETUP_PYTHON_ACTION]
    assert python[2] == {"id": "prepare_sources", "env": _ENV, "run": "exec ./demo.sh support sources"}
    platforms = _steps(doc, "test-plat-platforms")
    (sources,) = [step for step in platforms if _is_sources(step)]
    assert sources == {"id": "prepare_sources", "env": _ENV, "run": "${{ matrix.entry }} support sources"}
    arch = next(i for i, s in enumerate(platforms) if "uname -m" in s.get("run", ""))
    assert arch < platforms.index(sources)
    assert platforms.index(sources) < next(i for i, s in enumerate(platforms) if s.get("run", "").endswith("test plat"))


def test_no_checkout_no_sources(tmp_path, monkeypatch):
    """Review Focus 5: the si#861 decide job and a declared `checkout: false` job carry no sources step and no
    `secrets.` text."""
    gated = """
    ci:
      test:
        commands:
          two: { task: ship, unattended: true }
          three: { task: ship, unattended: true }
          lab: { task: ship, unattended: true }
          all: { depends_on: [lab], help: "All.", ci: { gate: { label: needs-lab } } }
    """
    files = _generated(tmp_path, monkeypatch, gated, _SOURCES, _DECLARED)
    (gate_doc, _), = [files[name] for name in files if cipipeline.DECIDE_JOB in files[name][0]["jobs"]]
    for doc, job in ((gate_doc, cipipeline.DECIDE_JOB), (files["release.yml"][0], "own")):
        body = doc["jobs"][job]
        assert not any(_is_sources(step) for step in body["steps"])
        assert "secrets." not in yaml.safe_dump(body)
    # the gated job behind the decide job checks out, so it gets the step
    gated_job = next(job for job in gate_doc["jobs"] if job != cipipeline.DECIDE_JOB)
    assert any(_is_sources(step) for step in gate_doc["jobs"][gated_job]["steps"])


def test_no_sources_section_is_byte_identical(tmp_path, monkeypatch):
    """No section and an empty one write the same bytes, and neither names the command anywhere (the goldens in
    fixtures/workflows and simplon's own `--check` pin the rest)."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    absent = _generated(tmp_path / "a", monkeypatch, _THREE, _DECLARED)
    empty = _generated(tmp_path / "b", monkeypatch, _THREE, "sources: []\n", _DECLARED)
    assert {name: text for name, (_, text) in absent.items()} == {name: text for name, (_, text) in empty.items()}
    assert not any("support sources" in text for _, text in absent.values())


def test_sources_without_placement_is_said(tmp_path, monkeypatch):
    """A product that places another body at `support sources` (`override: true`) has `support:sources` nowhere:
    every job says so in its note, and no step guesses a command line."""
    unplaced = """
    support:
      commands:
        ci-docker-preflight: { task: "support:ci-docker-preflight" }
        ci-disk-preflight: { task: "support:ci-disk-preflight" }
        ci-disk-cleanup: { task: "support:ci-disk-cleanup" }
        sources: { task: ship, override: true }
    """
    head = _HEAD.split("support:")[0]
    manifest_path = tmp_path / "demo.yaml"
    manifest_path.write_text(head + "".join(textwrap.dedent(p) for p in (unplaced, _THREE, _SOURCES, _DECLARED)),
                             encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(name="demo", root=tmp_path,
                                                                     manifest_path=manifest_path))
    assert workflows_task.generate() == 0
    for name in ("ci.yml", "release.yml"):
        text = (tmp_path / ".github/workflows" / name).read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
        assert not any(_is_sources(step) for job in doc["jobs"].values() for step in job["steps"])
        assert "secrets.PLATFORM_REPO_TOKEN" not in text
        assert 'checkout-sources: { task: "support:sources" }' in text


def test_the_release_job_gets_the_sources_step_after_its_checkout():
    """The release job (derived through the model since si#862) is a job that checks out, so it gets the step there too; a later
    `checkout=False` on it turns this red."""
    from simplon.manifest import artifactsection, catalogue
    from simplon.manifest import load as manifest_mod
    from test_workflowgen import _RELEASE_PRODUCT, _RELEASE_WORKFLOWS, _section

    product = _RELEASE_PRODUCT + _SOURCES
    loaded = manifest_mod.load(product, catalogue=catalogue.load(), manifest_path="app.yaml")
    data = {**yaml.safe_load(product), **_section(_RELEASE_WORKFLOWS)}
    from simplon.tasks import releasepipeline
    entry = workflowgen.parse(data)[0]
    release = releasepipeline.to_workflow(releasepipeline.derive(loaded, data, entry), loaded, data, entry, product="app")
    text = workflowgen.render(release, manifest=loaded, product="app", source="app.yaml",
                              artifacts=artifactsection.declared(data))
    steps = _steps(yaml.safe_load(text), workflowgen.RELEASE_JOB)
    assert steps[0]["uses"] == workflowgen.CHECKOUT_ACTION
    assert steps[1] == {"env": _ENV, "run": "exec ./app.sh support sources"}


def test_the_unplaced_advice_places_the_step_beside_the_override(tmp_path, monkeypatch):
    """The line `SOURCES_UNPLACED` hands the product, added beside its override, loads and gets every job the
    step: advice that collided with the override's own name would be refused by the merge instead."""
    advice = workflowgen.SOURCES_UNPLACED.strip().splitlines()[-1].strip()
    unplaced = f"""
    support:
      commands:
        ci-docker-preflight: {{ task: "support:ci-docker-preflight" }}
        ci-disk-preflight: {{ task: "support:ci-disk-preflight" }}
        ci-disk-cleanup: {{ task: "support:ci-disk-cleanup" }}
        sources: {{ task: ship, override: true }}
        {advice}
    """
    assert advice.endswith('{ task: "support:sources" }')
    head = _HEAD.split("support:")[0]
    manifest_path = tmp_path / "demo.yaml"
    manifest_path.write_text(head + "".join(textwrap.dedent(p) for p in (unplaced, _THREE, _SOURCES, _DECLARED)),
                             encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(name="demo", root=tmp_path,
                                                                     manifest_path=manifest_path))
    assert workflows_task.generate() == 0
    doc = yaml.safe_load((tmp_path / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    name = advice.split(":")[0]
    assert any(str(step.get("run", "")).endswith(f" support {name}")
               for job in doc["jobs"].values() for step in job["steps"])
