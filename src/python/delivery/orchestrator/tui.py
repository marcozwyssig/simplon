"""The Textual split-pane runner for a step Pipeline: LEFT the plan as a TREE (one row per command, its
state icon in front of its dotted path), RIGHT the details of the highlighted row - a leaf's live output, an
aggregate's children with their exit codes. This is the UX Marco asked for. It degrades to the flat headless
runner (steps.run_headless) when stdout is not a TTY (CI, piped) or when Textual is unavailable - so CI logs
stay clean and the real subprocess exit codes still drive pass/fail. The overall exit code always comes from
steps.overall_rc, never from the UI state.

The tree is DISPLAY only (netctl#1276): execution still walks the flat `pipeline.steps` list in order, and an
aggregate row is never run - its state is derived from the children below it (steps.Row.state).
"""
from __future__ import annotations

import sys

from .steps import (STATE_ICON, Pipeline, Row, StepState, build_rows, omitted_note, overall_rc,
                    run_headless)


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
from textual.widgets import Footer, Header, RichLog, Tree  # noqa: E402
from textual.widgets.tree import TreeNode  # noqa: E402


class _StepApp(App):
    """Left: the plan tree with state icons. Right: the highlighted row's details."""

    CSS = """
    #steps { width: 38%; border-right: solid $primary; }
    #details { width: 1fr; padding: 0 1; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("up", "cursor_up", "Up"), ("down", "cursor_down", "Down")]

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
        yield Footer()

    def on_mount(self) -> None:
        self._mount_tree()
        self._show_details(self.rows)
        self._run_steps()

    # ---------------------------------------------------------------- the left pane

    def _label(self, row: Row) -> str:
        """One row of the LEFT pane: the state icon plus the row's IDENTITY - the dotted command path for
        anything the manifest planned, the prose label for the internal probes of a hand-built pipeline.
        Never the argv: `command` is the exact-command identity and belongs to the RIGHT pane's section
        header (netctl#897). Rendering it here turned the step list into a wall of `docker run --rm -v ...`
        where the operator wanted to read `package.web-jar`."""
        return f"{STATE_ICON[row.state]} {row.label}"

    def _mount_tree(self) -> None:
        """Mount the display tree, fully expanded, and record each step's row chain."""
        tree = self._tree()
        tree.root.data = self.rows
        self._painted[id(self.rows)] = self._label(self.rows)
        index_of_step = {id(step): i for i, step in enumerate(self.pipeline.steps)}

        def attach(parent: TreeNode, row: Row, nodes: tuple[TreeNode, ...],
                   rows: tuple[Row, ...]) -> None:
            for child in row.children:
                label = self._label(child)
                self._painted[id(child)] = label
                node = parent.add(label, data=child, expand=True)
                chain_nodes, chain_rows = nodes + (node,), rows + (child,)
                if child.step is not None:
                    index = index_of_step.get(id(child.step))
                    if index is not None:
                        self._chain_nodes[index] = chain_nodes
                        self._chain_rows[index] = chain_rows
                attach(node, child, chain_nodes, chain_rows)

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

    def _show_details(self, row: Row) -> None:
        rlog = self.query_one("#details", RichLog)
        rlog.clear()
        if row.is_leaf:
            step = row.step
            rlog.write(f"$ {step.command or step.label}\n")
            if step.output:
                rlog.write(step.output.rstrip("\n"))
            elif step.state == StepState.RUNNING:
                rlog.write("(running…)")
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
            rlog.write(f"$ {step.command or step.label}\n")
        else:
            self._show_details(cursor)

    def _on_line(self, i: int, line: str) -> None:
        """A streamed output line: append it live only if its own step's row is the highlighted one."""
        chain = self._chain_rows.get(i, ())
        if chain and self._cursor_row() is chain[-1]:
            self.query_one("#details", RichLog).write(line)

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

    def _on_done(self) -> None:
        rc = overall_rc(self.pipeline)
        self.sub_title = "done - all passed" if rc == 0 else "done - failures (press q)"
        # auto-focus the first failed step's details, if any
        for i, step in enumerate(self.pipeline.steps):
            if step.state == StepState.FAILED and i in self._chain_nodes:
                self._tree().move_cursor(self._chain_nodes[i][-1])
                self._show_details(self._chain_rows[i][-1])
                break
