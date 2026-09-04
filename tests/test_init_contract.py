"""What `simplon init` writes must be the same contract on both platforms.

One shim quietly gaining a different variable than the other strands a whole
operating system, and it only shows up on the one nobody develops on.
"""
import re
from pathlib import Path

from simplon import bootstrap

VARS = ("LAUNCH_PRODUCT", "LAUNCH_ROOT", "LAUNCH_ORCH_DIR", "LAUNCH_MODULE")


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
    req = (tmp_path / "orchestrator" / "requirements.txt").read_text()
    assert re.search(r"^simplon==\d+\.\d+\.\d+", req, re.M), req
    assert "-r " not in req, "the kernel is a dependency now, not an include"
