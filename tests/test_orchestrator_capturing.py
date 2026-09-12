"""`steps.capturing` (si#174): a body that reports by PRINTING, turned into a step.

The kernel took an in-process `stream` callable and had nothing that made a print into the step's emit -
measured on the installed package: no `redirect_stdout` and no `StringIO` anywhere in it. What made this
worth doing once in the kernel rather than once per product is that the naive version is wrong in three
ways a first run does not show: it recurses on the headless emit (which PRINTS), it cross-wires two
steps of one fan, and it leaves `sys.stdout` pointing at a dead buffer afterwards.

Every test below is one of those, plus the three ways a body reports and the half-line rule.
"""
from __future__ import annotations

import sys
import threading
import time

import pytest

from simplon import context, steplog
from simplon.context import ProductContext
from simplon.orchestrator.steps import CRASH_RC, StepState, capturing


@pytest.fixture(autouse=True)
def _product_context(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_current",
                        ProductContext("probe", tmp_path, tmp_path / "probe.yaml"))


class _Recorder:
    """A stand-in for `sys.stdout` that records instead of printing. The tests that need to know what
    ESCAPED the capture install one; the ones about `isatty` subclass it to claim a terminal."""

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def _run(step) -> list[str]:
    """Run a capturing step, collecting what reached its emit."""
    seen: list[str] = []
    step.run(seen.append)
    return seen


# --- what a printing body produces --------------------------------------------------------------------


def test_what_the_body_prints_becomes_the_steps_lines_and_its_output():
    # Arrange
    def work() -> None:
        print("checked the registry")
        print("checked the daemon")

    step = capturing("probe", work, command="probe.checks")
    # Act
    seen = _run(step)
    # Assert: live through emit, accumulated in the Outcome, and green
    assert seen == ["checked the registry", "checked the daemon"]
    assert step.output == "checked the registry\nchecked the daemon"
    assert step.state == StepState.OK and step.rc == 0


def test_the_pane_can_read_the_lines_while_the_step_is_still_running():
    """`Step.live` is the SAME list the writer appends to, handed over by reference (si#144) - not a copy
    beside it, which goes stale the moment the body prints again."""
    # Arrange
    step = capturing("probe", lambda: print("one"), command="probe.one")
    # Act
    step.run()
    # Assert
    assert step.live == ["one"]
    assert step.shown_output == "one"


def test_the_whole_text_is_written_to_a_step_log(tmp_path):
    # Arrange
    step = capturing("probe", lambda: print("the reason"), command="probe.reason")
    # Act
    step.run()
    # Assert
    path = steplog.existing_log("probe.reason")
    assert path is not None and path.read_text().strip() == "the reason"


# --- the hang that only shows on the path a developer does not take first ------------------------------


def test_an_emit_that_prints_does_not_feed_itself_back_into_the_capture():
    """THE FAULT si#174 EXISTS TO PREVENT. The headless runner's emit PRINTS, so delivering a line with
    the redirect still in force feeds that print straight back into the writer that produced it:
    `maximum recursion depth exceeded` on the first line of the first step. The TUI's emit appends to a
    widget and does not print, so an interactive run is fine and the fault waits for the first piped or
    CI run.

    The assertion is that the emitted line reaches the REAL stdout exactly once, and that the step's own
    line list holds one entry rather than a thousand."""
    # Arrange: an emit that prints, exactly as `_HeadlessOutput._line` does
    printed: list[str] = []
    real = sys.stdout

    class Recorder(_Recorder):
        def write(self, text: str) -> int:
            printed.append(text)
            return len(text)

    def emit(line: str) -> None:
        print(f"  {line}", flush=True)

    step = capturing("probe", lambda: print("one line from the body"), command="probe.echo")
    # Act
    sys.stdout = Recorder()      # type: ignore[assignment]
    try:
        step.run(emit)
    finally:
        sys.stdout = real
    # Assert
    assert "".join(printed).strip() == "one line from the body"
    assert step.live == ["one line from the body"]


# --- restoration, on every path ------------------------------------------------------------------------


