"""si#858: `after_all:` - which catalogue task runs after every other leaf of its CI job, whatever they did.

A derived CI workflow puts such a leaf last in its job with `if: always()`: `test:report` merges the results
the other leaves wrote, and it has to run when one of them failed, because that is when somebody reads it.
The field is declared once on the task and inherited by every command that places it, for `publishes`'s
reason (si#490). A second task carrying it is a decision, so a test holds the population.
"""
from __future__ import annotations

import textwrap

import pytest

from simplon.manifest import catalogue
from simplon.manifest import load as manifest
from conftest import ROOT


def _loaded(text: str):
    return manifest.load(textwrap.dedent(text), catalogue=catalogue.load())


def test_the_report_task_runs_after_all():
    loaded = manifest.load((ROOT / "simplon.yaml").read_text(), catalogue=catalogue.load())
    placed = [c for group in loaded.commands.values() for c in group.values()
              if getattr(c, "task", "") == "test:report"]
    assert placed, "simplon's manifest places test:report"
    assert all(c.after_all is True for c in placed)


def test_only_the_report_task_runs_after_all():
    assert {key for key, task in catalogue.load().tasks.items() if task.get("after_all")} == {"test:report"}


def test_a_quoted_after_all_is_refused():
    with pytest.raises(ValueError, match="'after_all' is true or false"):
        _loaded("""
            tasks:
              ship: { impl: "simplon.test_impls:nullary", help: "Ship.", after_all: "yes" }
            ci:
              release:
                commands:
                  ship: { task: ship }
            """)
