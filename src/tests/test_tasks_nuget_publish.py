"""`build:nuget-pack` and `release:nuget` - packing a .NET library, then pushing what was packed, without the token ever reaching argv (si#127, si#344 C.3).

The assertions here are over the LINES, because the lines are the decisions: which image, whose uid,
where dotnet may write, and - the one this ticket turns on - that the credential arrives as a file
reference rather than as an element anybody with `ps` or `docker inspect` can read.

A string assertion over an argv is not evidence that the feature works; the end-to-end drive is what
claims that (design section 6). It IS evidence about the shape of a command, which is what these are.
"""
import pytest

from simplon.domain import context
from simplon.adapters import githubpackages
from simplon.domain.context import ProductContext
from simplon.tasks import nuget

from conftest import lifecycle_name

_MANIFEST = """
product: demo
artifacts:
  corelib:
    kind: nuget
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
    path: build/nuget
    tag: 1.4.0
  untagged:
    kind: nuget
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
    path: build/nuget
  floating:
    kind: nuget
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:latest
    project: src/Core/Core.csproj
    path: build/nuget
    tag: 1.0.0
  elsewhere:
    kind: nuget
    registry: nuget.example.com/team
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
    path: build/nuget
    tag: 1.0.0
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
def lines(monkeypatch, _product):
    """Every container line the task assembled, with nothing run. A `dotnet pack` line leaves the package
    a real one would, named for the version in its `-p:PackageVersion=` - so `push` finds what `pack` made."""
    seen: list = []

    def _stream(argv, cwd=None):
        seen.append(list(argv))
        if "pack" in argv:
            version = next(a for a in argv if a.startswith("-p:PackageVersion=")).split("=", 1)[1]
            out = _product / "build" / "nuget"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"Core.{version}.nupkg").write_bytes(b"PK")
        return 0

    monkeypatch.setattr(nuget, "stream", _stream)
    return seen


def _of(lines, verb):
    """The one line whose dotnet verb is `verb`."""
    return next(line for line in lines if verb in line)


# --- packing ------------------------------------------------------------------------------------------

def test_the_pack_carries_the_version_the_tag_names(lines):
    # act
    rc = nuget.pack("corelib", tag="2.0.1")

    # assert
    assert rc == 0
    packed = _of(lines, "pack")
    assert "-p:PackageVersion=2.0.1" in packed
    assert "src/Core/Core.csproj" in packed


def test_the_pack_and_the_push_each_name_and_label_their_own_container(lines):
    # act: si#412 - two containers, so two names; one name for both would stop the wrong one
    nuget.pack("corelib", tag="2.0.1")
    nuget.push("corelib", tag="2.0.1")

    # assert
    names = [lifecycle_name(line, "demo") for line in lines]
    assert len(names) == 2 and names[0] != names[1]


def test_an_interrupted_push_removes_the_container_it_named(lines, monkeypatch, removals):
    # arrange: the pack finishes, the push is interrupted while its client runs
    nuget.pack("corelib", tag="2.0.1")
    seen: list = []

    def _stream(argv, cwd=None):
        seen.append(list(argv))
        if "push" in argv:
            raise KeyboardInterrupt
        return 0
    monkeypatch.setattr(nuget, "stream", _stream)

    # act
    with pytest.raises(KeyboardInterrupt):
        nuget.push("corelib", tag="2.0.1")

    # assert: the push's container and not the pack's, and the interrupt still arrives
    assert removals == [lifecycle_name(seen[-1], "demo")]


def test_a_tag_declared_in_the_manifest_needs_no_argument(lines):
    nuget.pack("corelib")

    assert "-p:PackageVersion=1.4.0" in _of(lines, "pack")


def test_without_a_tag_anywhere_it_names_both_places_one_could_be(lines):
    """artifact.py's rule and its wording: cleon's version is only knowable after a build, so a message
    naming only the manifest key would read as 'this task cannot do it'."""
    with pytest.raises(ValueError, match="--tag"):
        nuget.pack("untagged")
    with pytest.raises(ValueError, match="--tag"):
        nuget.push("untagged")


# --- pushing, and the credential ----------------------------------------------------------------------

def test_the_push_names_the_source_and_carries_no_api_key(lines):
    """MEASURED (module head): an api key is not a credential - `--api-key` alone answers 401 against an
    authenticated feed - and a push with source credentials needs none. So there is nothing to put in
    argv, and this asserts that nothing is."""
    nuget.pack("corelib")
    nuget.push("corelib")

    pushed = _of(lines, "push")
    assert "--api-key" not in pushed
    assert "--source" in pushed
    assert nuget.DEFAULT_SOURCE in pushed


def test_the_token_is_in_no_line_at_all(lines):
    """The whole argv, every line, not one element: a token that reached any of them would be readable
    in `docker inspect` and in the host's /proc for as long as the container ran."""
    nuget.pack("corelib")
    nuget.push("corelib")

    assert lines, "nothing was assembled, so this asserts nothing"
    for line in lines:
        assert not any(_TOKEN in str(element) for element in line), line


def test_the_credential_arrives_as_an_env_file(lines):
    nuget.pack("corelib")
    nuget.push("corelib")

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

    nuget.pack("corelib")

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
        nuget.pack("corelib")

    import os
    assert not os.path.exists(seen["path"])


