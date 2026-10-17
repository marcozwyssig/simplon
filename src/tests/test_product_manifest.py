"""Tests for THIS repository's own manifest - simplon.yaml - and specifically for the documentation
website it declares (#2, task 3).

WHY A TEST OVER A PRODUCT MANIFEST AT ALL, when every other test here covers the kernel. Because the two
things task 3 had to get right are both DATA, and data in a YAML file has no type checker over it. The
`site:` section is read by a kernel task that would otherwise discover a typo as a container run against
a directory that is not there, and the reference-before-site ordering is a `depends_on` edge whose whole
purpose is to be checkable - a script beside the manifest could not be checked at all, which is the
argument for putting the edge in the manifest in the first place.

WHAT IS DELIBERATELY NOT TESTED: the prose. Whether the rules chapter states its case well is not a
property a test can hold, and asserting on the words would only pin them against editing. What can be
held is that the generated page lands where Hugo reads it, that it is written before Hugo runs, and that
neither the page nor the built site is committed.

The manifest is loaded through the real loader with the real catalogue - the same path the CLI takes -
so a section this file asserts on is a section the running product actually has. AAA throughout.
"""
from simplon.model.command import AggregateCommand
import shutil
import subprocess

import pytest

from simplon.manifest import catalogue as catalogue_mod
from simplon.manifest import load as manifest_mod
from simplon.manifest import outputs
from simplon.tasks import site as site_task

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"

#: The aggregate that ties the documentation commands together, and the order it must plan them in.
#: Spelled out rather than derived from the manifest, because a test that read the order out of the
#: manifest and then asserted the manifest declares it would hold nothing.
#:
#: THREE SINCE si#204: `acceptance` writes a second page into the content tree, so it is a second WRITER
#: that has to run before the reader. The two writers do not depend on each other and their relative
#: order carries no meaning; what this tuple holds is that `site` is last.
DOCS_AGGREGATE = "docs"
EXPECTED_PLAN = ("reference", "acceptance", "site")


@pytest.fixture(scope="module")
def product():
    """This repository's own manifest, loaded the way the CLI loads it."""
    return manifest_mod.load(MANIFEST.read_text(encoding="utf-8"),
                             catalogue=catalogue_mod.load())


def test_the_site_section_is_declared_and_valid(product):
    """The `site:` section parses through the very validator `docs:site` runs it through."""
    # Arrange: the raw manifest data, as simplon.manifest.context.manifest_data would hand it to the task.
    import yaml
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

    # Act
    declared = site_task.declared(data, source=str(MANIFEST))

    # Assert: the four values Hugo actually needs, plus the theme the page's whole look hangs on.
    #
    # `source` is declared by the manifest since si#344 B1 (it was the kernel's default before);
    # `test_simplon_names_its_own_site_source_and_the_default_is_unchanged` pins the declaration itself.
    assert declared.source == "src/site"
    # `output` is left out of the manifest on purpose, since si#314: a built site is a KIND of
    # build output, so the section must not carry the key at all and the value must still resolve - here
    # to `build/site`, because this manifest declares no `output:` either and takes the convention. The
    # kernel is the first consumer of both defaults rather than a product that happens to agree.
    assert "output" not in data["website"], (
        "simplon declares `site: output:` again; si#314 leaves it out on purpose, so that the kernel's "
        "own `<output>/site` is exercised by the one product this suite can actually build")
    assert declared.output == f"{outputs.DEFAULT}/{site_task.OUTPUT_KIND}" == "build/site"
    assert declared.image and declared.theme
    assert declared.base_url.startswith("https://")


def test_simplon_names_its_own_site_source_and_the_default_is_unchanged():
    # arrange: simplon's site moved under src/ (si#344 B1) so firn can write into it. The DEFAULT stays
    # `docs/site`, because it is every product's (si#183); simplon now names its path instead.
    from simplon.tasks import site
    import yaml
    data = yaml.safe_load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))

    # act
    declared = data["website"].get("source")

    # assert
    assert declared == "src/site"
    assert site.DEFAULT_SOURCE == "docs/site"
    assert (ROOT / declared / "hugo.yaml").is_file()


def test_the_image_and_the_theme_are_pinned(product):
    """Both moving-target refusals apply to the values THIS manifest actually declares.

    `declared()` enforces the rule; this asserts the manifest passes it for a reason a reader can see -
    a tag and a version that name one revision, not a query that resolves differently tomorrow.
    """
    # Arrange / Act
    import yaml
    declared = site_task.declared(yaml.safe_load(MANIFEST.read_text(encoding="utf-8")))

    # Assert
    assert ":" in declared.image and not declared.image.endswith(":latest")
    module, _, version = declared.theme.partition("@")
    assert module and version and version not in ("latest", "upgrade", "master", "main")


