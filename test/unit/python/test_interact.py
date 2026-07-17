"""Unit tests for interact - the pure resolver/arg logic of the lab-interaction commands."""
from delivery import interact


def test_parse_logs_args_defaults_to_listing_with_tail_120():
    # arrange / act: no args
    args = interact.parse_logs_args([])

    # assert: no node (-> list mode), not following, default tail
    assert args.node is None
    assert args.follow is False
    assert args.tail == "120"


def test_parse_logs_args_reads_follow_tail_and_node():
    # arrange / act: a node with -f and --tail=N in any order
    args = interact.parse_logs_args(["--tail=50", "netctl-zh", "-f"])

    # assert
    assert args.node == "netctl-zh"
    assert args.follow is True
    assert args.tail == "50"


def test_parse_logs_args_last_positional_wins():
    # arrange / act: two positionals (mirrors the bash `*) node="$a"` overwrite)
    args = interact.parse_logs_args(["netctl-zh", "netctl-be"])

    # assert
    assert args.node == "netctl-be"


def test_normalize_container_prefixes_only_when_missing():
    # arrange / act / assert
    assert interact.normalize_container("netctl-zh") == "clab-netctl-netctl-zh"
    assert interact.normalize_container("clab-netctl-sidecar-zh") == "clab-netctl-sidecar-zh"


def test_strip_prefix_removes_the_clab_prefix():
    # arrange / act / assert
    assert interact.strip_prefix("  clab-netctl-client-zh\tUp 2m") == "  client-zh\tUp 2m"


def test_resolve_connect_target_ssh_for_a_managed_device():
    # arrange: l3s-zh1 is a managed device with a mgmt IP
    devices = [("10.0.0.13", "l3s-zh1"), ("10.0.0.14", "w3s-zh1")]

    # act
    t = interact.resolve_connect_target("l3s-zh1", devices, ["zh"])

    # assert: SSH to its IP
    assert t == interact.ConnectTarget(kind="ssh", value="10.0.0.13")


def test_resolve_connect_target_site_name_maps_to_its_controller_container():
    # arrange: a bare lab-site name
    # act
    t = interact.resolve_connect_target("zh", devices=[], site_names=["zh", "be"])

    # assert: shell into the netctl-<site> controller
    assert t == interact.ConnectTarget(kind="shell", value="clab-netctl-netctl-zh")


def test_resolve_connect_target_other_name_is_a_container_shell():
    # arrange: a non-device, non-site name (e.g. sidecar-zh)
    # act
    t = interact.resolve_connect_target("sidecar-zh", devices=[], site_names=["zh"])

    # assert: shell into the prefixed container
    assert t == interact.ConnectTarget(kind="shell", value="clab-netctl-sidecar-zh")