def test_stdout_is_restored_after_a_body_that_raises():
    # Arrange
    def work() -> None:
        print("got this far")
        raise RuntimeError("and no further")

    before = sys.stdout
    step = capturing("probe", work, command="probe.raises")
    # Act
    step.run()
    # Assert
    assert sys.stdout is before


def test_a_nested_capture_puts_the_outer_one_back_rather_than_the_real_stdout():
    """`contextlib.redirect_stdout` is re-entrant and a hand-rolled swap is not, which is why the inner
    capture's exit must restore the OUTER writer - not the stream the outer one replaced."""
    # Arrange
    inner_step = capturing("inner", lambda: print("from the inner body"), command="probe.inner")
    inner_seen: list[str] = []

    def outer() -> None:
        print("outer before")
        inner_step.run(inner_seen.append)
        print("outer after")

    outer_step = capturing("outer", outer, command="probe.outer")
    before = sys.stdout
    # Act
    outer_seen = _run(outer_step)
    # Assert: each body's lines stayed in its own step, and stdout came all the way back
    assert inner_seen == ["from the inner body"]
    assert outer_seen == ["outer before", "outer after"]
    assert sys.stdout is before


# --- si#147 made stdout a shared resource ---------------------------------------------------------------


def test_two_capturing_steps_running_side_by_side_do_not_cross_wire():
    """MEASURED FIRST WITH A PER-STEP `contextlib.redirect_stdout`, which is the obvious implementation:
    two threads each redirecting round three prints, 50 ms apart, produced

        branch A captured ['A line 0']
        branch B captured ['B line 0', 'A line 1', 'B line 1', 'A line 2', 'B line 2']
        sys.stdout afterwards: branch A's writer, which is dead

    - five of six lines in the wrong step, and the process never got its stdout back, because
    `redirect_stdout` restores what IT saved on entry. One router with a thread-local target is what
    makes this hold."""
    # Arrange: a BARRIER rather than a sleep, so all three are provably inside their capture at the same
    # time (code review). A sleep only makes the interleaving likely: on a fast or differently scheduled
    # runner the three could serialise, and the test would pass without ever exercising the race it is
    # named for - power quietly lost rather than a false failure.
    seen: dict[str, list[str]] = {name: [] for name in ("A", "B", "C")}
    inside = threading.Barrier(len(seen), timeout=5)

    def body(name: str):
        def work() -> None:
            inside.wait()          # every branch is now redirecting at once
            for i in range(3):
                print(f"{name} line {i}")
                time.sleep(0.02)
        return work

    steps = {name: capturing(name, body(name), command=f"probe.{name}") for name in seen}
    before = sys.stdout

    def drive(name: str) -> None:
        steps[name].run(seen[name].append)

    # Act
    threads = [threading.Thread(target=drive, args=(name,)) for name in seen]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Assert
    for name in seen:
        assert seen[name] == [f"{name} line {i}" for i in range(3)]
    assert sys.stdout is before


def test_a_thread_that_is_not_capturing_keeps_printing_to_the_real_stdout():
    """The other half of the same property: a per-step redirect swallows every other thread's output for
    its duration - measured, an unrelated thread's line landed inside whichever step happened to be
    capturing. Here it must reach the stream the router replaced."""
    # Arrange
    escaped: list[str] = []

    class Recorder(_Recorder):
        def write(self, text: str) -> int:
            escaped.append(text)
            return len(text)

    done = threading.Event()

    def other() -> None:
        print("a completely unrelated thread")
        done.set()

    def work() -> None:
        thread = threading.Thread(target=other)
        thread.start()
        done.wait(timeout=2)
        thread.join()
        print("the body's own line")

    real = sys.stdout
    step = capturing("probe", work, command="probe.solo")
    # Act
    sys.stdout = Recorder()      # type: ignore[assignment]
    try:
        seen = _run(step)
    finally:
        sys.stdout = real
    # Assert
    assert seen == ["the body's own line"]
    assert "a completely unrelated thread" in "".join(escaped)


