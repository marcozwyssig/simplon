"""`simplon init` with no product name reads one from the repository (si#129).

THE RULE THE WHOLE MODULE IS ABOUT: a default, never a decree. si#102 is the fresh counter-example - its
generator derived a CMake target from `root.name` and got the product name wrong, because a directory is
named for where it sits and not for what it is. A repository can be `tooling`, or a monorepo holding two
products. So the argument still wins, unchanged, and a name that cannot be a product name is REFUSED with
the argument named as the fix rather than repaired into something that half works.

WHY THE REPOSITORIES HERE ARE REAL. Every case below runs `git init` in a tmp_path and asks the real git.
A stub would let this module agree with whatever the implementation happened to call - and the two facts
it depends on, that `rev-parse --show-toplevel` answers from a subdirectory and that `remote get-url`
fails rather than prints when there is no origin, are git's behaviour and not simplon's.
"""
import os
import subprocess
from pathlib import Path

import pytest

from simplon import bootstrap
from simplon.run import Result


def _git(*args: str, cwd: Path) -> str:
    """One git call, checked. Not `simplon.run` on purpose: this is the test's own arrangement, and it
    must fail loudly here rather than turn into a scaffold with a surprising name."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def _repo(path: Path, *, origin: str | None = None) -> Path:
    """A real git repository at `path`, optionally with an `origin` remote. No commit: the name is read
    from the remote and the working tree, and a repository with no commits yet is exactly the state
    somebody scaffolding a fresh product is in."""
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=path)
    if origin is not None:
        _git("remote", "add", "origin", origin, cwd=path)
    return path


# --- which name: the URL is parsed, and only the URL's own parts are dropped ------------------------


@pytest.mark.parametrize(("url", "expected"), [
    ("https://github.com/acme/netctl.git", "netctl"),
    ("https://github.com/acme/netctl", "netctl"),
    ("https://github.com/acme/netctl/", "netctl"),
    ("git@github.com:acme/netctl.git", "netctl"),
    ("ssh://git@host:2222/acme/netctl.git", "netctl"),
    ("file:///srv/git/netctl.git", "netctl"),
    ("/srv/git/netctl.git", "netctl"),
    ("../sibling/netctl", "netctl"),
])
def test_the_repository_name_is_parsed_out_of_every_url_shape_git_accepts(url, expected):
    # arrange / act / assert: `.git` and a trailing slash belong to the URL, not to the name, and the
    # scp-like `host:path` form has no slash before the last segment at all
    assert bootstrap.repository_name_from_url(url) == expected


def test_the_url_parser_repairs_nothing_beyond_the_urls_own_punctuation():
    # arrange / act: a repository really called this - the parser hands it over untouched and the
    # validation below is what refuses it. Repairing here would hide which of the two decided
    assert bootstrap.repository_name_from_url("https://github.com/acme/Ops%20Tools.git") == "Ops%20Tools"
    assert bootstrap.repository_name_from_url("git@host:acme/my.ctl.git") == "my.ctl"


# --- which name: origin first, the working tree second ----------------------------------------------


def test_the_origin_remote_wins_over_the_directory_it_was_cloned_into(tmp_path):
    """The two disagree the moment somebody clones into a differently named folder, and the remote is
    the one that survives it: `git clone .../netctl.git myproject` makes the directory an accident of one
    machine while the remote still carries the name the product is published under. A linked git
    worktree is the same case from the other side - its basename is `agent-3f2a` and the product is
    still netctl."""
    # arrange: the disagreement, made on purpose
    repo = _repo(tmp_path / "myproject", origin="https://github.com/acme/netctl.git")

    # act
    found = bootstrap.repository_default(repo)

    # assert
    assert found.name == "netctl"
    assert "origin" in found.source
    assert found.root == repo


def test_a_repository_with_no_remote_falls_back_to_its_working_tree_root(tmp_path):
    # arrange: `git init` and nothing else, which is what a brand-new product repository is
    repo = _repo(tmp_path / "labctl")

    # act
    found = bootstrap.repository_default(repo)

    # assert: a fallback, so it answers rather than failing - and it says which of the two it used,
    # including WHY it fell back, since "no remote yet" is a state a user can change
    assert found.name == "labctl"
    assert "working tree" in found.source
    assert "no 'origin' remote" in found.source
    assert found.root == repo


def test_the_name_is_read_from_the_repository_root_not_from_the_subdirectory_you_stand_in(tmp_path):
    # arrange: the fallback reads `git rev-parse --show-toplevel`, not `Path.cwd()`, and the difference
    # is invisible until somebody runs the command from inside the tree
    repo = _repo(tmp_path / "labctl")
    (repo / "deploy" / "provision").mkdir(parents=True)

    # act
    found = bootstrap.repository_default(repo / "deploy" / "provision")

    # assert
    assert found.name == "labctl"
    assert found.root == repo


# --- validation: refused with the fix, never repaired -----------------------------------------------


@pytest.mark.parametrize("directory", ["Ops Tools", "my.ctl", "1ctl", "foo_ctl"])
def test_a_repository_whose_name_is_not_a_product_name_is_refused_with_the_argument_named(
        tmp_path, directory):
    """The name becomes a launcher filename, a manifest filename, a package path and the `<PRODUCT>_ENV`
    variable stem. Lowercasing `Ops Tools` into `ops-tools` would name all four after a string nobody
    chose, silently, and the person who finds out is the one running `./ops-tools.sh` a week later."""
    # arrange
    repo = _repo(tmp_path / directory)

    # act
    with pytest.raises(ValueError) as excinfo:
        bootstrap.repository_default(repo)

    # assert: the bad value and the way out, both in the message a user actually sees
    message = str(excinfo.value)
    assert directory in message, message
    assert "simplon init <product>" in message, message


def test_the_refusal_says_where_the_name_came_from(tmp_path):
    # arrange: the remote and the directory disagree, so "which of the two produced this" is a real
    # question the message has to answer
    repo = _repo(tmp_path / "fine-name", origin="https://github.com/acme/Ops%20Tools.git")

    # act
    with pytest.raises(ValueError) as excinfo:
        bootstrap.repository_default(repo)

    # assert
    assert "origin" in str(excinfo.value)


# --- outside a repository: it says what it wants -----------------------------------------------------


def test_a_plain_directory_with_no_git_says_what_it_wants_and_names_the_argument(tmp_path):
    # arrange: no `git init` at all
    plain = tmp_path / "somewhere"
    plain.mkdir()

    # act
    with pytest.raises(ValueError) as excinfo:
        bootstrap.repository_default(plain)

    # assert: the condition, and the argument that solves it - not a traceback out of a subprocess
    message = str(excinfo.value)
    assert "not inside a git repository" in message, message
    assert "simplon init <product>" in message, message


def test_a_bare_repository_is_refused_rather_than_scaffolded_into_the_current_directory(tmp_path):
    """A repository with no working tree cannot say where its root is, and the one thing that must NOT
    happen is a scaffold landing wherever the command was typed. git answers `rev-parse --show-toplevel`
    with rc 128 here, and `_git` collapses an empty answer to the same nothing, so neither route can turn
    into `Path("")` - which resolves to the current directory and would look exactly like success."""
    # arrange
    bare = tmp_path / "bare.git"
    bare.mkdir()
    _git("init", "-q", "--bare", ".", cwd=bare)

    # act / assert
    with pytest.raises(ValueError) as excinfo:
        bootstrap.repository_default(bare)
    assert "simplon init <product>" in str(excinfo.value)


def test_git_answering_with_nothing_is_the_same_as_not_answering(tmp_path, monkeypatch):
    """rc 0 with an empty stdout is the shape the bare-repository case above cannot produce on this git,
    and it is the one that would do real damage: `Path("")` resolves to the CURRENT directory, so a
    repository that could not name its own root would scaffold into wherever the command was typed and
    report success. `_git` collapses it to the same nothing a failure gives."""
    # arrange
    monkeypatch.setattr(bootstrap, "run", lambda argv, **kwargs: Result(rc=0, out="  \n", err=""))

    # act / assert
    with pytest.raises(ValueError, match="not inside a git repository"):
        bootstrap.repository_default(tmp_path)


def test_git_missing_from_PATH_is_its_own_cause_with_the_same_fix(tmp_path, monkeypatch):
    # arrange: a host without git is a different condition from a directory without a repository, and a
    # message that named the wrong one would send somebody looking for the wrong thing. The repository is
    # made BEFORE PATH is emptied, so what is under test is the read and not the arrangement
    repo = _repo(tmp_path / "labctl")
    monkeypatch.setenv("PATH", str(tmp_path))

    # act
    with pytest.raises(ValueError) as excinfo:
        bootstrap.repository_default(repo)

    # assert
    message = str(excinfo.value)
    assert "git" in message and "PATH" in message, message
    assert "simplon init <product>" in message, message


# --- the CLI: the argument becomes optional, and the run says what it decided -------------------------


def test_init_with_no_arguments_at_all_scaffolds_the_repository_it_stands_in(tmp_path, monkeypatch):
    """The whole point of si#129: inside a repository named after the product there is nothing left to
    type. The block lands at the si#130 default, so the two tickets meet here."""
    # arrange
    repo = _repo(tmp_path / "labctl", origin="https://github.com/acme/labctl.git")
    monkeypatch.chdir(repo)

    # act
    rc = bootstrap.main(["init"])

    # assert
    assert rc == 0
    assert (repo / "labctl.sh").is_file()
    assert (repo / "labctl.yaml").is_file()
    assert (repo / bootstrap.DEFAULT_ORCH_DIR / "requirements.txt").is_file()


