"""`build:nuget-config` - the source a build can reach, in a file a repository can hold (si#127).

THE ONE ASSERTION THIS FILE EXISTS FOR is that no token is ever written. si#127 states it as the part
to get right ("it must not land in a generated `nuget.config` that someone commits"), and a test that
only checked the source URL would pass just as happily over a file with a PAT in it. So the token is set
to a recognisable string and its ABSENCE from the written bytes is asserted directly.

AAA throughout; nothing runs a container and nothing reaches a registry.
"""
from xml.etree import ElementTree

import pytest

from simplon import context
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
  named:
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
    source_name: house
  elsewhere:
    registry: nuget.example.com/team
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
  nohost:
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
groups: {}
env_groups: []
"""


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    return tmp_path


# --- the index URL, derived rather than declared twice -------------------------------------------------

@pytest.mark.parametrize("registry,expected", [
    ("nuget.pkg.github.com/marcozwyssig", "https://nuget.pkg.github.com/marcozwyssig/index.json"),
    ("nuget.pkg.github.com/owner/", "https://nuget.pkg.github.com/owner/index.json"),
    ("https://nuget.pkg.github.com/owner", "https://nuget.pkg.github.com/owner/index.json"),
])
def test_the_index_url_is_derived_from_the_registry_the_credential_check_reads(registry, expected):
    """One spelling of `registry:` for both the check and the URL. Two keys would be two sources for one
    fact, and the one that drifts is the one nothing reads back."""
    assert nuget.index_url(registry) == expected


def test_a_registry_naming_no_owner_is_refused_rather_than_producing_half_a_url():
    """`nuget.pkg.github.com` alone would render `https://nuget.pkg.github.com/index.json`, which is a
    404 at restore time and says nothing about the manifest."""
    with pytest.raises(ValueError, match="owner"):
        nuget.index_url("nuget.pkg.github.com")


# --- the file itself ----------------------------------------------------------------------------------

def test_the_generated_file_never_carries_the_token(_product, monkeypatch):
    """si#127's one security requirement, asserted over the bytes rather than implied by the design."""
    # arrange
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_RECOGNISABLE_SECRET")

    # act
    nuget.config(name="corelib")

    # assert
    written = (_product / "nuget.config").read_text(encoding="utf-8")
    assert "ghp_RECOGNISABLE_SECRET" not in written
    assert "%GITHUB_TOKEN%" in written


def test_the_file_names_the_source_and_parses_as_xml(_product):
    # act
    rc = nuget.config(name="corelib")

    # assert
    assert rc == 0
    root = ElementTree.fromstring((_product / "nuget.config").read_text(encoding="utf-8"))
    sources = {e.get("key"): e.get("value") for e in root.findall("./packageSources/add")}
    assert sources["github"] == "https://nuget.pkg.github.com/marcozwyssig/index.json"
    assert "nuget.org" in sources


def test_the_source_name_the_manifest_chooses_is_the_one_written(_product):
    """`release:nuget` pushes to `--source <name>`, so the name is a fact both halves share."""
    nuget.config(name="named")

    root = ElementTree.fromstring((_product / "nuget.config").read_text(encoding="utf-8"))
    assert "house" in {e.get("key") for e in root.findall("./packageSources/add")}
    assert root.find("./packageSourceCredentials/house") is not None


def test_the_credential_block_names_the_owner_as_the_user(_product):
    """GHCR ignores the username when the password is a token, but NuGet requires one, and the owner is
    the value that tells a reader of the file whose feed this is."""
    nuget.config(name="corelib")

    root = ElementTree.fromstring((_product / "nuget.config").read_text(encoding="utf-8"))
    block = root.find("./packageSourceCredentials/github")
    values = {e.get("key"): e.get("value") for e in block}
    assert values["Username"] == "marcozwyssig"
    assert values["ClearTextPassword"] == "%GITHUB_TOKEN%"


def test_nuget_org_is_cleared_first_so_a_machine_wide_config_cannot_change_the_answer(_product):
    """A restore that resolves differently on two machines is the defect a generated file exists to
    close, and `<clear />` is the only thing that stops an inherited source from joining in."""
    nuget.config(name="corelib")

    body = (_product / "nuget.config").read_text(encoding="utf-8")
    assert body.index("<clear />") < body.index("nuget.org")


# --- the refusals -------------------------------------------------------------------------------------

def test_a_registry_that_is_not_githubs_is_refused_by_name(_product):
    """The generated block writes `%GITHUB_TOKEN%`, so a config for someone else's host would tell a
    build to send a GitHub PAT there. `is_github_packages` is the check, and this is the caller paying
    it."""
    with pytest.raises(ValueError, match="nuget.pkg.github.com"):
        nuget.config(name="elsewhere")


def test_an_artefact_with_no_registry_names_the_key(_product):
    with pytest.raises(ValueError, match="registry"):
        nuget.config(name="nohost")


def test_an_undeclared_artefact_lists_the_ones_that_are(_product):
    with pytest.raises(ValueError, match="corelib"):
        nuget.config(name="nope")


def test_without_a_name_it_says_how_to_pin_one(_product):
    with pytest.raises(ValueError, match="with:"):
        nuget.config()
