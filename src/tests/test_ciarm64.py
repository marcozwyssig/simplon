"""si#358: linux/arm64 emulation on a CI host, checked first and registered only when missing.

The host is faked at the one seam the module talks through, `run`: `docker buildx ls --format json`
answers with what the fake builder sees, and the fake models the measured staleness - a builder made
before the emulator was registered does not see it until `docker buildx rm simplon`.

AAA; the name states the behaviour under test.
"""
import json

import pytest

from simplon.run import Result
from simplon.tasks import ciarm64, image


class _Boom(Exception):
    pass


def _die(msg, *a, **k):
    raise _Boom(msg)


class _Host:
    """A runner: whether the kernel has an arm64 handler, and whether the builder has seen it."""

    def __init__(self, virt, registered=False, builder_sees=None):
        self.virt = virt
        self.registered = registered
        self.builder_sees = registered if builder_sees is None else builder_sees
        self.calls = []

    def run(self, argv, **kw):
        argv = list(argv)
        self.calls.append(argv)
        if argv == ["systemd-detect-virt"]:
            return Result(rc=1 if self.virt == "none" else 0, out=self.virt + "\n", err="")
        if argv[:4] == ["docker", "buildx", "ls", "--format"]:
            platforms = ["linux/amd64"] + (["linux/arm64"] if self.builder_sees else [])
            line = json.dumps({"Name": image.BUILDER, "Nodes": [{"Platforms": platforms}]})
            return Result(rc=0, out=line + "\n", err="")
        if argv[:3] == ["docker", "buildx", "rm"]:
            self.builder_sees = self.registered
        if argv[:3] == ["apt-get", "install", "-y"] or argv[:3] == ["systemctl", "enable", "--now"]:
            self.registered = True
        if argv[:2] == ["docker", "create"]:
            return Result(rc=0, out="c0ffee\n", err="")
        return Result(rc=0, out="", err="")

    def ran(self, *prefix):
        return any(call[:len(prefix)] == list(prefix) for call in self.calls)


