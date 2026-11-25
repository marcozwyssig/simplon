"""`test:unit` (si#859, D7): a product's own pytest suite, run in a venv the kernel provisions.

AGAINST A REAL PRODUCT, NOT A STUB. Every test here writes a temporary product (a requirements file and
test files), and the task builds a real venv with the host's `python3` and installs into it with real
pip. A stub of pip or pytest would confirm exactly the assumptions written into it, and the defects this
task is about live in what those two tools really do: pip half-installing a requirements file, a venv
keeping packages its requirements file no longer names, pytest exiting 5 on an empty collection.

WHAT THIS MODULE NEEDS FROM THE MACHINE: `python3` with venv support on PATH (what `ensure_venv` needs
for `test:gate` too), and a package index pip can reach, because pytest itself and the packages named
below are installed from it. The suite has no offline-index convention to follow; pip's own cache keeps
the repeat cost low.

The tests that only need SOME venv share one module-scoped product, each in a directory of its own; the
tests whose subject IS the venv (rebuild, a failed install, which pytest runs) build their own.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from simplon.manifest import context
from simplon.tasks import unittests

PASSING = "def test_passes():\n    assert True\n"


def _product(root: Path, requirements: str = "# no runtime dependencies\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "requirements.txt").write_text(requirements)
    return root


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _as_current(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(context, "_current", context.ProductContext("demo", root, root / "demo.yaml"))


@pytest.fixture(scope="module")
def shared(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _product(tmp_path_factory.mktemp("product"))


@pytest.fixture
def product(shared: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _as_current(monkeypatch, shared)
    return shared


def test_a_passing_root_is_green(product: Path, capfd: pytest.CaptureFixture[str]) -> None:
    _write(product, "green/test_green.py", PASSING)

    rc = unittests.run(paths=["green"], requirements="requirements.txt")

    assert rc == 0
    assert "1 passed" in capfd.readouterr().out


def test_a_failing_test_is_red(product: Path) -> None:
    _write(product, "red/test_red.py", "def test_fails():\n    assert False\n")

    rc = unittests.run(paths=["red"], requirements="requirements.txt")

    assert rc != 0


def test_two_roots_run_in_one_invocation(product: Path, capfd: pytest.CaptureFixture[str]) -> None:
    _write(product, "one/test_one.py", PASSING)
    _write(product, "two/test_two.py", PASSING)

    rc = unittests.run(paths=["one", "two"], requirements="requirements.txt")

    assert rc == 0
    assert "2 passed" in capfd.readouterr().out


def test_an_empty_collection_is_red_and_names_the_paths(product: Path,
                                                        capfd: pytest.CaptureFixture[str]) -> None:
    # pytest exits 5 on "no tests ran"; a gate that read that as anything but red would be green
    # precisely because the suite it guards is gone.
    _write(product, "hollow/helpers.py", "VALUE = 1\n")

    rc = unittests.run(paths=["hollow"], requirements="requirements.txt")

    assert rc != 0
    err = capfd.readouterr().err
    assert "hollow" in err
    assert "no tests" in err


def test_a_missing_path_is_refused_before_pytest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    _write(root, "here/test_here.py", PASSING)

    with pytest.raises(context.TaskRefused, match="not/there"):
        unittests.run(paths=["here", "not/there"], requirements="requirements.txt")

    # Refused before anything was provisioned, not only before pytest.
    assert not (root / "build").exists()


def test_no_paths_is_refused_with_the_form_to_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _as_current(monkeypatch, _product(tmp_path))

    with pytest.raises(context.TaskRefused, match="paths"):
        unittests.run(paths=[], requirements="requirements.txt")


def test_paths_that_are_not_a_list_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A bare string would otherwise be iterated letter by letter into roots named `t`, `e`, ...
    _as_current(monkeypatch, _product(tmp_path))

    with pytest.raises(context.TaskRefused, match="list"):
        unittests.run(paths="tests", requirements="requirements.txt")  # type: ignore[arg-type]


def test_no_requirements_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    _write(root, "t/test_t.py", PASSING)

    with pytest.raises(context.TaskRefused, match="requirements"):
        unittests.run(paths=["t"], requirements="")


def test_a_missing_requirements_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    _write(root, "t/test_t.py", PASSING)

    with pytest.raises(context.TaskRefused, match="nope.txt"):
        unittests.run(paths=["t"], requirements="nope.txt")


def test_a_missing_config_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    _write(root, "t/test_t.py", PASSING)

    with pytest.raises(context.TaskRefused, match="absent.ini"):
        unittests.run(paths=["t"], requirements="requirements.txt", config="absent.ini")


def test_pytest_is_installed_only_when_the_requirements_lack_it(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch,
                                                               capfd: pytest.CaptureFixture[str]) -> None:
    # Without pytest in the requirements: the kernel adds pytest, UNPINNED (Marco, si#859), and says so
    # in one line. The stamp then freezes what was installed until the requirements change.
    bare = _product(tmp_path / "bare")
    _write(bare, "t/test_t.py", PASSING)
    _as_current(monkeypatch, bare)
    assert unittests.run(paths=["t"], requirements="requirements.txt") == 0
    out = capfd.readouterr().out
    added = [line for line in out.splitlines() if "added" in line]
    assert len(added) == 1 and "added pytest" in added[0] and "pytest==" not in added[0]
    kernels = re.search(r"pytest-(\S+),", out)
    assert kernels

    # With pytest pinned in the requirements: no second install, and THAT version is what runs. The pin
    # is an older release than the one the kernel just installed, so the header shows which install ran.
    pinned_version = "8.4.2"
    assert pinned_version != kernels.group(1)
    pinned = _product(tmp_path / "pinned", f"pytest=={pinned_version}\n")
    _write(pinned, "t/test_t.py", PASSING)
    _as_current(monkeypatch, pinned)
    assert unittests.run(paths=["t"], requirements="requirements.txt") == 0
    out = capfd.readouterr().out
    assert "added" not in out
    assert f"pytest-{pinned_version}" in out


def test_a_changed_requirements_file_rebuilds_the_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A venv cached on nothing keeps what it was first given: the recurring defect. Both directions are
    # driven, because `pip install -r` alone would satisfy the first and never the second.
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    _write(root, "t/test_six.py",
           "import importlib.util\n\ndef test_six_is_there():\n"
           "    assert importlib.util.find_spec('six') is not None\n")

    assert unittests.run(paths=["t"], requirements="requirements.txt") != 0

    (root / "requirements.txt").write_text("six==1.17.0\n")
    assert unittests.run(paths=["t"], requirements="requirements.txt") == 0

    (root / "requirements.txt").write_text("# six dropped again\n")
    assert unittests.run(paths=["t"], requirements="requirements.txt") != 0


def test_an_unchanged_requirements_file_reuses_the_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                        capfd: pytest.CaptureFixture[str]) -> None:
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    _write(root, "t/test_t.py", PASSING)
    assert unittests.run(paths=["t"], requirements="requirements.txt") == 0
    capfd.readouterr()

    assert unittests.run(paths=["t"], requirements="requirements.txt") == 0

    out = capfd.readouterr().out
    assert "added" not in out
    assert "reused" in out


def test_a_requirement_that_does_not_install_is_red_quoting_pip(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch,
                                                               capfd: pytest.CaptureFixture[str]) -> None:
    root = _product(tmp_path, "si859-no-such-distribution==0.0.0\n")
    _as_current(monkeypatch, root)
    _write(root, "t/test_t.py", PASSING)

    rc = unittests.run(paths=["t"], requirements="requirements.txt")

    assert rc != 0
    captured = capfd.readouterr()
    assert "si859-no-such-distribution" in captured.err
    assert "No matching distribution" in captured.err
    # Never a run of pytest against the half-built venv.
    assert "test session starts" not in captured.out

    # And the half-built venv is not taken for a finished one on the next run: the same file fails the
    # same way, quoting pip again, rather than reaching pytest.
    assert unittests.run(paths=["t"], requirements="requirements.txt") != 0
    captured = capfd.readouterr()
    assert "No matching distribution" in captured.err
    assert "test session starts" not in captured.out

    (root / "requirements.txt").write_text("# fixed\n")
    assert unittests.run(paths=["t"], requirements="requirements.txt") == 0


def test_config_is_passed_as_c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The configuration names a collection pattern the default would never match, so the one test here
    # is collected only when the file is really read: without it the collection is empty, which is red.
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    _write(root, "ci/unit.ini", "[pytest]\npython_files = check_*.py\n")
    _write(root, "t/check_thing.py", PASSING)

    assert unittests.run(paths=["t"], requirements="requirements.txt") != 0
    assert unittests.run(paths=["t"], requirements="requirements.txt", config="ci/unit.ini") == 0


def test_conftest_sys_path_inserts_resolve_from_the_product_root(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    # cleon, asbundle and cleon-firn put their own sources on sys.path from a conftest. This one spells
    # the path relative to the WORKING DIRECTORY, so it resolves only when pytest runs from the root.
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    monkeypatch.chdir(tmp_path.parent)
    _write(root, "src/python/mylib.py", "ANSWER = 42\n")
    _write(root, "block/tests/conftest.py",
           "import os, sys\nsys.path.insert(0, os.path.abspath('src/python'))\n")
    _write(root, "block/tests/test_lib.py",
           "import mylib\n\ndef test_answer():\n    assert mylib.ANSWER == 42\n")

    assert unittests.run(paths=["block/tests"], requirements="requirements.txt") == 0



def test_a_root_with_no_tests_beside_one_with_tests_is_red(product: Path,
                                                            capfd: pytest.CaptureFixture[str]) -> None:
    # `pytest a b` with `b` empty exits 0: the run alone cannot see an empty root, and the help text
    # promises that a root with no tests is red (#674, folded into si#859).
    _write(product, "full/test_full.py", PASSING)
    _write(product, "void/helpers.py", "VALUE = 1\n")

    rc = unittests.run(paths=["full", "void"], requirements="requirements.txt")

    assert rc != 0
    err = capfd.readouterr().err
    assert "void" in err and "full" not in err.split("no tests")[-1]


def test_a_run_past_its_timeout_is_red_and_says_so(product: Path, capfd: pytest.CaptureFixture[str]) -> None:
    _write(product, "slow/test_slow.py", "import time\n\ndef test_sleeps():\n    time.sleep(30)\n")

    rc = unittests.run(paths=["slow"], requirements="requirements.txt", timeout=3)

    assert rc != 0
    err = capfd.readouterr().err
    assert "3 s" in err and "timeout" in err


@pytest.mark.parametrize("timeout", [0, -1])
def test_a_timeout_that_is_no_limit_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              timeout: int) -> None:
    root = _product(tmp_path)
    _as_current(monkeypatch, root)
    _write(root, "t/test_t.py", PASSING)

    with pytest.raises(context.TaskRefused, match="timeout"):
        unittests.run(paths=["t"], requirements="requirements.txt", timeout=timeout)


def test_the_default_timeout_is_named() -> None:
    assert unittests.UNIT_TIMEOUT == 1800


def test_a_changed_included_requirements_file_rebuilds_the_venv(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    # The top-level file pulls the real list in with `-r`; a change there must reach the stamp too.
    root = _product(tmp_path, "-r deps/base.txt\n")
    _write(root, "deps/base.txt", "-c pins.txt\n")
    _write(root, "deps/pins.txt", "# no pins\n")
    _as_current(monkeypatch, root)
    _write(root, "t/test_six.py",
           "import importlib.util\n\ndef test_six_is_there():\n"
           "    assert importlib.util.find_spec('six') is not None\n")
    assert unittests.run(paths=["t"], requirements="requirements.txt") != 0

    (root / "deps/base.txt").write_text("-c pins.txt\nsix\n")
    (root / "deps/pins.txt").write_text("six==1.17.0\n")
    assert unittests.run(paths=["t"], requirements="requirements.txt") == 0

    # Only the constraint two levels down changes: the venv is rebuilt against it.
    (root / "deps/pins.txt").write_text("six==1.16.0\n")
    _write(root, "t/test_six.py",
           "import six\n\ndef test_six_version():\n    assert six.__version__ == '1.16.0'\n")
    assert unittests.run(paths=["t"], requirements="requirements.txt") == 0


@pytest.mark.parametrize("field", ["requirements", "config", "paths"])
@pytest.mark.parametrize("escape", ["absolute", "dotdot"])
def test_a_path_outside_the_product_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                    field: str, escape: str) -> None:
    root = _product(tmp_path / "product")
    _as_current(monkeypatch, root)
    _write(root, "t/test_t.py", PASSING)
    outside = tmp_path / "elsewhere"
    _write(outside, "requirements.txt", "# outside\n")
    _write(outside, "pytest.ini", "[pytest]\n")
    _write(outside, "test_o.py", PASSING)
    target = {"requirements": "requirements.txt", "config": "pytest.ini", "paths": ""}[field]
    spelled = str(outside / target) if escape == "absolute" else f"../elsewhere/{target}".rstrip("/")
    kwargs: dict[str, object] = {"paths": ["t"], "requirements": "requirements.txt"}
    kwargs[field] = [spelled] if field == "paths" else spelled

    with pytest.raises(context.TaskRefused, match="product root"):
        unittests.run(**kwargs)  # type: ignore[arg-type]
