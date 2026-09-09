"""si#102: the two coordinates that WRITE, and what a run of one has to be able to say.

Everything in `simplon.tasks.buildfiles` up to here returns data or a string. These two functions are
the only ones that touch a disk, so this file is the only one that may not stub the disk away. That is
not a preference: simplon 0.8.0 shipped a uniform build no product could drive because every test
behind it stubbed the thing under test, and a generator whose output never landed anywhere is not a
generator that was tested. So `tmp_path` holds a real product tree, a real manifest is read from it,
and every assertion below looks at what is on the disk afterwards.
"""
import pytest
import yaml

from simplon import context
from simplon.context import ProductContext
from simplon.tasks import buildfiles


def _product(monkeypatch, tmp_path, manifest, *sources):
    """A real product on disk: the named sources, a real manifest, and the context registered.

    The manifest is WRITTEN rather than monkeypatched onto `manifest_data`, because the `targets:`
    block reaching `read_tree` is one of the five behaviours under test here and a stub would assert
    that a dict travels between two variables.
    """
    for rel in sources:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// x\n", encoding="utf-8")
    (tmp_path / "demo.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    return tmp_path


# --- 1. the files land where the model says ---------------------------------------------------------


def test_the_cmake_files_land_exactly_where_the_model_says(monkeypatch, tmp_path):
    # arrange
    root = _product(monkeypatch, tmp_path, {},
                    "src/core/a.cpp", "src/app/main.cpp", "tests/core_test.cpp")

    # act
    rc = buildfiles.cmake()

    # assert: the model's own keys, compared against the disk - a hand-written list of paths here would
    # be a second statement of where the files go, and the two would drift
    expected = set(buildfiles.cmake_files(buildfiles.read_tree(root, {}), root, "demo"))
    assert rc == 0
    assert set(root.rglob("CMakeLists.txt")) == expected


def test_the_dotnet_files_land_exactly_where_the_model_says(monkeypatch, tmp_path):
    # arrange
    root = _product(monkeypatch, tmp_path, {}, "src/Core/Thing.cs", "src/App/Program.cs")

    # act
    rc = buildfiles.dotnet()

    # assert
    expected = set(buildfiles.dotnet_files(buildfiles.read_tree(root, {}), root, "demo"))
    assert rc == 0
    assert set(root.rglob("*.sln")) | set(root.rglob("*.csproj")) == expected


def test_the_project_is_named_after_the_product_and_not_after_the_checkout(monkeypatch, tmp_path):
    # arrange: `tmp_path` is not called `demo`, which is the whole point - an agent worktree and a CI
    # job clone the same product into directories with different names, and a committed file must not
    # change because of that
    root = _product(monkeypatch, tmp_path, {}, "src/core/a.cpp")

    # act
    buildfiles.cmake()

    # assert
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "project(demo " in text
    assert root.name not in text


def test_a_generated_file_carries_the_header_on_the_disk_too(monkeypatch, tmp_path):
    # arrange
    root = _product(monkeypatch, tmp_path, {}, "src/core/a.cpp")

    # act
    buildfiles.cmake()

    # assert
    assert (root / "src/core/CMakeLists.txt").read_text(encoding="utf-8").startswith(buildfiles.HEADER)


# --- 2. a hand edit is REVERTED, which is the opposite of si#101 -------------------------------------


def test_a_hand_edited_file_is_replaced(monkeypatch, tmp_path):
    # arrange: si#101 never clobbers a manifest because a manifest is a product's own statement; a
    # CMakeLists.txt is a RENDERING of one, and reverting a rendering is the whole point (spec section 2)
    root = _product(monkeypatch, tmp_path, {}, "src/core/a.cpp")
    edited = root / "src/core/CMakeLists.txt"
    edited.write_text("add_library(core my-own.cpp)\n", encoding="utf-8")

    # act
    rc = buildfiles.cmake()

    # assert
    text = edited.read_text(encoding="utf-8")
    assert rc == 0
    assert "my-own.cpp" not in text
    assert text.startswith(buildfiles.HEADER)


# --- 3. the run says which files it wrote ------------------------------------------------------------


def test_the_run_names_every_file_it_wrote(monkeypatch, tmp_path, capsys):
    # arrange: the generator overwrites without asking, so the report is the only place that difference
    # becomes visible before the diff does
    _product(monkeypatch, tmp_path, {}, "src/core/a.cpp", "tests/core_test.cpp")

    # act
    buildfiles.cmake()

    # assert
    said = capsys.readouterr().out
    for rel in ("CMakeLists.txt", "src/core/CMakeLists.txt", "tests/CMakeLists.txt"):
        assert rel in said


def test_the_report_names_the_files_relative_to_the_product_root(monkeypatch, tmp_path, capsys):
    # arrange: an absolute path names the machine that ran the generator, which is exactly what the
    # generated files themselves refuse to carry
    root = _product(monkeypatch, tmp_path, {}, "src/core/a.cpp")

    # act
    buildfiles.cmake()

    # assert
    assert str(root) not in capsys.readouterr().out


# --- 4. the manifest's `build: targets:` block reaches the tree read ----------------------------------


def test_the_manifests_targets_block_reaches_the_tree_read(monkeypatch, tmp_path):
    # arrange: the tree is the declaration and the manifest is the exception, so the ONE thing a
    # directory cannot show has to travel from the manifest into the rendered file
    root = _product(monkeypatch, tmp_path, {"build": {"targets": {"net": {"depends": ["core"]}}}},
                    "src/core/a.cpp", "src/net/b.cpp")

    # act
    buildfiles.cmake()

    # assert
    assert "target_link_libraries(net PRIVATE core)" in \
        (root / "src/net/CMakeLists.txt").read_text(encoding="utf-8")


def test_the_same_block_reaches_the_dotnet_half(monkeypatch, tmp_path):
    # arrange
    root = _product(monkeypatch, tmp_path, {"build": {"targets": {"Net": {"depends": ["Core"]}}}},
                    "src/Core/a.cs", "src/Net/b.cs")

    # act
    buildfiles.dotnet()

    # assert: the reference names the project the manifest pointed at, not merely some project
    assert '<ProjectReference Include="../Core/Core.csproj" />' in \
        (root / "src/Net/Net.csproj").read_text(encoding="utf-8")


def test_a_targets_key_naming_no_target_is_still_refused_through_the_manifest(
        monkeypatch, tmp_path, capsys):
    # arrange: `read_tree` refuses a typo, and reading the manifest must not be the layer that swallows
    # the refusal on its way to a person
    _product(monkeypatch, tmp_path, {"build": {"targets": {"nett": {"depends": ["core"]}}}},
             "src/core/a.cpp")

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.cmake()
    assert "nett" in capsys.readouterr().err


def test_a_targets_entry_that_is_not_a_mapping_is_refused_by_name(monkeypatch, tmp_path, capsys):
    # arrange: `targets: { net: core }` is a plausible typo for `net: { depends: [core] }`, and reaching
    # `read_tree` with it is an AttributeError where this module promises a diagnosis
    _product(monkeypatch, tmp_path, {"build": {"targets": {"net": "core"}}},
             "src/core/a.cpp", "src/net/b.cpp")

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.cmake()
    assert "net" in capsys.readouterr().err


def test_a_build_section_that_is_not_a_mapping_is_refused(monkeypatch, tmp_path, capsys):
    # arrange
    _product(monkeypatch, tmp_path, {"build": "cpp"}, "src/core/a.cpp")

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.cmake()
    assert "build" in capsys.readouterr().err


# --- 5. a tree with no target is REFUSED, not written -------------------------------------------------


def test_a_product_with_no_target_is_refused_rather_than_written(monkeypatch, tmp_path, capsys):
    # arrange: an empty project compiles, produces nothing, and is committed - the worst of the three
    root = _product(monkeypatch, tmp_path, {})

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.cmake()
    assert not (root / "CMakeLists.txt").exists()
    assert "src/" in capsys.readouterr().err


def test_the_dotnet_half_refuses_the_same_tree(monkeypatch, tmp_path):
    # arrange
    root = _product(monkeypatch, tmp_path, {})

    # act / assert
    with pytest.raises(SystemExit):
        buildfiles.dotnet()
    assert not (root / "demo.sln").exists()
