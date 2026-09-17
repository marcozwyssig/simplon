"""Every step's output on disk, because a TUI is not a place text can be copied out of.

Textual takes the mouse while it runs, so the terminal's own selection stops working and the output a
step produced is visible and unreachable at the same time. `> file` sidesteps the TUI entirely, which
is a workaround for someone who already knows it. A file written every time is the answer for everyone
else.
"""
import pytest

from simplon import context, steplog
from simplon.context import ProductContext


@pytest.fixture(autouse=True)
def _product_context(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_current",
                        ProductContext("cleon", tmp_path, tmp_path / "cleon.yaml"))


def test_a_dotted_command_becomes_the_file_name():
    assert steplog.log_name("build.compile") == "build.compile.log"


def test_an_argv_command_is_reduced_to_something_a_filesystem_accepts():
    """A step's identity falls back to its shlex-joined argv, which carries slashes, spaces and dots -
    `/venv/bin/python -u -m orchestrator build` must not become a path four directories deep."""
    assert steplog.log_name("/venv/bin/python -u -m orchestrator build") == \
        "venv-bin-python--u--m-orchestrator-build.log"


def test_a_nameless_step_still_gets_a_file():
    assert steplog.log_name("") == "step.log"


def test_the_output_lands_under_the_products_build_directory(tmp_path):
    written = steplog.write("build.compile", "compiling 34 plugins\nBUILD SUCCESSFUL")

    assert written == tmp_path / "build" / "logs" / "build.compile.log"
    assert written.read_text(encoding="utf-8") == "compiling 34 plugins\nBUILD SUCCESSFUL\n"


def test_a_second_run_replaces_the_first(tmp_path):
    """A log that appends is a log nobody can read: the interesting run is the last one, and a file
    holding four of them makes finding it the reader's job."""
    steplog.write("build.compile", "old")

    written = steplog.write("build.compile", "new")

    assert written.read_text(encoding="utf-8") == "new\n"


def test_no_registered_product_is_not_a_crash(monkeypatch):
    """The kernel is imported in places that never register a product - a unit test, a scaffolder run.
    Writing a log is a courtesy, and a courtesy that raises is a defect."""
    monkeypatch.setattr(context, "_current", None)

    assert steplog.write("build.compile", "text") is None


# --- the wiring: a streaming step leaves its output behind -------------------------------------------

def test_a_streaming_step_writes_its_output_where_it_can_be_read(tmp_path, monkeypatch):
    """The point of the whole module. `build.compile` scrolls 400 lines past a pane nobody can select
    from; afterwards there is a file."""
    from simplon.orchestrator import steps
    monkeypatch.setattr(steps, "run_stream",
                        lambda argv, on_line: (on_line("compiling"), on_line("BUILD SUCCESSFUL"), 0)[2])

    outcome = steps.argv_step("compile", ["ant", "compile"], command="build.compile").stream(lambda _: None)

    assert outcome.rc == 0
    assert (tmp_path / "build" / "logs" / "build.compile.log").read_text(encoding="utf-8") == \
        "compiling\nBUILD SUCCESSFUL\n"


def test_a_failed_step_writes_its_output_too(tmp_path, monkeypatch):
    """The failing run is the one somebody wants to read - writing only on success would hand back the
    log for every run except the interesting one."""
    from simplon.orchestrator import steps
    monkeypatch.setattr(steps, "run_stream",
                        lambda argv, on_line: (on_line("The command line is too long."), 1)[1])

    steps.argv_step("compile", ["ant", "compile"], command="build.compile").stream(lambda _: None)

    assert "too long" in (tmp_path / "build" / "logs" / "build.compile.log").read_text(encoding="utf-8")
