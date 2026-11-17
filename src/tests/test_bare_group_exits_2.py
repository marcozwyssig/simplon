"""si#716: a group called without a subcommand, and the launcher called with no argument, print the help on
STDERR and exit 2 - the invocation is incomplete, like an unknown subcommand. `--help` and `help` stay rc 0.

Measured before, through simplon's own launcher: `build`, `test`, `release`, `support`, `support git` and
the bare launcher each printed the help on stdout and exited 0, so a runbook line that dropped its
subcommand was green and verified nothing.

The kernel forms run simplon's OWN orchestrator in a subprocess, because the no-argument case is decided in
`simplon.cli.main` on the real argv. The generated forms render a `taskgen` module and drive its Click tree.

AAA; the name states the behaviour under test.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import typer
from click.testing import CliRunner
from typer.main import get_command

import simplon
from simplon.manifest import load as manifest
from simplon.tasks import taskgen

_SRC = Path(simplon.__file__).resolve().parents[1]
_ROOT = _SRC.parents[0]
_ORCH = _ROOT / "deploy" / "orchestrator" / "src" / "python"


def _simplon(*argv: str) -> subprocess.CompletedProcess:
    """simplon's own CLI as its launcher execs it, with no TUI."""
    env = dict(os.environ, PYTHONSAFEPATH="1", PYTHONPATH=os.pathsep.join([str(_SRC), str(_ORCH)]))
    return subprocess.run([sys.executable, "-m", "orchestrator", "--no-tui", *argv], env=env, cwd=_ROOT,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("argv", [[], ["test"], ["support"], ["support", "git"]],
                         ids=["no-argument", "kernel-group", "ancestor-group", "nested-group"])
def test_an_incomplete_invocation_prints_the_help_on_stderr_and_exits_2(argv):
    # act
    ran = _simplon(*argv)

    # assert: the help, on stderr, and nothing on stdout a script could mistake for a result
    assert ran.returncode == 2, (ran.returncode, ran.stdout[-400:])
    assert "Usage:" in ran.stderr and "Show this message and exit." in ran.stderr
    assert ran.stdout == ""


@pytest.mark.parametrize("argv", [["--help"], ["help"], ["test", "--help"], ["support", "git", "--help"]])
def test_asking_for_the_help_still_answers_0_on_stdout(argv):
    # act
    ran = _simplon(*argv)

    # assert
    assert ran.returncode == 0, ran.stderr[-400:]
    assert "Usage:" in ran.stdout


_MANIFEST = """
tasks:
  seed: { impl: "simplon.test_impls:seed", help: "Seed the lab." }
  commit: { impl: "simplon.test_impls:no_context", help: "Commit." }

ci:
  lab:
    commands:
      seed: { task: "seed", with: { sites: "zh" } }
      reseed: { task: "seed", with: { sites: "be" } }
support:
  groups:
    git:
      commands:
        commit: { task: "commit" }
"""


def _generated(tmp_path):
    """A rendered `taskgen` module, registered onto a fresh root, as the Click tree."""
    path = tmp_path / "_generated_cli.py"
    path.write_text(taskgen.render(manifest.load(_MANIFEST), source="demo.yaml", product="sample"))
    spec = importlib.util.spec_from_file_location(f"_generated_cli_{abs(hash(str(path)))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = typer.Typer(add_completion=False)
    module.register(app)
    return get_command(app)


@pytest.mark.parametrize("argv", [["lab"], ["support"], ["support", "git"]],
                         ids=["generated-group", "generated-ancestor", "generated-nested"])
def test_a_generated_group_without_a_subcommand_prints_the_help_on_stderr_and_exits_2(tmp_path, argv):
    # arrange
    root = _generated(tmp_path)

    # act
    result = CliRunner(mix_stderr=False).invoke(root, argv, prog_name="sample")

    # assert
    assert result.exit_code == 2, result.stdout
    assert "Usage:" in result.stderr
    assert result.stdout == ""


def test_a_generated_groups_help_flag_still_answers_0(tmp_path):
    # arrange
    root = _generated(tmp_path)

    # act
    result = CliRunner(mix_stderr=False).invoke(root, ["lab", "--help"], prog_name="sample")

    # assert
    assert result.exit_code == 0, result.stderr
    assert "Usage:" in result.stdout
