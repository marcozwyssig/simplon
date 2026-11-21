"""si#756: the generated job removes what a cancelled job left running, BEFORE its own checkout.

The kernel labels every container it starts `simplon.run=<product>` (si#409, si#412), and a runner's
SIGKILL ten seconds into a cancel is the one signal no handler sees, so on a machine that survives the
job the container runs on into the next job's checkout. firn wrote the reaping step by hand and had to
say `checkout: false` to put it first, which cost it the generator's checkout rules (firn#1314). Decided on
si#756: the kernel emits the step, ahead of the checkout it emits, and the product writes nothing.

Two halves. The generator half reads the rendered file. The behaviour half runs the rendered script
against the real docker daemon on this machine, with the shell GitHub uses for `shell: bash`, because a
stub would confirm exactly the assumptions written into it - and the three outcomes the script must keep
apart ("removed some", "nothing there", "could not look" / "could not remove") are exactly what a stub
would get right by construction.
"""
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

from simplon.adapters import docker
from simplon.manifest import catalogue as catalogue_mod
from simplon.manifest import load as manifest_mod
from simplon.tasks import dockerpreflight, workflowgen

from conftest import ROOT, docker_is_usable

_MANIFEST = """
tasks:
  suite: { impl: "simplon.test_impls:nullary", help: "Run every test." }

ci:
  test:
    commands:
      all: { task: suite }
"""

_JOBS = """
workflows:
  ci:
    on: [push]
    jobs:
      hosted:
        runs-on: ubuntu-latest
        steps:
          - command: test all
      own-machine:
        runs-on: firn
        steps:
          - command: test all
      kind:
        runner: { kind: self-hosted-debian, labels: ghr-8 }
        steps:
          - command: test all
      no-checkout:
        runs-on: firn
        checkout: false
        steps:
          - run: echo mine
"""


@pytest.fixture(scope="module")
def manifest():
    return manifest_mod.load(_MANIFEST, catalogue=catalogue_mod.load())


def _render(manifest, product: str = "sample") -> str:
    workflow = workflowgen.parse(yaml.safe_load(_JOBS))[0]
    return workflowgen.render(workflow, manifest=manifest, product=product, source=f"{product}.yaml", artifacts={})


def _reap_step(manifest, product: str = "sample") -> dict:
    return yaml.safe_load(_render(manifest, product))["jobs"]["hosted"]["steps"][0]


# --- the generator ---------------------------------------------------------------------------------------------


def test_every_job_reaps_first_and_checks_out_second(manifest):
    # arrange / act: a GitHub-hosted job, a machine named only by its label, a kind, and a job without
    # the generated checkout - the step does not depend on how the machine was named
    jobs = yaml.safe_load(_render(manifest))["jobs"]

    # assert
    for name, job in jobs.items():
        assert job["steps"][0]["name"] == workflowgen.REAP_NAME, name
    for name in ("hosted", "own-machine", "kind"):
        assert jobs[name]["steps"][1]["uses"] == workflowgen.CHECKOUT_ACTION, name
    assert jobs["no-checkout"]["steps"][1] == {"run": "echo mine"}


def test_the_step_runs_wherever_the_machine_outlives_the_job(manifest):
    # arrange / act
    step = _reap_step(manifest)

    # assert: skipped on a GitHub-hosted machine, which is destroyed after every job, and on Windows,
    # where `shell: bash` is not a given. An EMPTY `runner.environment` (a runner too old to set it) is
    # not 'github-hosted', so the step runs there: unknown errs toward looking, never toward skipping.
    assert step["if"] == "runner.environment != 'github-hosted' && runner.os != 'Windows'"
    assert step["shell"] == "bash"


def test_the_step_has_a_time_limit(manifest):
    # a hung daemon is neither green nor red without one
    assert isinstance(_reap_step(manifest)["timeout-minutes"], int)


def test_the_step_selects_by_the_kernels_own_label_and_the_product(manifest):
    # arrange / act
    run = _reap_step(manifest, product="firn")["run"]

    # assert: the label the launcher and `docker.lifecycle_args` set, valued with this product
    assert f"label={docker.RUN_LABEL}=firn" in run


def test_simplons_own_workflows_reap_first_in_every_job():
    # arrange: the committed, generated files, derived release jobs included
    files = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

    # act
    firsts = {(path.name, name): job["steps"][0].get("name")
              for path in files for name, job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].items()}

    # assert
    assert firsts
    assert set(firsts.values()) == {workflowgen.REAP_NAME}, firsts


