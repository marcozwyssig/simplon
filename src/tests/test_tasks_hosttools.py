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
    # a SKIPPED gate's own reason is the extensions' reason too (si#710): it says where to go instead
    why = "why" if state is State.SKIPPED else f"the gh gate left no gh that runs here ({state.value})"
    assert f"gh extensions skipped: {why}; not installed: github/gh-stack" in out.out + out.err


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


def test_a_gh_that_gives_no_answer_fails_the_extensions_rather_than_skipping_them(extensions, tmp_path,
                                                                                 monkeypatch, capsys):
    # arrange (si#740): the gate found gh PRESENT, then its second `gh --version` gave no answer. That is
    # "could not ask", not "no gh here": the extensions are not installed, and the command must say so red.
    _, answers, asked = extensions
    answers["gh"] = Outcome(State.PRESENT)

    def silent(tool, env=None):
        raise hostinstall.NoAnswer("`gh --version` gave no answer within 30 s and was stopped")
    monkeypatch.setattr(hostinstall, "runs", silent)
    _declare_extensions(tmp_path, ["gh"], ["github/gh-stack"])

    # act
    rc = hosttools.install()

    # assert
    assert rc == 1 and asked == []
    out = capsys.readouterr()
    assert "gave no answer within 30 s" in out.out + out.err
    assert "not installed: github/gh-stack" in out.out + out.err


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


def test_a_gh_that_is_not_logged_in_skips_the_extensions_without_failing_the_command(gates, tmp_path,
                                                                                      monkeypatch, capsys):
    # arrange: the real ensure_extensions, over a gh whose list answers rc 4 (measured: no token)
    monkeypatch.setattr(hostinstall, "runs", lambda tool, env=None: True)
    monkeypatch.setattr(gh, "run", lambda argv, timeout=None, **kw: Result(4, "", "gh auth login\n"))
    _declare_extensions(tmp_path, ["gh"], ["github/gh-stack@v0.3.0"])

    # act
    rc = hosttools.install()

    # assert
    assert rc == 0
    out = capsys.readouterr()
    assert "gh extension github/gh-stack@v0.3.0 skipped:" in out.out + out.err
    assert "gh auth login" in out.out + out.err


from simplon.kernel.run import Result  # noqa: E402


# --- si#710: the container route provisions nothing ------------------------------------------------------


def test_on_the_container_route_every_host_gate_is_skipped_and_says_so(monkeypatch, tmp_path, capsys):
    """firn measured it on 0.44.0: inside the kernel container gh.ensure() answered PRESENT (the image
    carries gh), and with GH_TOKEN exported every declared extension went `installed` - into the
    throwaway container, never onto the host. The REAL gates run here, over a gh that runs and answers
    every call; only `DELIVERY_ROUTE=inside`, which the launcher sets on its way into the container, says
    which route this is."""
    # arrange
    calls = []
    monkeypatch.setenv("DELIVERY_ROUTE", "inside")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GH_TOKEN", "a token")
    monkeypatch.setattr(oras, "ensure_oras", lambda: None)
    monkeypatch.setattr(hostinstall, "runs", lambda tool, env=None: True)
    monkeypatch.setattr(gh, "run", lambda argv, **kw: calls.append(argv) or Result(0, "", ""))
    monkeypatch.setattr(hostinstall, "act", lambda argv, **kw: calls.append(argv) or "")
    monkeypatch.setattr(claudeplugins, "run", lambda argv, **kw: calls.append(argv) or Result(0, "", ""))
    monkeypatch.setattr(claudeplugins.shutil, "which", lambda name, path=None: f"/usr/bin/{name}")
    _declare_extensions(tmp_path, ["brew", "gh", "claude"], ["github/gh-stack@v0.3.0"])

    # act
    rc = hosttools.install()

    # assert: nothing ran, every gate said why and where to go instead, and the skip is not a failure
    out = capsys.readouterr()
    said = out.out + out.err
    assert rc == 0, said
    assert calls == [], f"the container route ran {calls}"
    route = "the container route installs nothing on the host; run support install on the venv route"
    for gate in ("brew skipped: ", "gh skipped: ", "gh extensions skipped: ", "Claude Code plugins"):
        assert gate in said, said
    assert said.count(route) == 4, said


def test_on_the_venv_route_the_gates_run_as_before(gates, tmp_path, monkeypatch):
    # arrange: the route the launcher takes on a host with a python3
    monkeypatch.setenv("DELIVERY_ROUTE", "venv")
    seen = []
    monkeypatch.setattr(gh, "ensure", lambda **kw: seen.append(kw) or Outcome(State.PRESENT))
    _declare(tmp_path, "gh")

    # act
    rc = hosttools.install()

    # assert
    assert rc == 0
    assert seen == [{"container": False}]


# --- si#900: the firn editor gates --------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from simplon.adapters import firnrelease  # noqa: E402
from simplon.tasks import firneditor  # noqa: E402

