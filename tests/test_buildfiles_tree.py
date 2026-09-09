"""si#102: the source tree read as the declaration it is - and si#131/si#134, which is what it says.

si#102 read the DIRECT children of `src/` and everything directly in `tests/`. That left three things
a real C++ project has to state unsaid, and the third of them was not a gap but a defect: a nested
directory was compiled by nothing, a library could not say whether it wanted an archive or a shared
object, and a `_test` file beside its unit was swept into the LIBRARY's source list and shipped inside
the artefact. The tests below are the rules that replaced all three.
"""
from pathlib import Path

import pytest

from simplon.tasks import buildfiles


def _tree(tmp_path, *paths):
    for rel in paths:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// x\n")
    return tmp_path


def test_a_source_directory_without_a_main_is_a_static_library(tmp_path):
    # arrange
    root = _tree(tmp_path, "src/core/a.cpp", "src/core/b.cpp")

    # act
    targets = buildfiles.read_tree(root, {})

    # assert: STATIC is the default and it is stated rather than left to BUILD_SHARED_LIBS (si#131)
    assert [(t.name, t.kind) for t in targets] == [("core", "static")]


def test_a_nested_directory_folds_into_the_target_above_it(tmp_path):
    # arrange: si#131's first face. `src/net/tcp/` was a target of nothing - no CMakeLists.txt, and its
    # sources compiled by nobody, which arrives as an undefined symbol at link rather than as a message
    # about a file
    root = _tree(tmp_path, "src/net/net.cpp", "src/net/tcp/socket.cpp", "src/net/tcp/deep/x.cpp")

    # act
    targets = buildfiles.read_tree(root, {})

    # assert: ONE target, at the target root, carrying the whole subtree - and no target named `tcp`,
    # which is the name the other answer would have had to invent
    assert [t.name for t in targets] == ["net"]
    assert targets[0].directory == Path("src/net")
    assert [p.as_posix() for p in targets[0].sources] == [
        "src/net/net.cpp", "src/net/tcp/deep/x.cpp", "src/net/tcp/socket.cpp"]


def test_a_main_below_a_target_root_is_refused_rather_than_archived_in_silence(tmp_path, monkeypatch):
    # arrange: folding would compile `src/net/tools/main.cpp` INTO libnet.a, and a stray `main` in an
    # archive is invisible - the linker gives up a member only to resolve an undefined symbol, and
    # whoever links the archive has defined `main` already
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    root = _tree(tmp_path, "src/net/net.cpp", "src/net/tools/main.cpp")

    # act / assert: the file, and the move that fixes it
    with pytest.raises(RuntimeError) as e:
        buildfiles.read_tree(root, {})
    assert "src/net/tools/main.cpp" in str(e.value)
    assert "src/tools/" in str(e.value)


def test_a_unit_test_beside_its_unit_is_a_target_and_not_a_source_of_the_library(tmp_path):
    # arrange: si#134's defect, which shipped test code inside the artefact
    root = _tree(tmp_path, "src/net/net.cpp", "src/net/net_test.cpp")

    # act
    targets = {t.name: t for t in buildfiles.read_tree(root, {})}

    # assert: two targets, and the library does not carry the test file
    assert targets["net"].kind == "static"
    assert [p.as_posix() for p in targets["net"].sources] == ["src/net/net.cpp"]
    assert targets["net_test"].kind == "test"
    assert targets["net_test"].level == buildfiles.UNIT_LEVEL
    assert targets["net_test"].directory == Path("src/net")


def test_a_co_located_unit_test_links_its_library_without_the_manifest_saying_so(tmp_path):
    # arrange: the test sits INSIDE the library's directory, so the tree already says which library it
    # tests and where the header is - a `depends:`/`include:` pair would be a second statement of that
    root = _tree(tmp_path, "src/net/net.cpp", "src/net/net_test.cpp")

    # act
    targets = {t.name: t for t in buildfiles.read_tree(root, {})}

    # assert
    assert targets["net_test"].depends == ["net"]


def test_a_unit_test_beside_a_main_links_nothing(tmp_path):
    # arrange: CMake refuses `target_link_libraries` against an executable, so there is nothing to
    # derive here and the derivation says so by deriving nothing
    root = _tree(tmp_path, "src/app/main.cpp", "src/app/app_test.cpp")

    # act
    targets = {t.name: t for t in buildfiles.read_tree(root, {})}

    # assert
    assert targets["app"].kind == "executable"
    assert targets["app_test"].depends == []


def test_a_directory_of_nothing_but_tests_produces_the_tests_and_no_library(tmp_path):
    # arrange: there is no library left to compile, and none to link either
    root = _tree(tmp_path, "src/net/net_test.cpp")

    # act
    targets = buildfiles.read_tree(root, {})

    # assert
    assert [(t.name, t.kind, t.depends) for t in targets] == [("net_test", "test", [])]


