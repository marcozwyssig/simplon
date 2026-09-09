"""The run transcript: one file that describes the WHOLE run (si#148 items 3 and 4).

The gap it closes is not a nicer pane. `steplog.write` saves what one step printed and `failure_report`
prints the failures after the app has exited; neither is the thing somebody attaches to a ticket - every
step, in order, with its header, its rc and its duration, under a header that says when the run started,
in which environment and instance, and which simplon answered.

Written on BOTH paths. The run that most needs attaching to a ticket is a red CI run, which is exactly
the headless path, so a transcript written only under the TUI would exist only on the machine where the
operator could already read the screen.

AAA throughout; nothing here runs a subprocess and nothing sleeps.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from simplon import context, steplog
from simplon.context import ProductContext
from simplon.orchestrator import steps as steps_mod
from simplon.orchestrator.manifest import load as manifest_load
from simplon.orchestrator.steps import (
    Outcome,
    Pipeline,
    Step,
    StepState,
    run_headless,
    transcript,
    write_run_transcript,
)

_MANIFEST = """
tasks:
  install: { impl: "demo.impls:install", help: "Install host prereqs." }
  compile: { impl: "demo.impls:compile", help: "Compile the artefacts." }
  up: { impl: "demo.impls:up", help: "Deploy up." }

groups:
  build:
    commands:
      install: { task: "install" }
      compile: { task: "compile" }
      prep: { help: "Install + compile.", depends_on: ["install", "compile"], stop_on_failure: true }
  deploy:
    commands:
      up: { task: "up" }
      bringup: { help: "Full bring-up.", depends_on: ["prep", "up"] }
env_groups: [deploy]
"""

_STARTED = datetime(2026, 9, 10, 14, 3, 9)


@pytest.fixture(autouse=True)
def _product_context(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_current",
                        ProductContext("cleon", tmp_path, tmp_path / "cleon.yaml"))


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    """The durations in a transcript are asserted as text, so the clock is the test's - see
    test_orchestrator_status.py for the argument."""
    ticks = iter([float(n) for n in range(0, 200)])
    monkeypatch.setattr(steps_mod, "clock", lambda: next(ticks))


def _pipeline(rc_by_name: dict[str, int] | None = None) -> Pipeline:
    """The plan `run_command` builds for `bringup`, whose `build.prep` stops on a failure - so a red run
    really does leave a SKIPPED step behind for the transcript to report."""
    rc_by_name = rc_by_name or {}
    tree = manifest_load(_MANIFEST).plan_tree_for("bringup")
    steps = [Step(label=leaf.name, command=leaf.path, help=leaf.spec.help,
                  action=lambda name=leaf.name: Outcome(rc=rc_by_name.get(name, 0),
                                                        output=f"{name} spoke\nand exited"))
             for leaf in tree.leaves()]
    return Pipeline("bringup", steps, False, tree, tree.path)


# --- the body -----------------------------------------------------------------------------------------


def test_the_transcript_lists_every_step_in_the_order_it_ran():
    # arrange
    pipeline = _pipeline()
    run_headless(pipeline, verbose=False)
    # act
    lines = transcript(pipeline, header=["=== header ==="])
    # assert: the ORDER is the execution order, which is what a tree cannot show
    named = [line for line in lines if line.startswith(("✓ ", "✗ ", "⊘ "))]
    assert [line.split("  ")[0] for line in named] == \
        ["✓ build.install", "✓ build.compile", "✓ deploy.up"]


def test_every_step_carries_its_rc_and_its_duration():
    # arrange
    pipeline = _pipeline()
    run_headless(pipeline, verbose=False)
    # act
    lines = transcript(pipeline, header=[])
    # assert
    assert "✓ build.install  rc 0  1.0s" in lines
    assert "✓ build.compile  rc 0  1.0s" in lines


def test_every_step_carries_the_exact_command_and_its_help():
    """`_step_header`'s content, in the file: the dotted path is what a reader scans, the exact command
    plus the manifest's own `help:` is what makes a pasted excerpt reproducible rather than anecdotal."""
    # arrange
    pipeline = _pipeline()
    run_headless(pipeline, verbose=False)
    # act
    lines = transcript(pipeline, header=[])
    # assert
    assert "    $ build.install - Install host prereqs." in lines


