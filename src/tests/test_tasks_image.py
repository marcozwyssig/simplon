"""`build:image` / `release:image` - building a product's container image and publishing it (#31).

What is the product's is DATA: which registry, which package, which Dockerfile, which context, which
extra build arguments, which tag. The mechanics - derive the provenance, build, log in, push, and READ
BACK that the tag is in the registry - are the same everywhere, which is why they are in the kernel.

The read-back is the reason most of the red cases below exist. This project has twice shipped a step that
exited 0 and left nothing behind (`allure.render_report` for two releases; hugo on an empty content
tree), so a push nobody verifies is not treated here as a publish. Every one of those failures is
asserted RED, not merely described.

AAA throughout; nothing here builds, pushes or logs in for real - except `provenance`, which is measured
against a real temporary git checkout, because a derivation nobody ran against git is a guess.
"""
import os
import json
import re
import shutil
import subprocess
from pathlib import Path

import pathlib

import pytest

from conftest import lifecycle_name, without_lifecycle

from simplon.manifest import context
from simplon.adapters import docker, githubpackages
from simplon.manifest.context import ProductContext
from simplon.kernel.run import Result
from simplon.manifest import results as results_mod
from simplon.tasks import image

#: The real gate, captured before the autouse fixture below neutralises it - the two tests that assert
#: it DIES need the actual body, and reaching for it through the patched module would find the stub.
_REAL_ENSURE_DOCKER = docker.ensure_docker

_MANIFEST = """
product: demo
artifacts:
  app:
    kind: image
    registry: ghcr.io/owner
    repository: demo-app
    dockerfile: Dockerfile
    context: .
  worker:
    kind: image
    registry: ghcr.io/owner
    repository: demo-worker
    dockerfile: docker/worker.Dockerfile
    context: services/worker
    tag: latest
    build_args:
      PYTHON_VERSION: "3.12"
      SLIM: true
"""


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    (tmp_path / "Dockerfile").write_text("FROM busybox:1.36\n", encoding="utf-8")
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "worker.Dockerfile").write_text("FROM busybox:1.36\n", encoding="utf-8")
    # `worker` declares `context: services/worker`, and until si#74 this fixture never created it: three
    # tests here built an image whose declared context was not on the disk and asserted that docker was
    # handed the path anyway. That is si#74's finding sitting inside the kernel's own suite.
    (tmp_path / "services" / "worker").mkdir(parents=True)
    # The gate itself has its own tests (test_docker.py); here it is neutralised so a host without
    # docker still runs this suite - the one test that asserts it DIES restores it deliberately.
    monkeypatch.setattr(docker, "ensure_docker", lambda: None)
    return tmp_path


class _Cli:
    """A stand-in for the docker (and git) command line: records every argv and answers from a rule.

    `verdict` maps the first tokens of an argv to an rc, defaulting to 0, so a test states only the one
    call it wants to fail - which is how each red case below stays about one thing.
    """

    def __init__(self, verdict=None, output="", outputs=None, effects=None):
        self.calls: list = []
        # What a streamed command LEAVES BEHIND, by argv prefix - bake's `--metadata-file` (fix round 1).
        self.effects = effects or {}
        self.verdict = verdict or {}
        self.output = output
        # si#347: what a command PRINTS, by argv prefix, for the calls whose answer is read as a value -
        # the registry's index, the builder's platform list, the daemon's own platform. `output` stays the
        # answer of every other call, so the tests written before this keep the fake they were written for.
        self.outputs = outputs or {}

    def _rc(self, argv) -> int:
        for prefix, rc in self.verdict.items():
            if tuple(argv[:len(prefix)]) == tuple(prefix):
                return rc
        return 0

    def _out(self, argv) -> str:
        for prefix, out in self.outputs.items():
            if tuple(argv[:len(prefix)]) == tuple(prefix):
                return out
        return self.output

    def run(self, argv, **kwargs) -> Result:
        self.calls.append(list(argv))
        return Result(rc=self._rc(argv), out=self._out(argv), err="")

    def stream(self, argv, **kwargs) -> int:
        self.calls.append(list(argv))
        rc = self._rc(argv)
        for prefix, effect in self.effects.items():
            if rc == 0 and tuple(argv[:len(prefix)]) == tuple(prefix):
                effect(list(argv))
        return rc

    def argv_starting(self, *prefix) -> list:
        return [call for call in self.calls if tuple(call[:len(prefix)]) == prefix]


@pytest.fixture(autouse=True)
def _oras_is_there(monkeypatch):
    """The oras gate, neutralised. It PROVIDES the tool (network, or a package manager), which no unit
    test may do; the two tests about its absence patch it back deliberately."""
    monkeypatch.setattr(githubpackages, "require_oras", lambda: None)


@pytest.fixture
def cli(monkeypatch):
    """The command line, stubbed for both seams the module uses."""
    fake = _Cli()
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)
    return fake


@pytest.fixture
def _no_provenance(monkeypatch):
    """No git derivation, for the tests that are about something else - so a build argv stays readable."""
    monkeypatch.setattr(image, "provenance", lambda root: {})


# --- what the manifest declares -----------------------------------------------------------------------

def test_a_declared_image_carries_its_registry_repository_dockerfile_and_context():
    # arrange
    data = _images(app={"registry": "ghcr.io/owner", "repository": "demo-app",
                   "dockerfile": "Dockerfile", "context": "."})

    # act
    cfg = image.declared(data, "app")

    # assert
    assert (cfg.registry, cfg.repository) == ("ghcr.io/owner", "demo-app")
    assert (cfg.dockerfile, cfg.context) == ("Dockerfile", ".")


def test_an_undeclared_image_lists_the_ones_that_are():
    # arrange
    data = _images(app={}, worker={})

    # act / assert
    with pytest.raises(ValueError, match="app, worker"):
        image.declared(data, "nope")


def test_a_missing_section_says_what_a_product_has_to_declare():
    # arrange: the failure has to land HERE, naming the keys, rather than as a docker run against a path
    # that is not there

    # act / assert
    with pytest.raises(ValueError, match="registry, the repository, the Dockerfile"):
        image.declared({"product": "demo"}, "app")


@pytest.mark.parametrize("missing", ["registry", "repository", "dockerfile", "context"])
def test_each_required_key_is_named_when_it_is_the_one_that_is_missing(missing):
    # arrange: four keys, four distinguishable messages - a section missing `dockerfile` should say so,
    # not complain about the optional tag it also has not got
    body = {"registry": "ghcr.io/owner", "repository": "demo-app",
            "dockerfile": "Dockerfile", "context": "."}
    del body[missing]

    # act / assert
    with pytest.raises(ValueError, match=f"declares no `{missing}:`, which build:image needs"):
        image.declared(_images(app=body), "app")


def test_a_registry_is_required_even_for_a_purely_local_build():
    """An unqualified name is what docker resolves against Docker Hub, so a build tagged without a
    registry and a release pushing it are two different images (simplon.adapters.imagenames.require_registry records
    that failure in full). The build has to tag what the release will push."""
    # arrange
    body = {"repository": "demo-app", "dockerfile": "Dockerfile", "context": "."}

    # act / assert
    with pytest.raises(ValueError, match="declares no `registry:`, which build:image needs"):
        image.declared(_images(app=body), "app")


@pytest.mark.parametrize("key,value", [("context", "/srv"), ("context", "../elsewhere"),
                                       ("dockerfile", "/etc/Dockerfile"), ("dockerfile", "../D")])
def test_a_path_that_leaves_the_product_root_is_refused_before_docker_sees_it(key, value):
    # arrange: `context: /` would stream the whole filesystem to the daemon as a build context
    body = {"registry": "ghcr.io/owner", "repository": "demo-app",
            "dockerfile": "Dockerfile", "context": "."}
    body[key] = value

    # act / assert
    with pytest.raises(ValueError, match="relative"):
        image.declared(_images(app=body), "app")


def test_a_context_of_dot_is_accepted_and_means_the_product_root():
    """The shared path rule refuses a bare '.' for its other callers (they scaffold into the path or hand
    it to rmtree); naming the product root is normal and unambiguous for a build context."""
    # arrange
    body = {"registry": "ghcr.io/owner", "repository": "demo-app",
            "dockerfile": "Dockerfile", "context": "./"}

    # act
    cfg = image.declared(_images(app=body), "app")

    # assert
    assert cfg.context == "."


def test_declared_build_arguments_are_carried_as_strings():
    # arrange: a manifest is YAML, so `SLIM: true` arrives as a bool and docker only speaks text
    data = _images(app={"registry": "ghcr.io/o", "repository": "r", "dockerfile": "Dockerfile",
                   "context": ".", "build_args": {"PYTHON_VERSION": "3.12", "SLIM": True,
                                                  "RETRIES": 3}})

    # act
    cfg = image.declared(data, "app")

    # assert
    assert cfg.build_args == {"PYTHON_VERSION": "3.12", "SLIM": "true", "RETRIES": "3"}


def test_a_build_argument_that_is_not_a_scalar_is_refused():
    # arrange: a list would reach docker as its repr, which is a value nobody wrote
    data = _images(app={"registry": "ghcr.io/o", "repository": "r", "dockerfile": "Dockerfile",
                   "context": ".", "build_args": {"PORTS": [80, 443]}})

    # act / assert
    with pytest.raises(ValueError, match="scalar"):
        image.declared(data, "app")


# --- the tag, from either side ------------------------------------------------------------------------

def test_a_tag_declared_in_the_manifest_needs_no_argument(cli, _no_provenance, _product):
    # arrange / act
    rc = image.build(name="worker")

    # assert
    assert rc == 0
    assert "ghcr.io/owner/demo-worker:latest" in cli.argv_starting("docker", "build")[0]


def test_an_argument_tag_wins_over_the_declared_one(cli, _no_provenance):
    # arrange: cleon's version is generated into a jar and only readable after a build, which is why the
    # argument exists at all - so it has to beat a constant the manifest happens to carry
    # act
    image.build(name="worker", tag="0.4.149")

    # assert
    assert "ghcr.io/owner/demo-worker:0.4.149" in cli.argv_starting("docker", "build")[0]


def test_without_a_tag_anywhere_and_nothing_to_derive_it_names_the_places_one_could_be(cli):
    # arrange: the `cli` fixture answers every git call with empty output, so the derivation below finds
    # no checkout and contributes nothing - which is the only state in which there is nothing to tag with
    # act / assert
    with pytest.raises(ValueError, match="--tag"):
        image.build(name="app")


def test_with_no_tag_declared_the_version_the_build_stamps_is_the_tag(monkeypatch, cli):
    """si#200. `git describe` already produces the number the image is STAMPED with (VERSION), so taking
    the tag from anywhere else would be a second source for one number - and the second source is the one
    that goes stale. The tag IS the derived version, verbatim: no leading 'v' stripped, no normalisation,
    because a rule that rewrites the number is a third statement about it."""
    # arrange
    monkeypatch.setattr(image, "provenance", lambda root: {"VERSION": "v0.13.0", "REVISION": "abc"})

    # act
    rc = image.build(name="app")

    # assert
    assert rc == 0
    assert "ghcr.io/owner/demo-app:v0.13.0" in cli.argv_starting("docker", "build")[0]


def test_a_declared_tag_still_beats_the_derived_one(monkeypatch, cli):
    # arrange: the same precedence `build_args` has - a product that stated its tag means it, and a
    # derivation that silently won over a manifest would make the manifest a suggestion
    monkeypatch.setattr(image, "provenance", lambda root: {"VERSION": "v0.13.0"})

    # act
    image.build(name="worker")

    # assert
    assert "ghcr.io/owner/demo-worker:latest" in cli.argv_starting("docker", "build")[0]


def test_a_declared_version_build_argument_carries_the_tag_with_it(monkeypatch, cli):
    # arrange: `build_args: { VERSION: ... }` is a product saying where its version really comes from, and
    # the image tag follows the version WHEREVER it was decided - one number, one place, still
    monkeypatch.setattr(image, "provenance", lambda root: {"VERSION": "v0.13.0"})
    data = image.declared(_images(app={"registry": "ghcr.io/owner", "repository": "demo-app",
                                  "dockerfile": "Dockerfile", "context": ".",
                                  "build_args": {"VERSION": "4.2.0"}}), "app")

    # act
    tag = image.resolve_tag(data, "", image.build_arguments(data, Path("/nowhere")).get("VERSION", ""))

    # assert
    assert tag == "4.2.0"


