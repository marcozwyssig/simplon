"""Unit tests for simplon.tasks.vcs (netctl#1280, epic #1274 slice S6): the framework-free skin
around simplon.tasks.gitops. Nothing here shells out to git - every simplon.tasks.gitops function is monkeypatched, so
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

from simplon import context, githubpackages
from simplon.tasks import vcs as vcs_cmd
from simplon.context import ProductContext


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
    monkeypatch.setattr(vcs_cmd.gitops, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.gitops, "commit", lambda message: 0)

    # act
    vcs_cmd.commit(["a", "message"])

    # assert: ROOT came from the registered ProductContext, not a product import
    assert seen["root"] == _registered_context.root


def test_push_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.gitops, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.gitops, "push", lambda: 0)

    # act
    vcs_cmd.push()

    assert seen["root"] == _registered_context.root


def test_prune_branches_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.gitops, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.gitops, "prune_branches", lambda dry, remote, unmerged: 0)

    # act
    vcs_cmd.prune_branches()

    assert seen["root"] == _registered_context.root


def test_submodules_configures_vcs_with_root_from_the_registered_context(monkeypatch, _registered_context):
    # arrange
    seen = {}
    monkeypatch.setattr(vcs_cmd.gitops, "configure", lambda root: seen.setdefault("root", root))
    monkeypatch.setattr(vcs_cmd.gitops, "init_submodule", lambda: 0)

    # act
    vcs_cmd.submodules()

    assert seen["root"] == _registered_context.root


# --- return-code propagation --------------------------------------------------------------------------


def test_commit_joins_the_argument_words_and_propagates_the_exit_code(monkeypatch, _registered_context):
    # arrange
    monkeypatch.setattr(vcs_cmd.gitops, "configure", lambda root: None)
    seen = {}

    def fake_commit(message):
        seen["message"] = message
        return 1

    monkeypatch.setattr(vcs_cmd.gitops, "commit", fake_commit)

    # act
    rc = vcs_cmd.commit(["fix", "the", "thing"])

    # assert: the body RETURNS the code; the generated wrapper is what turns it into a process exit
    assert seen["message"] == "fix the thing"
    assert rc == 1


def test_commit_with_no_words_joins_to_an_empty_message(monkeypatch, _registered_context):
    # arrange
    monkeypatch.setattr(vcs_cmd.gitops, "configure", lambda root: None)
    seen = {}

    def fake_commit(message):
        seen["message"] = message
        return 0

    monkeypatch.setattr(vcs_cmd.gitops, "commit", fake_commit)

    # act
    vcs_cmd.commit(None)

    # assert
    assert seen["message"] == ""


def test_prune_branches_forwards_its_flags_to_vcs_prune_branches(monkeypatch, _registered_context):
    # arrange
    monkeypatch.setattr(vcs_cmd.gitops, "configure", lambda root: None)
    calls = {}

    def fake_prune(*, dry, remote, unmerged):
        calls.update(dry=dry, remote=remote, unmerged=unmerged)
        return 0

    monkeypatch.setattr(vcs_cmd.gitops, "prune_branches", fake_prune)

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
    import simplon.tasks.vcs as module

    # act
    source = Path(module.__file__).read_text(encoding="utf-8")

    # assert
    assert "typer.Exit" not in source
    assert "\nimport typer" not in source


# --- auth-scopes: the gh token's package permissions -------------------------------------------------

def test_the_refresh_asks_for_the_package_scopes_the_registry_needs(monkeypatch):
    # arrange: a terminal, no environment token, and a gh token without the package scopes
    asked = []
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(vcs_cmd.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(vcs_cmd.gitops, "gh_scopes", lambda: ("gist", "repo"))
    monkeypatch.setattr(vcs_cmd.gitops, "refresh_scopes", lambda scopes: asked.append(tuple(scopes)) or 0)

    # act
    rc = vcs_cmd.auth_scopes()

    # assert: exactly the scopes githubpackages declares, so the two never drift apart
    assert asked == [githubpackages.PACKAGE_SCOPES]
    assert rc == 0


def test_nothing_is_refreshed_when_the_token_already_carries_the_scopes(monkeypatch):
    # arrange
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(vcs_cmd.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(vcs_cmd.gitops, "gh_scopes",
                        lambda: ("repo", "read:packages", "write:packages"))
    monkeypatch.setattr(vcs_cmd.gitops, "refresh_scopes", _must_not_run)

    # act / assert: idempotent, so it can be run before every publish without a browser opening
    assert vcs_cmd.auth_scopes() == 0


def test_an_environment_token_is_named_instead_of_refreshing_a_token_nobody_reads(monkeypatch):
    # arrange: GITHUB_TOKEN wins in githubpackages.token(), so a refreshed gh token would never be used
    monkeypatch.setenv("GITHUB_TOKEN", "from-the-environment")
    monkeypatch.setattr(vcs_cmd.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(vcs_cmd.gitops, "refresh_scopes", _must_not_run)

    # act / assert: says so and does nothing, rather than appearing to fix something
    assert vcs_cmd.auth_scopes() == 0


def test_without_a_terminal_it_does_not_start_a_browser_flow_nobody_can_answer(monkeypatch):
    # arrange: `gh auth refresh` is a device flow - in CI it would hang until the job times out
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(vcs_cmd.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(vcs_cmd.gitops, "refresh_scopes", _must_not_run)

    # act / assert
    assert vcs_cmd.auth_scopes() == 0


def _must_not_run(*args, **kwargs):
    raise AssertionError("must not have refreshed the token")
