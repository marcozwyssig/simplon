"""Unit tests for simplon.tasks.hosttools - `support install`, the command that provisions the host
tooling the kernel itself cannot work without. Nothing here installs anything: every gate is
monkeypatched, so the suite proves what the command DECIDES and reports. AAA throughout.
"""
import pytest
import yaml

from simplon.manifest import context
from simplon.adapters import oras
from simplon.manifest.context import ProductContext
from simplon.tasks import hosttools


@pytest.fixture(autouse=True)
def _registered_context(monkeypatch, tmp_path):
    monkeypatch.setattr(context, "_current",
                        ProductContext("sample", tmp_path / "repo", tmp_path / "sample.yaml"))
    # si#525: `support install` now reads the manifest for the `claude` toolchain, so it has to exist
    (tmp_path / "sample.yaml").write_text("product: sample\n", encoding="utf-8")


def test_it_provisions_oras(monkeypatch):
    # arrange
    provisioned = []
    monkeypatch.setattr(oras, "ensure_oras", lambda: provisioned.append(1))

    # act
    rc = hosttools.install()

    # assert
    assert provisioned == [1]
    assert rc == 0


def test_a_tool_that_could_not_be_provided_is_reported_as_a_failed_command(monkeypatch):
    # arrange: the gate exhausted package manager AND download
    def refuse():
        raise oras.OrasError("no oras and no way to get one")
    monkeypatch.setattr(oras, "ensure_oras", refuse)

    # act
    rc = hosttools.install()

    # assert: a non-zero exit, not a traceback - this is a command, not a library call
    assert rc == 1


# --- si#526: the brew and gh toolchains ---------------------------------------------------------------------

from simplon.adapters import brew, gh  # noqa: E402
from simplon.adapters.hostinstall import Outcome, State  # noqa: E402
from simplon.tasks import claudeplugins, profiles  # noqa: E402


def _declare(tmp_path, *names):
    lines = "".join(f"  - {name}\n" for name in names)
    (tmp_path / "sample.yaml").write_text(f"product: sample\ntoolchains:\n{lines}" if names
                                          else "product: sample\n", encoding="utf-8")


@pytest.fixture
def gates(monkeypatch):
    """Recorders in place of the real gates; each answers what the test put in `answers`."""
    order, answers = [], {}
    monkeypatch.setattr(oras, "ensure_oras", lambda: order.append("oras"))
    def fake(name):
        def ensure(**kw):
            order.append(name)
            return answers.get(name, Outcome(State.PRESENT))
        return ensure
    monkeypatch.setattr(brew, "ensure", fake("brew"))
    monkeypatch.setattr(gh, "ensure", fake("gh"))
    return order, answers


def test_undeclared_gh_and_brew_are_not_asked(gates, tmp_path, capsys):
    # arrange
    order, _ = gates
    _declare(tmp_path)

    # act
    rc = hosttools.install()

    # assert: OFF is silent, too
    assert rc == 0
    assert order == ["oras"]
    out = capsys.readouterr()
    assert "gh" not in out.out + out.err and "brew" not in out.out + out.err


def test_install_runs_brew_before_gh_so_gh_can_use_it(gates, tmp_path):
    # arrange
    order, _ = gates
    _declare(tmp_path, "gh", "brew")

    # act
    hosttools.install()

    # assert
    assert order == ["brew", "oras", "gh"]


def test_no_route_for_gh_fails_the_command(gates, tmp_path):
    # arrange
    _, answers = gates
    answers["gh"] = Outcome(State.NO_ROUTE, "no brew, winget or apt")
    _declare(tmp_path, "gh")

    # act
    rc = hosttools.install()

    # assert
    assert rc == 1


def test_skipped_brew_does_not_fail_the_command(gates, tmp_path):
    # arrange
    _, answers = gates
    answers["brew"] = Outcome(State.SKIPPED, "Homebrew does not run on Windows")
    _declare(tmp_path, "brew")

    # act
    rc = hosttools.install()

    # assert
    assert rc == 0


def test_every_gate_runs_after_one_failed(gates, tmp_path):
    # arrange
    order, answers = gates
    answers["brew"] = Outcome(State.FAILED, "install.sh exited 1")
    _declare(tmp_path, "brew", "gh")

    # act
    rc = hosttools.install()

    # assert
    assert rc == 1
    assert order == ["brew", "oras", "gh"]


def test_a_broken_toolchains_list_is_reported_and_the_other_gates_still_run(gates, tmp_path):
    # arrange
    order, _ = gates
    _declare(tmp_path, "brwe")

    # act
    rc = hosttools.install()

    # assert
    assert rc == 1
    assert order == ["oras"]


def test_brew_is_a_known_toolchain():
    # act / assert
    assert "brew" in profiles.known_toolchains()


def test_github_plugin_requires_gh():
    # act
    eff = claudeplugins.effective({"product": "x", "toolchains": ["claude"]})

    # assert
    assert eff is not None and eff.needs[f"github@{claudeplugins.BUILTIN_MARKETPLACE}"] == ("gh",)


