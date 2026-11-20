"""The carrier's directories for a stack's bind mounts: declared, created, checked (si#782).

WHAT THE FAKE BELOW CONFIRMS IS WHAT WAS MEASURED, AND ONLY THAT. `FakeDaemon` answers the Docker API the
way Docker 29.1 answered it on 2026-11-20, directly and through a Portainer 2.45 proxy on the same host: a
missing bind source refused at create with 400 "bind source path does not exist", an archive of a created
container whose first header is the bound directory, an absent image answered 404. A stub cannot find a
defect in an assumption written into it; those assumptions were measured against the real daemon before
they were written here, and the PR that brought this records the run. No real carrier was reachable.

No network: `_request` and `_docker` are the only places that open one, and both are replaced.

AAA throughout.
"""
from __future__ import annotations

import io
import json
import tarfile
import urllib.error

import pytest

from simplon.adapters import portainer
from simplon.manifest import context, deployment, environments
from simplon.tasks import carrier

from conftest import Recorder

REPOSITORY = environments.Repository(url="github.com/acme/app", compose="docker-compose.yml")
TARGET = portainer.PortainerTarget("https://portainer.local", "t", 3, "app-prod")


def _document(directories: object, carrier_: str = "haus", **extra: object) -> dict:
    prod: dict = {"backend": "portainer", "carrier": carrier_, "stack": "app-prod",
                  "repository": {"url": "github.com/acme/app"}, "directories": directories, **extra}
    if not carrier_:
        del prod["carrier"], prod["stack"], prod["repository"]
    return {"carriers": {"haus": {"portainer": {"url_from": "HAUS"}}},
            "cd": {"default": "prod", "environments": {"prod": prod}}}


def _prod(directories: object) -> environments.Environment:
    return environments.parse_data(_document(directories), ("portainer",)).environments["prod"]


# --- what a manifest may write ----------------------------------------------------------------------

def test_an_entry_is_read_as_path_owner_and_mode() -> None:
    # act
    env = _prod([{"path": "/srv/app/data/", "owner": "1000:1000", "mode": "0750"},
                 {"path": "/srv/app/backups", "owner": "1000"},
                 {"path": "/srv/app/cache"}])

    # assert
    assert env.directories == (
        environments.Directory("/srv/app/data", 1000, 1000, 0o750),
        environments.Directory("/srv/app/backups", 1000, None, None),
        environments.Directory("/srv/app/cache", None, None, None))


def test_an_environment_that_declares_none_has_none() -> None:
    """The products that predate the key are unchanged by it."""
    # act / assert
    assert _prod(None).directories == ()


@pytest.mark.parametrize("key, value, read_as", [
    ("mode", "0750", 488), ("mode", "750", 750), ("owner", "33:33", 2013), ("owner", "1000:50", 60050)])
def test_an_unquoted_owner_or_mode_is_refused_because_yaml_has_already_changed_it(key, value, read_as) -> None:
    """MEASURED with the kernel's own loader: these arrive as the numbers on the right. 488 the mode and
    488 the typo cannot be told apart once parsed, so the only honest answer is to ask for the quotes."""
    # arrange
    from simplon.manifest import yamlkeys

    parsed = yamlkeys.load(f"path: /srv/a\n{key}: {value}\n")

    # act / assert
    assert parsed[key] == read_as
    with pytest.raises(ValueError) as refused:
        _prod([parsed])
    assert "must be quoted" in str(refused.value)


@pytest.mark.parametrize("entry, fragment", [
    ({"path": "srv/app"}, "names no absolute `path:`"),
    ({"owner": "1000"}, "names no absolute `path:`"),
    ({"path": "/srv/app", "owner": "cockpit"}, "is not a uid or uid:gid"),
    ({"path": "/srv/app", "mode": "rwx"}, "is not an octal mode"),
    ({"path": "/srv/app", "mod": "0750"}, "does not take mod"),
    ("/srv/app", "is a mapping with a `path:`"),
])
def test_an_entry_that_cannot_be_acted_on_is_refused_by_what_is_wrong(entry, fragment) -> None:
    # act / assert
    with pytest.raises(ValueError) as refused:
        _prod([entry])
    assert fragment in str(refused.value)


