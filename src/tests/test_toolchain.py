"""si#95: the toolchain declaration a product writes, and what the kernel refuses."""
import re
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
    from simplon.manifest import context
    from simplon.kernel.run import Result
    # The manifest is WRITTEN and not just named, because si#250 made the executor read it: the layout
    # says where inside the tree a containerised command runs, and a context pointing at a file that is
    # not there is not a product this command could ever have been reached through.
    (tmp_path / "netctl.yaml").write_text("groups: {}\n", encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))
    seen = []
    stopped_by = []
    named = []
    monkeypatch.setattr(toolchain.docker, "run_container",
                        lambda a, name, **kw: seen.append(list(a)) or stopped_by.append(name)
                        or Result(rc=3, out="", err=""))
    monkeypatch.setattr(toolchain, "docker_argv",
                        lambda *a, **k: named.append(k["name"]) or ["docker", "run", "--rm", "img", "cmd"])

    # act
    rc = toolchain.run_toolchain(_Ctx("netctl build compile"), image="img:1", argv=["cmd"])

    # assert: thin - it executes what docker_argv decided, and hands the real rc back
    assert seen == [["docker", "run", "--rm", "img", "cmd"]]
    assert rc == 3
    # si#409: the container it would stop on a cancel is the one the line names, and it HAS a name
    assert stopped_by == named and named[0].startswith("simplon-netctl-")


def test_a_command_with_no_cache_never_asks_for_the_instance_section(monkeypatch, tmp_path):
    # arrange: `simplon init` writes no `instance:` section, so resolving one up front killed every
    # toolchain command in every fresh product (si#105 defect 4)
    from simplon.manifest import context
    from simplon.kernel.run import Result
    # The manifest is WRITTEN and not just named, because si#250 made the executor read it: the layout
    # says where inside the tree a containerised command runs, and a context pointing at a file that is
    # not there is not a product this command could ever have been reached through.
    (tmp_path / "netctl.yaml").write_text("groups: {}\n", encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    monkeypatch.setattr(toolchain.docker, "run_container", lambda a, name, **kw: Result(rc=0, out="", err=""))
    monkeypatch.setattr(toolchain.labinstance, "resolve", _boom)

    # act / assert: the resolve is not reached at all, which is the only proof that it is not required
    assert toolchain.run_toolchain(_Ctx("netctl build compile"), image="img:1", argv=["cmd"]) == 0


def test_a_command_WITH_a_cache_still_resolves_the_instance(monkeypatch, tmp_path):
    # arrange: moving the resolve behind the caches must not quietly drop the netctl#453 property
    from simplon.manifest import context
    from simplon.kernel.run import Result
    # The manifest is WRITTEN and not just named, because si#250 made the executor read it: the layout
    # says where inside the tree a containerised command runs, and a context pointing at a file that is
    # not there is not a product this command could ever have been reached through.
    (tmp_path / "netctl.yaml").write_text("groups: {}\n", encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    monkeypatch.setattr(toolchain.labinstance, "resolve", lambda *a, **k: "a1")
    seen = []
    monkeypatch.setattr(toolchain.docker, "run_container",
                        lambda a, name, **kw: seen.append(list(a)) or Result(rc=0, out="", err=""))

    # act
    toolchain.run_toolchain(_Ctx("netctl build compile"), image="img:1", argv=["cmd"],
                            caches=[{"volume": "gradle-cache", "path": "/cache"}])

    # assert
    assert "netctl-gradle-cache-a1:/cache" in seen[0]


def test_the_refusal_names_the_command_the_block_was_read_from(monkeypatch, tmp_path):
    # arrange: `ctx` is in the signature for exactly this - the values cannot say which command they came
    # from, and "somewhere a toolchain command has no image" is not a diagnosis
    from simplon.manifest import context
    # The manifest is WRITTEN and not just named, because si#250 made the executor read it: the layout
    # says where inside the tree a containerised command runs, and a context pointing at a file that is
    # not there is not a product this command could ever have been reached through.
    (tmp_path / "netctl.yaml").write_text("groups: {}\n", encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        toolchain.run_toolchain(_Ctx("netctl build compile"), argv=["cmd"])
    assert "netctl build compile" in str(e.value)


# --- a HOME the calling uid owns (si#319) --------------------------------------------------------------

def test_the_argv_hands_the_container_a_home(monkeypatch):
    """si#319: a container run as the caller owns the bind mount and NOTHING else, so a tool that wants a
    home dies before it reads anything - measured twice in this family, gradle with "Could not initialize
    native services" and dotnet with `/.dotnet` denied. Both were answered by a hand-made variable
    pointing into the product's tree. The kernel hands one over instead."""
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: ["--user", "1000:1000"])

    # act
    line = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[],
                                 home="/work/build/home")

    # assert
    assert "HOME=/work/build/home" in line


def test_a_product_that_sets_its_own_home_still_wins(monkeypatch):
    """A default and not a rule, and here the ordering IS the mechanism: docker takes the LAST `-e` for a
    name, and the manifest's environment is appended after the kernel's."""
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    line = toolchain.docker_argv(_cfg(env={"HOME": "/home/build"}), root=Path("/repo"), product="p",
                                 instance="dev", extra=[], home="/work/build/home")

    # assert: both are there, the product's is later
    assert line.index("HOME=/home/build") > line.index("HOME=/work/build/home")


def test_no_home_given_leaves_the_argv_exactly_as_it_was(monkeypatch):
    # arrange: the kernel is the only caller that knows a product's output directory, so a body invoked
    # without one must not invent a path
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    line = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="p", instance="dev", extra=[])

    # assert
    assert not any(str(item).startswith("HOME=") for item in line)


