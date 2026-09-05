"""Tests over the release workflow itself (#2, task 4) - .github/workflows/release.yml.

WHY A TEST OVER A CI FILE, twice over.

FIRST, the acceptance this task had to meet is an ABSENCE: a release that changes no documentation must
still rebuild and republish the site, which means the workflow must carry no `paths:` filter and no
changed-files condition. An absence is the one thing a reviewer cannot see. Worse, adding one later would
look like an optimisation, would pass every run that happens to touch the docs, and would be found out by
the first release that does not - months later, by somebody who was not here.

SECOND, and it is the decision the whole job rests on: the site is BUILT by the same command in CI as by
hand. Deploying is the workflow's - `upload-pages-artifact` and `deploy-pages` talk to services that
exist only inside an Actions run - but building must not be. A workflow that called hugo itself, or that
reproduced the reference-then-site order as two `run:` lines, would be a second route to the same end,
and the one nobody runs by hand is the one that silently goes wrong. So this asserts that the job runs
exactly one build command AND that the command it runs is a real command in this repository's manifest
whose plan is the reference and then the site. That is the join: it fails if the workflow invents a step,
and it fails if the manifest stops planning what the workflow assumes.

WHAT IS DELIBERATELY NOT TESTED: that a tag actually deploys. That takes a real Actions run against a
repository whose Pages source is set, and nothing here can stand in for it. What can be held is
everything that would make such a run do the wrong thing quietly.
"""
import tomllib

import pytest
import yaml

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod

from conftest import ROOT

WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
MANIFEST = ROOT / "simplon.yaml"
PYPROJECT = ROOT / "pyproject.toml"

#: The job that publishes the website, the one command it is allowed to run, and what that command must
#: plan. Spelled out rather than derived from the files under test - a test that read the command out of
#: the workflow and the plan out of the manifest, and then asserted each file says what it says, would
#: hold nothing.
DOCS_JOB = "docs"
THE_ONE_COMMAND = "./simplon.sh build docs"
EXPECTED_PLAN = ("reference", "site")

#: Actions whose whole purpose is to answer "which files changed". Any of them in this workflow would be
#: the `paths:` filter wearing a different hat.
CHANGED_FILES_ACTIONS = ("dorny/paths-filter", "tj-actions/changed-files", "technote-space/get-diff-action")

#: What the workflow may reach for to make the site. Anything else here - a hugo call, a docker run, a
#: script beside the manifest - would be the second route this job exists to not have.
FORBIDDEN_IN_RUNS = ("hugo", "docker run", "build site", "build reference")


@pytest.fixture(scope="module")
def workflow():
    """The release workflow, parsed. `on:` is read back as the boolean True, because YAML 1.1 says so."""
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def docs_job(workflow):
    return workflow["jobs"][DOCS_JOB]


@pytest.fixture(scope="module")
def product():
    """This repository's own manifest, loaded the way the CLI loads it."""
    return manifest_mod.load(MANIFEST.read_text(encoding="utf-8"), catalogue=catalogue_mod.load())