@pytest.mark.parametrize("path", [
    "/srv/app/{{ 7*7 }}", "/srv/app/{% raw %}", "/srv/app/../../etc", "/srv/my app", "/srv/app;rm -rf x",
    "/srv/app/$(id)", "/srv/app\nx"])
def test_a_path_that_could_be_read_as_code_on_the_carrier_never_reaches_the_play(path, monkeypatch,
                                                                                tmp_path) -> None:
    """SEEN RED FIRST, on the carrier side: before this rule `/srv/app/{{ 7*7 }}` reached the play and the
    pinned ansible image created `/srv/app/49` - a template evaluated as root on the carrier."""
    # arrange
    document = _document([{"path": path, "owner": "1000"}])
    monkeypatch.setattr(context, "_current", context.ProductContext("p", tmp_path, tmp_path / "p.yaml"))
    monkeypatch.setattr(context.ProductContext, "manifest_data", lambda self: document)

    # act / assert
    with pytest.raises(ValueError) as refused:
        carrier.directories_on("haus")
    assert "may only use letters, digits" in str(refused.value)


def test_the_path_rule_is_one_function_a_resolved_value_can_be_put_through() -> None:
    """The follow-up resolves `${VAR}` from the deployment's values; the resolved string goes through this
    same function, because a value from the environment is no safer than one from the file."""
    # act / assert
    assert environments.carrier_path("/srv/biz-cockpit/prod/data", "x") == "/srv/biz-cockpit/prod/data"
    with pytest.raises(ValueError):
        environments.carrier_path("/srv/{{ lookup('env', 'HOME') }}", "x")


def test_the_carrier_vars_are_tagged_so_ansible_takes_them_literally() -> None:
    """THE SECOND WALL, measured with the pinned image: tagged `!unsafe`, `/srv/app/{{ 7*7 }}` was created
    as a directory of that literal name rather than `/srv/app/49`."""
    # act
    text = carrier.unsafe_vars([{"path": "/srv/app/{{ 7*7 }}", "owner": "1000"}])

    # assert
    assert 'path: !unsafe "/srv/app/{{ 7*7 }}"' in text and 'owner: !unsafe "1000"' in text
    assert carrier.unsafe_vars([]) == "carrier_directories: []\n"


def test_a_list_is_required_and_not_one_entry() -> None:
    # act / assert
    with pytest.raises(ValueError) as refused:
        _prod({"path": "/srv/app"})
    assert "must be a list of entries" in str(refused.value)


def test_directories_with_no_carrier_have_nowhere_to_be() -> None:
    # act / assert
    with pytest.raises(ValueError) as refused:
        environments.parse_data(_document([{"path": "/srv/app"}], carrier_=""), ("portainer",))
    assert "no machine for them to be created on or checked against" in str(refused.value)


# --- the check, against a daemon that answers as the real one did -----------------------------------

