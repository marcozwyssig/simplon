"""Unit tests for simplon.outputs (si#314): the ONE directory a product's build writes into.

A VALUE, NOT A RULE. `output:` sets where the kernel's producing coordinates write by default; a
coordinate that names its own destination still gets exactly what it named. That is the decision the
ticket landed on after the measurement over all eight reachable manifests, which found two destinations
outside `build/` and one of them in THIS repository's own manifest - the two documentation pages that
are written into the source tree because hugo reads its content from there. A rule refusing those would
have refused the kernel first, and a rule that exempts the kernel is the one si#53 struck.
"""
import pytest

from simplon import context, outputs
from simplon.context import ProductContext
from simplon.tasks import profiles


def _register(monkeypatch, tmp_path, data=None):
    ctx = ProductContext("sample", tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data", lambda self: dict(data or {}))
    return ctx


def test_the_default_root_is_build(monkeypatch, tmp_path):
    # arrange: a manifest that says nothing about output
    _register(monkeypatch, tmp_path, {})

    # act / assert: the convention gradle, maven, cargo and this repository's own manifest already use
    assert outputs.root() == tmp_path / "build"


def test_a_declared_root_wins(monkeypatch, tmp_path):
    # arrange: cleon's real case - it keeps `build/` for what it FETCHES and publishes out of another
    # root, which is why this is a default and not a rule
    _register(monkeypatch, tmp_path, {"output": "build-out"})

    # act / assert
    assert outputs.root() == tmp_path / "build-out"


def test_an_absolute_root_is_refused(monkeypatch, tmp_path):
    # arrange: `root / value` COLLAPSES onto an absolute value, and the result is handed to a clean
    _register(monkeypatch, tmp_path, {"output": "/var/tmp/x"})

    # act / assert
    with pytest.raises(ValueError) as excinfo:
        outputs.root()
    assert "output" in str(excinfo.value)


def test_a_root_escaping_the_product_is_refused(monkeypatch, tmp_path):
    # arrange / act / assert: `..` reaches just as far as an absolute path does
    _register(monkeypatch, tmp_path, {"output": "../elsewhere"})
    with pytest.raises(ValueError):
        outputs.root()


def test_a_root_that_is_not_a_string_is_refused(monkeypatch, tmp_path):
    # arrange / act / assert: `output: 3` is a broken declaration, not an omission
    _register(monkeypatch, tmp_path, {"output": 3})
    with pytest.raises(ValueError) as excinfo:
        outputs.root()
    assert "output" in str(excinfo.value)


def test_every_kind_resolves_under_the_root(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path, {"output": "build-out"})

    # act / assert: the kinds are what the producing coordinates already are
    for kind in outputs.KINDS:
        assert outputs.for_kind(kind) == tmp_path / "build-out" / kind


def test_the_kinds_are_the_ones_the_ticket_decided():
    # arrange / act / assert: `site` is its own kind beside `docs` - a built website is not a document -
    # and `logs` is its own beside both, because a run protocol is not an artefact (si#314)
    assert set(outputs.KINDS) == {"cpp", "dotnet", "java", "python", "docker", "docs", "logs", "site"}


def test_every_language_profile_has_a_kind():
    """The four language kinds are the kernel's own toolchain profiles, and this is what keeps the two
    lists from drifting: a fifth profile without a kind would leave that language's artefacts with
    nowhere named to land, which is the defect si#314 exists against, reintroduced one language at a
    time."""
    # arrange / act: the languages the kernel ships a toolchain for
    languages = set(profiles.PROFILES)

    # assert
    assert languages <= set(outputs.KINDS), (
        f"a toolchain profile has no output kind: {sorted(languages - set(outputs.KINDS))}")


def test_an_unknown_kind_is_refused_and_the_message_lists_the_kinds(monkeypatch, tmp_path):
    # arrange: a typo in a kernel task body would otherwise write into `build/dokcer/` and report success
    _register(monkeypatch, tmp_path, {})

    # act / assert
    with pytest.raises(ValueError) as excinfo:
        outputs.for_kind("dokcer")
    assert "dokcer" in str(excinfo.value) and "docker" in str(excinfo.value)


# --- the home a container gets (si#319) ----------------------------------------------------------------

def test_the_container_home_is_a_directory_under_the_output_root(monkeypatch, tmp_path):
    """si#319: a container started as the CALLING uid owns the bind mount and nothing else, so it has no
    writable HOME at all. Every tool that wants one was pointed into the product's tree by hand - gradle
    by a consumer's image, dotnet by `tasks/nuget.py` since si#102 - and the tree then carries whatever
    ownership an earlier root run left. The kernel names one place instead."""
    # arrange
    _register(monkeypatch, tmp_path, {})

    # act
    home = outputs.ensure_home()

    # assert: created, under the output root, and owned by whoever ran this
    assert home == tmp_path / "build" / "home"
    assert home.is_dir()


def test_the_container_home_follows_a_declared_output_root(monkeypatch, tmp_path):
    # arrange / act
    _register(monkeypatch, tmp_path, {"output": "build-out"})

    # assert
    assert outputs.ensure_home() == tmp_path / "build-out" / "home"


def test_the_home_is_expressed_in_container_coordinates(monkeypatch, tmp_path):
    """The path the kernel puts in `HOME=` is the one INSIDE the container, which is the mount point plus
    the output directory - not the host path, which does not exist there."""
    # arrange
    _register(monkeypatch, tmp_path, {"output": "build-out"})

    # act / assert
    assert outputs.home_in_container("/work") == "/work/build-out/home"
    assert outputs.home_in_container("/src/") == "/src/build-out/home"
