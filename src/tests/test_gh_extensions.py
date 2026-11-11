"""si#630: the gh extensions a product declares in `gh: extensions:`, read from the manifest and installed by
`support install` after the gh gate.

The runner is a fake that records every argv and answers what the test put in it, so what is asserted is
what gh was asked to do. What a fake cannot show is how the real gh behaves; that was measured against gh
2.103.3 in a throwaway GH_CONFIG_DIR and XDG_DATA_HOME (see `adapters/gh.py`, "RE-PINNED, NOT REFUSED"), and
the fake answers the way the measurement did. AAA throughout.
"""
from __future__ import annotations

import subprocess

import pytest
import yaml

from conftest import ROOT
from simplon.adapters import gh
from simplon.adapters.hostinstall import State
from simplon.kernel.run import Result

GH_STACK = "gh stack\tgithub/gh-stack\t{}\n"


class FakeGh:
    """`gh extension list` answers `listing`; every other command answers `answers.get(verb, rc 0)`."""

    def __init__(self, listing: str = "", list_rc: int = 0, answers: dict | None = None):
        self.calls: list[list[str]] = []
        self.listing, self.list_rc, self.answers = listing, list_rc, answers or {}

    def __call__(self, argv, timeout=None, **kw):
        self.calls.append(list(argv))
        assert timeout is not None, "every gh call has a time limit"
        if argv[1:3] == ["extension", "list"]:
            return Result(self.list_rc, self.listing, "" if self.list_rc == 0 else "HTTP 401")
        answer = self.answers.get((argv[1], argv[2]))
        if isinstance(answer, BaseException):
            raise answer
        return answer or Result(0, "", "")


# --- declared_extensions: the `gh:` section -------------------------------------------------------------

def test_no_section_declares_nothing():
    # act / assert
    assert gh.declared_extensions({"toolchains": ["gh"]}, ("gh",)) == ()


def test_entries_are_read_in_order_with_their_pins():
    # arrange
    data = {"gh": {"extensions": ["github/gh-stack@v0.3.0", "dlvhdr/gh-dash"]}}

    # act
    extensions = gh.declared_extensions(data, ("gh",))

    # assert
    assert extensions == (gh.Extension("github/gh-stack", "v0.3.0"), gh.Extension("dlvhdr/gh-dash", ""))
    assert [str(e) for e in extensions] == ["github/gh-stack@v0.3.0", "dlvhdr/gh-dash"]


def test_an_empty_extensions_list_declares_nothing():
    # act / assert
    assert gh.declared_extensions({"gh": {"extensions": None}}, ("gh",)) == ()


def test_a_section_without_the_gh_toolchain_is_refused():
    # act / assert: a declaration nothing would read
    with pytest.raises(ValueError, match="but 'gh' is not in 'toolchains:'"):
        gh.declared_extensions({"gh": {"extensions": ["github/gh-stack"]}}, ("claude",), source="demo.yaml")


@pytest.mark.parametrize("section, fragment", [
    ("github/gh-stack", "must be a mapping with 'extensions:'"),
    ({"extension": ["github/gh-stack"]}, r"declares unknown key\(s\) extension"),
    ({"extensions": "github/gh-stack"}, "must be a list of 'owner/repo'"),
])
def test_a_misshapen_section_is_refused(section, fragment):
    # act / assert
    with pytest.raises(ValueError, match=fragment):
        gh.declared_extensions({"gh": section}, ("gh",), source="demo.yaml")


@pytest.mark.parametrize("entry", ["gh-stack", "github/gh-stack@", "github/gh stack", "a/b/c", "github/x@v 1",
                                   7, None, {"repo": "github/gh-stack"}])
def test_an_entry_that_is_not_owner_repo_is_refused(entry):
    # act / assert
    with pytest.raises(ValueError, match="is not 'owner/repo' or 'owner/repo@<version>'"):
        gh.declared_extensions({"gh": {"extensions": [entry]}}, ("gh",), source="demo.yaml")


