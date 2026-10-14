"""si#344 C.4: what the generated workflow says when an artifact crosses a job boundary (spec C.6).

AAA; the name states the behaviour under test. The tar lines are run for real: they are what crosses, and a
claim about them that was never executed is not yet a claim.
"""
import os
import stat
import subprocess
import textwrap

import pytest
import yaml

from simplon.domain import artifactsection, catalogue as catalogue_mod, manifest as manifest_mod
from simplon.tasks import workflowgen

from conftest import ROOT

TEXT = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      push-image: { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
"""

LOADED = manifest_mod.load(TEXT, catalogue=catalogue_mod.load(), manifest_path="demo.yaml")
ARTIFACTS = artifactsection.declared(yaml.safe_load(TEXT))

SPLIT = """
workflows:
  ci:
    on: [push]
    jobs:
      test:
        runs-on: ubuntu-latest
        steps:
          - command: build image
          - command: test image
      release:
        runs-on: ubuntu-latest
        steps:
          - command: build image
          - command: release push-image
"""


def _render(body, key="ci"):
    picked = next(w for w in workflowgen.parse(yaml.safe_load(textwrap.dedent(body))) if w.key == key)
    return workflowgen.render(picked, manifest=LOADED, product="demo", source="demo.yaml", artifacts=ARTIFACTS)


def _steps(doc, job):
    return doc["jobs"][job]["steps"]


def test_the_producing_job_archives_and_uploads_after_its_producing_step():
    # act
    doc = yaml.safe_load(_render(SPLIT))

    # assert: checkout, build image, test image, tar, upload
    steps = _steps(doc, "test")
    assert steps[2]["run"] == "./demo.sh test image"
    assert steps[3]["run"] == 'tar -cf "${{ runner.temp }}/simplon-handoff-app-checked.tar" build/test/app.json'
    assert steps[4] == {"uses": "actions/upload-artifact@v4",
                        "with": {"name": "app-checked",
                                 "path": "${{ runner.temp }}/simplon-handoff-app-checked.tar",
                                 "if-no-files-found": "error"}}


def test_the_consuming_job_needs_the_producer_and_downloads_before_its_consuming_step():
    # act
    doc = yaml.safe_load(_render(SPLIT))

    # assert: checkout, build image, download, untar, push
    job = doc["jobs"]["release"]
    assert job["needs"] == "test"
    steps = job["steps"]
    assert steps[2] == {"uses": "actions/download-artifact@v4",
                        "with": {"name": "app-checked", "path": "${{ runner.temp }}"}}
    assert steps[3]["run"] == 'tar -xf "${{ runner.temp }}/simplon-handoff-app-checked.tar"'
    assert steps[4]["run"] == "./demo.sh release push-image"


def test_the_file_says_why_the_kernel_wrote_the_handoff_steps():
    # act
    text = _render(SPLIT)

    # assert
    assert "upload-artifact drops file permissions" in text


def test_a_declared_needs_is_kept_first_and_not_repeated():
    # arrange: `release` already waits for a `lint` job of its own, and for `test`
    body = SPLIT.replace("      release:\n        runs-on: ubuntu-latest\n",
                         "      release:\n        runs-on: ubuntu-latest\n        needs: [lint, test]\n") + """\
      lint:
        runs-on: ubuntu-latest
        steps:
          - run: echo lint
"""

    # act
    doc = yaml.safe_load(_render(body))

    # assert
    assert doc["jobs"]["release"]["needs"] == ["lint", "test"]


def test_a_declared_needs_string_becomes_a_list_when_the_handoff_adds_a_job():
    # arrange
    body = SPLIT.replace("      release:\n        runs-on: ubuntu-latest\n",
                         "      release:\n        runs-on: ubuntu-latest\n        needs: lint\n") + """\
      lint:
        runs-on: ubuntu-latest
        steps:
          - run: echo lint
"""

    # act
    doc = yaml.safe_load(_render(body))

    # assert
    assert doc["jobs"]["release"]["needs"] == ["lint", "test"]


def test_a_workflow_with_no_edge_across_jobs_renders_as_it_did():
    # arrange: one job runs the whole chain
    body = """
    workflows:
      ci:
        on: [push]
        jobs:
          all:
            runs-on: ubuntu-latest
            steps:
              - command: build image
              - command: test image
              - command: release push-image
    """

    # act
    text = _render(body)

    # assert
    assert "upload-artifact" not in text and "download-artifact" not in text
    assert "needs" not in yaml.safe_load(text)["jobs"]["all"]


def test_an_aggregate_step_hands_over_what_its_leaves_produce():
    # arrange: an aggregate over the test leaf, run in the test job
    text = TEXT.replace("  test:\n    commands:\n",
                        "  test:\n    commands:\n      all: { depends_on: [check], help: \"Every test.\" }\n"
                        ).replace("      image: { task: \"test:image\"", "      check: { task: \"test:image\"")
    loaded = manifest_mod.load(text, catalogue=catalogue_mod.load(), manifest_path="demo.yaml")
    body = SPLIT.replace("- command: test image", "- command: test all")
    picked = next(w for w in workflowgen.parse(yaml.safe_load(textwrap.dedent(body))) if w.key == "ci")

    # act
    doc = yaml.safe_load(workflowgen.render(picked, manifest=loaded, product="demo", source="demo.yaml",
                                            artifacts=artifactsection.declared(yaml.safe_load(text))))

    # assert
    assert doc["jobs"]["test"]["steps"][4]["with"]["name"] == "app-checked"


def test_a_refusal_stops_generation_and_names_the_workflow():
    # arrange: the release job runs the push and nothing writes its evidence
    body = """
    workflows:
      release:
        on: [push]
        jobs:
          image:
            runs-on: ubuntu-latest
            steps:
              - command: build image
              - command: release push-image
    """

    # act / assert
    with pytest.raises(ValueError, match="workflow 'release', job 'image': 'release push-image' consumes "
                                         "'app-checked', and no job in this workflow produces it"):
        _render(body, key="release")


def test_simplons_own_ci_renders_byte_identical_and_hands_nothing_over():
    # arrange
    text = (ROOT / "simplon.yaml").read_text(encoding="utf-8")
    loaded = manifest_mod.load(text, catalogue=catalogue_mod.load(), manifest_path="simplon.yaml")
    data = yaml.safe_load(text)
    ci = next(w for w in workflowgen.parse(data) if w.key == "ci")

    # act
    rendered = workflowgen.render(ci, manifest=loaded, product="simplon", source="simplon.yaml",
                                  artifacts=artifactsection.declared(data))

    # assert
    assert rendered == (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "download-artifact" not in rendered


def _lines(doc):
    """The tar lines the generator wrote, with `${{ runner.temp }}` replaced the way the runner replaces it."""
    pack = _steps(doc, "test")[3]["run"]
    unpack = _steps(doc, "release")[3]["run"]
    return pack, unpack


def _sh(line, cwd, temp):
    return subprocess.run(["bash", "-c", line.replace("${{ runner.temp }}", str(temp))], cwd=cwd,
                          capture_output=True, text=True)


def test_the_handoff_lines_restore_the_path_and_its_mode(tmp_path):
    # arrange: the producing job's checkout holds the result, executable, under its relative path
    pack, unpack = _lines(yaml.safe_load(_render(SPLIT)))
    producer, consumer, temp = tmp_path / "producer", tmp_path / "consumer", tmp_path / "temp"
    for d in (producer, consumer, temp):
        d.mkdir()
    made = producer / "build" / "test" / "app.json"
    made.parent.mkdir(parents=True)
    made.write_text('{"rc": 0}\n', encoding="utf-8")
    made.chmod(0o755)

    # act: pack in the producer, unpack in a fresh consumer checkout
    packed = _sh(pack, producer, temp)
    unpacked = _sh(unpack, consumer, temp)

    # assert
    assert packed.returncode == 0 and unpacked.returncode == 0, packed.stderr + unpacked.stderr
    got = consumer / "build" / "test" / "app.json"
    assert got.read_text(encoding="utf-8") == '{"rc": 0}\n'
    assert stat.S_IMODE(os.stat(got).st_mode) == 0o755


def test_the_handoff_lines_fail_on_a_path_that_was_not_written(tmp_path):
    # arrange: the producer exited 0 and wrote nothing
    pack, _ = _lines(yaml.safe_load(_render(SPLIT)))
    temp = tmp_path / "temp"
    temp.mkdir()

    # act
    packed = _sh(pack, tmp_path, temp)

    # assert
    assert packed.returncode != 0
    assert "build/test/app.json" in packed.stderr
