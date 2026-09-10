"""Unit tests for run - the subprocess seam: the live line-streaming helper the TUI builds on, and the
two shapes a command impl runs external tools with (platform#43). Real `sh` subprocesses, because what is
under test IS the plumbing of the real exit code."""
from simplon.run import chain, run_stream, stream


def test_run_stream_emits_each_line_and_returns_the_real_rc():
    # arrange: a command that prints two lines and exits non-zero
    seen: list[str] = []

    # act
    rc = run_stream(["sh", "-c", "printf 'one\\ntwo\\n'; exit 5"], seen.append)

    # assert: every line was streamed (newline-stripped) and the real exit code is returned
    assert seen == ["one", "two"]
    assert rc == 5


def test_run_stream_returns_zero_on_success():
    # arrange / act
    seen: list[str] = []
    rc = run_stream(["sh", "-c", "echo ok"], seen.append)

    # assert
    assert rc == 0
    assert seen == ["ok"]


# --- the two shapes a command impl uses (platform#43) ------------------------------------------------

def test_stream_returns_the_real_exit_code():
    # arrange / act: a command whose rc is neither 0 nor 1, so a boolean-ish result cannot pass for it
    rc = stream(["sh", "-c", "echo streamed; exit 7"])

    # assert
    assert rc == 7


def test_stream_runs_in_the_directory_it_was_given(tmp_path):
    # arrange: a marker that exists ONLY in the given directory
    (tmp_path / "marker").write_text("here")

    # act
    inside = stream(["sh", "-c", "test -f marker"], cwd=str(tmp_path))
    outside = stream(["sh", "-c", "test -f marker"])

    # assert: the cwd is what decides, not the process' own directory
    assert (inside, outside) == (0, 1)


def test_chain_stops_at_the_first_failure_and_returns_ITS_code(tmp_path):
    # arrange: three steps, the second and third failing with DIFFERENT codes, each leaving a trace
    trace = tmp_path / "ran"

    # act
    rc = chain(["sh", "-c", f"echo one >> {trace}"],
               ["sh", "-c", f"echo two >> {trace}; exit 3"],
               ["sh", "-c", f"echo three >> {trace}; exit 4"])

    # assert: the code of the step that FAILED, not of the last one - and the last one never ran
    assert rc == 3
    assert trace.read_text().split() == ["one", "two"]


def test_chain_runs_every_step_when_none_fails(tmp_path):
    # arrange
    trace = tmp_path / "ran"

    # act
    rc = chain(["sh", "-c", f"echo one >> {trace}"],
               ["sh", "-c", f"echo two >> {trace}"])

    # assert
    assert rc == 0
    assert trace.read_text().split() == ["one", "two"]


def test_chain_runs_its_steps_in_the_directory_it_was_given(tmp_path):
    # arrange: a marker only the given directory has
    (tmp_path / "marker").write_text("here")

    # act
    rc = chain(["sh", "-c", "test -f marker"], ["sh", "-c", "test -f marker"], cwd=str(tmp_path))

    # assert
    assert rc == 0


def test_chain_of_nothing_succeeds():
    # arrange / act / assert: an empty plan is not a failure
    assert chain() == 0


# --- si#144: a segment is what arrived, not what ended in a newline ----------------------------------

def test_run_stream_hands_over_a_partial_line_when_the_child_goes_quiet():
    """The measured defect (si#144): pytest writes one dot per test and completes the line every 72 of
    them, so `for line in proc.stdout` froze the pane for up to 11.37s while the child was writing every
    few milliseconds. A reader that waits for the terminator is the whole of it."""
    # arrange: a child that writes an unterminated run of dots, pauses, then finishes the line
    seen: list[str] = []
    argv = ["sh", "-c", "printf '...'; sleep 0.5; printf '... [100%%]\\n'"]

    # act
    rc = run_stream(argv, seen.append, flush_after=0.05)

    # assert: the first three dots arrived on their own, before the line was ever terminated
    assert rc == 0
    assert seen == ["...", "... [100%]"]


def test_run_stream_splits_on_a_carriage_return_as_well_as_a_newline():
    """A repaint ends a segment for the same reason a newline does: what came before it is finished
    text. This passed before si#144 too - `text=True` makes `\\r` a terminator for `readline` - and is
    kept because the rewrite to a chunk reader must not lose it."""
    # arrange
    seen: list[str] = []

    # act
    rc = run_stream(["sh", "-c", "printf 'a  17%%\\rb 100%%\\n'"], seen.append)

    # assert
    assert rc == 0
    assert seen == ["a  17%", "b 100%"]


def test_run_stream_treats_crlf_as_one_break():
    # arrange: a Windows-ending child, which must not produce an empty segment between the two bytes
    seen: list[str] = []

    # act
    run_stream(["sh", "-c", "printf 'one\\r\\ntwo\\r\\n'"], seen.append)

    # assert
    assert seen == ["one", "two"]


def test_run_stream_keeps_a_multibyte_character_whole_across_a_chunk_boundary():
    """Chunked reading can cut a UTF-8 character in half, which `text=True` used to prevent. The state
    icons this kernel echoes (the run tree's glyphs) are exactly such characters."""
    # arrange: the two halves of one character, written 0.3s apart, so they land in different reads
    seen: list[str] = []
    argv = ["python3", "-c",
            "import sys,time; b='\\u2713'.encode(); sys.stdout.buffer.write(b[:1]);"
            " sys.stdout.buffer.flush(); time.sleep(0.3);"
            " sys.stdout.buffer.write(b[1:]+b'\\n'); sys.stdout.buffer.flush()"]

    # act
    run_stream(argv, seen.append, flush_after=0.05)

    # assert: one whole character, never two replacement marks
    assert "".join(seen) == "✓"


def test_run_stream_emits_the_last_line_when_the_child_never_terminates_it():
    # arrange
    seen: list[str] = []

    # act
    rc = run_stream(["sh", "-c", "printf 'no newline here'; exit 3"], seen.append)

    # assert
    assert (rc, seen) == (3, ["no newline here"])