def _walk(node):
    """Every (key, value) pair anywhere in the parsed document - the only way to assert that something is
    absent EVERYWHERE rather than absent from the one place a test remembered to look."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _runs(node):
    return [str(value) for key, value in _walk(node) if key == "run"]


# --- the trigger, and the acceptance that hangs off it ---------------------------------------------------


def test_the_release_is_triggered_by_a_tag_and_by_nothing_else(workflow):
    """The publication hangs on the tag, which is what makes the published site describe a version that
    exists on PyPI. A push trigger as well would put `main` on the page between releases."""
    # Arrange / Act
    trigger = workflow[True]                      # `on:` - YAML 1.1 reads the bare word as a boolean

    # Assert
    assert set(trigger) == {"push"}
    assert trigger["push"] == {"tags": ["v*"]}


def test_a_release_that_changes_no_documentation_still_rebuilds_the_site(workflow):
    """THE uncomfortable acceptance, checked rather than assumed.

    A `paths:` or `paths-ignore:` anywhere in this file would tie the publication to a changed file
    instead of to the tag. It would work for every release that happens to touch the documentation and
    fail silently for the first one that does not - leaving the previous release's site up while the
    project page links to it as the new version's.
    """
    # Arrange / Act
    keys = [key for key, _ in _walk(workflow)]

    # Assert
    assert "paths" not in keys
    assert "paths-ignore" not in keys


def test_nothing_in_the_workflow_asks_which_files_changed(workflow):
    """The same requirement from the other side: a changed-files ACTION would reintroduce the filter
    without using the word, and a conditional step is how it would be spent."""
    # Arrange / Act
    uses = [str(value) for key, value in _walk(workflow) if key == "uses"]

    # Assert
    assert not [u for u in uses if any(u.startswith(bad) for bad in CHANGED_FILES_ACTIONS)]


def test_the_documentation_job_runs_unconditionally(docs_job):
    """No `if:` on the job and none on any of its steps. `needs:` is a different thing - it orders the
    job after the upload, it does not decide whether it happens."""
    # Arrange / Act
    conditions = [key for key, _ in _walk(docs_job) if key == "if"]

    # Assert
    assert conditions == []
    assert "if" not in docs_job


# --- one command, and the same one a human types ---------------------------------------------------------


def test_the_documentation_job_runs_exactly_one_build_command(docs_job):
    """One `run:`, and it is the command a developer types in a checkout."""
    # Arrange / Act
    commands = [run.strip() for run in _runs(docs_job)]

    # Assert
    assert commands == [THE_ONE_COMMAND]


def test_the_workflow_builds_the_site_no_other_way(workflow):
    """No hugo, no docker run, and neither of the two steps `build docs` already plans.

    This is the agile-cockpit defect stated as a check: a pipeline that read a list and called
    `python -m tests.<name>` while a human called the launcher had two routes to one end, and they drifted.
    A release job that ran `build reference` and `build site` itself would be that shape exactly - the
    order would then live in two places, and the manifest's edge would stop being the truth.
    """
    # Arrange / Act
    runs = " ".join(_runs(workflow))

    # Assert
    assert not [bad for bad in FORBIDDEN_IN_RUNS if bad in runs]


def test_the_command_the_workflow_runs_is_a_real_command_that_plans_the_whole_build(docs_job, product):
    """THE join between the two files: the workflow's command resolves in the manifest, and its plan is
    the reference and then the site.

    Read off the workflow rather than assumed, so it fails if either side moves: a workflow that called
    `build site` would be caught here even though `build site` exists, because its plan is one step and
    the site would carry the previous run's reference.
    """
    # Arrange
    command = _runs(docs_job)[0].strip()

    # Act
    _, group, name = command.split()

    # Assert
    assert (group, name) in [(g, n) for g, members in product.commands.items() for n in members]
    assert product.plan_for(name, group=group) == EXPECTED_PLAN


def test_the_site_goes_up_only_after_the_wheel_did(workflow, docs_job):
    """Why the trigger is a tag at all: the page describes the version it was cut from, so it must not
    appear before that version can be installed."""
    # Arrange / Act / Assert
    assert docs_job["needs"] == "publish"
    assert "publish" in workflow["jobs"]


def test_the_deployment_is_the_workflows_and_carries_the_rights(docs_job):
    """The line the owner drew: building is simplon's, deploying is CI/CD's.

    Both actions below talk to services that exist only inside an Actions run, which is why they are here
    rather than in a task - and the two permissions they need are scoped to this job rather than granted
    to the whole workflow.
    """
    # Arrange
    uses = [str(value) for key, value in _walk(docs_job) if key == "uses"]

    # Act
    permissions = docs_job["permissions"]

    # Assert
    assert any(u.startswith("actions/upload-pages-artifact") for u in uses)
    assert any(u.startswith("actions/deploy-pages") for u in uses)
    assert permissions["pages"] == "write"
    assert permissions["id-token"] == "write"
    assert docs_job["environment"]["name"] == "github-pages"


def test_the_artifact_is_taken_from_the_directory_the_manifest_builds_into(docs_job):
    """The upload reads the directory the manifest declares as the site's output. Two spellings of one
    path is the shape that rots quietly, so this is where they are held together."""
    # Arrange
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    upload = next(step for step in docs_job["steps"]
                  if str(step.get("uses", "")).startswith("actions/upload-pages-artifact"))

    # Act
    path = upload["with"]["path"]

    # Assert
    assert path == manifest["site"]["output"]


def test_no_step_gates_on_a_clean_working_tree(workflow):
    """`hugo mod get` WRITES site/go.mod and site/go.sum on every build - idempotent while the pin and
    the file agree, which is the committed state, but a real diff the first time the pin moves ahead.

    Pinning the dependency is what makes the build reproducible. Asserting afterwards that the build
    changed nothing would assert something else entirely - that somebody had run it locally first - and
    would go red on the mechanism working correctly. So there is no such gate, and this holds the absence
    the way the `paths:` test above does.
    """
    # Arrange / Act
    runs = " ".join(_runs(workflow))

    # Assert
    assert "diff --exit-code" not in runs
    assert "status --porcelain" not in runs


# --- the version the release publishes, and what still has to be checked about it (#3) --------------------
#
# The workflow used to carry a step titled "The tag must name the version being published", which compared
# `${GITHUB_REF_NAME#v}` with `project.version` out of pyproject.toml. With setuptools-scm that comparison
# is a tautology - the version IS derived from the tag - and pyproject.toml no longer holds a number for it
# to read. So the step is gone.
#
# It does NOT follow that nothing needs checking. setuptools-scm has one precondition, and
# actions/checkout's default breaks it: a shallow clone (`fetch-depth: 1`) has the tag but not the history
# behind it, and setuptools-scm then derives a version that is merely wrong - it does not fail. That is
# strictly worse than the old failure mode, because the old one was loud. Two things below replace the
# step: the full history the derivation needs, and an assertion that what came out equals the tag, which
# now checks the MECHANISM (depth, dirty tree, a tag that is not where the build thinks it is) rather than
# what a human typed into a file.

PUBLISH_JOB = "publish"


@pytest.fixture(scope="module")
def publish_job(workflow):
    return workflow["jobs"][PUBLISH_JOB]


def test_no_step_compares_the_tag_to_a_version_in_a_file(workflow):
    """The absence the ticket asked for. A step reading `project.version` back out of pyproject.toml would
    mean somebody had put a static number there again - the three-places defect returning by the back
    door, and this time wearing a green check."""
    # Arrange / Act
    runs = " ".join(_runs(workflow))

    # Assert
    assert "pyproject.toml" not in runs, "the workflow is reading a version out of a file again (#3)"
    assert "tomllib" not in runs, "the workflow is reading a version out of a file again (#3)"


def test_the_publishing_checkout_fetches_the_whole_history(publish_job):
    """THE precondition, and the real replacement for the deleted step.

    actions/checkout defaults to depth 1. setuptools-scm on such a clone cannot see the tag's distance from
    anything and produces a wrong version SILENTLY - no error, a bad wheel, and PyPI accepts it. `0` is the
    setting that makes the derivation possible at all, so it is asserted rather than left to a default that
    is not ours.
    """
    # Arrange
    checkout = next(step for step in publish_job["steps"]
                    if str(step.get("uses", "")).startswith("actions/checkout"))

    # Act
    depth = checkout.get("with", {}).get("fetch-depth")

    # Assert
    assert depth == 0, "actions/checkout defaults to a shallow clone, which setuptools-scm cannot read (#3)"


def test_the_version_that_was_built_is_asserted_against_the_tag(publish_job):
    """Not tag-against-a-file (that number is gone) but tag-against-what-the-build-DERIVED. It catches the
    things that make the derivation go wrong quietly: a shallow clone, an unclean tree adding a local
    `+...` segment PyPI would reject, a tag that does not point where the build is standing.

    Read off the built artefact rather than recomputed, so it cannot pass by doing the same wrong thing
    twice.
    """
    # Arrange
    runs = " ".join(_runs(publish_job))

    # Assert
    assert "GITHUB_REF_NAME" in runs, "nothing in the publish job looks at the tag at all"
    assert "dist/" in runs, "the check must read the version off the built wheel, not recompute it"


def test_the_documentation_checkout_also_carries_the_history(docs_job):
    """UNIFORMITY, and it is worth saying that plainly rather than inventing a mechanism.

    No page carries the kernel's version - `simplon.__version__` has exactly one consumer, the pin in
    `bootstrap.render` - so this job would go green on a shallow clone. It would not be silent, though:
    the site build installs the kernel with `-e .`, so setuptools-scm runs, warns that the checkout is
    shallow and derives its no-tag sentinel.

    What is actually held here is that every checkout in this repository takes the same setting: one rule
    to state, one rule to assert, and no exception whose reasoning a later reader has to reconstruct.
    """
    # Arrange
    checkout = next(step for step in docs_job["steps"]
                    if str(step.get("uses", "")).startswith("actions/checkout"))

    # Act / Assert
    assert checkout.get("with", {}).get("fetch-depth") == 0


def test_the_project_page_links_the_documentation_website():
    """The address appears in two files that cannot read each other - pyproject.toml, where PyPI reads it,
    and simplon.yaml, where Hugo needs it to write absolute links. Neither is derivable from the other, so
    what holds them together is this."""
    # Arrange
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

    # Act
    linked = project["urls"]["Documentation"]

    # Assert
    assert linked == manifest["site"]["base_url"]
    assert linked.startswith("https://")
