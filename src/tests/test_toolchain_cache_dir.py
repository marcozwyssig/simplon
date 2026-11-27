"""si#865: the host-directory form of `caches:`, created as the caller outside the product tree.

THE DEFECT. `toolchain:run` runs every container as the caller (`--user uid:gid`), and a `caches:` entry
was only ever a NAMED VOLUME. docker creates a new named volume with the owner and mode of the mount
point in the image - root:root 0755 when the image has no such directory - so the caller could not write
into the one cache the kernel offered. Measured again for this ticket, docker 29.10.1:

    docker run --rm --user 1000:1000 -v v:/cache/gradle busybox:1.36 touch /cache/gradle/x
    touch: /cache/gradle/x: Permission denied

Decided by Marco 2026-11-22: option (b), a host DIRECTORY created as the caller outside the product tree,
like build:fetch's download cache (si#600). `{ dir: <name>, path: <path in the container> }` is that
form; `{ volume: ..., path: ... }` is unchanged.

The last two tests drive a real docker daemon as a non-root uid: a stub of `--user` cannot find this
defect, because the defect IS the daemon's choice of owner.

AAA; the name states the behaviour under test.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

import simplon
from conftest import docker_is_usable
from simplon.adapters import cachedir, hostpath
from simplon.tasks import toolchain


def _boom(msg="boom", *a, **k):
    raise RuntimeError(msg)


def _product(monkeypatch, tmp_path, name="netctl"):
    from simplon.manifest import context
    (tmp_path / f"{name}.yaml").write_text("groups: {}\n", encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext(name, tmp_path, tmp_path / f"{name}.yaml"))


# --- the declaration -------------------------------------------------------------------------------------


def test_a_dir_entry_is_declared_as_a_host_directory_cache():
    # arrange
    body = {"image": "gradle:jdk25", "argv": ["gradle"], "caches": [{"dir": "gradle", "path": "/cache/gradle"}]}

    # act
    cfg = toolchain.declared(body, where="build.compile")

    # assert
    assert cfg.caches == [toolchain.CacheDir(dir="gradle", path="/cache/gradle")]


def test_the_volume_form_is_unchanged_beside_it():
    # arrange
    body = {"image": "gradle:jdk25", "argv": ["gradle"],
            "caches": [{"volume": "v", "path": "/a"}, {"dir": "d", "path": "/b"}]}

    # act
    cfg = toolchain.declared(body, where="build.compile")

    # assert
    assert cfg.caches == [toolchain.Cache(volume="v", path="/a"), toolchain.CacheDir(dir="d", path="/b")]


@pytest.mark.parametrize("entry", [{"volume": "v", "dir": "d", "path": "/a"}, {"path": "/a"}, {"dir": "d"}])
def test_an_entry_that_is_not_exactly_one_form_is_refused_by_name(monkeypatch, entry):
    # arrange
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        toolchain.declared({"image": "gradle:jdk25", "argv": ["x"], "caches": [entry]}, where="build.compile")
    assert "build.compile" in str(e.value) and "`dir:`" in str(e.value) and "`volume:`" in str(e.value)


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "../x", "a\\b", "a:b"])
def test_a_dir_name_that_is_not_one_plain_name_is_refused(monkeypatch, name):
    # arrange: the name becomes one path component under the cache root; anything else lands elsewhere
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        toolchain.declared({"image": "gradle:jdk25", "argv": ["x"], "caches": [{"dir": name, "path": "/c"}]},
                           where="build.compile")
    assert "build.compile" in str(e.value) and repr(name) in str(e.value) and "plain name" in str(e.value)


# --- where the directory lives ---------------------------------------------------------------------------


def test_the_cache_root_follows_the_download_cache_chain_under_its_own_name(tmp_path):
    # arrange
    home = {"HOME": str(tmp_path / "h")}

    # act / assert: named, then the runner's tool cache, then XDG, then HOME
    assert cachedir.root({**home, "DELIVERY_DIR_CACHE": "/named", "RUNNER_TOOL_CACHE": "/r"}) == Path("/named")
    assert cachedir.root({**home, "RUNNER_TOOL_CACHE": "/r", "XDG_CACHE_HOME": "/x"}) == Path(
        "/r/simplon/caches")
    assert cachedir.root({**home, "XDG_CACHE_HOME": "/x"}) == Path("/x/simplon/caches")
    assert cachedir.root(home) == tmp_path / "h" / ".cache" / "simplon" / "caches"


def test_the_cache_root_variable_is_the_one_the_container_mapping_reads():
    # arrange / act / assert: two spellings of one name, held equal so they cannot drift
    assert cachedir.CACHE_ENV == hostpath.CACHE_MOUNT_ENV


def test_a_directory_carries_the_product_and_the_instance():
    # arrange / act
    dev = cachedir.directory(Path("/c"), "netctl", "gradle", "dev")
    a1 = cachedir.directory(Path("/c"), "netctl", "gradle", "a1")

    # assert: netctl#453's property, kept from the volume form
    assert dev == Path("/c/netctl/gradle-dev")
    assert a1 == Path("/c/netctl/gradle-a1")


def test_docker_argv_bind_mounts_the_directory(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    cfg = toolchain.declared({"image": "gradle:jdk25", "argv": ["gradle"],
                              "caches": [{"dir": "gradle", "path": "/cache/gradle"}]}, where="b")

    # act
    line = toolchain.docker_argv(cfg, root=Path("/repo"), product="firn", instance="main", extra=[],
                                 cache_dirs={"gradle": Path("/cache-root/firn/gradle-main")})

    # assert: an absolute source, so docker binds the directory instead of naming a volume
    assert "/cache-root/firn/gradle-main:/cache/gradle" in line
    assert line[line.index("/cache-root/firn/gradle-main:/cache/gradle") - 1] == "-v"
    assert not any(arg.startswith("firn-gradle-main") for arg in line)


# --- before the run: made as the caller, or refused --------------------------------------------------------


def _ran(monkeypatch):
    from simplon.kernel.run import Result
    seen: list[list[str]] = []
    monkeypatch.setattr(toolchain.docker, "run_container",
                        lambda a, name, **kw: seen.append(list(a)) or Result(rc=0, out="", err=""))
    return seen


def test_the_directory_is_made_as_the_caller_before_the_run(monkeypatch, tmp_path):
    # arrange
    (tmp_path / "tree").mkdir()
    _product(monkeypatch, tmp_path / "tree", name="firn")
    monkeypatch.setenv("DELIVERY_DIR_CACHE", str(tmp_path / "caches"))
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    monkeypatch.setattr(toolchain.labinstance, "resolve", lambda *a, **k: "main")
    seen = _ran(monkeypatch)

    # act
    rc = toolchain.run_toolchain(_Ctx("firn build compile"), image="img:1", argv=["cmd"],
                                 caches=[{"dir": "gradle", "path": "/cache/gradle"}])

    # assert
    made = tmp_path / "caches" / "firn" / "gradle-main"
    assert rc == 0
    assert made.is_dir() and made.stat().st_uid == os.getuid()
    assert f"{made}:/cache/gradle" in seen[0]


def test_a_directory_another_uid_owns_is_refused_and_nothing_runs(monkeypatch, tmp_path):
    # arrange: the shared-runner case - a first job under another uid made the directory
    if os.getuid() != 0:
        pytest.skip("making a directory another uid owns takes root")
    (tmp_path / "tree").mkdir()
    _product(monkeypatch, tmp_path / "tree", name="firn")
    monkeypatch.setenv("DELIVERY_DIR_CACHE", str(tmp_path / "caches"))
    theirs = tmp_path / "caches" / "firn" / "gradle-main"
    theirs.mkdir(parents=True)
    os.chown(theirs, 4242, 4242)
    monkeypatch.setattr(toolchain.labinstance, "resolve", lambda *a, **k: "main")
    errors: list[str] = []
    monkeypatch.setattr(toolchain.log, "error", errors.append)
    seen = _ran(monkeypatch)

    # act
    rc = toolchain.run_toolchain(_Ctx("firn build compile"), image="img:1", argv=["cmd"],
                                 caches=[{"dir": "gradle", "path": "/cache/gradle"}])

    # assert: a diagnosis naming the directory, its owner and the repair - and no container
    assert rc == 1 and seen == []
    assert errors == [f"firn build compile: cache 'gradle' needs {theirs} owned by uid 0; it is owned by uid "
                      f"4242. It is a cache: remove it (rm -rf {theirs}, a root shell if another uid owns it) "
                      f"and run this again."]


def test_a_directory_that_cannot_be_made_is_refused_and_nothing_runs(monkeypatch, tmp_path):
    # arrange: a file where the cache root would have to be - unwritable for root too
    (tmp_path / "tree").mkdir()
    _product(monkeypatch, tmp_path / "tree", name="firn")
    (tmp_path / "blocker").write_text("x", encoding="utf-8")
    monkeypatch.setenv("DELIVERY_DIR_CACHE", str(tmp_path / "blocker" / "caches"))
    monkeypatch.setattr(toolchain.labinstance, "resolve", lambda *a, **k: "main")
    errors: list[str] = []
    monkeypatch.setattr(toolchain.log, "error", errors.append)
    seen = _ran(monkeypatch)

    # act
    rc = toolchain.run_toolchain(_Ctx("firn build compile"), image="img:1", argv=["cmd"],
                                 caches=[{"dir": "gradle", "path": "/cache/gradle"}])

    # assert
    assert rc == 1 and seen == []
    assert "firn build compile: cache 'gradle'" in errors[0] and "DELIVERY_DIR_CACHE" in errors[0]


def _dir_cfg():
    return toolchain.declared({"image": "img:1", "argv": ["x"], "caches": [{"dir": "gradle", "path": "/c"}]},
                              where="b")


def _elsewhere(tmp_path):
    """A directory the caller owns outside the cache root, which a planted link would hand the container."""
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "secret").write_text("x", encoding="utf-8")
    return target


def test_a_symlinked_entry_is_refused_and_its_target_is_not_mounted(tmp_path):
    # arrange: somebody who can write the shared root planted the entry as a link to the caller's own dir
    base = tmp_path / "caches"
    (base / "firn").mkdir(parents=True)
    target = _elsewhere(tmp_path)
    (base / "firn" / "gradle-main").symlink_to(target)

    # act
    _, fault = toolchain.prepare_caches(_dir_cfg(), "firn", "main", "firn build compile", base)

    # assert: refused in words, naming the path and the repair
    entry = base / "firn" / "gradle-main"
    assert fault == (f"firn build compile: cache 'gradle' needs {entry} as a real directory; it is a "
                     f"symbolic link. Remove it (rm {entry}) and run this again.")


def test_a_symlinked_product_directory_is_refused(tmp_path):
    # arrange
    base = tmp_path / "caches"
    base.mkdir()
    target = _elsewhere(tmp_path)
    (base / "firn").symlink_to(target)

    # act
    _, fault = toolchain.prepare_caches(_dir_cfg(), "firn", "main", "firn build compile", base)

    # assert: refused, and nothing was made through the link
    assert fault == (f"firn build compile: cache 'gradle' needs {base / 'firn'} as a real directory; it is a "
                     f"symbolic link. Remove it (rm {base / 'firn'}) and run this again.")
    assert sorted(p.name for p in target.iterdir()) == ["secret"]


def test_a_product_directory_another_uid_owns_is_refused(tmp_path):
    # arrange
    if os.getuid() != 0:
        pytest.skip("making a directory another uid owns takes root")
    base = tmp_path / "caches"
    (base / "firn").mkdir(parents=True)
    os.chown(base / "firn", 4242, 4242)

    # act
    _, fault = toolchain.prepare_caches(_dir_cfg(), "firn", "main", "firn build compile", base)

    # assert
    assert fault.startswith(f"firn build compile: cache 'gradle' needs {base / 'firn'} owned by uid 0; it is "
                            f"owned by uid 4242.")
    assert not (base / "firn" / "gradle-main").exists()


def test_the_product_directory_is_made_private_to_the_caller(tmp_path):
    # arrange
    base = tmp_path / "caches"

    # act
    _, fault = toolchain.prepare_caches(_dir_cfg(), "firn", "main", "firn build compile", base)

    # assert
    assert fault == ""
    assert (base / "firn").stat().st_mode & 0o777 == 0o700


def test_a_symlinked_cache_root_itself_is_followed(tmp_path):
    # arrange: the ROOT is the caller's own choice (a runner's tool cache is often a link); only what is
    # below it could have been planted by somebody else
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "root-link").symlink_to(real)

    # act
    _, fault = toolchain.prepare_caches(_dir_cfg(), "firn", "main", "b", tmp_path / "root-link")

    # assert
    assert fault == ""
    assert (real / "firn" / "gradle-main").is_dir()


def _fault_of(result):
    """The refusal `prepare_caches` answers, whichever shape it answers in."""
    return result if isinstance(result, str) else result[1]


def test_a_world_writable_cache_root_without_the_sticky_bit_is_refused(tmp_path):
    # arrange: anybody can rename the caller's product directory away and plant a link after the check
    base = tmp_path / "caches"
    base.mkdir()
    os.chmod(base, 0o777)

    # act
    fault = _fault_of(toolchain.prepare_caches(_dir_cfg(), "firn", "main", "firn build compile", base))

    # assert: refused before anything is made under it, naming the path, the mode and the repair
    assert fault == (f"firn build compile: cache 'gradle' needs the cache root {base} writable by its owner "
                     f"alone or sticky; it is mode 0777, so another user could swap what is checked here "
                     f"before it is mounted. Run `chmod g-w,o-w {base}` or `chmod +t {base}`, then run "
                     f"this again.")
    assert not (base / "firn").exists()


def test_a_sticky_world_writable_cache_root_is_accepted(tmp_path):
    # arrange: /tmp's shape - others may write, nobody may rename what the caller made
    base = tmp_path / "caches"
    base.mkdir()
    os.chmod(base, 0o1777)

    # act
    fault = _fault_of(toolchain.prepare_caches(_dir_cfg(), "firn", "main", "firn build compile", base))

    # assert
    assert fault == ""
    assert (base / "firn" / "gradle-main").is_dir()


def test_the_line_mounts_the_resolved_path_that_was_checked(monkeypatch, tmp_path):
    # arrange: a cache root named through a link - the line must carry where the check actually looked
    (tmp_path / "tree").mkdir()
    _product(monkeypatch, tmp_path / "tree", name="firn")
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "root-link").symlink_to(real)
    monkeypatch.setenv("DELIVERY_DIR_CACHE", str(tmp_path / "root-link"))
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    monkeypatch.setattr(toolchain.labinstance, "resolve", lambda *a, **k: "main")
    seen = _ran(monkeypatch)

    # act
    toolchain.run_toolchain(_Ctx("firn build compile"), image="img:1", argv=["cmd"],
                            caches=[{"dir": "gradle", "path": "/cache/gradle"}])

    # assert
    assert f"{real.resolve()}/firn/gradle-main:/cache/gradle" in seen[0]
    assert not any(str(tmp_path / "root-link") in arg for arg in seen[0])


def test_a_volume_only_command_makes_no_directory(monkeypatch, tmp_path):
    # arrange: the volume form stays what it was, and a command with no `dir:` touches no cache root
    (tmp_path / "tree").mkdir()
    _product(monkeypatch, tmp_path / "tree", name="firn")
    monkeypatch.setenv("DELIVERY_DIR_CACHE", str(tmp_path / "caches"))
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    monkeypatch.setattr(toolchain.labinstance, "resolve", lambda *a, **k: "main")
    seen = _ran(monkeypatch)

    # act
    toolchain.run_toolchain(_Ctx("firn build compile"), image="img:1", argv=["cmd"],
                            caches=[{"volume": "gradle", "path": "/cache/gradle"}])

    # assert
    assert "firn-gradle-main:/cache/gradle" in seen[0]
    assert not (tmp_path / "caches").exists()


class _Ctx:
    def __init__(self, command_path: str) -> None:
        self.command_path = command_path


# --- the container route: a second mapping, made by the launcher -----------------------------------------


def test_on_the_container_route_the_cache_mount_is_translated_to_its_host_side(monkeypatch):
    # arrange: what the launcher's container route exports
    monkeypatch.setenv(hostpath.HOST_ROOT_ENV, "/home/me/tree")
    monkeypatch.setenv(hostpath.MOUNT_ROOT_ENV, "/src")
    monkeypatch.setenv(hostpath.CACHE_MOUNT_ENV, "/cache/dirs")
    monkeypatch.setenv(hostpath.CACHE_HOST_ENV, "/home/me/.cache/simplon/caches")

    # act / assert: both mappings hold, and neither swallows the other
    assert hostpath.translate("/cache/dirs/firn/gradle-main") == "/home/me/.cache/simplon/caches/firn/gradle-main"
    assert hostpath.translate("/src/build") == "/home/me/tree/build"


def test_without_the_cache_mapping_a_cache_outside_the_tree_is_refused_in_a_container(monkeypatch):
    # arrange: a kernel container nobody told about a cache mount
    monkeypatch.setenv(hostpath.HOST_ROOT_ENV, "/home/me/tree")
    monkeypatch.setenv(hostpath.MOUNT_ROOT_ENV, "/src")
    monkeypatch.setattr(hostpath.log, "die", _boom)

    # act / assert: the daemon would make an empty root-owned directory; the kernel says so instead
    with pytest.raises(RuntimeError) as e:
        hostpath.translate("/tmp/.cache/simplon/caches/firn/gradle-main")
    assert "/tmp/.cache/simplon/caches/firn/gradle-main" in str(e.value)


def test_half_a_cache_mapping_is_refused(monkeypatch):
    # arrange
    monkeypatch.setenv(hostpath.CACHE_HOST_ENV, "/home/me/.cache/simplon/caches")
    monkeypatch.setattr(hostpath.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        hostpath.translate("/cache/dirs/firn/gradle-main")
    assert hostpath.CACHE_MOUNT_ENV in str(e.value)


# --- measured against a real daemon, as a non-root uid ----------------------------------------------------

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here")

#: Small, pinned, already pulled by this suite (test_container_lifecycle_e2e.py).
IMAGE = "alpine:3.20"

#: The uid the child drops to when the suite itself runs as root: as root, `--user 0:0` writes anywhere
#: and the defect cannot show.
UID = 4242

CHILD = """
import sys
from pathlib import Path
from simplon.adapters import docker
from simplon.manifest import context
from simplon.tasks import toolchain
tree, entry_json = sys.argv[1:3]
import json
entry = json.loads(entry_json)
context._current = context.ProductContext("sicache", Path(tree), Path(tree) / "sicache.yaml")
got = toolchain.invocation("si865", image=sys.argv[3], argv=["sh", "-c", "touch /cache/c/x"],
                           workdir="/work", env=None, caches=[entry], network="none", cwd=None, extra=[])
