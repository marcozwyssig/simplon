"""Unit tests for simplon.tasks.completion (si#58): the verb that makes the generator addressable.

The GENERATOR is covered by test_completiongen.py. What is asserted here is the SEAM, the same one
test_tasks_workflows.py holds for `support:workflows`: that the verb reads the product's root, manifest
and manifest filename out of `simplon.context` rather than knowing a product, and that `--check` reports
disagreement as a NON-ZERO EXIT so one command serves both a pre-commit hook and a CI step.

AND ONE THING THE OTHER VERBS DO NOT HAVE TO SAY. This command's output is inert until somebody sources
it, so a run that wrote the file and said nothing else would have finished half a job. The install line
is asserted here rather than left to prose, because it is the difference between a generated file and a
working completion - which is the whole of si#58's fourth-quality-goal claim.

AAA throughout, including the negative cases.
"""
import textwrap

import pytest

from simplon import completiongen, context
from simplon.tasks import completion as completion_task

_MANIFEST = """
tasks:
  suite: { impl: "simplon.test_impls:nullary", help: "Run every test." }

groups:
  test:
    commands:
      all: { task: suite }
env_groups: []
"""


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A throwaway product: a repo root, a manifest with a name of its own, and a registered context."""
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(textwrap.dedent(_MANIFEST), encoding="utf-8")
    ctx = context.ProductContext(name="sample", root=tmp_path, manifest_path=manifest_path)
    monkeypatch.setattr(context, "_current", ctx)
    return ctx


def _target(product):
    return product.root / "deploy" / "completions" / "sample.bash"


def test_a_generate_writes_the_completion_under_the_product_root(product):
    """The seam: nothing here knows a product, so the file lands where THIS context says the root is."""
    # arrange / act
    rc = completion_task.generate()

    # assert
    assert rc == 0
    assert _target(product).is_file()
    assert "complete -o default -F _sample_complete sample.sh" in _target(product).read_text()


def test_the_run_says_where_the_file_goes_and_what_to_type_to_make_it_work(product, capsys):
    """A generator whose output nobody installs is a file in a repository, not a completion. The absolute
    path belongs HERE - in what the command prints for one machine - and never in the committed file,
    which two checkouts of the same commit have to agree about byte for byte."""
    # arrange / act
    completion_task.generate()
    printed = capsys.readouterr()

    # assert
    said = printed.out + printed.err
    assert str(_target(product)) in said, "the run does not say where the file it just wrote went"
    assert ".bashrc" in said and "source" in said
    assert "bashcompinit" in said, "the one zsh sentence is missing from the run's output"


def test_a_second_generate_says_up_to_date_rather_than_claiming_a_write(product, capsys):
    """"Nothing to do" and "did something" are different answers, and this repository's recurring defect
    is the pair that cannot be told apart."""
    # arrange
    completion_task.generate()
    capsys.readouterr()

    # act
    completion_task.generate()
    printed = capsys.readouterr()

    # assert
    assert "already up to date" in printed.out + printed.err


def test_check_returns_zero_when_the_committed_file_agrees(product):
    # arrange
    completion_task.generate()

    # act
    rc = completion_task.generate(check=True)

    # assert
    assert rc == 0


def test_check_returns_one_when_the_manifest_has_grown_a_command(product):
    """THE gate, and the exit code is the point rather than the message: a completion that has fallen
    behind the command tree fails silently - the command still runs when typed in full, and only the TAB
    goes quiet - so a warning nobody reads changes nothing about it. A 1 does."""
    # arrange: a generated file, then a manifest with one more command in it
    completion_task.generate()
    product.manifest_path.write_text(
        textwrap.dedent(_MANIFEST).replace("      all: { task: suite }",
                                           "      all: { task: suite }\n      unit: { task: suite }"),
        encoding="utf-8")

    # act
    rc = completion_task.generate(check=True)

    # assert
    assert rc == 1


def test_check_names_the_new_command_and_the_command_that_fixes_it(product, capsys):
    """A message that says "something is wrong" is the defect wearing a hat. This one has to name what
    changed and the exact line that resolves it, so nobody has to read this source to fix it."""
    # arrange
    completion_task.generate()
    product.manifest_path.write_text(
        textwrap.dedent(_MANIFEST).replace("      all: { task: suite }",
                                           "      all: { task: suite }\n      smoke: { task: suite }"),
        encoding="utf-8")
    capsys.readouterr()

    # act
    completion_task.generate(check=True)
    said = capsys.readouterr().out + capsys.readouterr().err

    # assert
    assert "smoke" in said
    assert "./sample.sh support completion" in said


def test_check_treats_a_missing_file_as_drift_and_writes_nothing(product):
    """A fresh checkout has never generated. That is drift - it has to be told what to run - and `--check`
    must still not write the file it is checking."""
    # arrange / act
    rc = completion_task.generate(check=True)

    # assert
    assert rc == 1
    assert not _target(product).exists()


def test_the_environments_reach_the_completion_from_the_manifest(product, capsys):
    """si#58 says the environment names come from the product's `environments` module rather than from
    the manifest. Measured against the code, they come from the manifest: `Provider.registry` reads
    `context.current().manifest_data()` and `parse_data` takes the names out of its `environments:`
    section - so a static generator can read them, and this is that read, end to end through the verb."""
    # arrange: the same product with an env-first group and a two-environment matrix
    product.manifest_path.write_text(textwrap.dedent(_MANIFEST).replace(
        "env_groups: []",
        "  deploy:\n    commands:\n      up: { task: suite }\n"
        "env_groups: [deploy]\ndefault: dev\nenvironments:\n"
        "  dev: { backend: local }\n  prod: { backend: local }\n"), encoding="utf-8")

    # act
    completion_task.generate()
    text = _target(product).read_text(encoding="utf-8")

    # assert
    assert "'dev'|'prod') return 0 ;;" in text
    assert f"'{completiongen.ENV_NODE}') _sample_reply=('deploy') ;;" in text
