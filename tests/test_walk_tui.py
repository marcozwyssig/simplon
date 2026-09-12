"""The half of the acceptance walk that needs a person: the two keys, the third state, and the resume
(si#205).

Driven through Textual's own test driver, the shape si#148's and si#169's tests use. si#169's finding is
what the waiting here is for: Textual applies work AFTER a refresh, so a test that reads a widget in the
instant it acted on it measures the wrong instant. Nothing below asserts on a value it did not first wait
for - `_asked` polls until the runner's worker thread is really inside the question, and every keypress is
followed by a wait for what it caused rather than by an assumption that it has landed.
"""
import asyncio
import threading
import time

import pytest

pytest.importorskip("textual")

from datetime import datetime  # noqa: E402

from simplon.orchestrator.steps import StepState, build_rows, summarise, transcript  # noqa: E402
from simplon.orchestrator.tui import _StepApp, _WalkApp, settle  # noqa: E402
from simplon.tasks import walk as walk_mod  # noqa: E402
from simplon.tasks.acceptance import read  # noqa: E402

TWO_SCENARIOS = """@gate
Feature: One verdict

  Background:
    Given a clean checkout

  Scenario: The gate runs everything
    When I run the gate
    Then it reports three steps

  Scenario: A gate that found nothing is not green
    When the empty gate runs
    Then it does not report success
"""


def _pipeline(state: walk_mod.State | None = None):
    """A real walk over two scenarios: three steps each, the background prepended to both."""
    feature = read(TWO_SCENARIOS, "tests/acceptance/one.feature", "acceptance/one.feature")
    key = walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "all scenarios", "sha256:aa")
    prompt = walk_mod.Prompt()
    return walk_mod.plan([(feature, feature.scenarios)], state or walk_mod.State(key=key),
                         prompt), prompt


async def _asked(prompt, pilot, timeout: float = 5.0) -> str:
    """Wait until a question is really open, and return it.

    POLLED and not read once. The runner's worker is a separate thread and the question appears when IT
    gets there, not when the UI thread finishes a frame - si#169's rule, applied to a handover rather than
    to a scroll.
    """
    deadline = time.monotonic() + timeout
    while not prompt.question and time.monotonic() < deadline:
        await pilot.pause()
        await asyncio.sleep(0.005)
    # RAISES rather than returning "". A helper that gives up quietly turns every assertion after it into
    # one that cannot fail for the reason it was written: the test would press keys nobody is waiting for
    # and then compare states nothing produced.
    assert prompt.question, f"no question was asked within {timeout}s"
    return prompt.question


async def _answer(prompt, pilot, key: str) -> None:
    """Press one verdict key and wait until the worker has taken it."""
    asked = prompt.question
    await pilot.press(key)
    deadline = time.monotonic() + 5.0
    while prompt.question == asked and time.monotonic() < deadline:
        await pilot.pause()
        await asyncio.sleep(0.005)
    assert prompt.question != asked, f"pressing {key!r} left the walk on the same question"


def test_accepting_and_refusing_cost_the_same_one_key():
    """Not a claim, an arrangement: `a` and `r` are single unmodified presses, they are the FIRST two
    bindings so a narrow footer drops the navigation keys before it drops them, and neither is a default -
    nothing happens until one of the two is pressed."""
    def spelled(binding):
        return (binding[0], binding[2]) if isinstance(binding, tuple) else (binding.key,
                                                                            binding.description)

    # act
    keys = [spelled(binding) for binding in _WalkApp.BINDINGS]

    # assert
    assert keys[:2] == [("a", "Accept step"), ("r", "Refuse step")]
    assert keys[2:] == [spelled(binding) for binding in _StepApp.BINDINGS]
    assert not any(key in ("enter", "space") for key, _ in keys)


def test_a_person_accepting_every_step_makes_the_walk_green():
    # arrange
    pipeline, prompt = _pipeline()

    async def _drive():
        app = _WalkApp(pipeline, prompt)
        async with app.run_test() as pilot:
            for _ in pipeline.steps:
                await _asked(prompt, pilot)
                await _answer(prompt, pilot, "a")
            await app.workers.wait_for_complete()

    # act
    asyncio.run(_drive())

    # assert
    assert [step.state for step in pipeline.steps] == [StepState.OK] * 6
    assert summarise(build_rows(pipeline)).passed


