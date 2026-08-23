"""Unit tests for delivery.commands.vcs (netctl#1280, epic #1274 slice S6): the framework-free skin
around delivery.vcs. Nothing here shells out to git - every delivery.vcs function is monkeypatched, so
the suite proves the wiring (ROOT resolution, parameter survival, return-code propagation) without
touching a real repository.

Since netctl#1444 these bodies RETURN an exit code instead of raising `typer.Exit`, and their option
declarations live in the manifest's `params:` rather than in their signatures - so what this suite
asserts about the signatures is now the PAYLOAD (names, types, defaults), which is what the generator
introspects. The presentation is asserted where it now lives, in netctl's manifest and its CLI-surface
golden. AAA throughout.
"""
import inspect
from pathlib import Path

import pytest

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

    # act
    vcs_cmd.commit(["a", "message"])

    # assert: ROOT came from the registered ProductContext, not a product import
    assert seen["root"] == _registered_context.root


def test_push_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.vcs, "push", lambda: 0)

    # act
    vcs_cmd.push()

    assert seen["root"] == _registered_context.root


def test_prune_branches_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.vcs, "prune_branches", lambda dry, remote, unmerged: 0)

    # act
    vcs_cmd.prune_branches()

    assert seen["root"] == _registered_context.root


def test_submodules_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.vcs, "init_submodule", lambda: 0)

    # act
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

    # act
    rc = vcs_cmd.commit(["fix", "the", "thing"])

    # assert: the body RETURNS the code; the generated wrapper is what turns it into a process exit
    assert seen["message"] == "fix the thing"
    assert rc == 1


def test_commit_with_no_words_joins_to_an_empty_message(monkeypatch, _registered_context):
    # arrange
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: None)
    seen = {}

    def fake_commit(message):
        seen["message"] = message
        return 0

    monkeypatch.setattr(vcs_cmd.vcs, "commit", fake_commit)

    # act
    vcs_cmd.commit(None)

    # assert
    assert seen["message"] == ""


def test_prune_branches_forwards_its_flags_to_vcs_prune_branches(monkeypatch, _registered_context):
    # arrange
    monkeypatch.setattr(vcs_cmd.vcs, "configure", lambda root: None)
    calls = {}

    def fake_prune(*, dry, remote, unmerged):
        calls.update(dry=dry, remote=remote, unmerged=unmerged)
        return 0

    monkeypatch.setattr(vcs_cmd.vcs, "prune_branches", fake_prune)

    # act
    vcs_cmd.prune_branches(dry_run=True, remote=True, unmerged=True)

    # assert
    assert calls == {"dry": True, "remote": True, "unmerged": True}


# --- the payload signatures the generator introspects (netctl#1444) ------------------------------------


def test_commit_keeps_its_variadic_message_parameter():
    # arrange / act
    signature = inspect.signature(vcs_cmd.commit)

    # assert: the ANNOTATION is what makes the generated wrapper render `nargs=-1`; without it Typer
    # would produce a single `--message TEXT` and the golden would catch it
    assert list(signature.parameters) == ["message"]
    assert signature.parameters["message"].annotation == "list[str] | None"
    assert signature.parameters["message"].default is None


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


def test_prune_branches_keeps_the_dry_run_remote_and_unmerged_parameters():
    # arrange: the sharp case named in the design - three flags a bare delegate would silently drop.
    # Their DECLS moved to the manifest in netctl#1444; what has to survive here is the payload.
    # act
    signature = inspect.signature(vcs_cmd.prune_branches)

    # assert
    assert list(signature.parameters) == ["dry_run", "remote", "unmerged"]
    assert [p.annotation for p in signature.parameters.values()] == ["bool", "bool", "bool"]
    assert [p.default for p in signature.parameters.values()] == [False, False, False]


def test_no_body_in_this_module_raises_typer_exit_any_more():
    # arrange: the point of netctl#1444 - these are callable from anything, not only a Click parser
    import delivery.commands.vcs as module

    # act
    source = Path(module.__file__).read_text(encoding="utf-8")

    # assert
    assert "typer.Exit" not in source
    assert "\nimport typer" not in source