def test_cwd_moves_the_working_directory_and_not_the_mount(monkeypatch):
    # arrange: si#371 - firn reads `firn.toml` from its working directory and takes no project option, so
    # a firn project under `src/firn/` needs the container to START there while the whole tree is mounted
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    cfg = _cfg(workdir="/workspace", cwd="src/firn")

    # act
    line = toolchain.docker_argv(cfg, root=Path("/repo"), product="simplon", instance="", extra=[])

    # assert
    assert "/repo:/workspace" in line
    assert line[line.index("-w") + 1] == "/workspace/src/firn"


def test_cwd_sits_below_the_build_root_when_there_is_one(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    cfg = _cfg(workdir="/workspace", cwd="firn")

    # act
    line = toolchain.docker_argv(cfg, root=Path("/repo"), product="p", instance="", extra=[],
                                 build_root="src")

    # assert: both are paths under the mount, the build root first because it is the product's
    assert line[line.index("-w") + 1] == "/workspace/src/firn"


def test_no_cwd_runs_in_the_mount_exactly_as_before(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    line = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="p", instance="", extra=[])

    # assert
    assert line[line.index("-w") + 1] == "/work"


@pytest.mark.parametrize("cwd", ["/src/firn", "../elsewhere", "src/../../x", ""])
def test_a_cwd_that_is_not_a_plain_path_under_the_tree_is_refused_by_name(monkeypatch, cwd):
    # arrange: the same gate `layout:` uses, so the two cannot disagree about what is inside the tree
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        _cfg(cwd=cwd)
    assert "cwd" in str(e.value) and "build.compile" in str(e.value)


def test_the_line_names_its_container_and_labels_it_with_the_product(monkeypatch):
    # arrange: si#409 - a cancelled run left its container running, because the kernel had no name to
    # stop it by and no label to find it by afterwards
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    line = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[],
                                 name="simplon-netctl-0123456789ab")

    # assert: an init as PID 1, the name the unwind removes, and the labels SIGKILL leaves behind
    assert "--init" in line
    assert line[line.index("--name") + 1] == "simplon-netctl-0123456789ab"
    assert "simplon.run=netctl" in line and "simplon.instance=dev" in line
    # and all of it is a docker option, in front of the image - not an argument handed to gradle
    assert line.index("simplon.run=netctl") < line.index("gradle:jdk25")


def test_a_line_with_no_name_has_no_name_and_no_instance_label_without_an_instance(monkeypatch):
    # arrange: a caller that only reads the line has no container to stop; a cache-free command
    # resolves no instance (si#105), and a label must not invent one
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    line = toolchain.docker_argv(_cfg(), root=Path("/repo"), product="netctl", instance="", extra=[])

    # assert
    assert "--name" not in line
    assert "--init" in line and "simplon.run=netctl" in line
    assert not [a for a in line if a.startswith("simplon.instance=")]


def test_every_container_name_is_fresh_and_one_docker_accepts():
    # act
    names = {toolchain.docker.container_name("my product/x") for _ in range(50)}

    # assert: unique per invocation, and only the characters docker allows in a name
    assert len(names) == 50
    assert all(re.fullmatch(r"simplon-my-product-x-[0-9a-f]{12}", n) for n in names), names


# --- si#511: `mounts:` - a tree path bind-mounted over a container path ---------------------------------


def _line(cfg):
    return toolchain.docker_argv(cfg, root=Path("/repo"), product="biz", instance="dev", extra=[])


def test_no_mounts_leaves_the_line_byte_for_byte(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: ["--user", "1000:1000"])

    # act / assert
    assert _line(_cfg()) == _line(_cfg(mounts=[]))
    assert _line(_cfg()).count("-v") == 1


def test_a_mount_sits_after_the_caches_and_before_the_image(monkeypatch):
    # arrange
    from simplon.adapters import hostpath
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: ["--user", "1000:1000"])
    cfg = _cfg(caches=[{"volume": "npm", "path": "/root/.npm"}],
               mounts=["build/nm:/work/src/frontend/node_modules"])

    # act
    line = _line(cfg)

    # assert
    value = f"{hostpath.translate(Path('/repo') / 'build/nm')}:/work/src/frontend/node_modules"
    assert line.index("biz-npm-dev:/root/.npm") < line.index(value) < line.index(cfg.image)
    assert line[line.index(value) - 1] == "-v"


