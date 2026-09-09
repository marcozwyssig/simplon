# A run easier to follow - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An operator watching a pipeline can answer "what is running, how long has it been running, and
how is the run doing" without touching a key, can find a failure in a tree of forty at a glance, and is
left with one file that describes the whole run well enough to attach to a ticket.

**Ticket:** [si#148](https://github.com/marcozwyssig/simplon/issues/148), plus three maintainer additions
recorded below as items 7-9. Related: [si#144](https://github.com/marcozwyssig/simplon/issues/144)
(Textual stays; its mechanism A must not be made unreachable),
[si#125](https://github.com/marcozwyssig/simplon/issues/125) (the provenance line item 4 reuses),
[si#147](https://github.com/marcozwyssig/simplon/issues/147) (parallel execution, which the status bar's
shape must survive).

**Tech Stack:** Python 3.11+, Textual 8.2.8 (pinned `>=8.2.8,<9`), pytest, mypy. No new dependency, no
new catalogue coordinate.

## The nine items

The ticket names six. The maintainer added three while this plan was being written, and item 8 displaced
item 1 as the centre of the change.

| # | What | Where |
|---|------|-------|
| 1 | Follow mode: the cursor moves to each step as it starts, stops on manual navigation, resumes on a key | `tui.py` |
| 2 | A live elapsed counter on the running row, driven by an injectable clock | `steps.py` + `tui.py` |
| 3 | A run transcript: every step in order, with its rc and its duration | `steps.py` + `steplog.py` |
| 4 | A transcript header: start time, environment, instance, simplon provenance | `steplog.py` + `cli.py` |
| 5 | `n` for the next failure, `/` to filter the tree by substring | `tui.py` |
| 6 | The details pane keeps its scroll position, and stops fighting a reader who scrolled up | `tui.py` |
| 7 | State by COLOUR as well as by glyph, from the theme's variables | `tui.py` |
| 8 | A status bar that always names the ACTIVE step and the run's aggregate | `steps.py` + `tui.py` |
| 9 | The command palette, carrying every action this change adds | `tui.py` |

Explicitly **not** built: jump mode (we have two panes and a tree; the tree has a cursor), and an F1
contextual-help panel - see "Decisions" for why the second one is a refusal rather than an omission.

## The measurements this plan rests on

Made on this machine, 2026-09-09, against the pinned `textual==8.2.8` in `deploy/orchestrator/.venv`.
They decide the shape, so they are recorded here rather than discovered during implementation.

**(a) `auto_scroll` really does fight the reader.** Read out of `RichLog.write`:

```python
auto_scroll = self.auto_scroll if scroll_end is None else scroll_end
...
if auto_scroll:
    self.scroll_end(animate=animate, immediate=False, x_axis=False)
```

`auto_scroll` defaults to `True`, and the branch is unconditional - it does not ask where the reader is.
So every emitted line of a running step yanks a reader who scrolled up back to the bottom, and following
a running step by reading it is impossible today. That is half of item 6 and it is a defect, not a
preference. The `scroll_end` PARAMETER is the seam: passing `False` per write leaves the offset alone,
and `RichLog.is_vertical_scroll_end` answers where the reader was before the write.

**(b) A Textual `TreeNode` cannot be hidden.** Its public surface is
`add/add_leaf/allow_expand/children/collapse/.../set_label/siblings/toggle` - no `display`, no `visible`.
So item 5's filter cannot mask rows in place; it has to REMOUNT the tree from `self.rows` with a
predicate. That is affordable because `_mount_tree` already builds everything (nodes, chains, `_painted`)
from `self.rows` in one pass, and the `Row` objects are reused, so `_painted`'s `id(row)` keys survive.

**(c) The theme picker and a contextual help panel come free with the command palette.**
`App.get_system_commands` already yields `Theme` ("Change the current theme"), `Quit`, `Keys` ("Show help
for the focused widget and a summary of available keys"), `Maximize` and `Screenshot`, and it is
documented as the override point (`yield from super().get_system_commands(screen)`). `ENABLE_COMMAND_PALETTE`
is `True` by default and `COMMAND_PALETTE_BINDING` is `ctrl+p`. So item 9 is an override of one method,
the theme picker of item 7's third bullet costs nothing, and F1 would be a second door to a panel Textual
already opens.

**(d) `Theme` carries the variables item 7 needs as real values.** Its fields include
`primary, secondary, warning, error, success, accent, foreground, background, surface, panel, dark`. So a
per-row Rich `Style` can be built from `self.current_theme.success` rather than from a literal colour, and
it follows the theme the operator picks in (c).

## Decisions

**The status bar carries the responsibility; follow mode is a convenience.** The complaint under items 1
and 2 is that nothing on screen follows the PROCESS - the tree row and the details pane both follow the
cursor. A permanent line at the bottom answers "what is running and for how long" once and keeps
answering it while the operator reads something else, which is strictly more than follow mode does:
follow mode answers it only for an operator who has not navigated away, and navigating away is the case
that produced the complaint. Both are built, the bar first.

**The bar is a pure function of the DISPLAY TREE plus a `now`.** `steps.status_line(root, now)` returns
plain text; `tui.py` writes it into a `Static`. That keeps the whole of the item testable without a
terminal, keeps the wall clock out of the assertion (the `now` is the caller's), and keeps the widget
dumb. The same choice is what makes item 2 provable without a sleep: the elapsed value travels
`Row.elapsed(now) -> format_duration -> the text`, and the test states the `now` it means.

**The bar's four states, and none of them is blank.** A bar that goes empty reads as a broken widget, so
each of the four cases says something:

- *nothing has started* - `waiting to start`, plus the pending count. One frame in practice, but `on_mount`
  paints before the worker thread has entered the first step, so the frame exists.
- *something is running* - the active step's dotted identity and its elapsed time, plus the counts and the
  run's own elapsed.
- *nothing is running and the run is not over* - the LAST step that finished, marked `last:`. Sequential
  execution makes this window narrow, but it is real: the runner marks an aborted subtree SKIPPED one step
  at a time with a repaint between each, and during that stretch no step is RUNNING.
- *the run is over* - the verdict, because that is the last thing an operator reads before pressing `q`,
  and the run's total elapsed.

**The bar's shape survives si#147.** `steps.running_rows(root)` returns a TUPLE and the left half
renders up to two names plus a `+k more` tail. Nothing here supports parallel execution; what it does is
avoid a widget that would have to be rebuilt to show two names. One sentence in the docstring says so.

**The bar names the dotted identity, never the argv.** The same rule and the same reason as `_label`'s
docstring: `package.web-jar` is what the operator is looking for, and `docker run --rm -v ...` is a wall.
The argv stays in the right pane's section header.

**The transcript is written on BOTH paths, headless included.** The artefact's whole purpose is to be
attached to a ticket, and the run that most needs attaching is a red CI run - which is precisely the
headless path. Writing it only under the TUI would produce the file only on the machine where the operator
could already read the screen. It costs CI one file under `build/`, which `clean` removes, and it degrades
to nothing when no product context is registered, exactly as `steplog.write` already does. So both
`run_headless` and `run_pipeline` call one shared writer, and `run_pipeline` calls it AFTER `app.run()`
returns so that a run the operator quit half way through still leaves a transcript of what did happen.

**The transcript extends `steplog`, it does not open a second store.** `steplog` already owns
`<repo>/build/logs/`, the context lookup, the name sanitising and the "a courtesy that raises is a defect"
rule. It gains `write_run` (the file) and `run_header` (the four header facts). The BODY is rendered in
`steps.py`, because that is the module that knows what a `Pipeline` is - `steplog` importing `steps` would
close a cycle, since `steps` imports `steplog`.

**The transcript file is `build/logs/run-transcript.log`.** One file, overwritten per run, beside the
per-step logs and under the same `clean`. A step whose identity normalises to `run-transcript` would
overwrite it; that collision is accepted and documented rather than defended with a second directory,
because a second directory is a second thing to explain and to clean.

**Item 4 reuses si#125's line rather than reimplementing it.** `cli._provenance()` is renamed to
`cli.provenance_line()` and called by `steplog.run_header`. The import is function-local, and that is not
style: `cli` imports `orchestrator.product`, which imports `steps`, which imports `steplog`, so a
module-level import would close a cycle. `provenance_line` is chosen over the bare `provenance` because
`simplon.tasks.image.provenance` already means the git provenance of an image.

**The environment reaches the header through a kernel-owned variable.** The active environment is known in
exactly one place, `cli.main`, which already does `os.environ[environments.ENV_VAR] = env` - and that
variable's NAME is the product's, so no kernel leaf can read it back. `main` therefore also exports
`context.ENVIRONMENT_ENV` (`DELIVERY_ENVIRONMENT`), one line beside the existing export, in the kernel's
own `DELIVERY_*` namespace next to `DELIVERY_PRODUCT_ROOT` and `DELIVERY_MANIFEST`. It also reaches child
processes, which matters the moment a step is itself a product command. A pipeline run outside `main` (a
test, a scaffolder) finds it unset and the header says `not set` rather than guessing.

**Every header field degrades to a phrase, never to an exception.** `labinstance.resolve()` raises when the
manifest declares no `instance:` section - simplon's own manifest does not declare one - and a transcript
that refuses to be written because the run had no lab is a courtesy that raises. Same rule as
`steplog.write` and `cli._install_marker`.

**Item 2's running duration is spelled `12.0s…` and a finished one `12.0s`.** One character, and it says
"still counting" so a running row cannot be misread as a finished one. `format_duration` stays the one
spelling of the number itself.

**Colour: three colours, two dims, and the glyphs stay.** Five states, three colours - the mapping and its
argument:

| state | style | why |
|-------|-------|-----|
| OK | `$success` | the obvious one |
| FAILED | `$error` + **bold** | the whole point of the item is a failure findable in a tree of forty |
| RUNNING | `$warning` | amber is "in flight, outcome unknown", and it is the row an operator hunts for while the run is live |
| SKIPPED | `$warning` dimmed | it did not run, which is the same *unknown outcome* sense one brightness down - and it must not compete with the failure that caused it |
| PENDING | dim, no colour | nothing has happened yet; a colour here would spend attention on the rows that carry no information |

Additive, never sole: `STATE_ICON` is untouched and every row keeps its glyph. And the colour is applied
where the widget is rendered - `_label` keeps returning `str`, so `_painted` goes on comparing CONTENT,
`_row` goes on returning text a test can assert, and neither `render_tree` (the headless rows) nor the
transcript can acquire markup, because neither ever sees the styled object.

**No F1 help panel.** `_step_header` already renders the manifest's own `help:` for the entered step, and
measurement (c) shows the command palette already ships `Keys`, a panel with help for the focused widget
and a summary of the bindings. An F1 binding would be a second door to a panel Textual opens, spending a
footer slot on it.

## Automated verification

- [ ] `./simplon.sh test all` - 2730 passed on `origin/main` before this work, with 4 known failures
      (3 in `test_tasks_docs.py`, which this box produces by running as root, and
      `test_releases_page.py::test_every_ticket_merged_into_a_release_is_named_in_its_section`). No new
      failure, and the new tests counted in.
- [ ] `./simplon.sh test typecheck-python` - clean, as it was before (84 source files).
- [ ] Every new test drives `App.run_test()` and asserts what a pane or the bar CONTAINS. No test sleeps.

## Manual verification

- [ ] `./simplon.sh build docs` on a TTY: the bar names the running step while the cursor sits elsewhere,
      a failed row is red at a glance, `ctrl+p` lists the new actions and the theme picker.

---

## Task 1: the pure half of the status bar (item 8) and the live elapsed (item 2)

**Files:** `src/simplon/orchestrator/steps.py`, `tests/test_orchestrator_status.py` (a new file rather than
`test_orchestrator_rows.py`, whose docstring scopes it to the display TREE - the bar is not that)

- [x] 1.1 Write failing tests for `Row.elapsed(now)`: a finished row answers its duration; a RUNNING row
      answers `now - started_at`; a PENDING row and a SKIPPED row answer `None`; a running AGGREGATE
      answers `now - <its first child's start>`. Watch them fail on `AttributeError`.
- [x] 1.2 Implement `Row.elapsed(now: float) -> float | None`. It delegates to `duration` when there is
      one and never invents a zero, for the reason `duration`'s docstring gives.
- [x] 1.3 Write failing tests for `RunSummary` / `summarise(root)`: counts per state, and a `counts`
      text that omits the zero categories.
- [x] 1.4 Implement them.
- [x] 1.5 Write failing tests for `running_rows(root) -> tuple[Row, ...]`: empty before the run,
      one entry while a step runs, TWO entries when two steps are RUNNING (the si#147 shape, constructed
      by hand - nothing runs them in parallel).
- [x] 1.6 Implement it.
- [x] 1.7 Write failing tests for `status_line(root, now)`, one per state: waiting, running (carries
      the dotted identity, the elapsed with its `…`, the counts and the run elapsed), the gap (`last:`),
      done-green (the verdict), done-red (the verdict, the failure count, the skipped count). Plus: a step
      whose `command` is an argv is rendered by its LABEL, and three running steps render as two names
      plus `+1 more`.
- [x] 1.8 Implement `status_line`.

**Verify:** `pytest tests/test_orchestrator_rows.py` green; no sleep anywhere; `mypy` clean.

## Task 2: the status bar widget (item 8) and the ticking row (item 2)

**Files:** `src/simplon/orchestrator/tui.py`, `tests/test_orchestrator_tui.py`

- [x] 2.1 Failing test: run a pipeline whose first step blocks on an event the test sets, move the cursor
      to a DIFFERENT row entirely, and assert the bar still names the running step and its elapsed time.
      This assertion is the feature.
- [x] 2.2 Failing test: after the run, the bar carries the verdict.
- [x] 2.3 Implement: a `Static#status` docked above the `Footer`, repainted from `steps.status_line` by
      `_repaint_status()`, called on mount, on every step transition, and from a `set_interval(1.0, ...)`
      tick.
- [x] 2.4 Failing test for the ticking ROW label: freeze `steps_mod.clock` at 0, start a step, advance the
      frozen clock to 12.0, call the tick, assert the row reads `12.0s…`. No sleep.
- [x] 2.5 Implement `_label`'s running branch via `Row.elapsed(clock())`.
- [x] 2.6 Failing test: the bar's CSS class follows the run's derived state (`-running`, `-failed`, `-ok`).
- [x] 2.7 Implement the class swap.

**Verify:** `pytest tests/test_orchestrator_tui.py` green; the existing TUI tests still green (the frozen
clock fixture already covers the new label branch).

## Task 3: the run transcript (items 3 and 4)

**Files:** `src/simplon/orchestrator/steps.py`, `src/simplon/steplog.py`, `src/simplon/context.py`,
`src/simplon/cli.py`, `tests/test_steplog.py`, `tests/test_orchestrator_steps.py`

- [x] 3.1 Failing test for `steps.transcript(pipeline, header)`: a three-step pipeline with one failure
      renders every step IN ORDER, each with its rc and its duration, the failure's output, and the header
      lines above them. Assert the content, not the call.
- [x] 3.2 Implement `transcript`. Pure: it takes the header lines and returns lines.
- [x] 3.3 Failing test for `steplog.run_header(name, started)`: it carries the run's start time, the
      environment, the instance and the simplon provenance line; and with no product context / no
      `instance:` section / no `DELIVERY_ENVIRONMENT` it says so in words instead of raising.
- [x] 3.4 Rename `cli._provenance` to `cli.provenance_line` and update its one call site. Add
      `context.ENVIRONMENT_ENV` and export it from `cli.main` beside the product's own variable.
- [x] 3.5 Implement `run_header` and `steplog.write_run`.
- [x] 3.6 Failing test: `run_headless` over a real multi-step pipeline writes
      `build/logs/run-transcript.log`, and its content carries the header and every step. Failing test:
      the TUI path writes the same file.
- [x] 3.7 Implement `steps.write_run_transcript(pipeline, started, now=None)` and call it from
      `run_headless` and from `run_pipeline`.
- [x] 3.8 Test: no markup, no ANSI escape in the written file (the shared-`STATE_ICON` constraint).

**Verify:** `pytest tests/test_steplog.py tests/test_orchestrator_steps.py` green.

## Task 4: follow mode (item 1), next failure and filter (item 5)

**Files:** `src/simplon/orchestrator/tui.py`, `tests/test_orchestrator_tui.py`

- [x] 4.1 Failing test: start a step, assert the cursor moved to it; move the cursor by hand, assert it
      stops following the next step; press `f`, assert it follows again.
- [x] 4.2 Implement follow mode with a `_moving` guard around the programmatic `move_cursor`, so a
      `NodeHighlighted` the app caused is not mistaken for manual navigation.
- [x] 4.3 Failing test: a run with failures scattered among passes; press `n` repeatedly and assert where
      the cursor lands each time, including the wrap.
- [x] 4.4 Implement `action_next_failure`.
- [x] 4.5 Failing test: press `/`, type a substring, assert exactly which rows remain (matching rows and
      the ancestors that carry them, nothing else); press escape, assert the full tree is back and the
      cursor is on a sensible row.
- [x] 4.6 Implement the filter by remounting the tree through `_mount_tree(keep=...)`.
- [x] 4.7 Test: the run keeps painting correctly THROUGH a filter - refresh a row while a filter hides it
      and assert nothing raises and the row is right when the filter clears.

**Verify:** `pytest tests/test_orchestrator_tui.py` green.

## Task 5: the details pane's scroll (item 6)

**Files:** `src/simplon/orchestrator/tui.py`, `tests/test_orchestrator_tui.py`

- [ ] 5.1 Failing test that PROVES measurement (a) on the widget: write enough lines to scroll, scroll up,
      write one more line, assert the offset did not move. Watch it fail against today's `auto_scroll`.
- [ ] 5.2 Implement the sticky bottom: `auto_scroll=False` on the `RichLog`, and `_on_line` captures
      `is_vertical_scroll_end` before the write and calls `scroll_end` only when the reader was there.
- [ ] 5.3 Failing test: scroll the pane, switch rows, switch back, assert the position survived.
- [ ] 5.4 Implement the per-row scroll memory, keyed by `id(row)`, saved when leaving a row.

**Verify:** `pytest tests/test_orchestrator_tui.py` green, including 5.1 which was red for the right
reason first.

## Task 6: colour (item 7) and the command palette (item 9)

**Files:** `src/simplon/orchestrator/tui.py`, `tests/test_orchestrator_tui.py`

- [ ] 6.1 Failing test: query the rendered tree and assert a FAILED row's label carries the theme's error
      colour and a bold style, an OK row the success colour, a PENDING row no colour.
- [ ] 6.2 Failing test, the other half: `render_tree` (headless) and the transcript carry NO markup and no
      escape for the same pipeline.
- [ ] 6.3 Implement `_styled(row)` off `self.current_theme`, applied at `Tree.add` / `set_label`, with
      `_label` still returning `str` so `_painted` compares content.
- [ ] 6.4 Failing test: changing the theme repaints the rows in the new theme's colours.
- [ ] 6.5 Implement the theme watcher.
- [ ] 6.6 Failing test: the command palette lists every action this change adds.
- [ ] 6.7 Implement `get_system_commands`.

**Verify:** `pytest tests/test_orchestrator_tui.py` green; both halves of 6.2 asserted.

## Task 7: the footer, the docs and the review

**Files:** `src/simplon/orchestrator/tui.py`, `site/content/using/examples.md`

- [ ] 7.1 Test: every new binding appears in the footer.
- [ ] 7.2 Extend `examples.md` section 3 with the keys, the bar and the transcript.
- [ ] 7.3 `./simplon.sh test all` and `./simplon.sh test typecheck-python`; compare against the baseline.
- [ ] 7.4 Dispatch `python-reviewer` on the diff; act on what it finds.
- [ ] 7.5 Open the PR against `main`, no labels, and update the ticket body with items 7-9.