def test_a_release_tags_what_the_build_tagged_without_being_told_twice(monkeypatch, cli, logins):
    # arrange: build and release are two commands, so the number would otherwise be typed twice - and the
    # release.yml check that the wheel IS the tag exists because two typed numbers drift
    monkeypatch.setattr(image, "provenance", lambda root: {"VERSION": "v0.13.0"})

    # act
    rc = image.release(name="app")

    # assert
    assert rc == 0
    assert cli.argv_starting("docker", "push")[0] == ["docker", "push", "ghcr.io/owner/demo-app:v0.13.0"]


def test_without_a_name_it_says_how_a_product_pins_one(cli):
    # act / assert
    with pytest.raises(ValueError, match="with: "):
        image.build(tag="1.0")


# --- provenance: measured against a real git checkout --------------------------------------------------

def _checkout(path: Path) -> Path:
    """A real, minimal git repository - the derivation is about git's answers, not about a stub's."""
    path.mkdir(parents=True, exist_ok=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@e", "PATH": "/usr/bin:/bin", "HOME": str(path)}
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "first"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "tag", "v1.2.3"], check=True, env=env)
    return path


@pytest.mark.skipif(shutil.which("git") is None, reason="git is the thing being measured")
def test_version_and_revision_are_derived_from_the_products_own_checkout(tmp_path):
    # arrange
    root = _checkout(tmp_path / "product")

    # act
    derived = image.provenance(root)

    # assert
    assert derived["VERSION"] == "v1.2.3"
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert derived["REVISION"] == head and len(head) == 40


@pytest.mark.skipif(shutil.which("git") is None, reason="git is the thing being measured")
def test_the_derived_version_is_the_products_and_never_the_kernels(tmp_path):
    """The decision #31 asks for in so many words: setuptools-scm is right here in this repository, and
    what it yields is SIMPLON's release number. Stamping it into a product's image would label the
    product with the version of its build tool."""
    # arrange
    import simplon

    root = _checkout(tmp_path / "product")

    # act
    derived = image.provenance(root)

    # assert
    assert derived["VERSION"] == "v1.2.3" != simplon.__version__


@pytest.mark.skipif(shutil.which("git") is None, reason="git is the thing being measured")
def test_an_uncommitted_change_is_visible_in_the_derived_version(tmp_path):
    # arrange: an image built from a dirty tree is not reproducible from any commit, and has to say so
    root = _checkout(tmp_path / "product")
    (root / "a.txt").write_text("changed", encoding="utf-8")

    # act
    derived = image.provenance(root)

    # assert
    assert derived["VERSION"].endswith("-dirty")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is the thing being measured")
def test_a_tree_inside_someone_elses_checkout_stamps_nothing(tmp_path, capsys):
    """`git -C <dir>` CLIMBS: in a directory with no `.git` of its own it answers out of the nearest
    enclosing repository, rc 0 and no hint. Measured on this kernel - a product tree created inside
    simplon's checkout returned simplon's own describe and HEAD, which is exactly the mislabelling the
    module promises not to do."""
    # arrange
    outer = _checkout(tmp_path / "outer")
    inner = outer / "products" / "inner"
    inner.mkdir(parents=True)

    # act
    derived = image.provenance(inner)

    # assert
    assert derived == {}
    warning = capsys.readouterr().out
    assert "no git checkout of its own" in warning and str(outer) in warning


@pytest.mark.skipif(shutil.which("git") is None, reason="git is the thing being measured")
def test_a_checkout_reached_through_a_symlink_is_still_that_checkout(tmp_path):
    # arrange: the toplevel comparison must not turn a symlinked path into a foreign repository
    root = _checkout(tmp_path / "product")
    link = tmp_path / "link"
    link.symlink_to(root)

    # act
    derived = image.provenance(link)

    # assert
    assert derived["VERSION"] == "v1.2.3"


def test_a_tree_that_is_not_a_checkout_yields_no_arguments_rather_than_a_placeholder(tmp_path):
    """An exported tarball has no git. Passing VERSION=unknown would override the Dockerfile's own
    `ARG VERSION=dev` - a considered product default - with a kernel placeholder, and the image would
    then claim a provenance nobody derived."""
    # arrange
    bare = tmp_path / "no-git"
    bare.mkdir()

    # act
    derived = image.provenance(bare)

    # assert
    assert derived == {}


def test_without_git_on_the_host_the_build_still_runs_without_provenance(monkeypatch, tmp_path):
    # arrange
    monkeypatch.setattr(image.shutil, "which", lambda name: None)

    # act
    derived = image.provenance(tmp_path)

    # assert
    assert derived == {}


def test_a_declared_build_argument_wins_over_the_derived_one(monkeypatch):
    # arrange: a `build_args:` entry naming VERSION is a product stating where its version really comes
    # from; the derivation is the default for those that have not said
    monkeypatch.setattr(image, "provenance", lambda root: {"VERSION": "v1.2.3", "REVISION": "abc"})
    cfg = image.Image(registry="ghcr.io/o", repository="r", dockerfile="Dockerfile", context=".",
                      build_args={"VERSION": "9.9.9"})

    # act
    args = image.build_arguments(cfg, Path("/nowhere"))

    # assert
    assert args == {"VERSION": "9.9.9", "REVISION": "abc"}


# --- build --------------------------------------------------------------------------------------------

def test_the_build_carries_the_dockerfile_the_reference_and_both_derived_arguments(cli, monkeypatch,
                                                                                   _product):
    # arrange
    monkeypatch.setattr(image, "provenance", lambda root: {"VERSION": "v1.2.3", "REVISION": "abc123"})

    # act
    rc = image.build(name="app", tag="1.0")

    # assert
    argv = cli.argv_starting("docker", "build")[0]
    assert rc == 0
    assert argv[:2] == ["docker", "build"]
    assert "--file" in argv and str(_product / "Dockerfile") in argv
    assert "--tag" in argv and "ghcr.io/owner/demo-app:1.0" in argv
    assert "--build-arg" in argv and "VERSION=v1.2.3" in argv and "REVISION=abc123" in argv
    assert argv[-1] == str(_product)


def test_a_declared_context_directory_is_what_docker_is_handed(cli, _no_provenance, _product):
    # arrange / act
    image.build(name="worker")

    # assert
    assert cli.argv_starting("docker", "build")[0][-1] == str(_product / "services/worker")


def test_a_missing_dockerfile_is_named_before_docker_is_started(cli, _no_provenance, _product):
    # arrange: the manifest says where it is; nothing answers to that path
    (_product / "Dockerfile").unlink()

    # act
    rc = image.build(name="app", tag="1.0")

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "build") == []


def test_a_missing_dockerfile_says_which_of_the_two_declared_paths_is_gone(cli, _no_provenance,
                                                                            _product, capsys):
    """si#74: `dockerfile:` and the context path can each go stale on their own, and which one did is the
    whole content of the answer. The finding that opened the ticket is exactly this - a Dockerfile that
    moved from the product root into `deploy/` (ac#28) - and a message that only said "the build failed"
    would have left the reader guessing between two lines of the manifest.
    """
    # arrange: the context is fine, the Dockerfile is not
    (_product / "Dockerfile").unlink()

    # act
    rc = image.build(name="app", tag="1.0")

    # assert: red, nothing built, and the message names the key that is wrong and not the other one
    assert rc == 1
    assert cli.argv_starting("docker", "build") == []
    err = capsys.readouterr().err
    assert "dockerfile: Dockerfile" in err
    assert "context:" not in err


def test_a_missing_context_is_caught_too_and_named_as_the_context(cli, _no_provenance, _product, capsys):
    """The half si#74 found missing. Before it, a context pointing at nothing reached `docker build` and
    came back as a tar error about a path, from a tool that had no idea a manifest existed."""
    # arrange: the Dockerfile is fine, the context directory is not
    shutil.rmtree(_product / "services" / "worker")

    # act
    rc = image.build(name="worker")

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "build") == []
    err = capsys.readouterr().err
    assert "context: services/worker" in err
    assert "dockerfile:" not in err


def test_both_paths_gone_are_both_named_rather_than_the_first_one(cli, _no_provenance, _product, capsys):
    """A message that stopped at the first fault would send the reader round twice. Both keys can be
    stale at once - that is what a directory move does - so both are reported in one answer."""
    # arrange
    (_product / "docker" / "worker.Dockerfile").unlink()
    shutil.rmtree(_product / "services" / "worker")

    # act
    rc = image.build(name="worker")

    # assert
    assert rc == 1
    err = capsys.readouterr().err
    assert "dockerfile: docker/worker.Dockerfile" in err
    assert "context: services/worker" in err
    assert "two paths that do not exist" in err


def test_a_declared_path_that_is_gone_is_answered_without_docker_on_the_host(monkeypatch, _no_provenance,
                                                                            _product, capsys):
    """The ORDER, which is the other half of the si#74 decision. The check used to sit after
    `ensure_docker`, so on a host with no docker the answer to "my manifest points at nothing" was "you
    have no docker" - a true statement about the wrong question, and the kernel's own recurring defect.

    Contrast `test_a_missing_docker_kills_the_build_rather_than_hinting` below: with the paths intact,
    a missing docker still dies. Only a broken declaration overtakes it.
    """
    # arrange: the real gate, no docker anywhere, and a Dockerfile that is not there
    monkeypatch.setattr(docker, "ensure_docker", _REAL_ENSURE_DOCKER)
    monkeypatch.setattr(docker.shutil, "which", lambda name: None)
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "0")
    (_product / "Dockerfile").unlink()

    # act: rc rather than SystemExit is the assertion - the docker gate never ran
    rc = image.build(name="app", tag="1.0")

    # assert
    assert rc == 1
    assert "dockerfile: Dockerfile" in capsys.readouterr().err


def test_a_failing_build_hands_back_dockers_own_rc(monkeypatch, _no_provenance):
    # arrange
    fake = _Cli(verdict={("docker", "build"): 7})
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)

    # act
    rc = image.build(name="app", tag="1.0")

    # assert
    assert rc == 7


def test_a_build_that_exits_zero_without_producing_the_image_is_red(monkeypatch, _no_provenance):
    """The 0.1.7 shape: rc 0 and nothing behind it. One cheap question separates a green build from a
    release step that pushes a reference the daemon does not have."""
    # arrange
    fake = _Cli(verdict={("docker", "image", "inspect"): 1})
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)

    # act
    rc = image.build(name="app", tag="1.0")

    # assert
    assert rc == 1


def test_a_missing_docker_kills_the_build_rather_than_hinting(monkeypatch, capsys):
    """The opposite decision from `docs:site`, and #31 acceptance 4. There a missing tool is a hint and
    rc 0, because the output is not the point of the run; here it is the whole point."""
    # arrange: the real gate, with no docker anywhere and no bootstrap opt-in
    monkeypatch.setattr(docker, "ensure_docker", _REAL_ENSURE_DOCKER)
    monkeypatch.setattr(docker.shutil, "which", lambda name: None)
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "0")

    # act / assert
    with pytest.raises(SystemExit) as exit_:
        image.build(name="app", tag="1.0")
    assert exit_.value.code == 1
    assert "docker" in capsys.readouterr().err


# --- release ------------------------------------------------------------------------------------------

@pytest.fixture
def logins(monkeypatch):
    """A docker login that succeeds, recorded - the failure case replaces it deliberately."""
    seen: list = []
    monkeypatch.setattr(githubpackages, "docker_login",
                        lambda registry, **kw: seen.append(registry))
    return seen