FIRN_TAG = "v0.19.0"


def _declare_firn(tmp_path, toolchains=("firn",), image=f"ghcr.io/marcozwyssig/firn:{FIRN_TAG}"):
    manifest = {"product": "sample", "toolchains": list(toolchains),
                "ci": {"build": {"commands": {"model": {"task": "build:model", "with": {"image": image}}}}}}
    (tmp_path / "sample.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


@pytest.fixture
def firn(gates, monkeypatch, tmp_path):
    """The three firn gates replaced by recorders; the release read counted. A developer's machine: no CI,
    the venv route, the runtime file under tmp_path."""
    for variable in ("CI", "GITHUB_ACTIONS", "DELIVERY_ROUTE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    order, answers = gates
    reads = []
    monkeypatch.setattr(firnrelease, "read",
                        lambda tag: reads.append(tag) or firnrelease.Release(tag, {}))

    def extension(tag, release_of, scratch):
        order.append("firn extension")
        assert Path(scratch).is_dir()
        try:
            release_of()
        except firnrelease.ReleaseUnreadable as e:  # as the real gate does
            return Outcome(State.FAILED, str(e))
        return answers.get("firn extension", Outcome(State.PRESENT))

    def runtime(choice, tag, release_of, root, *, image):
        order.append("firn runtime")
        assert image == f"ghcr.io/marcozwyssig/firn:{FIRN_TAG}", image
        release_of()
        outcome = answers.get("firn runtime", Outcome(State.PRESENT))
        return outcome, (None if outcome.state is State.FAILED else root / "build/tools/bin/firn-docker")

    def workspace(root, product, binary, data, *, docker):
        order.append("firn workspace")
        assert docker is (choice_runtime(binary) == "docker")
        return answers.get("firn workspace", Outcome(State.PRESENT))

    monkeypatch.setattr(firneditor, "extension_gate", extension)
    monkeypatch.setattr(firneditor, "runtime_gate", runtime)
    monkeypatch.setattr(firneditor, "workspace_gate", workspace)
    return order, answers, reads


FIRN_GATES = ["firn extension", "firn runtime", "firn workspace"]


def choice_runtime(binary):
    """The runtime the fake runtime gate's target stands for."""
    return "docker" if Path(binary).name == "firn-docker" else "local"


def test_firn_not_declared_says_nothing_and_reads_nothing(firn, tmp_path, capsys):
    # arrange: a firn image in the commands, but no `firn` toolchain
    order, _, reads = firn
    _declare_firn(tmp_path, toolchains=())

    # act
    rc = hosttools.install()

    # assert
    said = capsys.readouterr()
    assert rc == 0
    assert not set(FIRN_GATES) & set(order)
    assert reads == []
    assert "firn" not in said.out + said.err
    assert not firneditor.runtime_file().exists()


def test_a_runtime_flag_with_firn_not_declared_is_one_line_saying_it_was_ignored(firn, tmp_path, capsys):
    # arrange
    order, _, reads = firn
    _declare_firn(tmp_path, toolchains=())

    # act
    rc = hosttools.install(firn_runtime="docker")

    # assert: said once, and nothing stored or read
    out = "".join(capsys.readouterr())
    assert rc == 0, out
    assert out.count("--firn-runtime docker ignored: `firn` is not in toolchains:") == 1, out
    assert not set(FIRN_GATES) & set(order) and reads == []
    assert not firneditor.runtime_file().exists()


def test_container_route_skips_all_three_firn_gates_without_reading(firn, tmp_path, monkeypatch, capsys):
    # arrange: and a manifest whose pin is broken, to show it is not even read
    order, _, reads = firn
    monkeypatch.setenv("DELIVERY_ROUTE", "inside")
    _declare_firn(tmp_path, image="ghcr.io/marcozwyssig/firn")

    # act
    rc = hosttools.install()

    # assert
    said = capsys.readouterr()
    out = said.out + said.err
    assert rc == 0, out
    assert not set(FIRN_GATES) & set(order)
    assert reads == []
    for gate in FIRN_GATES:
        assert f"{gate} skipped: {hostinstall.CONTAINER_ROUTE_SKIP}" in out, out


def test_ci_skips_all_three_firn_gates(firn, tmp_path, monkeypatch, capsys):
    # arrange
    order, _, reads = firn
    monkeypatch.setenv("CI", "true")
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="docker")

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 0, out
    assert not set(FIRN_GATES) & set(order)
    assert reads == []
    assert not firneditor.runtime_file().exists()
    for gate in FIRN_GATES:
        assert f"{gate} skipped: CI=true: editor tools are for a machine somebody develops on" in out, out
    assert out.count("--firn-runtime docker ignored: the firn editor gates are skipped (CI=true") == 1, out


def test_a_runtime_flag_on_the_container_route_is_said_to_be_ignored(firn, tmp_path, monkeypatch, capsys):
    # arrange
    order, _, reads = firn
    monkeypatch.setenv("DELIVERY_ROUTE", "inside")
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="local")

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 0, out
    assert out.count(f"--firn-runtime local ignored: the firn editor gates are skipped "
                     f"({hostinstall.CONTAINER_ROUTE_SKIP})") == 1, out
    assert not set(FIRN_GATES) & set(order) and reads == []
    assert not firneditor.runtime_file().exists()