def test_a_repo_named_twice_is_refused_whatever_its_pins_and_case():
    # act / assert
    with pytest.raises(ValueError, match="names 'GitHub/gh-stack' twice"):
        gh.declared_extensions({"gh": {"extensions": ["github/gh-stack@v0.3.0", "GitHub/gh-stack"]}}, ("gh",))


def test_simplons_own_manifest_declares_gh_stack():
    # arrange
    data = yaml.safe_load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))

    # act
    extensions = gh.declared_extensions(data, tuple(data["toolchains"]))

    # assert
    assert [e.repo for e in extensions] == ["github/gh-stack"]


# --- ensure_extensions: what gh is asked to do --------------------------------------------------------

STACK_PINNED = (gh.Extension("github/gh-stack", "v0.3.0"),)


def test_nothing_declared_asks_gh_nothing():
    # arrange
    fake = FakeGh()

    # act / assert
    assert gh.ensure_extensions((), runner=fake) == []
    assert fake.calls == []


def test_a_missing_pinned_extension_is_installed_at_its_pin():
    # arrange
    fake = FakeGh()

    # act
    [(_, outcome)] = gh.ensure_extensions(STACK_PINNED, runner=fake)

    # assert
    assert outcome.state is State.INSTALLED
    assert fake.calls[1] == ["gh", "extension", "install", "github/gh-stack", "--pin", "v0.3.0"]


def test_a_missing_unpinned_extension_is_installed_without_a_pin():
    # arrange
    fake = FakeGh()

    # act
    [(_, outcome)] = gh.ensure_extensions((gh.Extension("github/gh-stack"),), runner=fake)

    # assert
    assert outcome.state is State.INSTALLED
    assert fake.calls[1] == ["gh", "extension", "install", "github/gh-stack"]


def test_an_extension_at_its_pin_is_present_and_nothing_is_installed():
    # arrange
    fake = FakeGh(listing=GH_STACK.format("v0.3.0"))

    # act
    [(_, outcome)] = gh.ensure_extensions(STACK_PINNED, runner=fake)

    # assert: the second run of `support install` installs nothing
    assert outcome.state is State.PRESENT and outcome.detail == "v0.3.0"
    assert fake.calls == [["gh", "extension", "list"]]


def test_an_unpinned_extension_is_left_alone_at_any_version():
    # arrange
    fake = FakeGh(listing=GH_STACK.format("v0.1.0"))

    # act
    [(_, outcome)] = gh.ensure_extensions((gh.Extension("GitHub/gh-stack"),), runner=fake)

    # assert: installed once and left alone, and GitHub's names are case-insensitive
    assert outcome.state is State.PRESENT
    assert len(fake.calls) == 1


def test_a_git_extension_pinned_to_a_full_sha_is_present_at_the_listed_prefix():
    # arrange: measured, `gh-f --pin <sha>` is listed at the first eight hex digits
    fake = FakeGh(listing="gh f\tgennaro-tedesco/gh-f\t59a2c598\n")
    pinned = (gh.Extension("gennaro-tedesco/gh-f", "59a2c59829bcafab47d2b776c8a1738b0473edeb"),)

    # act
    [(_, outcome)] = gh.ensure_extensions(pinned, runner=fake)

    # assert
    assert outcome.state is State.PRESENT


def test_an_extension_at_another_version_is_removed_and_installed_at_the_pin():
    # arrange: measured, `install --pin` over an install is a silent no-op, so the list decides
    fake = FakeGh(listing=GH_STACK.format("v0.2.1"))

    # act
    [(_, outcome)] = gh.ensure_extensions(STACK_PINNED, runner=fake)

    # assert
    assert outcome.state is State.INSTALLED and outcome.detail == "re-pinned from v0.2.1"
    assert fake.calls[1:] == [["gh", "extension", "remove", "github/gh-stack"],
                              ["gh", "extension", "install", "github/gh-stack", "--pin", "v0.3.0"]]


