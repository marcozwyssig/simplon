"""si#522: `test:manifest-model` stages a throwaway firn project and hands firn's verdict through.

The container is replaced here: `toolchain.invocation` records what it was asked and `docker.run_container`
answers a chosen rc. What a real firn says over the staged project is `test_manifestcheck_e2e.py`'s. AAA.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplon.manifest import context
from simplon.tasks import manifestcheck as task

from test_manifestmodel import DEMO


@pytest.fixture
def product(monkeypatch, tmp_path):
    monkeypatch.setattr(context, "_current", None)
    manifest = tmp_path / "demo.yaml"
    manifest.write_text(DEMO)
    context.set_current(context.ProductContext(name="demo", root=tmp_path, manifest_path=manifest))
    monkeypatch.setattr(task.outputs, "root", lambda: tmp_path / "build")
    return tmp_path


@pytest.fixture
def firn(monkeypatch):
    """Records each invocation's keyword arguments; `answer.rc` is what the container exits with."""
    calls: list[dict] = []
    answer = SimpleNamespace(rc=0)

    def invocation(where, **kw):
        calls.append(kw)
        return ["true"], "n"
    monkeypatch.setattr(task.toolchain, "invocation", invocation)
    monkeypatch.setattr(task.docker, "run_container", lambda line, name, **kw: SimpleNamespace(rc=answer.rc))
    return calls, answer


def _ctx():
    return SimpleNamespace(command_path="test manifest-model")


def test_stage_writes_the_two_projects(tmp_path):
    # act
    reason = task.stage(tmp_path / "s", "demo", "package product.demo\n", task.m2_source(), "0.36.0")

    # assert
    assert reason == ""
    assert (tmp_path / "s" / "firn.toml").read_text() == (
        'name = "demo-manifest-check"\nmodel = ["model"]\n\n[dependencies]\nsimplon = { path = "m2" }\n')
    assert (tmp_path / "s" / "m2" / "firn.toml").read_text() == (
        'name = "simplon-m2"\nversion = "0.36.0"\nmodel = ["model"]\n')
    assert (tmp_path / "s" / "model" / "demo.firn").read_text() == "package product.demo\n"
    for package in task.M2_PACKAGES:
        assert list((tmp_path / "s" / "m2" / "model" / "simplon" / package).glob("*.firn")), package


def test_a_leftover_file_does_not_survive_staging(tmp_path):
    # arrange: an earlier run's export under another product name
    old = tmp_path / "s" / "model" / "old.firn"
    old.parent.mkdir(parents=True)
    old.write_text("package product.old\n")

    # act
    task.stage(tmp_path / "s", "demo", "package product.demo\n", task.m2_source(), "0.36.0")

    # assert
    assert not old.exists()


def test_a_package_without_the_m2_is_refused_by_name(tmp_path):
    # arrange: an installed simplon whose wheel lost its M2
    empty = tmp_path / "empty"
    empty.mkdir()

    # act
    reason = task.stage(tmp_path / "s", "demo", "x\n", empty, "0.36.0")

    # assert
    assert "manifest" in reason and str(empty) in reason


def test_the_m2_is_the_shipped_set_and_nothing_else():
    # act
    names = {path.name for path in task.m2_source().iterdir() if path.is_dir()}

    # assert
    assert set(task.M2_PACKAGES) <= names


@pytest.mark.parametrize("rc", [0, 1, 2, 3, 70])
def test_firns_rc_passes_through(product, firn, rc):
    # arrange
    _, answer = firn
    answer.rc = rc

    # act / assert
    assert task.check(_ctx(), image="ghcr.io/marcozwyssig/firn:v0.2.0") == rc


def test_the_check_runs_validate_in_the_stage(product, firn):
    # arrange
    calls, _ = firn

    # act
    task.check(_ctx(), image="ghcr.io/marcozwyssig/firn:v0.2.0")

    # assert
    (call,) = calls
    assert call["argv"] == ["validate"] and call["network"] == "none"
    assert call["cwd"] == "build/manifest-check" and call["workdir"] == "/workspace"


def test_a_manifest_that_does_not_export_is_rc_1_and_runs_nothing(product, firn, monkeypatch):
    # arrange
    calls, _ = firn

    def refuse():
        raise ValueError("the manifest is broken")
    monkeypatch.setattr(task.manifestmodel, "current", refuse)

    # act
    rc = task.check(_ctx(), image="ghcr.io/marcozwyssig/firn:v0.2.0")

    # assert
    assert rc == 1 and calls == []


def test_a_check_dir_outside_the_build_root_is_refused(product, firn, monkeypatch):
    # arrange: the container starts in <mount>/<build_root>, which the output root is not under
    calls, _ = firn
    monkeypatch.setattr(task, "_build_root", lambda: "sub")

    # act
    rc = task.check(_ctx(), image="ghcr.io/marcozwyssig/firn:v0.2.0")

    # assert
    assert rc == 1 and calls == []


def test_an_invocation_the_kernel_refuses_is_rc_1(product, firn, monkeypatch):
    # arrange: `invocation` logs its own fault and answers None
    monkeypatch.setattr(task.toolchain, "invocation", lambda where, **kw: None)

    # act / assert
    assert task.check(_ctx(), image="ghcr.io/marcozwyssig/firn:v0.2.0") == 1


def test_the_products_own_firn_toml_is_untouched(product, firn):
    # arrange: netctl keeps its own firn project at its root
    own = Path(product) / "firn.toml"
    own.write_text('name = "netctl"\nmodel = ["model"]\n')

    # act
    task.check(_ctx(), image="ghcr.io/marcozwyssig/firn:v0.2.0")

    # assert
    assert own.read_text() == 'name = "netctl"\nmodel = ["model"]\n'