# --- the container the two commands run in ------------------------------------------------------------

def test_every_line_gets_the_kernels_home_and_runs_as_the_caller(lines):
    """si#102 measured this the hard way: as uid 1000 `dotnet` dies on `/.dotnet` denied, and as uid 0 it
    passes - so a container that runs as the caller and does not set it is green on one machine and red
    on the next."""
    nuget.pack("corelib")
    nuget.push("corelib")

    for line in lines:
        assert "-u" in line and "1000:1000" in line
        assert "HOME=/work/build/home" in line
        assert not any("DOTNET_CLI_HOME" in str(element) for element in line)


def test_an_unpinned_image_is_refused_with_the_kernels_one_wording(lines):
    """`docker.pinned_image` is the ONE image gate in this kernel; a second one written here would drift
    from it, which is the argument its own docstring makes."""
    with pytest.raises(ValueError, match="latest"):
        nuget.pack("floating")
    assert lines == []


# --- where the token may go ---------------------------------------------------------------------------

def test_a_registry_that_is_not_githubs_is_refused_before_a_token_is_minted(lines, monkeypatch):
    def _never():
        raise AssertionError("a token was minted for a host that is not GitHub's")

    nuget.pack("elsewhere")                       # a pack needs no registry
    monkeypatch.setattr(githubpackages, "token", _never)
    packed = list(lines)
    with pytest.raises(ValueError, match="nuget.pkg.github.com"):
        nuget.push("elsewhere")
    assert lines == packed


def test_a_project_that_is_not_there_is_named_before_anything_runs(lines, _product):
    (_product / "src" / "Core" / "Core.csproj").unlink()

    with pytest.raises(ValueError, match="Core.csproj"):
        nuget.pack("corelib")
    assert lines == []


def test_without_a_generated_config_the_push_has_no_source_and_says_which_command_writes_one(
        lines, _product):
    """The two halves are one feature: `--source github` means nothing without the file that names it,
    and the failure `dotnet` would give instead ('source not found') names neither the manifest nor the
    command that fixes it."""
    nuget.pack("corelib")
    (_product / "nuget.config").unlink()
    packed = list(lines)

    with pytest.raises(ValueError, match="build:nuget-config"):
        nuget.push("corelib")
    assert lines == packed


def test_a_failed_push_appends_the_scope_advice(lines, monkeypatch, capsys):
    """The one hint that is worth appending, and only for GitHub: the first local publish fails with
    `denied: permission_denied` and points at the package rather than at the token."""
    nuget.pack("corelib")
    monkeypatch.setattr(nuget, "stream", lambda argv, cwd=None: 7)

    rc = nuget.push("corelib")

    assert rc == 7
    assert "gh auth refresh" in capsys.readouterr().err


# --- si#344 C.3: pack writes the package, push pushes exactly that one ----------------------------------

def test_the_pack_writes_into_the_artifacts_path(lines):
    # act
    rc = nuget.pack("corelib")

    # assert
    assert rc == 0
    assert "/work/build/nuget" in _of(lines, "pack")


def test_the_pack_removes_an_earlier_package_before_it_packs(lines, _product):
    # arrange: yesterday's package of another version lies in the directory
    out = _product / "build" / "nuget"
    out.mkdir(parents=True)
    (out / "Core.1.3.0.nupkg").write_bytes(b"PK")

    # act
    nuget.pack("corelib")

    # assert
    assert sorted(p.name for p in out.iterdir()) == ["Core.1.4.0.nupkg"]


def test_a_pack_that_exits_0_and_writes_no_package_is_a_failed_step(monkeypatch, capsys):
    # arrange: dotnet answers 0 and writes nothing
    monkeypatch.setattr(nuget, "stream", lambda argv, cwd=None: 0)

    # act
    rc = nuget.pack("corelib")

    # assert
    assert rc == 1
    assert "wrote no package for 1.4.0" in capsys.readouterr().err


def test_the_push_pushes_the_one_package_packed_for_that_version(lines, _product):
    # arrange: an older package lies beside the one this version packed
    nuget.pack("corelib")
    (_product / "build" / "nuget" / "Core.1.3.0.nupkg").write_bytes(b"PK")

    # act
    rc = nuget.push("corelib")

    # assert
    assert rc == 0
    push = _of(lines, "push")
    assert "/work/build/nuget/Core.1.4.0.nupkg" in push
    assert not any("1.3.0" in part for part in push)


def test_a_push_with_nothing_packed_for_its_version_names_the_pack_command(lines):
    # act / assert
    with pytest.raises(ValueError, match="nothing packed for 1.4.0 under build/nuget: run `build:nuget-pack` first"):
        nuget.push("corelib")
    assert not any("push" in line for line in lines)


def test_a_pack_path_outside_the_output_root_is_refused_before_anything_is_deleted(_product, lines):
    # arrange
    text = (_product / "demo.yaml").read_text(encoding="utf-8").replace("path: build/nuget", "path: .", 1)
    (_product / "demo.yaml").write_text(text, encoding="utf-8")
    (_product / "keep.nupkg").write_bytes(b"PK")

    # act / assert
    with pytest.raises(ValueError, match="is not inside the output root"):
        nuget.pack("corelib")
    assert (_product / "keep.nupkg").exists()
