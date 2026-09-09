"""The Textual split-pane runner for a step Pipeline: LEFT the plan as a TREE (one row per command, its
state icon in front of its dotted path), RIGHT the details of the highlighted row - a leaf's live output, an
aggregate's children with their exit codes. This is the UX Marco asked for. It degrades to the flat headless
runner (steps.run_headless) when stdout is not a TTY (CI, piped) or when Textual is unavailable - so CI logs
stay clean and the real subprocess exit codes still drive pass/fail. The overall exit code always comes from
steps.overall_rc, never from the UI state.

The tree's ROWS are display only (netctl#1276): execution still walks the flat `pipeline.steps` list in
order, and an aggregate row is never run - its state is derived from the children below it (steps.Row.state).
The PLAN behind them is not purely display: a failure asks `steps.abort_after` which of the remaining steps
its subtree takes down with it (netctl#1317).
"""
from __future__ import annotations

import sys

from . import steps as steps_module
from .steps import (STATE_ICON, Emit, Pipeline, Row, Step, StepState, abort_after, build_rows,
                    failure_report, format_duration, omitted_note, overall_rc, run_headless,
                    status_line)


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
    # The TUI's screen - and with it the details pane that held the reason - is gone the moment the app
    # exits. The same block a CI log gets is therefore printed onto the terminal the operator is left
    # looking at (#49). A run with no failure prints nothing here, so a green run is not one line longer.
    for line in failure_report(pipeline):
        print(line, flush=True)
    return overall_rc(pipeline)


# Textual is imported lazily inside the class module-load so that `from .tui import run_pipeline` does
# not hard-require Textual on the headless path (run_pipeline's isatty check returns before this is
# touched in CI). The import sits at module top but the headless fallback in cli.py catches ImportError.
from textual import work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Horizontal  # noqa: E402
from textual.widgets import Footer, Header, RichLog, Static, Tree  # noqa: E402

from simplon import steplog  # noqa: E402
from textual.widgets.tree import TreeNode  # noqa: E402

#: The bar's colour, by the RUN's derived state. Three classes for five states, and the two that are
#: missing are deliberate: the bar is one line and its job is the run, so PENDING (nothing has happened)
#: and SKIPPED (a run in which nothing ran at all) leave it in the theme's ordinary foreground rather
#: than spending a colour on the absence of news. The per-ROW mapping, which does have to separate all
#: five, is `_STATE_STYLE`.
_BAR_CLASS = {StepState.RUNNING: "-running", StepState.OK: "-ok", StepState.FAILED: "-failed"}


