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


def test_the_launchers_step_writes_to_stderr_so_a_captured_stdout_stays_clean(monkeypatch, capfd):
    # arrange: `V=$(./demo.sh release version)` right after a deps refresh must capture the version only
    monkeypatch.setenv(cli.PLUGIN_STEP_ENV, "1")
    monkeypatch.setattr(claudeplugins, "step",
                        lambda: claudeplugins.Outcome(claudeplugins.State.SKIPPED, "CI=true"))

    # act
    cli.plugin_step_after_refresh()

    # assert
    out, err = capfd.readouterr()
    assert out == ""
    assert "skipped" in err



def _product(monkeypatch, tmp_path, claude_section):
    import types
    data = {"toolchains": ["claude"], **({"claude": claude_section} if claude_section is not None else {})}
    ctx = types.SimpleNamespace(manifest_data=lambda: data, manifest_path=tmp_path / "demo.yaml")
    monkeypatch.setattr(claudeplugins.context, "current", lambda: ctx)


def test_auto_install_false_skips_the_launchers_step_and_says_nothing(monkeypatch, tmp_path, capfd):
    # arrange: si#583 - firn's security review flags `./firn.sh test all` installing plugins from a
    # third-party repository; with the key off only an explicit `support install` installs
    _product(monkeypatch, tmp_path, {"auto_install": False})
    monkeypatch.setenv(cli.PLUGIN_STEP_ENV, "1")
    monkeypatch.setattr(claudeplugins, "step", lambda: pytest.fail("the automatic step ran"))

    # act
    cli.plugin_step_after_refresh()

    # assert: silent, as the product chose, and the variable is still consumed
    out, err = capfd.readouterr()
    assert out == "" and err == ""
    assert cli.PLUGIN_STEP_ENV not in os.environ


@pytest.mark.parametrize("section", [None, {"auto_install": True}])
def test_auto_install_absent_or_true_keeps_the_launchers_step(monkeypatch, tmp_path, section):
    # arrange
    _product(monkeypatch, tmp_path, section)
    monkeypatch.setenv(cli.PLUGIN_STEP_ENV, "1")
    ran = []
    monkeypatch.setattr(claudeplugins, "step", lambda: ran.append(1) or claudeplugins.Outcome(
        claudeplugins.State.NOTHING_MISSING))
    monkeypatch.setattr(claudeplugins, "report", lambda outcome: None)

    # act
    cli.plugin_step_after_refresh()

    # assert
    assert ran == [1]


def test_a_malformed_auto_install_still_reaches_the_step_so_its_diagnosis_is_reported(monkeypatch, tmp_path):
    # arrange: the launcher must not read an unreadable key as "off" - that would hide the diagnosis
    _product(monkeypatch, tmp_path, {"auto_install": "false"})
    monkeypatch.setenv(cli.PLUGIN_STEP_ENV, "1")
    ran = []
    monkeypatch.setattr(claudeplugins, "step", lambda: ran.append(1) or claudeplugins.Outcome(
        claudeplugins.State.FAILED, "bad"))
    monkeypatch.setattr(claudeplugins, "report", lambda outcome: None)

    # act
    cli.plugin_step_after_refresh()

    # assert
    assert ran == [1]
