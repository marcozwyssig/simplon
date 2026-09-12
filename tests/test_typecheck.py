"""Unit tests for the Python type gate's PURE decisions (`simplon.tasks.typecheck`).

Two things are worth pinning here, and neither of them is mypy's behaviour - that is mypy's own to test.

The first is that the gate RUNS THE INTERPRETER IT WAS GIVEN, as a module. `python -m mypy` and a bare
`mypy` on PATH are not the same command: the second resolves against whatever venv happens to be active,
which on a host with several checkouts is a coin toss, and a checker that reads a different installed set
than the product declares reports about a program nobody ships.

The second is the REFUSAL. A gate without a configuration file would run with mypy's defaults - rules
nobody wrote down, and therefore rules nobody can argue with when the gate goes red. The first argument
such a gate loses is its own existence, so the absence of the file is an error and not a fallback.

The third is that a MISSING CHECKER does not read as a finding. mypy is an optional extra
(`simplon[typecheck]`), so a product can legitimately adopt the gate and forget the install; `python -m
mypy` then exits non-zero exactly as a real type error does, and the two must not be reported alike.

No real subprocess, no mypy, no product checkout; AAA throughout.
"""
import sys
from pathlib import Path

import pytest

from simplon.tasks import typecheck


class _Result:
    """The three fields of simplon.run.Result this module reads, so the probe needs no subprocess.

    `out`/`err` arrived with si#203: the mypy run is CAPTURED now, because the caller classifies what it
    printed, which is the side of `simplon.run`'s own capture rule that inspection puts it on.
    """

    def __init__(self, rc: int, out: str = "", err: str = "") -> None:
        self.rc = rc
        self.out = out
        self.err = err


def test_the_argv_runs_mypy_as_a_module_of_the_given_interpreter() -> None:
    config = Path("/repo/mypy.ini")

    argv = typecheck.mypy_argv("/venv/bin/python", config)

    assert argv[:5] == ["/venv/bin/python", "-m", "mypy", "--config-file", "/repo/mypy.ini"]


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


# --- the tooling is an extra, so its absence is a setup error and has to say so -------------------------

def test_a_missing_checker_names_the_extra_instead_of_reporting_findings(monkeypatch) -> None:
    # arrange: the target interpreter has no mypy - `import mypy` fails, exactly as a type finding does
    monkeypatch.setattr(typecheck, "run", lambda argv, **kw: _Result(1))

    # act / assert
    with pytest.raises(ValueError) as raised:
        typecheck._require_mypy("/venv/bin/python")

    message = str(raised.value)
    assert "simplon[typecheck]" in message, message
    assert "not a type finding" in message, message


def test_a_present_checker_passes_the_probe_silently(monkeypatch) -> None:
    # arrange
    probed: list[list[str]] = []
    monkeypatch.setattr(typecheck, "run",
                        lambda argv, **kw: probed.append(argv) or _Result(0))

    # act
    typecheck._require_mypy("/venv/bin/python")

    # assert: the probe asks the NAMED interpreter, not this one - the whole point of the parameter
    assert probed == [["/venv/bin/python", "-c", "import mypy"]]


# --- si#203: a checker that could not see the installed set did not rule on the product -----------------

#: One real mypy transcript, trimmed. Both import wordings are here on purpose: `import-not-found` for a
#: module mypy found nothing for, `import-untyped` for one it found without types. Lifted from the run in
#: `typecheck.py`'s module head rather than invented, including the `note:` line - the parser has to
#: ignore it, or every missing import is counted twice.
_UNRESOLVED = (
    'src/simplon/topology.py:41: error: Cannot find implementation or library stub for module named '
    '"pydantic"  [import-not-found]\n'
    'src/simplon/topology.py:41: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html'
    '#missing-imports\n'
    'src/simplon/cli.py:29: error: Cannot find implementation or library stub for module named "typer"  '
    '[import-not-found]\n'
    'src/simplon/tasks/toolchain.py:46: error: Library stubs not installed for "yaml"  [import-untyped]\n'
    'Found 3 errors in 3 files (checked 87 source files)\n'
)
#: The same transcript's other half: an error about the product's own code.
_FINDING = ('src/simplon/verdict.py:426: error: Incompatible return value type (got "int", expected '
            '"str")  [return-value]\n')


#: What mypy 1.18.2 really prints with `pretty = True` in the product's config, captured rather than
#: written: the message WRAPS and the `[code]` bracket lands on the continuation line, for the import
#: fault and for the real finding alike. The source line and caret come with it.
_PRETTY = (
    'a.py:1: error: Cannot find implementation or library stub for module named\n'
    '"totallymissingmodule123"  [import-not-found]\n'
    '    import totallymissingmodule123\n'
    '    ^\n'
    'a.py:1: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports\n'
    'a.py:4: error: Incompatible return value type (got "int", expected "str") \n'
    '[return-value]\n'
    '        return 42\n'
    '               ^~\n'
    'Found 2 errors in 1 file (checked 1 source file)\n'
)