class FakeDaemon:
    """The endpoint's Docker as Portainer proxies it, with a filesystem of `path -> (uid, gid, mode)`.

    A value of `"file"` is a regular file at that path; an exception is raised on the archive call.
    """

    def __init__(self, tree: dict, image: bool = True, fail: "dict[str, int] | None" = None) -> None:
        self.tree = tree
        self.image = image
        self.fail = fail or {}
        self.calls: list[tuple[str, str]] = []
        self.containers: dict[str, str] = {}

    @staticmethod
    def _error(code: int, message: str) -> urllib.error.HTTPError:
        return urllib.error.HTTPError("u", code, message, {}, io.BytesIO(  # type: ignore[arg-type]
            json.dumps({"message": message}).encode()))

    def __call__(self, target, method: str, path: str, body: "bytes | None" = None,
                 content_type: str = "application/json") -> io.BytesIO:
        self.calls.append((method, path))
        for prefix, code in self.fail.items():
            if path.startswith(prefix):
                raise self._error(code, "refused by the fake")
        if path.startswith("/images/") and path.endswith("/json"):
            if not self.image:
                raise self._error(404, f"No such image: {portainer.PROBE_REFERENCE}")
            return io.BytesIO(b"{}")
        if path.startswith("/images/load"):
            assert body and tarfile.open(fileobj=io.BytesIO(body)).getnames(), "a real image tar is sent"
            self.image = True
            return io.BytesIO(b'{"stream":"Loaded image"}')
        if path == "/containers/create":
            spec = json.loads(body or b"{}")
            mount = spec["HostConfig"]["Mounts"][0]
            assert mount["Type"] == "bind" and mount["ReadOnly"] is True, "a -v bind would CREATE the path"
            if mount["Source"] not in self.tree:
                raise self._error(400, 'invalid mount config for type "bind": bind source path does not '
                                       f'exist: {mount["Source"]}')
            self.containers[f"c{len(self.containers)}"] = mount["Source"]
            return io.BytesIO(json.dumps({"Id": f"c{len(self.containers) - 1}", "Warnings": []}).encode())
        if "/archive" in path:
            seen = self.tree[self.containers[path.split("/")[2]]]
            if isinstance(seen, Exception):
                raise seen
            out = io.BytesIO()
            with tarfile.open(fileobj=out, mode="w") as archive:
                info = tarfile.TarInfo("probe")
                if seen == "file":
                    info.type, info.uid, info.gid, info.mode = tarfile.REGTYPE, 0, 0, 0o644
                else:
                    info.type, (info.uid, info.gid, info.mode) = tarfile.DIRTYPE, seen
                archive.addfile(info)
            return io.BytesIO(out.getvalue())
        if method == "DELETE":
            return io.BytesIO(b"")
        raise AssertionError(f"unexpected call {method} {path}")


def _deploy(monkeypatch, daemon: FakeDaemon, directories: list) -> Recorder:
    """`deploy up` through the shipped backend, with the stack side recorded and the daemon faked.

    The environment is PARSED from a manifest rather than built, so that on the code before si#782 - which
    ignored the key - the red was "it deployed", not "the test could not build its input". `raising=False`
    on `_docker` for the same reason.
    """
    recorder = Recorder({"/stacks": [{"Name": "app-prod", "EndpointId": 3, "Id": 9,
                                      "Status": portainer.STATUS_UP}]})
    monkeypatch.setattr(portainer, "_request", recorder)
    monkeypatch.setattr(portainer, "_docker", daemon, raising=False)
    monkeypatch.setattr(portainer, "_target_for", lambda env: (TARGET, REPOSITORY))
    monkeypatch.setattr(portainer, "check_registry_access", lambda *args: None)  # si#785, tested there
    portainer.PortainerBackend().deploy(
        _prod(directories), deployment.Version(selector="1.4.0", tag="1.4.0", builds=False))
    return recorder


MISSING_AND_ROOT = [{"path": "/srv/app/data", "owner": "1000:1000", "mode": "0750"},
                    {"path": "/srv/app/backups", "owner": "1000:1000", "mode": "0750"},
                    {"path": "/srv/app/belege", "owner": "1000:1000", "mode": "0750"}]


def test_a_missing_or_root_owned_directory_is_refused_before_the_stack_is_touched(monkeypatch) -> None:
    """THE TICKET'S ACCEPTANCE, seen red first: before si#782 this deployed, and Docker then created the
    missing directory as root and the service died with "unable to open database file"."""
    # arrange
    daemon = FakeDaemon({"/srv/app/data": (1000, 1000, 0o750), "/srv/app/belege": (0, 0, 0o755)})
    recorder = Recorder({})

    # act / assert
    with pytest.raises(portainer.PortainerError) as refused:
        recorder = _deploy(monkeypatch, daemon, MISSING_AND_ROOT)

    message = str(refused.value)
    assert "/srv/app/backups is missing" in message
    assert "/srv/app/belege is owned by 0:0, declared 1000:1000 and has mode 0755, declared 0750" in message
    assert "/srv/app/data" not in message.split(" on the carrier")[0], "a ready one is not named"
    assert "install -d -o 1000 -g 1000 -m 0750 /srv/app/backups" in message, "the way out is named"
    assert [call for call in recorder.calls if call[0] != "GET"] == [], "the stack was not touched"


