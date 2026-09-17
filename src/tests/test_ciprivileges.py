"""si#92: the CI privileges of a host, granted deliberately and as root.

WHY A COMMAND AND NOT A PARAGRAPH IN A RUNBOOK. Every product on a CI host writes the same six lines by
hand, and one of them is easy to leave out: without `#includedir /etc/sudoers.d` in `/etc/sudoers` the
file in that directory is INERT, and everything still looks right. Measured on three hosts that answered
`sudo: a password is required` while the file sat at the expected path.

WHY IT REFUSES WHEN IT IS NOT ROOT. This grants the privilege the kernel needs in order to be allowed to
do anything, so it cannot grant it to itself - si#87 drew the same line one step lower down. A refusal
that says so is the whole value; "it did not work" is not.

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.tasks import ciprivileges


class _Boom(Exception):
    pass


def _die(msg, *a, **k):
    raise _Boom(msg)


def _recorder(calls, rc=0):
    from simplon.run import Result as R
    return lambda argv, **kw: calls.append(list(argv)) or R(rc=rc, out="", err="")


@pytest.fixture
def host(monkeypatch, tmp_path):
    """A fake host: root, a known user, and /etc/sudoers[.d] redirected into tmp_path."""
    monkeypatch.setattr(ciprivileges.os, "getuid", lambda: 0)
    monkeypatch.setattr(ciprivileges, "_user_exists", lambda u: u == "runner")
    monkeypatch.setattr(ciprivileges.log, "die", _die)
    sudoers = tmp_path / "sudoers"
    sudoers.write_text("Defaults env_reset\n#includedir /etc/sudoers.d\n")
    monkeypatch.setattr(ciprivileges, "SUDOERS", sudoers)
    monkeypatch.setattr(ciprivileges, "SUDOERS_D", tmp_path / "sudoers.d")
    (tmp_path / "sudoers.d").mkdir()
    return tmp_path


def test_it_refuses_when_it_is_not_root_and_says_to_run_it_as_root(monkeypatch):
    # arrange: the ordinary case - somebody runs it in a job, where the kernel has no privilege
    monkeypatch.setattr(ciprivileges.os, "getuid", lambda: 1000)
    monkeypatch.setattr(ciprivileges.log, "die", _die)

    # act / assert: the message has to name the cure, not merely report failure
    with pytest.raises(_Boom) as e:
        ciprivileges.grant("runner")
    assert "root" in str(e.value)


def test_it_refuses_a_user_that_does_not_exist_and_writes_nothing(host, monkeypatch):
    # arrange
    calls = []
    monkeypatch.setattr(ciprivileges, "run", _recorder(calls))

    # act / assert
    with pytest.raises(_Boom) as e:
        ciprivileges.grant("nosuchuser")
    assert "nosuchuser" in str(e.value)
    assert list((host / "sudoers.d").iterdir()) == []


def test_it_grants_passwordless_sudo_and_the_docker_group(host, monkeypatch):
    # arrange: visudo accepts, every verification answers yes
    calls = []
    monkeypatch.setattr(ciprivileges, "run", _recorder(calls))
    monkeypatch.setattr(ciprivileges, "_groups_of", lambda u: ["runner", "docker"])

    # act
    rc = ciprivileges.grant("runner")

    # assert
    assert rc == 0
    dropin = host / "sudoers.d" / "runner"
    assert dropin.read_text() == "runner ALL=(ALL) NOPASSWD: ALL\n"
    assert oct(dropin.stat().st_mode)[-3:] == "440"
    assert ["groupadd", "-f", "docker"] in calls
    assert ["usermod", "-aG", "docker", "runner"] in calls


def test_a_sudoers_file_visudo_refuses_is_never_installed(host, monkeypatch):
    # arrange: visudo says no. Writing a broken file straight into /etc/sudoers.d can lock out sudo for
    # EVERYONE, so it is validated somewhere else first and only then moved into place.
    from simplon.run import Result as R
    monkeypatch.setattr(ciprivileges, "run",
                        lambda argv, **kw: R(rc=1 if "visudo" in argv[0] else 0, out="", err=""))

    # act / assert
    with pytest.raises(_Boom):
        ciprivileges.grant("runner")
    assert list((host / "sudoers.d").iterdir()) == []


def test_the_includedir_line_is_added_only_when_it_is_missing(host, monkeypatch):
    # arrange: a sudoers WITHOUT the include - the failure mode that makes the drop-in inert while
    # everything looks correct
    calls = []
    monkeypatch.setattr(ciprivileges, "run", _recorder(calls))
    monkeypatch.setattr(ciprivileges, "_groups_of", lambda u: ["runner", "docker"])
    ciprivileges.SUDOERS.write_text("Defaults env_reset\n")

    # act
    ciprivileges.grant("runner")

    # assert: appended once, and appending again on a second run does not duplicate it
    body = ciprivileges.SUDOERS.read_text()
    assert body.count("#includedir /etc/sudoers.d") == 1
    ciprivileges.grant("runner")
    assert ciprivileges.SUDOERS.read_text().count("#includedir /etc/sudoers.d") == 1


def test_the_verification_runs_AS_the_user_not_as_root(host, monkeypatch):
    # arrange: root can always sudo, so checking from here would pass on a host where the grant did
    # nothing - the si#87 distinction, one step up
    calls = []
    monkeypatch.setattr(ciprivileges, "run", _recorder(calls))
    monkeypatch.setattr(ciprivileges, "_groups_of", lambda u: ["runner", "docker"])

    # act
    ciprivileges.grant("runner")

    # assert
    assert ["sudo", "-nu", "runner", "sudo", "-n", "true"] in calls


def test_a_grant_that_did_not_take_is_reported_rather_than_claimed(host, monkeypatch):
    # arrange: everything was written, and the check as the user still refuses
    from simplon.run import Result as R
    monkeypatch.setattr(ciprivileges, "run",
                        lambda argv, **kw: R(rc=1 if argv[:3] == ["sudo", "-nu", "runner"] else 0,
                                             out="", err=""))
    monkeypatch.setattr(ciprivileges, "_groups_of", lambda u: ["runner", "docker"])

    # act / assert: a setup command that reports success it did not verify is the defect this repository
    # keeps finding elsewhere
    with pytest.raises(_Boom) as e:
        ciprivileges.grant("runner")
    assert "sudo" in str(e.value)
