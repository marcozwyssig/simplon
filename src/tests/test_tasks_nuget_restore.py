"""`build:nuget-restore` - resolving a private feed inside the container (si#127).

WHY THIS COORDINATE EXISTS AT ALL, since a product's ordinary `toolchain:run` compile command already
restores: it cannot carry the credential. `toolchain.run_toolchain`'s environment is "the environment the
manifest names, and nothing else" (si#105), and a token is precisely what a manifest may not name. So the
consuming half of si#127 needs a runner that can put a secret into a container, and this is it.
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
    project: src/App/App.csproj
  elsewhere:
    registry: nuget.example.com/team
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/App/App.csproj
groups: {}
env_groups: []
"""

_TOKEN = "ghp_RECOGNISABLE_SECRET"


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    (tmp_path / "src" / "App").mkdir(parents=True)
    (tmp_path / "src" / "App" / "App.csproj").write_text("<Project />", encoding="utf-8")
    (tmp_path / "nuget.config").write_text("<configuration />", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", _TOKEN)
    monkeypatch.setattr(nuget.docker, "ensure_docker", lambda: None)
    monkeypatch.setattr(nuget.docker, "user_args", lambda: ["-u", "1000:1000"])
    return tmp_path


@pytest.fixture
def lines(monkeypatch):
    seen: list = []
    monkeypatch.setattr(nuget, "stream", lambda argv, cwd=None: (seen.append(list(argv)), 0)[1])
    return seen


def test_the_restore_runs_the_declared_project_in_the_pinned_image(lines):
    # act
    rc = nuget.restore(name="corelib")

    # assert
    assert rc == 0
    assert len(lines) == 1
    assert lines[0][-3:] == ["dotnet", "restore", "src/App/App.csproj"]
    assert "mcr.microsoft.com/dotnet/sdk:9.0" in lines[0]


def test_the_credential_reaches_the_container_as_a_file_and_the_token_is_in_no_line(lines):
    """The same rule the publish keeps, asserted again here because this is the command a CONSUMER runs -
    and a consumer's machine is the one where a leaked token is least likely to be noticed."""
    nuget.restore(name="corelib")

    assert "--env-file" in lines[0]
    assert not any(_TOKEN in str(element) for element in lines[0])


def test_the_container_sets_dotnet_cli_home(lines):
    """si#102's measured fact, and it bites HARDER here: `dotnet restore` writes the package cache, so
    without a writable home the very command this coordinate exists for is the one that fails."""
    nuget.restore(name="corelib")

    assert f"DOTNET_CLI_HOME=/work/{nuget.CLI_HOME}" in lines[0]


def test_without_a_generated_config_it_names_the_command_that_writes_one(lines, _product):
    """A restore against a source nothing declares fails inside NuGet, in a message about a package that
    could not be found - which names neither the feed nor the missing file."""
    (_product / "nuget.config").unlink()

    with pytest.raises(ValueError, match="build:nuget-config"):
        nuget.restore(name="corelib")
    assert lines == []


def test_a_registry_that_is_not_githubs_is_refused_before_a_token_is_minted(lines, monkeypatch):
    def _never():
        raise AssertionError("a token was minted for a host that is not GitHub's")

    monkeypatch.setattr(githubpackages, "token", _never)

    with pytest.raises(ValueError, match="nuget.pkg.github.com"):
        nuget.restore(name="elsewhere")
    assert lines == []


def test_a_failed_restore_appends_the_scope_advice(monkeypatch, capsys):
    """`read:packages` is the scope a CONSUMER lacks, and `gh auth login` does not request it - so the
    very first restore on a fresh machine is the one that needs the sentence."""
    monkeypatch.setattr(nuget, "stream", lambda argv, cwd=None: 1)

    rc = nuget.restore(name="corelib")

    assert rc == 1
    assert "gh auth refresh" in capsys.readouterr().err