def test_every_probe_container_is_removed_and_none_is_left_on_the_carrier(monkeypatch) -> None:
    # arrange
    daemon = FakeDaemon({"/srv/app/data": (1000, 1000, 0o750), "/srv/app/belege": (0, 0, 0o755)})

    # act
    with pytest.raises(portainer.PortainerError):
        _deploy(monkeypatch, daemon, MISSING_AND_ROOT)

    # assert
    removed = {path.split("/")[2].split("?")[0] for method, path in daemon.calls if method == "DELETE"}
    assert removed == set(daemon.containers)


def test_directories_as_declared_let_the_deployment_through(monkeypatch, capsys) -> None:
    # arrange
    daemon = FakeDaemon({"/srv/app/data": (1000, 1000, 0o750), "/srv/app/backups": (1000, 5, 0o2770)})

    # act
    recorder = _deploy(monkeypatch, daemon, [
        {"path": "/srv/app/data", "owner": "1000:1000", "mode": "0750"},
        {"path": "/srv/app/backups", "owner": "1000"}])

    # assert
    assert any(call[0] == "PUT" for call in recorder.calls), "the stack was redeployed"
    assert "2 of 2 declared directories ready" in capsys.readouterr().out


def test_what_the_manifest_does_not_state_is_not_checked(monkeypatch) -> None:
    """None is "not stated", not "root" and not "0755": a default would be a statement nobody made."""
    # arrange
    daemon = FakeDaemon({"/srv/app/data": (1000, 0, 0o700)})

    # act / assert - no refusal over the group or the mode
    _deploy(monkeypatch, daemon, [{"path": "/srv/app/data", "owner": "1000"}])


def test_a_file_where_a_directory_belongs_is_named_as_one(monkeypatch) -> None:
    # arrange
    daemon = FakeDaemon({"/srv/app/data": "file"})

    # act / assert
    with pytest.raises(portainer.PortainerError) as refused:
        _deploy(monkeypatch, daemon, [{"path": "/srv/app/data", "owner": "1000"}])
    assert "/srv/app/data is not a directory" in str(refused.value)
    assert "install -d" not in str(refused.value), "install -d does not turn a file into a directory"


def test_the_probe_image_is_loaded_when_the_carrier_does_not_have_it(monkeypatch) -> None:
    """No registry, no pull: the kernel carries the empty image as bytes."""
    # arrange
    daemon = FakeDaemon({"/srv/app/data": (1000, 1000, 0o750)}, image=False)

    # act
    _deploy(monkeypatch, daemon, [{"path": "/srv/app/data", "owner": "1000:1000"}])

    # assert
    assert ("POST", "/images/load?quiet=1") in daemon.calls


def test_the_probe_image_is_one_docker_can_load() -> None:
    """The bytes are a `docker save` archive: a manifest naming the tag, a config and one layer."""
    # act
    archive = tarfile.open(fileobj=io.BytesIO(portainer._probe_image()))
    manifest = json.load(archive.extractfile("manifest.json"))  # type: ignore[arg-type]

    # assert
    assert manifest[0]["RepoTags"] == [portainer.PROBE_REFERENCE]
    assert set(archive.getnames()) == {"manifest.json", "layer.tar", manifest[0]["Config"]}