@pytest.fixture
def root(monkeypatch, tmp_path):
    monkeypatch.setattr(ciarm64.os, "getuid", lambda: 0)
    monkeypatch.setattr(ciarm64.log, "die", _die)
    monkeypatch.setattr(ciarm64.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(ciarm64, "INTERPRETER", tmp_path / "lib" / "qemu-aarch64-static")
    monkeypatch.setattr(ciarm64, "SCRIPT", tmp_path / "sbin" / "binfmt-aarch64")
    monkeypatch.setattr(ciarm64, "UNIT_DIR", tmp_path / "systemd")
    return tmp_path


def _on(monkeypatch, host):
    monkeypatch.setattr(ciarm64, "run", host.run)
    monkeypatch.setattr(image, "run", host.run)
    return host


# --- the branch ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("answer", ["kvm", "qemu", "vmware", "microsoft", "none"])
def test_a_vm_or_bare_metal_takes_the_package(answer):
    # arrange / act / assert
    assert ciarm64.branch(answer) == ciarm64.VM_BRANCH


def test_an_lxc_container_takes_the_boot_script():
    # arrange / act / assert
    assert ciarm64.branch("lxc\n") == ciarm64.LXC_BRANCH


@pytest.mark.parametrize("answer", ["docker", "systemd-nspawn", "wsl", ""])
def test_an_answer_with_no_recipe_takes_no_branch(answer):
    # arrange / act / assert
    assert ciarm64.branch(answer) == ""


def test_an_unknown_virtualisation_is_refused_by_name_before_anything_changes(monkeypatch, root):
    # arrange
    host = _on(monkeypatch, _Host("docker"))

    # act
    with pytest.raises(_Boom) as refused:
        ciarm64.arm64()

    # assert: the answer is named, and nothing but the question was asked
    assert "'docker'" in str(refused.value) and "NOTHING was changed" in str(refused.value)
    assert host.calls == [["systemd-detect-virt"]]


def test_without_root_a_real_run_is_refused(monkeypatch, root):
    # arrange
    monkeypatch.setattr(ciarm64.os, "getuid", lambda: 1000)
    host = _on(monkeypatch, _Host("kvm"))

    # act
    with pytest.raises(_Boom) as refused:
        ciarm64.arm64()

    # assert
    assert "needs root" in str(refused.value) and host.calls == []


# --- the three outcomes ----------------------------------------------------------------------------------


def test_a_builder_that_already_runs_arm64_is_reported_as_set_up_and_nothing_is_installed(monkeypatch, root,
                                                                                          capsys):
    # arrange
    host = _on(monkeypatch, _Host("lxc", registered=True))

    # act
    rc = ciarm64.arm64()

    # assert
    assert rc == 0 and "already set up" in capsys.readouterr().out
    assert not host.ran("apt-get") and not host.ran("systemctl") and not host.ran("docker", "buildx", "rm")


def test_a_builder_made_before_the_emulator_is_made_again_and_nothing_is_installed(monkeypatch, root, capsys):
    # arrange: the kernel has the handler, the builder does not see it
    host = _on(monkeypatch, _Host("kvm", registered=True, builder_sees=False))

    # act
    rc = ciarm64.arm64()

    # assert
    assert rc == 0 and host.ran("docker", "buildx", "rm", image.BUILDER)
    assert not host.ran("apt-get")
    assert "Nothing was installed" in capsys.readouterr().out


def test_a_vm_without_the_emulator_gets_the_package_and_a_fresh_builder(monkeypatch, root):
    # arrange
    host = _on(monkeypatch, _Host("kvm"))

    # act
    rc = ciarm64.arm64()

    # assert
    assert rc == 0
    assert host.ran("apt-get", "install", "-y", ciarm64.PACKAGE)
    assert host.ran("docker", "buildx", "rm", image.BUILDER)
    assert not (root / "systemd").exists()


def test_an_lxc_without_the_emulator_gets_the_interpreter_the_script_and_an_enabled_unit(monkeypatch, root):
    # arrange
    host = _on(monkeypatch, _Host("lxc"))

    # act
    rc = ciarm64.arm64()

    # assert
    assert rc == 0
    assert host.ran("docker", "create", ciarm64.BINFMT_IMAGE)
    assert host.ran("docker", "cp", f"c0ffee:{ciarm64.INTERPRETER_INSIDE}", str(ciarm64.INTERPRETER))
    assert ciarm64.SCRIPT.read_text() == ciarm64.script()
    assert (ciarm64.UNIT_DIR / ciarm64.UNIT).read_text() == ciarm64.unit()
    assert host.ran("systemctl", "enable", "--now", ciarm64.UNIT)
    assert not host.ran("apt-get")


def test_a_recipe_that_ran_but_left_the_builder_without_arm64_is_red(monkeypatch, root, capsys):
    # arrange: the install "succeeds" and registers nothing
    host = _Host("kvm")
    real = host.run

    def no_effect(argv, **kw):
        result = real(argv, **kw)
        if list(argv)[:2] == ["apt-get", "install"]:
            host.registered = False
        return result

    monkeypatch.setattr(ciarm64, "run", no_effect)
    monkeypatch.setattr(image, "run", no_effect)

    # act
    rc = ciarm64.arm64()

    # assert
    assert rc == 1 and "still does not list linux/arm64" in capsys.readouterr().err


def test_a_dry_run_needs_no_root_and_changes_nothing(monkeypatch, root, capsys):
    # arrange
    monkeypatch.setattr(ciarm64.os, "getuid", lambda: 1000)
    host = _on(monkeypatch, _Host("lxc"))

    # act
    rc = ciarm64.arm64(dry_run=True)

    # assert
    assert rc == 0 and "lxc recipe" in capsys.readouterr().out
    assert not host.ran("apt-get") and not host.ran("systemctl") and not host.ran("docker", "create")
    assert not host.ran("docker", "buildx", "rm") and not host.ran("docker", "buildx", "create")
    assert not ciarm64.SCRIPT.exists()


# --- the LXC recipe's text -------------------------------------------------------------------------------


def test_the_boot_script_registers_aarch64_with_the_f_flag_against_the_copied_interpreter():
    # arrange / act
    text = ciarm64.script()

    # assert: firn's measured line (docs/07 §7), and the early exit that makes a re-run a no-op
    assert r":qemu-aarch64:M::\x7fELF\x02\x01\x01" in text
    assert f":{ciarm64.INTERPRETER}:POCF'" in text
    assert "[ -e /run/binfmt/qemu-aarch64 ] && exit 0" in text


def test_the_unit_runs_before_docker_and_is_installed_for_boot():
    # arrange / act
    text = ciarm64.unit()

    # assert
    assert "Before=docker.service" in text and "WantedBy=multi-user.target" in text
    assert f"ExecStart={ciarm64.SCRIPT}" in text


def test_a_build_that_cannot_run_arm64_names_the_support_command():
    # arrange / act
    said = image._emulation_command(["linux/arm64"])

    # assert
    assert "support ci-arm64" in said
