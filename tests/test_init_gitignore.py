"""What `simplon init` scaffolds into a product's `.gitignore`, held to git's own verdict (si#155).

WHY THE ASSERTION IS `git status --porcelain` AND NOT A LINE IN A FILE. An ignore rule is not text, it is
a verdict over a path, and the two come apart in both directions: a pattern in the right file with the
wrong anchoring ignores nothing, and a pattern that is too broad ignores something the kernel generates
to be COMMITTED. Neither shows in a `in body` check. So every test below either runs `git status` over a
tree something really wrote into, or runs `git check-ignore`, which is the same engine answering about
one path.

WHY THE BLOCK IS ALSO HELD TO THE KERNEL'S OWN CONSTANTS. `bootstrap` may not import a single task
module - it is the ONE kernel entry that runs with no product context, before yaml or docker or typer are
on the path - so the paths in the block are typed there a second time. That is the same deliberate double
declaration `profiles.py` makes of `DEFAULT_ORCH_DIR`, and it is held the same way: from the test side,
where an import costs nothing.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simplon import bootstrap
from simplon.tasks import docs as docs_task
from simplon.tasks import profiles as profiles_task
from simplon.tasks import site as site_task
from simplon.tasks import testrun

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")

#: The rendered block, taken from the scaffold rather than retyped - a copy here would be a third
#: declaration of the same list and the first to go stale.
BLOCK = bootstrap.render("fooctl")[bootstrap.GITIGNORE]

#: Only the PATTERNS. Every "is this path named here" question below has to ask the rules and not the
#: prose: the block explains at length which paths it deliberately leaves out, so a plain substring
#: search over the text answers yes for `.venv` - the one name the block exists to say nothing about.
PATTERNS = [line for line in BLOCK.splitlines() if line and not line.startswith("#")]


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _repo(path: Path) -> Path:
    """A real git work tree, because `git check-ignore` and `git status` both refuse anything else."""
    path.mkdir(parents=True, exist_ok=True)
    assert _git("init", "-q", ".", cwd=path).returncode == 0
    return path


def _status(path: Path) -> str:
    done = _git("status", "--porcelain", cwd=path)
    assert done.returncode == 0, done.stderr
    return done.stdout


def _ignored(path: Path, relative: str) -> bool:
    """git's own verdict for one path. 0 means ignored, 1 means not; anything else is a broken tree."""
    done = _git("check-ignore", "-q", "--", relative, cwd=path)
    assert done.returncode in (0, 1), f"{relative}: rc {done.returncode} {done.stderr}"
    return done.returncode == 0


def _scaffolded(path: Path) -> Path:
    repo = _repo(path)
    bootstrap.write("fooctl", repo)
    return repo


# --- the verdict, over paths the kernel really writes --------------------------------------------------


#: The four untracked entries a scaffolded product answers with when it has no `.gitignore` at all,
#: measured by driving `./<p>.sh help`, `support toolchain python 3.12`, `build deps`, `build unit` and
#: `build analyse` on 2026-09-11. Reproduced here as files rather than as containers: what is under test
#: is the ignore rule, and a docker run would make this suite need a network to rule on a text file.
MEASURED = (
    ".simplon-toolchain/lib/python3.12/site-packages/mypy/__init__.py",
    f"{bootstrap.pkg_dir_for(bootstrap.DEFAULT_ORCH_DIR)}/__pycache__/cli.cpython-313.pyc",
    "src/__pycache__/test_add.cpython-312.pyc",
    "src/fooctl/__pycache__/__init__.cpython-312.pyc",
)

