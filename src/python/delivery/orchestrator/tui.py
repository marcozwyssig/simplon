"""The Textual split-pane runner for a step Pipeline: LEFT a live activity log (one row per step with
its state icon), RIGHT the captured details/output of the highlighted step. This is the UX Marco asked
for. It degrades to the flat headless runner (steps.run_headless) when stdout is not a TTY (CI, piped)
or when Textual is unavailable - so CI logs stay clean and the real subprocess exit codes still drive
pass/fail. The overall exit code always comes from steps.overall_rc, never from the UI state.
"""
from __future__ import annotations

import sys

from .steps import Pipeline, StepState, overall_rc, run_headless

_ICON = {
    StepState.PENDING: "·",
    StepState.RUNNING: "▶",
    StepState.OK: "✓",
    StepState.FAILED: "✗",
    StepState.SKIPPED: "⊘",
}


def run_pipeline(pipeline: Pipeline) -> int:
    """Run the pipeline in the Textual UI when attached to a TTY (and Textual imports), else headless.
    Returns the overall exit code (0 iff every step passed)."""
    if not sys.stdout.isatty():
        return run_headless(pipeline)
    try:
        app = _StepApp(pipeline)
    except Exception:  # noqa: BLE001 - any Textual import/construct issue -> safe fallback
        return run_headless(pipeline)
    app.run()
    return overall_rc(pipeline)


# Textual is imported lazily inside the class module-load so that `from .tui import run_pipeline` does
# not hard-require Textual on the headless path (run_pipeline's isatty check returns before this is
# touched in CI). The import sits at module top but the headless fallback in cli.py catches ImportError.
from textual import work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Horizontal  # noqa: E402
from textual.widgets import Footer, Header, Label, ListItem, ListView, RichLog  # noqa: E402


class _StepApp(App):
    """Left: the step list with state icons. Right: the highlighted step's output."""

    CSS = """
    #steps { width: 38%; border-right: solid $primary; }
    #details { width: 1fr; padding: 0 1; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("up", "cursor_up", "Up"), ("down", "cursor_down", "Down")]

    def __init__(self, pipeline: Pipeline) -> None:
        super().__init__()
        self.pipeline = pipeline
        self.title = pipeline.name

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield ListView(
                *[ListItem(Label(self._row(i)), id=f"s{i}") for i in range(len(self.pipeline.steps))],
                id="steps",
            )
            yield RichLog(id="details", wrap=True, highlight=False, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._run_steps()

    def _row(self, i: int) -> str:
        step = self.pipeline.steps[i]
        return f"{_ICON[step.state]} {step.command or step.label}"

    def _refresh_row(self, i: int) -> None:
        item = self.query_one(f"#s{i}", ListItem)
        item.query_one(Label).update(self._row(i))

    def _show_details(self, i: int) -> None:
        rlog = self.query_one("#details", RichLog)
        rlog.clear()
        step = self.pipeline.steps[i]
        rlog.write(f"$ {step.command or step.label}\n")
        if step.output:
            rlog.write(step.output.rstrip("\n"))
        elif step.state == StepState.RUNNING:
            rlog.write("(running…)")
        elif step.state == StepState.PENDING:
            rlog.write("(pending)")

    def _begin_details(self, i: int) -> None:
        """When a step STARTS and is the highlighted one, clear the pane and write its header so the
        streamed lines append below it live."""
        if self.query_one("#steps", ListView).index == i:
            rlog = self.query_one("#details", RichLog)
            rlog.clear()
            step = self.pipeline.steps[i]
            rlog.write(f"$ {step.command or step.label}\n")

    def _on_line(self, i: int, line: str) -> None:
        """A streamed output line: append it live only if its step is the highlighted one."""
        if self.query_one("#steps", ListView).index == i:
            self.query_one("#details", RichLog).write(line)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None and event.item.id:
            self._show_details(int(event.item.id[1:]))

    @work(thread=True)
    def _run_steps(self) -> None:
        stopped = False
        for i, step in enumerate(self.pipeline.steps):
            if stopped:
                step.state = StepState.SKIPPED                      # stop_on_failure: do not run doomed steps
                self.call_from_thread(self._refresh_row, i)
                continue
            step.state = StepState.RUNNING
            self.call_from_thread(self._refresh_row, i)             # -> RUNNING shown
            self.call_from_thread(self._begin_details, i)
            # stream lines live into the details pane (only rendered when this step is highlighted)
            outcome = step.run(lambda line, i=i: self.call_from_thread(self._on_line, i, line))
            self.call_from_thread(self._refresh_row, i)             # -> OK/FAILED
            self.call_from_thread(self._maybe_refresh_details, i)
            if not outcome.ok and self.pipeline.stop_on_failure:
                stopped = True
        self.call_from_thread(self._on_done)

    def _maybe_refresh_details(self, i: int) -> None:
        lv = self.query_one("#steps", ListView)
        if lv.index == i:
            self._show_details(i)

    def _on_done(self) -> None:
        rc = overall_rc(self.pipeline)
        self.sub_title = "done - all passed" if rc == 0 else "done - failures (press q)"
        # auto-focus the first failed step's details, if any
        for i, step in enumerate(self.pipeline.steps):
            if step.state == StepState.FAILED:
                self.query_one("#steps", ListView).index = i
                self._show_details(i)
                break