def test_an_unreadable_manifest_is_reported_and_the_other_gates_still_run(gates, tmp_path):
    # arrange: final review - manifest_data() raises RuntimeError, not ValueError, on broken YAML
    order, _ = gates
    (tmp_path / "sample.yaml").write_text("product: sample\ntoolchains: [gh\n", encoding="utf-8")

    # act
    rc = hosttools.install()

    # assert
    assert rc == 1
    assert order == ["oras"]


# --- si#630: the gh extensions a product declares ---------------------------------------------------------

from simplon.adapters import hostinstall  # noqa: E402


def _declare_extensions(tmp_path, toolchains, extensions):
    (tmp_path / "sample.yaml").write_text(yaml.safe_dump(
        {"product": "sample", "toolchains": list(toolchains), "gh": {"extensions": list(extensions)}}),
        encoding="utf-8")


@pytest.fixture
def extensions(gates, monkeypatch):
    """The gh gate's recorder plus a recorder for `gh.ensure_extensions`, answering `answers["ext"]`."""
    order, answers = gates
    asked = []

    def ensure_extensions(declared):
        order.append("gh extensions")
        asked.extend(str(e) for e in declared)
        return [(e, answers.get("ext", Outcome(State.INSTALLED))) for e in declared]
    monkeypatch.setattr(gh, "ensure_extensions", ensure_extensions)
    monkeypatch.setattr(hostinstall, "runs", lambda tool, env=None: True)
    return order, answers, asked


def test_declared_extensions_are_installed_after_the_gh_gate(extensions, tmp_path, capsys):
    # arrange
    order, _, asked = extensions
    _declare_extensions(tmp_path, ["gh"], ["github/gh-stack@v0.3.0", "dlvhdr/gh-dash"])

    # act
    rc = hosttools.install()

    # assert: each one reported in its own line
    assert rc == 0
    assert order == ["oras", "gh", "gh extensions"]
    assert asked == ["github/gh-stack@v0.3.0", "dlvhdr/gh-dash"]
    out = capsys.readouterr()
    assert "gh extension github/gh-stack@v0.3.0 installed" in out.out + out.err
    assert "gh extension dlvhdr/gh-dash installed" in out.out + out.err


def test_a_failed_extension_fails_the_command(extensions, tmp_path, capsys):
    # arrange
    _, answers, _ = extensions
    answers["ext"] = Outcome(State.FAILED, "gh extension install exited 1")
    _declare_extensions(tmp_path, ["gh"], ["github/gh-stack"])

    # act
    rc = hosttools.install()

    # assert
    assert rc == 1
    out = capsys.readouterr()
    assert "gh extension github/gh-stack: install failed: gh extension install exited 1" in out.out + out.err


@pytest.mark.parametrize("state, rc_expected", [(State.SKIPPED, 0), (State.FAILED, 1), (State.NO_ROUTE, 1)])
def test_extensions_are_skipped_and_said_so_when_the_gate_left_no_gh(extensions, tmp_path, capsys, state,
                                                                      rc_expected):
    # arrange
    _, answers, asked = extensions
    answers["gh"] = Outcome(state, "why")
    _declare_extensions(tmp_path, ["gh"], ["github/gh-stack"])

    # act
    rc = hosttools.install()

    # assert: the gate's own outcome decides the rc, and the skip is a line, not a silence
    assert rc == rc_expected
    assert asked == []
    out = capsys.readouterr()
    assert f"gh extensions skipped: the gh gate left no gh that runs here ({state.value})" in out.out + out.err


def test_extensions_are_skipped_when_an_installed_gh_does_not_run_here(extensions, tmp_path, monkeypatch,
                                                                       capsys):
    # arrange: winget's INSTALLED "open a new shell" - gh is there, but not for this process
    _, answers, asked = extensions
    answers["gh"] = Outcome(State.INSTALLED, "open a new shell so PATH picks gh up")
    monkeypatch.setattr(hostinstall, "runs", lambda tool, env=None: False)
    _declare_extensions(tmp_path, ["gh"], ["github/gh-stack"])

    # act
    rc = hosttools.install()

    # assert
    assert rc == 0 and asked == []
    out = capsys.readouterr()
    assert "gh extensions skipped" in out.out + out.err


def test_no_gh_section_says_nothing_about_extensions(extensions, tmp_path, capsys):
    # arrange
    order, _, _ = extensions
    _declare(tmp_path, "gh")

    # act
    rc = hosttools.install()

    # assert
    assert rc == 0
    assert "gh extensions" not in order
    out = capsys.readouterr()
    assert "extension" not in out.out + out.err


def test_a_gh_section_without_the_gh_toolchain_is_reported_and_the_other_gates_still_run(extensions, tmp_path,
                                                                                         capsys):
    # arrange
    order, _, asked = extensions
    _declare_extensions(tmp_path, ["brew"], ["github/gh-stack"])

    # act
    rc = hosttools.install()

    # assert
    assert rc == 1
    assert order == ["brew", "oras"] and asked == []
    out = capsys.readouterr()
    assert "but 'gh' is not in 'toolchains:'" in out.out + out.err