def test_the_argv_refuses_the_wrapping_a_products_pretty_setting_would_impose() -> None:
    """A product's `pretty = True` breaks the classification and breaks it the DANGEROUS way. Measured
    on a tree whose only fault is a missing dependency: the wrap puts `[import-not-found]` on the
    continuation line, so `classify` sees no import fault and two findings, and the gate says "mypy
    reported findings" about code that is clean. `--no-pretty` on the line overrides the key, measured
    against mypy 1.18.2.

    The transcript below is what that config really printed, so the assertion under it is the reason
    for the flag rather than a restatement of it.
    """
    assert typecheck.classify(_PRETTY) == ([], 2), (
        "if this ever stops being true the flag can go; today it is why the flag is there")
    assert "--no-pretty" in typecheck.mypy_argv("/venv/bin/python", Path("/repo/mypy.ini"))


def test_the_argv_forces_the_error_codes_the_classification_reads() -> None:
    """A product may write `hide_error_codes = True`, and then `classify` finds no import faults and
    reports a setup failure as findings - the confusion si#203 exists to end, reintroduced by a config
    key. Measured against mypy 1.18.2: the flag on the line overrides the key in the file."""
    argv = typecheck.mypy_argv("/venv/bin/python", Path("/repo/mypy.ini"))

    assert "--show-error-codes" in argv, argv


def test_import_faults_are_separated_from_findings_and_notes_are_not_counted() -> None:
    # arrange / act
    unresolved, findings = typecheck.classify(_UNRESOLVED + _FINDING)

    # assert: three import faults by MODULE name, one finding, and the note counted as neither
    assert unresolved == ["pydantic", "typer", "yaml"], unresolved
    assert findings == 1


def test_a_clean_transcript_classifies_as_nothing_at_all() -> None:
    unresolved, findings = typecheck.classify("Success: no issues found in 87 source files\n")

    assert (unresolved, findings) == ([], 0)


def test_one_module_missing_from_four_files_is_four_faults_and_one_name() -> None:
    """Duplicates are kept: `typer` was 4 of this kernel's own 20 errors, so a caller counting affected
    FILES has something to count, and one that wants the names says `set`."""
    line = ('x.py:1: error: Cannot find implementation or library stub for module named "typer"  '
            '[import-not-found]\n')

    unresolved, findings = typecheck.classify(line * 4)

    assert unresolved == ["typer"] * 4 and findings == 0


def test_a_run_that_is_ONLY_import_faults_is_refused_as_setup_not_reported_as_findings(
        monkeypatch, tmp_path) -> None:
    """THE load-bearing negative of si#203. Measured on this kernel in a container with its dependencies
    absent: rc 1, 20 errors, 20 of 20 import resolution, not one about the product - the same exit code a
    single real type error gives. Reported as findings it teaches a product that the gate is noisy."""
    # arrange
    (tmp_path / "mypy.ini").write_text("[mypy]\n")
    monkeypatch.setattr(typecheck.context, "current", lambda: _Ctx(tmp_path))
    monkeypatch.setattr(typecheck, "_require_mypy", lambda exe: None)
    monkeypatch.setattr(typecheck, "run", lambda argv, **kw: _Result(1, out=_UNRESOLVED))

    # act / assert
    with pytest.raises(ValueError) as raised:
        typecheck.check()

    message = str(raised.value)
    assert "not a type finding" in message, message
    assert "pydantic, typer, yaml" in message, message


def test_import_faults_BESIDE_findings_are_reported_and_the_findings_still_go_red(
        monkeypatch, tmp_path) -> None:
    """The third case, and the one a refusal must not swallow: the findings are real, so they are
    reported, and the silence around everything the missing modules touch is named rather than read as a
    pass. Measured: 28 errors, 27 import resolution and 1 real, on the same tree."""
    # arrange
    (tmp_path / "mypy.ini").write_text("[mypy]\n")
    warned: list[str] = []
    monkeypatch.setattr(typecheck.context, "current", lambda: _Ctx(tmp_path))
    monkeypatch.setattr(typecheck, "_require_mypy", lambda exe: None)
    monkeypatch.setattr(typecheck, "run", lambda argv, **kw: _Result(1, out=_UNRESOLVED + _FINDING))
    monkeypatch.setattr(typecheck.log, "warn", lambda msg: warned.append(msg))
    monkeypatch.setattr(typecheck.log, "die", _die)

    # act / assert
    with pytest.raises(SystemExit) as raised:
        typecheck.check()

    assert "reported findings" in str(raised.value)
    assert warned and "pydantic, typer, yaml" in warned[0], warned


def test_a_green_run_echoes_what_mypy_printed_and_says_so(monkeypatch, tmp_path, capsys) -> None:
    """Capturing is what makes the classification possible, and the cost it must not have is a silent
    gate: the output a person came for is written back out verbatim."""
    # arrange
    (tmp_path / "mypy.ini").write_text("[mypy]\n")
    monkeypatch.setattr(typecheck.context, "current", lambda: _Ctx(tmp_path))
    monkeypatch.setattr(typecheck, "_require_mypy", lambda exe: None)
    monkeypatch.setattr(typecheck, "run",
                        lambda argv, **kw: _Result(0, out="Success: no issues found in 3 source files\n"))

    # act
    rc = typecheck.check()

    # assert
    assert rc == 0
    assert "Success: no issues found in 3 source files" in capsys.readouterr().out


class _Ctx:
    """The one attribute `check` reads off a ProductContext."""

    def __init__(self, root: Path) -> None:
        self.root = root


def _die(msg: str):
    raise SystemExit(msg)
