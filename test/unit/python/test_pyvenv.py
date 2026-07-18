"""Unit tests for the self-healing venv provisioning (netctl#475, kernel-extracted netctl#592). No real
venvs, no network; run() and urlretrieve are doubles that materialise the files a successful step would;
AAA throughout."""
import os

import pytest

from delivery import pyvenv
from delivery.run import Result


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
    monkeypatch.setattr(pyvenv.urllib.request, "urlretrieve",
                        lambda url, dest: fetched.append(url) or _executable(pyvenv.Path(dest)))

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
    monkeypatch.setattr(pyvenv.urllib.request, "urlretrieve", lambda url, dest: _executable(pyvenv.Path(dest)))
    monkeypatch.setattr(pyvenv.log, "die", _boom)

    # act / assert: the die names the apt fix
    with pytest.raises(SystemExit, match="python3-venv"):
        pyvenv.ensure_venv(venv)
