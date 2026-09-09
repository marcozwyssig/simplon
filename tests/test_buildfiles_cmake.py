"""si#102: CMake rendered from the model, purely and in a fixed order.

Every assertion here is a string comparison, and that is the point of the renderers being pure: the
decisions - which target, which order, which link line - are exactly what a test should be able to read
without a compiler or a filesystem in the room.
"""
from pathlib import Path

from simplon.tasks import buildfiles


def _targets():
    return [
        buildfiles.Target(name="app", kind="executable", directory=Path("src/app"),
                          sources=[Path("src/app/main.cpp")]),
        buildfiles.Target(name="core", kind="library", directory=Path("src/core"),
                          sources=[Path("src/core/a.cpp"), Path("src/core/b.cpp")]),
        buildfiles.Target(name="core_test", kind="test", directory=Path("tests"),
                          sources=[Path("tests/core_test.cpp")]),
        buildfiles.Target(name="net", kind="library", directory=Path("src/net"),
                          sources=[Path("src/net/b.cpp")], depends=["core"],
                          include=["vendor/asio/include"]),
    ]


def _files(root=Path("/product"), product="product"):
    return buildfiles.cmake_files(_targets(), root, product)


def test_the_root_file_carries_the_minimum_version_and_the_project():
    # act
    text = _files()[Path("/product/CMakeLists.txt")]

    # assert
    assert "cmake_minimum_required(" in text
    assert "project(product " in text


def test_the_root_file_carries_one_sorted_add_subdirectory_per_target_directory():
    # arrange / act
    text = _files()[Path("/product/CMakeLists.txt")]

    # assert: sorted, and each directory once even though `tests` holds several targets
    lines = [ln for ln in text.splitlines() if ln.startswith("add_subdirectory(")]
    assert lines == ["add_subdirectory(src/app)", "add_subdirectory(src/core)",
                     "add_subdirectory(src/net)", "add_subdirectory(tests)"]


def test_a_library_directory_carries_add_library_with_its_sources_sorted():
    # act
    text = _files()[Path("/product/src/core/CMakeLists.txt")]

    # assert
    assert "add_library(core a.cpp b.cpp)" in text


def test_an_executable_directory_carries_add_executable():
    # act
    text = _files()[Path("/product/src/app/CMakeLists.txt")]

    # assert
    assert "add_executable(app main.cpp)" in text


def test_a_declared_dependency_becomes_a_link_line():
    # act
    text = _files()[Path("/product/src/net/CMakeLists.txt")]

    # assert
    assert "target_link_libraries(net PRIVATE core)" in text


def test_a_target_with_no_dependency_links_nothing():
    # act: the tree does not show a dependency, so none is invented (spec section 2)
    text = _files()[Path("/product/src/core/CMakeLists.txt")]

    # assert
    assert "target_link_libraries" not in text


def test_a_test_target_is_built_and_registered_with_ctest():
    # act
    text = _files()[Path("/product/tests/CMakeLists.txt")]

    # assert
    assert "add_executable(core_test core_test.cpp)" in text
    assert "add_test(NAME core_test COMMAND core_test)" in text


def test_ctest_is_enabled_at_the_root_when_there_is_a_test():
    # act / assert: `add_test` in a subdirectory does nothing without this line at the top
    assert "enable_testing()" in _files()[Path("/product/CMakeLists.txt")]


def test_every_generated_file_starts_with_the_header():
    # act / assert: a file without one sends the reader looking for what overwrote it
    for path, text in _files().items():
        assert text.startswith(buildfiles.HEADER), path


def test_the_header_answers_both_questions_a_surprise_raises():
    # assert: what overwrote this, and where to change it instead (spec section 3)
    assert "DO NOT EDIT" in buildfiles.HEADER
    assert "reverted on the next run" in buildfiles.HEADER
    assert "manifest" in buildfiles.HEADER


def test_rendering_the_same_targets_twice_returns_equal_strings():
    # act: the committed-output decision rests on this
    first = buildfiles.render_cmake(_targets(), Path("src/core"))
    second = buildfiles.render_cmake(_targets(), Path("src/core"))

    # assert
    assert first == second


def test_two_runs_over_two_roots_render_the_same_bytes():
    # arrange / act: two checkouts of one product, in two places, and DELIBERATELY NOT CALLED THE SAME -
    # an agent worktree, a CI job that clones into `work/`, a second clone beside the first. The root
    # decides where the files land and nothing else about it may reach the bytes, which is why the
    # project is named from the product rather than from `root.name`. With both roots called `product`
    # this assertion held while the name still came from the directory.
    here = buildfiles.cmake_files(_targets(), Path("/one/product"), "demo")
    there = buildfiles.cmake_files(_targets(), Path("/elsewhere/product-worktree-2"), "demo")

    # assert
    assert [t for _, t in sorted(here.items())] == [t for _, t in sorted(there.items())]


def test_every_file_ends_with_exactly_one_newline():
    # act / assert: a tail that grows with the number of targets is whitespace in a review
    for path, text in _files().items():
        assert text.endswith("\n") and not text.endswith("\n\n"), path


def test_a_declared_include_is_anchored_at_the_product_root():
    # arrange: `include: [vendor/asio/include]` names a directory at the ROOT (spec section 2), but the
    # line lands in src/net/CMakeLists.txt, where CMake resolves a relative path against
    # CMAKE_CURRENT_SOURCE_DIR - so the bare string would point at src/net/vendor/asio/include
    text = _files()[Path("/product/src/net/CMakeLists.txt")]

    # act / assert
    assert ('target_include_directories(net PRIVATE "${CMAKE_SOURCE_DIR}/vendor/asio/include")') in text


def test_an_absolute_include_is_left_alone():
    # arrange: a product naming a path outside its own tree means it
    targets = [buildfiles.Target(name="net", kind="library", directory=Path("src/net"),
                                 sources=[Path("src/net/b.cpp")], include=["/opt/vendor/include"])]

    # act
    text = buildfiles.render_cmake(targets, Path("src/net"))

    # assert
    assert 'target_include_directories(net PRIVATE "/opt/vendor/include")' in text


def test_an_include_path_holding_a_space_stays_one_argument():
    # arrange: CMake splits an UNQUOTED argument on whitespace and on `;`, so a directory a real
    # filesystem allows - "Program Files", a vendor drop with a space - would arrive as two arguments
    # naming two directories that do not exist. Quoting is what a hand-written CMakeLists does, and it
    # costs a product nothing it could otherwise have said
    targets = [buildfiles.Target(name="net", kind="library", directory=Path("src/net"),
                                 sources=[Path("src/net/b.cpp")],
                                 include=["vendor/asio 1.30/include"])]

    # act
    text = buildfiles.render_cmake(targets, Path("src/net"))

    # assert
    assert ('target_include_directories(net PRIVATE '
            '"${CMAKE_SOURCE_DIR}/vendor/asio 1.30/include")') in text
