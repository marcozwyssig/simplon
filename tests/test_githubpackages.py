"""Moving a file in and out of a GitHub Packages registry.

Arrange / Act / Assert throughout, one action per test. The subprocess seam is stubbed rather than
mocked at the library boundary: what is under test is what this module DECIDES - which argv, which
message - not whether oras works.
"""
from pathlib import Path

import pytest

from simplon import githubpackages, run


class _Result:
    def __init__(self, rc=0, out="", err=""):
        self.rc, self.out, self.err = rc, out, err


@pytest.fixture
def calls(monkeypatch):
    """Records every subprocess this module would have run."""
    recorded = []

    def fake_run(argv, **kwargs):
        recorded.append((argv, kwargs))
        return _Result(rc=0, out="v1 v2")

    def fake_stream(argv, **kwargs):
        recorded.append((argv, kwargs))
        return 0

    monkeypatch.setattr(run, "run", fake_run)
    monkeypatch.setattr(run, "stream", fake_stream)
    monkeypatch.setattr(githubpackages, "require_oras", lambda: None)
    return recorded


# --- references -------------------------------------------------------------------------------------

def test_a_reference_has_exactly_one_slash_between_its_parts():
    registry, repository, tag = "ghcr.io/owner/", "/repo", "1.0-linux-x86_64"

    result = githubpackages.reference(registry, repository, tag)

    assert result == "ghcr.io/owner/repo:1.0-linux-x86_64"


def test_the_login_host_is_the_registry_without_its_owner():
    registry = "ghcr.io/marcozwyssig"

    host = githubpackages.registry_host(registry)

    assert host == "ghcr.io"


# --- the token --------------------------------------------------------------------------------------

def test_the_environment_wins_over_gh(monkeypatch, calls):
    monkeypatch.setenv("GITHUB_TOKEN", "from-the-environment")

    result = githubpackages.token()

    assert result == "from-the-environment"
    assert calls == []                      # `gh` was never asked


def test_gh_answers_when_the_environment_does_not(monkeypatch):
    """Someone already logged in with `gh` should not have to mint a second credential."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(run, "run", lambda argv, **kw: _Result(rc=0, out="from-gh\n"))

    result = githubpackages.token()

    assert result == "from-gh"


def test_neither_source_is_an_error_that_names_both(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(run, "run", lambda argv, **kw: _Result(rc=1))

    with pytest.raises(githubpackages.PackageError, match="gh auth login"):
        githubpackages.token()


# --- the advice everyone needs once -----------------------------------------------------------------

def test_the_advice_names_the_command_that_grants_the_scopes():
    """`gh auth login` requests gist, read:org, repo and workflow - not the package scopes - so the
    first local publish fails pointing at the package rather than at the token."""
    scopes = githubpackages.PACKAGE_SCOPES

    advice = githubpackages.scope_advice(scopes)

    assert "gh auth refresh" in advice
    assert "read:packages,write:packages" in advice


# --- pushing ----------------------------------------------------------------------------------------

def test_a_push_runs_from_the_files_own_directory(tmp_path, calls):
    """oras records the path it is GIVEN as the artifact's name. An absolute path bakes the builder's
    directory into the manifest, and a consumer pulls a file named after someone else's machine."""
    archive = tmp_path / "bundle.zip"
    archive.write_text("x")

    githubpackages.push("ghcr.io/o/r:t", str(archive), "application/vnd.example+zip")

    argv, kwargs = calls[-1]
    assert argv == ["oras", "push", "ghcr.io/o/r:t", "bundle.zip:application/vnd.example+zip"]
    assert kwargs["cwd"] == str(tmp_path)


def test_pushing_something_that_is_not_there_says_so(tmp_path, calls):
    missing = tmp_path / "absent.zip"

    with pytest.raises(githubpackages.PackageError, match="does not exist"):
        githubpackages.push("ghcr.io/o/r:t", str(missing), "application/vnd.example+zip")


# --- listing ----------------------------------------------------------------------------------------

def test_tags_come_back_as_a_list(calls):
    registry, repository = "ghcr.io/owner", "repo"

    result = githubpackages.tags(registry, repository)

    assert result == ["v1", "v2"]


