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
        # PLATFORM_SRC was the old shim's kernel-source variable: a hardcoded second
        # directory joined onto PYTHONPATH ahead of the product's own orchestrator path.
        # A plain "PYTHONPATH" absence check is unsatisfiable here - every shim that sets
        # PYTHONPATH at all (correctly, to just its own orchestrator/src/python) contains
        # that literal substring as the assignment target.
        assert "PLATFORM_SRC" not in text, f"{name} still prepends a kernel source path"


def test_requirements_pin_the_kernel_by_version(tmp_path):
    bootstrap.write("democtl", tmp_path)
    req = (tmp_path / "orchestrator" / "requirements.txt").read_text()
    assert re.search(r"^simplon==\d+\.\d+\.\d+", req, re.M), req
    assert "-r " not in req, "the kernel is a dependency now, not an include"
