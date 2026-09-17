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
        buildfiles.Target(name="core", kind="static", directory=Path("src/core"),
                          sources=[Path("src/core/a.cpp"), Path("src/core/b.cpp")]),
        buildfiles.Target(name="core_test", kind="test", directory=Path("tests"),
                          sources=[Path("tests/core_test.cpp")]),
        buildfiles.Target(name="net", kind="shared", directory=Path("src/net"),
                          sources=[Path("src/net/b.cpp"), Path("src/net/tcp/socket.cpp")],
                          depends=["core"], include=["vendor/asio/include"]),
        buildfiles.Target(name="net_test", kind="test", directory=Path("src/net"),
                          sources=[Path("src/net/net_test.cpp")], depends=["net"],
                          level=buildfiles.UNIT_LEVEL),
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


def test_a_nested_source_is_rendered_relative_to_the_target_it_folded_into():
    # arrange / act: `src/net/tcp/socket.cpp` is a source of `net`, whose CMakeLists.txt sits in
    # src/net - so the path in the file is the one CMake resolves from there (si#131)
    text = _files()[Path("/product/src/net/CMakeLists.txt")]

    # assert: and nothing was written for the nested directory, because it is not a target
    assert "add_library(net SHARED b.cpp tcp/socket.cpp)" in text
    assert Path("/product/src/net/tcp/CMakeLists.txt") not in _files()


def test_a_static_library_says_STATIC_rather_than_leaving_it_to_BUILD_SHARED_LIBS():
    # act
    text = _files()[Path("/product/src/core/CMakeLists.txt")]

    # assert: the keyword is WRITTEN OUT (si#131). A bare `add_library` follows BUILD_SHARED_LIBS,
    # which nobody sets, so the file said nothing about what it produced and no product could have both
    assert "add_library(core STATIC a.cpp b.cpp)" in text


def test_a_shared_library_says_SHARED():
    # act
    text = _files()[Path("/product/src/net/CMakeLists.txt")]

    # assert
    assert "add_library(net SHARED b.cpp tcp/socket.cpp)" in text


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


def test_a_library_exports_its_own_directory_so_a_consumer_finds_its_headers():
    # act: PRIVATE was the defect - the directory compiled the target and was inherited by nothing, so
    # a library whose headers no consumer could find was the only kind this generator produced (si#131)
    text = _files()[Path("/product/src/core/CMakeLists.txt")]

    # assert
    assert 'target_include_directories(core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")' in text


def test_an_executable_exports_nothing_because_nothing_links_it():
    # act
    text = _files()[Path("/product/src/app/CMakeLists.txt")]

    # assert: no line at all, rather than a PUBLIC one that says nothing to anybody
    assert "target_include_directories" not in text


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


def test_a_level_becomes_a_ctest_label_and_no_level_becomes_no_line():
    # act: a level is a fact about the build rather than about a path only once ctest can select on it
    colocated = _files()[Path("/product/src/net/CMakeLists.txt")]
    levelless = _files()[Path("/product/tests/CMakeLists.txt")]

    # assert
    assert 'set_tests_properties(net_test PROPERTIES LABELS "unit")' in colocated
    assert "set_tests_properties" not in levelless


def test_a_co_located_unit_test_is_its_own_executable_beside_the_library():
    # act: both targets in one file, because the test sits in the library's own directory (si#134)
    text = _files()[Path("/product/src/net/CMakeLists.txt")]

    # assert: and the library's source list does not carry the test
    assert "add_executable(net_test net_test.cpp)" in text
    assert "target_link_libraries(net_test PRIVATE net)" in text
    assert "net_test.cpp" not in text.split("add_executable(net_test")[0]


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
    assert ('target_include_directories(net PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}" '
            '"${CMAKE_SOURCE_DIR}/vendor/asio/include")') in text


def test_an_absolute_include_is_left_alone():
    # arrange: a product naming a path outside its own tree means it
    targets = [buildfiles.Target(name="net", kind="executable", directory=Path("src/net"),
                                 sources=[Path("src/net/main.cpp")], include=["/opt/vendor/include"])]

    # act
    text = buildfiles.render_cmake(targets, Path("src/net"))

    # assert
    assert 'target_include_directories(net PRIVATE "/opt/vendor/include")' in text


def test_an_include_path_holding_a_space_stays_one_argument():
    # arrange: CMake splits an UNQUOTED argument on whitespace and on `;`, so a directory a real
    # filesystem allows - "Program Files", a vendor drop with a space - would arrive as two arguments
    # naming two directories that do not exist. Quoting is what a hand-written CMakeLists does, and it
    # costs a product nothing it could otherwise have said
    targets = [buildfiles.Target(name="net", kind="executable", directory=Path("src/net"),
                                 sources=[Path("src/net/main.cpp")],
                                 include=["vendor/asio 1.30/include"])]

    # act
    text = buildfiles.render_cmake(targets, Path("src/net"))

    # assert
    assert ('target_include_directories(net PRIVATE '
            '"${CMAKE_SOURCE_DIR}/vendor/asio 1.30/include")') in text


def test_a_co_located_test_rendered_before_its_library_still_links_it():
    """Targets are sorted by NAME, and `_test` does not sort last: `n_test` precedes `net`, so a
    co-located unit test can be written into the file ahead of the library it links.

    THAT IS LEGAL AND IT WAS MEASURED RATHER THAN ASSUMED (silkeh/clang:19, 2026-09-09). CMake requires
    the target being MODIFIED to exist - `n_test` does - and resolves the names in the list at generate
    time, so a library defined further down the same file is found, and its PUBLIC include directory
    reaches the test's compile as well. The rendered tree above configured, compiled and passed its
    ctest case in that order.

    It is pinned here because the alternative repair is the tempting one: sorting libraries first would
    look tidier, churn every generated file, and defend against nothing.
    """
    # arrange
    targets = [
        buildfiles.Target(name="n_test", kind="test", directory=Path("src/net"),
                          sources=[Path("src/net/n_test.cpp")], depends=["net"],
                          level=buildfiles.UNIT_LEVEL),
        buildfiles.Target(name="net", kind="static", directory=Path("src/net"),
                          sources=[Path("src/net/net.cpp")]),
    ]

    # act
    text = buildfiles.render_cmake(targets, Path("src/net"))

    # assert
    assert text.index("add_executable(n_test") < text.index("add_library(net STATIC")
    assert "target_link_libraries(n_test PRIVATE net)" in text