def test_the_argument_still_wins_over_the_repository(tmp_path, monkeypatch):
    # arrange: a monorepo, or a repository called `tooling` - the case si#102 got wrong
    repo = _repo(tmp_path / "tooling", origin="https://github.com/acme/tooling.git")
    monkeypatch.chdir(repo)

    # act
    rc = bootstrap.main(["init", "fooctl", "--dir", "."])

    # assert: the argument decided, and nothing named after the repository was written
    assert rc == 0
    assert (repo / "fooctl.sh").is_file()
    assert not (repo / "tooling.sh").exists()


def test_an_explicit_name_still_lands_in_its_own_subdirectory(tmp_path, monkeypatch):
    # arrange: the behaviour that must NOT change - a named product is a new thing being created here
    repo = _repo(tmp_path / "tooling")
    monkeypatch.chdir(repo)

    # act
    rc = bootstrap.main(["init", "fooctl"])

    # assert
    assert rc == 0
    assert (repo / "fooctl" / "fooctl.sh").is_file()
    assert not (repo / "fooctl.sh").exists()


def test_a_defaulted_name_lands_at_the_repository_root_rather_than_below_it(tmp_path, monkeypatch):
    """The `--dir` interaction si#129 asks to be stated rather than discovered.

    Reading the name from the repository IS the statement that the repository is the product, and
    `./labctl/labctl.sh` inside the labctl repository contradicts the fact just used to name it - it
    would also put the launcher one directory below the manifest marker its own `paths.py` walks up to.
    Run from a subdirectory, so "the repository root" is provably not "here".
    """
    # arrange
    repo = _repo(tmp_path / "labctl")
    (repo / "src").mkdir()
    monkeypatch.chdir(repo / "src")

    # act
    rc = bootstrap.main(["init"])

    # assert
    assert rc == 0
    assert (repo / "labctl.sh").is_file()
    assert not (repo / "src" / "labctl.sh").exists()
    assert not (repo / "labctl" / "labctl.sh").exists()