def test_a_re_pin_whose_install_fails_says_the_extension_is_gone():
    # arrange: measured wording for a pin no release has
    fake = FakeGh(listing=GH_STACK.format("v0.2.1"), answers={
        ("extension", "install"): Result(1, "", "X Could not find a release of github/gh-stack for v9.9.9\n")})

    # act
    [(_, outcome)] = gh.ensure_extensions((gh.Extension("github/gh-stack", "v9.9.9"),), runner=fake)

    # assert
    assert outcome.state is State.FAILED
    assert "removed v0.2.1 to re-pin" in outcome.detail and "it is not installed now" in outcome.detail
    assert "Could not find a release" in outcome.detail


def test_a_failed_remove_installs_nothing():
    # arrange
    fake = FakeGh(listing=GH_STACK.format("v0.2.1"),
                  answers={("extension", "remove"): Result(1, "", "permission denied\n")})

    # act
    [(_, outcome)] = gh.ensure_extensions(STACK_PINNED, runner=fake)

    # assert
    assert outcome.state is State.FAILED and "at v0.2.1, not the pin" in outcome.detail
    assert ["gh", "extension", "install", "github/gh-stack", "--pin", "v0.3.0"] not in fake.calls


def test_every_extension_is_attempted_after_one_failed():
    # arrange
    fake = FakeGh(answers={("extension", "install"): Result(1, "", "X boom\n")})
    declared = (gh.Extension("a/gh-one"), gh.Extension("b/gh-two"))

    # act
    outcomes = gh.ensure_extensions(declared, runner=fake)

    # assert
    assert [o.state for _, o in outcomes] == [State.FAILED, State.FAILED]
    assert [c[3] for c in fake.calls[1:]] == ["a/gh-one", "b/gh-two"]
    assert outcomes[0][1].detail == "gh extension install exited 1: X boom"


def test_a_failed_list_is_not_an_empty_one():
    # arrange: a probe that failed says nothing about what is installed
    fake = FakeGh(list_rc=1)

    # act
    outcomes = gh.ensure_extensions(STACK_PINNED, runner=fake)

    # assert: nothing installed on the strength of a failed probe, and the failure is the outcome
    assert [o.state for _, o in outcomes] == [State.FAILED]
    assert "gh extension list exited 1" in outcomes[0][1].detail
    assert fake.calls == [["gh", "extension", "list"]]


def test_a_gh_that_is_not_logged_in_skips_every_extension_and_names_the_way_out():
    # arrange: measured, `gh extension list` with no token exits 4 ("gh auth login")
    fake = FakeGh(list_rc=4)
    declared = (gh.Extension("github/gh-stack", "v0.3.0"), gh.Extension("dlvhdr/gh-dash"))

    # act
    outcomes = gh.ensure_extensions(declared, runner=fake)

    # assert: skipped, not failed and not present - and nothing installed on the strength of no answer
    assert [o.state for _, o in outcomes] == [State.SKIPPED, State.SKIPPED]
    assert all("gh auth login" in o.detail for _, o in outcomes)
    assert fake.calls == [["gh", "extension", "list"]]


def test_an_install_that_fails_with_a_token_is_still_failed():
    # arrange: the list answered (gh is logged in), the install did not
    fake = FakeGh(answers={("extension", "install"): Result(4, "", "HTTP 401: Bad credentials\n")})

    # act
    [(_, outcome)] = gh.ensure_extensions(STACK_PINNED, runner=fake)

    # assert: only the probe's rc 4 means "not logged in"
    assert outcome.state is State.FAILED


def test_a_hanging_install_is_failed_not_waited_on():
    # arrange
    fake = FakeGh(answers={("extension", "install"): subprocess.TimeoutExpired(["gh"], 600)})

    # act
    [(_, outcome)] = gh.ensure_extensions(STACK_PINNED, runner=fake)

    # assert
    assert outcome.state is State.FAILED and "timed out" in outcome.detail
