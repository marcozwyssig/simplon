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
    print(json.dumps([{{"name": "claude-plugins-official"}}, {{"name": "alexgreensh-token-optimizer"}}]))
elif args[:2] == ["plugin", "install"]:
    if args[2] == os.environ.get("FAKE_FAIL"):
        sys.exit(1)
    installed.append(args[2])
    json.dump(installed, open(state, "w"))
'''


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A PATH holding only a fake `claude`, and a product context whose manifest data the test sets."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(_FAKE.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir))
    for variable in ("CI", "GITHUB_ACTIONS", "FAKE_FAIL", "FAKE_HANG"):
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
