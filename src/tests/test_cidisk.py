"""si#327: the docker-disk hygiene of a CI host, configured deliberately and as root.

WHY A COMMAND AND NOT A RUNBOOK PARAGRAPH, which is `ciprivileges`' argument at a second place. The
measured cause of this repository's dead CI was 64 GB in /var/lib/docker on a container with a ZFS
refquota, answering `Disk quota exceeded`. The cure is four settings and a timer, and it has to be applied
to EVERY runner - eight of them in this account, across three repositories. Eight hand-edits of a JSON
file is how one host ends up with `log-opts` and no `builder.gc`, and nothing says which.

WHY IT MERGES AND NEVER OVERWRITES. `/etc/docker/daemon.json` is where a host's `data-root`,
`registry-mirrors` and `insecure-registries` live. A command that wrote a fresh document with the four
settings it cares about would silently take a mirror away from a machine that needs one - and the symptom
would appear on the next build, nowhere near this command.

WHY A RESTART IS CONDITIONAL. `systemctl restart docker` kills every running container, which on a runner
means killing the job that is calling this. So the restart happens only when the file actually changed,
and a second run of an already-configured host must not touch the engine at all.

AAA; the name states the behaviour under test.
"""
import json

import pytest

from simplon.tasks import cidisk


class _Boom(Exception):
    pass


def _die(msg, *a, **k):
    raise _Boom(msg)


def _recorder(calls, rc=0):
    from simplon.run import Result as R
    return lambda argv, **kw: calls.append(list(argv)) or R(rc=rc, out="", err="")


@pytest.fixture
def host(monkeypatch, tmp_path):
    """A fake host: root, with /etc/docker and /etc/systemd/system redirected into tmp_path."""
    monkeypatch.setattr(cidisk.os, "getuid", lambda: 0)
    monkeypatch.setattr(cidisk.log, "die", _die)
    etc = tmp_path / "etc-docker"
    etc.mkdir()
    monkeypatch.setattr(cidisk, "DAEMON_JSON", etc / "daemon.json")
    units = tmp_path / "systemd"
    units.mkdir()
    monkeypatch.setattr(cidisk, "UNIT_DIR", units)
    return tmp_path


# --- the pure merge -------------------------------------------------------------------------------------


def test_merged_adds_the_four_settings_to_an_empty_document():
    # arrange / act
    out = cidisk.merged({})

    # assert: exactly what was asked for, and the numbers are the module's constants rather than repeats
    assert out["log-driver"] == cidisk.LOG_DRIVER
    assert out["log-opts"] == {"max-size": cidisk.LOG_MAX_SIZE, "max-file": cidisk.LOG_MAX_FILE}
    assert out["builder"]["gc"] == {"enabled": True, "defaultKeepStorage": cidisk.KEEP_STORAGE}


def test_merged_keeps_settings_this_command_knows_nothing_about():
    # arrange: the keys a real runner's daemon.json actually carries
    current = {"data-root": "/srv/docker", "registry-mirrors": ["https://mirror.example"],
               "insecure-registries": ["registry.lan:5000"]}

    # act
    out = cidisk.merged(current)

    # assert: nothing of the host's own was dropped - the whole reason this is a merge
    assert out["data-root"] == "/srv/docker"
    assert out["registry-mirrors"] == ["https://mirror.example"]
    assert out["insecure-registries"] == ["registry.lan:5000"]


def test_merged_keeps_a_foreign_builder_subkey_while_setting_gc():
    # arrange: `builder:` may already carry entitlements; only `gc` is ours
    current = {"builder": {"entitlements": {"security-insecure": True}}}

    # act
    out = cidisk.merged(current)

    # assert
    assert out["builder"]["entitlements"] == {"security-insecure": True}
    assert out["builder"]["gc"]["enabled"] is True


def test_merged_replaces_a_hand_edited_fragment_that_is_not_a_mapping():
    # arrange: a real daemon.json is hand-edited, and `log-opts` can be a string there. Merging into it
    # would raise - out of the one command whose promise is that it leaves what it cannot understand alone.
    current = {"log-opts": "max-size=10m", "builder": ["nonsense"]}

    # act
    out = cidisk.merged(current)

    # assert: the settings still land, and nothing raised
    assert out["log-opts"] == {"max-size": cidisk.LOG_MAX_SIZE, "max-file": cidisk.LOG_MAX_FILE}
    assert out["builder"]["gc"]["enabled"] is True


