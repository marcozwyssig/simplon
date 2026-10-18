"""simplon's own `release version` (final review of si#491, Important 1): the version is refused before
anything is cut unless it is spelled `vX.Y.Z`.

Measured by that review: on the button, `0.99.0` passed the local cut, the stamping check
(`git describe` = `0.99.0`), `test release-notes` (rc 0) and the si#3 wheel check (setuptools-scm reads an
unprefixed tag too) - so a public tag and a PyPI upload that can never be re-used would have gone out.
The tag-push route ignored such a tag (`tags: ["v*"]`); the dispatch route has nothing that does. This is
the product's guard until `release:check` (si#487) gives the kernel one, and it is a DIAGNOSIS: no
version simplon has ever released is spelled otherwise (`git tag` - every tag is vX.Y.Z).

AAA; the name states the behaviour under test.
"""
import sys

import pytest

from conftest import ROOT  # noqa: E402 - the one product-root anchor (si#283)

sys.path.insert(0, str(ROOT / "deploy" / "orchestrator" / "src" / "python"))
from orchestrator import cli  # noqa: E402 - the product's own module, only reachable from here
from simplon.manifest import catalogue as catalogue_mod  # noqa: E402
from simplon.manifest import load as manifest_mod  # noqa: E402


@pytest.mark.parametrize("version", ["v0.34.0", "v1.0.0", "v10.20.30"])
def test_a_version_spelled_like_every_release_so_far_is_accepted(version):
    assert cli.release_version(tag=version) == 0


@pytest.mark.parametrize("version", ["0.99.0", "v0.99", "v0.99.0-rc1", "V0.99.0", "v0.99.0 ", "-v0.99.0", ""])
def test_any_other_spelling_is_refused_and_named(version, capsys):
    # act
    rc = cli.release_version(tag=version)

    # assert
    assert rc == 1
    err = capsys.readouterr().err
    assert repr(version) in err and "vX.Y.Z" in err


def test_every_tag_this_repository_carries_is_one_the_guard_accepts():
    """The population: a guard that would have refused a real release is an expression rule, not a
    diagnosis. Over every tag there is, not a sample."""
    import subprocess
    tags = subprocess.run(["git", "-C", str(ROOT), "tag", "--list"], capture_output=True, text=True,
                          check=True).stdout.split()

    assert tags, "no tags to measure against"
    assert [t for t in tags if cli.release_version(tag=t) != 0] == []


def test_the_release_checks_the_version_before_anything_else():
    # arrange
    product = manifest_mod.load((ROOT / "simplon.yaml").read_text(encoding="utf-8"),
                                catalogue=catalogue_mod.load())

    # act
    plan = product.plan_for("all", group="release")

    # assert
    assert plan[0] == "version"