# --- the three ways a body reports ----------------------------------------------------------------------


def test_a_body_that_returns_is_a_passing_step():
    # Arrange / Act
    step = capturing("probe", lambda: None, command="probe.quiet")
    step.run()
    # Assert
    assert step.rc == 0 and step.state == StepState.OK


def test_sys_exit_with_a_message_is_rc_one_and_the_message_is_a_line_of_the_step():
    """CPython's own rule, and the message is the whole reason the step is red - dropping it would leave
    a red step that says nothing."""
    # Arrange
    def work() -> None:
        print("checked three things")
        sys.exit("no docker found, so there is nothing to build")

    step = capturing("probe", work, command="probe.exit")
    # Act
    seen = _run(step)
    # Assert
    assert step.rc == 1 and step.state == StepState.FAILED
    assert seen == ["checked three things", "no docker found, so there is nothing to build"]


@pytest.mark.parametrize("code, expected", [(None, 0), (0, 0), (3, 3)])
def test_sys_exit_with_a_code_is_that_code(code, expected):
    # Arrange / Act
    step = capturing("probe", lambda: sys.exit(code), command="probe.code")
    step.run()
    # Assert
    assert step.rc == expected


def test_a_fault_in_the_closing_flush_does_not_displace_the_bodys_own_exception():
    """The half-line flush runs while the body's exception is already travelling, so it is a courtesy
    that must not become the news. If it raised, `Step.crash` would end on the FLUSH's traceback -
    `__context__` would still carry the body's, but `failure_report` shows a step's last ten lines, so
    the traceback a reader actually needs would be pushed out of that window."""
    # Arrange: an emit that blows up on the half line, and a body that has already blown up
    def emit(line: str) -> None:
        if not line.endswith("."):
            raise RuntimeError("the repaint fell over on the half line")

    def work() -> None:
        print("a finished line.")
        print("a half line with no newline", end="")
        raise ValueError("the body's own fault")

    step = capturing("probe", work, command="probe.flush")
    # Act
    step.run(emit)
    # Assert: the body's exception is the recorded one, and the flush fault is gone rather than on top
    assert "ValueError: the body's own fault" in step.crash
    assert "the repaint fell over" not in step.crash


def test_a_body_that_raises_becomes_a_failed_step_and_not_an_escaping_exception():
    """One item blowing up must not take the rest of the pipeline down - that is the opposite of what
    `stop_on_failure: false` promises. si#182 owns the verdict; what this asserts is that the exception
    reaches it instead of the caller, and that the lines printed BEFORE the raise survive beside the
    traceback."""
    # Arrange
    def work() -> None:
        print("processing leaf-01")
        raise ValueError("leaf-02 did not answer")

    step = capturing("probe", work, command="probe.blows-up")
    # Act
    seen = _run(step)
    # Assert
    assert step.state == StepState.FAILED and step.rc == CRASH_RC
    assert seen == ["processing leaf-01"]
    assert "processing leaf-01" in step.output
    assert "ValueError: leaf-02 did not answer" in step.crash


# --- half lines (si#144's class, in-process) --------------------------------------------------------------


def test_a_half_line_is_handed_over_when_the_body_flushes():
    # Arrange
    def work() -> None:
        print("progress: ", end="")
        sys.stdout.flush()
        print("done")

    step = capturing("probe", work, command="probe.partial")
    # Act
    seen = _run(step)
    # Assert
    assert seen == ["progress: ", "done"]


def test_a_half_line_the_body_never_finished_is_handed_over_at_the_end_of_the_step():
    """Not lost, which is the half si#144 measured for subprocesses. The bound is the STEP rather than an
    idle timer: here the only thread that could hand the bytes over is the body's own."""
    # Arrange
    step = capturing("probe", lambda: print("no newline here", end=""), command="probe.tail")
    # Act
    seen = _run(step)
    # Assert
    assert seen == ["no newline here"]