def test_a_readonly_mount_keeps_ro(monkeypatch):
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    assert any(arg.endswith(":/data:ro") for arg in _line(_cfg(mounts=["fixtures:/data:ro"])))


@pytest.mark.parametrize("entry", ["nocolon", "src:rel", "/abs:/x", "../sib:/x", "src\\nm:/x", "src:/x:rw",
                                   "src:/work", "src:/work/", "src:/", "src:/work/a/.."])
def test_a_bad_mount_is_refused_by_name(monkeypatch, entry):
    # arrange
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        _cfg(mounts=[entry])
    assert "build.compile" in str(e.value) and entry in str(e.value)


def test_two_mounts_on_one_target_are_refused(monkeypatch):
    monkeypatch.setattr(toolchain.log, "die", _boom)
    with pytest.raises(RuntimeError) as e:
        _cfg(mounts=["a:/x", "b:/x/"])
    assert "/x" in str(e.value)


@pytest.mark.parametrize("raw", ["a:/b", [{"a": 1}], [3]])
def test_mounts_must_be_a_list_of_strings(monkeypatch, raw):
    monkeypatch.setattr(toolchain.log, "die", _boom)
    with pytest.raises(RuntimeError) as e:
        _cfg(mounts=raw)
    assert "mounts" in str(e.value)


def test_a_toolchain_built_positionally_still_means_what_it_did():
    cfg = toolchain.Toolchain("img:1", ["x"], "/work", {}, [], "")
    assert cfg.mounts == [] and cfg.cwd == ""


def test_a_mount_over_the_tree_says_so_in_these_words(monkeypatch):
    monkeypatch.setattr(toolchain.log, "die", _boom)
    with pytest.raises(RuntimeError) as e:
        _cfg(mounts=["src:/work"])
    assert str(e.value) == ("build.compile: mount 'src:/work' would cover /work, the tree this command runs "
                            "in; mount over a path below it instead")


# --- si#511: the mount points exist before the run, owned by the caller --------------------------------


def _mounted(*entries):
    return _cfg(mounts=list(entries))


def test_the_source_and_the_inner_target_are_created_before_the_run(tmp_path):
    # act
    fault = toolchain.prepare_mounts(_mounted("build/nm:/work/src/frontend/node_modules"), tmp_path, "b.g")

    # assert: both exist, and both are the caller's - docker would have made them root's
    import os
    assert fault == ""
    for made in (tmp_path / "build/nm", tmp_path / "src/frontend/node_modules"):
        assert made.is_dir() and made.stat().st_uid == os.getuid()


def test_a_target_outside_the_workdir_creates_nothing_on_the_host(tmp_path):
    assert toolchain.prepare_mounts(_mounted("build/nm:/cache/nm"), tmp_path, "b.g") == ""
    assert sorted(p.name for p in tmp_path.iterdir()) == ["build"]


def test_a_source_that_is_a_file_is_refused(tmp_path):
    # arrange
    (tmp_path / "build").mkdir()
    (tmp_path / "build/nm").write_text("x", encoding="utf-8")

    # act
    fault = toolchain.prepare_mounts(_mounted("build/nm:/work/src/nm"), tmp_path, "b.g")

    # assert: named, and nothing was made for the other half either
    assert "b.g" in fault and "build/nm" in fault and "not a directory" in fault
    assert not (tmp_path / "src").exists()


@pytest.mark.skipif(not hasattr(__import__("os"), "geteuid") or __import__("os").geteuid() != 0,
                    reason="handing a directory to another uid takes root")
def test_a_path_owned_by_someone_else_is_refused_before_any_mkdir(tmp_path):
    # arrange: the target's nearest existing ancestor belongs to uid 4242
    import os
    (tmp_path / "src").mkdir()
    os.chown(tmp_path / "src", 4242, 4242)

    # act
    fault = toolchain.prepare_mounts(_mounted("x:/work/src/frontend/node_modules"), tmp_path, "b.g")

    # assert: refused in words, and the source was NOT made first - the check comes before any mkdir
    assert fault == ("b.g: mount 'x:/work/src/frontend/node_modules' needs src owned by uid 0; it is owned "
                     "by uid 4242. Remove it or chown it (it takes a root shell), then run this again.")
    assert not (tmp_path / "x").exists()


def test_invocation_returns_none_on_a_mount_fault(monkeypatch, tmp_path):
    # arrange
    from simplon.manifest import context
    (tmp_path / "biz.yaml").write_text("groups: {}\n", encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext("biz", tmp_path, tmp_path / "biz.yaml"))
    (tmp_path / "build").mkdir()
    (tmp_path / "build/nm").write_text("x", encoding="utf-8")
    errors = []
    monkeypatch.setattr(toolchain.log, "error", errors.append)

    # act
    got = toolchain.invocation("biz gate", image="gradle:jdk25", argv=["x"], workdir="/work", env=None,
                               caches=None, network=None, cwd=None, extra=[], mounts=["build/nm:/work/nm"])

    # assert
    assert got is None and errors and "build/nm" in errors[0]