def test_merged_is_idempotent():
    # arrange / act: merging twice is merging once - the property the conditional restart rests on
    once = cidisk.merged({})

    # assert
    assert cidisk.merged(once) == once


# --- the command ---------------------------------------------------------------------------------------


def test_hygiene_refuses_when_not_root(monkeypatch, host):
    # arrange
    monkeypatch.setattr(cidisk.os, "getuid", lambda: 1000)

    # act / assert: it names the cure, which is the value of the refusal
    with pytest.raises(_Boom) as caught:
        cidisk.hygiene()
    assert "root" in str(caught.value)


def test_hygiene_writes_the_daemon_config_and_restarts_docker(host, monkeypatch):
    # arrange
    calls: list[list[str]] = []
    monkeypatch.setattr(cidisk, "run", _recorder(calls))

    # act
    rc = cidisk.hygiene()

    # assert
    assert rc == 0
    written = json.loads(cidisk.DAEMON_JSON.read_text())
    assert written["log-opts"]["max-size"] == cidisk.LOG_MAX_SIZE
    assert ["systemctl", "restart", "docker"] in calls


def test_hygiene_does_not_restart_docker_when_nothing_changed(host, monkeypatch):
    # arrange: an already-configured host
    # `document()` and not a second json.dumps: reproducing the bytes by hand is what made this test
    # fail the first time, and the failure was right - see the function's own docstring.
    cidisk.DAEMON_JSON.write_text(cidisk.document({}))
    calls: list[list[str]] = []
    monkeypatch.setattr(cidisk, "run", _recorder(calls))

    # act
    rc = cidisk.hygiene()

    # assert: a restart kills the job that is calling this, so an unchanged file must not cause one
    assert rc == 0
    assert ["systemctl", "restart", "docker"] not in calls


def test_hygiene_refuses_an_unparseable_daemon_json_without_writing(host, monkeypatch):
    # arrange: a hand-edited file with a trailing comma
    cidisk.DAEMON_JSON.write_text('{"data-root": "/srv/docker",}')
    monkeypatch.setattr(cidisk, "run", _recorder([]))

    # act / assert: it does NOT overwrite what it could not read - that would be the data loss this
    # whole command exists to avoid, committed by the command itself
    with pytest.raises(_Boom):
        cidisk.hygiene()
    assert cidisk.DAEMON_JSON.read_text() == '{"data-root": "/srv/docker",}'


def test_hygiene_installs_the_timer_and_enables_it(host, monkeypatch):
    # arrange
    calls: list[list[str]] = []
    monkeypatch.setattr(cidisk, "run", _recorder(calls))

    # act
    cidisk.hygiene()

    # assert: the unit, the timer, and the two systemctl calls that make a timer real
    service = (cidisk.UNIT_DIR / cidisk.SERVICE).read_text()
    timer = (cidisk.UNIT_DIR / cidisk.TIMER).read_text()
    assert f"until={cidisk.PRUNE_UNTIL}" in service
    assert "docker system prune -af" in service
    assert "OnCalendar=daily" in timer
    assert ["systemctl", "daemon-reload"] in calls
    assert ["systemctl", "enable", "--now", cidisk.TIMER] in calls


def test_the_scheduled_prune_does_not_touch_volumes(host, monkeypatch):
    # arrange
    monkeypatch.setattr(cidisk, "run", _recorder([]))

    # act
    cidisk.hygiene()

    # assert: a runner with a persistent volume would lose it, and the loss would look like a bug
    # somewhere else entirely
    assert "--volumes" not in (cidisk.UNIT_DIR / cidisk.SERVICE).read_text()


def test_dry_run_changes_nothing_on_the_host(host, monkeypatch):
    # arrange
    calls: list[list[str]] = []
    monkeypatch.setattr(cidisk, "run", _recorder(calls))

    # act
    rc = cidisk.hygiene(dry_run=True)

    # assert: eight hosts is the reason this flag exists - look first, then apply. A dry run may LOOK
    # (that is the point of it), so the property is not "ran nothing" but "changed nothing": no file
    # written, and no systemctl.
    assert rc == 0
    assert not cidisk.DAEMON_JSON.exists()
    assert not (cidisk.UNIT_DIR / cidisk.TIMER).exists()
    assert [c for c in calls if c[0] == "systemctl"] == []