# --- the script, against the real daemon --------------------------------------------------------------------------

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to reap from")


def _docker(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=60)


def _alive(cid: str) -> bool:
    return bool(_docker("ps", "--all", "--quiet", "--no-trunc", "--filter", f"id={cid}").stdout.strip())


def _start(*, label: str | None, mount: Path, rm: bool = True) -> str:
    out = _docker("run", "--detach", *(["--rm"] if rm else []), *(["--label", label] if label else []),
                  "-v", f"{mount}:/work", dockerpreflight.PROBE_IMAGE, "sleep", "300")
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _reap(manifest, product: str, workspace: Path, *, env: dict | None = None) -> subprocess.CompletedProcess:
    """The rendered step, run the way GitHub runs `shell: bash`: `bash --noprofile --norc -eo pipefail`."""
    script = workspace.parent / "reap.sh"
    script.write_text(_reap_step(manifest, product)["run"], encoding="utf-8")
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                          capture_output=True, text=True, timeout=120,
                          env={**os.environ, "GITHUB_WORKSPACE": str(workspace),
                               "RUNNER_TEMP": str(workspace.parent), **(env or {})})


@pytest.fixture
def staged(tmp_path):
    """A workspace, a directory outside it, a product nobody else uses, and every container cleaned up."""
    workspace, elsewhere = tmp_path / "ws", tmp_path / "elsewhere"
    (workspace / "build").mkdir(parents=True)
    elsewhere.mkdir()
    started: list[str] = []
    yield workspace, elsewhere, f"reap{uuid.uuid4().hex[:10]}", started
    for cid in started:
        _docker("rm", "--force", cid)


@needs_docker
def test_only_this_products_containers_mounting_this_workspace_are_removed(manifest, staged):
    # arrange
    workspace, elsewhere, product, started = staged
    label = f"{docker.RUN_LABEL}={product}"
    orphan_rm = _start(label=label, mount=workspace / "build")
    orphan_kept = _start(label=label, mount=workspace, rm=False)
    other_checkout = _start(label=label, mount=elsewhere)
    unlabelled = _start(label=None, mount=workspace)
    other_product = _start(label=f"{docker.RUN_LABEL}={product}x", mount=workspace)
    started += [orphan_rm, orphan_kept, other_checkout, unlabelled, other_product]

    # act
    result = _reap(manifest, product, workspace)

    # assert
    assert result.returncode == 0, result.stdout + result.stderr
    assert not _alive(orphan_rm) and not _alive(orphan_kept)
    assert _alive(other_checkout) and _alive(unlabelled) and _alive(other_product)
    assert "2 orphaned container(s) removed" in result.stdout
    assert "::warning::" not in result.stdout and "::error::" not in result.stdout


@needs_docker
def test_nothing_to_reap_is_green_and_says_so(manifest, staged):
    # arrange
    workspace, _, product, _ = staged

    # act
    result = _reap(manifest, product, workspace)

    # assert
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 orphaned container(s) removed" in result.stdout
    assert "::warning::" not in result.stdout


@needs_docker
def test_a_daemon_it_cannot_ask_is_a_warning_and_not_nothing_to_do(manifest, staged, tmp_path):
    # arrange: a client pointed at a socket that is not there
    workspace, _, product, _ = staged

    # act
    result = _reap(manifest, product, workspace, env={"DOCKER_HOST": f"unix://{tmp_path}/no.sock"})

    # assert: the job goes on - its own first docker step meets the same daemon and says why - but the
    # file's verdict is not the green "0 removed" a clean machine gets
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::" in result.stdout
    assert "orphaned container(s) removed" not in result.stdout


@needs_docker
def test_an_orphan_it_cannot_remove_fails_the_step(manifest, staged, tmp_path):
    # arrange: the real client on PATH, except that it refuses to remove anything
    workspace, _, product, started = staged
    orphan = _start(label=f"{docker.RUN_LABEL}={product}", mount=workspace, rm=False)
    started.append(orphan)
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "docker").write_text(f'#!/bin/sh\n[ "$1" = rm ] && {{ echo refused >&2; exit 1; }}\n'
                                 f'exec {shutil.which("docker")} "$@"\n', encoding="utf-8")
    (shim / "docker").chmod(0o755)

    # act
    result = _reap(manifest, product, workspace, env={"PATH": f"{shim}:{os.environ['PATH']}"})

    # assert: the orphan writes into this job's checkout, so a green job on top of it is no verdict
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert _alive(orphan)