def test_the_reference_is_written_where_hugo_reads_it(product):
    """The generated page lands inside the Hugo project's content tree.

    This is the join between the two commands, and it is a join by PATH: `docs:reference` writes a file
    and `docs:site` renders a directory, and nothing connects them except that the first path is under
    the second. Hugo renders only what lives under its content directory, so a page written anywhere
    else is a page that silently does not appear.
    """
    # Arrange
    import yaml
    declared = site_task.declared(yaml.safe_load(MANIFEST.read_text(encoding="utf-8")))

    # Act
    pinned = product.commands["build"]["reference"].with_

    # Assert
    assert str(pinned["output"]).startswith(f"{declared.source}/content/")
    assert (ROOT / declared.source / "content").is_dir()


def test_the_reference_output_is_pinned_off_the_command_line(product):
    """`output` is pinned with `with:`, not left as an argument.

    It has to be: a planned step is spawned with no arguments, so an aggregate could not supply one.
    A `reference` that still took a positional path would fail as a step while working by hand.
    """
    # Arrange / Act
    spec = product.commands["build"]["reference"]

    # Assert
    assert "output" in spec.with_


def test_the_reference_is_planned_before_the_site(product):
    """THE ordering guarantee, as a manifest edge rather than a convention.

    `plan_for` is what the runner executes, so asserting on it asserts on the run. The first page is
    WRITTEN by `reference` and READ by `site`; planned the other way round, a build publishes the
    previous run's reference, and the very first one publishes none.
    """
    # Arrange / Act
    plan = product.plan_for(DOCS_AGGREGATE, group="build")

    # Assert
    assert plan == EXPECTED_PLAN


def test_the_docs_aggregate_carries_no_body_of_its_own(product):
    """It is an aggregate, which is what makes the edge above expressible at all.

    `impl` and `depends_on` are mutually exclusive, so neither leaf could have carried the dependency:
    the ordering needed a third command with no body. A future edit that gave `docs` an `impl:` would
    still load, still run, and quietly stop planning anything.
    """
    # Arrange / Act
    spec = product.commands["build"][DOCS_AGGREGATE]

    # Assert
    assert isinstance(spec, AggregateCommand)   # runs no body of its own (si#400 4d)
    assert spec.depends_on == EXPECTED_PLAN


def test_both_documentation_commands_are_real_commands(product):
    """The two leaves exist under the names the aggregate plans, and each resolves to a kernel task."""
    # Arrange / Act
    members = product.commands["build"]

    # Assert
    # since si#400 4c a coordinate's impl names its generated class
    assert members["reference"].impl == "simplon.tasks.docs_reference:DocsReference"
    assert members["site"].impl == "simplon.tasks.docs_site:DocsSite"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_the_generated_half_of_the_site_is_not_committed(product):
    """Neither the built site nor the generated reference page enters the repository.

    Asserted through git's own ignore rules rather than by reading .gitignore, because what matters is
    the VERDICT - a rule that is present but shadowed by a later negation would read fine and ignore
    nothing. The reference page is the interesting one: it is an output that sits among sources, since
    Hugo renders only what is under content/, so no directory rule covers it.
    """
    # Arrange
    import yaml
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    declared = site_task.declared(data)
    paths = [f"{declared.output}/index.html", str(product.commands["build"]["reference"].with_["output"])]

    # Act
    verdicts = [subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode
                for path in paths]

    # Assert: 0 means "ignored"; 1 means "not ignored"; 128 means this is not a work tree.
    if 128 in verdicts:
        pytest.skip("not a git work tree")
    assert verdicts == [0, 0], f"not ignored: {[p for p, rc in zip(paths, verdicts) if rc != 0]}"


def test_release_all_hands_the_tag_to_every_member_that_takes_one(product):
    # arrange: each leaf of `release all` runs as its own subprocess (si#433). A member that got no tag
    # would not stop: `push-image` falls back to `git describe` and, before the tag exists, publishes
    # under `v0.31.0-N-g<sha>` with rc 0
    from simplon import cli

    spec = product.spec_for("release", "all")
    takers = cli.receivers(product, "release", "all", spec)

    # act
    handed = cli.leaf_arguments(takers, {"tag": "v9.9.9"})

    # assert: in each leaf's own form - `release tag`'s tag is required, so it is a positional
    assert handed == {"notes": ("--tag=v9.9.9",), "push-image": ("--tag=v9.9.9",),
                      "tag": ("--", "v9.9.9")}
