"""Unit tests for delivery.commands.vcs (netctl#1280, epic #1274 slice S6): the Typer callback skin
around delivery.vcs. Nothing here shells out to git - every delivery.vcs function is monkeypatched, so
the suite proves the wiring (ROOT resolution, option survival, return-code propagation) without touching
a real repository. AAA throughout.
"""
import inspect
from pathlib import Path

import pytest
import typer

from delivery import context
from delivery.commands import vcs as vcs_cmd
from delivery.context import ProductContext


@pytest.fixture(autouse=True)
def _registered_context(monkeypatch, tmp_path):
    # every callback resolves ROOT through context.current(); register a fake product for each test
    ctx = ProductContext("sample", tmp_path / "repo", tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    return ctx


# --- ROOT resolution ---------------------------------------------------------------------------------


def test_commit_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.vcs, "commit", lambda message: 0)

    # act / assert: the callback always exits (raise typer.Exit), never returns a value
    with pytest.raises(typer.Exit):
        vcs_cmd.commit(["a", "message"])

    # assert: ROOT came from the registered ProductContext, not a product import
    assert seen["root"] == _registered_context.root


def test_push_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.vcs, "push", lambda: 0)

    # act / assert
    with pytest.raises(typer.Exit):
        vcs_cmd.push()

    assert seen["root"] == _registered_context.root


def test_prune_branches_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.vcs, "prune_branches", lambda dry, remote, unmerged: 0)

    # act / assert
    with pytest.raises(typer.Exit):
        vcs_cmd.prune_branches()

    assert seen["root"] == _registered_context.root


def test_submodules_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.vcs, "init_submodule", lambda: 0)

    # act / assert
    with pytest.raises(typer.Exit):
        vcs_cmd.submodules()

    assert seen["root"] == _registered_context.root


# --- return-code propagation --------------------------------------------------------------------------


def test_commit_joins_the_argument_words_and_propagates_the_exit_code(monkeypatch, _registered_context):
    # arrange
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: None)
    seen = {}

    def fake_commit(message):
        seen["message"] = message
        return 1

    monkeypatch.setattr(vcs_cmd.vcs, "commit", fake_commit)

    # act / assert
    with pytest.raises(typer.Exit) as excinfo:
        vcs_cmd.commit(["fix", "the", "thing"])

    assert seen["message"] == "fix the thing"
    assert excinfo.value.exit_code == 1


def test_commit_with_no_words_joins_to_an_empty_message(monkeypatch, _registered_context):
    # arrange
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: None)
    seen = {}

    def fake_commit(message):
        seen["message"] = message
        return 0

    monkeypatch.setattr(vcs_cmd.vcs, "commit", fake_commit)

    # act / assert
    with pytest.raises(typer.Exit):
        vcs_cmd.commit(None)

    assert seen["message"] == ""


def test_prune_branches_forwards_its_flags_to_vcs_prune_branches(monkeypatch, _registered_context):
    # arrange
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: None)
    calls = {}

    def fake_prune(*, dry, remote, unmerged):
        calls.update(dry=dry, remote=remote, unmerged=unmerged)
        return 0

    monkeypatch.setattr(vcs_cmd.vcs, "prune_branches", fake_prune)

    # act / assert
    with pytest.raises(typer.Exit):
        vcs_cmd.prune_branches(dry_run=True, remote=True, unmerged=True)

    assert calls == {"dry": True, "remote": True, "unmerged": True}


# --- the Typer signatures the manifest resolves directly (a bare delegate would drop these) -----------


def test_commit_keeps_its_positional_message_argument():
    # arrange / act
    signature = inspect.signature(vcs_cmd.commit)

    # assert
    assert list(signature.parameters) == ["message"]
    assert signature.parameters["message"].default.help == "commit message"


def test_push_takes_no_options():
    # arrange / act
    signature = inspect.signature(vcs_cmd.push)

    # assert
    assert list(signature.parameters) == []


def test_submodules_takes_no_options():
    # arrange / act
    signature = inspect.signature(vcs_cmd.submodules)

    # assert
    assert list(signature.parameters) == []


def test_prune_branches_keeps_the_dry_run_remote_and_unmerged_options():
    # arrange: the sharp case named in the design - three flags a bare delegate would silently drop
    # act
    signature = inspect.signature(vcs_cmd.prune_branches)

    # assert
    assert list(signature.parameters) == ["dry_run", "remote", "unmerged"]
    assert signature.parameters["dry_run"].default.param_decls == ("--dry-run", "-n")
    assert signature.parameters["remote"].default.param_decls == ("--remote",)
    assert signature.parameters["unmerged"].default.param_decls == ("--unmerged",)
