"""Smoke test for the shared Textual split-pane app (delivery.orchestrator.tui): drive it headlessly
via run_test() and assert the worker ran every step to its real state and the details pane shows a step's
output. Skipped when Textual is not installed. Moved here from netctl - the tui is platform's now.
"""
import asyncio

import pytest

pytest.importorskip("textual")

from delivery.orchestrator.steps import Outcome, Pipeline, Step  # noqa: E402
from delivery.orchestrator.tui import _StepApp  # noqa: E402


def _pipeline() -> Pipeline:
    return Pipeline("smoke", [
        Step(label="passes", action=lambda: Outcome(rc=0, output="all good")),
        Step(label="fails", action=lambda: Outcome(rc=1, output="boom")),
    ])


def test_tui_app_runs_every_step_and_renders_details():
    # arrange
    pipeline = _pipeline()

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()   # the @work(thread=True) step runner
            await pilot.pause()
            # highlight the first (passing) step; its output should reach the details log
            from textual.widgets import ListView, RichLog
            app.query_one("#steps", ListView).index = 0
            await pilot.pause()
            details = app.query_one("#details", RichLog)
            rendered = "\n".join(str(line) for line in details.lines)
        return rendered

    # act
    rendered = asyncio.run(_drive())

    # assert: both steps reached their real states, and the passing step's output rendered
    assert pipeline.steps[0].state.name == "OK"
    assert pipeline.steps[1].state.name == "FAILED"
    assert "all good" in rendered
