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
import shutil
import subprocess
from pathlib import Path

import pytest

from simplon import context, docker, githubpackages
from simplon.context import ProductContext
from simplon.run import Result
from simplon.tasks import image

#: The real gate, captured before the autouse fixture below neutralises it - the two tests that assert
#: it DIES need the actual body, and reaching for it through the patched module would find the stub.
_REAL_ENSURE_DOCKER = docker.ensure_docker

_MANIFEST = """
product: demo
images:
  app:
    registry: ghcr.io/owner
    repository: demo-app
    dockerfile: Dockerfile
    context: .
  worker:
    registry: ghcr.io/owner
    repository: demo-worker
    dockerfile: docker/worker.Dockerfile
    context: services/worker
    tag: latest
    build_args:
      PYTHON_VERSION: "3.12"
      SLIM: true
groups: {}
env_groups: []
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

    def __init__(self, verdict=None, output=""):
        self.calls: list = []
        self.verdict = verdict or {}
        self.output = output

    def _rc(self, argv) -> int:
        for prefix, rc in self.verdict.items():
            if tuple(argv[:len(prefix)]) == tuple(prefix):
                return rc
        return 0

    def run(self, argv, **kwargs) -> Result:
        self.calls.append(list(argv))
        return Result(rc=self._rc(argv), out=self.output, err="")

    def stream(self, argv, **kwargs) -> int:
        self.calls.append(list(argv))
        return self._rc(argv)

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
    data = {"images": {"app": {"registry": "ghcr.io/owner", "repository": "demo-app",
                               "dockerfile": "Dockerfile", "context": "."}}}

    # act
    cfg = image.declared(data, "app")

    # assert
    assert (cfg.registry, cfg.repository) == ("ghcr.io/owner", "demo-app")
    assert (cfg.dockerfile, cfg.context) == ("Dockerfile", ".")


def test_an_undeclared_image_lists_the_ones_that_are():
    # arrange
    data = {"images": {"app": {}, "worker": {}}}

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
    with pytest.raises(ValueError, match=f"'{missing}' is required"):
        image.declared({"images": {"app": body}}, "app")


def test_a_registry_is_required_even_for_a_purely_local_build():
    """An unqualified name is what docker resolves against Docker Hub, so a build tagged without a
    registry and a release pushing it are two different images (simplon.imagenames.require_registry records
    that failure in full). The build has to tag what the release will push."""
    # arrange
    body = {"repository": "demo-app", "dockerfile": "Dockerfile", "context": "."}

    # act / assert
    with pytest.raises(ValueError, match="'registry' is required"):
        image.declared({"images": {"app": body}}, "app")


@pytest.mark.parametrize("key,value", [("context", "/srv"), ("context", "../elsewhere"),
                                       ("dockerfile", "/etc/Dockerfile"), ("dockerfile", "../D")])
def test_a_path_that_leaves_the_product_root_is_refused_before_docker_sees_it(key, value):
    # arrange: `context: /` would stream the whole filesystem to the daemon as a build context
    body = {"registry": "ghcr.io/owner", "repository": "demo-app",
            "dockerfile": "Dockerfile", "context": "."}
    body[key] = value

    # act / assert
    with pytest.raises(ValueError, match="relative"):
        image.declared({"images": {"app": body}}, "app")


def test_a_context_of_dot_is_accepted_and_means_the_product_root():
    """The shared path rule refuses a bare '.' for its other callers (they scaffold into the path or hand
    it to rmtree); naming the product root is normal and unambiguous for a build context."""
    # arrange
    body = {"registry": "ghcr.io/owner", "repository": "demo-app",
            "dockerfile": "Dockerfile", "context": "./"}

    # act
    cfg = image.declared({"images": {"app": body}}, "app")

    # assert
    assert cfg.context == "."


def test_declared_build_arguments_are_carried_as_strings():
    # arrange: a manifest is YAML, so `SLIM: true` arrives as a bool and docker only speaks text
    data = {"images": {"app": {"registry": "ghcr.io/o", "repository": "r", "dockerfile": "Dockerfile",
                               "context": ".", "build_args": {"PYTHON_VERSION": "3.12", "SLIM": True,
                                                              "RETRIES": 3}}}}

    # act
    cfg = image.declared(data, "app")

    # assert
    assert cfg.build_args == {"PYTHON_VERSION": "3.12", "SLIM": "true", "RETRIES": "3"}


def test_a_build_argument_that_is_not_a_scalar_is_refused():
    # arrange: a list would reach docker as its repr, which is a value nobody wrote
    data = {"images": {"app": {"registry": "ghcr.io/o", "repository": "r", "dockerfile": "Dockerfile",
                               "context": ".", "build_args": {"PORTS": [80, 443]}}}}

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
    data = image.declared({"images": {"app": {"registry": "ghcr.io/owner", "repository": "demo-app",
                                              "dockerfile": "Dockerfile", "context": ".",
                                              "build_args": {"VERSION": "4.2.0"}}}}, "app")

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
    # arrange
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
