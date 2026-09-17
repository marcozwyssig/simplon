"""Unit tests for simplon.tasks.workflows (si#40): the verb that makes the generator addressable.

The GENERATOR is covered by test_workflowgen.py. What is asserted here is the SEAM, and it is the same
seam test_tasks_tasks.py holds for `tasks:generate`: that the verb reads the product's root, manifest and
manifest filename out of `simplon.context` rather than knowing a product, and that `--check` reports
disagreement as a NON-ZERO EXIT so one command serves both a pre-commit hook and a CI step.

THE EXIT CODE IS THE POINT, not the message. si#40 is a ticket about a class of failure that is green:
a workflow that has drifted from its manifest still runs, still passes, and still tests whatever it
happens to say. A warning printed into a log that nobody reads changes nothing about that. A 1 does.

AAA throughout, including the negative cases.
"""
import textwrap

import pytest

from simplon import context
from simplon.tasks import workflows as workflows_task

_MANIFEST = """
tasks:
  suite: { impl: "simplon.test_impls:nullary", help: "Run every test." }

groups:
  test:
    commands:
      all: { task: suite }
env_groups: []

workflows:
  ci:
    on: [push]
    jobs:
      build:
        runs-on: ubuntu-latest
        steps:
          - command: test all
"""

_WITH_A_HAND_WRITTEN_ONE = _MANIFEST + """
  release:
    handwritten: two shell scripts and a great deal of reasoning
"""


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A throwaway product: a repo root, a manifest with a name of its own, and a registered context."""
    manifest_path = tmp_path / "sample.yaml"
    manifest_path.write_text(_MANIFEST, encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    ctx = context.ProductContext(name="sample", root=tmp_path, manifest_path=manifest_path)
    monkeypatch.setattr(context, "_current", ctx)
    return ctx


def _target(product):
    return product.root / ".github" / "workflows" / "ci.yml"


# --- generating ---------------------------------------------------------------------------------------


def test_generate_writes_the_workflow_the_manifest_declares(product):
    """The kernel must not know where a product keeps its workflows: the path comes out of the
    declaration, resolved against the product's ROOT from the context."""
    # Arrange / Act
    rc = workflows_task.generate()

    # Assert
    assert rc == 0
    assert _target(product).exists()


def test_the_generated_workflow_runs_the_product_by_its_own_launcher_name(product):
    """`sample.sh`, not `simplon.sh`. The product token comes from the registered context, which is the
    whole of what makes this a kernel mechanism rather than simplon's own script."""
    # Arrange
    workflows_task.generate()

    # Act
    text = _target(product).read_text(encoding="utf-8")

    # Assert
    assert "./sample.sh test all" in text
    assert "simplon.sh" not in text


def test_the_generated_workflow_names_the_manifest_it_came_from(product):
    """A generated file has to say what regenerates it, or the first person to edit it by hand has no
    way of knowing they should not have."""
    # Arrange
    workflows_task.generate()

    # Act
    text = _target(product).read_text(encoding="utf-8")

    # Assert
    assert "GENERATED from sample.yaml" in text


def test_generating_twice_is_quiet_the_second_time(product):
    """Idempotent, and it says which of the two happened rather than reporting success either way."""
    # Arrange
    workflows_task.generate()

    # Act
    rc = workflows_task.generate()

    # Assert
    assert rc == 0


# --- checking -----------------------------------------------------------------------------------------


def test_check_is_green_when_the_committed_file_agrees(product):
    # Arrange
    workflows_task.generate()

    # Act
    rc = workflows_task.generate(check=True)

    # Assert
    assert rc == 0


def test_check_writes_nothing(product):
    """`--check` is a gate. A gate that repaired what it found would report green on a tree that was red
    a moment earlier, and the drift would reach the commit anyway."""
    # Arrange
    workflows_task.generate()
    _target(product).write_text("name: tampered\n", encoding="utf-8")

    # Act
    workflows_task.generate(check=True)

    # Assert
    assert _target(product).read_text(encoding="utf-8") == "name: tampered\n"