sys.exit(2 if got is None else docker.run_container(*got).rc)
"""


def _as_a_caller(base: Path) -> tuple[dict, object]:
    """The environment and preexec for a child that is NOT root: this uid when the suite already is not,
    else UID with the docker socket's group, so it can still reach the daemon."""
    if os.getuid() != 0:
        return {}, None
    sock_gid = os.stat("/var/run/docker.sock").st_gid
    os.chown(base, UID, UID)
    for path in base.rglob("*"):
        os.chown(path, UID, UID)

    def drop() -> None:
        os.setgroups([sock_gid])
        os.setgid(UID)
        os.setuid(UID)
    return {"HOME": str(base)}, drop


def _drive(entry: dict, base: Path) -> subprocess.CompletedProcess:
    import json
    tree = base / "tree"
    tree.mkdir()
    (tree / "sicache.yaml").write_text("groups: {}\ninstance: { env_var: SICACHE_INSTANCE, default: main, max_id_len: 12 }\n", encoding="utf-8")
    env, drop = _as_a_caller(base)
    src = str(Path(simplon.__file__).resolve().parents[1])
    environ = {**os.environ, **env, "PYTHONPATH": src, "DELIVERY_DIR_CACHE": str(base / "caches"),
               "SICACHE_INSTANCE": "e2e"}
    for name in (hostpath.HOST_ROOT_ENV, hostpath.MOUNT_ROOT_ENV, hostpath.CACHE_HOST_ENV):
        environ.pop(name, None)
    return subprocess.run([sys.executable, "-c", CHILD, str(tree), json.dumps(entry), IMAGE],
                          capture_output=True, text=True, env=environ, preexec_fn=drop, timeout=120)