def test_a_refused_listing_names_both_of_its_causes(monkeypatch):
    """Missing scopes and a package that has not granted access need DIFFERENT fixes, and only the
    first is guessable from the error text."""
    monkeypatch.setattr(githubpackages, "require_oras", lambda: None)
    monkeypatch.setattr(run, "run", lambda argv, **kw: _Result(rc=1, err="denied: read_package"))

    with pytest.raises(githubpackages.PackageError) as caught:
        githubpackages.tags("ghcr.io/owner", "repo")

    message = str(caught.value)
    assert "gh auth refresh" in message
    assert "grant this repository read access" in message


# --- oras: provided, not merely demanded ------------------------------------------------------------

def test_the_oras_requirement_provisions_it_instead_of_only_reporting_it(monkeypatch):
    """A missing oras used to stop a build with an instruction. The gate installs it."""
    provisioned = []
    monkeypatch.setattr(githubpackages.oras, "ensure_oras", lambda: provisioned.append(1))

    githubpackages.require_oras()

    assert provisioned == [1]


def test_a_gate_failure_reaches_the_caller_as_a_package_error(monkeypatch):
    """Every failure in this module is a PackageError - the contract its callers catch on."""
    def refuse():
        raise githubpackages.oras.OrasError("no oras and no way to get one")
    monkeypatch.setattr(githubpackages.oras, "ensure_oras", refuse)

    with pytest.raises(githubpackages.PackageError, match="no way to get one"):
        githubpackages.require_oras()


# --- a DIRECTORY as an artifact, and the way back ---------------------------------------------------

def test_the_newest_tag_is_the_last_one_the_registry_lists(calls):
    """`oras repo tags` lists oldest first. Products were each writing `| tail -1` in a shell, which is
    a rule about someone else's tool living in three places."""
    assert githubpackages.newest_tag("ghcr.io/owner", "repo") == "v2"


def test_a_package_with_no_tags_says_so_rather_than_returning_nothing(monkeypatch):
    monkeypatch.setattr(githubpackages, "tags", lambda registry, repository: [])

    with pytest.raises(githubpackages.PackageError, match="no tags"):
        githubpackages.newest_tag("ghcr.io/owner", "repo")


def test_publishing_a_directory_packs_it_and_pushes_the_archive(tmp_path, calls, monkeypatch):
    """githubpackages could publish a FILE. Everything that wants to publish a p2 repository, a site or
    a folder of jars had to zip it first, which is the same six lines in every product."""
    source = tmp_path / "site"
    (source / "features").mkdir(parents=True)
    (source / "site.xml").write_text("<site/>")
    pushed: list = []
    monkeypatch.setattr(githubpackages, "push",
                        lambda ref, path, media: pushed.append((ref, path, media)))

    archive = githubpackages.push_directory("ghcr.io/o/r:t", source, "application/vnd.x+zip")

    assert archive.name == "site.zip" and archive.is_file()
    assert pushed == [("ghcr.io/o/r:t", str(archive), "application/vnd.x+zip")]


def test_publishing_a_directory_that_is_not_there_names_it(tmp_path, calls):
    with pytest.raises(githubpackages.PackageError, match="nothing to publish"):
        githubpackages.push_directory("ghcr.io/o/r:t", tmp_path / "absent", "application/vnd.x+zip")


def test_fetching_an_artifact_unpacks_the_single_archive_it_pulled(tmp_path, monkeypatch):
    """The consuming half: a product that publishes a directory wants it back as a directory, and the
    step in between - 'which of the pulled files is the archive' - is not a product's question."""
    import zipfile
    def fake_pull(ref, destination):
        z = Path(destination) / "thing.zip"
        with zipfile.ZipFile(z, "w") as archive:
            archive.writestr("site.xml", "<site/>")
    monkeypatch.setattr(githubpackages, "pull", fake_pull)

    unpacked = githubpackages.fetch_directory("ghcr.io/o/r:t", tmp_path / "out")

    assert (unpacked / "site.xml").read_text() == "<site/>"
