"""Unit tests for run.run_stream - the live line-streaming subprocess helper the TUI builds on."""
from delivery.run import run_stream


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