@needs_docker
def test_measured_a_named_volume_is_not_writable_by_the_caller():
    # arrange: the form that was the only one before si#865, kept as the record of why `dir:` exists
    base = Path(tempfile.mkdtemp(prefix="si865-", dir="/tmp"))
    volume = f"si865-{uuid.uuid4().hex[:8]}"

    # act
    try:
        done = _drive({"volume": volume, "path": "/cache/c"}, base)
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", f"sicache-{volume}-e2e"], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)

    # assert: docker made the volume root-owned, and the caller's write was refused
    assert done.returncode != 0, done.stdout + done.stderr
    assert "Permission denied" in done.stdout + done.stderr


@needs_docker
def test_measured_a_dir_cache_is_written_by_the_caller_and_survives_the_run():
    # arrange
    base = Path(tempfile.mkdtemp(prefix="si865-", dir="/tmp"))

    # act
    try:
        done = _drive({"dir": "c", "path": "/cache/c"}, base)
        written = base / "caches" / "sicache" / "c-e2e" / "x"
        owner = written.stat().st_uid if written.is_file() else None
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # assert: the run was green, and what it wrote is on the host, owned by the caller
    assert done.returncode == 0, done.stdout + done.stderr
    assert owner == (os.getuid() if os.getuid() != 0 else UID)


