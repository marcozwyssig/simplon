"""si#525: the launcher installs the `claude` toolchain's plugins when it has just refreshed its deps.

Not on every launch - measured, `support claude-plugins -n` takes 1421 ms against 382 ms for a bare
`./simplon.sh --help` - and never on the container route, where `claude` is on the host and not in the
image. The launcher is bash and the step is Python, so the launcher only SAYS that the deps were refreshed
(one exported variable) and the kernel's `main`, which has the product context, runs the one
implementation. A plugin never fails a build: whatever the step answers, the command still runs.
"""
from __future__ import annotations

import os

import pytest

from simplon import cli
from simplon.cli import bootstrap
from simplon.tasks import claudeplugins


def _launcher() -> str:
    return bootstrap._render_launcher("demo", "launch.sh.j2", "deploy/orchestrator")


def test_launcher_says_so_after_a_venv_deps_refresh():
    # arrange
    text = _launcher()

    # act: the venv route's refresh block, from its condition to its `fi`
    start = text.index('if [ ! -f "$STAMP" ] || [ "$REQ" -nt "$STAMP" ]; then')
    block = text[start:text.index("\nfi\n", start)]

    # assert: after the install succeeded, so a failed pip run does not ask for plugins
    assert block.index(f"export {cli.PLUGIN_STEP_ENV}=1") > block.index('touch "$STAMP"')


def test_launcher_container_route_has_no_plugin_step():
    # arrange
    text = _launcher()

    # act
    start = text.index('if [ ! -f "$CSTAMP" ] || [ "$REQ" -nt "$CSTAMP" ]; then')
    block = text[start:text.index("\n    fi\n", start)]

    # assert
    assert cli.PLUGIN_STEP_ENV not in block


@pytest.mark.parametrize("state", list(claudeplugins.State))
def test_the_step_runs_once_and_never_fails_the_command(monkeypatch, state):
    # arrange
    calls: list[int] = []
    reported: list[claudeplugins.Outcome] = []
    monkeypatch.setenv(cli.PLUGIN_STEP_ENV, "1")
    monkeypatch.setattr(claudeplugins, "step",
                        lambda: (calls.append(1), claudeplugins.Outcome(state, "why"))[1])
    monkeypatch.setattr(claudeplugins, "report", reported.append)

    # act
    cli.plugin_step_after_refresh()
    cli.plugin_step_after_refresh()

    # assert: once - the variable is taken, so a plan's `./demo.sh <leaf>` children do not repeat it
    assert calls == [1]
    assert cli.PLUGIN_STEP_ENV not in os.environ
    assert reported == ([] if state is claudeplugins.State.OFF else [claudeplugins.Outcome(state, "why")])


def test_without_the_variable_nothing_runs(monkeypatch):
    # arrange
    monkeypatch.delenv(cli.PLUGIN_STEP_ENV, raising=False)
    monkeypatch.setattr(claudeplugins, "step", lambda: pytest.fail("ran without a deps refresh"))

    # act / assert
    cli.plugin_step_after_refresh()


def test_an_unexpected_error_in_the_step_is_a_warning_not_a_failed_command(monkeypatch):
    # arrange
    warned: list[str] = []
    monkeypatch.setenv(cli.PLUGIN_STEP_ENV, "1")
    monkeypatch.setattr(claudeplugins, "step", lambda: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(cli.log, "warn", warned.append)

    # act
    cli.plugin_step_after_refresh()

    # assert
    assert warned and "disk full" in warned[0]