def test_a_release_logs_in_pushes_and_then_asks_the_registry(cli, logins):
    # arrange / act
    rc = image.release(name="app", tag="1.0")

    # assert
    assert rc == 0
    assert logins == ["ghcr.io/owner"]
    assert cli.argv_starting("docker", "push")[0] == ["docker", "push", "ghcr.io/owner/demo-app:1.0"]
    # and the question went to the REGISTRY through a client with no local store to answer from - the
    # daemon would say yes for the image that never left the machine, and `docker manifest inspect` says
    # yes for a tag that only exists in ~/.docker/manifests/
    assert cli.argv_starting("oras", "manifest", "fetch")


# --- si#439: the evidence must be about what is pushed ------------------------------------------------
# A green record from an earlier build read green. The release now compares each reference it pushes with
# the daemon id the bound evidence ran, inside the guard that read it (`results.tested`).

def _released_after(subjects, name="app"):
    """`release` run the way the guard runs it: with `subjects` as what the bound evidence ran."""
    token = results_mod._tested.set(tuple(results_mod.Subject("checked", ref, id_) for ref, id_ in subjects))
    try:
        return image.release(name=name, tag="1.0")
    finally:
        results_mod._tested.reset(token)


def test_a_release_whose_evidence_ran_these_bytes_publishes(cli, logins):
    # arrange
    cli.outputs[("docker", "image", "inspect", "--format")] = "sha256:aa\n"

    # act
    rc = _released_after([("ghcr.io/owner/demo-app:1.0", "sha256:aa")])

    # assert
    assert rc == 0
    assert cli.argv_starting("docker", "push")


def test_evidence_about_another_tag_publishes_nothing(cli, logins, capsys):
    # arrange: the case si#439 measured - yesterday's green record, a release by hand with another --tag
    cli.outputs[("docker", "image", "inspect", "--format")] = "sha256:aa\n"

    # act
    rc = _released_after([("ghcr.io/owner/demo-app:0.9", "sha256:aa")])

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "push") == [] and logins == []
    err = capsys.readouterr().err
    assert "ghcr.io/owner/demo-app:1.0 was never tested: the evidence ran ghcr.io/owner/demo-app:0.9" in err


def test_evidence_about_the_same_tag_before_a_rebuild_publishes_nothing(cli, logins, capsys):
    # arrange: the case a reference comparison would miss - same tag, new bytes
    cli.outputs[("docker", "image", "inspect", "--format")] = "sha256:bb\n"

    # act
    rc = _released_after([("ghcr.io/owner/demo-app:1.0", "sha256:aa")])

    # assert: told apart from "never tested", because the fix is the same but the cause is not
    assert rc == 1
    assert cli.argv_starting("docker", "push") == []
    err = capsys.readouterr().err
    assert "was rebuilt after it was tested: the test ran sha256:aa, and it is sha256:bb now" in err
    assert "never tested" not in err


def test_a_multi_platform_release_compares_every_platform_it_pushes(monkeypatch, logins, _no_provenance,
                                                                   _recorded, _multi, capsys):
    # arrange: arm64 was smoked, amd64 was not
    fake = _fake(monkeypatch, outputs={("oras", "manifest", "fetch"): _INDEX_BOTH,
                                       ("docker", "image", "inspect", "--format"): "sha256:aa\n"})

    # act
    rc = _released_after([("ghcr.io/owner/demo-multi:1.0-linux-arm64", "sha256:aa")], name="multi")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "buildx", "bake") == []
    assert "demo-multi:1.0-linux-amd64 was never tested" in capsys.readouterr().err


def test_a_push_that_exits_zero_without_the_tag_reaching_the_registry_is_red(monkeypatch, logins,
                                                                            capsys):
    """#31 acceptance 3, seen red. `docker push` reports success, the registry does not serve the tag -
    measured for real against a local registry:2 whose tag directory was removed under it, and the probe
    answered `not found`."""
    # arrange
    fake = _Cli(verdict={("oras", "manifest", "fetch"): 1})
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)

    # act
    rc = image.release(name="app", tag="1.0")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "push")           # it really did push, and reported success
    assert "not in the registry" in capsys.readouterr().err


def test_a_failed_login_stops_the_release_and_names_the_command_that_grants_the_scopes(cli, monkeypatch,
                                                                                       capsys):
    """#31 acceptance 5's first half, and acceptance 4's second. A registry that rejects the credential
    must not end in a traceback the reader has to dig the fix out of."""
    # arrange: off a workflow, where this advice applies (si#361) - CI runs this suite inside one
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    def rejected(registry, **kwargs):
        raise githubpackages.PackageError("docker login to ghcr.io failed: 401 Unauthorized\n"
                                          + githubpackages.scope_advice())
    monkeypatch.setattr(githubpackages, "docker_login", rejected)

    # act
    rc = image.release(name="app", tag="1.0")

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "push") == []      # nothing was pushed after a refused login
    err = capsys.readouterr().err
    assert "gh auth refresh" in err and "write:packages" in err


def test_a_failing_push_hands_back_dockers_own_rc_and_asks_the_registry_nothing(monkeypatch, logins):
    # arrange: `no basic auth credentials` is what an unauthenticated push against a registry with
    # htpasswd answers with, rc 1 - measured
    fake = _Cli(verdict={("docker", "push"): 1})
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)

    # act
    rc = image.release(name="app", tag="1.0")

    # assert: and nothing is read back, because a push that failed has nothing to confirm
    assert rc == 1
    assert fake.argv_starting("oras", "manifest", "fetch") == []


def test_a_release_without_a_locally_built_image_says_to_build_first(monkeypatch, logins, capsys):
    # arrange
    fake = _Cli(verdict={("docker", "image", "inspect"): 1})
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)

    # act
    rc = image.release(name="app", tag="1.0")

    # assert
    assert rc == 1
    assert logins == [] and fake.argv_starting("docker", "push") == []
    assert "build:image" in capsys.readouterr().err


def test_a_registry_that_is_not_github_gets_no_github_token(cli, monkeypatch, capsys, _product):
    """`registry:` is a MANIFEST KEY. Without this check a product writing `registry: registry.example.com`
    would have a GitHub PAT minted and handed to a third party - and the 401 answered with
    `gh auth refresh`, advice that means nothing there. The module the credential comes from exists
    because a token leaked once."""
    # arrange
    (_product / "demo.yaml").write_text(_MANIFEST.replace("registry: ghcr.io/owner",
                                                          "registry: registry.example.com/team"),
                                        encoding="utf-8")
    monkeypatch.setattr(githubpackages, "docker_login",
                        lambda registry, **kw: pytest.fail("a GitHub token must not leave GitHub"))
    # ... and the operator has stored one, which si#200 made a precondition rather than an assumption
    monkeypatch.setattr(docker, "has_stored_login", lambda host: True)

    # act
    rc = image.release(name="app", tag="1.0")

    # assert: the push still happens, on whatever credential the operator already stored
    assert rc == 0
    assert cli.argv_starting("docker", "push")[0][-1] == "registry.example.com/team/demo-app:1.0"
    assert "no GitHub token is minted" in capsys.readouterr().out


def test_a_push_to_a_registry_with_no_stored_credential_is_refused_rather_than_attempted(
        monkeypatch, capsys, _product, cli):
    """si#200, and it is the other half of `is_github_packages`. That check stops the GitHub token from
    reaching a third-party host; it leaves the third-party host with no credential story at all, and the
    push went out anyway - to be answered by `denied: requested access to the resource is denied`, which
    names no host, no account and no fix. Docker Hub is the registry that made this concrete."""
    # arrange
    (_product / "demo.yaml").write_text(_MANIFEST.replace("registry: ghcr.io/owner",
                                                          "registry: docker.io/team"), encoding="utf-8")
    monkeypatch.setattr(docker, "has_stored_login", lambda host: False)

    # act
    rc = image.release(name="app", tag="1.0")

    # assert: refused BEFORE the push, and the message names the host and the command that fixes it
    assert rc == 1
    assert cli.argv_starting("docker", "push") == []
    said = capsys.readouterr().err
    assert "docker login docker.io" in said and "docker.io/team/demo-app:1.0" in said


def test_the_credential_is_asked_about_the_host_and_not_about_the_whole_registry(monkeypatch, cli,
                                                                                 _product):
    # arrange: `registry:` carries the namespace too (`docker.io/team`), and `docker login` knows only
    # hosts - asking about the namespace would answer no for a host that IS logged in
    (_product / "demo.yaml").write_text(_MANIFEST.replace("registry: ghcr.io/owner",
                                                          "registry: docker.io/team"), encoding="utf-8")
    asked: list = []
    monkeypatch.setattr(docker, "has_stored_login", lambda host: asked.append(host) or True)

    # act
    image.release(name="app", tag="1.0")

    # assert
    assert asked == ["docker.io"]


def test_github_packages_still_mints_its_own_credential_rather_than_demanding_a_stored_one(monkeypatch,
                                                                                           cli, logins):
    # arrange: the GHCR path logs in for itself, so demanding a stored credential there would refuse the
    # one registry this kernel CAN authenticate to on its own
    monkeypatch.setattr(docker, "has_stored_login",
                        lambda host: pytest.fail("the GHCR path mints its own credential"))

    # act
    rc = image.release(name="app", tag="1.0")

    # assert
    assert rc == 0 and logins == ["ghcr.io/owner"]


def test_a_failing_push_to_a_registry_that_is_not_github_says_nothing_about_gh(monkeypatch, capsys,
                                                                               _product):
    # arrange
    (_product / "demo.yaml").write_text(_MANIFEST.replace("registry: ghcr.io/owner",
                                                          "registry: registry.example.com/team"),
                                        encoding="utf-8")
    fake = _Cli(verdict={("docker", "push"): 1})
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)
    monkeypatch.setattr(docker, "has_stored_login", lambda host: True)

    # act
    rc = image.release(name="app", tag="1.0")

    # assert
    assert rc == 1
    assert "gh auth refresh" not in capsys.readouterr().err


def test_the_scope_advice_on_a_failed_push_is_offered_as_a_condition_not_a_diagnosis(monkeypatch,
                                                                                     logins, capsys):
    # arrange: a push fails on a full disk and a dead network too, and a message that says the same thing
    # whatever happened says nothing at all
    fake = _Cli(verdict={("docker", "push"): 1})
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)

    # act
    image.release(name="app", tag="1.0")

    # assert
    err = capsys.readouterr().err
    assert "if the registry refused it rather than the network" in err
    assert "gh auth refresh" in err


def test_a_release_builds_nothing_of_its_own(cli, logins):
    # arrange: build and release are two of the five verbs and stay two commands, so a product that
    # builds an image for a smoke test is never one typo away from publishing it
    # act
    image.release(name="app", tag="1.0")

    # assert
    assert cli.argv_starting("docker", "build") == []


def test_a_missing_docker_kills_the_release_too(monkeypatch, capsys):
    # arrange
    monkeypatch.setattr(docker, "ensure_docker", _REAL_ENSURE_DOCKER)
    monkeypatch.setattr(docker.shutil, "which", lambda name: None)
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "0")

    # act / assert
    with pytest.raises(SystemExit) as exit_:
        image.release(name="app", tag="1.0")
    assert exit_.value.code == 1


# --- the registry probe -------------------------------------------------------------------------------

def test_the_probe_asks_oras_and_never_a_docker_client(monkeypatch):
    """The read-back is worth exactly its inability to answer from local state. `docker image inspect`
    answers about the daemon; `docker manifest inspect` answers out of `~/.docker/manifests/` - measured,
    it returned rc 0 for a `:cached` tag the registry did not have. oras keeps no such store."""
    # arrange
    fake = _Cli()
    monkeypatch.setattr(image, "run", fake.run)

    # act
    present = image.published("localhost:5000/probe:t1")

    # assert
    assert present is True
    assert fake.calls == [["oras", "manifest", "fetch", "--descriptor", "localhost:5000/probe:t1"]]
    assert [call for call in fake.calls if call[0] == "docker"] == []


def test_a_probe_that_cannot_answer_is_not_a_publish(monkeypatch):
    # arrange: no attempt to tell "the tag is missing" from "the registry could not be asked" - reading
    # the client's wording for that decision is parsing formatted text, and both readings mean the same
    # thing here
    fake = _Cli(verdict={("oras", "manifest", "fetch"): 1})
    monkeypatch.setattr(image, "run", fake.run)

    # act / assert
    assert image.published("ghcr.io/owner/demo-app:1.0") is False


