"""si#102: the solution rendered with GUIDs derived from the path, never generated.

The determinism test is first, and that is the order the design asks for: the decision to COMMIT the
generated files is what makes it load-bearing, and a `uuid4` here would put a new GUID in the diff on
every run and make that decision unusable within a week.
"""
from pathlib import Path

import pytest

from simplon.tasks import buildfiles


def test_a_guid_is_derived_from_the_path_so_two_runs_agree():
    # arrange / act
    a = buildfiles.project_guid("src/Core/Core.csproj")
    b = buildfiles.project_guid("src/Core/Core.csproj")
    other = buildfiles.project_guid("src/Net/Net.csproj")

    # assert: uuid4 here would put a new GUID in the diff on every run, and the committed decision
    # (spec section 4) would be unusable within a week
    assert a == b
    assert a != other
    assert a == a.upper() and a.count("-") == 4


def _targets():
    return [
        buildfiles.Target(name="App", kind="executable", directory=Path("src/App"),
                          sources=[Path("src/App/Program.cs")]),
        buildfiles.Target(name="Core", kind="static", directory=Path("src/Core"),
                          sources=[Path("src/Core/A.cs")]),
        buildfiles.Target(name="Net", kind="shared", directory=Path("src/Net"),
                          sources=[Path("src/Net/B.cs")], depends=["Core"]),
    ]


def _files(root=Path("/product")):
    return buildfiles.dotnet_files(_targets(), root, "demo")


def test_there_is_one_csproj_per_target_directory_and_one_solution():
    # act
    paths = sorted(_files())

    # assert
    assert paths == [Path("/product/demo.sln"),
                     Path("/product/src/App/App.csproj"),
                     Path("/product/src/Core/Core.csproj"),
                     Path("/product/src/Net/Net.csproj")]


def test_the_solution_names_every_project_sorted():
    # act
    text = _files()[Path("/product/demo.sln")]

    # assert
    named = [ln.split('"')[3] for ln in text.splitlines() if ln.startswith("Project(")]
    assert named == ["App", "Core", "Net"]


def test_a_project_row_carries_the_guid_the_path_derives():
    # arrange
    guid = buildfiles.project_guid("src/Core/Core.csproj")

    # act
    text = _files()[Path("/product/demo.sln")]

    # assert
    assert f'"Core", "src/Core/Core.csproj", "{{{guid}}}"' in text


def test_the_project_type_guid_is_microsofts_fixed_constant():
    # act / assert: not derived, not invented - it is the C# SDK project type and Microsoft owns it
    text = _files()[Path("/product/demo.sln")]
    assert text.count('Project("{9A19103F-16F7-4668-BE54-9A1E7A4F7556}")') == 3


def test_the_configuration_matrix_rows_are_sorted():
    # act
    text = _files()[Path("/product/demo.sln")]

    # assert: four rows per project, in one order, so the diff moves only when a project does
    rows = [ln.strip() for ln in text.splitlines() if ".ActiveCfg" in ln or ".Build.0" in ln]
    assert rows == sorted(rows)
    assert len(rows) == 12


def test_a_declared_dependency_becomes_a_project_reference():
    # act
    text = _files()[Path("/product/src/Net/Net.csproj")]

    # assert
    assert '<ProjectReference Include="../Core/Core.csproj" />' in text


def test_a_target_with_no_dependency_references_nothing():
    # act: the tree does not show a dependency, so none is invented (spec section 2)
    text = _files()[Path("/product/src/Core/Core.csproj")]

    # assert
    assert "ProjectReference" not in text


def test_an_executable_says_so_and_a_library_does_not():
    # act
    files = _files()

    # assert
    assert "<OutputType>Exe</OutputType>" in files[Path("/product/src/App/App.csproj")]
    assert "OutputType" not in files[Path("/product/src/Core/Core.csproj")]


def test_every_generated_file_carries_the_header():
    # act / assert: the csproj carries the XML spelling of it, because a `#` line in front of
    # `<Project>` is not a comment in XML, it is a broken build
    files = _files()
    assert files[Path("/product/demo.sln")].count(buildfiles.HEADER) == 1
    for path, text in files.items():
        if path.suffix == ".csproj":
            assert text.startswith(buildfiles.XML_HEADER), path


def test_the_solution_still_opens_with_the_line_visual_studio_looks_for():
    # act / assert: the header sits where every other comment in a .sln sits, because the parser reads
    # the format line first and a `#` in front of it is a missing header rather than a comment
    text = _files()[Path("/product/demo.sln")]
    assert text.startswith("Microsoft Visual Studio Solution File, Format Version 12.00\n")


def test_the_two_headers_carry_the_same_two_sentences():
    # act / assert: one wording, two comment syntaxes
    plain = [ln.lstrip("# ") for ln in buildfiles.HEADER.splitlines()]
    xml = [ln[len("<!-- "):-len(" -->")] for ln in buildfiles.XML_HEADER.splitlines()]
    assert plain == xml


