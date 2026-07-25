"""Unit tests for linux - the pure Linux host-provisioning primitives (kernel modules / apt / binfmt).
Moved here from netctl's orchestrator - the mechanism is platform's now (netctl#651 strand 2). The
headline is the netctl#95 modprobe-`-a` regression guard. AAA throughout, negatives included."""
import pytest

from delivery import linux


def test_modprobe_argv_always_uses_dash_a_and_loads_every_module():
    # arrange: three modules (the netctl#95 case - a bare modprobe would load only the first)
    mods = ["wireguard", "mpls_router", "mpls_iptunnel"]

    # act
    argv = linux.modprobe_argv(mods)

    # assert: `-a` is present (else only the first loads, netctl#95) and ALL modules are passed through
    assert argv[:2] == ["modprobe", "-a"]
    assert argv[2:] == mods


def test_modprobe_argv_rejects_an_empty_module_list():
    # arrange / act / assert: no modules is a programming error, not a silent no-op
    with pytest.raises(ValueError):
        linux.modprobe_argv([])


def test_load_or_install_snippet_uses_dash_a_in_both_modprobe_calls():
    # arrange
    mods = ["wireguard", "mpls_router", "mpls_iptunnel"]

    # act
    snippet = linux.load_or_install_snippet(mods, pkg="linux-modules-extra-X")

    # assert: both the load and the post-install reload use `-a` (the netctl#95 fix), install is gated
    assert snippet.count("modprobe -a wireguard mpls_router mpls_iptunnel") == 2
    assert 'apt-get install -y "linux-modules-extra-X"' in snippet


def test_load_or_install_snippet_defaults_to_the_running_kernel_modules_extra():
    # arrange / act: no pkg override
    snippet = linux.load_or_install_snippet(["wireguard"])

    # assert: the default targets the running kernel's extras package (shell-expanded on the host)
    assert 'apt-get install -y "linux-modules-extra-$(uname -r)"' in snippet


def test_apt_candidate_present_true_for_a_real_numeric_version():
    # arrange: a policy block with a numeric candidate (the package is installable)
    text = "linux-modules-extra-6.8.0-117-generic:\n  Installed: (none)\n  Candidate: 6.8.0-117.117\n"

    # act / assert
    assert linux.apt_candidate_present(text) is True


def test_apt_candidate_present_false_for_a_none_candidate():
    # arrange: an empty index reports "(none)" (dead DNS / unpopulated index) - NOT installable
    text = "  Installed: (none)\n  Candidate: (none)\n"

    # act / assert
    assert linux.apt_candidate_present(text) is False


def test_has_f_flag_detects_a_container_capable_handler():
    # arrange: a Rosetta entry carries flags OCF (F = fix-binary, container-capable)
    rosetta = "enabled\ninterpreter /usr/bin/rosetta\nflags: OCF\n"

    # act / assert
    assert linux.has_f_flag(rosetta) is True


def test_has_f_flag_false_without_the_f_flag():
    # arrange: an entry without F cannot run from inside a container
    plain = "enabled\ninterpreter /usr/bin/qemu\nflags: OC\n"

    # act / assert
    assert linux.has_f_flag(plain) is False