class _StepApp(App):
    """Left: the plan tree with state icons. Right: the highlighted row's details."""

    CSS = """
    #steps { width: 38%; border-right: solid $primary; }
    #details { width: 1fr; padding: 0 1; }
    #status { height: 1; padding: 0 1; background: $panel; color: $foreground; }
    #status.-running { color: $warning; }
    #status.-ok { color: $success; }
    #status.-failed { color: $error; }
    """
    # `c` and `s` are not conveniences. A Textual app puts the terminal in raw mode and turns on mouse
    # reporting so it can handle clicks itself, which switches OFF the terminal's own selection - the
    # output is on screen and cannot be marked, copied or quoted anywhere. The way out has to come from
    # inside the app: `c` to the clipboard, `s` to a file for when the clipboard cannot be reached (an
    # SSH session whose terminal does not speak OSC 52, or a log someone wants to attach to a ticket).
    BINDINGS = [("q", "quit", "Quit"), ("up", "cursor_up", "Up"), ("down", "cursor_down", "Down"),
                ("c", "copy_details", "Copy"), ("s", "save_details", "Save")]

    def __init__(self, pipeline: Pipeline) -> None:
        super().__init__()
        self.pipeline = pipeline
        self.title = pipeline.name
        self.rows = build_rows(pipeline)
        # Per step index, the chain of rows (and their tree nodes) from the ROOT down to that step's own
        # row. A finishing step changes the state of every ancestor, and only of its ancestors, so the
        # chain is both what has to be repainted and the test for "is the highlighted row affected by this
        # step". Filled on mount, when the nodes exist.
        self._chain_nodes: dict[int, tuple[TreeNode, ...]] = {}
        self._chain_rows: dict[int, tuple[Row, ...]] = {}
        # Per SKIPPED step (by identity), why it will not run - the same `Abort.reason` the headless runner
        # prints. Without it the TTY operator sees a bare ⊘ and never learns which subtree decided, which is
        # the whole content of a subtree-scoped stop (netctl#1317). Keyed by the Step rather than its index
        # because the details pane is reached from a Row.
        self._skipped_because: dict[int, str] = {}
        # The last text written to each node, so an unchanged row is not written again. Textual's
        # `TreeNode.set_label` schedules `_refresh_node`, which marks every VISIBLE line of that node's
        # subtree dirty - for the root that is the whole pane. A 17-leaf plan repaints the root twice per
        # step, and almost all of those repaints are no-ops: the root's derived state is RUNNING from the
        # first leaf to the last. Writing only real changes takes the measured dirty-line marks of such a
        # plan from 978 to 120 and the label writes from 102 to 44, at an unchanged frame count.
        self._painted: dict[int, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Tree(self._label(self.rows), id="steps")
            yield RichLog(id="details", wrap=True, highlight=False, markup=False)
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._mount_tree()
        self._show_details(self.rows)
        self._repaint_status()
        # ONE second, and the interval exists for two readers at once: the running row's own counter and
        # the bar's. Both answer "is this compiling or is it hung", which is asked in whole seconds and
        # never in tenths, and a faster beat would repaint forty rows for a number that did not change.
        # `_painted` suppresses the rows whose text is unchanged, so a tick costs one label write per
        # running chain rather than one per row.
        self.set_interval(1.0, self._tick)
        self._run_steps()

    # ---------------------------------------------------------------- the bottom bar (si#148 item 8)

    def _tick(self) -> None:
        """One beat of the two live counters: the bar, and the label of every row that is RUNNING.

        The row counters are refreshed through `_refresh_row`, so an ancestor whose own elapsed changed is
        repainted with the leaf and a row whose text did not change is not written again."""
        for index, step in enumerate(self.pipeline.steps):
            if step.state == StepState.RUNNING:
                self._refresh_row(index)
        self._repaint_status()

    def _repaint_status(self) -> None:
        """Write the bar. The TEXT is `steps.status_line`, computed over the display tree and the clock -
        pure, plain, and asserted without a terminal; this method only places it and colours the whole line
        by the run's derived state, which is the additive half of item 7 for a widget that has no glyph of
        its own."""
        bar = self.query_one("#status", Static)
        bar.update(status_line(self.rows, steps_module.clock()))
        state = self.rows.state
        bar.set_classes([_BAR_CLASS.get(state, "")] if state in _BAR_CLASS else [])

    # ---------------------------------------------------------------- the left pane

    def _label(self, row: Row) -> str:
        """One row of the LEFT pane: the state icon plus the row's IDENTITY - the dotted command path for
        anything the manifest planned, the prose label for the internal probes of a hand-built pipeline.
        Never the argv: `command` is the exact-command identity and belongs to the RIGHT pane's section
        header (netctl#897). Rendering it here turned the step list into a wall of `docker run --rm -v ...`
        where the operator wanted to read `package.web-jar`.

        Since #52 a row that RAN also carries its duration - one column, appended, so the pane gains no
        line. A row that did NOT run carries none: `⊘ deploy.up` stays bare, because `0.0s` there would
        claim the step finished instantly instead of never starting.

        Since si#148 a row that IS RUNNING carries a live counter in the same column, spelled `12.0s…`.
        The trailing ellipsis is one character and it is the whole difference between a step that took
        twelve seconds and one that has taken twelve so far and may take sixty more - without it the two
        rows are byte-identical and the column would answer a question it was not asked. The gap this
        closes: a running row carried NOTHING at all, so "compiling for three minutes" and "hung" looked
        the same, which is the question asked immediately before someone presses Ctrl-C.

        The live counter is a LEAF's only, and the restriction is not a shortcut. An aggregate's duration
        is its SPAN and `Row.duration` defines it only once everything under it is over, so a growing
        number there would be a second quantity in the same column - and the run's own elapsed, which is
        what an aggregate's live span would approximate, is on the bar already. It is also the expensive
        one: `TreeNode.set_label` marks every VISIBLE line of that node's subtree dirty, so a ticking ROOT
        would repaint the whole pane once a second, which is precisely the cost `_painted` exists to
        avoid. A ticking leaf writes one label and its ancestors are suppressed as unchanged.

        It returns a plain `str`, and that is load-bearing rather than incidental (si#148 item 7): the
        colour is applied where the widget is written, so `_painted` goes on comparing CONTENT, `_row`
        goes on handing a test text it can assert, and neither the headless `render_tree` nor the run
        transcript can ever acquire markup from here."""
        duration = row.duration
        if duration is not None:
            shown = f"  {format_duration(duration)}"
        elif row.is_leaf and row.state == StepState.RUNNING:
            elapsed = row.elapsed(steps_module.clock())
            shown = f"  {format_duration(elapsed)}…" if elapsed is not None else ""
        else:
            shown = ""
        return f"{STATE_ICON[row.state]} {row.label}{shown}"

    def _mount_tree(self) -> None:
        """Mount the display tree, fully expanded, and record the row chain of EVERY step, the root's own
        included.

        The root is not always an aggregate: `plan_tree_for` of an impl-bearing command returns a childless
        node, so `build_rows` legitimately hands back a one-row tree whose root carries the single step -
        and `run_command` is public kernel API a product can call with any command name. Recording only the
        chains reached through `children` left that pipeline with no chain at all, and five call sites
        (`_refresh_row`, `_begin_details`, `_on_line`, `_maybe_refresh_details`, `_on_done`) then no-opped
        in silence: the row stayed on its pending dot and the pane said "running" over a step that had
        already exited 0. Five readers tolerating a missing chain was the defect, not the contract."""
        tree = self._tree()
        tree.root.data = self.rows
        self._painted[id(self.rows)] = self._label(self.rows)
        index_of_step = {id(step): i for i, step in enumerate(self.pipeline.steps)}

        def record(row: Row, nodes: tuple[TreeNode, ...], rows: tuple[Row, ...]) -> None:
            if row.step is None:
                return
            index = index_of_step.get(id(row.step))
            if index is not None:
                self._chain_nodes[index] = nodes
                self._chain_rows[index] = rows

        def attach(parent: TreeNode, row: Row, nodes: tuple[TreeNode, ...],
                   rows: tuple[Row, ...]) -> None:
            for child in row.children:
                label = self._label(child)
                self._painted[id(child)] = label
                node = parent.add(label, data=child, expand=True)
                chain_nodes, chain_rows = nodes + (node,), rows + (child,)
                record(child, chain_nodes, chain_rows)
                attach(node, child, chain_nodes, chain_rows)

        record(self.rows, (tree.root,), (self.rows,))
        attach(tree.root, self.rows, (tree.root,), (self.rows,))
        tree.root.expand_all()

    def _tree(self) -> Tree:
        return self.query_one("#steps", Tree)

    def _row(self, i: int) -> str:
        """The left pane's text for step `i` - the leaf row it runs on. Kept as a named accessor because it
        is what a test can assert the left pane renders without reaching into Textual's node internals."""
        return self._label(self._chain_rows[i][-1])

    def _refresh_row(self, i: int) -> None:
        """Repaint step `i`'s row AND its ancestors: an aggregate's state is derived, so a leaf reaching
        OK/FAILED can change every row above it - but only the rows whose text really changed are written,
        see `_painted`."""
        for node, row in zip(self._chain_nodes.get(i, ()), self._chain_rows.get(i, ())):
            label = self._label(row)
            if self._painted.get(id(row)) != label:
                self._painted[id(row)] = label
                node.set_label(label)

    # ---------------------------------------------------------------- the right pane

    def _cursor_row(self) -> Row | None:
        node = self._tree().cursor_node
        return node.data if node is not None else None

    @staticmethod
    def _step_header(step: Step) -> str:
        """The details pane's first line for a step: its exact command, plus the command's own help text
        when the manifest gave it one (#49). One line, and only where a step is ENTERED - the left pane's
        rows stay the dotted paths, which is what makes them scannable."""
        identity = step.command or step.label
        return f"$ {identity} - {step.help}" if step.help else f"$ {identity}"

    def _details_text(self, row: Row) -> str:
        """What the right pane shows for `row`, as plain text - the one source `_show_details`, `c` and
        `s` all read, so what is copied is what is displayed rather than a second rendering of it."""
        # `step is not None` rather than `row.is_leaf`, and the two are the SAME test - `is_leaf` is
        # defined as exactly this. Only one of the two spellings narrows `Row.step` from `Step | None` to
        # `Step`, though, and every line below this reaches into the step, so the leaf test is written
        # where it does that work instead of leaving eleven unchecked attribute reads behind a property.
        step = row.step
        if step is not None:
            body = step.output.rstrip("\n") if step.output else {
                StepState.RUNNING: "(running…)",
                StepState.SKIPPED: f"(skipped: {self._skipped_because.get(id(step), 'a previous step failed')})",
                StepState.PENDING: "(pending)",
            }.get(step.state, "")
            return f"{self._step_header(step)}\n\n{body}".rstrip("\n")
        lines = [f"$ {row.label}", ""]
        for child in row.children:
            verdict = f"rc {child.rc}" if child.rc is not None else f"({child.state.value})"
            lines.append(f"{STATE_ICON[child.state]} {child.label}  {verdict}")
        note = omitted_note(row)
        if note:
            lines += ["", note]
        elif not row.children:
            lines.append("(no steps)")
        return "\n".join(lines).rstrip("\n")

    def _save_details_to(self, identity: str, text: str):
        """Write one pane's text; separated so a test can substitute it and so the path comes back."""
        return steplog.write(identity, text)

    def action_copy_details(self) -> None:
        row = self._cursor_row()
        if row is None:
            return
        self.copy_to_clipboard(self._details_text(row))
        self.notify("copied to the clipboard", timeout=3)

    def action_save_details(self) -> None:
        row = self._cursor_row()
        if row is None:
            return
        step = row.step
        identity = (step.command or step.label) if step is not None else row.label
        path = self._save_details_to(identity, self._details_text(row))
        self.notify(f"saved to {path}" if path else "nowhere to save to (no product context)", timeout=5)

    def _show_details(self, row: Row) -> None:
        rlog = self.query_one("#details", RichLog)
        rlog.clear()
        step = row.step
        if step is not None:
            rlog.write(f"{self._step_header(step)}\n")
            if step.output:
                rlog.write(step.output.rstrip("\n"))
            elif step.state == StepState.RUNNING:
                rlog.write("(running…)")
            elif step.state == StepState.SKIPPED:
                rlog.write(f"(skipped: {self._skipped_because.get(id(step), 'a previous step failed')})")
            elif step.state == StepState.PENDING:
                rlog.write("(pending)")
            return
        # An aggregate has no output of its own: what it can answer is "what is under me, and how did it
        # go", so the pane lists its children with their exit codes.
        rlog.write(f"$ {row.label}\n")
        for child in row.children:
            verdict = f"rc {child.rc}" if child.rc is not None else f"({child.state.value})"
            rlog.write(f"{STATE_ICON[child.state]} {child.label}  {verdict}")
        note = omitted_note(row)
        if note:
            rlog.write("")
            rlog.write(note)
        elif not row.children:
            rlog.write("(no steps)")

    def _begin_details(self, i: int) -> None:
        """When a step STARTS: if its own row is highlighted, clear the pane and write its header so the
        streamed lines append below it live; if an ANCESTOR is highlighted, redraw that aggregate's listing
        so the child flips to running there too."""
        cursor = self._cursor_row()
        chain = self._chain_rows.get(i, ())
        if cursor is None or cursor not in chain:
            return
        if cursor is chain[-1]:
            rlog = self.query_one("#details", RichLog)
            rlog.clear()
            step = self.pipeline.steps[i]
            rlog.write(f"{self._step_header(step)}\n")
        else:
            self._show_details(cursor)

    def _on_line(self, i: int, line: str) -> None:
        """A streamed output line: append it live only if its own step's row is the highlighted one."""
        chain = self._chain_rows.get(i, ())
        if chain and self._cursor_row() is chain[-1]:
            self.query_one("#details", RichLog).write(line)

    def _emitter(self, i: int) -> Emit:
        """Step `i`'s live-line callback.

        A method rather than the `lambda line, i=i:` it replaces. The default-argument trick was there to
        bind the loop variable per iteration, which a parameter does anyway - and it cost the checker the
        lambda's type entirely, so nothing verified that what `Step.run` is handed matches `Emit`. Now it
        does, and the capture is a call frame instead of a mutable default.
        """
        def emit(line: str) -> None:
            self.call_from_thread(self._on_line, i, line)

        return emit

    def _maybe_refresh_details(self, i: int) -> None:
        cursor = self._cursor_row()
        if cursor is not None and cursor in self._chain_rows.get(i, ()):
            self._show_details(cursor)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.data is not None:
            self._show_details(event.node.data)

    # ---------------------------------------------------------------- the runner

    @work(thread=True)
    def _run_steps(self) -> None:
        # The doomed step indices, not a `stopped` latch: a failure aborts the SUBTREE that declared
        # stop_on_failure (netctl#1317), so the steps after it may be that subtree's siblings and still run.
        aborted: set[int] = set()
        for i, step in enumerate(self.pipeline.steps):
            if i in aborted:
                step.state = StepState.SKIPPED                      # its subtree stopped: do not run it
                self.call_from_thread(self._refresh_row, i)
                self.call_from_thread(self._maybe_refresh_details, i)   # -> the pane names the scope
                self.call_from_thread(self._repaint_status)
                continue
            step.state = StepState.RUNNING
            step.started_at = steps_module.clock()   # so the bar and the row count from HERE, not from
            # the moment `Step.run` is reached: `_begin_details` and a repaint sit between the two, and a
            # counter that started after them would under-report every step by that much. `Step.run` sets
            # it again from the same clock, which is idempotent to within those microseconds.
            self.call_from_thread(self._refresh_row, i)             # -> RUNNING shown
            self.call_from_thread(self._begin_details, i)
            self.call_from_thread(self._repaint_status)
            # stream lines live into the details pane (only rendered when this step is highlighted)
            outcome = step.run(self._emitter(i))
            self.call_from_thread(self._refresh_row, i)             # -> OK/FAILED
            self.call_from_thread(self._maybe_refresh_details, i)
            self.call_from_thread(self._repaint_status)
            if not outcome.ok:
                abort = abort_after(self.pipeline, i)
                aborted |= abort.indices
                for doomed in abort.indices:
                    self._skipped_because.setdefault(id(self.pipeline.steps[doomed]), abort.reason)
        self.call_from_thread(self._on_done)

    def _on_done(self) -> None:
        rc = overall_rc(self.pipeline)
        self.sub_title = "done - all passed" if rc == 0 else "done - failures (press q)"
        self._repaint_status()
        # auto-focus the first failed step's details, if any
        for i, step in enumerate(self.pipeline.steps):
            if step.state == StepState.FAILED and i in self._chain_nodes:
                self._tree().move_cursor(self._chain_nodes[i][-1])
                self._show_details(self._chain_rows[i][-1])
                break