def test_the_probe_provides_oras_rather_than_assuming_it(monkeypatch):
    # arrange: the gate INSTALLS oras where it can; a host where even that failed must not have the
    # missing binary surface as a FileNotFoundError out of subprocess
    fake = _Cli()
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(githubpackages, "require_oras",
                        lambda: (_ for _ in ()).throw(githubpackages.PackageError("no oras")))

    # act / assert
    with pytest.raises(githubpackages.PackageError):
        image.published("ghcr.io/owner/demo-app:1.0")
    assert fake.calls == []


def test_a_release_provisions_the_probes_tool_before_it_pushes_anything(cli, logins, monkeypatch,
                                                                        capsys):
    """An image in a registry that nobody can confirm is the worst of both: the push happened and the
    verdict is unavailable. So the gate runs first, and a host that cannot get oras never pushes."""
    # arrange
    monkeypatch.setattr(githubpackages, "require_oras",
                        lambda: (_ for _ in ()).throw(githubpackages.PackageError("no oras")))

    # act
    rc = image.release(name="app", tag="1.0")

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "push") == [] and logins == []
    assert "not attempted" in capsys.readouterr().err


def test_the_reference_is_joined_the_way_release_artifact_joins_its_own():
    # arrange: one product's image and its artifact cannot end up spelled differently
    cfg = image.Image(registry="ghcr.io/owner/", repository="/demo-app", dockerfile="Dockerfile",
                      context=".")

    # act / assert
    assert image.reference(cfg, "1.0") == "ghcr.io/owner/demo-app:1.0"


# --- si#274: rc 0 and no output is a third state ------------------------------------------------------

def test_a_toplevel_that_answers_nothing_is_told_apart_from_one_that_answers_elsewhere(tmp_path, capsys,
                                                                                       monkeypatch):
    """si#274, SEEN RED, and the red it replaces was invisible.

    `git rev-parse --show-toplevel` exiting 0 and printing nothing became `Path("")` - which **is**
    `PosixPath('.')` and resolves to the working directory - so the check below compared the cwd with the
    product root, found them different, and reported this tree as living inside somebody else's checkout.
    The message said so in as many words: *"the nearest one is ."*. Measured on a self-hosted runner on
    2026-09-16, where it made a green suite red once and passed on the re-run.

    The two states have to stay apart. "Your tree sits inside another checkout" is a real diagnosis a
    product can act on; "git said nothing" is a broken tool, and telling somebody to declare
    `build_args:` because of it would send them to fix the wrong thing.
    """
    # arrange: a real checkout, and a git whose --show-toplevel succeeds and says nothing
    root = _checkout(tmp_path / "product")
    real = image.run

    def mute(argv, **kwargs):
        if "--show-toplevel" in argv:
            return Result(rc=0, out="\n", err="")
        return real(argv, **kwargs)

    monkeypatch.setattr(image, "run", mute)

    # act
    derived = image.provenance(root)

    # assert: nothing derived, and the warning blames the tool rather than the tree
    warning = capsys.readouterr().out
    assert derived == {}
    assert "printed nothing" in warning, warning
    assert "si#274" in warning, warning
    assert "no git checkout of its own" not in warning, warning


def test_a_describe_that_answers_nothing_does_not_stamp_an_empty_version(tmp_path, capsys, monkeypatch):
    """The same third state one line down, and it had never been seen to fire - which is the reason to
    write it before it does. An empty `describe` would have stamped `VERSION=""` into the image: a label
    that is present, empty and wrong, which a reader cannot tell from a build that declined to say."""
    # arrange
    root = _checkout(tmp_path / "product")
    real = image.run

    def mute(argv, **kwargs):
        if "describe" in argv:
            return Result(rc=0, out="", err="")
        return real(argv, **kwargs)

    monkeypatch.setattr(image, "run", mute)

    # act
    derived = image.provenance(root)

    # assert
    warning = capsys.readouterr().out
    assert derived == {}, f"an empty version reached the build arguments: {derived}"
    assert "`describe`" in warning and "printed nothing" in warning, warning


def test_a_checkout_that_answers_normally_is_untouched_by_any_of_it(tmp_path):
    """The assurance the two refusals must not spend: an ordinary repository still derives both values."""
    # arrange
    root = _checkout(tmp_path / "product")

    # act
    derived = image.provenance(root)

    # assert
    assert derived["VERSION"] == "v1.2.3"
    assert len(derived["REVISION"]) == 40


@pytest.fixture
def _tagged(monkeypatch):
    """One resolved tag, so a smoke test is about the run rather than about tag derivation - which
    `resolve_tag` has its own tests for, and which has no git to derive from in a tmp_path."""
    monkeypatch.setattr(image, "resolve_tag", lambda cfg, tag, derived="": "1.2.3")

# --- test:image - running what the build produced (si#301, firn#110) ----------------------------------

def test_a_smoke_run_starts_the_reference_the_build_would_have_produced(cli, _no_provenance, _product,
                                                                        monkeypatch):
    """The three verbs name ONE reference. A smoke test that resolved its tag differently would be
    testing an image the build did not produce and the release will not publish - which is the failure
    `release` already guards against from the other side."""
    # arrange
    (_product / "fixture").mkdir()
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    monkeypatch.setattr(image, "resolve_tag", lambda cfg, tag, derived="": "1.2.3")

    # act
    rc = image.smoke("app", argv="check", mount="fixture:/workspace")

    # assert
    assert rc == 0
    started = cli.argv_starting("docker", "run")
    assert len(started) == 1
    assert "ghcr.io/owner/demo-app:1.2.3" in started[0]
    assert "check" == started[0][-1]
    assert f"{_product / 'fixture'}:/workspace" in started[0]


def test_a_smoke_run_names_and_labels_its_container_for_the_product(cli, _no_provenance, _product,
                                                                    _tagged, monkeypatch):
    # arrange: si#412 - firn's cleanup could find a `toolchain:run` container by label, not this one
    monkeypatch.setattr(image, "present_locally", lambda ref: True)

    # act
    image.smoke("app", argv="check")

    # assert
    lifecycle_name(cli.argv_starting("docker", "run")[0], "demo")


def test_an_interrupted_smoke_run_removes_the_container_it_named(_no_provenance, _product, _tagged,
                                                                  removals, monkeypatch):
    # arrange: the interrupt arrives while the client runs, as a Ctrl-C or a runner cancel does
    started: list = []

    def interrupted(argv, **kwargs):
        if argv[:2] == ["docker", "run"]:
            started.append(list(argv))
            raise KeyboardInterrupt
        return Result(rc=0, out="", err="")
    monkeypatch.setattr(image, "run", interrupted)
    monkeypatch.setattr(image, "present_locally", lambda ref: True)

    # act
    with pytest.raises(KeyboardInterrupt):
        image.smoke("app", argv="check")

    # assert: the container the line named is the one removed, and the interrupt still arrives
    assert removals == [lifecycle_name(started[0], "demo")]


def test_a_smoke_run_refuses_an_image_the_daemon_does_not_hold(cli, _no_provenance, _product, _tagged,
                                                               monkeypatch, capsys):
    """It runs what a build produced and never pulls, so a missing image is a refusal that names the
    verb which would produce it - not a silent `docker pull` of whatever the registry has."""
    # arrange
    (_product / "fixture").mkdir()
    monkeypatch.setattr(image, "present_locally", lambda ref: False)

    # act
    rc = image.smoke("app", argv="check", mount="fixture:/workspace")

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "run") == []
    assert "build image" in capsys.readouterr().err


def test_a_smoke_run_hands_back_the_containers_own_return_code(cli, _no_provenance, _product, _tagged,
                                                               monkeypatch):
    """The rc is the product's answer about its own image, so it travels rather than being flattened
    to 1: a gate that reports every failure as the same number is one nobody can triage."""
    # arrange
    (_product / "fixture").mkdir()
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    monkeypatch.setattr(image, "run", _Cli(verdict={("docker", "run"): 3}).run)

    # act
    rc = image.smoke("app", argv="check", mount="fixture:/workspace")

    # assert
    assert rc == 3


def test_a_smoke_run_refuses_output_that_does_not_say_what_was_expected(_no_provenance, _product,
                                                                        _tagged, monkeypatch, capsys):
    """An exit code of zero is the weaker half of the claim. A distroless image whose entrypoint is
    missing its model files can still exit 0 on `--help`, so a product may name what it must SAY."""
    # arrange
    (_product / "fixture").mkdir()
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    monkeypatch.setattr(image, "run", _Cli(output="something else entirely").run)

    # act
    rc = image.smoke("app", argv="check", mount="fixture:/workspace", expect="0 errors")

    # assert
    assert rc == 1
    assert "0 errors" in capsys.readouterr().err


def test_a_smoke_run_refuses_a_mount_that_is_not_a_directory_of_this_product(cli, _no_provenance,
                                                                            _product, _tagged,
                                                                            monkeypatch, capsys):
    """`_inside_the_product`'s rule, reaching the one task that would otherwise let a manifest mount
    a sibling checkout into a container: a path that leaves the product is refused before docker is
    asked, and a path that is simply not there is said as itself."""
    # arrange
    monkeypatch.setattr(image, "present_locally", lambda ref: True)

    # act
    rc = image.smoke("app", argv="check", mount="does-not-exist:/workspace")

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "run") == []


# --- si#303: `rc:` is an expectation, not a tolerance -------------------------------------------------


def test_an_expected_refusal_is_green(_no_provenance, _product, _tagged, monkeypatch):
    """THE STATEMENT si#303 ASKED FOR, and it could not be made at all: `rc != 0 is red` left a system
    level unable to say *the image REFUSES a broken input*, which is the other half of what it wants to
    say about a shipped artefact. The consumer who asked has had the fixture for months and could not
    use it."""
    (_product / "fixture").mkdir()
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    monkeypatch.setattr(image, "run", _Cli(verdict={("docker", "run"): 2}).run)

    assert image.smoke("app", argv="check", mount="fixture:/workspace", rc=2) == 0


def test_an_expected_refusal_that_does_not_happen_is_red(_no_provenance, _product, _tagged,
                                                         monkeypatch, capsys):
    """AN EXPECTATION AND NOT A TOLERANCE, which is the whole of why it takes a value. A tolerance widens
    what counts as green; an expectation moves it, so success where a refusal was demanded is a failure
    - and the image's own 0 must not be handed back as this task's verdict, or the failure would be
    reported as green."""
    (_product / "fixture").mkdir()
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    monkeypatch.setattr(image, "run", _Cli().run)          # the container exits 0

    rc = image.smoke("app", argv="check", mount="fixture:/workspace", rc=2)

    assert rc == 1, "a refusal that did not happen was reported with the container's own success"
    assert "2 was expected" in capsys.readouterr().err


def test_the_default_is_unchanged_and_says_nothing_about_an_expectation(_no_provenance, _product,
                                                                        _tagged, monkeypatch, capsys):
    """Every manifest written before si#303 keeps its meaning, and the message for the ordinary case
    does not grow a clause about an expectation nobody stated."""
    (_product / "fixture").mkdir()
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    monkeypatch.setattr(image, "run", _Cli(verdict={("docker", "run"): 3}).run)

    rc = image.smoke("app", argv="check", mount="fixture:/workspace")

    assert rc == 3
    assert "was expected" not in capsys.readouterr().err


def test_what_the_image_says_is_still_checked_when_a_refusal_was_expected(_no_provenance, _product,
                                                                          _tagged, monkeypatch, capsys):
    """The two halves compose: a product may demand that the image refuse AND that it say why. Without
    this the `expect` branch would only ever run for a zero exit, which is where it started."""
    (_product / "fixture").mkdir()
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    monkeypatch.setattr(image, "run", _Cli(verdict={("docker", "run"): 2},
                                           output="something else entirely").run)

    rc = image.smoke("app", argv="check", mount="fixture:/workspace", rc=2, expect="model is broken")

    assert rc == 1
    assert "model is broken" in capsys.readouterr().err