# --- the launcher's container route mounts the cache root and declares both sides -------------------------

DIRS = "/cache/dirs"


def _launch(tmp_path, **env):
    from test_launch_container import _product as scaffold, _run
    root = scaffold(tmp_path / "p")
    base = {"DELIVERY_DIR_CACHE": "", "RUNNER_TOOL_CACHE": "", "XDG_CACHE_HOME": str(tmp_path / "xdg"),
            "HOME": str(tmp_path / "home")}
    base.update(env)
    return _run(root, "support", "doctor", env=base)


def test_the_container_route_mounts_the_xdg_cache_root_with_both_sides_declared(tmp_path):
    # act
    done = _launch(tmp_path)

    # assert
    host = tmp_path / "xdg" / "simplon" / "caches"
    assert done.returncode == 0, done.stderr
    assert host.is_dir()
    last = done.docker[-1]
    assert f"-v {host}:{DIRS}" in last
    assert f"-e DELIVERY_DIR_CACHE={DIRS}" in last
    assert f"-e DELIVERY_DIR_CACHE_HOST={host}" in last


def test_on_a_runner_the_tool_cache_holds_the_cache_root(tmp_path):
    # act
    done = _launch(tmp_path, RUNNER_TOOL_CACHE=str(tmp_path / "runner"))

    # assert
    assert f"-v {tmp_path / 'runner' / 'simplon' / 'caches'}:{DIRS}" in done.docker[-1]


def test_a_named_cache_root_is_mounted_and_its_host_value_does_not_cross_by_name(tmp_path):
    # arrange
    named = tmp_path / "named"

    # act
    done = _launch(tmp_path, DELIVERY_DIR_CACHE=str(named))

    # assert
    last = done.docker[-1]
    assert f"-v {named}:{DIRS}" in last
    assert f"DELIVERY_DIR_CACHE={named}" not in last
    assert " -e DELIVERY_DIR_CACHE " not in f" {last} "


def test_a_cache_root_that_cannot_be_made_is_a_warning_and_nothing_is_declared(tmp_path):
    # arrange: a file where the directory would have to be made
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    # act
    done = _launch(tmp_path, DELIVERY_DIR_CACHE=str(blocker / "caches"))

    # assert: the run goes on; the kernel, told nothing, refuses a `dir:` cache by name if one is used
    assert done.returncode == 0, done.stderr
    last = done.docker[-1]
    assert DIRS not in last and "DELIVERY_DIR_CACHE" not in last
    assert "directory cache root" in done.stderr and str(blocker / "caches") in done.stderr
