"""simplon's OWN container image, held against simplon's own manifest (si#200).

WHY THIS FILE EXISTS SEPARATELY from test_tasks_image.py. That module proves the TASK works, against a
fixture manifest. This one proves it is USED - that the kernel which ships `build:image` and
`release:image` now points both at itself, that the Dockerfile and the context those coordinates name are
really on the disk, and that the pin si#201's launcher reads cannot drift away from the image the release
builds. It is the same split as test_workflowgen.py against test_own_workflows.py, and the same rule
underneath: a tool never used in its own house rots unseen.

WHAT IT CANNOT CLAIM. That an image exists in a registry. That takes a push, a credential and a network,
and nothing here can stand in for one - si#200 was driven end to end against a local `registry:2`
(built, pushed, read back, purged locally, pulled by version, run), and the Docker Hub half is unproven
because no account for it exists on the machine that did the work. What this file holds is everything
that would make such a push publish the wrong thing quietly: a pin naming an image nobody builds, a
moving tag under a launcher, a version that stops being derived, or a Dockerfile the manifest points past.

AAA throughout; nothing here builds, pushes or reaches a network.
"""
import subprocess

import pytest
import yaml

from simplon import docker
from simplon.tasks import image

from conftest import ROOT

#: The product's own manifest and the pin beside its Dockerfile - the two files this module is about.
MANIFEST = ROOT / "simplon.yaml"
PIN = ROOT / "deploy" / "image" / "image.pin"

