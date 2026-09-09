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
from datetime import datetime
from typing import Iterable

from . import steps as steps_module
from .steps import (STATE_ICON, Emit, Pipeline, Row, Step, StepState, abort_after, build_rows,
                    failure_report, format_duration, omitted_note, overall_rc, run_headless,
                    status_line, step_header, write_run_transcript)


def run_pipeline(pipeline: Pipeline) -> int:
    """Run the pipeline in the Textual UI when attached to a TTY (and Textual imports), else headless.
    Returns the overall exit code (0 iff every step passed)."""
    if not sys.stdout.isatty():
        return run_headless(pipeline)     # which writes its own transcript
    try:
        app = _StepApp(pipeline)
    except Exception:  # noqa: BLE001 - any Textual import/construct issue -> safe fallback
        return run_headless(pipeline)
    app.run()
    # AFTER the app, not from `_on_done`: quitting is a normal way for `App.run` to return, and a run the
    # operator stopped half way through is exactly the one whose record is worth keeping (si#148 item 3).
    write_run_transcript(pipeline, app.started)
    # The TUI's screen - and with it the details pane that held the reason - is gone the moment the app
    # exits. The same block a CI log gets is therefore printed onto the terminal the operator is left
    # looking at (#49). A run with no failure prints nothing here, so a green run is not one line longer.
    for line in failure_report(pipeline):
        print(line, flush=True)
    return overall_rc(pipeline)


# Textual is imported lazily inside the class module-load so that `from .tui import run_pipeline` does
# not hard-require Textual on the headless path (run_pipeline's isatty check returns before this is
# touched in CI). The import sits at module top but the headless fallback in cli.py catches ImportError.
from rich.style import Style  # noqa: E402
from rich.text import Text  # noqa: E402
from textual import work  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.app import App, ComposeResult, SystemCommand  # noqa: E402
from textual.screen import Screen  # noqa: E402
from textual.theme import Theme  # noqa: E402
from textual.containers import Horizontal  # noqa: E402
from textual.widgets import Footer, Header, Input, RichLog, Static, Tree  # noqa: E402

from simplon import steplog  # noqa: E402
from textual.widgets.tree import TreeNode  # noqa: E402

#: The bar's colour, by the RUN's derived state. Three classes for five states, and the two that are
#: missing are deliberate: the bar is one line and its job is the run, so PENDING (nothing has happened)
#: and SKIPPED (a run in which nothing ran at all) leave it in the theme's ordinary foreground rather
#: than spending a colour on the absence of news. The per-ROW mapping, which does have to separate all
#: five, is `_STATE_STYLE`.
_BAR_CLASS = {StepState.RUNNING: "-running", StepState.OK: "-ok", StepState.FAILED: "-failed"}


def _state_styles(theme: Theme) -> dict[StepState, Style]:
    """Each state's style, built from the THEME's own variables (si#148 item 7) - `$success`, `$warning`,
    `$error` - so the result follows the terminal and Textual's own light/dark handling instead of
    fighting it, and follows the theme the operator picks in the command palette.

    FIVE STATES AND THREE COLOURS, and the mapping is an argument rather than a preference:

      - OK is green and FAILED is red, which need no defending. FAILED is also BOLD, because the item's
        whole point is a failure findable at a glance in a tree of forty, and red alone in a column of
        forty short rows is not a glance.
      - RUNNING takes the yellow. Amber means "in flight, outcome unknown", and the running row is the
        one an operator hunts for while the run is live - it is the only row whose state will change.
      - SKIPPED takes the same yellow one brightness down. It is the same *unknown outcome* - the step
        did not run and never will - and dimming it keeps it from competing for attention with the
        FAILURE that caused it, which is what the reader actually has to find.
      - PENDING gets no colour at all, only dim. Nothing has happened there; a colour would spend a
        reader's attention on the rows carrying no information, and in a fresh 40-step plan that is all
        of them.

    ADDITIVE, NEVER SOLE. `STATE_ICON` is untouched and every row keeps its glyph, so a reader with a
    colour vision deficiency, a terminal with a broken palette and a saved log all keep working.
    """
    return {StepState.OK: Style(color=theme.success),
            StepState.FAILED: Style(color=theme.error, bold=True),
            StepState.RUNNING: Style(color=theme.warning),
            StepState.SKIPPED: Style(color=theme.warning, dim=True),
            StepState.PENDING: Style(dim=True)}