# --- si#344 C.3: a test writes its own result ---------------------------------------------------------

def test_a_smoke_run_writes_its_verdict_record_to_the_result_it_is_bound_to(cli, _no_provenance, _product,
                                                                           _tagged, monkeypatch):
    # arrange
    text = (_product / "demo.yaml").read_text(encoding="utf-8")
    (_product / "demo.yaml").write_text(
        text + "  app-checked: { kind: test-result, path: build/test/app.json }\n", encoding="utf-8")
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    cli.outputs[("docker", "image", "inspect", "--format")] = "sha256:aa\n"

    # act
    rc = image.smoke("app", argv="check", results="app-checked")

    # assert: si#439 - each run names the daemon id of what it ran, the subject a release compares
    assert rc == 0
    record = json.loads((_product / "build" / "test" / "app.json").read_text(encoding="utf-8"))
    assert record["image"] == "app"
    assert record["verdict"] == 0
    assert record["runs"] == [{"reference": "ghcr.io/owner/demo-app:1.2.3", "id": "sha256:aa", "platform": "",
                               "argv": "check", "expected_rc": 0, "rc": 0, "verdict": 0}]


def test_a_failing_smoke_run_still_writes_its_record_with_the_failure(cli, _no_provenance, _product, _tagged,
                                                                      monkeypatch):
    # arrange
    text = (_product / "demo.yaml").read_text(encoding="utf-8")
    (_product / "demo.yaml").write_text(
        text + "  app-checked: { kind: test-result, path: build/test/app.json }\n", encoding="utf-8")
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    cli.verdict[("docker", "run")] = 2

    # act
    rc = image.smoke("app", argv="check", results="app-checked")

    # assert
    assert rc == 2
    record = json.loads((_product / "build" / "test" / "app.json").read_text(encoding="utf-8"))
    assert record["verdict"] == 2


def test_a_smoke_run_refused_before_it_runs_leaves_no_earlier_record_behind(cli, _no_provenance, _product,
                                                                           _tagged, monkeypatch):
    # arrange: yesterday's green record, and an image the daemon does not hold today (final review, C.3)
    text = (_product / "demo.yaml").read_text(encoding="utf-8")
    (_product / "demo.yaml").write_text(
        text + "  app-checked: { kind: test-result, path: build/test/app.json }\n", encoding="utf-8")
    stale = _product / "build" / "test" / "app.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"image": "app", "verdict": 0, "runs": []}\n', encoding="utf-8")
    monkeypatch.setattr(image, "present_locally", lambda ref: False)

    # act
    rc = image.smoke("app", argv="check", results="app-checked")

    # assert
    assert rc == 1
    assert not stale.exists()


# --- the pointer a build leaves behind (si#314) --------------------------------------------------------

def test_a_build_records_what_it_produced_under_the_output_directory(cli, _no_provenance, _product,
                                                                     tmp_path):
    """si#314: a container image lives in a daemon, not in a directory, so the promise "everything this
    build produced is discoverable under one directory" can only be kept with a POINTER. It is the same
    shape as `deploy/image/image.pin`, and it is what a deployment redeems anyway - the alternative,
    `docker save`, is about a gigabyte of tarball per build written by something nobody reads."""
    # arrange: the daemon answers with the id of the image it just built
    cli.output = "sha256:abc123"

    # act
    rc = image.build(name="worker")

    # assert
    assert rc == 0
    record = tmp_path / "build" / "docker" / "image.txt"
    assert record.is_file()
    written = record.read_text(encoding="utf-8")
    assert "ghcr.io/owner/demo-worker:latest" in written
    # the local IMAGE ID, and it is labelled as that rather than as a digest: a freshly built image has
    # no registry digest at all - that one exists only once something has been pushed
    assert "sha256:abc123" in written


def test_the_record_follows_a_declared_output_root(cli, _no_provenance, _product, tmp_path):
    # arrange: a product that publishes out of another root takes the pointer with it
    manifest = (tmp_path / "demo.yaml")
    manifest.write_text("output: build-out\n" + manifest.read_text(encoding="utf-8"), encoding="utf-8")

    # act
    image.build(name="worker")

    # assert
    assert (tmp_path / "build-out" / "docker" / "image.txt").is_file()


def test_a_record_that_cannot_be_written_does_not_turn_a_real_image_red(cli, _no_provenance, _product,
                                                                       tmp_path, monkeypatch, capsys):
    """The image IS built, and reporting a built image as a failed build would be the opposite lie to the
    one this ticket is about. The write is reported instead - loudly, because a promise quietly not kept
    is the defect this repository hunts."""
    # arrange: the output directory cannot be created (the root-owned `build/` tasks/docs.py records)
    def _refuse(*_args, **_kwargs):
        raise PermissionError("Permission denied")
    monkeypatch.setattr(pathlib.Path, "mkdir", _refuse)

    # act
    rc = image.build(name="worker")

    # assert
    assert rc == 0
    assert "image.txt" in capsys.readouterr().out


# --- si#347: one image, several platforms, one manifest list -------------------------------------------
#
# firn publishes its image for linux/amd64 AND linux/arm64 from an x86_64 runner, and its Dockerfile starts
# `FROM` another image the same manifest declares and nobody publishes. Everything below is the argv the
# kernel hands buildx and the reading of what the registry answers; the end-to-end half was measured
# against a local `registry:2` and is recorded in the si#347 block of `simplon.tasks.image`.

_MULTI = """
  base:
    kind: image
    registry: ghcr.io/owner
    repository: demo-base
    dockerfile: docker/base.Dockerfile
    context: .
    tag: "25"
  multi:
    kind: image
    registry: ghcr.io/owner
    repository: demo-multi
    dockerfile: Dockerfile
    context: .
    platforms: [linux/amd64, linux/arm64]
    contexts: [base]
  single-on-base:
    kind: image
    registry: ghcr.io/owner
    repository: demo-single
    dockerfile: Dockerfile
    context: .
    contexts: [base]
"""

#: What `docker buildx ls --format json` prints for a bootstrapped builder that can run both - one JSON
#: object per line, the shape measured with buildx v0.38.0.
_BUILDER_BOTH = ('{"Name":"simplon","Driver":"docker-container","Nodes":[{"Name":"simplon0",'
                 '"Platforms":["linux/amd64","linux/amd64/v2","linux/arm64","linux/386"]}]}\n'
                 '{"Name":"default","Driver":"docker","Nodes":[{"Platforms":["linux/amd64"]}]}\n')
_BUILDER_AMD64_ONLY = ('{"Name":"simplon","Driver":"docker-container","Nodes":[{"Name":"simplon0",'
                       '"Platforms":["linux/amd64","linux/amd64/v2","linux/386"]}]}\n')

#: The index buildx pushed to a local registry:2 on 2026-10-10, trimmed to the fields that are read:
#: two platform manifests and the two attestation manifests buildx adds with `unknown/unknown`.
_INDEX_BOTH = """{"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
 {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "sha256:4e89", "platform": {"architecture": "amd64", "os": "linux"}},
 {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "sha256:f674", "platform": {"architecture": "arm64", "os": "linux"}},
 {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "sha256:7d37", "platform": {"architecture": "unknown", "os": "unknown"},
  "annotations": {"vnd.docker.reference.type": "attestation-manifest"}},
 {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "sha256:35fc", "platform": {"architecture": "unknown", "os": "unknown"},
  "annotations": {"vnd.docker.reference.type": "attestation-manifest"}}]}"""
_INDEX_AMD64_ONLY = """{"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
 {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "sha256:4e89", "platform": {"architecture": "amd64", "os": "linux"}}]}"""
_SINGLE_MANIFEST = """{"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
 "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": "sha256:aa"}, "layers": []}"""


@pytest.fixture
def _multi(_product):
    """The fixture manifest with three more images: a dependency with a constant tag, a two-platform image
    built FROM it, and a single-platform image built FROM it."""
    (_product / "demo.yaml").write_text(_MANIFEST + _MULTI.lstrip("\n"),
                                        encoding="utf-8")
    (_product / "docker" / "base.Dockerfile").write_text("FROM busybox:1.36\n", encoding="utf-8")
    return _product


#: The manifest digests bake reports per loaded platform - the same two the index fixtures carry, which is
#: what a warm push measured: the published children ARE the loaded images.
_LOADED = {"linux/amd64": "sha256:4e89", "linux/arm64": "sha256:f674"}


def _bake_reports(digests):
    """A bake that writes its `--metadata-file` the way buildx v0.38.0 does for `type=docker` targets."""
    def effect(argv):
        if "--metadata-file" not in argv:
            return
        targets = argv[argv.index("--metadata-file") + 2:]
        document = {target: {"containerimage.digest": digests[platform]}
                    for target in targets for platform in digests
                    if target == image.platform_target("multi", platform)}
        Path(argv[argv.index("--metadata-file") + 1]).write_text(json.dumps(document), encoding="utf-8")
    return effect


def _fake(monkeypatch, *, verdict=None, outputs=None, loaded=None) -> _Cli:
    fake = _Cli(verdict=verdict, outputs={("docker", "buildx", "ls"): _BUILDER_BOTH,
                                          ("docker", "version"): "linux/amd64",
                                          **(outputs or {})},
                effects={("docker", "buildx", "bake"): _bake_reports(loaded or _LOADED)})
    monkeypatch.setattr(image, "run", fake.run)
    monkeypatch.setattr(image, "stream", fake.stream)
    return fake


@pytest.fixture
def _recorded(_multi):
    """What a full `build image` of `multi:1.0` records, so a release test is about the release."""
    record = _multi / "build" / "docker" / "built-multi.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"reference": "ghcr.io/owner/demo-multi:1.0", "platforms": _LOADED}),
                      encoding="utf-8")
    return record


def _images(**entries: dict) -> dict:
    """A manifest document whose `artifacts:` holds `entries`, each of `kind: image` (si#344 B2)."""
    return {"artifacts": {name: {"kind": "image", **body} for name, body in entries.items()}}


def _body(**extra) -> dict:
    return {"registry": "ghcr.io/owner", "repository": "demo-app", "dockerfile": "Dockerfile",
            "context": ".", **extra}


# --- the declaration --------------------------------------------------------------------------------

def test_a_declared_platform_list_is_carried_in_order():
    # arrange
    data = _images(app=_body(platforms=["linux/amd64", "linux/arm64"]))

    # act
    cfg = image.declared(data, "app")

    # assert
    assert cfg.platforms == ("linux/amd64", "linux/arm64")


def test_an_image_without_platforms_declares_none():
    # arrange
    data = _images(app=_body())

    # act
    cfg = image.declared(data, "app")

    # assert
    assert (cfg.platforms, cfg.contexts) == ((), ())


@pytest.mark.parametrize("platforms,fragment", [
    ("linux/amd64", "'platforms' must be a list of non-empty strings"),
    (["amd64"], "is not '<os>/<arch>[/<variant>]'"),
    (["linux/arm/v7/extra"], "is not '<os>/<arch>[/<variant>]'"),
    ([7], "'platforms' must be a list of non-empty strings"),
])
def test_a_platform_list_that_buildx_would_refuse_is_refused_at_the_declaration(platforms, fragment):
    # arrange
    data = _images(app=_body(platforms=platforms))

    # act
    raised = pytest.raises(ValueError, match=re.escape(fragment))

    # assert
    with raised:
        image.declared(data, "app")


@pytest.mark.parametrize("platforms,expected", [
    ([], ()),
    (["linux/amd64", "linux/arm64", "linux/amd64"], ("linux/amd64", "linux/arm64")),
])
def test_a_restated_or_empty_platform_list_builds_rather_than_being_refused(platforms, expected):
    """Neither is broken: an empty list says what no key says, a repeated platform says it twice. Refusing
    either would forbid a manifest that builds, which is an expression rule nothing measured asks for."""
    # arrange
    data = _images(app=_body(platforms=platforms))

    # act
    cfg = image.declared(data, "app")

    # assert
    assert cfg.platforms == expected


def test_a_context_listed_twice_is_one_context():
    # arrange
    data = _images(app=_body(contexts=["base", "base"]), base=_body(tag="1"))

    # act
    cfg = image.declared(data, "app")

    # assert
    assert [name for name, _ in cfg.contexts] == ["base"]