def test_a_hand_edited_workflow_makes_check_return_one(product, capsys):
    """SEEN RED (acceptance 5). The property is broken on purpose and the gate is watched failing.

    A workflow whose step no longer matches the manifest is invisible today - this is the whole ticket -
    so what matters is not that something was printed but that the process exits non-zero, because that
    is what a pre-commit hook and a CI step actually read.
    """
    # Arrange
    workflows_task.generate()
    target = _target(product)
    target.write_text(target.read_text(encoding="utf-8").replace("./sample.sh test all", "pytest -q"),
                      encoding="utf-8")

    # Act
    rc = workflows_task.generate(check=True)

    # Assert
    assert rc == 1
    out = capsys.readouterr().out
    assert "-      - run: pytest -q" in out, "the report must show the difference, not merely announce it"
    assert "+      - run: ./sample.sh test all" in out


def test_check_names_the_command_that_regenerates(product, capsys):
    """A gate that says only "no" makes somebody go and find out how. The message carries the fix, and it
    carries the PRODUCT's own token because that is what they have to type."""
    # Arrange
    workflows_task.generate()
    _target(product).write_text("name: tampered\n", encoding="utf-8")

    # Act
    workflows_task.generate(check=True)

    # Assert
    assert "sample support workflows" in capsys.readouterr().out


def test_a_workflow_that_was_never_generated_makes_check_red(product):
    """A fresh checkout that has never generated has to be told to. Drift, not an error - the same call
    `simplon.taskgen.check` makes, and for the same reason: raising here would read as a broken gate."""
    # Arrange / Act
    rc = workflows_task.generate(check=True)

    # Assert
    assert rc == 1


# --- the file nobody declares ---------------------------------------------------------------------------


def test_an_undeclared_workflow_file_makes_check_red(product, capsys):
    """THE case si#40 exists for, as an exit code.

    agile-cockpit ran three assertions against a `.gitlab-ci.yml` that nothing had executed for months
    and they passed the whole time, because from the directory an unmanaged file is indistinguishable
    from a maintained one. This is what makes it distinguishable, and a warning would not have been.
    """
    # Arrange
    workflows_task.generate()
    (product.root / ".github" / "workflows" / "legacy.yml").write_text("name: legacy\n",
                                                                      encoding="utf-8")

    # Act
    rc = workflows_task.generate(check=True)

    # Assert
    assert rc == 1
    assert "legacy.yml" in capsys.readouterr().out


def test_the_complaint_says_both_ways_to_answer_it(product, capsys):
    """Declaring the workflow, or declaring it hand-written. Stated in the message so the fix never
    requires reading the kernel's source - and so that `handwritten:` is a visible option rather than
    something only its author knows about."""
    # Arrange
    (product.root / ".github" / "workflows" / "legacy.yml").write_text("name: legacy\n",
                                                                      encoding="utf-8")

    # Act
    workflows_task.generate(check=True)

    # Assert
    out = capsys.readouterr().out
    assert "workflows:" in out
    assert "handwritten:" in out


def test_generating_also_reports_an_undeclared_file(product, capsys):
    """The scan runs on a WRITE too, and that is deliberate rather than symmetric-for-its-own-sake:
    generating is exactly when a file left behind by a rename stops having an owner, and the run that
    has just rewritten the directory is the cheapest moment to say so."""
    # Arrange
    (product.root / ".github" / "workflows" / "legacy.yml").write_text("name: legacy\n",
                                                                      encoding="utf-8")

    # Act
    rc = workflows_task.generate()

    # Assert
    assert rc == 1
    assert "legacy.yml" in capsys.readouterr().out


# --- the declared decline --------------------------------------------------------------------------------


def test_a_hand_written_workflow_is_accounted_for_rather_than_reported(product, capsys):
    """One manifest line moves a file out of the complaint. That is what makes the decline an answer and
    not a hole."""
    # Arrange
    product.manifest_path.write_text(_WITH_A_HAND_WRITTEN_ONE, encoding="utf-8")
    (product.root / ".github" / "workflows" / "release.yml").write_text("name: release\n",
                                                                       encoding="utf-8")
    workflows_task.generate()
    capsys.readouterr()

    # Act
    rc = workflows_task.generate(check=True)

    # Assert
    assert rc == 0


def test_a_hand_written_workflow_is_named_with_its_reason_on_every_run(product, capsys):
    """Said out loud each time rather than counted.

    The reason is the part that decays: "this one is hand-written" is easy to keep believing after it has
    stopped being true, and a line that repeats the stated reason is what gives somebody the chance to
    notice that it no longer holds.
    """
    # Arrange
    product.manifest_path.write_text(_WITH_A_HAND_WRITTEN_ONE, encoding="utf-8")
    (product.root / ".github" / "workflows" / "release.yml").write_text("name: release\n",
                                                                       encoding="utf-8")

    # Act
    workflows_task.generate(check=True)

    # Assert
    out = capsys.readouterr().out
    assert "release.yml is declared hand-written" in out
    assert "two shell scripts" in out