class _StepApp(App):
    """Left: the plan tree with state icons. Right: the highlighted row's details."""

    CSS = """
    #steps { width: 38%; border-right: solid $primary; }
    #details { width: 1fr; padding: 0 1; }
    #filter { height: 3; }
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
    #
    # `f`, `n` and `/` are si#148's three, and the footer is where they are discoverable at all. It is
    # also close to full at eight entries, which is why the command palette (ctrl+p) carries the same
    # actions with a sentence each: a footer is a reminder for someone who already knows, a palette is
    # how somebody finds out.
    BINDINGS = [("q", "quit", "Quit"), ("up", "cursor_up", "Up"), ("down", "cursor_down", "Down"),
                ("f", "follow", "Follow"), ("n", "next_failure", "Next failure"),
                # PRIORITY, so `/` closes the filter box it opened instead of being typed into it. The
                # cost is that a filter cannot contain a literal `/`, and it is nothing: what the filter
                # matches are ROW identities, which are dotted command paths and prose labels. The gain
                # is that the toggle is one key and one footer entry rather than two - the footer is the
                # only place a key is discoverable and it is already full.
                Binding("/", "filter", "Filter", priority=True),
                ("c", "copy_details", "Copy"), ("s", "save_details", "Save")]

    def __init__(self, pipeline: Pipeline) -> None:
        super().__init__()
        self.pipeline = pipeline
        # When this run began, in WALL time, for the transcript header - the app is the one object that
        # exists for exactly the run's lifetime, so `run_pipeline` and the `ctrl+p` action read the same
        # instant instead of each taking their own.
        self.started = datetime.now()
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
        # FOLLOW MODE (si#148 item 1): while true, each step that starts takes the cursor with it. On by
        # default, because a run nobody has touched should show what it is doing rather than an aggregate
        # listing - and off the moment the operator navigates, because a cursor that keeps being taken
        # away is worse than one that never moves.
        self._follow = True
        # The ROW this app last moved the cursor to. A remembered target rather than a flag around
        # `move_cursor`, because Textual POSTS `NodeHighlighted` instead of calling the handler: a guard
        # set and cleared around the call is long gone by the time the handler runs, and every one of the
        # app's own moves would then read as the operator navigating.
        #
        # A ROW and not a TreeNode, which is not a detail: `Tree.clear()` builds a NEW root object, so the
        # `/` filter's remount replaces every node in the pane while the `Row` objects are reused. Held by
        # node, the token stopped matching the moment a filter went up - measured, and it switched follow
        # mode off on the app's own repaint.
        self._expected_row: Row | None = None
        # The substring the left pane is filtered by, "" for no filter (si#148 item 5).
        self._filter = ""
        # Where the reader was in each row's output, by row identity (si#148 item 6). `_show_details`
        # clears the pane and rewrites it, so somebody who found a place in a long step's output, looked
        # elsewhere and came back had to find it again. Kept per ROW rather than per pane, because the
        # question is "where was I in THIS step".
        self._scroll_at: dict[int, int] = {}
        # Which row the pane is currently rendering, so the offset above can be saved for the row being
        # LEFT. The cursor has already moved by the time a highlight arrives, so the pane has to remember
        # what it was showing itself.
        self._showing: Row | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Tree(self._styled(self.rows), id="steps")
            # auto_scroll OFF, and the sticky bottom is `_on_line`'s job instead (si#148 item 6).
            # Measured out of `RichLog.write`: the `auto_scroll` branch calls `scroll_end` on EVERY write
            # without ever asking where the reader is, so one emitted line threw a reader who had
            # scrolled to line 10 down to line 182. Following a running step by reading it was impossible.
            yield RichLog(id="details", wrap=True, highlight=False, markup=False, auto_scroll=False)
        yield Input(placeholder="filter the plan (/ again to clear)", id="filter")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#filter", Input).display = False
        self._mount_tree()
        # The tree keeps the focus, explicitly. Adding the filter box put a second focusable widget on
        # the screen, and with it the `up`/`down`/`c`/`s` keys reached a hidden Input instead of the pane
        # they belong to - measured as two `down` presses that moved nothing.
        self._tree().focus()
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
        repainted with the leaf and a row whose text did not change is not written again.

        IT READS WORKER-THREAD STATE WITHOUT A HANDSHAKE, and that is worth naming because it is the one
        reader here that has none. Every other main-thread reader of `Step.state` / `started_at` runs
        inside a callback the worker itself scheduled through `call_from_thread`, so the message queue
        gives it an ordering. This one is on a timer. It is safe because each of those is a single
        attribute and CPython's GIL makes such a read atomic - the worst case is a value one tick stale,
        which the next tick corrects, and never a torn read. If this ever runs on a free-threaded
        interpreter, that argument is the one to revisit."""
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

    def _styled(self, row: Row) -> Text:
        """`_label`'s text, wearing its state's colour - the ONE place a row acquires one (si#148 item 7).

        The split is the constraint, not an implementation detail. `_label` stays a plain `str`, so
        `_painted` keeps comparing CONTENT and a repaint is still suppressed when the text did not change;
        `_row` keeps handing a test something it can assert; and the shared `STATE_ICON` vocabulary that
        `render_tree` and the run transcript also render can never pick up markup, because neither of them
        passes through here."""
        return Text(self._label(row), style=_state_styles(self.current_theme)[row.state])

    def _mount_tree(self) -> None:
        """Mount the display tree, fully expanded, and record the row chain of EVERY step, the root's own
        included.

        The root is not always an aggregate: `plan_tree_for` of an impl-bearing command returns a childless
        node, so `build_rows` legitimately hands back a one-row tree whose root carries the single step -
        and `run_command` is public kernel API a product can call with any command name. Recording only the
        chains reached through `children` left that pipeline with no chain at all, and five call sites
        (`_refresh_row`, `_begin_details`, `_on_line`, `_maybe_refresh_details`, `_on_done`) then no-opped
        in silence: the row stayed on its pending dot and the pane said "running" over a step that had
        already exited 0. Five readers tolerating a missing chain was the defect, not the contract.

        SINCE si#148 IT ALSO REMOUNTS. A Textual `TreeNode` cannot be hidden - measured against the pinned
        8.2.8, whose node surface carries no `display` and no `visible` - so the `/` filter has no way to
        mask rows in place and rebuilds the pane instead. That is affordable precisely because this method
        already derives everything (the nodes, the chains, the `_painted` baseline) from `self.rows` in
        one pass, and because the `Row` objects are REUSED: `_painted`'s `id(row)` keys survive the
        rebuild and are re-primed here with each row's current text, so a filter cannot leave a row
        showing a state it has since left.

        A row hidden by a filter simply has no chain, which is the state the five readers above already
        handle by design - and the RUN goes on painting into a pane that is not showing it, so clearing
        the filter mid-run shows the truth rather than a snapshot from when it went up."""
        tree = self._tree()
        tree.clear()
        self._chain_nodes.clear()
        self._chain_rows.clear()
        tree.root.data = self.rows
        # No `set_label` for the root here: the widget is CONSTRUCTED with this text (see `compose`) and
        # `Tree.clear()` carries the current label onto the new root it builds, so writing it again would
        # be the one redundant write `_painted` exists to prevent. A theme change goes through
        # `_repaint_everything`, which clears `_painted` and therefore does write it.
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
                if not self._kept(child):
                    continue
                self._painted[id(child)] = self._label(child)
                node = parent.add(self._styled(child), data=child, expand=True)
                chain_nodes, chain_rows = nodes + (node,), rows + (child,)
                record(child, chain_nodes, chain_rows)
                attach(node, child, chain_nodes, chain_rows)

        record(self.rows, (tree.root,), (self.rows,))
        attach(tree.root, self.rows, (tree.root,), (self.rows,))
        tree.root.expand_all()
        # `Tree.clear()` leaves `cursor_node` pointing into the tree it just discarded, so the cursor is
        # put back on the rebuilt root here. Without it the pane has a cursor line and no cursor NODE,
        # and every reader that starts from `_cursor_row` - the details pane, `c`, `s`, `n` - answers
        # None over a tree that is plainly on screen.
        tree.move_cursor(tree.root)
        # The root is where the cursor starts and Textual announces that as an ordinary highlight. Naming
        # it here keeps `on_tree_node_highlighted` from reading the app's OWN opening frame as the
        # operator navigating, which would switch follow mode off before the first step had run.
        self._expected_row = self.rows

    def _kept(self, row: Row) -> bool:
        """Whether `row` survives the current filter: it matches, or something under it does (si#148 item
        5). An ancestor is kept because it CARRIES a match - a filtered pane that dropped the path to what
        it found would be a flat list, and the shape is the left pane's whole value."""
        if not self._filter:
            return True
        needle = self._filter.lower()
        return needle in row.label.lower() or any(self._kept(child) for child in row.children)

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
                node.set_label(self._styled(row))

    # ---------------------------------------------------------------- the right pane

    def _cursor_row(self) -> Row | None:
        node = self._tree().cursor_node
        return node.data if node is not None else None

    @staticmethod
    def _step_header(step: Step) -> str:
        """The details pane's first line for a step: its exact command, plus the command's own help text
        when the manifest gave it one (#49). One line, and only where a step is ENTERED - the left pane's
        rows stay the dotted paths, which is what makes them scannable.

        The line itself moved down to `steps.step_header` with si#148, because the run transcript renders
        the same sentence and is written on the headless path too. Two spellings of one line is how two
        artefacts of the same run come to disagree; this stays as the pane's own name for it."""
        return step_header(step)

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
        """Render `row` into the right pane, remembering where the reader was in the row being LEFT and
        restoring where they were in the row being entered (si#148 item 6).

        A row never visited before opens at the BOTTOM, which is deliberate and is what the pane did
        before: a step's output ends with the thing that decided it - the traceback's last frame, `Found
        3 errors`, `BUILD SUCCESSFUL` - and that is what a reader opening a finished step wants first.
        What changes is only that a place somebody found is not thrown away when they look elsewhere."""
        rlog = self.query_one("#details", RichLog)
        if self._showing is not None and self._showing is not row:
            self._scroll_at[id(self._showing)] = int(rlog.scroll_offset.y)
        self._showing = row
        rlog.clear()
        self._render_details(rlog, row)
        remembered = self._scroll_at.get(id(row))
        if remembered is None:
            rlog.scroll_end(animate=False)
        else:
            rlog.scroll_to(y=remembered, animate=False)

    def _render_details(self, rlog: RichLog, row: Row) -> None:
        """Write `row` into an ALREADY CLEARED pane. Split out of `_show_details` so the scroll bookkeeping
        wraps every branch of it, including the early return a leaf takes."""
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
            # A step that is STARTING has no place a reader could have found yet, so any offset kept for
            # this row belongs to a previous rendering of it and would drop the reader into the middle of
            # a pane holding one line (si#148 item 6).
            self._showing = cursor
            self._scroll_at.pop(id(cursor), None)
            step = self.pipeline.steps[i]
            rlog.write(f"{self._step_header(step)}\n")
        else:
            self._show_details(cursor)

    def _on_line(self, i: int, line: str) -> None:
        """A streamed output line: append it live only if its own step's row is the highlighted one.

        A STICKY BOTTOM rather than Textual's `auto_scroll` (si#148 item 6): where the reader was BEFORE
        the write decides where they are after it. At the bottom means "watching the tail", and the tail
        is what has to keep arriving; anywhere else means "reading", and a reader must not be moved.

        `auto_scroll` cannot express that - its branch in `RichLog.write` is unconditional - which is why
        the widget is constructed with it off. See `compose` for the measurement."""
        chain = self._chain_rows.get(i, ())
        if not (chain and self._cursor_row() is chain[-1]):
            return
        rlog = self.query_one("#details", RichLog)
        following_the_tail = rlog.is_vertical_scroll_end
        rlog.write(line, scroll_end=False)
        if following_the_tail:
            rlog.scroll_end(animate=False)

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
        row = event.node.data
        if row is None:
            # A node carrying no Row: the pane's opening frame, before `_mount_tree` has put the root row
            # on it, and any node left over from a tree a remount discarded. Neither is the operator and
            # neither has anything to show, so both are ignored rather than read as navigation - which is
            # what switched follow mode off before the first step had run.
            return
        if row is not self._expected_row:
            # Anything the app did not ask for is the operator: a key, a click, `n`. Following stops,
            # because a cursor that keeps being taken away from where somebody put it is worse than one
            # that never moves. The target is NOT cleared on a match, deliberately: one move can announce
            # itself more than once (a remount posts a highlight of its own), and a one-shot token turned
            # the second announcement into a phantom keypress.
            self._follow = False
        self._show_details(row)

    # ---------------------------------------------------------------- following, finding, filtering

    def _follow_to(self, index: int) -> None:
        """Take the cursor to step `index`'s row, if following is on and that row is on screen.

        A row hidden by the current filter has no chain, so this is a no-op for it rather than a jump to
        something else - the operator filtered it away on purpose, and the bar goes on naming it."""
        if not self._follow:
            return
        chain = self._chain_nodes.get(index, ())
        if not chain:
            return
        tree = self._tree()
        if tree.cursor_node is chain[-1]:
            return
        self._expected_row = self._chain_rows[index][-1]
        tree.move_cursor(chain[-1])

    def action_follow(self) -> None:
        """Resume following, and go straight to what is running rather than waiting for the next step -
        an operator asking to follow a run is asking about the step in flight, not the one after it."""
        self._follow = True
        running = next((i for i, step in enumerate(self.pipeline.steps)
                        if step.state == StepState.RUNNING), None)
        if running is not None:
            self._follow_to(running)
        self.notify("following the running step", timeout=3)

    def action_next_failure(self) -> None:
        """The cursor to the next FAILED step after this one, wrapping (si#148 item 5).

        Three failures among forty steps and the only way to find them was to scan the icons. It walks the
        EXECUTION order rather than the visible rows, so it is the same walk whatever the tree is
        filtered to - and a failure the filter is hiding is still reachable, which is the behaviour that
        keeps `/` and `n` from cancelling each other out.

        A green run notifies instead of moving. Moving the cursor somewhere arbitrary to signal "nothing
        found" is how a UI answers a question it was not asked.
        """
        failed = [i for i, step in enumerate(self.pipeline.steps) if step.state == StepState.FAILED]
        if not failed:
            self.notify("no failure in this run", timeout=3)
            return
        cursor = self._cursor_row()
        # -1 when the cursor is on an aggregate, on nothing, or on a row the filter has taken away, so
        # the walk starts at the first failure. `cursor is not None` is not defensive noise: without it a
        # missing chain answers `(None,)[-1]`, which would MATCH a null cursor and silently pin `here` to
        # step 0.
        here = -1 if cursor is None else next(
            (i for i in range(len(self.pipeline.steps))
             if self._chain_rows.get(i, ()) and self._chain_rows[i][-1] is cursor), -1)
        target = next((i for i in failed if i > here), failed[0])
        chain = self._chain_nodes.get(target, ())
        if not chain:
            # It is hidden by the filter. Showing it means dropping the filter, which is what the operator
            # asked for by pressing `n` - the alternative is a key that silently does nothing.
            self._set_filter("")
            chain = self._chain_nodes.get(target, ())
        if chain:
            self._tree().move_cursor(chain[-1])

    def action_filter(self) -> None:
        """`/` opens the filter box, and `/` again closes it AND clears the filter.

        A toggle rather than a separate escape binding, deliberately: the footer is the only place a key
        is discoverable and it is already at eight entries, so a second key for "undo the last one" is a
        line of footer spent on a reflex the same key can carry."""
        box = self.query_one("#filter", Input)
        if box.display:
            box.display = False
            box.value = ""
            self._set_filter("")
            self._tree().focus()
            return
        box.display = True
        box.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self._set_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter leaves the filter in place and gives the tree the cursor back - the operator has found
        what they were looking for and now wants to move around inside it."""
        if event.input.id == "filter":
            event.input.display = False
            self._tree().focus()

    def _set_filter(self, needle: str) -> None:
        """Apply a filter and rebuild the left pane, keeping the cursor where it was."""
        if needle == self._filter:
            return
        self._filter = needle
        self._repaint_everything()

    def _repaint_everything(self) -> None:
        """Rebuild the left pane, keeping the cursor on the row it was on when that row survives - and
        putting it somewhere real when it does not, because a pane with no cursor has nothing to show on
        the right.

        Two callers, and both are RARE by construction: a filter going up or down, and an operator picking
        a theme. Neither is on the per-second path, which is why a full rebuild is the affordable answer
        to both - a `TreeNode` cannot be hidden and its style cannot be changed without rewriting its
        label, so each of them is a rewrite of every row either way."""
        was = self._cursor_row()
        self._painted.clear()      # a theme change alters no TEXT, so the content guard has to be lifted
        self._mount_tree()
        target = next((nodes[-1] for index, nodes in self._chain_nodes.items()
                       if self._chain_rows[index][-1] is was), None)
        if target is not None:
            self._expected_row = was
            self._tree().move_cursor(target)
        row = self._cursor_row()
        if row is not None:
            self._show_details(row)

    def watch_theme(self, theme: str) -> None:
        """Repaint when the operator picks another theme in the command palette.

        The styles are read from `current_theme` at write time, so nothing about them is stale - but a
        `TreeNode` holds the `Text` it was last given, and no row's TEXT changes when a theme does. Hence
        the repaint, and hence `_repaint_everything` clearing `_painted` before it: the content guard
        would otherwise correctly suppress every single write."""
        if self.is_running and self._chain_nodes:
            self._repaint_everything()

    # ---------------------------------------------------------------- the command palette (item 9)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Every action this runner has, discoverable without a key (si#148 item 9, ctrl+p).

        `yield from super()` FIRST and deliberately: Textual's own commands come with the palette, and two
        of them answer questions this ticket raised. `Theme` is the honest answer to a terminal whose
        palette makes our green unreadable - the operator picks another one and `watch_theme` repaints.
        `Keys` opens a panel with help for the focused widget and a summary of the bindings, which is why
        this change adds no F1 of its own: `_step_header` already renders the manifest's `help:` for the
        step on screen, and a second door to a panel Textual already opens would cost a footer slot for
        nothing.
        """
        yield from super().get_system_commands(screen)
        yield SystemCommand("Follow the running step",
                            "Move the cursor to each step as it starts", self.action_follow)
        yield SystemCommand("Next failure", "Jump to the next failed step, wrapping",
                            self.action_next_failure)
        yield SystemCommand("Filter the plan", "Show only the rows matching a substring",
                            self.action_filter)
        yield SystemCommand("Copy this step's output", "To the clipboard", self.action_copy_details)
        yield SystemCommand("Save this step's output", "To a file under build/logs/",
                            self.action_save_details)
        yield SystemCommand("Transcript of this run",
                            "Write build/logs/run-transcript.log now, without waiting for the end",
                            self.action_save_transcript)

    def action_save_transcript(self) -> None:
        """Write the run transcript NOW. It is written again when the app exits; what this adds is the
        long run somebody wants to report on while it is still going."""
        path = write_run_transcript(self.pipeline, self.started)
        self.notify(f"transcript written to {path}" if path
                    else "nowhere to write a transcript to (no product context)", timeout=5)

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
            self.call_from_thread(self._follow_to, i)   # BEFORE the pane: `_begin_details` decides what to
            # write from where the cursor IS, so moving it first is what makes the pane open on the step
            # that just started instead of redrawing the aggregate the operator was left looking at.
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
                self._expected_row = self._chain_rows[i][-1]     # the app's own move, not the operator's
                self._tree().move_cursor(self._chain_nodes[i][-1])
                self._show_details(self._chain_rows[i][-1])
                break