def test_a_context_without_a_constant_tag_is_named_by_the_version_it_would_be_built_under():
    """A Dockerfile can name such a dependency with a global `ARG VERSION` before its FROM, and the kernel
    passes VERSION to both - so the context is named the way the dependency's own build would tag it."""
    # arrange
    data = _images(app=_body(contexts=["base"]), base=_body(repository="demo-base"))
    cfg = image.declared(data, "app")

    # act
    name = image.context_name(cfg.contexts[0][1], "v1.2.3")

    # assert
    assert name == "ghcr.io/owner/demo-base:v1.2.3"


def test_a_context_names_a_declared_image_and_carries_it_whole():
    # arrange
    data = _images(app=_body(platforms=["linux/amd64"], contexts=["base"]),
                   base=_body(repository="demo-base", dockerfile="base.Dockerfile", tag="25"))

    # act
    cfg = image.declared(data, "app")

    # assert: the name a Dockerfile's FROM uses is the dependency's OWN reference, derived, not retyped
    assert [name for name, _ in cfg.contexts] == ["base"]
    assert image.context_name(cfg.contexts[0][1]) == "ghcr.io/owner/demo-base:25"


@pytest.mark.parametrize("images,fragment", [
    ({"app": _body(contexts="base"), "base": _body(tag="1")}, "'contexts' must be a list of non-empty strings"),
    ({"app": _body(contexts=["nope"]), "base": _body(tag="1")}, "context 'nope' is not an image in the"),
    ({"app": _body(contexts=["app"], tag="1")}, "contexts form a cycle: app -> app"),
    ({"app": _body(contexts=["base"]), "base": _body(contexts=["app"], tag="1")},
     "contexts form a cycle: app -> base -> app"),
    ({"my.app": _body(platforms=["linux/amd64"])}, "cannot name a buildx bake target"),
    ({"app": _body(contexts=["my.base"]), "my.base": _body(tag="1")}, "cannot name a buildx bake target"),
])
def test_a_context_that_cannot_be_supplied_is_refused_by_name(images, fragment):
    # arrange
    data = _images(**images)
    name = next(iter(images))

    # act
    raised = pytest.raises(ValueError, match=fragment)

    # assert
    with raised:
        image.declared(data, name)


# --- si#343: a `kind: file` as a context ---------------------------------------------------------------

_FILE = {"kind": "file", "path": "build/dist/gradle.zip", "url": "https://e.org/g.zip", "sha256": "a" * 64}


def test_a_file_context_is_carried_beside_the_image_contexts_and_not_as_one():
    # arrange
    data = _images(app=_body(contexts=["base", "gradle-dist"]), base=_body(tag="1"))
    data["artifacts"]["gradle-dist"] = _FILE

    # act
    cfg = image.declared(data, "app")

    # assert
    assert [name for name, _ in cfg.contexts] == ["base"]
    assert cfg.files == (("gradle-dist", "build/dist/gradle.zip"),)


def test_a_file_context_without_a_path_is_refused_by_name():
    # arrange
    data = _images(app=_body(contexts=["gradle-dist"]))
    data["artifacts"]["gradle-dist"] = {k: v for k, v in _FILE.items() if k != "path"}

    # act / assert
    with pytest.raises(ValueError, match="context 'gradle-dist' is a `file` and declares no `path:`"):
        image.declared(data, "app")


def test_a_bake_target_is_handed_the_files_directory_under_the_entrys_name(tmp_path):
    # arrange
    data = _images(app=_body(platforms=["linux/amd64"], contexts=["gradle-dist"]))
    data["artifacts"]["gradle-dist"] = _FILE
    cfg = image.declared(data, "app")

    # act
    bake = image.bake_definition(cfg, "app", "ghcr.io/owner/demo-app:1", {}, tmp_path)

    # assert
    assert bake["target"]["app"]["contexts"] == {"gradle-dist": str(tmp_path / "build/dist")}


def _with_file_context(product):
    (product / "demo.yaml").write_text(_MANIFEST + f"""\
  tool:
    kind: image
    registry: ghcr.io/owner
    repository: demo-tool
    dockerfile: Dockerfile
    context: .
    contexts: [gradle-dist]
  gradle-dist: {{ kind: file, path: build/dist/gradle.zip, url: "https://e.org/g.zip", sha256: {"a" * 64} }}
""", encoding="utf-8")


def test_the_build_is_handed_the_fetched_files_directory_as_a_build_context(cli, _no_provenance, _product):
    # arrange
    _with_file_context(_product)
    (_product / "build/dist").mkdir(parents=True)
    (_product / "build/dist/gradle.zip").write_bytes(b"zip")

    # act
    image.build(name="tool", tag="1")

    # assert
    argv = cli.argv_starting("docker", "build")[0]
    assert argv[argv.index("--build-context") + 1] == f"gradle-dist={_product / 'build/dist'}"


def test_a_file_context_not_yet_fetched_is_named_before_docker_is_started(cli, _no_provenance, _product, capsys):
    # arrange
    _with_file_context(_product)

    # act
    rc = image.build(name="tool", tag="1")

    # assert: red, docker never asked, and the message says which step has not run
    assert rc == 1
    assert cli.argv_starting("docker", "build") == []
    assert "contexts: gradle-dist - no file at build/dist/gradle.zip; fetch it first, `build:fetch`" \
        in capsys.readouterr().err


def test_a_broken_dependency_is_refused_as_itself_and_not_as_its_dependent():
    # arrange: the dependency is missing a required key
    data = _images(app=_body(contexts=["base"]),
                   base={"registry": "ghcr.io/owner", "dockerfile": "D", "context": ".", "tag": "1"})

    # act
    raised = pytest.raises(ValueError, match=r"'artifacts\.base' declares no `repository:`")

    # assert
    with raised:
        image.declared(data, "app")


# --- build: unchanged without `platforms:` ----------------------------------------------------------

def test_an_image_without_platforms_builds_with_exactly_the_argv_it_had_before(cli, _no_provenance,
                                                                                _product):
    """si#347's third acceptance line, held as a literal: the whole argv, not a few members of it."""
    # arrange / act
    rc = image.build(name="worker")

    # assert
    assert rc == 0
    assert cli.argv_starting("docker", "build") == [[
        "docker", "build", "--file", str(_product / "docker/worker.Dockerfile"),
        "--tag", "ghcr.io/owner/demo-worker:latest",
        "--build-arg", "PYTHON_VERSION=3.12", "--build-arg", "SLIM=true",
        str(_product / "services/worker")]]
    assert cli.argv_starting("docker", "buildx") == []


def test_a_release_without_platforms_pushes_and_probes_exactly_as_before(cli, logins):
    # arrange / act
    rc = image.release(name="worker")

    # assert
    assert rc == 0
    assert cli.argv_starting("docker", "push") == [["docker", "push", "ghcr.io/owner/demo-worker:latest"]]
    assert cli.argv_starting("oras") == [["oras", "manifest", "fetch", "--descriptor",
                                          "ghcr.io/owner/demo-worker:latest"]]
    assert cli.argv_starting("docker", "buildx") == []


def test_a_single_platform_image_built_from_another_needs_that_one_built_first(monkeypatch, _no_provenance,
                                                                               _multi, capsys):
    """Without `platforms:` the build is the plain `docker build` it always was, and that resolves FROM in
    the daemon - so the dependency has to be there, and saying so beats docker's pull from a registry that
    never had it."""
    # arrange
    fake = _fake(monkeypatch, verdict={("docker", "image", "inspect", "ghcr.io/owner/demo-base:25"): 1})

    # act
    rc = image.build(name="single-on-base", tag="1.0")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "build") == []
    err = capsys.readouterr().err
    assert "ghcr.io/owner/demo-base:25" in err and "build:image" in err and "name: base" in err


def test_a_single_platform_image_whose_dependency_is_built_keeps_the_plain_argv(monkeypatch,
                                                                                _no_provenance, _multi):
    # arrange
    fake = _fake(monkeypatch)

    # act
    rc = image.build(name="single-on-base", tag="1.0")

    # assert
    assert rc == 0
    assert fake.argv_starting("docker", "build") == [[
        "docker", "build", "--file", str(_multi / "Dockerfile"), "--tag", "ghcr.io/owner/demo-single:1.0",
        str(_multi)]]


# --- build: with `platforms:` -----------------------------------------------------------------------

def test_a_multi_platform_build_bakes_one_target_per_platform_and_never_runs_docker_build(
        monkeypatch, _no_provenance, _multi):
    # arrange
    fake = _fake(monkeypatch)

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 0
    assert fake.argv_starting("docker", "build") == []
    bake = fake.argv_starting("docker", "buildx", "bake")
    assert bake == [["docker", "buildx", "bake", "--builder", "simplon", "--file",
                     str(_multi / "build" / "docker" / "bake-multi.json"),
                     "--metadata-file", str(_multi / "build" / "docker" / "bake-multi.metadata.json"),
                     "multi__linux_amd64", "multi__linux_arm64"]]


def test_the_bake_file_supplies_the_dependency_per_platform_and_pushes_only_the_image(monkeypatch,
                                                                                      _multi):
    """The dependency is a TARGET of the same bake, built for the dependent's platforms; it carries no tag
    and no output, so nothing ever publishes it - firn's toolchain is never pushed."""
    # arrange
    monkeypatch.setattr(image, "provenance", lambda root: {"VERSION": "v1", "REVISION": "abc"})
    _fake(monkeypatch)

    # act
    image.build(name="multi", tag="1.0")

    # assert
    bake = json.loads((_multi / "build" / "docker" / "bake-multi.json").read_text(encoding="utf-8"))
    targets = bake["target"]
    assert targets["base"] == {"context": str(_multi), "dockerfile": str(_multi / "docker/base.Dockerfile"),
                               "platforms": ["linux/amd64", "linux/arm64"],
                               "args": {"VERSION": "v1", "REVISION": "abc"}}
    assert targets["multi"]["platforms"] == ["linux/amd64", "linux/arm64"]
    assert targets["multi"]["tags"] == ["ghcr.io/owner/demo-multi:1.0"]
    assert targets["multi"]["output"] == ["type=registry"]
    assert targets["multi"]["contexts"] == {"ghcr.io/owner/demo-base:25": "target:base"}
    assert targets["multi__linux_arm64"]["platforms"] == ["linux/arm64"]
    assert targets["multi__linux_arm64"]["output"] == [
        "type=docker,name=ghcr.io/owner/demo-multi:1.0-linux-arm64"]
    assert "tags" not in targets["multi__linux_arm64"]
    assert targets["multi__linux_arm64"]["contexts"] == {"ghcr.io/owner/demo-base:25": "target:base"}


def test_the_hosts_own_platform_is_also_tagged_under_the_plain_reference(monkeypatch, _no_provenance,
                                                                         _multi):
    """So every command that runs the image by its reference - firn's system level does - keeps working
    on the host that built it."""
    # arrange
    fake = _fake(monkeypatch)

    # act
    image.build(name="multi", tag="1.0")

    # assert
    assert fake.argv_starting("docker", "tag") == [["docker", "tag", "ghcr.io/owner/demo-multi:1.0-linux-amd64",
                                                    "ghcr.io/owner/demo-multi:1.0"]]


def test_a_host_whose_platform_is_not_declared_tags_nothing_under_the_plain_reference(monkeypatch,
                                                                                    _no_provenance, _multi):
    # arrange
    fake = _fake(monkeypatch, outputs={("docker", "version"): "linux/riscv64"})

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 0
    assert fake.argv_starting("docker", "tag") == []


def test_a_missing_buildx_is_refused_naming_where_it_comes_from(monkeypatch, _no_provenance, _multi, capsys):
    """The static CLI `simplon.adapters.docker` bootstraps carries no plugins, so this is reachable on exactly the
    hosts that bootstrap exists for."""
    # arrange
    fake = _fake(monkeypatch, verdict={("docker", "buildx", "version"): 1})

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "buildx", "bake") == []
    err = capsys.readouterr().err
    assert "docker-buildx-plugin" in err and "docker/setup-buildx-action" in err


