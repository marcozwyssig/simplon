"""`release:nuget` - packing a .NET library and pushing it, without the token ever reaching argv (si#127).

The assertions here are over the LINES, because the lines are the decisions: which image, whose uid,
where dotnet may write, and - the one this ticket turns on - that the credential arrives as a file
reference rather than as an element anybody with `ps` or `docker inspect` can read.

A string assertion over an argv is not evidence that the feature works; the end-to-end drive is what
claims that (design section 6). It IS evidence about the shape of a command, which is what these are.
"""
import pytest

from simplon import context, githubpackages
from simplon.context import ProductContext
from simplon.tasks import nuget

_MANIFEST = """
product: demo
artifacts:
  corelib:
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
    tag: 1.4.0
  untagged:
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
  floating:
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:latest
    project: src/Core/Core.csproj
    tag: 1.0.0
  elsewhere:
    registry: nuget.example.com/team
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
    tag: 1.0.0
groups: {}
env_groups: []
"""

_TOKEN = "ghp_RECOGNISABLE_SECRET"


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    (tmp_path / "src" / "Core").mkdir(parents=True)
    (tmp_path / "src" / "Core" / "Core.csproj").write_text("<Project />", encoding="utf-8")
    (tmp_path / "nuget.config").write_text("<configuration />", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", _TOKEN)
    monkeypatch.setattr(nuget.docker, "ensure_docker", lambda: None)
    monkeypatch.setattr(nuget.docker, "user_args", lambda: ["-u", "1000:1000"])
    return tmp_path


@pytest.fixture
def lines(monkeypatch):
    """Every container line the task assembled, with nothing run."""
    seen: list = []

    def _stream(argv, cwd=None):
        seen.append(list(argv))
        return 0

    monkeypatch.setattr(nuget, "stream", _stream)
    return seen


def _of(lines, verb):
    """The one line whose dotnet verb is `verb`."""
    return next(line for line in lines if verb in line)


# --- packing ------------------------------------------------------------------------------------------

def test_the_pack_carries_the_version_the_tag_names(lines):
    # act
    rc = nuget.publish(name="corelib", tag="2.0.1")

    # assert
    assert rc == 0
    packed = _of(lines, "pack")
    assert "-p:PackageVersion=2.0.1" in packed
    assert "src/Core/Core.csproj" in packed


def test_a_tag_declared_in_the_manifest_needs_no_argument(lines):
    nuget.publish(name="corelib")

    assert "-p:PackageVersion=1.4.0" in _of(lines, "pack")


def test_without_a_tag_anywhere_it_names_both_places_one_could_be(lines):
    """artifact.py's rule and its wording: cleon's version is only knowable after a build, so a message
    naming only the manifest key would read as 'this task cannot do it'."""
    with pytest.raises(ValueError, match="--tag"):
        nuget.publish(name="untagged")


# --- pushing, and the credential ----------------------------------------------------------------------

def test_the_push_names_the_source_and_carries_no_api_key(lines):
    """MEASURED (module head): an api key is not a credential - `--api-key` alone answers 401 against an
    authenticated feed - and a push with source credentials needs none. So there is nothing to put in
    argv, and this asserts that nothing is."""
    nuget.publish(name="corelib")

    pushed = _of(lines, "push")
    assert "--api-key" not in pushed
    assert "--source" in pushed
    assert nuget.DEFAULT_SOURCE in pushed


def test_the_token_is_in_no_line_at_all(lines):
    """The whole argv, every line, not one element: a token that reached any of them would be readable
    in `docker inspect` and in the host's /proc for as long as the container ran."""
    nuget.publish(name="corelib")

    assert lines, "nothing was assembled, so this asserts nothing"
    for line in lines:
        assert not any(_TOKEN in str(element) for element in line), line


def test_the_credential_arrives_as_an_env_file(lines):
    nuget.publish(name="corelib")

    for line in lines:
        assert "--env-file" in line
        assert not any(str(element).startswith(f"{nuget.TOKEN_VAR}=") for element in line)


def test_the_env_file_holds_the_token_while_the_run_lasts_and_is_gone_after(monkeypatch):
    """The file is the credential, so its lifetime is the thing to assert: readable during the run,
    absent after it, and 0600 while it exists."""
    seen: dict = {}

    def _stream(argv, cwd=None):
        path = argv[argv.index("--env-file") + 1]
        seen["path"] = path
        seen["body"] = open(path, encoding="utf-8").read()
        import os
        import stat
        seen["mode"] = stat.S_IMODE(os.stat(path).st_mode)
        return 0

    monkeypatch.setattr(nuget, "stream", _stream)

    nuget.publish(name="corelib")

    import os
    assert seen["body"].strip() == f"{nuget.TOKEN_VAR}={_TOKEN}"
    assert seen["mode"] == 0o600
    assert not os.path.exists(seen["path"])


def test_the_env_file_is_removed_even_when_the_run_raises(monkeypatch):
    """A `finally`, not a happy path: a crash between writing the credential and deleting it would leave
    a readable token in a temp directory nobody looks at again."""
    seen: dict = {}

    def _boom(argv, cwd=None):
        seen["path"] = argv[argv.index("--env-file") + 1]
        raise RuntimeError("the daemon went away")

    monkeypatch.setattr(nuget, "stream", _boom)

    with pytest.raises(RuntimeError):
        nuget.publish(name="corelib")

    import os
    assert not os.path.exists(seen["path"])


# --- the container the two commands run in ------------------------------------------------------------

def test_every_line_sets_dotnet_cli_home_and_runs_as_the_caller(lines):
    """si#102 measured this the hard way: as uid 1000 `dotnet` dies on `/.dotnet` denied, and as uid 0 it
    passes - so a container that runs as the caller and does not set it is green on one machine and red
    on the next."""
    nuget.publish(name="corelib")

    for line in lines:
        assert "-u" in line and "1000:1000" in line
        assert f"DOTNET_CLI_HOME=/work/{nuget.CLI_HOME}" in line


def test_an_unpinned_image_is_refused_with_the_kernels_one_wording(lines):
    """`docker.pinned_image` is the ONE image gate in this kernel; a second one written here would drift
    from it, which is the argument its own docstring makes."""
    with pytest.raises(ValueError, match="latest"):
        nuget.publish(name="floating")
    assert lines == []


# --- where the token may go ---------------------------------------------------------------------------

def test_a_registry_that_is_not_githubs_is_refused_before_a_token_is_minted(lines, monkeypatch):
    def _never():
        raise AssertionError("a token was minted for a host that is not GitHub's")

    monkeypatch.setattr(githubpackages, "token", _never)

    with pytest.raises(ValueError, match="nuget.pkg.github.com"):
        nuget.publish(name="elsewhere")
    assert lines == []


def test_a_project_that_is_not_there_is_named_before_anything_runs(lines, _product):
    (_product / "src" / "Core" / "Core.csproj").unlink()

    with pytest.raises(ValueError, match="Core.csproj"):
        nuget.publish(name="corelib")
    assert lines == []


def test_without_a_generated_config_the_push_has_no_source_and_says_which_command_writes_one(
        lines, _product):
    """The two halves are one feature: `--source github` means nothing without the file that names it,
    and the failure `dotnet` would give instead ('source not found') names neither the manifest nor the
    command that fixes it."""
    (_product / "nuget.config").unlink()

    with pytest.raises(ValueError, match="build:nuget-config"):
        nuget.publish(name="corelib")
    assert lines == []


def test_a_failed_push_appends_the_scope_advice(monkeypatch, capsys):
    """The one hint that is worth appending, and only for GitHub: the first local publish fails with
    `denied: permission_denied` and points at the package rather than at the token."""
    monkeypatch.setattr(nuget, "stream", lambda argv, cwd=None: 0 if "pack" in argv else 7)

    rc = nuget.publish(name="corelib")

    assert rc == 7
    assert "gh auth refresh" in capsys.readouterr().err
