"""The host path of a bind mount, asked from inside a container that runs containers (si#201).

WHAT THESE TESTS STAND ON, measured on 2026-09-12 before a line of `simplon.hostpath` was written, with
a kernel container holding the docker socket and the tree at /src:

  * `docker run -v /src:/x busybox ls -la /x` inside that container printed an EMPTY directory, rc 0,
    and left a root-owned `/src` behind on the HOST. The daemon resolved `/src` against the host, did
    not find it, and created it. No error anywhere - which is this repository's own hunted defect: a
    step that cannot fail, and a gate that would then run against nothing and report green.
  * the same run with the real host path printed the tree.

So the translation is not a nicety, and the case that has no answer must refuse rather than mount.
"""

import pytest

from simplon import context
from simplon import hostpath


def _boom(msg="boom", *a, **k):
    raise RuntimeError(msg)


def _here(tmp_path, monkeypatch=None, *, contained=False):
    """Register a product context rooted at `tmp_path`, and say what the process is TOLD about itself.

    `contained` is pinned rather than sampled because this suite runs on both routes: inside the kernel
    container the marker file really is there, and a test of the venv branch that read it would be red on
    one route and green on the other - which is the very difference si#201 exists to remove.
    """
    if monkeypatch is not None:
        monkeypatch.setattr(hostpath, "in_a_container", lambda: contained)
    return context.set_current(context.ProductContext("democtl", tmp_path, tmp_path / "democtl.yaml"))


def _mounted(monkeypatch, host, mount="/src"):
    """Declare the bind mount the way the launcher's container route does: both sides, named."""
    monkeypatch.setenv(hostpath.HOST_ROOT_ENV, host)
    monkeypatch.setenv(hostpath.MOUNT_ROOT_ENV, mount)


# --- the venv route: nothing changes -------------------------------------------------------------------


def test_without_a_declared_host_root_a_path_is_handed_back_unchanged(tmp_path, monkeypatch):
    # arrange: the venv route, which is every run this kernel has ever made. The argv it builds must
    # come out byte-identical, or the two routes differ before either of them has run anything
    monkeypatch.delenv(hostpath.HOST_ROOT_ENV, raising=False)
    monkeypatch.delenv(hostpath.MOUNT_ROOT_ENV, raising=False)
    _here(tmp_path, monkeypatch, contained=False)

    # act / assert
    assert hostpath.translate(tmp_path / "build" / "logs") == str(tmp_path / "build" / "logs")


def test_a_path_outside_the_product_root_is_also_unchanged_on_the_venv_route(tmp_path, monkeypatch):
    # arrange: a temp directory is a perfectly good mount source when the daemon and this process share
    # a filesystem, and the venv route must keep saying so
    monkeypatch.delenv(hostpath.HOST_ROOT_ENV, raising=False)
    monkeypatch.delenv(hostpath.MOUNT_ROOT_ENV, raising=False)
    _here(tmp_path, monkeypatch, contained=False)

    # act / assert
    assert hostpath.translate("/tmp/simplon-scratch") == "/tmp/simplon-scratch"


# --- the container route: the prefix moves --------------------------------------------------------------


def test_a_path_under_the_mount_is_rewritten_onto_the_host_root(tmp_path, monkeypatch):
    # arrange
    _mounted(monkeypatch, "/home/marco/simplon")
    _here(tmp_path)

    # act
    translated = hostpath.translate("/src/build/website")

    # assert
    assert translated == "/home/marco/simplon/build/website"


def test_the_mount_root_itself_translates_to_the_host_root(tmp_path, monkeypatch):
    # arrange: `-v {root}:/work` is the commonest of the seven mount sites, so the identity case is the
    # one that must not come out as '/home/marco/simplon/.'
    _mounted(monkeypatch, "/home/marco/simplon")
    _here(tmp_path)

    # act / assert
    assert hostpath.translate("/src") == "/home/marco/simplon"


def test_a_string_path_is_accepted_because_two_call_sites_build_one(tmp_path, monkeypatch):
    # arrange: `tasks/allure.py` joins with os.path and never holds a Path
    _mounted(monkeypatch, "/home/marco/simplon")
    _here(tmp_path)

    # act / assert
    assert hostpath.translate("/src/build/allure") == "/home/marco/simplon/build/allure"


# --- the two refusals ------------------------------------------------------------------------------------


def test_a_path_that_only_looks_like_a_prefix_is_not_inside_the_mount(tmp_path, monkeypatch):
    # arrange: `/srcfoo` shares five characters with `/src` and none of its components. A string prefix
    # test would have handed the daemon `<host>foo`
    _mounted(monkeypatch, "/home/marco/simplon")
    monkeypatch.setattr(hostpath.log, "die", _boom)
    _here(tmp_path)

    # act / assert
    with pytest.raises(RuntimeError):
        hostpath.translate("/srcfoo/build")


def test_a_path_that_climbs_out_of_the_mount_is_refused_rather_than_carried_over(tmp_path, monkeypatch):
    # arrange: `..` is not folded away by `relative_to`, so before si#201 normalised the input this came
    # through as `<host>/a/../../etc` - a source the daemon resolves OUTSIDE the mount
    _mounted(monkeypatch, "/home/marco/simplon")
    monkeypatch.setattr(hostpath.log, "die", _boom)
    _here(tmp_path)

    # act / assert
    with pytest.raises(RuntimeError):
        hostpath.translate("/src/a/../../etc")


def test_a_path_that_climbs_and_comes_back_is_the_path_it_normalises_to(tmp_path, monkeypatch):
    # arrange: the Gegenprobe, so the refusal above is about leaving the mount rather than about the
    # characters `..`
    _mounted(monkeypatch, "/home/marco/simplon")
    _here(tmp_path)

    # act / assert
    assert hostpath.translate("/src/build/../build/logs") == "/home/marco/simplon/build/logs"