def test_the_two_level_directories_under_tests_name_the_level(tmp_path):
    # arrange: `tests/` holds two levels now, so the generator has to tell them apart (si#134)
    root = _tree(tmp_path, "tests/system/api_test.cpp", "tests/acceptance/story_test.cpp",
                 "tests/legacy_test.cpp")

    # act
    levels = {t.name: t.level for t in buildfiles.read_tree(root, {})}

    # assert: and a test directly in tests/ keeps the shape si#102 shipped, with no level
    assert levels == {"api_test": "system", "story_test": "acceptance", "legacy_test": None}


def test_a_level_directory_holds_a_project_as_well_as_a_file(tmp_path):
    # arrange: a .NET test project is a directory, so a level has to be able to hold one - otherwise
    # "the location names the level" would be a C++ feature rather than a rule
    root = _tree(tmp_path, "tests/system/Api.Tests/ApiTests.cs")

    # act
    targets = {t.name: t for t in buildfiles.read_tree(root, {})}

    # assert
    assert targets["Api.Tests"].level == "system"
    assert targets["Api.Tests"].directory == Path("tests/system/Api.Tests")


def test_a_directory_holding_main_is_an_executable(tmp_path):
    # arrange
    root = _tree(tmp_path, "src/app/main.cpp")

    # act / assert
    assert [(t.name, t.kind) for t in buildfiles.read_tree(root, {})] == [("app", "executable")]


def test_a_test_directory_becomes_test_targets(tmp_path):
    # arrange
    root = _tree(tmp_path, "src/core/a.cpp", "tests/core_test.cpp")

    # act
    kinds = {t.name: t.kind for t in buildfiles.read_tree(root, {})}

    # assert
    assert kinds == {"core": "static", "core_test": "test"}


def test_sources_are_sorted_so_two_runs_agree(tmp_path):
    # arrange: a directory listing is not an order, and the output is committed
    root = _tree(tmp_path, "src/core/z.cpp", "src/core/a.cpp", "src/core/m.cpp")

    # act
    target = buildfiles.read_tree(root, {})[0]

    # assert
    assert [p.name for p in target.sources] == ["a.cpp", "m.cpp", "z.cpp"]


def test_a_dependency_the_tree_cannot_show_comes_from_the_manifest(tmp_path):
    # arrange: the ONE thing a directory does not say
    root = _tree(tmp_path, "src/core/a.cpp", "src/net/b.cpp")

    # act
    targets = {t.name: t for t in buildfiles.read_tree(root, {"net": {"depends": ["core"]}})}

    # assert
    assert targets["net"].depends == ["core"]
    assert targets["core"].depends == []


def test_a_declared_kind_is_the_one_thing_a_directory_of_sources_cannot_show(tmp_path):
    # arrange: an archive and a shared object are the same directory of sources (si#131)
    root = _tree(tmp_path, "src/plugin/plugin.cpp")

    # act / assert
    assert buildfiles.read_tree(root, {"plugin": {"kind": "shared"}})[0].kind == "shared"


def test_a_kind_that_is_no_kind_is_refused_by_name(tmp_path, monkeypatch):
    # arrange: `kind: dynamic` would otherwise reach the renderer and select one of the two constructs
    # there are, writing a guess into a committed file
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    root = _tree(tmp_path, "src/plugin/plugin.cpp")

    # act / assert
    with pytest.raises(RuntimeError) as e:
        buildfiles.read_tree(root, {"plugin": {"kind": "dynamic"}})
    assert "dynamic" in str(e.value) and "shared" in str(e.value) and "static" in str(e.value)


def test_a_kind_declared_for_a_test_is_refused(tmp_path, monkeypatch):
    # arrange: where a file sits is what makes it a test, and a test turned into a library would lose
    # its `add_test` - the suite shrinks by one case and every run stays green
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    root = _tree(tmp_path, "tests/net_test.cpp")

    # act / assert
    with pytest.raises(RuntimeError) as e:
        buildfiles.read_tree(root, {"net_test": {"kind": "static"}})
    assert "net_test" in str(e.value) and "kind" in str(e.value)


def test_a_declared_dependency_adds_to_the_one_the_tree_derived(tmp_path):
    # arrange: a co-located test already links its library. If `depends:` REPLACED that, then naming
    # one extra dependency would silently unlink the test from the unit it tests, and the failure would
    # arrive as an undefined symbol rather than as anything about the manifest
    root = _tree(tmp_path, "src/net/net.cpp", "src/net/net_test.cpp")

    # act
    targets = {t.name: t for t in buildfiles.read_tree(root, {"net_test": {"depends": ["fmt"]}})}

    # assert: the derived one first, which is the order a linker can care about
    assert targets["net_test"].depends == ["net", "fmt"]


def test_a_manifest_block_that_says_nothing_about_depends_keeps_the_derived_one(tmp_path):
    # arrange: the common case - a block carrying only `include:`
    root = _tree(tmp_path, "src/net/net.cpp", "src/net/net_test.cpp")

    # act
    targets = {t.name: t
               for t in buildfiles.read_tree(root, {"net_test": {"include": ["vendor/gtest"]}})}

    # assert
    assert targets["net_test"].depends == ["net"]