#: The name simplon's manifest gives its one image, and the string both commands pin with `with:`.
IMAGE = "kernel"


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _reference(text: str) -> str:
    """The image reference a pin file states, or '' when it states that nothing is published.

    The rule is the one the file documents for bash - comments and blank lines are skipped, the first
    line left is the reference - and `test_the_pin_is_readable_by_a_shell_without_python` below holds
    this reading and the shell's against each other, because two readings of one file is exactly the
    drift si#201 would discover at runtime.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


# --- the placement: the kernel points both coordinates at itself ----------------------------------------


def test_the_kernel_declares_the_image_it_ships_the_coordinates_for():
    # arrange / act
    cfg = image.declared(_manifest(), IMAGE, source=str(MANIFEST))

    # assert
    assert cfg.registry and cfg.repository
    assert cfg.dockerfile == "deploy/image/Dockerfile" and cfg.context == "."


def test_the_declared_dockerfile_and_context_are_on_the_disk():
    # arrange: si#74's finding was a Dockerfile that moved and a manifest that did not, in another
    # product, discovered by a build. The kernel's own tree is checked here instead
    cfg = image.declared(_manifest(), IMAGE, source=str(MANIFEST))

    # act
    missing = image.missing_declared_paths(cfg, ROOT)

    # assert
    assert missing == []


@pytest.mark.parametrize("group", ["build", "release"])
def test_both_verbs_are_placed_and_pin_the_one_image(group):
    # arrange / act
    command = _manifest()["groups"][group]["commands"]["image"]

    # assert: the catalogue coordinate, not a body of its own, and the name pinned so the command line
    # carries no argument a caller has to remember
    assert command["task"] == f"{group}:image"
    assert command["with"] == {"name": IMAGE}


def test_the_image_declares_no_tag_so_there_is_one_source_for_the_version():
    # arrange: `git describe` is what stamps VERSION into the image, and since si#200 it is what tags it.
    # A `tag:` here would be a second place to keep one number - the arrangement #3 deleted from
    # pyproject.toml, where the version had been typed into three files
    cfg = image.declared(_manifest(), IMAGE, source=str(MANIFEST))

    # act / assert
    assert cfg.tag == ""


# --- the pin si#201 reads ------------------------------------------------------------------------------


#: Pins that must be refused, and the word the refusal has to carry. Written as data because the three
#: are the same defect at three depths: a tag that moves, no tag at all, and a tag on somebody else's
#: image - and a launcher that pulled any of them would run a kernel this checkout never chose.
_BAD_PINS = [
    ("docker.io/marcozwyssig/simplon:latest", "latest"),
    ("docker.io/marcozwyssig/simplon", "must pin a version"),
    ("docker.io/someone-else/simplon:v0.13.0", "not the image"),
]


def _pin_fault(text: str, cfg) -> str:
    """'' when the pin file `text` states something a launcher may act on, else the sentence saying why
    not.

    ONE CHECKER, USED TWICE, and that is the whole point of it existing rather than two assertions
    (si#200, on review). The committed pin carries no reference yet - nothing has been published - so a
    test that asserted the rule against the real file alone would be an assertion that cannot fail: this
    repository's oldest defect, a green verdict from a check that never ran. The rule therefore lives in
    one function, the bad cases below drive it red against synthetic pins, and the committed file is run
    through the SAME function. The day a reference lands in the file it is checked by code already proven
    to refuse, and no test has to be remembered and unguarded.

    An empty pin is a legitimate state rather than a fault: the file's own head says what a launcher must
    do with it, which is to say that this checkout has no published image and the venv route is the one
    that works.
    """
    reference = _reference(text)
    if not reference:
        return ""
    try:
        docker.pinned_image(reference, str(PIN))
    except ValueError as refusal:
        return str(refusal)
    if not reference.startswith(f"{cfg.registry}/{cfg.repository}:"):
        return (f"{PIN} names {reference}, which is not the image simplon.yaml builds "
                f"({cfg.registry}/{cfg.repository})")
    return ""


@pytest.mark.parametrize("line, word", _BAD_PINS)
def test_a_pin_a_launcher_must_not_act_on_is_named_as_such(line, word):
    # arrange
    cfg = image.declared(_manifest(), IMAGE, source=str(MANIFEST))

    # act
    fault = _pin_fault(f"# the file's own comment\n{line}\n", cfg)

    # assert
    assert word in fault


def test_a_pin_naming_this_products_image_at_a_version_is_accepted():
    # arrange: the green case of the same checker, so the three reds above are not merely a function that
    # refuses everything
    cfg = image.declared(_manifest(), IMAGE, source=str(MANIFEST))

    # act / assert
    assert _pin_fault(f"# a comment\n{cfg.registry}/{cfg.repository}:v0.13.0\n", cfg) == ""


def test_the_committed_pin_passes_that_same_rule():
    # arrange
    cfg = image.declared(_manifest(), IMAGE, source=str(MANIFEST))

    # act
    fault = _pin_fault(PIN.read_text(encoding="utf-8"), cfg)

    # assert
    assert fault == "", fault


def test_the_pin_is_readable_by_a_shell_without_python():
    # arrange: the whole premise of si#201's second route is that bash knows the image reference before
    # any Python exists. The pipeline below is the one deploy/image/image.pin documents, run for real
    written = "# a comment\n\n   # an indented comment\ndocker.io/marcozwyssig/simplon:v0.13.0\n"
    pipeline = "grep -v '^[[:space:]]*#' | grep -v '^[[:space:]]*$' | head -n1"

    # act
    shell = subprocess.run(["bash", "-c", pipeline], input=written, capture_output=True, text=True,
                           check=True)

    # assert: and the two readings of one file agree, which is what keeps si#201 from discovering a
    # second parser at runtime
    assert shell.stdout.strip() == "docker.io/marcozwyssig/simplon:v0.13.0"
    assert shell.stdout.strip() == _reference(written)


def test_the_shell_reading_of_the_committed_pin_is_the_python_one():
    # arrange / act
    pipeline = f"grep -v '^[[:space:]]*#' {PIN} | grep -v '^[[:space:]]*$' | head -n1"
    shell = subprocess.run(["bash", "-c", pipeline], capture_output=True, text=True, check=True)

    # assert
    assert shell.stdout.strip() == _reference(PIN.read_text(encoding="utf-8"))


# --- what the image is, and what publishes it ----------------------------------------------------------


def test_the_context_keeps_the_git_directory_the_version_is_derived_from():
    # arrange: the silent failure this guard is for. Excluding `.git` is the usual advice and it is wrong
    # here - setuptools-scm would then derive its no-tag sentinel INSIDE the build, the image would carry
    # a version nobody chose, and every other artefact would still look correct
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    # act
    lines = [line.strip() for line in ignored.splitlines() if line.strip()
             and not line.strip().startswith("#")]

    # assert
    assert not any(line.strip("/*") == ".git" for line in lines)


def test_the_image_carries_the_kernel_from_this_tree_rather_than_from_a_release():
    # arrange: a Dockerfile installing `simplon==<version>` off PyPI could only be built after a release,
    # so the ci.yml step that keeps it from rotting could not exist
    dockerfile = (ROOT / "deploy" / "image" / "Dockerfile").read_text(encoding="utf-8")

    # act / assert
    assert "python -m build --wheel" in dockerfile
    assert "pip install --no-cache-dir simplon" not in dockerfile


def test_the_docker_client_in_the_image_is_the_version_the_kernel_already_pins():
    """One source for the docker CLI version, two consumers (si#201).

    si#200 kept the client out of the image on the argument that a baked copy would be the version nobody
    bumps. si#201 measured that leaving it out costs 84 MB and 15.0 s on first use, needs egress from a
    container whose premise is "bash and docker", and changes four verdicts in simplon's own gate - so
    the client went in. This is the half that answers the original objection: the Dockerfile installs
    `simplon.docker.DOCKER_CLI_VERSION` and nothing else, so bumping the kernel's pin bumps the layer or
    this goes red.
    """
    # arrange
    dockerfile = (ROOT / "deploy" / "image" / "Dockerfile").read_text(encoding="utf-8")

    # act
    declared = [line.split("=", 1)[1].strip() for line in dockerfile.splitlines()
                if line.startswith("ARG DOCKER_CLI_VERSION=")]

    # assert
    assert declared == [docker.DOCKER_CLI_VERSION], declared
    # and the CLIENT only: the static bundle also carries the engine binaries, which have nothing to do
    # in an image that talks to the host's daemon through a mounted socket
    assert "docker/docker" in dockerfile
    assert "dockerd" not in dockerfile


def test_oras_is_still_out_of_the_image_because_nothing_measured_asked_for_it():
    # arrange: the other half of si#201's split, asserted because an absence is what a reviewer cannot
    # see. oras is reached only by `release:artifact` and the read-back in `release:image`, it has a
    # provisioning gate that works (`simplon.oras.ensure_oras`), and it changed no verdict in the
    # both-routes gate run - so the argument si#200 made against baking a tool in still holds for it
    dockerfile = (ROOT / "deploy" / "image" / "Dockerfile").read_text(encoding="utf-8")

    # act: the INSTRUCTIONS only - this file argues its decisions in prose, and a sweep that read
    # the comments would be asking whether the word appears rather than whether the tool is there
    instructions = [line for line in dockerfile.splitlines()
                    if line.strip() and not line.strip().startswith("#")]

    # assert
    assert not any("oras" in line.lower() for line in instructions), instructions


def test_the_image_is_built_on_every_push_so_the_dockerfile_cannot_rot():
    # arrange
    steps = _manifest()["workflows"]["ci"]["jobs"]["self-build"]["steps"]

    # act
    commands = [step.get("command") for step in steps]

    # assert
    assert "build image" in commands


def test_nothing_publishes_the_image_automatically():
    # arrange: the decision si#200 took, asserted because an absence is what a reviewer cannot see.
    # Publishing needs a long-lived Docker Hub token in the repository's secrets; this repository stores
    # no registry secret at all today (PyPI is Trusted Publishing, Pages is OIDC). The day that changes
    # it is a decision somebody takes, with this test in the diff
    declared = _manifest()["workflows"]
    generated = "".join((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
                        for name in ("ci.yml", "release.yml"))

    # act
    steps = [step.get("command") for job in declared["ci"]["jobs"].values() for step in job["steps"]]

    # assert
    assert "release image" not in steps
    assert "release image" not in generated
