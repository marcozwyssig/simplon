"""The version has ONE source, and it is the git tag (#3).

WHY THIS FILE EXISTS. The number used to be typed into three files - `pyproject.toml`, the `__version__`
literal in `src/simplon/__init__.py`, and the `simplon==` pin in `bootstrap.py` - while the git tag was a
fourth spelling that nothing local paired with any of them. A test chained the pin to `__version__` and
another chained `pyproject.toml` to it, so a divergence was caught, but only AFTER it had been written.
The tag was never checked at all until a release workflow compared it to a file.

That shape cost three collisions with concurrent sessions in a single day (0.1.4, 0.1.8, 0.1.9), and the
third one is the reason this is mechanism and not a checklist: the number a stranger had already reserved
for themselves was in no tag and in no commit on `main` at the moment we looked for it. It was in a branch
we could not see. No amount of looking first would have found it.

WHAT THESE TESTS HOLD, then, is an ABSENCE and a wiring. The absence - no static version anywhere in the
tree - is the thing a reviewer cannot see and the thing that would quietly come back the first time
somebody "fixes" a build by pasting a number into `pyproject.toml`. The wiring is the four settings that
make setuptools-scm produce a version a human never types.

WHAT IS DELIBERATELY NOT TESTED HERE: that a build actually derives the tag. That needs a real build, and
tests/test_wheel.py does it - it builds the wheel, installs it into a throwaway venv, and asks the
installed package what version it is.
"""
import re
import subprocess
import tomllib

import pytest
import yaml

import simplon
from conftest import ROOT

PYPROJECT = ROOT / "pyproject.toml"
GITIGNORE = ROOT / ".gitignore"
WORKFLOWS = ROOT / ".github" / "workflows"

#: Where setuptools-scm writes the version at build time. Inside the package, because it has to ship in
#: the wheel; gitignored, because it is a build output.
VERSION_FILE = "src/simplon/_version.py"

#: PEP 440, restricted to the two shapes this project's scheme can produce: a final release from a tag,
#: or `<release>.postN.devM[+local]` from a commit after one.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.post\d+\.dev\d+)?(?:\+[A-Za-z0-9.]+)?$")


@pytest.fixture(scope="module")
def pyproject():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


# --- the absence: nothing in the tree states a version -----------------------------------------------------


def test_pyproject_declares_no_static_version(pyproject):
    """THE absence. `project.version` and `dynamic = ["version"]` are mutually exclusive by PEP 621, so a
    static number here is not merely a second spelling - it is a build error waiting for whoever adds it.
    Stated as a test anyway, because the failure mode being guarded is somebody deleting `dynamic` too."""
    # Arrange / Act
    project = pyproject["project"]

    # Assert
    assert "version" not in project, (
        "pyproject.toml states a version again; the tag is the source (#3), see [tool.setuptools_scm]")
    assert project["dynamic"] == ["version"]


def test_the_package_source_carries_no_version_literal():
    """`__version__` must be DERIVED - from the build-time file or the installed metadata - and never
    assigned a release number in the source. The one literal allowed is the unmistakable non-release
    fallback for a tree that is neither built nor installed."""
    # Arrange
    source = (ROOT / "src" / "simplon" / "__init__.py").read_text(encoding="utf-8")

    # Act
    literals = re.findall(r'^\s*__version__ = "(.*)"', source, re.M)

    # Assert
    assert literals == ["0.0.0.dev0+unknown"], (
        f"a version literal is back in simplon/__init__.py: {literals}")


