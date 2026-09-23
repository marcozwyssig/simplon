"""Unit tests for interact - the pure resolver/arg logic of the lab-interaction commands.

si#312: the container prefix is PASSED, never derived and never defaulted. These tests are written
against a NON-default instance prefix (`clab-netctl-a1-`) wherever one is involved, because the defect
that opened the ticket was invisible under the reserved instance's spelling: a module that carries
`clab-netctl-` answers every question correctly for `dev` and silently for everybody else.
"""
import pathlib

import pytest

from simplon import interact

#: The two spellings netctl's own naming produces, and the only reason both appear here is that one is a
#: PREFIX of the other - which is what makes "did this name come from my instance" a real question.
DEV = "clab-netctl-"
A1 = "clab-netctl-a1-"


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


def test_normalize_container_prefixes_with_the_prefix_it_is_given():
    # arrange / act / assert: the same bare node under two instances resolves to two containers. Before
    # si#312 both answers were the dev one, which is the measured defect (`--instance a1` read dev's log).
    assert interact.normalize_container("netctl-zh", A1) == "clab-netctl-a1-netctl-zh"
    assert interact.normalize_container("netctl-zh", DEV) == "clab-netctl-netctl-zh"


def test_normalize_container_leaves_a_name_that_already_carries_the_given_prefix():
    # arrange / act / assert
    assert interact.normalize_container("clab-netctl-a1-sidecar-zh", A1) == "clab-netctl-a1-sidecar-zh"


def test_normalize_container_does_not_read_a_sibling_prefix_as_its_own():
    # arrange: a name spelled for `dev`, resolved while the caller is on `a1`. `dev`'s prefix is a PREFIX
    # of a1's, never the other way round, so this is the direction that can actually go wrong.
    # act
    resolved = interact.normalize_container("clab-netctl-sidecar-zh", A1)

    # assert: not silently accepted as an a1 container. The name is nonsense and docker will say so,
    # which is the whole point - a wrong answer that LOOKS right is what this ticket is about.
    assert resolved == "clab-netctl-a1-clab-netctl-sidecar-zh"


def test_strip_prefix_drops_the_given_prefix_from_a_listing_line():
    # arrange: what netctl actually hands over - a `docker ps --format '  {{.Names}}\t{{.Status}}'` LINE,
    # indented, not a bare container name (measured at netctl cli.py:229 and :242).
    # act / assert
    assert interact.strip_prefix("  clab-netctl-a1-client-zh\tUp 2m", A1) == "  client-zh\tUp 2m"


def test_strip_prefix_drops_only_the_first_occurrence():
    # arrange: a line whose remainder repeats the prefix - a status column, a path, a second column. The
    # `.replace` this function used to be emptied EVERY occurrence, so the tail was corrupted too.
    line = "  clab-netctl-a1-client-zh\tUp 2m (image clab-netctl-a1-base)"

    # act
    shown = interact.strip_prefix(line, A1)

    # assert: the name is shortened, the rest of the line is left exactly as docker wrote it
    assert shown == "  client-zh\tUp 2m (image clab-netctl-a1-base)"


def test_resolve_connect_target_ssh_for_a_managed_device():
    # arrange: l3s-zh1 is a managed device with a mgmt IP
    devices = [("10.0.0.13", "l3s-zh1"), ("10.0.0.14", "w3s-zh1")]

    # act
    t = interact.resolve_connect_target("l3s-zh1", devices, {"zh": "netctl-zh"}, A1)

    # assert: SSH to its IP - a device is reached by address, so no prefix is involved
    assert t == interact.ConnectTarget(kind="ssh", value="10.0.0.13")


def test_resolve_connect_target_site_name_maps_to_the_controller_the_caller_named():
    # arrange: the site -> controller-container map is the PRODUCT's knowledge (si#312: the kernel names
    # no product), the prefix places it on an instance.
    # act
    t = interact.resolve_connect_target("zh", [], {"zh": "netctl-zh", "be": "netctl-be"}, A1)

    # assert: this is the call that used to open a shell in DEV's controller while the operator had
    # named another instance - the one finding of the three that mis-ACTS rather than mis-reads.
    assert t == interact.ConnectTarget(kind="shell", value="clab-netctl-a1-netctl-zh")


def test_resolve_connect_target_other_name_is_a_container_shell():
    # arrange / act: a non-device, non-site name (e.g. sidecar-zh)
    t = interact.resolve_connect_target("sidecar-zh", [], {"zh": "netctl-zh"}, A1)

    # assert
    assert t == interact.ConnectTarget(kind="shell", value="clab-netctl-a1-sidecar-zh")


def test_require_instance_present_accepts_a_prefix_some_container_carries():
    # arrange: a1 is up
    names = ["clab-netctl-a1-netctl-zh", "clab-netctl-a1-client-zh"]

    # act / assert: no refusal, and nothing returned - the function exists to REFUSE, so a caller cannot
    # mistake its answer for a value it may ignore.
    assert interact.require_instance_present(A1, names) is None


def test_require_instance_present_refuses_when_nothing_carries_the_prefix():
    # arrange: the measured reproduction. `--instance a1` has zero containers while dev is running; the
    # command used to resolve to dev's container and stream its live log.
    names = ["clab-netctl-netctl-zh", "clab-netctl-client-zh"]

    # act / assert
    with pytest.raises(interact.InstanceNotPresent) as excinfo:
        interact.require_instance_present(A1, names)

    # assert: the message carries the prefix it looked for, because "nothing is running" and "something
    # else is running" are the two readings a bare refusal would leave open
    assert A1 in str(excinfo.value)


def test_require_instance_present_refuses_on_an_empty_host():
    # arrange / act / assert: no containers at all is the same answer as somebody else's containers - the
    # instance this command presupposes is not there.
    with pytest.raises(interact.InstanceNotPresent):
        interact.require_instance_present(A1, [])


def test_require_instance_present_is_not_fooled_by_a_name_carrying_the_prefix_in_the_middle():
    # arrange: a substring match is what `docker ps --filter name=` does, and it is not what belongs to an
    # instance. Only a name that STARTS with the prefix does.
    # act / assert
    with pytest.raises(interact.InstanceNotPresent):
        interact.require_instance_present(A1, ["wrapper-clab-netctl-a1-netctl-zh"])


def test_the_module_names_no_product_and_no_reserved_instance():
    # arrange: si#312's first sentence - `_PREFIX = "clab-netctl-"` disappears as a constant ALTOGETHER,
    # and no default value takes its place, because a preset prefix is the same defect by a detour.
    source = pathlib.Path(interact.__file__).read_text(encoding="utf-8")

    # act / assert: the container-name vocabulary of one product, in code or in prose
    for product_spelling in ("clab-", "netctl-"):
        assert product_spelling not in source, (
            f"interact names {product_spelling!r}: the kernel derives no container name of its own "
            f"(si#312). The prefix is passed by the caller that resolved it.")

    # assert: and no module-level string constant is left to grow back into one
    constants = {name: value for name, value in vars(interact).items()
                 if isinstance(value, str) and not name.startswith("__")}
    assert constants == {}, f"interact carries string constants again: {sorted(constants)}"