def test_a_path_outside_the_mount_is_refused_rather_than_mounted(tmp_path, monkeypatch):
    # arrange: the measured trap. `/tmp/simplon-mermaid-xyz` exists in the container and nowhere else,
    # so the daemon would create an empty directory of that name on the host and mount it
    _mounted(monkeypatch, "/home/marco/simplon")
    monkeypatch.setattr(hostpath.log, "die", _boom)
    _here(tmp_path)

    # act / assert
    with pytest.raises(RuntimeError) as refusal:
        hostpath.translate("/tmp/simplon-mermaid-xyz")
    said = str(refusal.value)
    assert "/tmp/simplon-mermaid-xyz" in said
    assert "/src" in said and "/home/marco/simplon" in said


def test_a_windows_drive_path_is_refused_as_the_undriven_route_it_is(tmp_path, monkeypatch):
    # arrange: `<product>.cmd` sets the host root from `%~dp0`, so on Windows it is `C:\...`. The kernel
    # reading it is in a LINUX container, and nothing there joins a drive path onto a POSIX one. Found on
    # review, and the point of the test is the WORDING: without it the check one line down blamed a named
    # volume, which is a true sentence about the wrong problem
    _mounted(monkeypatch, "C:\\Users\\marco\\proj")
    monkeypatch.setattr(hostpath.log, "die", _boom)
    _here(tmp_path)

    # act / assert
    with pytest.raises(RuntimeError) as refusal:
        hostpath.translate("/src/build")
    said = str(refusal.value)
    assert "Windows drive path" in said
    assert "DELIVERY_ROUTE=venv" in said


def test_a_relative_host_root_is_refused_because_the_daemon_would_invent_one(tmp_path, monkeypatch):
    # arrange: docker reads a `-v` source with no leading slash as a NAMED VOLUME, so a relative value
    # here would silently mount an empty volume instead of the tree
    _mounted(monkeypatch, "simplon")
    monkeypatch.setattr(hostpath.log, "die", _boom)
    _here(tmp_path)

    # act / assert
    with pytest.raises(RuntimeError) as refusal:
        hostpath.translate("/src")
    assert hostpath.HOST_ROOT_ENV in str(refusal.value)


def test_a_container_that_was_told_nothing_refuses_instead_of_mounting_its_own_path(tmp_path, monkeypatch):
    # arrange: `docker run <image> ...` typed by hand, with no launcher to set the variable. The kernel
    # cannot know the host path and must not guess - the measured consequence of guessing is an empty
    # root-owned directory on the host and a green gate over nothing
    monkeypatch.delenv(hostpath.HOST_ROOT_ENV, raising=False)
    monkeypatch.delenv(hostpath.MOUNT_ROOT_ENV, raising=False)
    monkeypatch.setattr(hostpath.log, "die", _boom)
    _here(tmp_path, monkeypatch, contained=True)

    # act / assert
    with pytest.raises(RuntimeError) as refusal:
        hostpath.translate(tmp_path)
    assert hostpath.HOST_ROOT_ENV in str(refusal.value)


def test_half_a_mapping_is_refused_because_the_other_half_cannot_be_guessed(tmp_path, monkeypatch):
    # arrange: the measured reason the pair is a pair. Inferring the container side from the product
    # root mapped a scaffolded fixture INSIDE the mount onto the host root, and a sibling container was
    # handed the wrong tree with a cmake error to show for it
    monkeypatch.setenv(hostpath.HOST_ROOT_ENV, "/home/marco/simplon")
    monkeypatch.delenv(hostpath.MOUNT_ROOT_ENV, raising=False)
    monkeypatch.setattr(hostpath.log, "die", _boom)
    _here(tmp_path)

    # act / assert
    with pytest.raises(RuntimeError) as refusal:
        hostpath.translate("/src")
    assert hostpath.MOUNT_ROOT_ENV in str(refusal.value)


def test_a_subdirectory_of_the_mount_is_not_flattened_onto_the_host_root(tmp_path, monkeypatch):
    # arrange: the Gegenprobe for that same defect - a product scaffolded into a subdirectory of the
    # mount, which is what the kernel's own e2e tests do to a fixture
    _mounted(monkeypatch, "/home/marco/simplon")
    context.set_current(context.ProductContext("gatedemo", type(tmp_path)("/src/build/pytest/demo0"),
                                               type(tmp_path)("/src/build/pytest/demo0/gatedemo.yaml")))

    # act / assert
    assert hostpath.translate("/src/build/pytest/demo0") == "/home/marco/simplon/build/pytest/demo0"


#: The real predicate, captured at import - conftest pins `in_a_container` to False for every test so the
#: suite says the same thing on both routes, and the one test that is ABOUT the predicate has to put the
#: real one back.
_REAL_IN_A_CONTAINER = hostpath.in_a_container


@pytest.mark.parametrize("present, expected", [("/.dockerenv", True),
                                               ("/run/.containerenv", True),
                                               ("/etc/hostname", False)])
def test_the_container_is_recognised_by_the_file_its_runtime_writes(monkeypatch, present, expected):
    # arrange: docker writes /.dockerenv (measured present in the kernel image), podman and the other
    # OCI runtimes write /run/.containerenv. A file that exists on every host must NOT count, or the
    # venv route would start taking the refusal branch
    monkeypatch.setattr(hostpath, "in_a_container", _REAL_IN_A_CONTAINER)
    monkeypatch.setattr(hostpath.os.path, "exists", lambda path: path == present)

    # act / assert
    assert hostpath.in_a_container() is expected