def test_a_defaulted_name_with_an_explicit_dir_uses_the_dir(tmp_path, monkeypatch):
    # arrange: --dir always wins, so the defaulted name never decides the directory once one is given
    repo = _repo(tmp_path / "labctl")
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.chdir(repo)

    # act
    rc = bootstrap.main(["init", "--dir", str(elsewhere)])

    # assert
    assert rc == 0
    assert (elsewhere / "labctl.sh").is_file()
    assert not (repo / "labctl.sh").exists()


def test_a_defaulted_run_says_which_name_it_read_and_where_it_is_writing(tmp_path, monkeypatch, capsys):
    """Two defaults fall out of one omission, so neither may be silent."""
    # arrange
    repo = _repo(tmp_path / "labctl", origin="https://github.com/acme/labctl.git")
    monkeypatch.chdir(repo)

    # act
    bootstrap.main(["init"])

    # assert: the name, where it was read, and the target - plus the flag that overrides the target
    err = capsys.readouterr().err
    assert "labctl" in err
    assert "origin" in err
    assert str(repo) in err
    assert "--dir" in err


def test_a_named_run_says_nothing_extra(tmp_path, monkeypatch, capsys):
    # arrange: nothing was defaulted, so there is nothing to announce - a note on every run is noise
    repo = _repo(tmp_path / "labctl")
    monkeypatch.chdir(repo)

    # act
    bootstrap.main(["init", "fooctl"])

    # assert
    assert capsys.readouterr().err == ""


