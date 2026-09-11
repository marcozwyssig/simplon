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
import shutil
import subprocess

import pytest

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod
from simplon.tasks import site as site_task

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"

#: The aggregate that ties the two documentation commands together, and the order it must plan them in.
#: Spelled out rather than derived from the manifest, because a test that read the order out of the
#: manifest and then asserted the manifest declares it would hold nothing.
DOCS_AGGREGATE = "docs"
EXPECTED_PLAN = ("reference", "site")


@pytest.fixture(scope="module")
def product():
    """This repository's own manifest, loaded the way the CLI loads it."""
    return manifest_mod.load(MANIFEST.read_text(encoding="utf-8"),
                             catalogue=catalogue_mod.load())


def test_the_site_section_is_declared_and_valid(product):
    """The `site:` section parses through the very validator `docs:site` runs it through."""
    # Arrange: the raw manifest data, as simplon.context.manifest_data would hand it to the task.
    import yaml
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

    # Act
    declared = site_task.declared(data, source=str(MANIFEST))

    # Assert: the four values Hugo actually needs, plus the theme the page's whole look hangs on.
    #
    # `source` is asserted TWICE over, because since si#183 it is the kernel's answer rather than this
    # manifest's: the section must not carry the key at all, and the value must still be `docs/site`.
    # That makes this repository the first consumer of the default rather than a product that happens to
    # agree with it - so if the default ever stopped working, simplon's own `build docs` would say so.
    assert "source" not in data["site"], (
        "simplon declares `site: source:` again; si#183 leaves it out on purpose, so that the kernel's "
        "own default is exercised by the one product this suite can actually build")
    assert declared.source == "docs/site"
    assert declared.source == site_task.DEFAULT_SOURCE
    assert declared.output == "build/website"
    assert declared.image and declared.theme
    assert declared.base_url.startswith("https://")


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
    assert not spec.impl
    assert spec.depends_on == EXPECTED_PLAN


def test_both_documentation_commands_are_real_commands(product):
    """The two leaves exist under the names the aggregate plans, and each resolves to a kernel task."""
    # Arrange / Act
    members = product.commands["build"]

    # Assert
    assert members["reference"].impl == "simplon.tasks.cliref:reference"
    assert members["site"].impl == "simplon.tasks.site:build"


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
