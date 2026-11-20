"""Unit tests for the self-healing venv provisioning (netctl#475, kernel-extracted netctl#592). No network;
run() and fetch.download are doubles that materialise the files a successful step would, except in the
si#717 block at the foot, which builds real venvs because its defect is in what the OS does with a stale
shebang; AAA throughout."""
import os
import shutil
import subprocess

import pytest

from simplon.adapters import pyvenv
from simplon.kernel.run import Result


def _boom(msg):
    raise SystemExit(msg)


def _executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)


def _pip(venv):
    """A pip the way pip's script maker writes it: a launcher naming this venv's own python (si#717)."""
    _executable(venv / "bin" / "python")
    pip = venv / "bin" / "pip"
    pip.write_text(f"#!{venv}/bin/python\n")
    pip.chmod(0o755)


def test_healthy_venv_short_circuits_without_any_subprocess(monkeypatch, tmp_path):
    # arrange: a venv whose bin/pip is present and executable
    venv = tmp_path / ".venv"
    _pip(venv)
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
            _pip(venv)
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
            _pip(venv)  # get-pip.py materialises pip
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


def test_a_tampered_get_pip_is_refused_and_never_run(monkeypatch, tmp_path):
    # arrange (si#668): ensurepip is missing, so get-pip.py is the route; the real download serves a
    # script that is not the pinned one
    import servedbytes
    venv = tmp_path / ".venv"
    ran = []

    def fake_run(argv, **kw):
        ran.append(argv)
        if argv[:3] == ["python3", "-m", "ensurepip"]:
            return Result(rc=1, out="", err="")
        if "--without-pip" in argv:
            _executable(venv / "bin" / "python")
        return Result(rc=0, out="", err="")

    monkeypatch.setattr(pyvenv, "run", fake_run)
    servedbytes.serve(monkeypatch, b"print('not get-pip')\n")
    monkeypatch.setattr(pyvenv.log, "die", _boom)

    # act
    with pytest.raises(SystemExit) as refused:
        pyvenv.ensure_venv(venv)

    # assert: the refusal names the URL and the pin, and the venv's python never ran a script
    assert pyvenv.GET_PIP_URL in str(refused.value) and pyvenv.GET_PIP_SHA256 in str(refused.value)
    assert not [argv for argv in ran if argv[0] == str(venv / "bin" / "python")]
    assert not (venv / "get-pip.py").exists()


# --- si#717: a venv moved (or copied) with its repository keeps a pip bound to another venv --------------
#
# REAL venvs, not doubles, because the defect lives in what the OS does with a stale shebang: `bin/pip` is
# present and executable, so `os.access(pip, X_OK)` said healthy, and posix_spawn then raised
# `FileNotFoundError` naming the pip that exists. A double that writes `#!/bin/sh` cannot show that.

def _host_has_ensurepip():
    if not shutil.which("python3"):
        return False
    return subprocess.run(["python3", "-m", "ensurepip", "--version"], capture_output=True).returncode == 0


needs_ensurepip = pytest.mark.skipif(not _host_has_ensurepip(),
                                     reason="no python3 with ensurepip here to build a real venv from")


def _real_venv(path):
    subprocess.run(["python3", "-m", "venv", str(path)], check=True, capture_output=True)
    return path


@needs_ensurepip
def test_a_venv_moved_with_its_repository_is_rebuilt_and_its_suite_installs(tmp_path):
    """Measured on agile-cockpit (2026-11-16): after the repository moved, every suite gate died with
    `FileNotFoundError: ... .venv/bin/pip` before a test ran; moving the `.venv` away made each one pass."""
    # arrange: a real venv built at the old path, then the whole suite directory moved
    old = tmp_path / "old" / "suite"
    _real_venv(old / ".venv")
    (old / "requirements.txt").write_text("")
    suite = tmp_path / "new" / "suite"
    suite.parent.mkdir()
    old.rename(suite)
    assert os.access(suite / ".venv" / "bin" / "pip", os.X_OK)  # all the old probe looked at

    # act
    py, pip = pyvenv.venv_python_pip(suite)

    # assert: pip runs, and it runs as this venv
    assert subprocess.run([pip, "--version"], capture_output=True).returncode == 0
    prefix = subprocess.run([py, "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True)
    assert prefix.stdout.strip() == str(suite / ".venv")


@needs_ensurepip
def test_a_venv_copied_while_the_original_still_exists_is_rebuilt(tmp_path):
    """The copied shape of the same defect, measured on 2026-11-20: the copy's pip runs, through the
    ORIGINAL venv's python, and installs into the original. The suite would then start without its
    dependencies, so 'pip runs' is not the health check - 'pip runs as this venv' is."""
    # arrange
    original = _real_venv(tmp_path / "a" / ".venv")
    copy = tmp_path / "b" / ".venv"
    shutil.copytree(original, copy, symlinks=True)

    # act
    pyvenv.ensure_venv(copy)

    # assert: the copy's pip now reports the copy's site-packages, and the original was left alone
    said = subprocess.run([str(copy / "bin" / "pip"), "--version"], capture_output=True, text=True).stdout
    assert str(copy) in said, said
    assert (original / "bin" / "pip").read_text().startswith(f"#!{original}/bin/python")


def test_a_long_path_pip_wrapper_bound_to_its_own_venv_is_healthy(monkeypatch, tmp_path):
    # arrange: past the kernel's shebang length pip writes a `#!/bin/sh` wrapper whose `exec` line names
    # the interpreter; read naively, `/bin/sh` exists and is not this venv's
    venv = tmp_path / ".venv"
    _executable(venv / "bin" / "python")
    pip = venv / "bin" / "pip"
    pip.write_text(f"#!/bin/sh\n'''exec' {venv}/bin/python \"$0\" \"$@\"\n' '''\nimport sys\n")
    pip.chmod(0o755)
    monkeypatch.setattr(pyvenv, "run", lambda argv, **kw: _boom(f"unexpected run: {argv}"))

    # act / assert: returned as-is, nothing executed
    assert pyvenv.ensure_venv(venv) == venv


def test_a_venv_that_cannot_be_rebuilt_is_refused_by_name_with_the_way_out(monkeypatch, tmp_path):
    # arrange: a stale pip whose interpreter is gone, and a rebuild that removes nothing and fixes nothing
    venv = tmp_path / ".venv"
    pip = venv / "bin" / "pip"
    pip.parent.mkdir(parents=True)
    pip.write_text("#!/nowhere/old/.venv/bin/python3\n")
    pip.chmod(0o755)
    monkeypatch.setattr(pyvenv.shutil, "rmtree", lambda *a, **kw: None)
    monkeypatch.setattr(pyvenv, "run", lambda argv, **kw: Result(rc=0, out="", err=""))
    monkeypatch.setattr(pyvenv.log, "die", _boom)

    # act / assert: a refusal, never a returned venv a suite would then run out of
    with pytest.raises(SystemExit) as refused:
        pyvenv.ensure_venv(venv)
    message = str(refused.value)
    assert f"Remove {venv}" in message, message