def test_a_step_that_never_ran_carries_no_rc_and_no_duration():
    """The same guarantee #52 put on the tree column: `rc 0` or `0.0s` on a skipped step would claim it
    ran and passed instantly, which is the one claim this repo keeps hunting. And the SCOPE is named -
    `build.prep` stopped, `deploy.up` was never in it and still ran, which is netctl#1317's whole point
    and something a bare `⊘` cannot say."""
    # arrange: the FIRST leaf of the stopping subtree fails, so its sibling is the one skipped
    pipeline = _pipeline({"install": 1})
    run_headless(pipeline, verbose=False)
    # act
    lines = transcript(pipeline, header=[])
    # assert
    skipped = [line for line in lines if line.startswith("⊘ ")]
    assert skipped == ["⊘ build.compile  (skipped: build.prep stopped on a failure)"]
    assert any(line.startswith("✓ deploy.up  rc 0") for line in lines), \
        "a sibling of the stopped subtree still runs"


def test_a_red_transcript_says_why_each_failure_failed_and_where_the_rest_of_it_is():
    # arrange
    pipeline = _pipeline({"compile": 1})
    run_headless(pipeline, verbose=False)
    # act
    text = "\n".join(transcript(pipeline, header=[]))
    # assert: `failure_report`'s own lines, not a second rendering of them
    assert "why build.compile failed (rc 1):" in text
    assert "compile spoke" in text


def test_the_transcript_ends_on_the_runs_verdict():
    # arrange
    pipeline = _pipeline({"install": 1})
    run_headless(pipeline, verbose=False)
    # act
    lines = transcript(pipeline, header=[])
    # assert
    assert lines[-1] == "verdict: ✗ 1 of 3 steps failed, 1 skipped"


def test_a_green_transcript_ends_on_a_green_verdict():
    pipeline = _pipeline()
    run_headless(pipeline, verbose=False)
    assert transcript(pipeline, header=[])[-1] == "verdict: ✓ all 3 steps passed"


def test_the_transcript_carries_no_markup_and_no_escape():
    """`STATE_ICON` is shared with the headless renderer and this file is something a reader attaches to
    a ticket. Rich markup or an ANSI escape landing in either is the defect si#144 warns about for a pty,
    so the transcript is asserted to be plain text and nothing else."""
    # arrange
    pipeline = _pipeline({"compile": 1})
    run_headless(pipeline, verbose=False)
    # act
    text = "\n".join(transcript(pipeline, header=["=== x ==="]))
    # assert
    assert "\x1b" not in text, "no ANSI escape"
    assert "[/" not in text and "[bold" not in text and "[red" not in text, "no rich markup"


# --- the header (item 4) ------------------------------------------------------------------------------


def test_the_header_says_when_the_run_started():
    assert "started:      2026-09-10 14:03:09" in steplog.run_header("bringup", _STARTED)


def test_the_header_names_the_run():
    assert steplog.run_header("bringup", _STARTED)[0] == "=== simplon run transcript: bringup ==="


def test_the_header_names_the_active_environment(monkeypatch):
    # arrange: the kernel-owned mirror `cli.main` exports beside the product's own variable
    monkeypatch.setenv(context.ENVIRONMENT_ENV, "prod")
    # act
    lines = steplog.run_header("bringup", _STARTED)
    # assert
    assert "environment:  prod" in lines


def test_an_environment_nobody_selected_is_said_rather_than_guessed(monkeypatch):
    """A pipeline run outside `cli.main` - a unit test, a scaffolder - has no active environment. Naming
    the manifest's default there would put a fact in the file that no run produced."""
    monkeypatch.delenv(context.ENVIRONMENT_ENV, raising=False)
    assert "environment:  not set" in steplog.run_header("bringup", _STARTED)


def test_the_header_names_the_lab_instance(monkeypatch, tmp_path):
    # arrange: a manifest that declares the section `labinstance.spec` reads
    (tmp_path / "cleon.yaml").write_text(
        "instance:\n  env_var: CLEON_INSTANCE\n  default: dev\n  max_id_len: 2\n", encoding="utf-8")
    monkeypatch.setenv("CLEON_INSTANCE", "a1")
    # act
    lines = steplog.run_header("bringup", _STARTED)
    # assert
    assert "instance:     a1" in lines


