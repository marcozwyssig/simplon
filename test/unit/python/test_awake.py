"""Unit tests for the keep-awake OS decision (netctl#546, kernel-extracted netctl#592). The
`_keep_awake_argv` helper is PURE - it maps an OS name to the argv of an idle-sleep inhibitor (or None) -
so it is tested here without spawning any process. AAA throughout; goal-stating names.
"""
from delivery.awake import _keep_awake_argv


def test_keep_awake_on_darwin_maps_to_the_caffeinate_inhibitor_argv():
    # arrange: the host OS name reported for macOS
    os_name = "Darwin"
    # act
    argv = _keep_awake_argv(os_name)
    # assert: caffeinate with the display/idle/system/disk + user-active flags
    assert argv == ["caffeinate", "-dimsu"]


def test_keep_awake_on_linux_maps_to_a_systemd_inhibit_idle_wrapper():
    # arrange: the host OS name reported for Linux
    os_name = "Linux"
    # act
    argv = _keep_awake_argv(os_name)
    # assert: an idle-only systemd-inhibit holding a long-lived sleep
    assert argv is not None
    assert argv[0] == "systemd-inhibit"
    assert "--what=idle" in argv
    assert argv[-2:] == ["sleep", "infinity"]


def test_keep_awake_on_unknown_os_is_a_no_op():
    # arrange: any OS name that has no known inhibitor
    os_name = "Windows"
    # act
    argv = _keep_awake_argv(os_name)
    # assert: None so the context manager spawns nothing
    assert argv is None