def test_a_builder_that_is_not_there_is_created_with_the_container_driver(monkeypatch, _no_provenance,
                                                                          _multi):
    # arrange
    fake = _fake(monkeypatch, verdict={("docker", "buildx", "inspect"): 1})

    # act
    image.build(name="multi", tag="1.0")

    # assert
    assert fake.argv_starting("docker", "buildx", "create") == [[
        "docker", "buildx", "create", "--name", "simplon", "--driver", "docker-container",
        "--driver-opt", "network=host", "--bootstrap"]]


def test_a_builder_that_is_there_is_used_as_it_is(monkeypatch, _no_provenance, _multi):
    # arrange
    fake = _fake(monkeypatch)

    # act
    image.build(name="multi", tag="1.0")

    # assert
    assert fake.argv_starting("docker", "buildx", "create") == []
    assert fake.argv_starting("docker", "buildx", "use") == []


def test_a_builder_that_cannot_be_created_is_red_before_anything_is_built(monkeypatch, _no_provenance,
                                                                          _multi, capsys):
    # arrange
    fake = _fake(monkeypatch, verdict={("docker", "buildx", "inspect"): 1, ("docker", "buildx", "create"): 1})

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "buildx", "bake") == []
    assert "docker buildx create" in capsys.readouterr().err


def test_a_platform_the_builder_cannot_run_is_warned_about_with_the_command_that_registers_it(
        monkeypatch, _no_provenance, _multi, capsys):
    """The decision on emulation: WARN and build, never register and never refuse. A Dockerfile that
    cross-compiles with `--platform=$BUILDPLATFORM` needs no emulator, so a refusal would forbid a working
    product; registering one is a privileged, host-wide act on a shared runner."""
    # arrange
    fake = _fake(monkeypatch, outputs={("docker", "buildx", "ls"): _BUILDER_AMD64_ONLY})

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 0
    assert fake.argv_starting("docker", "buildx", "bake")
    assert fake.argv_starting("docker", "run") == []          # nothing registered on the host's behalf
    out = capsys.readouterr()
    said = out.out + out.err
    assert "linux/arm64" in said
    assert "docker run --privileged --rm tonistiigi/binfmt:qemu-v10.2.3 --install arm64" in said


def test_a_failed_bake_names_the_emulation_command_when_a_platform_was_not_runnable(monkeypatch,
                                                                                 _no_provenance, _multi,
                                                                                 capsys):
    # arrange
    _fake(monkeypatch, verdict={("docker", "buildx", "bake"): 1},
          outputs={("docker", "buildx", "ls"): _BUILDER_AMD64_ONLY})

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 1
    err = capsys.readouterr().err
    assert "exec format error" in err and "--install arm64" in err


def test_a_failed_bake_says_nothing_about_emulation_when_every_platform_was_runnable(monkeypatch,
                                                                                  _no_provenance, _multi,
                                                                                  capsys):
    # arrange
    _fake(monkeypatch, verdict={("docker", "buildx", "bake"): 1})

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert "binfmt" not in capsys.readouterr().err


def test_a_bake_that_exits_zero_without_loading_a_platform_is_red(monkeypatch, _no_provenance, _multi,
                                                                  capsys):
    # arrange: the arm64 image never reached the daemon
    _fake(monkeypatch, verdict={("docker", "image", "inspect", "ghcr.io/owner/demo-multi:1.0-linux-arm64"): 1})

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert "ghcr.io/owner/demo-multi:1.0-linux-arm64" in capsys.readouterr().err


def test_a_multi_platform_build_checks_the_dependencys_paths_too(monkeypatch, _no_provenance, _multi,
                                                                capsys):
    # arrange
    (_multi / "docker" / "base.Dockerfile").unlink()
    fake = _fake(monkeypatch)

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "buildx", "bake") == []
    assert "dockerfile: docker/base.Dockerfile" in capsys.readouterr().err


def test_a_multi_platform_build_records_every_platform_it_loaded(monkeypatch, _no_provenance, _multi):
    # arrange
    _fake(monkeypatch)

    # act
    image.build(name="multi", tag="1.0")

    # assert
    record = (_multi / "build" / "docker" / "image.txt").read_text(encoding="utf-8")
    assert "reference: ghcr.io/owner/demo-multi:1.0" in record
    assert "linux/amd64: ghcr.io/owner/demo-multi:1.0-linux-amd64" in record
    assert "linux/arm64: ghcr.io/owner/demo-multi:1.0-linux-arm64" in record


# --- release: one manifest list, read back per platform -----------------------------------------------

@pytest.mark.parametrize("text,expected", [
    (_INDEX_BOTH, {"linux/amd64", "linux/arm64"}),
    (_INDEX_AMD64_ONLY, {"linux/amd64"}),
    ('{"mediaType": "application/vnd.docker.distribution.manifest.list.v2+json", "manifests": ['
     '{"platform": {"os": "linux", "architecture": "arm", "variant": "v7"}}]}', {"linux/arm/v7"}),
    (_SINGLE_MANIFEST, None),
    ("not json", None),
    ("", None),
    ('{"manifests": "nope"}', None),
])
def test_the_platforms_an_index_carries_are_read_and_attestations_are_not_platforms(text, expected):
    # arrange / act
    found = image.index_platforms(text)

    # assert
    assert found == expected


@pytest.mark.parametrize("declared,found,missing", [
    (("linux/amd64", "linux/arm64"), {"linux/amd64", "linux/arm64"}, []),
    (("linux/amd64", "linux/arm64"), {"linux/amd64"}, ["linux/arm64"]),
    (("linux/arm64",), {"linux/arm64/v8"}, []),
    (("linux/arm/v7",), {"linux/arm/v6"}, ["linux/arm/v7"]),
])
def test_a_declared_platform_is_matched_with_or_without_the_variant_the_registry_adds(declared, found,
                                                                                      missing):
    # arrange / act
    result = image.missing_platforms(declared, found)

    # assert
    assert result == missing


def test_a_multi_platform_release_bakes_the_push_and_reads_back_the_index(monkeypatch, logins,
                                                                          _no_provenance, _recorded, _multi):
    # arrange
    fake = _fake(monkeypatch, outputs={("oras", "manifest", "fetch"): _INDEX_BOTH})

    # act
    rc = image.release(name="multi", tag="1.0")

    # assert
    assert rc == 0
    assert logins == ["ghcr.io/owner"]
    assert fake.argv_starting("docker", "push") == []
    assert fake.argv_starting("docker", "buildx", "bake") == [[
        "docker", "buildx", "bake", "--builder", "simplon", "--file",
        str(_multi / "build" / "docker" / "bake-multi.json"), "multi"]]
    assert fake.argv_starting("oras") == [["oras", "manifest", "fetch", "ghcr.io/owner/demo-multi:1.0"]]


def test_a_pushed_index_missing_a_declared_platform_is_red_and_names_it(monkeypatch, logins,
                                                                        _no_provenance, _recorded, capsys):
    # arrange
    _fake(monkeypatch, outputs={("oras", "manifest", "fetch"): _INDEX_AMD64_ONLY})

    # act
    rc = image.release(name="multi", tag="1.0")

    # assert
    assert rc == 1
    err = capsys.readouterr().err
    assert "linux/arm64" in err and "linux/amd64" in err


def test_a_pushed_tag_that_is_a_single_manifest_is_not_a_multi_platform_publish(monkeypatch, logins,
                                                                                _no_provenance, _recorded,
                                                                                capsys):
    # arrange
    _fake(monkeypatch, outputs={("oras", "manifest", "fetch"): _SINGLE_MANIFEST})

    # act
    rc = image.release(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert "not a manifest list" in capsys.readouterr().err


def test_a_multi_platform_read_back_that_cannot_be_asked_is_red(monkeypatch, logins, _no_provenance, _recorded,
                                                                capsys):
    # arrange
    _fake(monkeypatch, verdict={("oras", "manifest", "fetch"): 1})

    # act
    rc = image.release(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert "could not be asked" in capsys.readouterr().err


def test_a_multi_platform_release_needs_every_platform_built_first(monkeypatch, logins, _no_provenance,
                                                                   _multi, capsys):
    # arrange
    fake = _fake(monkeypatch, verdict={("docker", "image", "inspect", "ghcr.io/owner/demo-multi:1.0-linux-arm64"): 1})

    # act
    rc = image.release(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert logins == [] and fake.argv_starting("docker", "buildx", "bake") == []
    err = capsys.readouterr().err
    assert "linux/arm64" in err and "`build image` WITHOUT `platform:`" in err


def test_a_failed_multi_platform_push_hands_back_its_rc_and_reads_nothing_back(monkeypatch, logins,
                                                                              _no_provenance, _recorded):
    # arrange
    fake = _fake(monkeypatch, verdict={("docker", "buildx", "bake"): 3})

    # act
    rc = image.release(name="multi", tag="1.0")

    # assert
    assert rc == 3
    assert fake.argv_starting("oras") == []


def test_a_multi_platform_release_puts_no_credential_on_any_argv(monkeypatch, logins, _no_provenance,
                                                                 _recorded):
    # arrange
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret_value")
    fake = _fake(monkeypatch, outputs={("oras", "manifest", "fetch"): _INDEX_BOTH})

    # act
    image.release(name="multi", tag="1.0")

    # assert
    assert not any("ghp_secret_value" in " ".join(call) for call in fake.calls)


# --- smoke: every platform has started once -----------------------------------------------------------

def test_a_multi_platform_smoke_runs_every_declared_platform_under_its_own_platform(monkeypatch,
                                                                                   _no_provenance, _multi):
    # arrange
    fake = _fake(monkeypatch)

    # act
    rc = image.smoke("multi", tag="1.0", argv="--version", user=False)

    # assert
    assert rc == 0
    assert [without_lifecycle(each) for each in fake.argv_starting("docker", "run")] == [
        ["docker", "run", "--rm", "--platform", "linux/amd64", "ghcr.io/owner/demo-multi:1.0-linux-amd64",
         "--version"],
        ["docker", "run", "--rm", "--platform", "linux/arm64", "ghcr.io/owner/demo-multi:1.0-linux-arm64",
         "--version"]]


def test_a_smoke_pinned_to_one_platform_runs_only_that_one(monkeypatch, _no_provenance, _multi):
    # arrange
    fake = _fake(monkeypatch)

    # act
    rc = image.smoke("multi", tag="1.0", argv="--version", user=False, platform="linux/arm64")

    # assert
    assert rc == 0
    assert [without_lifecycle(call)[4] for call in fake.argv_starting("docker", "run")] == ["linux/arm64"]


def test_a_smoke_pinned_to_an_undeclared_platform_is_refused(monkeypatch, _no_provenance, _multi, capsys):
    # arrange
    fake = _fake(monkeypatch)

    # act
    rc = image.smoke("multi", tag="1.0", platform="linux/s390x")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "run") == []
    assert "linux/amd64, linux/arm64" in capsys.readouterr().err


def test_a_smoke_pinned_to_a_platform_on_a_single_platform_image_is_refused(cli, _no_provenance, _product,
                                                                           _tagged, monkeypatch, capsys):
    # arrange
    monkeypatch.setattr(image, "present_locally", lambda ref: True)

    # act
    rc = image.smoke("app", platform="linux/arm64")

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "run") == []
    assert "platforms:" in capsys.readouterr().err


def test_a_multi_platform_smoke_reports_the_platform_that_failed(monkeypatch, _no_provenance, _multi,
                                                                 capsys):
    # arrange: arm64 exits 126, the shape of a missing emulator
    fake = _fake(monkeypatch, verdict={("docker", "run", "--rm", "--platform", "linux/arm64"): 126})

    # act
    rc = image.smoke("multi", tag="1.0", user=False)

    # assert: both ran - one platform's failure does not hide whether the other started
    assert rc == 126
    assert len(fake.argv_starting("docker", "run")) == 2
    assert "ghcr.io/owner/demo-multi:1.0-linux-arm64 exited 126" in capsys.readouterr().err


def test_a_multi_platform_smoke_refuses_a_platform_the_daemon_does_not_hold(monkeypatch, _no_provenance,
                                                                            _multi, capsys):
    # arrange
    fake = _fake(monkeypatch, verdict={("docker", "image", "inspect", "ghcr.io/owner/demo-multi:1.0-linux-arm64"): 1})

    # act
    rc = image.smoke("multi", tag="1.0", user=False)

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "run") == []
    assert "build image" in capsys.readouterr().err