def test_a_product_that_declares_no_instance_section_is_said_rather_than_raised(tmp_path):
    """`labinstance.spec` fails loudly on a missing section, which is right for a lab command and wrong
    here: simplon's own manifest declares none, and a transcript that refuses to be written because the
    run had no lab is a courtesy that raises."""
    (tmp_path / "cleon.yaml").write_text("product: cleon\n", encoding="utf-8")
    assert "instance:     not declared" in steplog.run_header("bringup", _STARTED)


def test_the_header_carries_the_same_provenance_line_the_help_screen_shows():
    """si#125 put "which simplon is answering, and from where" into the help epilog. The transcript wants
    the identical fact, and a second implementation of it would be two answers to one question."""
    from simplon import cli

    # act
    lines = steplog.run_header("bringup", _STARTED)
    # assert
    assert f"tooling:      {cli.provenance_line()}" in lines


def test_no_registered_product_still_yields_a_header(monkeypatch):
    monkeypatch.setattr(context, "_current", None)
    lines = steplog.run_header("bringup", _STARTED)
    assert lines[0].startswith("=== simplon run transcript")
    assert "instance:     not declared" in lines


# --- the file, on both paths --------------------------------------------------------------------------


def test_the_headless_runner_leaves_a_transcript_on_disk(tmp_path):
    # arrange
    pipeline = _pipeline({"install": 1})
    # act
    run_headless(pipeline, verbose=False)
    # assert
    written = tmp_path / "build" / "logs" / "run-transcript.log"
    assert written.is_file(), "CI is exactly where a red run has to be attachable to a ticket"
    text = written.read_text(encoding="utf-8")
    assert "=== simplon run transcript: bringup ===" in text
    assert "✗ build.install  rc 1" in text
    assert "⊘ build.compile" in text


def test_the_transcript_is_replaced_rather_than_appended(tmp_path):
    """The same rule the per-step logs follow: the interesting run is the last one."""
    run_headless(_pipeline(), verbose=False)
    run_headless(_pipeline({"install": 1}), verbose=False)

    text = (tmp_path / "build" / "logs" / "run-transcript.log").read_text(encoding="utf-8")
    assert text.count("=== simplon run transcript") == 1


def test_writing_a_transcript_without_a_product_is_not_a_crash(monkeypatch):
    monkeypatch.setattr(context, "_current", None)
    assert write_run_transcript(_pipeline(), _STARTED) is None


def test_a_run_that_was_never_started_still_writes_a_transcript(tmp_path):
    """A transcript of a run the operator quit half way through is the case the TUI path has to survive:
    `run_pipeline` writes AFTER `app.run()` returns, and quitting is a normal way for it to return."""
    # arrange: nothing ran at all
    pipeline = _pipeline()
    # act
    written = write_run_transcript(pipeline, _STARTED)
    # assert
    assert written is not None
    text = written.read_text(encoding="utf-8")
    assert "· build.install" in text
    assert "verdict:" in text


def test_a_transcript_that_cannot_be_composed_costs_the_file_and_never_the_run(monkeypatch, capsys):
    """The guard is round the WHOLE composition, and one frame's difference is the point.

    `steplog.write_run` catches OSError, which is all that WRITING can raise. Everything before it -
    the header, the `STATE_ICON` lookups, the `abort_after` traversal, `failure_report` - is rendering,
    and a rendering fault there used to propagate out of `run_headless` and `run_pipeline`. It would take
    the process down before the exit code was returned and before the failure summary was printed, on
    exactly the red run the artefact exists for: a file meant to explain a failure replacing the
    explanation with its own traceback.
    """
    # arrange: the rendering raises, the way a future StepState missing from STATE_ICON would
    def explode(*_args, **_kwargs):
        raise KeyError("a state nobody added an icon for")

    monkeypatch.setattr(steps_mod, "transcript", explode)
    pipeline = _pipeline({"install": 1})

    # act
    rc = run_headless(pipeline, verbose=False)

    # assert: the RUN still returns its verdict, and the loss is named once
    assert rc == 1
    assert "the run transcript could not be composed" in capsys.readouterr().out
