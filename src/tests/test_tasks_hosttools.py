"""Unit tests for simplon.tasks.hosttools - `support install`, the command that provisions the host
tooling the kernel itself cannot work without. Nothing here installs anything: every gate is
monkeypatched, so the suite proves what the command DECIDES and reports. AAA throughout.
"""
import pytest

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
    assert eff is not None and "gh" in eff.requires