def test_a_line_written_in_pieces_arrives_as_one_line():
    """Rich writes one visual line in several calls, and a pane of fragments is not a pane of lines."""
    # Arrange
    def work() -> None:
        sys.stdout.write("one ")
        sys.stdout.write("line ")
        sys.stdout.write("in three writes\n")

    step = capturing("probe", work, command="probe.pieces")
    # Act
    seen = _run(step)
    # Assert
    assert seen == ["one line in three writes"]


def test_a_carriage_return_ends_a_segment_the_way_it_does_for_a_subprocess():
    """The same `simplon.run.LINE_BREAK` both readers use: a bare `\\r` is a repaint, and what came before
    it is finished text a reader can see."""
    # Arrange
    step = capturing("probe", lambda: sys.stdout.write("50%\r100%\r"), command="probe.bar")
    # Act
    seen = _run(step)
    # Assert
    assert seen == ["50%", "100%"]


# --- Rich, measured rather than assumed -------------------------------------------------------------------


def test_a_rich_console_built_before_the_step_still_writes_into_it():
    """`Console.file` is a PROPERTY that reads `sys.stdout` at every access when no `file=` was passed
    (measured on rich 15.0.0), so a console built at a product's module import - long before any of this
    exists - is reached. This is the claim the ticket said to check rather than assume."""
    # Arrange
    console = pytest.importorskip("rich.console").Console()
    step = capturing("probe", lambda: console.print("[bold]a Rich line[/bold]"), command="probe.rich")
    # Act
    seen = _run(step)
    # Assert: it arrived, and it arrived as PLAIN text - `isatty` is False, so no ANSI reaches the log
    assert seen == ["a Rich line"]


def test_a_captured_thread_is_told_it_is_not_a_terminal():
    """Why the line above is plain: `rich.Console` and `simplon.fetch` both ask, and a writer that
    claimed to be a terminal would put ANSI and cursor moves into a step log and a run transcript.

    THE TERMINAL HAS TO BE REAL FOR THIS TO BE A CHECK. Written against pytest's own captured stdout the
    assertion passed with `isatty` deleted outright - pytest's replacement already answers False, so
    every implementation looked correct. It is driven under a stream that CLAIMS to be a terminal, and
    it asserts both halves: the captured thread is told no, the uncaptured one is told yes."""
    # Arrange: a stdout that says it is a terminal
    class Terminal(_Recorder):
        def isatty(self) -> bool:
            return True

    answers: list[bool] = []
    step = capturing("probe", lambda: answers.append(sys.stdout.isatty()), command="probe.tty")
    real = sys.stdout
    # Act
    sys.stdout = Terminal()      # type: ignore[assignment]
    try:
        step.run()
        uncaptured = sys.stdout.isatty()
    finally:
        sys.stdout = real
    # Assert
    assert answers == [False]
    assert uncaptured is True    # nothing is capturing this thread, so the terminal is still a terminal


def test_a_captured_rich_console_puts_no_escape_sequences_into_the_record():
    """`isatty` answering False is NOT enough, which is what driving this found (rich 15.0.0).
    `Console.is_terminal` does follow the capture, but `Console._color_system` is detected once in
    `__init__` and rich renders a style whenever that is truthy - so a console a product built at module
    import, under a real terminal, wrote `\x1b[1;31ma warning\x1b[0m` straight into the step.

    Driven under a stdout that CLAIMS to be a terminal, because that is the only condition under which
    rich emits colour at all: against pytest's own captured stdout this test was green before the fix,
    which is the check-that-cannot-fail this repository keeps finding."""
    # Arrange
    console_module = pytest.importorskip("rich.console")

    class Terminal(_Recorder):
        def isatty(self) -> bool:
            return True

    real = sys.stdout
    sys.stdout = Terminal()      # type: ignore[assignment]
    try:
        console = console_module.Console()
        step = capturing("probe", lambda: console.print("[bold red]a warning[/bold red]"),
                         command="probe.colour")
        # Act
        seen = _run(step)
    finally:
        sys.stdout = real
    # Assert
    assert seen == ["a warning"]
    assert not any("\x1b" in line for line in seen)
    assert step.output == "a warning"      # and the step log and the transcript get the same text