#: What the other kernel commands leave behind, each named by the constant that decides it rather than
#: retyped - so moving one of them turns this red instead of leaving a line here pointing at nothing.
WRITTEN = (
    f"{docs_task.OUTPUT_DIR}/html5/index.html",
    f"{docs_task.GRADLE_STATE}/8.14.3/fileHashes/fileHashes.bin",
    f"{site_task.CACHE_DIR}/modules/filecache/x",
    "build/logs/run-transcript.log",
    "build/tools/bin/docker",
    f"{testrun.REPORTS}/{testrun.RESULTS}/a1b2-result.json",
    f"{testrun.REPORTS}/{testrun.SCRATCH}/index.html",
    f"{testrun.REPORTS}/test-verdict.json",
    f"{testrun.REPORTS}/unit.xml",
    # The same two under a `reports:` the product moved, which is the case the unanchored pair exists
    # for: `reports:` is a manifest value and only its default sits under `tests/`.
    f"reports/{testrun.RESULTS}/a1b2-result.json",
    f"reports/{testrun.SCRATCH}/index.html",
)


def test_a_scaffold_leaves_git_with_nothing_to_report_after_the_kernel_has_written_to_the_tree(tmp_path):
    """The assertion si#155 asks for: not a line in a file, an empty `git status --porcelain`."""
    # arrange: a scaffolded product whose own files are committed, so only the kernel's droppings are left
    repo = _scaffolded(tmp_path / "fooctl")
    assert _git("add", "-A", cwd=repo).returncode == 0
    assert _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "scaffold",
                cwd=repo).returncode == 0
    assert _status(repo) == "", "the scaffold itself is not committed, so the act below rules on nothing"

    # act: put every measured and every constant-named output into the tree
    for relative in MEASURED + WRITTEN:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")

    # assert
    assert _status(repo) == "", "git can still see something the kernel wrote"


def test_without_the_block_git_sees_every_one_of_them(tmp_path):
    """The half that makes the test above an assertion: with the block removed, each path is visible.

    A rule that has never been seen failing is not yet a rule, and this one would pass on an empty
    `.gitignore` in a tree that happened to have nothing in it.
    """
    # arrange
    repo = _scaffolded(tmp_path / "fooctl")
    (repo / bootstrap.GITIGNORE).unlink()

    # act
    visible = {relative for relative in MEASURED + WRITTEN if not _ignored(repo, relative)}

    # assert
    assert visible == set(MEASURED + WRITTEN)


# --- the other side of the line: what must stay visible ------------------------------------------------


