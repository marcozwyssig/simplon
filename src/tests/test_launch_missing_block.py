"""A launcher that cannot find its orchestrator says so, and says where it looked (si#24).

THE DEFECT THIS IS AGAINST, measured on the launcher as it stood before this check existed:

  * the block directory gone -- `python3 -m venv` CREATES it (it makes parents), and pip then reports
    `Could not open requirements file`. The launcher manufactures the very directory it was sent to
    find, and the message that comes out is pip's opinion about a file, not the launcher's about a
    block. It also leaves a `.venv` behind in a tree that has no orchestrator in it.
  * the package sources gone -- `python: No module named orchestrator`, with no path in it at all.
    Nothing in that sentence tells anybody which of the two `orchestrator`s is missing, or from where.

Neither separates "this checkout has no orchestrator" from "the install fell over", and the launcher
holds `LAUNCH_ORCH_DIR` the whole time. That is the shape CLAUDE.md calls the recurring defect, and the
answer it prescribes: say it at the seam.

WHY IT IS DIAGNOSIS AND NOT AN EXPRESSION RULE. It forbids no manifest anything and refuses no layout a
product might want -- `--orch-dir` still accepts every relative path it accepted before. It reports a
broken checkout, with the paths it needed. So the census in CLAUDE.md ("does a real manifest violate
it?") does not apply: there is nothing here for a manifest to violate.

WHAT IS NOT EXECUTED HERE. The `.cmd` half is held by its text, because this suite runs on Linux and
cmd.exe is not available to it -- the same limit `test_launch_cmd.py` states for the line-ending policy.
The two launchers are written from one pair of templates and checked against the same three paths, so
the text is what there is to hold.
"""
import subprocess

import pytest

from simplon import bootstrap

PRODUCT = "democtl"
ORCH_DIR = "deploy/orchestrator"

#: The three paths the launcher needs, relative to the scaffold target: the block itself, the
#: requirements file it installs from, and the package directory PYTHONPATH points at. Each one absent
#: is a different way for the same thing to be untrue, and each has to arrive as its own message.
NEEDED = [
    ORCH_DIR,
    f"{ORCH_DIR}/requirements.txt",
    f"{ORCH_DIR}/src/python/orchestrator",
]


def _scaffold(tmp_path):
    bootstrap.write(PRODUCT, tmp_path, orch_dir=ORCH_DIR)
    return tmp_path / f"{PRODUCT}.sh"


def _remove(path):
    if path.is_dir():
        for child in sorted(path.rglob("*"), reverse=True):
            child.rmdir() if child.is_dir() else child.unlink()
        path.rmdir()
    else:
        path.unlink()


@pytest.mark.parametrize("missing", NEEDED)
def test_the_launcher_refuses_and_names_the_path_it_could_not_find(tmp_path, missing):
    # arrange: a real scaffold, then one of the three things the launcher needs taken away
    shim = _scaffold(tmp_path)
    gone = tmp_path / missing
    _remove(gone)

    # act
    res = subprocess.run([str(shim), "help"], cwd=tmp_path, capture_output=True, text=True)

    # assert: loud (a non-zero rc), and specific enough to act on without opening the file
    assert res.returncode == 1, res.stdout + res.stderr
    assert str(tmp_path / ORCH_DIR) in res.stderr, res.stderr
    assert str(gone) in res.stderr, res.stderr
    assert "LAUNCH_ORCH_DIR" in res.stderr


@pytest.mark.parametrize("missing", NEEDED)
def test_the_launcher_provisions_nothing_when_the_block_is_not_there(tmp_path, missing):
    """The half that a non-zero exit code does not cover, and the reason the check is where it is.

    Without it the venv is built first and the complaint comes afterwards, so a tree with no
    orchestrator in it ends up with a `.venv` that was created to install something that is not there.
    A run that fails must leave the tree as it found it, or the next reader cannot tell which of the
    two directories is the mistake.
    """
    # arrange
    shim = _scaffold(tmp_path)
    _remove(tmp_path / missing)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    # act
    subprocess.run([str(shim), "help"], cwd=tmp_path, capture_output=True, text=True)

    # assert
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before, "the launcher wrote into a tree it had already decided was broken"


def test_the_check_runs_before_the_venv_is_touched():
    # The ordering is the property, and it is readable in the rendered file: the guard has to stand
    # ahead of the `rm -rf "$VENV"` that rebuilds a broken venv, or it can only report damage it did.
    sh = bootstrap.render(PRODUCT, orch_dir=ORCH_DIR)[f"{PRODUCT}.sh"]

    assert sh.index("no orchestrator here") < sh.index('rm -rf "$VENV"')


def test_the_windows_launcher_checks_the_same_three_paths():
    # Held by text: see the module docstring. What must not drift is WHICH paths are checked - a .cmd
    # that guarded two of the three would be the half-parametrised shim si#4 warns about, wearing a
    # diagnostic.
    cmd = bootstrap.render(PRODUCT, orch_dir=ORCH_DIR)[f"{PRODUCT}.cmd"]

    assert 'if not exist "%LAUNCH_ORCH_DIR%\\" set "ORCH_MISSING=%LAUNCH_ORCH_DIR%"' in cmd
    assert 'if not exist "%REQ%" set "ORCH_MISSING=%REQ%"' in cmd
    assert '%LAUNCH_ORCH_DIR%\\src\\python\\%LAUNCH_MODULE%\\" set "ORCH_MISSING=' in cmd
    assert "no orchestrator here" in cmd
    assert "exit /b 1" in cmd


def test_the_guard_does_not_move_with_the_block_dir():
    # The check derives from LAUNCH_ORCH_DIR rather than spelling a path, so it is the same text at
    # every layout - which is also why it costs the default nothing.
    default = bootstrap.render(PRODUCT)[f"{PRODUCT}.sh"]
    relocated = bootstrap.render(PRODUCT, orch_dir="deploy/provision/orchestrator")[f"{PRODUCT}.sh"]
    guard = '''for _needed in "$LAUNCH_ORCH_DIR" "$REQ" "$LAUNCH_ORCH_DIR/src/python/$LAUNCH_MODULE"; do'''

    assert guard in default
    assert guard in relocated