@pytest.mark.parametrize("daemon, said", [
    (FakeDaemon({"/srv/app/data": (1000, 1000, 0o750)}, image=False, fail={"/images/load": 500}),
     "directory check did not run"),
    (FakeDaemon({"/srv/app/data": (1000, 1000, 0o750)}, fail={"/images/": 403}),
     "directory check did not run"),
    (FakeDaemon({"/srv/app/data": (1000, 1000, 0o750)}, fail={"/containers/create": 403}),
     "could not tell whether /srv/app/data is ready"),
    (FakeDaemon({"/srv/app/data": OSError("connection reset")}),
     "could not tell whether /srv/app/data is ready"),
])
def test_a_probe_that_could_not_tell_is_neither_ready_nor_missing(monkeypatch, capsys, daemon, said) -> None:
    """A FAILED PROBE IS NOT A RESULT. It refuses nothing, because "missing" would send the operator to
    create a directory that may well be there - and it is said by name, because "ready" is not what it is."""
    # act
    _deploy(monkeypatch, daemon, [{"path": "/srv/app/data", "owner": "1000:1000"}])

    # assert
    out = capsys.readouterr().out
    assert said in out
    assert "declared directory ready" not in out, "nothing was found ready"


def test_an_environment_with_no_directories_asks_the_carrier_nothing(monkeypatch) -> None:
    # arrange
    daemon = FakeDaemon({})

    # act
    _deploy(monkeypatch, daemon, [])

    # assert
    assert daemon.calls == []


# --- deploy carrier creates them --------------------------------------------------------------------

def test_the_carrier_run_creates_the_directories_of_every_environment_standing_on_it(monkeypatch,
                                                                                   tmp_path) -> None:
    """The play configures the MACHINE; `test` and `prod` on one carrier both get theirs from one run."""
    # arrange
    document = _document([{"path": "/srv/app/prod", "owner": "1000:1000", "mode": "0750"}])
    environments_ = document["cd"]["environments"]
    environments_["test"] = {**environments_["prod"], "stack": "app-test",
                             "directories": [{"path": "/srv/app/test", "owner": "1000"},
                                             {"path": "/srv/app/prod", "owner": "0"}]}
    document["carriers"]["other"] = {"portainer": {"url_from": "O"}}
    environments_["elsewhere"] = {**environments_["prod"], "carrier": "other",
                                  "directories": [{"path": "/srv/not-here"}]}
    monkeypatch.setattr(context, "_current", context.ProductContext("p", tmp_path, tmp_path / "p.yaml"))
    monkeypatch.setattr(context.ProductContext, "manifest_data", lambda self: document)

    # act
    items = carrier.directories_on("haus")

    # assert
    assert items == [{"path": "/srv/app/prod", "owner": "1000", "group": "1000", "mode": "0750"},
                     {"path": "/srv/app/test", "owner": "1000"}]


def test_the_play_reads_the_directories_as_data_and_creates_parents_plainly(tmp_path, monkeypatch) -> None:
    """The parents first and with nothing set: measured, `file` creating a deep path in one step gives
    the missing parents the declared owner and mode too."""
    # arrange
    import yaml

    from simplon.kernel import run

    monkeypatch.setattr(run, "stream", lambda argv, **_: 0)
    items = [{"path": "/srv/app/data", "owner": "1000"}]

    # act
    carrier._ansible(carrier.carrierspec.Carrier("haus", portainer=carrier.carrierspec.Portainer("P", 1)),
                     "10.0.0.9", tmp_path, tmp_path / "key", 9443, items)

    # assert
    play = yaml.safe_load((tmp_path / "carrier.yml").read_text(encoding="utf-8"))[0]
    assert play["vars_files"] == [carrier.VARS_FILE]
    assert (tmp_path / carrier.VARS_FILE).read_text() == carrier.unsafe_vars(
        items, {"portainer_password_variable": "P_PASSWORD"})
    names = [task["name"] for task in play["tasks"]]
    parents = names.index("The parents of those directories are there, as the system makes them")
    assert names[parents + 1] == "The directories the stacks bind are there, with their owner and mode"
    assert set(play["tasks"][parents]["ansible.builtin.file"]) == {"path", "state"}