def test_the_generated_build_files_si102_commits_are_still_visible_to_git(tmp_path):
    """An ignore rule that swallowed these would reverse a decided question, and silently.

    Driven through the REAL generator over a real source tree rather than against a typed list of
    filenames, because where those files land is the generator's business: si#102 writes one
    CMakeLists.txt per target directory, and a directory is whatever `read_tree` found.
    """
    # arrange: a scaffolded product with a C++ and a .NET shaped source tree under it
    from simplon.tasks import buildfiles

    repo = _scaffolded(tmp_path / "fooctl")
    for relative in ("src/core/core.cpp", "src/net/net.cpp", "tests/core_test/core_test.cpp"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("int main() { return 0; }\n", encoding="utf-8")
    targets = buildfiles.read_tree(repo, {})
    assert targets, "the fixture tree yielded no targets, so this test rules on nothing"

    # act: exactly what the two coordinates write
    generated = {**buildfiles.cmake_files(targets, repo, "fooctl"),
                 **buildfiles.dotnet_files(targets, repo, "fooctl")}

    # assert: every one of them, by git's own verdict
    hidden = sorted(path.relative_to(repo).as_posix() for path in generated
                    if _ignored(repo, path.relative_to(repo).as_posix()))
    assert hidden == [], f"the ignore block hides files si#102 generates to be committed: {hidden}"


def test_everything_the_scaffold_itself_writes_is_still_visible_to_git(tmp_path):
    """Including the `.gitignore`, which a `.gitignore` can hide from git as easily as anything else."""
    # arrange / act
    repo = _scaffolded(tmp_path / "fooctl")

    # assert
    hidden = sorted(relative for relative in bootstrap.render("fooctl") if _ignored(repo, relative))
    assert hidden == []


# --- the block is held to the constants that decide the paths ------------------------------------------


def test_the_python_profiles_user_base_is_the_directory_the_block_names(tmp_path):
    """`bootstrap` cannot import `profiles`, so the path is declared twice; this is the seam.

    The value is read off the profile's own command table rather than off a constant, because there is no
    constant: the user base is an env var on three command bodies, and a fourth command added without it
    is exactly the drift this reads out.
    """
    # arrange
    commands = profiles_task.PROFILES["python"].commands

    # act
    bases = {body["env"]["PYTHONUSERBASE"] for body in commands.values() if "env" in body}

    # assert: one user base, under the mount, and the block anchors that name at the product root
    assert len(bases) == 1, f"the python profile now has more than one user base: {bases}"
    name = Path(next(iter(bases))).name
    assert f"/{name}/" in PATTERNS, (
        f"no rule names {name}, which is where `build deps` installs 80 MB")


def test_every_directory_the_block_anchors_is_one_the_kernel_writes_at_the_product_root(tmp_path):
    """Anchoring is the half a `in BLOCK` check cannot see, and getting it wrong is silent both ways."""
    # arrange: the root-level directories, from the constants that place them
    repo = _repo(tmp_path / "fooctl")
    (repo / bootstrap.GITIGNORE).write_text(BLOCK, encoding="utf-8")
    anchored = {Path(docs_task.OUTPUT_DIR).parts[0], str(docs_task.GRADLE_STATE),
                Path(site_task.CACHE_DIR).parts[0], testrun.REPORTS}

    # act / assert: ignored AT the root, and NOT under a target directory, where si#102 generates
    for directory in sorted(anchored):
        assert _ignored(repo, f"{directory}/x"), f"{directory}/ is not ignored at the product root"
        assert not _ignored(repo, f"src/target/{directory}/CMakeLists.txt"), (
            f"{directory}/ is anchored too loosely and would hide a generated CMakeLists.txt")


def test_the_caches_that_ignore_themselves_carry_no_line_here(tmp_path):
    """venv, pytest and mypy each write a `.gitignore` holding `*`; measured, not assumed.

    This is the finding that keeps the block honest. The 0.10.0 notes tell a product to add three lines -
    `.simplon-toolchain`, `.mypy_cache`, `.pytest_cache` - and two of them were never needed. A block
    that carried them would read as though it were doing work git was already doing.
    """
    # arrange: a venv made the way the launcher makes one, in a tree carrying only the scaffold's block
    repo = _scaffolded(tmp_path / "fooctl")
    venv = repo / bootstrap.DEFAULT_ORCH_DIR / ".venv"
    done = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

    # act
    self_ignore = venv / ".gitignore"

    # assert: the venv hides itself, and no line in the block claims the credit
    assert self_ignore.is_file(), "python no longer writes a .gitignore into a venv; the block needs one"
    assert _ignored(repo, f"{bootstrap.DEFAULT_ORCH_DIR}/.venv/pyvenv.cfg")
    for cache in (".venv", ".mypy_cache", ".pytest_cache"):
        assert not [rule for rule in PATTERNS if cache in rule], (
            f"{cache} writes its own .gitignore holding `*`; a rule here would be theatre")


# --- never clobber: what happens to a `.gitignore` that is already there --------------------------------


def test_a_scaffold_into_a_repository_that_has_a_gitignore_keeps_every_byte_of_it(tmp_path):
    """si#129 put `init` at the repository ROOT, so the file it meets is usually somebody else's.

    si#110's finding is the reason this is a test rather than a remark: `support:toolchain` round-tripped
    a manifest through a plain yaml loader and forty-two comment lines did not come back.
    """
    # arrange
    repo = _repo(tmp_path / "fooctl")
    theirs = "# ours, do not lose\n*.log\n!keep.log\n"
    (repo / bootstrap.GITIGNORE).write_text(theirs, encoding="utf-8")

    # act
    bootstrap.write("fooctl", repo)

    # assert: their bytes are still the head of the file, and the block follows
    after = (repo / bootstrap.GITIGNORE).read_text(encoding="utf-8")
    assert after.startswith(theirs)
    assert after.endswith(BLOCK)
    # and their rules still rule: a negation after a pattern is exactly what an appender can break
    assert _ignored(repo, "a.log") and not _ignored(repo, "keep.log")


def test_a_pre_existing_gitignore_does_not_make_the_whole_scaffold_refuse(tmp_path):
    """The clobber rule would otherwise fail `init` over the one rendered file the scaffold does not own."""
    # arrange
    repo = _repo(tmp_path / "fooctl")
    (repo / bootstrap.GITIGNORE).write_text("*.log\n", encoding="utf-8")

    # act
    written = bootstrap.write("fooctl", repo)

    # assert
    assert (repo / "fooctl.yaml").is_file()
    assert (repo / bootstrap.GITIGNORE) in written


def test_a_second_scaffold_appends_nothing_and_changes_nothing(tmp_path):
    """The marker is the whole duplicate guard; nothing reads position, so nothing can be reordered wrong."""
    # arrange
    repo = _scaffolded(tmp_path / "fooctl")
    edited = (repo / bootstrap.GITIGNORE).read_text(encoding="utf-8").replace("/build/", "/out/")
    edited += "\n# mine\nnotes.txt\n"
    (repo / bootstrap.GITIGNORE).write_text(edited, encoding="utf-8")

    # act
    written = bootstrap.write("fooctl", repo, force=True)

    # assert: the hand-edited block survives a FORCED re-scaffold, which overwrites every other file
    assert (repo / bootstrap.GITIGNORE).read_text(encoding="utf-8") == edited
    assert (repo / bootstrap.GITIGNORE) not in written
    assert "product: fooctl" in (repo / "fooctl.yaml").read_text(encoding="utf-8"), "force did not run"


def test_the_block_never_lands_glued_to_an_unterminated_last_line(tmp_path):
    """A file that ends without a newline is ordinary, and `foo.log# --- written by simplon ---` is a
    pattern rather than a comment - so the marker would be invisible to the next run as well."""
    # arrange
    repo = _repo(tmp_path / "fooctl")
    (repo / bootstrap.GITIGNORE).write_text("*.log", encoding="utf-8")

    # act
    bootstrap.write("fooctl", repo)

    # assert
    lines = (repo / bootstrap.GITIGNORE).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "*.log"
    assert bootstrap.GITIGNORE_MARKER in lines
    assert _ignored(repo, "build/x"), "the block was appended but git does not read it"


def test_the_scaffolded_gitignore_is_written_with_lf_on_every_host(tmp_path):
    """git reads CRLF patterns, but the file joins a tree whose other nine are pinned to LF (si#57)."""
    # arrange / act
    repo = _scaffolded(tmp_path / "fooctl")

    # assert
    assert b"\r\n" not in (repo / bootstrap.GITIGNORE).read_bytes()


def test_main_says_which_of_the_three_things_it_did_to_a_gitignore(tmp_path, capsys, monkeypatch):
    """A scaffolder that touches a file the product maintains says so; the three outcomes are
    indistinguishable from the tree afterwards, so only the run can tell them apart."""
    # arrange
    repo = _repo(tmp_path / "fooctl")
    (repo / bootstrap.GITIGNORE).write_text("*.log\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    # act: append, then meet its own block
    assert bootstrap.main(["init", "fooctl", "--dir", str(repo)]) == 0
    appended = capsys.readouterr().err
    assert bootstrap.main(["init", "fooctl", "--dir", str(repo), "--force"]) == 0
    again = capsys.readouterr().err

    # assert
    assert "appended" in appended and "nothing in it was rewritten" in appended
    assert "left untouched" in again
