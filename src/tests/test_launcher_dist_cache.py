"""si#600: on the container route the launcher mounts the host's download cache into the kernel's container.

Decided by Marco 2026-11-08 (si#600): mounted by default, because on firn's container route nothing reached
the cache unless CI wired the variable in by hand. The host side is resolved with the chain
`simplon.tasks.fetchfile.cache_dir` uses (DELIVERY_DIST_CACHE, RUNNER_TOOL_CACHE, XDG_CACHE_HOME, HOME),
mounted at one fixed container path, and the container is told THAT path - never the host's. A cache that
cannot be mounted is a warning and `off`, never a failed run.

Driven against a fake `docker` that records its argv (the harness of `test_launch_container.py`), so the
assertions are on the line a shell really assembled.

AAA; the name states the behaviour under test.
"""
from test_launch_container import _product, _run

MOUNT = "/cache/dist"


def _quiet(tmp_path, **env):
    """The caller's environment with every link of the chain pinned, so the host running the suite cannot
    leak its own cache into the measurement."""
    base = {"DELIVERY_DIST_CACHE": "", "RUNNER_TOOL_CACHE": "", "XDG_CACHE_HOME": str(tmp_path / "xdg"),
            "HOME": str(tmp_path / "home")}
    base.update(env)
    return base


def test_by_default_the_xdg_cache_is_created_mounted_and_named_by_its_container_path(tmp_path):
    # arrange
    root = _product(tmp_path / "p")

    # act
    done = _run(root, "support", "doctor", env=_quiet(tmp_path))

    # assert
    host = tmp_path / "xdg" / "simplon" / "dist"
    assert done.returncode == 0, done.stderr
    assert host.is_dir()
    last = done.docker[-1]
    assert f"-v {host}:{MOUNT}" in last
    assert f"-e DELIVERY_DIST_CACHE={MOUNT}" in last


def test_without_xdg_the_cache_is_under_home(tmp_path):
    # arrange
    root = _product(tmp_path / "p")

    # act
    done = _run(root, "support", "doctor", env=_quiet(tmp_path, XDG_CACHE_HOME=""))

    # assert
    assert f"-v {tmp_path / 'home' / '.cache' / 'simplon' / 'dist'}:{MOUNT}" in done.docker[-1]


def test_on_a_runner_the_tool_cache_wins_over_xdg(tmp_path):
    # arrange
    root = _product(tmp_path / "p")

    # act
    done = _run(root, "support", "doctor", env=_quiet(tmp_path, RUNNER_TOOL_CACHE=str(tmp_path / "runner")))

    # assert
    assert f"-v {tmp_path / 'runner' / 'simplon' / 'dist'}:{MOUNT}" in done.docker[-1]
    assert not (tmp_path / "xdg").exists()


def test_a_named_cache_is_mounted_and_its_host_path_does_not_cross(tmp_path):
    # arrange
    root = _product(tmp_path / "p")
    named = tmp_path / "named"

    # act
    done = _run(root, "support", "doctor", env=_quiet(tmp_path, DELIVERY_DIST_CACHE=str(named)))

    # assert: mounted, and the variable reaching the container is the container path - the DELIVERY_*
    # loop does not forward the host's value by name on top of it
    last = done.docker[-1]
    assert f"-v {named}:{MOUNT}" in last
    assert f"-e DELIVERY_DIST_CACHE={MOUNT}" in last
    assert " -e DELIVERY_DIST_CACHE " not in f" {last} "
    assert f"DELIVERY_DIST_CACHE={named}" not in last


def test_off_mounts_nothing_creates_nothing_and_says_off_inside(tmp_path):
    # arrange
    root = _product(tmp_path / "p")

    # act
    done = _run(root, "support", "doctor", env=_quiet(tmp_path, DELIVERY_DIST_CACHE="off"))

    # assert
    assert done.returncode == 0, done.stderr
    last = done.docker[-1]
    assert MOUNT not in last.replace(f"DELIVERY_DIST_CACHE={MOUNT}", "")
    assert "-e DELIVERY_DIST_CACHE=off" in last
    assert not (tmp_path / "xdg").exists()
    assert not (tmp_path / "home").exists()


def test_a_cache_that_cannot_be_created_is_a_warning_and_the_run_goes_on_without_it(tmp_path):
    # arrange: a regular file where a directory would have to be made - unwritable for root too
    root = _product(tmp_path / "p")
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    # act
    done = _run(root, "support", "doctor", env=_quiet(tmp_path, DELIVERY_DIST_CACHE=str(blocker / "dist")))

    # assert
    assert done.returncode == 0, done.stderr
    last = done.docker[-1]
    assert f":{MOUNT}" not in last
    assert "-e DELIVERY_DIST_CACHE=off" in last
    assert "download cache" in done.stderr
    assert str(blocker / "dist") in done.stderr


def test_a_cache_path_with_a_colon_is_not_mounted_because_v_would_split_it(tmp_path):
    # arrange
    root = _product(tmp_path / "p")
    odd = tmp_path / "a:b"

    # act
    done = _run(root, "support", "doctor", env=_quiet(tmp_path, DELIVERY_DIST_CACHE=str(odd)))

    # assert
    assert done.returncode == 0, done.stderr
    last = done.docker[-1]
    assert f":{MOUNT}" not in last
    assert "-e DELIVERY_DIST_CACHE=off" in last
    assert "colon" in done.stderr
    assert not odd.exists()


def test_the_batch_launcher_mounts_no_cache_and_tells_the_kernel_off(tmp_path):
    # arrange: held as text, as test_launch_cmd does - there is no Windows here to drive it on
    root = _product(tmp_path / "p")

    # act
    cmd = (root / "democtl.cmd").read_text(encoding="utf-8")

    # assert: off, set on the line itself, and a host value of the name does not cross on top of it
    assert 'set "DOCKER_ENV=%DOCKER_ENV% -e DELIVERY_DIST_CACHE=off"' in cmd
    assert 'if /i "%~1"=="DELIVERY_DIST_CACHE" goto :eof' in cmd
    assert f":{MOUNT}" not in cmd
