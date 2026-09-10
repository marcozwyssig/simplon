# Output arrives when it happens - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A step's output reaches the reader while the step is producing it - the pane no longer freezes
for eleven seconds while the child is writing - and a row highlighted mid-run shows what that step has
already said instead of an empty pane.

**Architecture:** Two changes, one per mechanism, and neither is a pty. `run_stream` stops iterating
lines and reads CHUNKS, splitting on `\r` and `\n` and handing over a pending partial line when the child
goes quiet for `LIVE_FLUSH` seconds - the measured cause of the burst is a write that never terminates a
line, not buffering. `Step` exposes the line list `argv_step` already fills, so the details pane can
render a running step's backlog out of the one buffer that exists rather than out of a second copy.

**Tech Stack:** Python 3.11+, Textual 8.2.8 (pinned `>=8.2.8,<9`), pytest, mypy. No new dependency, no
new catalogue coordinate, no pty.

**Spec:** [si#144](https://github.com/marcozwyssig/simplon/issues/144). Related:
[si#148](https://github.com/marcozwyssig/simplon/issues/148) / PR #151, which built follow mode, the
status bar and the sticky-bottom `RichLog`, and which defused mechanism A for the common case without
removing it; [si#143](https://github.com/marcozwyssig/simplon/issues/143), whose capture rule
`run.py`'s docstring records; [si#142](https://github.com/marcozwyssig/simplon/issues/142), whose own
progress bar shares the pane.

## Global Constraints

- English prose, Swiss spelling (`ss`, never `ß`), no em dashes in prose.
- Docstrings argue WHY and carry the measurement that decided the shape.
- `steplog`'s per-step logs and si#148's `build/logs/run-transcript.log` stay MARKUP-FREE. The existing
  assertions on that (`tests/test_orchestrator_transcript.py`) stay green rather than being adjusted.
- The headless path (`run_headless`, taken whenever stdout is not a TTY) stays clean and complete: CI
  depends on it.
- No new catalogue coordinate.
- The release notes gain an entry naming si#144 (`test:release-notes` refuses a merged ticket the notes
  do not name).
- Every new assertion is seen RED before it is seen green.

---

## The measurements this plan rests on

Made on this machine on 2026-09-10, against `origin/main` at `b1291ca`, with a three-mode harness: the
child read exactly as `run_stream` reads it today (`pipe-lines`), the same pipe read with `os.read` in
chunks (`pipe-raw`, which shows what the child actually WROTE and when), and the child on a
`pty.openpty()` (`pty-raw`). If `pipe-raw` arrives steadily while `pipe-lines` does not, the reader is
the cause; if `pipe-raw` itself arrives only at the end, the child's buffering is.

### (a) The dominant cause is a write that does not terminate a line

`./simplon.sh test all`, which is simplon's own longest step and the one an operator watches:

| read as | units delivered | bytes | first at | worst silence |
|---|---|---|---|---|
| `pipe-lines` (today) | 126 | 8280 | 1.40s | **11.30s** |
| `pipe-raw` | 2865 | 8280 | 0.68s | 6.82s |

The child wrote 2865 times and the reader handed over 126 times. pytest writes ONE DOT per test and
flushes it; the dots become a line only every 72 tests. Per BYTE, from the child's write to the
`on_line` call:

| policy | max | mean | median |
|---|---|---|---|
| today: split on newline/CR only | **11.37s** | 0.203s | 0.000s |
| quiet flush 0.05s | 0.65s | 0.025s | 0.000s |
| **quiet flush 0.10s** | **1.50s** | **0.032s** | 0.000s |
| quiet flush 0.20s | 1.76s | 0.045s | 0.000s |
| quiet flush 0.50s | 4.59s | 0.066s | 0.000s |

and the cost of the flush, in segments the step log gains for the same 8280 bytes: 126 today, 190 at
0.10s, 159 at 0.20s, 210 at 0.05s. **0.10s is the choice**: it cuts the worst wait by 7.6x for 64 extra
lines in one step's log. The residual ~7s is the child's own silence (pytest collecting), which no
reader can shorten.

### (b) The ticket's top candidate is wrong about `\r`, and the code already says so

`run_stream` passes `text=True`, which turns on Python's universal newlines, and `\r` IS a line
terminator for `readline`. Measured three ways:

| child | CRs into a pipe | lines `for line in proc.stdout` yielded |
|---|---|---|
| a shell writing `downloading N%\r` every 200ms | 15 | 16, one every 200ms, none late |
| `curl --progress-bar` (2 MB over HTTPS) | 9 | 11, first at 0.21s |
| `git clone --progress` (oras-project/oras) | 405 | 412 |

So a carriage return never DELAYS anything here - it does the opposite, it explodes a bar into a page,
which is what `run.py`'s own docstring already records (`the caller receives ['a  17%', 'b 100%']`). The
ticket is right that the reader is the defect and right about the shape - a write that does not
terminate a line is not delivered - and wrong about which terminator is missing. It is the un-terminated
TAIL, not the carriage return.

### (c) Child-side block buffering is not present in this toolbox

| child | pipe: first byte | pipe: delivered as written | pty: bytes | pty: CRs |
|---|---|---|---|---|
| `docker pull debian:bookworm-slim` (cold) | 1.69s | yes | 267 | 7 |
| `docker build --no-cache` (3 layers, 6.5s) | 0.25s | yes | 37196 | 397 |
| `curl --progress-bar` | 0.13s | yes | 722 | 10 |
| `git clone --progress` | 0.00s | yes | 17481 | 412 |
| `oras push` (300 MB, local registry) | 0.00s | yes | 2774 | 33 |
| `containerlab version check` | 0.11s | yes | 323 | 5 |
| `gh release download` | - | **writes nothing at all** | 723 | 27 |
| `./simplon.sh test all` | 0.68s | yes | 37502 | 126 |
| a Python child WITHOUT `-u` | 3.01s (at exit) | **no** | - | - |
| the same child under `stdbuf -oL` | 3.01s (at exit) | **no** | - | - |

Not measured, because neither is installed on this machine: `gradle` and `dotnet`. Both are reached
through `docker run` in this kernel's own profiles, so the pipe they write to is docker's, and docker is
in the table.

The only child that block-buffered was Python without `-u`, and simplon spawns none: `simplon.sh` execs
`python -u -m <module>` and `StepFactoryContext.for_module` builds `[sys.executable, "-u", "-m", ...]`.

### (d) `stdbuf -oL` is useless here, and a pty costs more than it buys

`stdbuf -oL python3 <child>` still delivered everything at exit, identical to without it: `stdbuf`
preloads a libc that sets libc STDIO's buffering mode, and Python's `io` is not libc stdio - nor is Go's
`os.Stdout`, which is docker, containerlab, oras and gh. Confirmed, then dropped.

A pty fixes exactly one row of table (c) - `gh`, which writes nothing to a pipe by its own TTY check -
and pays for it everywhere else: `docker build` goes from 822 bytes to 37196 (45x) with 397 carriage
returns, `oras push` from 444 to 2774 with 33. Every one of those bytes lands in `steplog`'s file and
in si#148's run transcript, which is the artefact somebody attaches to a ticket. Rejected. `gh`'s
silence is a per-tool fact for a per-tool answer on the day a step needs it, not a reason to reshape
every step's log.

## File structure

| File | Responsibility | Change |
|---|---|---|
| `src/simplon/run.py` | the subprocess seam | `run_stream` becomes a chunk reader with a quiet flush |
| `src/simplon/orchestrator/steps.py` | the step model | `Step.live` + `Step.shown_output`; `argv_step` hands its list over |
| `src/simplon/orchestrator/tui.py` | the Textual panes | the two renderers read `shown_output` |
| `tests/test_run.py` | the reader's own proof | `\r` / `\n` / partials / ordering / a real child |
| `tests/test_orchestrator_steps.py` | the model's proof | a running step's backlog |
| `tests/test_orchestrator_tui.py` | the pane's proof | highlight a different row, come back, read the backlog |
| `site/content/using/releases.md` | the notes | a `### ...(si#144)` section under `## 0.10.0` |

## Decisions

**Mechanism A is fixed by exposing the list that already exists, not by tailing the log file.** The
ticket asks for the second and asks for the choice to be argued. `argv_step` already keeps every line
in a local `lines: list[str]`; the Step is built two lines later, so handing that SAME list to the Step
adds no copy at all - `Step.live` is the list, by reference. Tailing `build/logs/<step>.log` instead
would add file I/O to the render path and, more to the point, would leave mechanism A UNFIXED in exactly
the cases the ticket cares about: `steplog.write` returns `None` when no product context is registered
(`log_directory()` catches the `RuntimeError`) or when the directory is unwritable, and the pane would
then have nothing to read. A backlog that disappears on a read-only checkout is not a backlog.

**One reader, one behaviour, headless included.** The quiet flush is not switched off for
`run_headless`. A knob would be a second behaviour to explain and a second one to test, and the cost of
not having it is measured and small: `test all` prints 190 indented lines in CI instead of 126, all of
them dot-runs, all markup-free.

**A thread, not `select`.** `select.select` accepts only sockets on Windows, and this kernel runs there
- `simplon.cmd` exists and `StepFactoryContext.for_module`'s docstring records cleon's Windows cell dying
on `WinError 193`. A one-line pump thread doing blocking `os.read` into a `queue.Queue` is portable, and
it keeps `on_line` on the caller's own thread, which is what the TUI's `call_from_thread` contract
assumes.

**EOF still ends the read, not `proc.poll()`.** Today `for line in proc.stdout` runs until the pipe
closes, so a step whose child spawns something that inherits stdout waits for that too. Ending the loop
on `poll()` would change that silently. The loop ends on a zero-length read and nowhere else.

**An incremental UTF-8 decoder.** Reading arbitrary chunk boundaries can cut a multi-byte character in
half; `text=True` used to handle that. `codecs.getincrementaldecoder("utf-8")("replace")` keeps the
half-character until its second half arrives, and the state icons (`▶`, `✓`, `⊘`) that steps echo are
exactly such characters.

---

### Task 1: The reader hands over what has arrived

**Files:**
- Modify: `src/simplon/run.py:110-127` (`run_stream`)
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `run.LIVE_FLUSH: float = 0.1`; `run_stream(argv: list[str], on_line: Callable[[str], None],
  *, flush_after: float = LIVE_FLUSH) -> int`. `on_line` receives one SEGMENT: the text between two line
  breaks (`\n`, `\r` or `\r\n`), or the pending partial when the child has written nothing for
  `flush_after` seconds, or the remainder at EOF. No terminator is included, and no segment is empty
  except one produced by a genuinely empty line.

- [x] **Step 1: Write the failing tests**

In `tests/test_run.py`, after the existing two `run_stream` tests:

```python
def test_run_stream_hands_over_a_partial_line_when_the_child_goes_quiet():
    """The measured defect (si#144): pytest writes one dot per test and the line completes every 72 of
    them, so `for line in proc.stdout` froze the pane for up to 11.3 seconds while the child was writing
    every few milliseconds. A reader that waits for the terminator is the whole of it."""
    # arrange: a child that writes an unterminated run of dots, pauses, then finishes the line
    seen = []
    argv = ["sh", "-c", "printf '...'; sleep 0.5; printf '... [100%%]\\n'"]

    # act
    rc = run_stream(argv, seen.append, flush_after=0.05)

    # assert: the first three dots arrived on their own, before the line was ever terminated
    assert rc == 0
    assert seen == ["...", "... [100%]"]


def test_run_stream_splits_on_a_carriage_return_as_well_as_a_newline():
    # arrange: a progress repaint, which terminates nothing
    seen = []

    # act
    rc = run_stream(["sh", "-c", "printf 'a  17%%\\rb 100%%\\n'"], seen.append)

    # assert
    assert rc == 0
    assert seen == ["a  17%", "b 100%"]


def test_run_stream_treats_crlf_as_one_break():
    # arrange: a Windows-ending child, which must not produce an empty segment between the two bytes
    seen = []

    # act
    run_stream(["sh", "-c", "printf 'one\\r\\ntwo\\r\\n'"], seen.append)

    # assert
    assert seen == ["one", "two"]


def test_run_stream_keeps_a_multibyte_character_whole_across_a_chunk_boundary():
    """Chunked reading can cut a UTF-8 character in half, which `text=True` used to prevent. The step
    icons this kernel echoes (▶ ✓ ⊘) are exactly such characters."""
    # arrange: the two halves of one character, written 0.2s apart, so they land in different reads
    seen = []
    argv = ["python3", "-c",
            "import sys,time; b='✓'.encode(); sys.stdout.buffer.write(b[:1]); sys.stdout.buffer.flush();"
            " time.sleep(0.2); sys.stdout.buffer.write(b[1:]+b'\\n'); sys.stdout.buffer.flush()"]

    # act
    run_stream(argv, seen.append, flush_after=0.05)

    # assert: one whole character, never two replacement marks
    assert "".join(seen) == "✓"


def test_run_stream_emits_the_last_line_when_the_child_never_terminates_it():
    # arrange
    seen = []

    # act
    rc = run_stream(["sh", "-c", "printf 'no newline here'; exit 3"], seen.append)

    # assert
    assert (rc, seen) == (3, ["no newline here"])
```

- [x] **Step 2: Run them and watch them fail**

Run: `cd /tmp/wt-144 && deploy/orchestrator/.venv/bin/python -m pytest tests/test_run.py -x -q`
Expected: FAIL. `test_run_stream_hands_over_a_partial_line_when_the_child_goes_quiet` gets
`['...... [100%]']` (one segment, the dots held until the line ended) and
`test_run_stream_splits_on_a_carriage_return_as_well_as_a_newline` PASSES already - universal newlines
does that today, which is measurement (b). Keep it: it is the assertion that the rewrite must not lose.

- [x] **Step 3: Rewrite `run_stream`**

Replace the body of `run_stream` in `src/simplon/run.py` (imports `codecs`, `os`, `queue`, `re`,
`threading` at the top of the module):

```python
#: How long the reader waits for a line to FINISH before handing over what it already has.
#:
#: The measurement that chose it (si#144), on `./simplon.sh test all` - simplon's own longest step:
#: pytest writes one dot per test and flushes it, and the line completes every 72 tests, so the 2865
#: writes reached `on_line` as 126 lines and a byte waited up to 11.37s. With this flush the worst wait
#: is 1.50s and the mean falls from 0.203s to 0.032s. The price is paid in the step log, in lines the
#: child did not end itself: 126 -> 190 for that step. 0.05s buys 0.65s worst for 210 lines, 0.20s
#: gives 1.76s for 159. This is the knee.
LIVE_FLUSH = 0.1

#: A line break as a child writes one: CRLF first, so a Windows ending is ONE break rather than a break
#: and an empty line. A bare `\r` is a repaint, and it ends a segment for the same reason a newline does
#: - what came before it is finished text that a reader can see.
_BREAK = re.compile(r"\r\n|\r|\n")


def run_stream(argv: list[str], on_line: Callable[[str], None],
               *, flush_after: float = LIVE_FLUSH) -> int:
    """Run `argv` and feed each output SEGMENT (stdout+stderr merged) to `on_line` AS IT IS PRODUCED,
    then return the real exit code. This is what lets the TUI show a long step's output live
    (build/up/seed) instead of only on completion.

    A SEGMENT, not a line, and that is the whole of si#144. `for line in proc.stdout` hands over on a
    terminator, and the tools here write output that has none yet: pytest writes one dot per test and
    completes the line every 72 of them. Measured on `./simplon.sh test all`, the child wrote 2865 times
    and the reader handed over 126 times, with a byte waiting up to 11.37 seconds - the pane frozen for
    eleven seconds while the child was writing every few milliseconds. So this reads CHUNKS, splits on
    `\\r` and `\\n`, and when the child has written nothing for `flush_after` seconds it hands over the
    partial line it is holding. The same measurement after: 1.50s worst, 0.032s mean.

    What it is NOT is a pty. A pty is the general answer to a child that BLOCK-BUFFERS, and no child
    here does: docker, containerlab, oras, curl, git and this kernel's own `python -u` child all
    deliver as they write into a plain pipe. What a pty would add is 45x the bytes and 397 carriage
    returns on a `docker build`, into `steplog`'s file and into the run transcript somebody attaches to
    a ticket.

    A PUMP THREAD rather than `select`, because `select.select` accepts only sockets on Windows and this
    kernel runs there. It reads bytes and nothing else; `on_line` stays on the CALLER's thread, which is
    what the TUI's `call_from_thread` assumes. The loop ends on a zero-length read and not on
    `proc.poll()`: today's reader runs until the pipe closes, so a child that hands stdout to something
    it spawned is still waited for, and ending on the exit status would drop that output silently.
    """
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    chunks: "queue.Queue[bytes]" = queue.Queue()

    def pump() -> None:
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b""
            chunks.put(chunk)
            if not chunk:
                return

    thread = threading.Thread(target=pump, name="run_stream", daemon=True)
    thread.start()
    # An INCREMENTAL decoder: a chunk boundary can fall inside a multi-byte character, which `text=True`
    # used to hide. `errors="replace"` keeps the old contract - output is shown, never raised on.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending = ""
    while True:
        try:
            chunk = chunks.get(timeout=flush_after)
        except queue.Empty:
            if pending:                       # the child went quiet holding an unfinished line
                on_line(pending)
                pending = ""
            continue
        if not chunk:
            break
        pending += decoder.decode(chunk)
        parts = _BREAK.split(pending)
        pending = parts.pop()                 # whatever follows the last break is not finished yet
        for part in parts:
            on_line(part)
    pending += decoder.decode(b"", True)
    if pending:
        on_line(pending)
    thread.join()
    proc.stdout.close()
    return proc.wait()
```

- [x] **Step 4: Run the tests and watch them pass**

Run: `cd /tmp/wt-144 && deploy/orchestrator/.venv/bin/python -m pytest tests/test_run.py -q`
Expected: PASS, all of them, including the two that existed before.

- [x] **Step 5: See the new assertions red**

Temporarily set `flush_after`'s default to `10**9` and re-run: the quiet-flush test must fail with
`['...... [100%]']`. Temporarily change `_BREAK` to `re.compile(r"\n")`: the carriage-return test must
fail. Restore both.

- [x] **Step 6: Prove it against a REAL long-running child, with the timing**

Run, and record both numbers in the commit message:

```bash
cd /tmp/wt-144 && deploy/orchestrator/.venv/bin/python - <<'PY'
import time
from simplon.run import run_stream
t0 = time.perf_counter(); at = []
run_stream(["./simplon.sh", "test", "all"], lambda line: at.append(time.perf_counter() - t0))
gaps = [b - a for a, b in zip(at, at[1:])]
print(f"segments={len(at)} first={at[0]:.2f}s worst silence={max(gaps):.2f}s")
PY
```

Expected: `first` around 0.7-1.0s (was 1.40s) and `worst silence` around 7s (was 11.30s), with roughly
190 segments (was 126).

- [x] **Step 7: Commit**

```bash
git add src/simplon/run.py tests/test_run.py
git commit -F - <<'MSG'
fix(#144): a segment is what arrived, not what ended in a newline
...
MSG
```

---

### Task 2: A running step carries its backlog

**Files:**
- Modify: `src/simplon/orchestrator/steps.py` (`Step`, `argv_step`)
- Test: `tests/test_orchestrator_steps.py`

**Interfaces:**
- Consumes: `run_stream` from Task 1.
- Produces: `Step.live: list[str]` (the segments produced SO FAR, filled by the streaming action;
  empty for an `action` step) and `Step.shown_output -> str` (`self.output` once the step has finished,
  else `"\n".join(self.live)`). `argv_step` passes its own collector list as `live=`.

- [x] **Step 1: Write the failing tests**

In `tests/test_orchestrator_steps.py`:

```python
def test_a_running_step_shows_the_lines_it_has_already_produced():
    """Mechanism A of si#144: `Outcome.output` is built after the action RETURNS, so a step highlighted
    while it runs had nothing to show however much it had printed. si#148's follow mode moved the cursor
    to the running step and left this exactly as it was for a reader who navigates."""
    # arrange: a stream action that reports what the step can show while it is still inside the action
    seen = {}

    def action(emit):
        emit("first")
        emit("second")
        seen["mid_run"] = step.shown_output
        return Outcome(rc=0, output="first\nsecond")

    step = Step(label="long", stream=action, live=[])

    # act
    step.run()

    # assert
    assert seen["mid_run"] == ""      # nothing yet: the plain Step keeps no buffer of its own
    assert step.shown_output == "first\nsecond"


def test_argv_step_lets_the_pane_read_a_running_step_s_output():
    # arrange: a fake run_stream that reports the step's backlog from inside the run
    seen = {}
    step_holder = {}

    def fake_run_stream(argv, on_line, **kwargs):
        on_line("compiling")
        on_line("linking")
        seen["mid_run"] = step_holder["step"].shown_output
        return 0

    monkeypatch.setattr(steps, "run_stream", fake_run_stream)
    step = argv_step("build", ["make"], command="build.compile")
    step_holder["step"] = step

    # act
    step.run()

    # assert: the pane could have rendered both lines before the process exited
    assert seen["mid_run"] == "compiling\nlinking"
    assert step.shown_output == "compiling\nlinking"


def test_a_re_run_step_does_not_show_the_previous_run_s_lines():
    # arrange
    calls = []

    def fake_run_stream(argv, on_line, **kwargs):
        on_line(f"run {len(calls)}")
        calls.append(1)
        return 0

    monkeypatch.setattr(steps, "run_stream", fake_run_stream)
    step = argv_step("build", ["make"], command="build.compile")

    # act
    step.run()
    step.run()

    # assert
    assert step.shown_output == "run 1"
```

(The two `monkeypatch` tests take `monkeypatch` as a parameter; `steps` is the module already imported
by that file. Use the file's existing `_no_steplog` arrangement so nothing is written to `build/logs/`.)

- [x] **Step 2: Run them and watch them fail**

Run: `cd /tmp/wt-144 && deploy/orchestrator/.venv/bin/python -m pytest tests/test_orchestrator_steps.py -x -q -k "backlog or running or re_run"`
Expected: FAIL with `TypeError: Step.__init__() got an unexpected keyword argument 'live'`.

- [x] **Step 3: Add the field and the property**

In `src/simplon/orchestrator/steps.py`, in `Step`, after `output`:

```python
    # The segments this step has produced SO FAR, filled by the streaming action as they arrive. THE
    # SAME LIST the action collects into, handed over by reference at construction (see `argv_step`) -
    # not a copy, and not a second buffer kept for the pane alone.
    #
    # It exists because `Outcome.output` is only built after the action RETURNS (si#144, mechanism A):
    # a row highlighted while its step was running showed `(running…)` however much the step had
    # printed, and the lines that went by while another row was selected were gone. si#148's follow mode
    # moved the cursor to the running step, which covers the operator who touches nothing and leaves
    # this exactly as it was for the one who navigates.
    #
    # The alternative the ticket names is to write `steplog` incrementally and let the pane tail the
    # file. Rejected: `steplog.write` returns None with no product context registered and on an
    # unwritable checkout, so the backlog would be missing in exactly the degraded cases, and the pane
    # would take file I/O into its render path to get it.
    live: list[str] = field(default_factory=list)

    @property
    def shown_output(self) -> str:
        """What a reader should see: the finished output, or the segments produced so far while it runs.

        `output` wins once it is set, because it is the action's own last word - an action that returns
        a different text than it streamed (a summary, a captured stderr) means that text."""
        return self.output or "\n".join(self.live)
```

In `argv_step`, hand the collector over and clear it per run:

```python
    lines: list[str] = []

    def stream(emit: Emit) -> Outcome:
        lines.clear()      # a Step can be run twice; the pane must not show the previous run's output

        def on_line(line: str) -> None:
            lines.append(line)
            emit(line)

        rc = run_stream(argv, on_line)
        output = "\n".join(lines)
        steplog.write(identity, output)
        return Outcome(rc=rc, output=output)
    return Step(label=label, stream=stream, live=lines, command=identity, help=help)
```

- [x] **Step 4: Run the tests and watch them pass**

Run: `cd /tmp/wt-144 && deploy/orchestrator/.venv/bin/python -m pytest tests/test_orchestrator_steps.py -q`
Expected: PASS.

- [x] **Step 5: See it red**

Temporarily change `shown_output` to `return self.output`: the two backlog tests must fail with `''`.
Temporarily drop `lines.clear()`: the re-run test must fail with `'run 0\nrun 1'`. Restore both.

- [x] **Step 6: Commit**

```bash
git add src/simplon/orchestrator/steps.py tests/test_orchestrator_steps.py
git commit -F - <<'MSG'
fix(#144): a running step carries the lines it has already produced
...
MSG
```

---

### Task 3: The pane renders the backlog

**Files:**
- Modify: `src/simplon/orchestrator/tui.py` (`_details_text`, `_render_details`)
- Test: `tests/test_orchestrator_tui.py`

**Interfaces:**
- Consumes: `Step.shown_output` from Task 2.
- Produces: nothing new. `_details_text` and `_render_details` read `step.shown_output` where they read
  `step.output`; `c` and `s` therefore copy and save a running step's backlog too.

- [x] **Step 1: Write the failing test**

In `tests/test_orchestrator_tui.py`, the proof the ticket asks for - a DIFFERENT row highlighted while
the step produces output, then its own:

```python
def test_a_row_highlighted_mid_run_shows_what_the_step_has_already_produced():
    """si#144 mechanism A, and the test the ticket specifies: run a step that produces output slowly,
    keep a different row highlighted while it does, then highlight the step's row and read the pane.

    si#148's follow mode covers the operator who touches nothing. This is the one who navigated away."""
    import threading

    released = threading.Event()
    arrived = threading.Event()

    def slow(emit):
        emit("compiling one")
        emit("compiling two")
        arrived.set()
        released.wait(5)
        return Outcome(rc=0, output="compiling one\ncompiling two\ndone")

    pipeline = Pipeline("smoke", [
        Step(label="slow", command="build.compile", stream=slow, live=[]),
        Step(label="after", command="deploy.up", action=lambda: Outcome(rc=0, output="up")),
    ])

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await asyncio.get_running_loop().run_in_executor(None, arrived.wait, 5)
            _focus_line(app, 2)                 # the OTHER row, while the first step is still running
            await pilot.pause()
            _focus_line(app, 1)                 # back to the running step
            await pilot.pause()
            mid_run = _details(app)
            released.set()
            await app.workers.wait_for_complete()
            return mid_run

    # act
    rendered = asyncio.run(_drive())

    # assert
    assert "compiling one" in rendered and "compiling two" in rendered
    assert "(running…)" not in rendered
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd /tmp/wt-144 && deploy/orchestrator/.venv/bin/python -m pytest tests/test_orchestrator_tui.py -x -q -k mid_run`
Expected: FAIL - the pane holds `(running…)` and neither line.

- [x] **Step 3: Read `shown_output` in both renderers**

In `_details_text`:

```python
        step = row.step
        if step is not None:
            shown = step.shown_output
            body = shown.rstrip("\n") if shown else {
```

In `_render_details`:

```python
        step = row.step
        if step is not None:
            rlog.write(f"{self._step_header(step)}\n")
            shown = step.shown_output
            if shown:
                rlog.write(shown.rstrip("\n"))
            elif step.state == StepState.RUNNING:
```

- [x] **Step 4: Run the test and watch it pass**

Run: `cd /tmp/wt-144 && deploy/orchestrator/.venv/bin/python -m pytest tests/test_orchestrator_tui.py -q`
Expected: PASS, and every other TUI test still green.

- [x] **Step 5: See it red**

Put `step.output` back in `_render_details` only: the new test must fail again. Restore.

- [x] **Step 6: Commit**

```bash
git add src/simplon/orchestrator/tui.py tests/test_orchestrator_tui.py
git commit -F - <<'MSG'
fix(#144): the details pane reads a running step, not only a finished one
...
MSG
```

---

### Task 4: The artefacts stay markup-free, and the notes say so

**Files:**
- Modify: `site/content/using/releases.md`
- Test: `tests/test_orchestrator_transcript.py` (run, not modified)

- [x] **Step 1: Prove the artefacts did not change shape**

Run the two suites that assert si#148's artefacts carry no markup, unchanged:

```bash
cd /tmp/wt-144 && deploy/orchestrator/.venv/bin/python -m pytest \
  tests/test_orchestrator_transcript.py tests/test_steplog.py -q
```

Expected: PASS with no edit to either file. If one goes red, the fix is the code, not the assertion.

- [x] **Step 2: Write a real run's transcript and read it**

```bash
cd /tmp/wt-144 && ./simplon.sh test all > /dev/null 2>&1; \
  grep -c $'\e' build/logs/run-transcript.log build/logs/*.log || echo "no escapes anywhere"
```

Expected: zero escape characters in every file.

- [x] **Step 3: Add the release-notes section**

Under `## 0.10.0` in `site/content/using/releases.md`, after the si#148 section (the change these notes
continue), a `### ...(si#144)` section: what was measured, which candidate was the cause, which were
ruled out and with what evidence, and what a product sees change (more lines in a step log, none of them
markup).

- [x] **Step 4: Run the notes gate**

Run: `cd /tmp/wt-144 && ./simplon.sh test release-notes`
Expected: PASS - it reads the merged tickets in the range and 144 is now named.

- [x] **Step 5: The full gate**

Run: `cd /tmp/wt-144 && ./simplon.sh test all; ./simplon.sh test typecheck-python`
Expected: the three known `test_tasks_docs.py` failures (this box runs as root) and nothing else;
mypy clean over 86 files.

- [x] **Step 6: Commit**

```bash
git add site/content/using/releases.md
git commit -F - <<'MSG'
docs(#144): the notes for output that arrives when it happens
...
MSG
```

---

**Spec coverage.** Mechanism A: Tasks 2 and 3, proven the way the ticket specifies (highlight a
different row, come back, assert the pane carries the lines). Mechanism B: measured in table (c) and
found absent - no code change, and the finding is recorded in `run_stream`'s docstring and in the notes.
The four ranked candidates: candidate 1 corrected and implemented as the un-terminated tail rather than
the carriage return (Task 1), candidate 2 ruled out by measurement, candidate 3 ruled out by
measurement, candidate 4 rejected with its cost measured. "Numbers, per tool, before and after": tables
(a) to (d) here, and Task 1 Step 6 re-runs the one that matters after the change.

**Placeholders.** None: every code step carries the code, every test step the test, every run step the
command and the expected output.

## Where execution diverged from this plan

Two places, both recorded because the plan was wrong and the code is not.

**Task 2's Step model was built twice.** The first version put the recorder in `Step.run`, wrapping the
`Emit` it hands the streaming action, so that EVERY streaming step got a backlog rather than only the
ones handed their list. It is the better-looking design and it was rolled back: it makes `argv_step`'s
action correct only when reached through `run`, and two of this kernel's own tests
(`test_a_streaming_step_writes_its_output_where_it_can_be_read`,
`test_a_failed_step_writes_its_output_too`) call `.stream(...)` directly - under that design they wrote
an EMPTY step log and said nothing about it. A silent wrong answer on an existing correct-looking call
beat a hand-built `stream=` step showing no backlog, which is what the pane did before anyway. The cost
of the version kept is written on the field.

**Task 3's test drives a real child.** The plan's version built a `Step(stream=...)` by hand, which
under the design above has no backlog at all - so the test failed for the right reason and for the wrong
one. It now runs a real `sh` child through the real `run_stream`, blocked on a file rather than a sleep,
which is what the proof standard asked for: what broke here was the plumbing between the reader and the
pane, and a fake action does not have any. Its wait carries a DEADLINE, because the first version spun
until the backlog appeared and therefore HUNG instead of failing when the property was broken - a test
that hangs when the thing it protects is broken is not an assertion.

## Self-review

**Type consistency.** `Step.live: list[str]` and `Step.shown_output -> str` are used under those exact
names in Tasks 2 and 3; `run_stream(argv, on_line, *, flush_after)` keeps its two positional parameters,
so `argv_step`'s call site is unchanged and the three test doubles that monkeypatch it keep working -
they take `**kwargs` in the new tests and `(argv, on_line)` in the existing ones, which the keyword-only
parameter with a default leaves valid.
