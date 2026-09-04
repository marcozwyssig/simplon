"""Smoke tests for the product-agnostic launcher launch.sh (netctl#592 Train C).

launch.sh runs BEFORE any python package exists, so it is bash, not python; here we drive it via
subprocess. The tests are hermetic: a fake `python3` on PATH answers the ensurepip probe (so the host
is never touched) and a pre-seeded healthy venv short-circuits the bootstrap, letting us assert the
exec contract (`python -u -m <module> "$@"`) and the required-parameter guards. AAA throughout.
"""
import os
import subprocess
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parents[3] / "src" / "sh" / "launch.sh"


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _fake_python3_bin(tmp_path: Path) -> Path:
    """A `python3` that answers `-m ensurepip --version` ok, so the probe never hits the real host."""
    bindir = tmp_path / "fakebin"
    _exe(bindir / "python3", '#!/bin/sh\nexit 0\n')
    return bindir


def _healthy_venv(orch: Path) -> Path:
    """A venv whose bin/pip is executable (short-circuits the build) and whose bin/python echoes its
    argv, so the test can read back exactly how the module was exec'd. A .deps-stamp newer than
    requirements.txt skips the pip reinstall."""
    venv = orch / ".venv"
    _exe(venv / "bin" / "pip", "#!/bin/sh\nexit 0\n")
    _exe(venv / "bin" / "python", '#!/bin/sh\necho "PYARGS:$*"\n')
    (orch / "requirements.txt").write_text("")
    os.utime(orch / "requirements.txt", (1, 1))  # ancient, so the stamp below always wins
    (venv / ".deps-stamp").write_text("")
    return venv


def _env(tmp_path, orch, **overrides):
    env = {
        **os.environ,
        "PATH": f"{_fake_python3_bin(tmp_path)}:{os.environ['PATH']}",
        "LAUNCH_PRODUCT": "testctl",
        "LAUNCH_ROOT": str(tmp_path),
        "LAUNCH_ORCH_DIR": str(orch),
        "LAUNCH_MODULE": "widget",
    }
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def test_healthy_venv_execs_module_unbuffered_and_forwards_args(tmp_path):
    # arrange: a healthy pre-seeded venv and a hermetic python3
    orch = tmp_path / "orch"
    _healthy_venv(orch)

    # act
    result = subprocess.run(
        ["bash", str(LAUNCH), "cmd", "--flag", "x"],
        capture_output=True, text=True, env=_env(tmp_path, orch))

    # assert: exec'd the venv python as `-u -m widget cmd --flag x`
    assert result.returncode == 0, result.stderr
    assert "PYARGS:-u -m widget cmd --flag x" in result.stdout


def test_missing_venv_is_built_then_module_is_exec(tmp_path):
    # arrange: no venv yet; the fake python3 materialises a working venv on `-m venv <dir>`
    orch = tmp_path / "orch"
    orch.mkdir()
    (orch / "requirements.txt").write_text("")
    venv = orch / ".venv"
    builder = tmp_path / "fakebin"
    _exe(builder / "python3", f'''#!/bin/sh
case "$*" in
  "-m ensurepip --version") exit 0 ;;
  "-m venv "*)
    d="{venv}"
    mkdir -p "$d/bin"
    printf '#!/bin/sh\\nexit 0\\n' > "$d/bin/pip"; chmod 755 "$d/bin/pip"
    printf '#!/bin/sh\\necho "PYARGS:$*"\\n' > "$d/bin/python"; chmod 755 "$d/bin/python"
    exit 0 ;;
  *) exit 0 ;;
esac
''')
    env = {**os.environ, "PATH": f"{builder}:{os.environ['PATH']}",
           "LAUNCH_PRODUCT": "testctl", "LAUNCH_ROOT": str(tmp_path),
           "LAUNCH_ORCH_DIR": str(orch), "LAUNCH_MODULE": "widget"}

    # act
    result = subprocess.run(["bash", str(LAUNCH), "go"], capture_output=True, text=True, env=env)

    # assert: the venv was built, deps stamped, and the module exec'd
    assert result.returncode == 0, result.stderr
    assert "PYARGS:-u -m widget go" in result.stdout
    assert (venv / ".deps-stamp").exists()


@pytest.mark.parametrize("missing", ["LAUNCH_PRODUCT", "LAUNCH_ROOT", "LAUNCH_ORCH_DIR", "LAUNCH_MODULE"])
def test_each_required_parameter_fails_fast(tmp_path, missing):
    # arrange: drop exactly one required parameter
    orch = tmp_path / "orch"
    _healthy_venv(orch)

    # act
    result = subprocess.run(
        ["bash", str(LAUNCH)],
        capture_output=True, text=True, env=_env(tmp_path, orch, **{missing: None}))

    # assert: non-zero exit naming the missing var (set -u / :? guard), module never runs
    assert result.returncode != 0
    assert missing in result.stderr
    assert "PYARGS" not in result.stdout
