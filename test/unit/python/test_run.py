"""Unit tests for run - the subprocess seam: the live line-streaming helper the TUI builds on, and the
two shapes a command impl runs external tools with (platform#43). Real `sh` subprocesses, because what is
under test IS the plumbing of the real exit code."""
from delivery.run import chain, run_stream, stream


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
