"""Unit tests for the self-healing venv provisioning (netctl#475, kernel-extracted netctl#592). No real
venvs, no network; run() and fetch.download are doubles that materialise the files a successful step would;
AAA throughout."""
import os

import pytest

from simplon import pyvenv
from simplon.run import Result


def _boom(msg):
    raise SystemExit(msg)


def _executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)


def test_healthy_venv_short_circuits_without_any_subprocess(monkeypatch, tmp_path):
    # arrange: a venv whose bin/pip is present and executable
    venv = tmp_path / ".venv"
    _executable(venv / "bin" / "pip")
    monkeypatch.setattr(pyvenv, "run", lambda argv, **kw: _boom(f"unexpected run: {argv}"))

    # act / assert: returned as-is, nothing executed
    assert pyvenv.ensure_venv(venv) == venv


def test_half_created_venv_is_rebuilt(monkeypatch, tmp_path):
    # arrange: the dir exists WITHOUT pip (the #467 shape); ensurepip works, venv creation heals it
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:3] == ["python3", "-m", "venv"]:
            _executable(venv / "bin" / "pip")
        return Result(rc=0, out="", err="")

    monkeypatch.setattr(pyvenv, "run", fake_run)

    # act
    pyvenv.ensure_venv(venv)

    # assert: the stale dir was wiped and recreated via plain `python3 -m venv`
    assert ["python3", "-m", "venv", str(venv)] in calls


def test_no_ensurepip_falls_back_to_get_pip(monkeypatch, tmp_path):
    # arrange: ensurepip probe fails, so the venv is created --without-pip and pip fetched into it
    venv = tmp_path / ".venv"
    calls = []
    fetched = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["python3", "-m"] and argv[2] == "ensurepip":
            return Result(rc=1, out="", err="")
        if "--without-pip" in argv:
            (venv / "bin").mkdir(parents=True, exist_ok=True)
            _executable(venv / "bin" / "python")
        if argv and argv[0] == str(venv / "bin" / "python"):
            _executable(venv / "bin" / "pip")  # get-pip.py materialises pip
        return Result(rc=0, out="", err="")

    monkeypatch.setattr(pyvenv, "run", fake_run)
    monkeypatch.setattr(pyvenv.fetch, "download",
                        lambda url, dest, **kw: fetched.append(url) or _executable(pyvenv.Path(dest)))

    # act
    pyvenv.ensure_venv(venv)

    # assert: --without-pip creation, one get-pip download, executed with the venv's python
    assert ["python3", "-m", "venv", "--without-pip", str(venv)] in calls
    assert fetched == [pyvenv.GET_PIP_URL]
    assert os.access(venv / "bin" / "pip", os.X_OK)


def test_dies_when_pip_cannot_be_provisioned_at_all(monkeypatch, tmp_path):
    # arrange: every strategy runs but nothing materialises a pip
    venv = tmp_path / ".venv"
    monkeypatch.setattr(pyvenv, "run", lambda argv, **kw: Result(rc=1, out="", err=""))
    monkeypatch.setattr(pyvenv.fetch, "download", lambda url, dest, **kw: _executable(pyvenv.Path(dest)))
    monkeypatch.setattr(pyvenv.log, "die", _boom)

    # act / assert: the die names the apt fix
    with pytest.raises(SystemExit, match="python3-venv"):
        pyvenv.ensure_venv(venv)


def test_venv_python_pip_returns_the_venv_bin_paths_and_installs_requirements(monkeypatch, tmp_path):
    # arrange: ensure_venv is a double that reports a ready venv; capture the pip install argv
    installs = []
    monkeypatch.setattr(pyvenv, "ensure_venv", lambda v: v)
    monkeypatch.setattr(pyvenv, "run",
                        lambda argv, **kw: installs.append(argv) or Result(rc=0, out="", err=""))

    # act
    py, pip = pyvenv.venv_python_pip(tmp_path)

    # assert: the returned executables live under <dir>/.venv/bin, and requirements.txt was pip-installed
    assert py == str(tmp_path / ".venv" / "bin" / "python")
    assert pip == str(tmp_path / ".venv" / "bin" / "pip")
    assert installs == [[pip, "install", "-q", "--disable-pip-version-check",
                         "-r", str(tmp_path / "requirements.txt")]]


# --- si#202: the host dependency has to be a diagnosis, and a failed install is not a red suite --------

def test_a_host_without_python3_is_refused_by_name_before_anything_is_wiped(monkeypatch, tmp_path):
    """Measured on 2026-09-12 with every `python*` removed from PATH: the run wiped the half-built venv
    and then ended in `FileNotFoundError: [Errno 2] No such file or directory: 'python3'`, a rendered
    traceback naming neither the tool nor the way out. The gate's own docstring promises the opposite."""
    # arrange: a half-created venv (bin/ but no pip) on a host with no python3
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    monkeypatch.setattr(pyvenv.shutil, "which", lambda name: None)
    monkeypatch.setattr(pyvenv, "run", lambda argv, **kw: _boom(f"unexpected run: {argv}"))
    monkeypatch.setattr(pyvenv.log, "die", _boom)

    # act / assert
    with pytest.raises(SystemExit) as raised:
        pyvenv.ensure_venv(venv)

    message = str(raised.value)
    assert "python3 is not on PATH" in message, message
    # the container route, because "install python3" is the wrong advice on a host with only bash+docker
    assert "results_from:" in message, message
    # and the tree it might have reused is still there
    assert (venv / "bin").is_dir()


def test_a_failed_dependency_install_dies_instead_of_returning_a_venv_without_the_suites_tools(
        monkeypatch, tmp_path):
    """si#202, measured: with a bad pin in a product's requirements.txt the rc was dropped, pytest was
    started out of a venv that had none, and the gate recorded `unit: failed (rc 1) - the suite ran and
    reported failures`. The suite never ran. pip's own text is quoted because only pip knows which line
    of the file it was."""
    # arrange
    monkeypatch.setattr(pyvenv, "ensure_venv", lambda v: v)
    monkeypatch.setattr(pyvenv, "run", lambda argv, **kw: Result(
        rc=1, out="", err="ERROR: No matching distribution found for allure-pytest==2.16.1"))
    monkeypatch.setattr(pyvenv.log, "die", _boom)

    # act / assert
    with pytest.raises(SystemExit) as raised:
        pyvenv.venv_python_pip(tmp_path)

    message = str(raised.value)
    assert "requirements.txt" in message, message
    assert "No matching distribution found for allure-pytest==2.16.1" in message, message
