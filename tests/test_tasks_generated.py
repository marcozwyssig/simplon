"""IS THE COMMITTED GENERATED FILE WHAT REGENERATING PRODUCES? (si#240)

The question has been invented TWICE in this family of repositories, independently, and it has drawn
blood once. biz-cockpit wrote `verify_spec` - `git diff --exit-code` over its OpenAPI contract - and
called it "the CI staleness gate"; this kernel wrote `test_own_completion.py` for its shell completion.
And `6ddecaf` records what happens without one: a command was added to `simplon.yaml` without
regenerating `deploy/completions/simplon.bash`, and `main` was red with an uncompletable command until
somebody noticed.

THE TEMPLATE'S OWN DEFECT, CARRIED OVER WOULD HAVE BEEN THE WHOLE POINT MISSED. `git diff --exit-code`
over a file git does not track exits 0. So a generated artefact that was never committed - the exact
mistake this gate exists to catch, in its most complete form - would pass it green, and the gate would
be this repository's recurring defect wearing a gate's clothes: an outcome that cannot tell "nothing to
compare" from "compared and matched". Every entry is therefore checked for being TRACKED first, and an
untracked one is a failure with its own sentence rather than a silent pass.

THE GATE HAS SIDE EFFECTS AND SAYS SO. It regenerates into the working tree, because that is what makes
the comparison real - a regeneration into a temporary directory would compare two things the product's
own command never produced side by side. A CI checkout is disposable; a developer is told.

AAA throughout.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplon import context
from simplon.context import ProductContext
from simplon.tasks import generated


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "product"
    root.mkdir()
    for argv in (["init", "-q", "-b", "main"], ["config", "user.email", "g@example.com"],
                 ["config", "user.name", "The Gate"], ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
    return root


def _commit(root: Path, message: str = "seed") -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True,
                   capture_output=True)


def _product(root: Path, monkeypatch, manifest: str) -> None:
    path = root / "demo.yaml"
    path.write_text(manifest, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", root, path))


_MANIFEST = """
generated:
  completion:
    path: out/completion.sh
    by: support completion
"""


# --- the section --------------------------------------------------------------------------------------


def test_a_manifest_with_no_section_says_what_it_needs(tmp_path, monkeypatch):
    # Arrange
    root = _repo(tmp_path)
    _product(root, monkeypatch, "images: {}\n")
    # Act / Assert
    with pytest.raises(ValueError, match=r"`generated:`"):
        generated.declared()


def test_an_entry_without_a_regenerating_command_is_refused(tmp_path, monkeypatch):
    # Arrange
    root = _repo(tmp_path)
    _product(root, monkeypatch, "generated:\n  completion: { path: out/completion.sh }\n")
    # Act / Assert
    with pytest.raises(ValueError, match=r"by:"):
        generated.declared()


def test_an_entry_without_a_path_is_refused(tmp_path, monkeypatch):
    # Arrange
    root = _repo(tmp_path)
    _product(root, monkeypatch, "generated:\n  completion: { by: support completion }\n")
    # Act / Assert
    with pytest.raises(ValueError, match=r"path:"):
        generated.declared()


# --- the gate -----------------------------------------------------------------------------------------


def test_a_file_that_regenerates_identically_passes(tmp_path, monkeypatch):
    # Arrange: a committed artefact, and a regeneration that writes the same bytes
    root = _repo(tmp_path)
    (root / "out").mkdir()
    (root / "out" / "completion.sh").write_text("# generated\n", encoding="utf-8")
    _product(root, monkeypatch, _MANIFEST)
    _commit(root)
    monkeypatch.setattr(generated, "_regenerate",
                        lambda entry, root: (root / entry.path).write_text("# generated\n",
                                                                          encoding="utf-8") and 0 or 0)
    # Act
    rc = generated.check()
    # Assert
    assert rc == 0


def test_a_file_that_regenerates_differently_fails_and_names_it(tmp_path, monkeypatch, capsys):
    # Arrange: the committed bytes are stale - this is `6ddecaf`, reproduced
    root = _repo(tmp_path)
    (root / "out").mkdir()
    (root / "out" / "completion.sh").write_text("# stale\n", encoding="utf-8")
    _product(root, monkeypatch, _MANIFEST)
    _commit(root)
    monkeypatch.setattr(generated, "_regenerate",
                        lambda entry, root: (root / entry.path).write_text("# fresh\n",
                                                                           encoding="utf-8") and 0 or 0)
    # Act
    rc = generated.check()
    # Assert: red, and the report names the file and the command that refreshes it
    assert rc == 1
    said = capsys.readouterr().out + capsys.readouterr().err


def test_an_untracked_generated_file_is_a_failure_and_not_a_silent_pass(tmp_path, monkeypatch):
    """The template's own defect, and the reason this gate is not six lines of `git diff`.

    `git diff --exit-code` over a file git does not track exits 0. The artefact that was never committed
    at all is the most complete form of the mistake this gate exists to catch, and the borrowed
    implementation would have called it green."""
    # Arrange: generated, present, and never committed
    root = _repo(tmp_path)
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    _commit(root)
    (root / "out").mkdir()
    (root / "out" / "completion.sh").write_text("# generated\n", encoding="utf-8")
    _product(root, monkeypatch, _MANIFEST)
    monkeypatch.setattr(generated, "_regenerate",
                        lambda entry, root: (root / entry.path).write_text("# generated\n",
                                                                           encoding="utf-8") and 0 or 0)
    # Act
    rc = generated.check()
    # Assert: red, because nothing was compared
    assert rc == 1


def test_a_regeneration_that_fails_is_not_read_as_freshness(tmp_path, monkeypatch):
    """A command that could not run leaves the file exactly as it was, so the diff is empty and the gate
    would say `fresh`. Two meanings for one outcome, which is what this repository refuses."""
    # Arrange
    root = _repo(tmp_path)
    (root / "out").mkdir()
    (root / "out" / "completion.sh").write_text("# generated\n", encoding="utf-8")
    _product(root, monkeypatch, _MANIFEST)
    _commit(root)
    monkeypatch.setattr(generated, "_regenerate", lambda entry, root: 3)
    # Act
    rc = generated.check()
    # Assert
    assert rc == 1
