"""The `merge:` section (si#874): `merge: auto` switches the derived auto-merge workflow on, and what refuses
any other value at LOAD. AAA throughout."""
import pytest

from simplon.manifest import load as manifest
from simplon.manifest import merge

from test_manifest import _OK


def test_auto_is_true():
    # act / assert
    assert merge.declared({"merge": "auto"}) is True


def test_absent_is_false():
    # act / assert: no `merge:` is the normal case, not a failure
    assert merge.declared({}) is False


@pytest.mark.parametrize("value", ["manual", "Auto", None, True, {"auto": True}, ["auto"]])
def test_other_value_is_refused(value):
    # act / assert: the message names the only value there is
    with pytest.raises(ValueError, match="auto"):
        merge.declared({"merge": value})


def test_a_manifest_with_a_bad_merge_does_not_load():
    # act / assert: refused by the loader, before any command or workflow meets it
    with pytest.raises(ValueError, match="auto"):
        manifest.load(_OK + "\nmerge: manual\n")


def test_the_docs_table_quotes_every_rule_of_the_model():
    """The `merge:` section of how/manifest.md quotes each rule's key, reason and source, a second source for
    strings the model owns: a reason reworded in the model turns this red until the page says the same."""
    # arrange
    from pathlib import Path

    from simplon.model import automerge as policy
    page = (Path(__file__).resolve().parents[1] / "site" / "content" / "how" / "manifest.md").read_text("utf-8")

    # act / assert
    for key, reason, source in policy.RULES:
        assert f"| `{key}` | {reason} | {source} |" in page
    for scope, access, reason in policy.PERMISSIONS:
        assert f"| `{scope}: {access}` | {reason} |" in page
