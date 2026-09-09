"""What `simplon init` writes must be the same contract on both platforms.

One shim quietly gaining a different variable than the other strands a whole
operating system, and it only shows up on the one nobody develops on.
"""
import re
from pathlib import Path

from simplon import bootstrap

VARS = ("LAUNCH_PRODUCT", "LAUNCH_ROOT", "LAUNCH_ORCH_DIR", "LAUNCH_MODULE")

#: Where a scaffold with no `--orch-dir` puts the block (si#130), read off the constant rather than
#: retyped here.
BLOCK = bootstrap.DEFAULT_ORCH_DIR


def test_both_shims_declare_the_same_contract(tmp_path):
    bootstrap.write("democtl", tmp_path)
    sh = (tmp_path / "democtl.sh").read_text()
    cmd = (tmp_path / "democtl.cmd").read_text()
    for var in VARS:
        assert var in sh, f"{var} missing from the sh shim"
        assert var in cmd, f"{var} missing from the cmd shim"


def test_no_shim_reaches_for_a_submodule(tmp_path):
    bootstrap.write("democtl", tmp_path)
    for name in ("democtl.sh", "democtl.cmd"):
        text = (tmp_path / name).read_text()
        assert "lib/platform" not in text, f"{name} still expects the submodule"

        # It is not the variable name but the value that is the rule: nothing but the
        # product's own orchestrator path may sit on PYTHONPATH. A kernel path prepended
        # ahead of it would silently shadow the installed package - on every call, with no
        # error - so pin the whole assignment, not a substring a renamed variable would dodge.
        expected = {
            "democtl.sh": 'export PYTHONPATH="$LAUNCH_ORCH_DIR/src/python${PYTHONPATH:+:$PYTHONPATH}"',
            "democtl.cmd": 'set "PYTHONPATH=%LAUNCH_ORCH_DIR%\\src\\python;%PYTHONPATH%"',
        }
        lines = [l.strip() for l in text.splitlines() if "PYTHONPATH=" in l]
        assert lines == [expected[name]], f"{name}: {lines}"


def test_requirements_pin_the_kernel_by_version(tmp_path):
    bootstrap.write("democtl", tmp_path)
    req = (tmp_path / BLOCK / "requirements.txt").read_text()
    assert re.search(r"^simplon==\d+\.\d+\.\d+", req, re.M), req
    assert "-r " not in req, "the kernel is a dependency now, not an include"


# --- provisioning: the half of the launcher nobody watches until a runner is bare -----------------------

def test_both_shims_rebuild_a_venv_that_has_no_pip(tmp_path):
    """The rebuild condition has to be PIP, not the interpreter.

    An interrupted first run leaves a venv directory holding python and no pip. A shim that
    gates on the directory or on the interpreter calls that healthy, then fails on the very
    next line - every run, forever, with no path back except deleting the tree by hand. The
    tree also has to be removed before the rebuild, because `venv` over a half-built one is
    not a repair, and removing it drops the deps stamp, which is what forces the reinstall.
    """
    bootstrap.write("democtl", tmp_path)
    sh = (tmp_path / "democtl.sh").read_text()
    cmd = (tmp_path / "democtl.cmd").read_text()

    assert 'if [ ! -x "$PIP" ]; then' in sh, "the sh shim does not gate its rebuild on pip"
    assert 'rm -rf "$VENV"' in sh, "the sh shim rebuilds over the broken venv instead of removing it"
    assert 'if not exist "%VPIP%" (' in cmd, "the cmd shim does not gate its rebuild on pip"
    assert 'rmdir /s /q "%VENV%"' in cmd, "the cmd shim rebuilds over the broken venv instead of removing it"


def test_the_sh_shim_can_provision_a_python_that_cannot_make_venvs(tmp_path):
    """Debian and Ubuntu strip ensurepip out of the core python3 package, which is exactly what a
    fresh CI runner has. Without the probe the failure is a half-created venv and an ensurepip
    stacktrace; with it, the shim installs the interpreter-matched venv package where apt can be
    driven unprompted, and otherwise fetches pip into the venv, which needs no privileges at all.
    """
    bootstrap.write("democtl", tmp_path)
    sh = (tmp_path / "democtl.sh").read_text()

    assert "python3 -m ensurepip --version" in sh, "no ensurepip probe"
    assert "python%d.%d-venv" in sh, "the apt install is not interpreter-matched"
    assert "sudo -n true" in sh, "a non-root apt host has no non-interactive path"
    assert "get-pip.py" in sh, "no fallback for a host with neither root nor apt"
    # The diagnostic is the point of the fallback branch: a CI log has to answer why the apt
    # path was skipped without anyone getting onto the host.
    assert "uid=%s apt=%s sudo=%s" in sh, "the fallback does not say why apt was skipped"