def test_init_outside_a_repository_exits_2_with_the_fix_and_no_traceback(tmp_path, monkeypatch, capsys):
    # arrange
    plain = tmp_path / "somewhere"
    plain.mkdir()
    monkeypatch.chdir(plain)

    # act
    rc = bootstrap.main(["init"])

    # assert: the same fail-loud contract a bad product name and a bad --orch-dir already get
    assert rc == 2
    err = capsys.readouterr().err
    assert "not inside a git repository" in err
    assert "simplon init <product>" in err
    assert list(plain.iterdir()) == [], "a refused run scaffolded anyway"


def test_a_bare_simplon_with_no_argv_still_names_the_subcommand(capsys):
    """`simplon init` with nothing after it is a legal command now; `simplon` bare is still not one, and
    the two must not collapse into each other. argparse alone would only complain about a missing
    argument that is no longer required, which would leave a first-time user with no message at all."""
    # act
    rc = bootstrap.main([])

    # assert
    assert rc == 2
    assert "simplon init" in capsys.readouterr().err


def test_the_help_says_the_argument_is_optional_and_what_it_defaults_to(capsys):
    # arrange / act: the one place a user looks before typing the command
    with pytest.raises(SystemExit):
        bootstrap.main(["init", "--help"])

    # assert
    out = capsys.readouterr().out
    assert "optional" in out or "default" in out
    assert "repository" in out


def test_the_scaffolded_shim_of_a_defaulted_run_names_the_repository_product(tmp_path, monkeypatch):
    # arrange: the name has to reach the shim's own parameters, not merely the filename - a scaffold
    # named right on disk and wrong inside is the failure this whole module is about
    repo = _repo(tmp_path / "elsewhere", origin="https://github.com/acme/labctl.git")
    monkeypatch.chdir(repo)

    # act
    bootstrap.main(["init"])

    # assert
    assert "LAUNCH_PRODUCT=labctl" in (repo / "labctl.sh").read_text(encoding="utf-8")
    assert 'ENV_VAR = "LABCTL_ENV"' in (
        repo / bootstrap.pkg_dir_for(bootstrap.DEFAULT_ORCH_DIR) / "environments.py"
    ).read_text(encoding="utf-8")


def test_the_default_name_is_read_where_the_command_runs_and_not_from_dir(tmp_path, monkeypatch):
    """One rule rather than two. `--dir` says where the skeleton goes; the repository the command RUNS
    in says what it is called. The common case (`--dir .`) makes the two identical, and the rare case is
    announced by the note rather than guessed at."""
    # arrange
    repo = _repo(tmp_path / "labctl")
    other = _repo(tmp_path / "otherctl")
    monkeypatch.chdir(repo)

    # act
    rc = bootstrap.main(["init", "--dir", str(other)])

    # assert
    assert rc == 0
    assert (other / "labctl.sh").is_file()
    assert not (other / "otherctl.sh").exists()


def test_os_getcwd_is_what_the_default_reads(tmp_path, monkeypatch):
    # arrange: a guard against reading the module's import-time directory instead of the process's
    # current one - the bug would be invisible in every test that happens to run from the repo root
    repo = _repo(tmp_path / "labctl")
    monkeypatch.chdir(repo)

    # act / assert
    assert bootstrap.repository_default(Path(os.getcwd())).name == "labctl"