# --- fix round 1: one platform on demand, the push held against the build, the builder race -------------

def test_a_build_pinned_to_one_platform_bakes_only_that_platform(monkeypatch, _no_provenance, _multi):
    """The everyday build: firn's CI and devcontainer pin `platform: linux/amd64`, so adopting `platforms:`
    does not turn every `build image` into an emulated arm64 native-image compile."""
    # arrange
    fake = _fake(monkeypatch)

    # act
    rc = image.build(name="multi", tag="1.0", platform="linux/amd64")

    # assert
    assert rc == 0
    assert fake.argv_starting("docker", "buildx", "bake")[0][-1:] == ["multi__linux_amd64"]
    assert fake.argv_starting("docker", "tag") == [["docker", "tag", "ghcr.io/owner/demo-multi:1.0-linux-amd64",
                                                    "ghcr.io/owner/demo-multi:1.0"]]
    inspected = [call[-1] for call in fake.argv_starting("docker", "image", "inspect") if len(call) == 4]
    assert "ghcr.io/owner/demo-multi:1.0-linux-arm64" not in inspected


def _baked(root):
    return json.loads((root / "build" / "docker" / "bake-multi.json").read_text(encoding="utf-8"))["target"]


def test_a_build_pinned_to_one_platform_bakes_every_target_including_contexts_for_that_platform_only(
        monkeypatch, _no_provenance, _multi):
    """si#355: the dependency used to be baked for each declared platform, so a cold amd64-only build
    needed an arm64 emulator for a stage nobody asked for."""
    # arrange
    _fake(monkeypatch)

    # act
    image.build(name="multi", tag="1.0", platform="linux/amd64")

    # assert
    targets = _baked(_multi)
    assert {key: body["platforms"] for key, body in targets.items()} == {
        "base": ["linux/amd64"], "multi": ["linux/amd64"], "multi__linux_amd64": ["linux/amd64"]}


def test_a_build_without_platform_still_bakes_every_declared_platform_for_every_target(
        monkeypatch, _no_provenance, _multi):
    # arrange
    _fake(monkeypatch)

    # act
    image.build(name="multi", tag="1.0")

    # assert
    both = ["linux/amd64", "linux/arm64"]
    targets = _baked(_multi)
    assert {key: body["platforms"] for key, body in targets.items()} == {
        "base": both, "multi": both, "multi__linux_amd64": ["linux/amd64"], "multi__linux_arm64": ["linux/arm64"]}


def test_the_host_log_line_says_the_platform_is_declared_when_it_is_only_not_the_one_built(
        monkeypatch, _no_provenance, _multi, capsys):
    # arrange
    _fake(monkeypatch)

    # act
    image.build(name="multi", tag="1.0", platform="linux/arm64")

    # assert
    out = capsys.readouterr()
    text = out.out + out.err
    assert "is not among the platforms built here (linux/arm64)" in text
    assert "not among the declared platforms" not in text


def test_a_build_pinned_to_a_platform_that_is_not_the_hosts_tags_nothing_plain(monkeypatch, _no_provenance,
                                                                             _multi):
    # arrange
    fake = _fake(monkeypatch)

    # act
    rc = image.build(name="multi", tag="1.0", platform="linux/arm64")

    # assert
    assert rc == 0
    assert fake.argv_starting("docker", "buildx", "bake")[0][-1:] == ["multi__linux_arm64"]
    assert fake.argv_starting("docker", "tag") == []


def test_a_build_pinned_to_an_undeclared_platform_is_refused_naming_the_declared_ones(monkeypatch,
                                                                                   _no_provenance, _multi,
                                                                                   capsys):
    # arrange
    fake = _fake(monkeypatch)

    # act
    rc = image.build(name="multi", tag="1.0", platform="linux/s390x")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "buildx") == []
    assert "linux/amd64, linux/arm64" in capsys.readouterr().err


def test_a_build_pinned_to_a_platform_on_a_single_platform_image_is_refused(cli, _no_provenance, _product,
                                                                           capsys):
    # arrange / act
    rc = image.build(name="app", tag="1.0", platform="linux/arm64")

    # assert
    assert rc == 1
    assert cli.argv_starting("docker", "build") == []
    assert "declares no `platforms:`" in capsys.readouterr().err


def test_a_build_records_the_digest_bake_reported_for_each_platform(monkeypatch, _no_provenance, _multi):
    # arrange
    _fake(monkeypatch)

    # act
    image.build(name="multi", tag="1.0")

    # assert
    assert image.read_built("multi", "ghcr.io/owner/demo-multi:1.0") == _LOADED


def test_a_one_platform_build_replaces_its_own_entry_and_keeps_the_others(monkeypatch, _no_provenance,
                                                                         _recorded):
    # arrange
    _fake(monkeypatch, loaded={"linux/amd64": "sha256:new0", "linux/arm64": "sha256:f674"})

    # act
    image.build(name="multi", tag="1.0", platform="linux/amd64")

    # assert
    assert image.read_built("multi", "ghcr.io/owner/demo-multi:1.0") == {"linux/amd64": "sha256:new0",
                                                                         "linux/arm64": "sha256:f674"}


def test_a_record_about_another_reference_is_no_record(_recorded):
    # arrange / act
    found = image.read_built("multi", "ghcr.io/owner/demo-multi:2.0")

    # assert
    assert found == {}


def test_bakes_metadata_is_read_per_platform_target():
    # arrange
    text = json.dumps({"multi__linux_amd64": {"containerimage.digest": "sha256:aa"},
                       "multi__linux_arm64": {"buildx.build.ref": "x"}})

    # act
    digests = image.built_digests(text, "multi", ["linux/amd64", "linux/arm64"])

    # assert
    assert digests == {"linux/amd64": "sha256:aa"}


def test_a_release_with_no_record_of_the_build_is_refused_before_anything_is_pushed(monkeypatch, logins,
                                                                                   _no_provenance, _multi,
                                                                                   capsys):
    # arrange: the images are in the daemon, but nothing says what the build produced
    fake = _fake(monkeypatch, outputs={("oras", "manifest", "fetch"): _INDEX_BOTH})

    # act
    rc = image.release(name="multi", tag="1.0")

    # assert
    assert rc == 1
    assert fake.argv_starting("docker", "buildx", "bake") == []
    assert "`build image` WITHOUT `platform:`" in capsys.readouterr().err


def test_a_push_that_published_other_images_than_the_build_loaded_is_red_and_names_them(monkeypatch, logins,
                                                                                     _no_provenance,
                                                                                     _recorded, capsys):
    """The cold-cache case: the push rebuilt arm64, so the registry serves an image `test:image` never ran."""
    # arrange
    rebuilt = _INDEX_BOTH.replace("sha256:f674", "sha256:cold")
    _fake(monkeypatch, outputs={("oras", "manifest", "fetch"): rebuilt})

    # act
    rc = image.release(name="multi", tag="1.0")

    # assert
    assert rc == 1
    err = capsys.readouterr().err
    assert "linux/arm64: the registry holds sha256:cold, the build loaded sha256:f674" in err
    assert "linux/amd64:" not in err


@pytest.mark.parametrize("published,built,expected", [
    ({"linux/amd64": "sha256:a", "linux/arm64": "sha256:b"}, {"linux/amd64": "sha256:a", "linux/arm64": "sha256:b"}, 0),
    ({"linux/amd64": "sha256:a", "linux/arm64/v8": "sha256:b"}, {"linux/amd64": "sha256:a", "linux/arm64": "sha256:b"}, 0),
    ({"linux/amd64": "sha256:a", "linux/arm64": "sha256:x"}, {"linux/amd64": "sha256:a", "linux/arm64": "sha256:b"}, 1),
    ({"linux/amd64": "sha256:a"}, {"linux/amd64": "sha256:a", "linux/arm64": "sha256:b"}, 1),
])
def test_published_digests_are_held_against_the_built_ones_per_platform(published, built, expected):
    # arrange / act
    lines = image.digest_mismatches(("linux/amd64", "linux/arm64"), published, built)

    # assert
    assert len(lines) == expected


def test_a_builder_created_meanwhile_by_another_run_is_used_rather_than_failing(monkeypatch, _no_provenance,
                                                                              _multi):
    """Two jobs on one daemon both find no builder; the one whose `create` loses sees it exist afterwards."""
    # arrange: the first inspect finds nothing, the create loses the race, the second inspect finds it
    fake = _fake(monkeypatch, verdict={("docker", "buildx", "create"): 1})
    answers = iter([1, 0])
    plain = fake.run

    def run(argv, **kwargs):
        if tuple(argv[:3]) == ("docker", "buildx", "inspect"):
            fake.calls.append(list(argv))
            return Result(rc=next(answers), out="", err="")
        return plain(argv, **kwargs)
    monkeypatch.setattr(image, "run", run)

    # act
    rc = image.build(name="multi", tag="1.0")

    # assert
    assert rc == 0
    assert len(fake.argv_starting("docker", "buildx", "inspect")) == 2
    assert fake.argv_starting("docker", "buildx", "bake")


# --- an image is an `artifacts:` entry of `kind: image` (si#344 B2) -----------------------------------

def test_an_entry_of_another_kind_is_not_an_image(tmp_path):
    # arrange
    data = {"artifacts": {"site": {"kind": "directory", "path": "build/site"}}}

    # act
    with pytest.raises(ValueError) as caught:
        image.declared(data, "site")

    # assert
    assert str(caught.value) == (
        "manifest: 'artifacts.site' is of kind 'directory', and this task reads a 'image' or a kind that "
        "refines it - name an entry of that kind, or change the entry's `kind:`")


def test_a_missing_image_lists_only_the_images():
    # arrange
    data = {"artifacts": {"site": {"kind": "directory"}, **_images(app=_body())["artifacts"]}}

    # act
    with pytest.raises(ValueError) as caught:
        image.declared(data, "nope")

    # assert
    assert str(caught.value) == "manifest: no image 'nope' in the 'artifacts:' section; declared are: app"


def test_a_local_image_declares_nothing_a_build_needs_and_says_which_key_first():
    # arrange: netctl's shape - a reference no kernel task builds
    data = _images(web={"local": "netctl:local"})

    # act
    with pytest.raises(ValueError) as caught:
        image.declared(data, "web")

    # assert
    assert str(caught.value) == ("manifest: 'artifacts.web' declares no `registry:`, which build:image needs - "
                                 "it reads registry, repository, dockerfile, context")


def test_a_number_tag_builds_under_its_string(tmp_path):
    # arrange: decision A - `tag: 25` loads and is the tag (image._str refused it before si#344 B2)
    data = _images(app={**_body(), "tag": 25})

    # act
    cfg = image.declared(data, "app")

    # assert
    assert cfg.tag == "25"


def test_a_release_logs_in_and_publishes_inside_a_docker_config_that_ends_with_it(cli, monkeypatch, tmp_path):
    # arrange: si#443 - the job's token in the runner's own config expires and denies later public pulls
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "operator"))
    seen: list = []
    monkeypatch.setattr(githubpackages, "docker_login",
                        lambda registry, **kw: seen.append(("login", os.environ["DOCKER_CONFIG"])))
    asked = image.published
    monkeypatch.setattr(image, "published",
                        lambda ref: seen.append(("verify", os.environ["DOCKER_CONFIG"])) or asked(ref))

    # act
    rc = image.release(name="app", tag="1.0")

    # assert: login and read-back shared one scope, and it was not the operator's config
    assert rc == 0
    assert [what for what, _ in seen] == ["login", "verify"]
    assert seen[0][1] == seen[1][1] != str(tmp_path / "operator")
    assert os.environ["DOCKER_CONFIG"] == str(tmp_path / "operator")
