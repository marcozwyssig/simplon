"""si#525: the plugin step's five outcomes, against a real `claude` executable on a PATH this test owns.

OFF, SKIPPED, NOTHING_MISSING, INSTALLED and FAILED are kept apart because each is a different thing for the
person reading the line - "this product does not use Claude", "this machine cannot", "ready", "restart
Claude Code" and "broken" - and the recurring defect is any two of them reading alike. The fake answers the
two `--json` queries from files and records every argv, so what is asserted is what a child process was
asked to do.
"""
from __future__ import annotations

import json
import stat
import sys
import time
import types
from pathlib import Path

import pytest

from simplon.tasks import claudeplugins, hosttools

_FAKE = '''#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(os.path.join(here, "argv.log"), "a") as log:
    log.write(" ".join(args) + "\\n")
state = os.path.join(here, "installed.json")
installed = json.load(open(state)) if os.path.exists(state) else []
if args[:2] == ["plugin", "list"]:
    if os.environ.get("FAKE_HANG"):
        time.sleep(30)
    print(json.dumps([{{"id": i, "scope": "user"}} for i in installed]))
elif args[:3] == ["plugin", "marketplace", "list"]:
    # The shape the real CLI answers in (measured 2026-11-06, claude 2.1.318): `ref` only when pinned.
    markets = os.environ.get("FAKE_MARKETS")
    print(markets or json.dumps([
        {{"name": "claude-plugins-official", "source": "github", "repo": "anthropics/claude-plugins-official"}},
        {{"name": "alexgreensh-token-optimizer", "source": "github", "repo": "alexgreensh/token-optimizer"}}]))
elif args[:2] == ["plugin", "install"]:
    if args[2] == os.environ.get("FAKE_FAIL"):
        sys.exit(1)
    installed.append(args[2])
    json.dump(installed, open(state, "w"))
'''


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A PATH holding a fake `claude` and the executables the default plugins run (`gh`, `node`), and a
    product context whose manifest data the test sets. A test about a missing one removes it (si#582)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(_FAKE.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    for name in ("gh", "node"):
        (bin_dir / name).write_text("#!/bin/sh\n")
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    for variable in ("CI", "GITHUB_ACTIONS", "FAKE_FAIL", "FAKE_HANG", "FAKE_MARKETS"):
        monkeypatch.delenv(variable, raising=False)
    box = types.SimpleNamespace(data={"toolchains": ["claude"]}, bin=bin_dir)
    ctx = types.SimpleNamespace(manifest_data=lambda: box.data, manifest_path=tmp_path / "demo.yaml")
    monkeypatch.setattr(claudeplugins.context, "current", lambda: ctx)
    box.argv = lambda: (bin_dir / "argv.log").read_text().splitlines() if (bin_dir / "argv.log").exists() else []
    box.install_all = lambda ids: (bin_dir / "installed.json").write_text(json.dumps(list(ids)))
    box.env = lambda **more: {"PATH": str(bin_dir), **more}
    return box


def _lines(monkeypatch):
    lines: list[tuple[str, str]] = []
    for level in ("info", "ok", "warn"):
        monkeypatch.setattr(claudeplugins.log, level, lambda msg, _l=level: lines.append((_l, msg)))
    return lines


def test_off_without_claude_toolchain(machine):
    # arrange
    machine.data = {"toolchains": ["python"]}

    # act
    outcome = claudeplugins.step(env=machine.env())

    # assert: OFF asks nothing of the machine at all
    assert outcome.state is claudeplugins.State.OFF
    assert machine.argv() == []


def test_skipped_without_claude_on_path(machine, tmp_path):
    # act
    outcome = claudeplugins.step(env={"PATH": str(tmp_path / "empty")})

    # assert
    assert outcome.state is claudeplugins.State.SKIPPED
    assert outcome.detail == "no `claude` on PATH"


@pytest.mark.parametrize("variable", ["CI", "GITHUB_ACTIONS"])
def test_skipped_in_ci(machine, variable):
    # act
    outcome = claudeplugins.step(env=machine.env(**{variable: "true"}))

    # assert
    assert outcome.state is claudeplugins.State.SKIPPED
    assert variable in outcome.detail
    assert machine.argv() == []


def test_skipped_on_the_container_route(machine):
    # act
    outcome = claudeplugins.step(env=machine.env(), container=True)

    # assert
    assert outcome.state is claudeplugins.State.SKIPPED
    assert outcome.detail == "the container route: `claude` runs on the host"


def test_nothing_missing(machine):
    # arrange
    machine.install_all(claudeplugins.BASE_PLUGINS)

    # act
    outcome = claudeplugins.step(env=machine.env())

    # assert
    assert outcome.state is claudeplugins.State.NOTHING_MISSING
    assert not any(line.startswith("plugin install") for line in machine.argv())


def test_installed_counts_and_says_restart(machine, monkeypatch):
    # arrange: all but two
    machine.install_all(claudeplugins.BASE_PLUGINS[:-2])
    lines = _lines(monkeypatch)

    # act
    outcome = claudeplugins.step(env=machine.env())
    claudeplugins.report(outcome)

    # assert
    assert outcome.state is claudeplugins.State.INSTALLED
    assert outcome.count == 2
    assert any("restart Claude Code" in msg for _, msg in lines)


def test_failed_names_the_plugin(machine, monkeypatch):
    # arrange
    machine.install_all(claudeplugins.BASE_PLUGINS[:-1])
    monkeypatch.setenv("FAKE_FAIL", claudeplugins.BASE_PLUGINS[-1])

    # act
    outcome = claudeplugins.step(env=machine.env())

    # assert
    assert outcome.state is claudeplugins.State.FAILED
    assert claudeplugins.BASE_PLUGINS[-1] in outcome.detail


def test_hung_claude_is_failed_not_hung(machine, monkeypatch):
    # arrange: Review Focus 5 - a launcher must never wait on a hung CLI
    monkeypatch.setenv("FAKE_HANG", "1")

    # act
    started = time.monotonic()
    outcome = claudeplugins.step(env=machine.env(), timeout_s=1)

    # assert
    assert outcome.state is claudeplugins.State.FAILED
    assert time.monotonic() - started < 5
    assert "did not answer within 1s" in outcome.detail


def test_dry_run_shows_origin(machine, monkeypatch):
    # arrange
    machine.data = {"toolchains": ["claude", "python"],
                    "claude": {"marketplaces": {"acme": {"source": "github", "repo": "acme/p"}},
                               "plugins": ["x@acme"]}}
    lines = _lines(monkeypatch)

    # act
    claudeplugins.install(dry_run=True)

    # assert: the person running it can see what the product added and what simplon brings
    shown = " ".join(msg for _, msg in lines)
    assert "(default)" in shown and "(toolchain python)" in shown and "(product)" in shown
    assert not any(line.startswith("plugin install") for line in machine.argv())


def test_support_install_says_nothing_for_claude_when_off(machine, monkeypatch):
    # arrange
    machine.data = {}
    monkeypatch.setattr(hosttools.oras, "ensure_oras", lambda: None)
    lines = _lines(monkeypatch)

    # act
    rc = hosttools.install()

    # assert
    assert rc == 0
    assert not any("claude" in msg.lower() for _, msg in lines)


def test_support_install_fails_on_failed_and_still_runs_every_gate(machine, monkeypatch):
    # arrange
    monkeypatch.setenv("FAKE_FAIL", claudeplugins.BASE_PLUGINS[0])
    seen: list[str] = []
    monkeypatch.setattr(hosttools.oras, "ensure_oras", lambda: seen.append("oras"))

    # act
    rc = hosttools.install()

    # assert
    assert rc == 1
    assert seen == ["oras"]


# --- final review (si#525) ----------------------------------------------------------------------------

def test_a_hung_plugin_install_is_failed_not_hung(machine, monkeypatch):
    # arrange: the launcher runs this step before every command after a refresh, `--help` included
    machine.install_all(claudeplugins.BASE_PLUGINS[:-1])
    fake = machine.bin / "claude"
    fake.write_text(fake.read_text().replace('elif args[:2] == ["plugin", "install"]:',
                                             'elif args[:2] == ["plugin", "install"]:\n    time.sleep(30)'))

    # act
    started = time.monotonic()
    outcome = claudeplugins.step(env=machine.env(), timeout_s=1)

    # assert
    assert outcome.state is claudeplugins.State.FAILED
    assert time.monotonic() - started < 5
    assert "did not finish within 1s" in outcome.detail


def test_a_claude_section_without_the_claude_toolchain_is_a_diagnosis_not_off():
    # arrange: every product with a `claude:` section before si#525 is in this state after the bump
    data = {"toolchains": ["python"], "claude": {"plugins": ["superpowers@claude-plugins-official"]}}

    # act / assert: additions nothing reads, reported as "off", would be the recurring defect
    with pytest.raises(ValueError, match="'claude:' section, but 'claude' is not in 'toolchains:'"):
        claudeplugins.effective(data)


def test_a_marketplace_registered_unpinned_is_failed_when_the_manifest_pins_it(machine, monkeypatch):
    # arrange: si#581 - the machine registered token-optimizer before the product pinned it. Matching by
    # name alone read that as "nothing missing" and the pin was never applied.
    machine.data = {"toolchains": ["claude"], "claude": {"marketplaces": {
        "alexgreensh-token-optimizer": {"source": "github", "repo": "alexgreensh/token-optimizer",
                                        "ref": "v5.13.17"}}}}
    machine.install_all(claudeplugins.BASE_PLUGINS[:-1])
    _lines(monkeypatch)

    # act
    outcome = claudeplugins.step(env=machine.env())

    # assert: FAILED, naming both sources and the way out; nothing re-added, its plugin not installed
    assert outcome.state is claudeplugins.State.FAILED
    assert "alexgreensh/token-optimizer" in outcome.detail and "#v5.13.17" in outcome.detail
    assert "claude plugin marketplace remove alexgreensh-token-optimizer" in outcome.detail
    assert not [a for a in machine.argv() if a.startswith(("plugin marketplace add", "plugin install"))]


def test_a_marketplace_registered_at_the_pinned_ref_is_nothing_missing(machine, monkeypatch):
    # arrange: the same pin, registered as pinned - the CLI lists the ref
    machine.data = {"toolchains": ["claude"], "claude": {"marketplaces": {
        "alexgreensh-token-optimizer": {"source": "github", "repo": "alexgreensh/token-optimizer",
                                        "ref": "v5.13.17"}}}}
    monkeypatch.setenv("FAKE_MARKETS", json.dumps([
        {"name": "claude-plugins-official", "source": "github", "repo": "anthropics/claude-plugins-official"},
        {"name": "alexgreensh-token-optimizer", "source": "github", "repo": "alexgreensh/token-optimizer",
         "ref": "v5.13.17"}]))
    machine.install_all(claudeplugins.BASE_PLUGINS)
    _lines(monkeypatch)

    # act
    outcome = claudeplugins.step(env=machine.env())

    # assert
    assert outcome.state is claudeplugins.State.NOTHING_MISSING



def test_auto_install_false_does_not_stop_an_explicit_install(machine, monkeypatch):
    # arrange: si#583 turns off the LAUNCHER's automatic step only; `support install` still installs
    machine.data = {"toolchains": ["claude"], "claude": {"auto_install": False}}
    _lines(monkeypatch)

    # act
    outcome = claudeplugins.step(env=machine.env())

    # assert
    assert outcome.state is claudeplugins.State.INSTALLED
    assert outcome.count == len(claudeplugins.BASE_PLUGINS)


# --- si#592: the dry run's verdict matches its rc, and a marketplace shows its source --------------------

_PINNED = {"toolchains": ["claude"], "claude": {"marketplaces": {
    "alexgreensh-token-optimizer": {"source": "github", "repo": "alexgreensh/token-optimizer",
                                    "ref": "v5.13.17"}}}}


def test_a_red_dry_run_does_not_end_on_an_ok_line(machine, monkeypatch):
    # arrange: the home registered the marketplace unpinned, the manifest pins it (firn, 0.40.0)
    machine.data = _PINNED
    machine.install_all(claudeplugins.BASE_PLUGINS)
    lines = _lines(monkeypatch)

    # act
    rc = claudeplugins.install(dry_run=True)

    # assert
    assert rc == 1
    assert lines[-1][0] == "warn"
    assert not any(level == "ok" for level, _ in lines)


def test_a_green_dry_run_still_ends_on_an_ok_line(machine, monkeypatch):
    # arrange: every executable the default plugins run is on this PATH too
    machine.install_all(claudeplugins.BASE_PLUGINS)
    for name in ("node", "gh"):
        (machine.bin / name).write_text("#!/bin/sh\n")
        (machine.bin / name).chmod(0o755)
    lines = _lines(monkeypatch)

    # act
    rc = claudeplugins.install(dry_run=True)

    # assert
    assert rc == 0
    assert lines[-1][0] == "ok"


def test_the_dry_run_names_a_replaced_marketplace_and_its_ref(machine, monkeypatch):
    # arrange: an empty home, so the pinned marketplace would be registered
    machine.data = _PINNED
    monkeypatch.setenv("FAKE_MARKETS", "[]")
    lines = _lines(monkeypatch)

    # act
    claudeplugins.install(dry_run=True)

    # assert
    shown = [msg for _, msg in lines]
    assert ("marketplace alexgreensh-token-optimizer (alexgreensh/token-optimizer#v5.13.17, "
            "product, replaces the default)") in shown
    assert "marketplace claude-plugins-official (anthropics/claude-plugins-official, default)" in shown
    assert ("would register marketplace alexgreensh-token-optimizer "
            "(alexgreensh/token-optimizer#v5.13.17)") in shown


def test_registering_a_pinned_marketplace_prints_its_ref(machine, monkeypatch):
    # arrange
    machine.data = _PINNED
    monkeypatch.setenv("FAKE_MARKETS", "[]")
    lines = _lines(monkeypatch)

    # act
    claudeplugins.step(env=machine.env())

    # assert
    assert ("registering marketplace alexgreensh-token-optimizer (alexgreensh/token-optimizer#v5.13.17)"
            in [msg for _, msg in lines])


# --- si#596: a mismatched marketplace's plugins are skipped, and both runs say why ------------------------

_OPTIMIZER = "token-optimizer@alexgreensh-token-optimizer"


def test_the_dry_run_skips_the_plugins_of_a_mismatched_marketplace(machine, monkeypatch):
    # arrange: nothing installed, the marketplace registered unpinned, the manifest pins it
    machine.data = _PINNED
    lines = _lines(monkeypatch)

    # act
    claudeplugins.install(dry_run=True)

    # assert: the preview agrees with what step() does
    shown = [msg for _, msg in lines]
    assert f"would install {_OPTIMIZER}" not in shown
    assert (f"would skip {_OPTIMIZER}: its marketplace alexgreensh-token-optimizer is registered from "
            f"another source") in shown
    assert any(m.startswith(f"would install {p}") for m in shown for p in claudeplugins.BASE_PLUGINS
               if p != _OPTIMIZER)


def test_the_run_names_a_mismatch_as_the_reason_it_skips_a_plugin(machine, monkeypatch):
    # arrange
    machine.data = _PINNED
    _lines(monkeypatch)

    # act
    outcome = claudeplugins.step(env=machine.env())

    # assert
    assert (f"{_OPTIMIZER} skipped: its marketplace alexgreensh-token-optimizer is registered from another "
            f"source") in outcome.detail
    assert "could not be registered" not in outcome.detail


# --- si#582: a default or toolchain plugin whose executable is missing is skipped, and says so ----------

_GITHUB = "github@claude-plugins-official"
_SKIP_GITHUB = f"skipped {_GITHUB}: `gh` is not on PATH"
_SKIP_OPTIMIZER = f"skipped {_OPTIMIZER}: `node` is not on PATH"


def _without(machine, *names):
    for name in names:
        (machine.bin / name).unlink()


def test_firn_without_gh_and_node_installs_the_rest_and_names_both_skips(machine, monkeypatch):
    # arrange: firn's host, measured in si#582 - `toolchains: [claude]`, docker and python3, no gh, no node
    _without(machine, "gh", "node")
    lines = _lines(monkeypatch)

    # act
    outcome = claudeplugins.step(env=machine.env())
    claudeplugins.report(outcome)

    # assert: the rest is installed, the two are not, and the run says which and why
    installs = [a for a in machine.argv() if a.startswith("plugin install")]
    assert not any(_GITHUB in a or _OPTIMIZER in a for a in installs)
    assert outcome.state is claudeplugins.State.INSTALLED
    assert outcome.count == len(claudeplugins.BASE_PLUGINS) - 2
    assert claudeplugins._rc(outcome) == 0
    shown = [msg for _, msg in lines]
    assert _SKIP_GITHUB in shown and _SKIP_OPTIMIZER in shown


def test_support_install_is_green_on_firns_host(machine, monkeypatch):
    # arrange
    _without(machine, "gh", "node")
    monkeypatch.setattr(hosttools.oras, "ensure_oras", lambda: None)
    _lines(monkeypatch)

    # act / assert
    assert hosttools.install() == 0


def test_an_executable_the_product_requires_is_still_red(machine, monkeypatch):
    # arrange: the product SAID it needs node (`claude.requires:`), so its absence is a refusal
    machine.data = {"toolchains": ["claude"], "claude": {"requires": ["node"]}}
    _without(machine, "node")
    lines = _lines(monkeypatch)

    # act
    rc = claudeplugins.install()

    # assert
    assert rc == 1
    assert any(level == "warn" and "`node` is not on PATH" in msg and "claude.requires" in msg
               for level, msg in lines)


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_product_requirement_is_red_in_both_runs_even_when_its_plugin_is_skipped(
        machine, monkeypatch, dry_run):
    machine.data = {"toolchains": ["claude"], "claude": {"requires": ["node"]}}
    _without(machine, "node")
    _lines(monkeypatch)

    assert claudeplugins.install(dry_run=dry_run) == 1


def test_the_dry_run_skips_what_the_run_skips_for_the_same_reason(machine, monkeypatch):
    # arrange: a python product on a host with no pyright and no gh
    machine.data = {"toolchains": ["claude", "python"]}
    _without(machine, "gh")
    lines = _lines(monkeypatch)

    # act
    rc_dry = claudeplugins.install(dry_run=True)
    preview = [msg for _, msg in lines]
    lines.clear()
    rc_run = claudeplugins.install()
    run = [msg for _, msg in lines]

    # assert: same plugins, same reasons, "would skip" in the preview; both green
    pyright = "pyright-lsp@claude-plugins-official"
    assert f"would skip {pyright}: `pyright-langserver` is not on PATH" in preview
    assert f"would skip {_GITHUB}: `gh` is not on PATH" in preview
    assert f"skipped {pyright}: `pyright-langserver` is not on PATH" in run
    assert _SKIP_GITHUB in run
    assert f"would install {pyright}" not in preview and f"would install {_GITHUB}" not in preview
    skipped_dry = sorted(m.removeprefix("would skip ").split(":")[0] for m in preview
                         if m.startswith("would skip "))
    skipped_run = sorted(m.removeprefix("skipped ").split(":")[0] for m in run if m.startswith("skipped "))
    assert skipped_dry == skipped_run == sorted([pyright, _GITHUB])
    assert rc_dry == rc_run == 0


def test_only_skipped_plugins_left_is_green_and_never_silent_and_not_nothing_to_do(machine, monkeypatch):
    # arrange: everything this machine can run is installed; gh is missing, github is not installed
    _without(machine, "gh")
    machine.install_all(p for p in claudeplugins.BASE_PLUGINS if p != _GITHUB)
    lines = _lines(monkeypatch)

    for _ in range(2):      # the skip is said on EVERY run, not once
        lines.clear()

        # act
        rc = claudeplugins.install()

        # assert: green, the skip named, and the last line is not the plain "nothing to do"
        assert rc == 0
        shown = [msg for _, msg in lines]
        assert _SKIP_GITHUB in shown
        assert "nothing to do" not in lines[-1][1]
        assert "1 cannot run here" in lines[-1][1]
    assert not any(a.startswith("plugin install") for a in machine.argv())


def test_an_installed_plugin_whose_executable_is_missing_is_left_and_warned(machine, monkeypatch):
    # arrange: github was installed while gh was there; gh has gone since
    _without(machine, "gh")
    machine.install_all(claudeplugins.BASE_PLUGINS)
    lines = _lines(monkeypatch)

    # act
    rc = claudeplugins.install()

    # assert: not uninstalled, not reinstalled, not "already installed", and said
    assert rc == 0
    assert not any(a.startswith(("plugin install", "plugin uninstall")) for a in machine.argv())
    shown = [msg for _, msg in lines]
    assert f"{_GITHUB} already installed" not in shown
    assert any(level == "warn" and msg.startswith(f"{_GITHUB} is installed") and "`gh` is not on PATH" in msg
               for level, msg in lines)


def test_a_skipped_plugins_marketplace_is_not_registered(machine, monkeypatch):
    # arrange: an empty home and no node - token-optimizer's marketplace serves nothing that installs
    monkeypatch.setenv("FAKE_MARKETS", "[]")
    _without(machine, "node")
    _lines(monkeypatch)

    # act
    claudeplugins.step(env=machine.env())

    # assert
    assert not any("alexgreensh/token-optimizer" in a for a in machine.argv())
