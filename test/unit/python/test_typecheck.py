"""Unit tests for the Python type gate's PURE decisions (`delivery.tasks.typecheck`).

Two things are worth pinning here, and neither of them is mypy's behaviour - that is mypy's own to test.

The first is that the gate RUNS THE INTERPRETER IT WAS GIVEN, as a module. `python -m mypy` and a bare
`mypy` on PATH are not the same command: the second resolves against whatever venv happens to be active,
which on a host with several checkouts is a coin toss, and a checker that reads a different installed set
than the product declares reports about a program nobody ships.

The second is the REFUSAL. A gate without a configuration file would run with mypy's defaults - rules
nobody wrote down, and therefore rules nobody can argue with when the gate goes red. The first argument
such a gate loses is its own existence, so the absence of the file is an error and not a fallback.

No subprocess, no mypy, no product checkout; AAA throughout.
"""
import sys
from pathlib import Path

import pytest

from delivery.tasks import typecheck


def test_the_argv_runs_mypy_as_a_module_of_the_given_interpreter() -> None:
    config = Path("/repo/mypy.ini")

    argv = typecheck.mypy_argv("/venv/bin/python", config)

    assert argv == ["/venv/bin/python", "-m", "mypy", "--config-file", "/repo/mypy.ini"]


def test_the_argv_names_no_source_root_because_the_config_owns_that() -> None:
    # Which trees are covered is the product's stated position, and it is stated in ONE place. An argv
    # that also named roots would be a second answer to the same question.
    argv = typecheck.mypy_argv("/venv/bin/python", Path("/repo/mypy.ini"))

    assert not [token for token in argv if token.endswith("/src") or token.startswith("src")]


def test_the_default_configuration_is_mypys_own_name(tmp_path: Path) -> None:
    (tmp_path / "mypy.ini").write_text("[mypy]\n")

    resolved = typecheck._config_path(tmp_path, typecheck.DEFAULT_CONFIG)

    assert resolved == tmp_path / "mypy.ini"


def test_a_product_may_keep_its_configuration_under_another_name(tmp_path: Path) -> None:
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "types.ini").write_text("[mypy]\n")

    resolved = typecheck._config_path(tmp_path, "build/types.ini")

    assert resolved == tmp_path / "build" / "types.ini"


def test_a_missing_configuration_is_refused_rather_than_defaulted(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as raised:
        typecheck._config_path(tmp_path, typecheck.DEFAULT_CONFIG)

    assert "mypy.ini" in str(raised.value)


def test_an_empty_config_argument_falls_back_to_the_default_name(tmp_path: Path) -> None:
    # `with: {}` and an unpinned parameter both arrive as an empty string; that is the default case,
    # not a product asking for a file called "".
    (tmp_path / "mypy.ini").write_text("[mypy]\n")

    resolved = typecheck._config_path(tmp_path, "")

    assert resolved == tmp_path / "mypy.ini"


def test_without_a_named_interpreter_the_gate_uses_the_one_the_cli_runs_in(tmp_path: Path) -> None:
    # The default case: a product whose Python IS the host venv names nothing.
    chosen = typecheck._interpreter(tmp_path, "")

    assert chosen == sys.executable


def test_a_product_may_name_a_blocks_own_interpreter(tmp_path: Path) -> None:
    # The uv-project case: the installed set lives in the block, not on the host.
    venv = tmp_path / "src" / "backend" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/sh\n")

    chosen = typecheck._interpreter(tmp_path, "src/backend/.venv/bin/python")

    assert chosen == str(venv / "python")


def test_a_named_interpreter_that_is_absent_is_refused_not_replaced(tmp_path: Path) -> None:
    # THE load-bearing negative. Falling back to the host venv would type a different installed set
    # than the product ships and still report success - the one outcome a gate must never produce.
    with pytest.raises(ValueError) as raised:
        typecheck._interpreter(tmp_path, "src/backend/.venv/bin/python")

    assert "no interpreter at" in str(raised.value)
    assert sys.executable not in str(raised.value)