def test_a_refusal_stops_that_scenario_and_the_next_one_is_still_walked():
    """The mapping's load-bearing half, driven: pytest-bdd stops a scenario at its first failing step and
    runs the next scenario anyway, and `abort_after` reproduces it from the scenario node's flag alone."""
    # arrange
    pipeline, prompt = _pipeline()

    async def _drive():
        app = _WalkApp(pipeline, prompt)
        async with app.run_test() as pilot:
            await _asked(prompt, pilot)
            await _answer(prompt, pilot, "a")          # scenario 1, step 1
            await _asked(prompt, pilot)
            await _answer(prompt, pilot, "r")          # scenario 1, step 2 - the customer says no
            for _ in range(3):                          # scenario 2 is asked in full
                await _asked(prompt, pilot)
                await _answer(prompt, pilot, "a")
            await app.workers.wait_for_complete()

    # act
    asyncio.run(_drive())

    # assert
    assert [step.state for step in pipeline.steps] == [
        StepState.OK, StepState.FAILED, StepState.SKIPPED,
        StepState.OK, StepState.OK, StepState.OK]


def test_the_step_nobody_reached_says_which_scenario_declined_it():
    # arrange
    pipeline, prompt = _pipeline()

    async def _drive():
        app = _WalkApp(pipeline, prompt)
        async with app.run_test() as pilot:
            await _asked(prompt, pilot)
            await _answer(prompt, pilot, "r")
            for _ in range(3):
                await _asked(prompt, pilot)
                await _answer(prompt, pilot, "a")
            await app.workers.wait_for_complete()

    # act
    asyncio.run(_drive())
    lines = transcript(pipeline, [])

    # assert: the scope, in the transcript's own words, with nothing added for a walk
    assert "(skipped: The gate runs everything stopped on a failure)" in lines[2]
    assert "verdict:" in lines[-1] and "passed" not in lines[-1]


def test_a_walk_the_person_stopped_leaves_the_rest_pending_and_is_not_green():
    """A step nobody reached is a third state, and stopping produces a DIFFERENT one from refusing: PENDING
    means the walk ended before it, SKIPPED means a refusal declined it. Neither reads as a pass."""
    # arrange
    pipeline, prompt = _pipeline()

    async def _drive():
        app = _WalkApp(pipeline, prompt)
        async with app.run_test() as pilot:
            await _asked(prompt, pilot)
            await _answer(prompt, pilot, "a")
            await _asked(prompt, pilot)
            await pilot.press("q")                      # stopped with a question open
            await app.workers.wait_for_complete()

    # act
    asyncio.run(_drive())
    settle(pipeline)

    # assert
    assert pipeline.steps[0].state is StepState.OK
    assert [step.state for step in pipeline.steps[1:]] == [StepState.PENDING] * 5
    summary = summarise(build_rows(pipeline))
    assert not summary.passed and summary.pending == 5


def test_the_record_of_a_stopped_walk_says_pending_and_never_running():
    """`transcript` prints a step that never entered `run` as `(<state>)`, so a step left RUNNING would
    read as work still going on in a record of a run that is over."""
    # arrange
    pipeline, prompt = _pipeline()

    async def _drive():
        app = _WalkApp(pipeline, prompt)
        async with app.run_test() as pilot:
            await _asked(prompt, pilot)
            await pilot.press("q")
            await app.workers.wait_for_complete()

    # act
    asyncio.run(_drive())
    before = transcript(pipeline, [])
    settle(pipeline)
    after = transcript(pipeline, [])

    # assert: seen red first - the raw state really is RUNNING until `settle` is called
    assert any("(running)" in line for line in before)
    assert not any("(running)" in line for line in after)
    assert any("(pending)" in line for line in after)


def test_a_stray_keypress_with_no_question_open_is_not_a_signature():
    # arrange
    prompt = walk_mod.Prompt()

    # act / assert
    assert prompt.answer(True) is False


