"""Every step's output on disk, because a TUI is not a place text can be copied out of.

Textual takes the mouse while it runs, so the terminal's own selection stops working and the output a
step produced is visible and unreachable at the same time. `> file` sidesteps the TUI entirely, which
is a workaround for someone who already knows it. A file written every time is the answer for everyone
else.
"""
import pytest

from simplon import context, outputs, steplog
from simplon.context import ProductContext


@pytest.fixture(autouse=True)
def _product_context(tmp_path, monkeypatch):
    # The manifest EXISTS, the way it does in any registered product: since si#314 the log directory is
    # `<output>/logs/` and `output:` is read from it. A tree without one exercised the "cannot read the
    # manifest" path by accident, which is a case of its own below.
    (tmp_path / "cleon.yaml").write_text("name: cleon\n", encoding="utf-8")
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


def test_a_declared_output_root_moves_the_step_logs(tmp_path):
    """si#314: the logs are a KIND under the product's one output directory, so a product that publishes
    out of another root takes its run protocol with it rather than leaving it in a `build/` nothing else
    uses."""
    # arrange
    (tmp_path / "cleon.yaml").write_text("output: build-out\n", encoding="utf-8")

    # act
    written = steplog.write("build.compile", "BUILD SUCCESSFUL")

    # assert
    assert written == tmp_path / "build-out" / "logs" / "build.compile.log"


def test_an_impossible_output_root_keeps_the_log_in_the_default_place_and_says_so(tmp_path, capsys,
                                                                                   monkeypatch):
    """The record of a run must not be what a broken declaration takes away first. A step log and the
    transcript are what somebody attaches to a ticket when a run went wrong; losing them BECAUSE
    something else is already wrong is exactly backwards. So the default root - which needs no manifest
    to be known - catches it, and the fallback is stated rather than silent."""
    # arrange: a root that would be cleaned somewhere else entirely, and a fresh process's memory of
    # what it has already said
    monkeypatch.setattr(steplog, "_SAID", set())
    (tmp_path / "cleon.yaml").write_text("output: /var/tmp/x\n", encoding="utf-8")

    # act
    written = steplog.write("build.compile", "BUILD SUCCESSFUL")

    # assert
    assert written == tmp_path / "build" / "logs" / "build.compile.log"
    # `log.warn` writes to stdout in this kernel, which is where the rest of a run's narration goes
    assert "output" in capsys.readouterr().out


def test_the_fallback_is_said_once_and_not_once_per_step(tmp_path, capsys, monkeypatch):
    # arrange
    monkeypatch.setattr(steplog, "_SAID", set())
    (tmp_path / "cleon.yaml").write_text("output: /var/tmp/x\n", encoding="utf-8")

    # act: three steps of one run
    for step in ("build.compile", "build.jar", "test.unit"):
        steplog.write(step, "out")

    # assert: the same sentence three times is a way of not being read. Counted on the sentence's own
    # opening rather than on the word `output`, which the nested refusal text carries again.
    assert capsys.readouterr().out.count("step logs and the run transcript") == 1


def test_a_tree_with_no_manifest_takes_the_convention_without_a_word(tmp_path, capsys, monkeypatch):
    """A missing manifest is not a broken declaration. The kernel is registered against trees that carry
    none - a scaffolder mid-write, a unit test - and narrating that on every step is noise, not news."""
    # arrange
    monkeypatch.setattr(steplog, "_SAID", set())
    (tmp_path / "cleon.yaml").unlink()

    # act
    written = steplog.write("build.compile", "BUILD SUCCESSFUL")

    # assert
    assert written == tmp_path / "build" / "logs" / "build.compile.log"
    assert capsys.readouterr().out == ""
