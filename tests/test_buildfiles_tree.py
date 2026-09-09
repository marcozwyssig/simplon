"""si#102: the source tree read as the declaration it is."""
from pathlib import Path

import pytest

from simplon.tasks import buildfiles


def _tree(tmp_path, *paths):
    for rel in paths:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// x\n")
    return tmp_path


def test_a_source_directory_without_a_main_is_a_library(tmp_path):
    # arrange
    root = _tree(tmp_path, "src/core/a.cpp", "src/core/b.cpp")

    # act
    targets = buildfiles.read_tree(root, {})

    # assert
    assert [(t.name, t.kind) for t in targets] == [("core", "library")]


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
    assert kinds == {"core": "library", "core_test": "test"}


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