def test_a_vsix_scratch_directory_that_cannot_be_made_fails_the_extension_and_the_others_still_run(
        firn, tmp_path, monkeypatch, capsys):
    # arrange
    order, _, _ = firn

    def refuse(*args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(firneditor.tempfile, "TemporaryDirectory", refuse)
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="docker")

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 1, out
    assert order[-2:] == ["firn runtime", "firn workspace"]
    assert "firn extension: install failed: could not make a scratch directory for the .vsix" in out, out
    assert "No space left on device" in out, out


def test_a_failing_firn_gate_fails_install_but_every_gate_runs(firn, tmp_path, capsys):
    # arrange
    order, answers, reads = firn
    answers["firn extension"] = Outcome(State.FAILED, "`code` is not on PATH")
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="docker")

    # assert: in order, after the existing gates, and the release read once for all of them
    out = "".join(capsys.readouterr())
    assert rc == 1
    assert order[-3:] == FIRN_GATES
    assert reads == [FIRN_TAG]
    assert "firn extension: install failed: `code` is not on PATH" in out, out


def test_the_run_names_runtime_and_source(firn, tmp_path, capsys):
    # arrange
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="docker")

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 0, out
    assert "firn runtime: docker (flag)" in out, out


def test_a_failed_runtime_gate_leaves_the_workspace_unwritten_and_says_why(firn, tmp_path, capsys):
    # arrange
    order, answers, _ = firn
    answers["firn runtime"] = Outcome(State.FAILED, "the docker daemon does not answer")
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="docker")

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 1
    assert order[-2:] == ["firn extension", "firn runtime"]
    assert "firn workspace: not written" in out and "runtime gate" in out, out


def test_a_runtime_that_cannot_be_chosen_fails_the_runtime_and_still_runs_the_extension(firn, tmp_path, capsys):
    # arrange
    order, _, _ = firn
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="podman")

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 1
    assert order[-1] == "firn extension"
    assert "firn runtime: could not be chosen: unknown firn runtime 'podman'" in out, out
    assert "firn runtime: install failed" not in out, out
    assert "firn workspace: not written" in out, out


def test_an_unreadable_release_with_no_flag_fails_the_runtime_never_docker(firn, tmp_path, monkeypatch, capsys):
    # arrange: no flag, nothing stored, and the release cannot be read
    order, _, _ = firn
    calls = []

    def unreadable(tag):
        calls.append(tag)
        raise firnrelease.ReleaseUnreadable(f"could not read firn's release {tag}")
    monkeypatch.setattr(firnrelease, "read", unreadable)
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install()

    # assert: the failed read is not repeated within the run
    out = "".join(capsys.readouterr())
    assert rc == 1
    assert "firn runtime: could not be chosen: could not read firn's release v0.19.0" in out, out
    assert "firn runtime: docker" not in out
    assert calls == [FIRN_TAG]


def test_a_broken_pin_is_one_failed_line_naming_the_gates_not_run(firn, tmp_path, capsys):
    # arrange
    order, _, reads = firn
    _declare_firn(tmp_path, image="ghcr.io/marcozwyssig/firn")

    # act
    rc = hosttools.install()

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 1
    assert not set(FIRN_GATES) & set(order)
    assert reads == []
    assert "which has no tag" in out and "not run: firn extension, firn runtime, firn workspace" in out, out


def test_a_failed_workspace_gate_fails_install(firn, tmp_path, capsys):
    # arrange
    order, answers, _ = firn
    answers["firn workspace"] = Outcome(State.FAILED, "written but not git-ignored")
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="docker")

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 1
    assert order[-3:] == FIRN_GATES
    assert "firn workspace: install failed: written but not git-ignored" in out, out


def test_a_workspace_gate_that_refuses_is_reported_failed(firn, tmp_path, monkeypatch, capsys):
    # arrange: `projects` refuses a folder firn-workspace.toml lists and the disk does not have
    order, _, _ = firn

    def refuse(root, product, binary, data, *, docker):
        order.append("firn workspace")
        raise ValueError("project folder src/gone (from firn-workspace.toml) does not exist")
    monkeypatch.setattr(firneditor, "workspace_gate", refuse)
    _declare_firn(tmp_path)

    # act
    rc = hosttools.install(firn_runtime="docker")

    # assert
    out = "".join(capsys.readouterr())
    assert rc == 1
    assert "firn workspace: install failed: project folder src/gone" in out, out