def test_a_second_press_before_the_worker_moved_on_does_not_overwrite_the_first():
    """The verdict is whatever was pressed FIRST. A second key while the worker is still picking the
    answer up would otherwise turn an acceptance into a refusal, or the other way round, with the person
    seeing nothing."""
    # arrange: a real waiter, because the guard is `_ready.is_set()` and only a blocked `ask` sets it
    prompt = walk_mod.Prompt()
    taken: list[bool] = []
    waiter = threading.Thread(target=lambda: taken.append(prompt.ask("a step")), daemon=True)
    waiter.start()
    deadline = time.monotonic() + 5.0
    while not prompt.question and time.monotonic() < deadline:
        time.sleep(0.005)

    # act
    first = prompt.answer(True)
    second = prompt.answer(False)
    waiter.join(timeout=5.0)

    # assert
    assert (first, second) == (True, False)
    assert taken == [True]


def test_quitting_releases_the_step_so_the_worker_thread_can_end():
    """The worker is a `@work(thread=True)` thread blocked on an event. One nobody sets outlives
    `App.run()` and the interpreter waits for it at exit, so a walk stopped mid-question would hang the
    process rather than end it."""
    # arrange
    pipeline, prompt = _pipeline()

    async def _drive():
        app = _WalkApp(pipeline, prompt)
        async with app.run_test() as pilot:
            await _asked(prompt, pilot)
            await pilot.press("q")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5.0)
            return True

    # act / assert: the timeout IS the assertion
    assert asyncio.run(_drive())


# --- resuming ---------------------------------------------------------------------------------------------


def test_a_resumed_walk_asks_only_the_steps_nobody_answered():
    # arrange: two of the six already answered, one accepted and one refused
    key = walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "all scenarios", "sha256:aa")
    state = walk_mod.State(key=key)
    address = "acceptance/one.feature:The gate runs everything"
    state.record(address, 0, True, datetime(2026, 9, 12, 10, 0, 0))
    state.record(address, 1, True, datetime(2026, 9, 12, 10, 1, 0))
    pipeline, prompt = _pipeline(state)
    asked: list[str] = []

    async def _drive():
        app = _WalkApp(pipeline, prompt)
        async with app.run_test() as pilot:
            for _ in range(4):
                asked.append(await _asked(prompt, pilot))
                await _answer(prompt, pilot, "a")
            await app.workers.wait_for_complete()

    # act
    asyncio.run(_drive())

    # assert: the two replayed steps asked nobody, and they are still OK in the record
    assert [q.split(" - ", 1)[1] for q in asked] == [
        "Then it reports three steps", "Given a clean checkout", "When the empty gate runs",
        "Then it does not report success"]
    assert [step.state for step in pipeline.steps] == [StepState.OK] * 6
    assert state.answered() == 6


def test_a_resumed_walk_keeps_an_earlier_refusal_and_its_consequence():
    """A replay is not a re-run: a step refused on Monday is still refused on Wednesday, and the rest of
    its scenario is still not asked."""
    # arrange
    key = walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "all scenarios", "sha256:aa")
    state = walk_mod.State(key=key)
    state.record("acceptance/one.feature:The gate runs everything", 0, False,
                 datetime(2026, 9, 12, 10, 0, 0))
    pipeline, prompt = _pipeline(state)

    async def _drive():
        app = _WalkApp(pipeline, prompt)
        async with app.run_test() as pilot:
            for _ in range(3):
                await _asked(prompt, pilot)
                await _answer(prompt, pilot, "a")
            await app.workers.wait_for_complete()

    # act
    asyncio.run(_drive())

    # assert
    assert [step.state for step in pipeline.steps] == [
        StepState.FAILED, StepState.SKIPPED, StepState.SKIPPED,
        StepState.OK, StepState.OK, StepState.OK]


def test_a_resumed_walk_records_who_answered_what_and_when_on_every_line():
    # arrange
    key = walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "all scenarios", "sha256:aa")
    state = walk_mod.State(key=key)
    state.record("acceptance/one.feature:The gate runs everything", 0, True,
                 datetime(2026, 9, 12, 10, 0, 0))
    pipeline, _ = _pipeline(state)

    # act
    lines = transcript(pipeline, [])

    # assert: the step header under the first line names the sitting the answer came from
    assert lines[1].endswith("- accepted in an earlier sitting at 2026-09-12 10:00:00")
    assert lines[3].endswith("The gate runs everything")
