"""Unit tests for labnet - the pure helpers behind a containerlab lab lifecycle (OOB-bridge snippets and
the post-deploy verdict). Moved here from netctl (netctl#730); no VM, no subprocess; AAA throughout."""
from delivery import labnet


def test_oob_up_snippet_is_idempotent_create_and_up():
    # arrange / act
    snip = labnet.oob_bridge_up_snippet("oob-zh")

    # assert: skips when present, else adds + ups the bridge
    assert "ip link show oob-zh" in snip
    assert "ip link add oob-zh type bridge" in snip
    assert "ip link set oob-zh up" in snip


def test_oob_down_snippet_removes_only_when_present():
    # arrange / act
    snip = labnet.oob_bridge_down_snippet("oob-be")

    # assert
    assert "ip link show oob-be" in snip
    assert "ip link del oob-be" in snip
    assert snip.endswith("|| true")


def test_deploy_verdict_ok_when_deployed():
    # arrange / act / assert: a completed deploy is ok regardless of count
    assert labnet.deploy_verdict(True, 0) == "ok"
    assert labnet.deploy_verdict(True, 25) == "ok"


def test_deploy_verdict_die_when_failed_and_no_containers():
    # arrange / act / assert: failed every attempt AND nothing up -> fatal
    assert labnet.deploy_verdict(False, 0) == "die"


def test_deploy_verdict_degraded_when_failed_but_some_containers():
    # arrange / act / assert: partial deploy (an accepted flake floor) -> degraded
    assert labnet.deploy_verdict(False, 18) == "degraded"
