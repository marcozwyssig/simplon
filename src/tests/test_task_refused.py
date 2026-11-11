"""si#544: a task body's refusal reaches the terminal as its message alone, rc 1; a bug keeps its traceback.

Measured before: `build homebrew-formula` with no `--source` printed 112 lines, rc 1, with every local of
every frame (the parameter values included), and the diagnosis in the last two. Run here through a real
scaffolded product, in a subprocess, because Typer installs its own excepthook when the app is called and
only a real call shows what wins.

AAA; the name states the behaviour under test.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import simplon
from simplon.cli import bootstrap
from simplon.manifest.context import TaskRefused

PKG = bootstrap.pkg_dir_for(bootstrap.DEFAULT_ORCH_DIR)
SAID = "the refusal is the whole diagnosis - bind `source` to go on"


@pytest.fixture
def product(tmp_path):
    """A scaffolded product whose `build` refuses and whose `check` has a bug that raises ValueError."""
    bootstrap.write("fooctl", tmp_path)
    cli = tmp_path / PKG / "cli.py"
    text = cli.read_text()
    build = '    log.info("fooctl: build (placeholder) - wire me up in ' + PKG + '/cli.py")\n'
    check = '    log.info("fooctl: check (placeholder) - wire me up in ' + PKG + '/cli.py")\n'
    assert build in text and check in text
    text = text.replace(build, "    from simplon.manifest.context import TaskRefused\n"
                               f"    secret = 'hun' + 'ter2'\n    raise TaskRefused({SAID!r})\n")
    text = text.replace(check, "    secret = 'hun' + 'ter2'\n    int('x')\n")
    cli.write_text(text)
    return tmp_path


def _run(root: Path, *argv: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONSAFEPATH="1", COLUMNS="100",
               PYTHONPATH=os.pathsep.join([str(Path(simplon.__file__).resolve().parents[1]),
                                           str(root / bootstrap.DEFAULT_ORCH_DIR / "src" / "python")]))
    return subprocess.run([sys.executable, "-m", "orchestrator", *argv], env=env, capture_output=True,
                          text=True, cwd=root, timeout=120)


def test_a_task_refusal_is_its_message_alone_with_rc_1(product):
    # act
    ran = _run(product, "build")

    # assert
    assert ran.returncode == 1
    assert ran.stderr.strip() == SAID
    assert "Traceback" not in ran.stderr and "hunter2" not in ran.stderr + ran.stdout


def test_a_bug_that_raises_valueerror_keeps_its_traceback_without_the_locals(product):
    # act
    ran = _run(product, "test", "check")

    # assert: the traceback is there, the bug's line with it; the locals (a parameter's value) are not
    assert ran.returncode == 1
    assert "Traceback" in ran.stderr and "int('x')" in ran.stderr
    assert "invalid literal for int()" in ran.stderr
    assert "hunter2" not in ran.stderr + ran.stdout


def test_a_task_refusal_is_still_a_valueerror():
    # assert: every caller and test that catches a body's ValueError keeps catching it
    assert issubclass(TaskRefused, ValueError)