def test_a_dependency_is_never_invented(tmp_path):
    # arrange: guessing from include paths was rejected - it fails at link time, in a message about
    # symbols rather than about the manifest
    root = _tree(tmp_path, "src/core/a.cpp", "src/net/b.cpp")

    # act / assert
    assert all(t.depends == [] for t in buildfiles.read_tree(root, {}))


def test_an_override_naming_no_target_is_refused_by_name(tmp_path, monkeypatch):
    # arrange
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    root = _tree(tmp_path, "src/core/a.cpp")

    # act / assert: a typo in `targets:` is silent otherwise, and silently does nothing
    with pytest.raises(RuntimeError) as e:
        buildfiles.read_tree(root, {"nett": {"depends": ["core"]}})
    assert "nett" in str(e.value) and "core" in str(e.value)


def test_the_targets_are_sorted_by_name(tmp_path):
    # arrange: the order targets come back in decides the order of `add_subdirectory` and of the
    # solution's project rows, and both are committed
    root = _tree(tmp_path, "src/zeta/a.cpp", "src/alpha/a.cpp", "src/mid/a.cpp")

    # act / assert
    assert [t.name for t in buildfiles.read_tree(root, {})] == ["alpha", "mid", "zeta"]


def test_an_override_carries_the_include_paths_a_directory_cannot_show(tmp_path):
    # arrange
    root = _tree(tmp_path, "src/net/b.cpp")

    # act
    targets = buildfiles.read_tree(root, {"net": {"include": ["vendor/asio/include"]}})

    # assert
    assert targets[0].include == ["vendor/asio/include"]


def test_a_target_directory_is_relative_to_the_root_so_the_model_travels(tmp_path):
    # arrange: an absolute path here would put a tmp_path into a committed file
    root = _tree(tmp_path, "src/core/a.cpp")

    # act
    target = buildfiles.read_tree(root, {})[0]

    # assert
    assert target.directory == Path("src/core")
    assert target.sources == [Path("src/core/a.cpp")]


def test_a_dotnet_test_directory_becomes_one_test_target(tmp_path):
    # arrange: the .NET half of the spec's table - a DIRECTORY under tests/ is one test project, where
    # the C++ half makes one target per file
    root = _tree(tmp_path, "src/Core/A.cs", "tests/CoreTests/ATest.cs", "tests/CoreTests/BTest.cs")

    # act
    targets = {t.name: t for t in buildfiles.read_tree(root, {})}

    # assert
    assert targets["CoreTests"].kind == "test"
    assert targets["CoreTests"].directory == Path("tests/CoreTests")
    assert [p.name for p in targets["CoreTests"].sources] == ["ATest.cs", "BTest.cs"]


def test_a_malformed_depends_is_refused_rather_than_stringified(tmp_path, monkeypatch):
    # arrange: `depends: {core: yes}` is a typo, and turning it into one dependency named
    # "{'core': True}" writes that into a committed build file instead of saying so
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    root = _tree(tmp_path, "src/core/a.cpp", "src/net/b.cpp")

    # act / assert
    with pytest.raises(RuntimeError) as e:
        buildfiles.read_tree(root, {"net": {"depends": {"core": True}}})
    assert "net" in str(e.value) and "depends" in str(e.value)


def test_a_refusal_stops_rather_than_falling_through(tmp_path, monkeypatch):
    # arrange: `log.die` exits, and the line after it must not assume otherwise - a fall-through here
    # ends in a KeyError where the reader was promised a diagnosis
    monkeypatch.setattr(buildfiles.log, "die", lambda m, *a, **k: None)
    root = _tree(tmp_path, "src/core/a.cpp")

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.read_tree(root, {"nett": {"depends": ["core"]}})


def test_two_directories_that_would_carry_one_target_name_are_refused(tmp_path, monkeypatch):
    # arrange: `src/core/` is the library `core` and `tests/core/` is the test project `core`, and
    # CMake refuses the second `add_library(core ...)` outright - so the generated tree could not have
    # configured. What the model did instead was worse than the CMake error: `_overridden` round-tripped
    # the list through a dict keyed on the name, so ONE of the two silently replaced the other and the
    # library vanished from a file nobody would look at again
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    root = _tree(tmp_path, "src/core/a.cpp", "tests/core/b.cpp")

    # act / assert: the name, and BOTH directories, because the way out is renaming one of them
    with pytest.raises(RuntimeError) as e:
        buildfiles.read_tree(root, {})
    assert "core" in str(e.value)
    assert "src/core" in str(e.value) and "tests/core" in str(e.value)


def test_the_duplicate_refusal_stops_rather_than_falling_through(tmp_path, monkeypatch):
    # arrange: same rule as every other refusal here - `log.die` may exit, and the code after it must
    # not be reached on the assumption that it did not
    monkeypatch.setattr(buildfiles.log, "die", lambda m, *a, **k: None)
    root = _tree(tmp_path, "src/core/a.cpp", "tests/core/b.cpp")

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.read_tree(root, {})