def test_a_hand_written_workflow_is_left_exactly_as_it_was(product):
    """The manifest declared the file somebody's own; writing to it would make the declaration a lie."""
    # Arrange
    product.manifest_path.write_text(_WITH_A_HAND_WRITTEN_ONE, encoding="utf-8")
    target = product.root / ".github" / "workflows" / "release.yml"
    target.write_text("name: release\n", encoding="utf-8")

    # Act
    workflows_task.generate()

    # Assert
    assert target.read_text(encoding="utf-8") == "name: release\n"


# --- the refusal a product with nothing to generate gets ---------------------------------------------------


def test_a_product_with_no_workflows_section_is_refused_loudly(tmp_path, monkeypatch):
    """And this is why the coordinate is OFFERED rather than placed (si#39's bar): the command reads a
    section, so a product without one would get a command that dies on its first line.

    Refused rather than reported as an empty success, because "this product declares no workflows" and
    "this product's workflows are fine" are different answers, and a run that gave the second for the
    first is the defect this repository keeps finding.
    """
    # Arrange
    manifest_path = tmp_path / "bare.yaml"
    manifest_path.write_text(textwrap.dedent("""
        tasks:
          suite: { impl: "simplon.test_impls:nullary", help: "Run every test." }
        groups:
          test:
            commands:
              all: { task: suite }
        env_groups: []
    """), encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        context.ProductContext(name="bare", root=tmp_path,
                                               manifest_path=manifest_path))

    # Act / Assert
    with pytest.raises(ValueError, match="declares no 'workflows' section"):
        workflows_task.generate(check=True)


# --- a declaration with no file behind it (review B2) --------------------------------------------------


def _said(capsys) -> str:
    """Everything the run said, on BOTH streams.

    `log.error` writes to stderr, which is right - this is an error, and a caller piping stdout into a
    report should not have it silently land in the report. A test reading only `.out` would therefore
    have gone red while the message was there, which is how the first version of these two failed.
    """
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_a_hand_written_declaration_whose_file_is_gone_returns_one(product, capsys):
    """The mirror image of the undeclared file, as an exit code.

    Before this, tidying `release.yml` away left `--check` saying "is declared hand-written" and
    returning 0 - a name with nothing behind it, reported as if somebody were looking after it. That is
    the dead `.gitlab-ci.yml` seen from the other side, and it went green for the same reason: the
    manifest's claim was never checked against the disk.
    """
    # Arrange: declared hand-written, and never written
    product.manifest_path.write_text(_WITH_A_HAND_WRITTEN_ONE, encoding="utf-8")
    workflows_task.generate()
    capsys.readouterr()

    # Act
    rc = workflows_task.generate(check=True)

    # Assert
    assert rc == 1
    said = _said(capsys)
    assert "release.yml is declared hand-written and does not exist" in said
    assert "restore it, or drop the entry" in said


def test_generating_also_refuses_a_declaration_with_no_file(product, capsys):
    """The write path says it too. A run that had just rewritten the directory and still reported success
    over a declaration pointing at nothing would be the quietest place for this to hide."""
    # Arrange
    product.manifest_path.write_text(_WITH_A_HAND_WRITTEN_ONE, encoding="utf-8")

    # Act
    rc = workflows_task.generate()

    # Assert
    assert rc == 1
    assert "does not exist" in _said(capsys)


def test_the_declaration_goes_green_once_the_file_is_back(product, capsys):
    """The pair, so the assertion above is about the file and not about the decline. Restoring the file
    is the whole fix - the manifest never had to change."""
    # Arrange
    product.manifest_path.write_text(_WITH_A_HAND_WRITTEN_ONE, encoding="utf-8")
    workflows_task.generate()
    (product.root / ".github" / "workflows" / "release.yml").write_text("name: release\n",
                                                                       encoding="utf-8")

    # Act
    rc = workflows_task.generate(check=True)

    # Assert
    assert rc == 0
    assert "is declared hand-written: two shell scripts" in _said(capsys)
