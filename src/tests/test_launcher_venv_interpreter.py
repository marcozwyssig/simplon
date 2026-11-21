"""si#844: the launcher rebuilds a venv whose pip runs under no interpreter of its own - si#717's rule.

si#717 taught `adapters.pyvenv.ensure_venv` that an executable `bin/pip` is not a healthy venv: its
launcher names the interpreter it runs under, and that interpreter can be gone (Homebrew removed
python@3.14 under netctl's venv, netctl#2022) or live in another venv (a venv copied with its
repository). The launcher's own venv check stayed `[ ! -x "$PIP" ]`, so such a venv passed it and the
run died afterwards on `.venv/bin/python: No such file or directory`, rc 127, naming nothing.

Every test here runs the REAL rendered launcher with bash against a REAL venv. A venv whose python is
gone is made the way it happens: the venv is created from a copied python binary, and the copy is
deleted. Only the last test stages its failure (a python3 on PATH that writes a bad pip), and says so.
The product's requirements are empty and its orchestrator prints its interpreter, so nothing here needs
the network.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simplon.cli import bootstrap

pytestmark = pytest.mark.skipif(sys.platform == "win32" or shutil.which("python3") is None,
                                reason="the .sh launcher on a host with python3")


def _product(root: Path) -> Path:
    """A product checkout holding the rendered launcher and an orchestrator that names its interpreter."""
    package = root / "deploy" / "orchestrator" / "src" / "python" / "orchestrator"
    package.mkdir(parents=True)
    (package / "__main__.py").write_text('import sys\nprint("ran under", sys.executable)\n')
    (root / "deploy" / "orchestrator" / "requirements.txt").write_text("")
    launcher = root / "demo.sh"
    launcher.write_text(bootstrap._render_launcher("demo", "launch.sh.j2", "deploy/orchestrator"))
    launcher.chmod(0o755)
    return root / "deploy" / "orchestrator" / ".venv"


def _launch(root: Path, path: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "DELIVERY_ROUTE": "venv", "PYTHONDONTWRITEBYTECODE": "1"}
    if path is not None:
        env["PATH"] = path
    return subprocess.run(["bash", str(root / "demo.sh")], capture_output=True, text=True, env=env,
                          timeout=300)


def _venv_from_a_python_that_is_then_removed(venv: Path, home: Path) -> None:
    home.mkdir(parents=True)
    python = home / "python3"
    shutil.copy2(os.path.realpath(shutil.which("python3")), python)
    subprocess.run([str(python), "-m", "venv", str(venv)], check=True, timeout=300)
    python.unlink()


def _ran_under_its_own_venv(result: subprocess.CompletedProcess, venv: Path) -> bool:
    return result.returncode == 0 and f"ran under {venv / 'bin' / 'python'}" in result.stdout


@pytest.mark.parametrize("depth", [0, 12], ids=["shebang-form", "bin-sh-exec-form"])
def test_a_venv_whose_python_was_removed_is_rebuilt_and_the_command_runs(tmp_path, depth):
    # arrange: depth 12 makes the path longer than a shebang takes, so pip carries the `'''exec'` form
    root = tmp_path.joinpath(*(["a-rather-long-directory"] * depth))
    venv = _product(root)
    _venv_from_a_python_that_is_then_removed(venv, tmp_path / "pybin")
    assert os.access(venv / "bin" / "pip", os.X_OK)                     # what the old check looked at
    assert not os.access(venv / "bin" / "python", os.X_OK)              # and what it missed

    # act
    result = _launch(root)

    # assert: rebuilt, said so, and the command ran under the new venv's own python
    assert _ran_under_its_own_venv(result, venv), result.stderr
    assert f"the venv at {venv} has a pip that does not run as this venv" in result.stderr
    assert str(tmp_path / "pybin" / "python3") not in os.path.realpath(venv / "bin" / "python")


def test_a_venv_with_python_and_no_pip_is_still_rebuilt_silently(tmp_path):
    # arrange: what an interrupted first run leaves - the case the old `-x "$PIP"` gate was written for
    venv = _product(tmp_path / "product")
    subprocess.run(["python3", "-m", "venv", "--without-pip", str(venv)], check=True, timeout=300)

    # act
    result = _launch(tmp_path / "product")

    # assert: rebuilt; no "does not run as this venv" line, since there was no pip to name anything
    assert _ran_under_its_own_venv(result, venv), result.stderr
    assert "does not run as this venv" not in result.stderr
    assert os.access(venv / "bin" / "pip", os.X_OK)


def test_a_venv_copied_from_another_is_rebuilt_rather_than_run_as_the_original(tmp_path):
    # arrange: the copy's pip names the ORIGINAL's python, which works - and installs into the original
    venv = _product(tmp_path / "product")
    original = tmp_path / "original-venv"
    subprocess.run(["python3", "-m", "venv", str(original)], check=True, timeout=300)
    shutil.copytree(original, venv, symlinks=True)

    # act
    result = _launch(tmp_path / "product")

    # assert
    assert _ran_under_its_own_venv(result, venv), result.stderr
    assert f"the venv at {venv} has a pip that does not run as this venv (it names {original}" \
        in result.stderr


def test_a_healthy_venv_reached_through_a_symlink_is_left_alone(tmp_path):
    # arrange: the first run builds it; the second goes through a symlinked path, so pip's shebang and
    # the launcher's VENV differ as strings while naming the same directory
    venv = _product(tmp_path / "product")
    assert _ran_under_its_own_venv(_launch(tmp_path / "product"), venv)
    marker = venv / "untouched"
    marker.write_text("")
    (tmp_path / "link").symlink_to(tmp_path / "product")

    # act
    result = _launch(tmp_path / "link")

    # assert: nothing to do is silent and rebuilds nothing
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert marker.exists()


def test_a_rebuild_that_does_not_help_stops_and_names_the_venv_and_the_way_out(tmp_path):
    # arrange - STAGED: a python3 first on PATH that builds the venv and then points its pip elsewhere,
    # standing in for a rebuild that cannot take (the tree survived `rm -rf`, a python3 that builds bad
    # venvs). The real python3 still does the building.
    venv = _product(tmp_path / "product")
    _venv_from_a_python_that_is_then_removed(venv, tmp_path / "pybin")
    shim = tmp_path / "shim"
    shim.mkdir()
    real = shutil.which("python3")
    (shim / "python3").write_text(
        "#!/bin/sh\n"
        f'"{real}" "$@" || exit $?\n'
        'if [ "$1 $2" = "-m venv" ]; then\n'
        '    for v; do :; done\n'
        '    sed -i "1s|.*|#!/nowhere/python3|;2d" "$v/bin/pip"\n'
        "fi\n")
    (shim / "python3").chmod(0o755)

    # act
    result = _launch(tmp_path / "product", path=f"{shim}{os.pathsep}{os.environ['PATH']}")

    # assert: a refusal that names the venv, what pip names, and what to do - and the command never ran
    assert result.returncode == 1
    assert "ran under" not in result.stdout
    assert f"the venv at {venv} still has a pip that does not run as this venv (it names " \
        "/nowhere/python3) after\ndemo: rebuilding it." in result.stderr
    assert f"Remove {venv} by hand and run again" in result.stderr
    assert f"{shim / 'python3'}" in result.stderr