def test_the_generated_version_file_is_not_committed():
    """It is a build output that happens to land among the sources (the same shape as the generated command
    reference). Committed, it would be a fourth spelling of the number - and a stale one."""
    # Arrange / Act
    tracked = subprocess.run(["git", "ls-files", VERSION_FILE], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()

    # Assert
    assert tracked == "", f"{VERSION_FILE} is tracked by git; it is a build output (#3)"
    assert VERSION_FILE in GITIGNORE.read_text(encoding="utf-8")


# --- the wiring: what makes the tag the source -------------------------------------------------------------


def test_the_build_requires_setuptools_scm(pyproject):
    """Without it in `build-system.requires`, `dynamic = ["version"]` has nothing to fill it in and the
    build fails - which is the good failure, but only if the requirement is actually declared."""
    # Arrange / Act
    requires = pyproject["build-system"]["requires"]

    # Assert
    assert any(req.startswith("setuptools-scm") or req.startswith("setuptools_scm") for req in requires), requires


def test_the_version_scheme_keeps_the_last_RELEASE_readable(pyproject):
    """`no-guess-dev`, and not the default, because of the pin the scaffolder writes.

    The default `guess-next-dev` renders an untagged tree as `0.1.13.dev3+g1234abc` - a version that does
    not exist yet and may never, since the next tag could be 0.2.0. Nothing in that string points back to
    something installable. `no-guess-dev` renders it as `0.1.12.post1.dev3+g1234abc`, which names the
    release the tree DESCENDS FROM, and `bootstrap.released_pin` reads that off the front.
    """
    # Arrange / Act
    scm = pyproject["tool"]["setuptools_scm"]

    # Assert
    assert scm["version_scheme"] == "no-guess-dev"
    assert scm["version_file"] == VERSION_FILE


def test_the_installed_version_is_a_version_this_scheme_can_produce():
    """The end of the chain, read from the package the tests import. Whatever the tree's state, the string
    is either a release or a `.postN.devM` descendant of one - never a hand-typed anything."""
    # Arrange / Act
    version = simplon.__version__

    # Assert
    assert VERSION_RE.match(version), (
        f"{version!r} is not a shape this project's version scheme produces; if it is "
        f"'0.0.0.dev0+unknown', simplon is neither built nor installed in this environment")


def test_the_version_names_a_tag_that_actually_EXISTS_in_this_repository():
    """THE join, and the point of the whole ticket: the version and the repository's tags are the same
    fact. Whatever this package reports, the release it names is one somebody really cut.

    Deliberately "SOME tag" and not "the NEAREST tag". The version an installed package reports was
    derived when it was installed, and this repository is installed editable - so between a fresh tag and
    the next `pip install -e .` the two legitimately differ by a release. That gap is a property of the
    venv, not of the code, and a test that went red on it would be reporting the wrong thing. The strict
    join - a version that must be exactly the tag it was built at - belongs to the artefact that is built
    fresh, and tests/test_wheel.py holds it there.

    Skipped when the checkout has no tags at all (a shallow clone); .github/workflows/release.yml is where
    that precondition is held, with `fetch-depth: 0`.
    """
    # Arrange
    listed = subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True, text=True, check=True)
    tags = {line.strip().lstrip("v") for line in listed.stdout.splitlines() if line.strip()}
    if not tags:
        pytest.skip("no tags in this checkout; nothing to join against")

    # Act
    release = simplon.__version__.split(".post")[0]

    # Assert
    assert release in tags, (
        f"the package says {simplon.__version__!r}, whose release {release!r} is not a tag of this "
        f"repository; a version that names no tag was not derived from one")


def test_every_workflow_checks_out_the_history_the_version_needs():
    """The precondition, held over EVERY workflow rather than the one that publishes.

    actions/checkout defaults to `fetch-depth: 1`, and a clone that shallow carries no tags. setuptools-scm
    then falls back to its `0.0` no-tag sentinel: the kernel calls itself something `released_pin` refuses,
    and a suite that passes in every developer's checkout goes red only in CI - or, on the release path,
    produces a wheel labelled with a version nobody chose and PyPI accepts without complaint.

    Asserted across the DIRECTORY because the failure is invisible in a diff: a new workflow gets the
    default, and the default is wrong here. `*.y*ml` because GitHub reads `.yaml` exactly as it reads
    `.yml`, and a test that only globbed one of them would be the same blind spot one file extension over.

    THE LIMIT, stated rather than left for somebody to discover: this reads the steps a workflow spells out
    itself. A checkout inside a composite action, or inside a reusable workflow this one calls with
    `uses:` at the job level, is invisible here - there is no file in this repository to read it out of.
    Neither exists today, and adding one means carrying the same setting across that boundary by hand.
    """
    # Arrange
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert files, WORKFLOWS

    # Act
    shallow = []
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in doc.get("jobs", {}).items():
            # A job that IS a `uses:` reusable-workflow call has no `steps` of its own. Skipped rather
            # than crashed on, and named in the docstring above as the boundary this test cannot see past.
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/checkout"):
                    if step.get("with", {}).get("fetch-depth") != 0:
                        shallow.append(f"{path.name}:{job_name}")

    # Assert
    assert shallow == [], f"these checkouts are shallow and cannot carry a version: {shallow}"
