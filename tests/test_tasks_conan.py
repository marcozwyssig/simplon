"""`release:conan` and `build:conan-cache` - a Conan package as an OCI artifact (si#128).

A TRANSPORT, NOT A REMOTE, and these tests are written so that nothing here could be mistaken for one:
nothing resolves a graph, nothing understands a version range, and the archive is moved as the opaque
file `conan cache save` wrote. The one thing that would break a consumer silently - re-wrapping the
`.tgz` in a `.zip`, which is what `release:artifact`'s directory path does - has an assertion of its own.

AAA throughout; nothing pushes anything.
"""
import pytest

from simplon import context, githubpackages
from simplon.context import ProductContext
from simplon.tasks import conan

_MANIFEST = """
product: demo
artifacts:
  cpplib:
    registry: ghcr.io/marcozwyssig
    repository: demo-conan
    source: build/conan/demo.tgz
    media_type: application/vnd.conan.cache.v1+tgz
    tag: 1.0.0
  untagged:
    registry: ghcr.io/marcozwyssig
    repository: demo-conan
    source: build/conan/demo.tgz
    media_type: application/vnd.conan.cache.v1+tgz
  elsewhere:
    registry: registry.example.com/team
    repository: demo-conan
    source: build/conan/demo.tgz
    media_type: application/vnd.conan.cache.v1+tgz
    tag: 1.0.0
  nomedia:
    registry: ghcr.io/marcozwyssig
    repository: demo-conan
    source: build/conan/demo.tgz
    tag: 1.0.0
groups: {}
env_groups: []
"""


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    archive = tmp_path / "build" / "conan" / "demo.tgz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"not really a tarball")
    return tmp_path


@pytest.fixture
def pushed(monkeypatch):
    calls: list = []
    monkeypatch.setattr(githubpackages, "login", lambda registry, **kw: calls.append(("login", registry)))
    monkeypatch.setattr(githubpackages, "push",
                        lambda ref, path, media: calls.append(("push", ref, str(path), media)))
    monkeypatch.setattr(githubpackages, "push_directory",
                        lambda *a, **kw: pytest.fail("a .tgz was wrapped in a .zip"))
    return calls


@pytest.fixture
def pulled(monkeypatch):
    calls: list = []
    monkeypatch.setattr(githubpackages, "login", lambda registry, **kw: calls.append(("login", registry)))

    def _pull(ref, destination):
        calls.append(("pull", ref, str(destination)))
        (context.current().root / "build" / "conan" / "demo.tgz").write_bytes(b"pulled")

    monkeypatch.setattr(githubpackages, "pull", _pull)
    return calls


# --- publishing ---------------------------------------------------------------------------------------

def test_the_archive_is_pushed_as_a_file_under_the_tag_it_was_given(pushed, _product):
    # act
    rc = conan.publish(name="cpplib", tag="2.1.0")

    # assert
    assert rc == 0
    assert ("push", "ghcr.io/marcozwyssig/demo-conan:2.1.0",
            str(_product / "build" / "conan" / "demo.tgz"),
            "application/vnd.conan.cache.v1+tgz") in pushed


def test_the_archive_is_never_zipped_on_the_way_out(pushed):
    """`release:artifact` publishes a DIRECTORY and zips it; a `.tgz` put through that path arrives as a
    `.zip` holding a `.tgz`, and `conan cache restore` is then handed the wrong file. The fixture fails
    the test if `push_directory` is reached at all."""
    conan.publish(name="cpplib")

    assert [call[0] for call in pushed] == ["login", "push"]


def test_a_tag_declared_in_the_manifest_needs_no_argument(pushed):
    conan.publish(name="cpplib")

    assert pushed[1][1].endswith(":1.0.0")


def test_without_a_tag_anywhere_it_names_both_places_one_could_be(pushed):
    with pytest.raises(ValueError, match="--tag"):
        conan.publish(name="untagged")


def test_a_missing_key_is_named(pushed):
    with pytest.raises(ValueError, match="media_type"):
        conan.publish(name="nomedia")


def test_an_undeclared_artefact_lists_the_ones_that_are(pushed):
    with pytest.raises(ValueError, match="cpplib"):
        conan.publish(name="nope", tag="1")


def test_an_archive_that_is_not_there_says_which_command_writes_one(pushed, _product):
    """The kernel does not run conan, so the message has to name the command that produces the file -
    otherwise 'nothing to publish' reads as a defect in this task."""
    (_product / "build" / "conan" / "demo.tgz").unlink()

    with pytest.raises(ValueError, match="conan cache save"):
        conan.publish(name="cpplib")


def test_a_registry_that_is_not_githubs_is_not_logged_into_with_a_github_token(pushed, capsys):
    """image.py's rule, kept here: a GitHub token goes to GitHub and nowhere else, and the push then
    uses whatever credential the operator's own `oras login` stored."""
    conan.publish(name="elsewhere")

    assert [call[0] for call in pushed] == ["push"]
    assert "registry.example.com" in capsys.readouterr().out


# --- fetching -----------------------------------------------------------------------------------------

def test_the_archive_is_pulled_back_beside_where_the_product_expects_it(pulled, _product):
    # act
    rc = conan.fetch(name="cpplib", tag="2.1.0")

    # assert
    assert rc == 0
    assert ("pull", "ghcr.io/marcozwyssig/demo-conan:2.1.0",
            str(_product / "build" / "conan")) in pulled


def test_the_fetch_says_the_path_the_next_command_needs(pulled, _product, capsys):
    """The next thing the operator types is `conan cache restore <path>`, so the path is the output that
    matters - a success line saying only 'pulled' would leave them to guess it."""
    conan.fetch(name="cpplib")

    assert "build/conan/demo.tgz" in capsys.readouterr().out


def test_the_fetch_refuses_when_the_pull_left_nothing_where_it_said(pulled, monkeypatch, _product):
    """A pull that reports success and leaves no file is the defect this repository has shipped twice
    (allure.render_report, hugo on an empty tree). The file is looked for rather than assumed."""
    monkeypatch.setattr(githubpackages, "pull", lambda ref, destination: None)
    (_product / "build" / "conan" / "demo.tgz").unlink()

    with pytest.raises(RuntimeError, match="demo.tgz"):
        conan.fetch(name="cpplib")


def test_the_fetch_needs_a_tag_too(pulled):
    with pytest.raises(ValueError, match="--tag"):
        conan.fetch(name="untagged")
