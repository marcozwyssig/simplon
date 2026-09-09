"""si#95: the toolchain declaration a product writes, and what the kernel refuses."""
from pathlib import Path

import pytest

from simplon.tasks import toolchain


def _boom(msg="boom", *a, **k):
    raise RuntimeError(msg)


class _Ctx:
    """The one thing `run_toolchain` reads off its `typer.Context`: which command it was invoked as."""

    def __init__(self, command_path: str) -> None:
        self.command_path = command_path


def test_a_declaration_becomes_a_toolchain(monkeypatch):
    # arrange
    body = {"image": "gradle:jdk25", "workdir": "/work",
            "argv": ["gradle", "build"],
            "env": {"GRADLE_USER_HOME": "/home/gradle/.gradle"},
            "caches": [{"volume": "gradle-cache", "path": "/home/gradle/.gradle"}]}

    # act
    cfg = toolchain.declared(body, where="build.compile")

    # assert
    assert cfg.image == "gradle:jdk25"
    assert cfg.argv == ["gradle", "build"]
    assert cfg.caches == [toolchain.Cache(volume="gradle-cache", path="/home/gradle/.gradle")]


def test_an_unpinned_image_is_refused_by_the_one_gate(monkeypatch):
    # arrange: the refusal must come from pinned_image, not a second check written here
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        toolchain.declared({"image": "gradle", "argv": ["gradle"]}, where="build.compile")
    assert "gradle" in str(e.value)


def test_a_declaration_without_argv_is_refused_by_name(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert: the message names the key and where it was missing
    with pytest.raises(RuntimeError) as e:
        toolchain.declared({"image": "gradle:jdk25"}, where="build.compile")
    assert "argv" in str(e.value) and "build.compile" in str(e.value)


def test_workdir_defaults_so_a_product_need_not_write_it():
    # arrange / act
    cfg = toolchain.declared({"image": "gcc:14", "argv": ["make"]}, where="build.compile")

    # assert: the spec's "the user has only their parameters" - /work is the kernel's answer
    assert cfg.workdir == "/work"


def _cfg(**kw):
    body = {"image": "gradle:jdk25", "argv": ["gradle", "build"]}
    body.update(kw)
    return toolchain.declared(body, where="build.compile")


def test_the_argv_mounts_the_tree_and_runs_as_the_caller(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: ["--user", "1000:1000"])

    # act
    line = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[])

    # assert: the bind mount, the workdir, and the uid that owns whatever the run writes
    assert "--user" in line and "1000:1000" in line
    assert "-v" in line and "/repo:/work" in line
    assert line[-2:] == ["gradle", "build"]


def test_the_caller_argv_is_APPENDED_to_the_manifest_argv(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    line = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev",
                                 extra=["--rerun-tasks"])

    # assert: netctl#1091's promise - the full vocabulary survives - on top of a pinned default
    assert line[-3:] == ["gradle", "build", "--rerun-tasks"]


def test_an_empty_caller_argv_changes_nothing(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    a = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[])
    b = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[])

    # assert
    assert a == b and a[-2:] == ["gradle", "build"]


def test_cache_volumes_carry_the_product_and_the_instance(monkeypatch):
    # arrange: netctl#453's property, which only netctl knew by hand until now
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    cfg = _cfg(caches=[{"volume": "gradle-cache", "path": "/home/gradle/.gradle"}])

    # act
    dev = toolchain.docker_argv(cfg, root=Path("/repo"), product="netctl", instance="dev", extra=[])
    a1 = toolchain.docker_argv(cfg, root=Path("/repo"), product="netctl", instance="a1", extra=[])

    # assert
    assert "netctl-gradle-cache-dev:/home/gradle/.gradle" in dev
    assert "netctl-gradle-cache-a1:/home/gradle/.gradle" in a1


def test_env_reaches_the_container_and_nothing_else_does(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    cfg = _cfg(env={"GRADLE_USER_HOME": "/home/gradle/.gradle"})

    # act
    line = toolchain.docker_argv(cfg, root=Path("/repo"), product="netctl", instance="dev", extra=[])

    # assert: no implicit inheritance - what the manifest names, and only that
    assert "GRADLE_USER_HOME=/home/gradle/.gradle" in line
    assert len([x for x in line if x == "-e"]) == 1


def test_the_network_appears_only_when_it_is_given(monkeypatch):
    # arrange: the one runtime value the manifest cannot supply (the spec's section 5)
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    without = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[])
    with_net = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev",
                                     extra=[], network="scratch-net")

    # assert
    assert "--network" not in without
    assert ["--network", "scratch-net"] == with_net[3:5]   # right after `docker run --rm`


def test_the_executor_runs_the_assembled_line_and_returns_its_rc(monkeypatch, tmp_path):
    # arrange: the product context is the one value the executor READS, so it is stood in for here the
    # way every other task test does it (tests/test_docker.py's fixture). The manifest keys arrive as
    # PARAMETERS since si#105 - that is what makes the design's `with:` block bindable at all.
    from simplon import context
    from simplon.run import Result
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))
    seen = []
    monkeypatch.setattr(toolchain, "run",
                        lambda a, **kw: seen.append(list(a)) or Result(rc=3, out="", err=""))
    monkeypatch.setattr(toolchain, "docker_argv", lambda *a, **k: ["docker", "run", "--rm", "img", "cmd"])

    # act
    rc = toolchain.run_toolchain(_Ctx("netctl build compile"), image="img:1", argv=["cmd"])

    # assert: thin - it executes what docker_argv decided, and hands the real rc back
    assert seen == [["docker", "run", "--rm", "img", "cmd"]]
    assert rc == 3


def test_a_command_with_no_cache_never_asks_for_the_instance_section(monkeypatch, tmp_path):
    # arrange: `simplon init` writes no `instance:` section, so resolving one up front killed every
    # toolchain command in every fresh product (si#105 defect 4)
    from simplon import context
    from simplon.run import Result
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    monkeypatch.setattr(toolchain, "run", lambda a, **kw: Result(rc=0, out="", err=""))
    monkeypatch.setattr(toolchain.labinstance, "resolve", _boom)

    # act / assert: the resolve is not reached at all, which is the only proof that it is not required
    assert toolchain.run_toolchain(_Ctx("netctl build compile"), image="img:1", argv=["cmd"]) == 0


def test_a_command_WITH_a_cache_still_resolves_the_instance(monkeypatch, tmp_path):
    # arrange: moving the resolve behind the caches must not quietly drop the netctl#453 property
    from simplon import context
    from simplon.run import Result
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    monkeypatch.setattr(toolchain.labinstance, "resolve", lambda *a, **k: "a1")
    seen = []
    monkeypatch.setattr(toolchain, "run",
                        lambda a, **kw: seen.append(list(a)) or Result(rc=0, out="", err=""))

    # act
    toolchain.run_toolchain(_Ctx("netctl build compile"), image="img:1", argv=["cmd"],
                            caches=[{"volume": "gradle-cache", "path": "/cache"}])

    # assert
    assert "netctl-gradle-cache-a1:/cache" in seen[0]


def test_the_refusal_names_the_command_the_block_was_read_from(monkeypatch, tmp_path):
    # arrange: `ctx` is in the signature for exactly this - the values cannot say which command they came
    # from, and "somewhere a toolchain command has no image" is not a diagnosis
    from simplon import context
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        toolchain.run_toolchain(_Ctx("netctl build compile"), argv=["cmd"])
    assert "netctl build compile" in str(e.value)