def test_generating_twice_is_byte_identical():
    # act / assert: the assertion the committed decision rests on (spec section 4)
    assert _files() == _files()


def test_two_roots_produce_the_same_bytes():
    # arrange / act: the same product checked out twice, in two places
    here = buildfiles.dotnet_files(_targets(), Path("/one/product"), "demo")
    there = buildfiles.dotnet_files(_targets(), Path("/two/product"), "demo")

    # assert
    assert [t for _, t in sorted(here.items())] == [t for _, t in sorted(there.items())]


def test_two_projects_never_share_a_guid():
    # act
    text = _files()[Path("/product/demo.sln")]

    # assert
    guids = {buildfiles.project_guid(f"src/{n}/{n}.csproj") for n in ("App", "Core", "Net")}
    assert len(guids) == 3
    assert all(guid in text for guid in guids)


def test_a_dependency_naming_no_project_is_refused_rather_than_a_traceback(monkeypatch):
    # arrange: `depends: [Coer]` is a typo of `Core`, and a `ProjectReference` is a PATH to a project -
    # there is no path to one that does not exist. Before this it ended in `KeyError: 'Coer'` out of
    # `_render_csproj`, a traceback out of the CLI where this module promises a diagnosis
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    targets = [*_targets(),
               buildfiles.Target(name="Web", kind="static", directory=Path("src/Web"),
                                 sources=[Path("src/Web/C.cs")], depends=["Coer"])]

    # act / assert: the target, the name it got wrong, and the projects that do exist
    with pytest.raises(RuntimeError) as e:
        buildfiles.dotnet_files(targets, Path("/product"), "demo")
    assert "Web" in str(e.value) and "Coer" in str(e.value) and "Core" in str(e.value)


def test_that_refusal_stops_rather_than_falling_through(monkeypatch):
    # arrange: the rule every refusal in this module keeps - the line after `log.die` must not run on
    # the assumption that it did not exit, or the KeyError comes back after the diagnosis
    monkeypatch.setattr(buildfiles.log, "die", lambda m, *a, **k: None)
    targets = [*_targets(),
               buildfiles.Target(name="Web", kind="static", directory=Path("src/Web"),
                                 sources=[Path("src/Web/C.cs")], depends=["Coer"])]

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.dotnet_files(targets, Path("/product"), "demo")


def test_a_shared_kind_renders_the_same_class_library_a_static_one_does():
    """si#131's `kind:` is a C++ word, and the .NET half is where it deliberately says nothing.

    A .NET assembly is a .NET assembly: `shared` and `static` are the same `.csproj`, and that is
    correct rather than a gap - the distinction the key exists for is CMake's, and the solution
    generator would have to invent a meaning to render it differently.
    """
    # act
    files = _files()

    # assert
    static = files[Path("/product/src/Core/Core.csproj")]
    shared = files[Path("/product/src/Net/Net.csproj")]
    assert "<OutputType>" not in static and "<OutputType>" not in shared
    assert "<IsTestProject>" not in static and "<IsTestProject>" not in shared


def test_a_co_located_unit_test_is_refused_because_dotnet_cannot_express_one(monkeypatch):
    """si#134's .NET half, answered plainly rather than generated wrong.

    THE REASON IS THE SDK'S GLOB, not the test framework's package references. An SDK-style project
    compiles every `.cs` beneath itself - `_render_csproj` emits no `<Compile>` items at all - so a
    test file inside a library's directory is part of that library whatever the solution says about it,
    and a second `.csproj` in the same directory is not a shape MSBuild has. There is nothing to
    generate that is both buildable and true, so the generator refuses and names the move.
    """
    # arrange
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    targets = [*_targets(),
               buildfiles.Target(name="CoreTests", kind="test", directory=Path("src/Core"),
                                 sources=[Path("src/Core/CoreTests.cs")], depends=["Core"],
                                 level=buildfiles.UNIT_LEVEL)]

    # act / assert: the file, and where it has to go instead
    with pytest.raises(RuntimeError) as e:
        buildfiles.dotnet_files(targets, Path("/product"), "demo")
    assert "src/Core/CoreTests.cs" in str(e.value)
    assert "tests/CoreTests/" in str(e.value)


def test_the_co_located_refusal_stops_rather_than_falling_through(monkeypatch):
    # arrange: the rule every refusal in this module keeps
    monkeypatch.setattr(buildfiles.log, "die", lambda m, *a, **k: None)
    targets = [*_targets(),
               buildfiles.Target(name="CoreTests", kind="test", directory=Path("src/Core"),
                                 sources=[Path("src/Core/CoreTests.cs")],
                                 level=buildfiles.UNIT_LEVEL)]

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.dotnet_files(targets, Path("/product"), "demo")
