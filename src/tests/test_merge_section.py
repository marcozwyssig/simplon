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


@pytest.mark.parametrize("value", ["manual", True, {"auto": True}, ["auto"]])
def test_other_value_is_refused(value):
    # act / assert: the message names the only value there is
    with pytest.raises(ValueError, match="auto"):
        merge.declared({"merge": value})


def test_a_manifest_with_a_bad_merge_does_not_load():
    # act / assert: refused by the loader, before any command or workflow meets it
    with pytest.raises(ValueError, match="auto"):
        manifest.load(_OK + "\nmerge: manual\n")
