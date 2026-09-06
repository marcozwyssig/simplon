"""`simplon init --orch-dir`: the block directory is a parameter, not a decree (#4).

The scaffolder used to write `orchestrator/` at the repo root and nowhere else. That is one
consumer's layout -- the one it grew up in. Two of the three products keep their adapter under
`deploy/provision/orchestrator` because their own structure rule reserves the root, and today they
hand-edit the generated shim afterwards, which `init --force` then throws away.

The rule these tests hold is that the dir is threaded EVERYWHERE or nowhere. A shim whose
`LAUNCH_ORCH_DIR` moved but whose venv, requirements or PYTHONPATH did not is worse than the
hardcoded one, because it fails at run time on a fresh host instead of at generation time here.

The Python PACKAGE stays `orchestrator` (LAUNCH_MODULE) under every layout: it is an identifier on
PYTHONPATH, not a location. Only the block dir that holds `.venv`, `requirements.txt` and
`src/python/` moves.

si#24 added the third consumer of this parameter, and it is the kernel itself: simplon's own block sits
under `deploy/orchestrator` now, so the flag is no longer something the kernel offers and declines to
use. Its own placement is held in `test_own_orch_block.py`; what belongs HERE is the depth, which is why
the two subprocess tests at the foot of this module run at five levels as well as six.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import simplon
from simplon import bootstrap


def _run_generated(pkg_src, argv, *, code=None):
    """Run the SCAFFOLDED package in a SUBPROCESS with the kernel + the generated package on PYTHONPATH -
    the exact seam the shim sets - so its import-time context.set_current() never leaks into this process.
    Mirrors the helper in test_bootstrap.py; the only difference is where `pkg_src` sits."""
    kernel_src = Path(simplon.__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONSAFEPATH="1",
               PYTHONPATH=os.pathsep.join([str(kernel_src), str(pkg_src)]))
    args = ([sys.executable, "-c", code] if code is not None
            else [sys.executable, "-m", "orchestrator", *argv])
    return subprocess.run(args, env=env, capture_output=True, text=True)

# biz-cockpit's real layout, and the reason this parameter exists: `src/` is the product, build and
# delivery mechanics live under `deploy/`. Nested on purpose - a one-segment dir would let a
# separator bug through, and the cmd shim needs backslashes.
NESTED = "deploy/provision/orchestrator"

# The kernel's OWN block dir (si#24). It is here, beside biz-cockpit's, because the depth is the thing
# under test and this one is a third value: `orchestrator` is four levels above the package, `deploy/
# orchestrator` five, `deploy/provision/orchestrator` six. The marker walk carries all three; a fixed
# parent depth carries exactly one, and si#24 found a `parents[4]` in the kernel's own cli.py that had
# been correct only at the default.
OWN = "deploy/orchestrator"

#: Every relocated block dir the subprocess evidence at the foot of this module is taken at. Two values,
#: two depths (five and six), because the walk is what is being trusted and one depth cannot show that.
RELOCATED = [OWN, NESTED]

# The tail every package path ends in, whatever the block dir is. Under a chosen dir, EVERY occurrence
# of it must be prefixed by that dir -- an occurrence prefixed by anything else is a path the parameter
# failed to reach. A plain "is the default string absent" check cannot be used here: the default IS a
# suffix of the nested path (`deploy/provision/orchestrator/src/python/orchestrator`), so it would flag
# a correct render.
PKG_TAIL = "src/python/orchestrator"


def _unprefixed_pkg_paths(text: str, orch_dir: str) -> list[str]:
    """Every place `text` spells a package path that does NOT hang off `orch_dir`, with context."""
    stray, start = [], 0
    while (hit := text.find(PKG_TAIL, start)) != -1:
        if not text[:hit].endswith(f"{orch_dir}/"):
            stray.append(text[max(0, hit - 60):hit + len(PKG_TAIL)])
        start = hit + len(PKG_TAIL)
    return stray


# --- the file set moves ---------------------------------------------------------------------------

def test_orch_dir_moves_the_whole_block_in_the_file_set():
    # arrange / act
    rendered = bootstrap.render("democtl", orch_dir=NESTED)

    # assert: requirements and the package wiring all land under the chosen dir, the manifest and the
    # two launchers stay at the root where the shim contract puts them
    assert set(rendered) == {
        "democtl.sh",
        "democtl.cmd",
        "democtl.yaml",
        f"{NESTED}/requirements.txt",
        f"{NESTED}/src/python/orchestrator/__init__.py",
        f"{NESTED}/src/python/orchestrator/__main__.py",
        f"{NESTED}/src/python/orchestrator/cli.py",
        f"{NESTED}/src/python/orchestrator/paths.py",
        f"{NESTED}/src/python/orchestrator/environments.py",
    }


def test_write_lands_the_block_on_disk_under_the_chosen_dir(tmp_path):
    # arrange / act
    written = bootstrap.write("democtl", tmp_path, orch_dir=NESTED)

    # assert
    on_disk = {p.relative_to(tmp_path).as_posix() for p in written}
    assert f"{NESTED}/requirements.txt" in on_disk
    assert f"{NESTED}/src/python/orchestrator/cli.py" in on_disk
    assert not (tmp_path / "orchestrator").exists(), "the default block dir was written anyway"
    assert (tmp_path / "democtl.sh").stat().st_mode & 0o111, "the shim lost its exec bit"


# --- the shims: every derived path, not just LAUNCH_ORCH_DIR ---------------------------------------

def test_the_sh_shim_points_every_derived_path_at_the_chosen_dir():
    # arrange / act
    sh = bootstrap.render("democtl", orch_dir=NESTED)["democtl.sh"]

    # assert: the one assignment that decides the rest
    assert f'LAUNCH_ORCH_DIR="$ROOT/{NESTED}"' in sh

    # assert: and nothing still reaches for the root-level default
    assert '$ROOT/orchestrator"' not in sh, "the shim still points at the default block dir"

    # assert: the venv, the requirements file and PYTHONPATH DERIVE from the variable rather than
    # spelling a path of their own - a half-parametrised shim only breaks on a fresh host
    assert 'VENV="$LAUNCH_ORCH_DIR/.venv"' in sh
    assert 'REQ="$LAUNCH_ORCH_DIR/requirements.txt"' in sh
    assert 'export PYTHONPATH="$LAUNCH_ORCH_DIR/src/python${PYTHONPATH:+:$PYTHONPATH}"' in sh

    # assert: the package identifier is NOT the directory and does not move with it
    assert "LAUNCH_MODULE=orchestrator" in sh


def test_the_cmd_shim_spells_the_chosen_dir_with_windows_separators():
    # arrange / act
    cmd = bootstrap.render("democtl", orch_dir=NESTED)["democtl.cmd"]

    # assert: cmd.exe needs backslashes. A nested dir carried over verbatim gives
    # `%LAUNCH_ROOT%\deploy/provision/orchestrator`, which is the kind of path that half-works
    # until it reaches a tool that does not normalise it.
    assert 'set "LAUNCH_ORCH_DIR=%LAUNCH_ROOT%\\deploy\\provision\\orchestrator"' in cmd
    assert "/provision/" not in cmd, "a POSIX separator survived into the cmd shim"

    # assert: the derived paths hang off the variable, as on the sh side
    assert 'set "VENV=%LAUNCH_ORCH_DIR%\\.venv"' in cmd
    assert 'set "REQ=%LAUNCH_ORCH_DIR%\\requirements.txt"' in cmd
    assert 'set "PYTHONPATH=%LAUNCH_ORCH_DIR%\\src\\python;%PYTHONPATH%"' in cmd


# --- the sweep: nothing anywhere still names the default -------------------------------------------

def test_no_generated_file_still_names_the_default_block_path():
    """The whole point of the ticket: a path the parameter did not reach fails at run time.

    `LAUNCH_ORCH_DIR` was never the only place - the generated cli.py tells the reader which file to
    edit, and it spelled the default path out in full.
    """
    # arrange / act
    rendered = bootstrap.render("democtl", orch_dir=NESTED)

    # assert
    for rel, content in rendered.items():
        stray = _unprefixed_pkg_paths(content, NESTED)
        assert stray == [], f"{rel} spells a package path outside the chosen block dir: {stray}"


def test_next_steps_points_at_the_chosen_dir(tmp_path):
    # arrange / act
    steps = bootstrap.next_steps("democtl", tmp_path, orch_dir=NESTED)

    # assert: the guidance names the file the user actually has to open
    assert f"{NESTED}/src/python/orchestrator/cli.py" in steps
    assert _unprefixed_pkg_paths(steps, NESTED) == []


# --- the path is checked, loudly -------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "/absolute/orchestrator",          # leading slash: lands outside the scaffold target
    "\\windows\\absolute",             # the same, spelled for cmd.exe
    "C:/drive/orchestrator",           # a drive-qualified path is absolute too
    "../sibling/orchestrator",         # climbs out of the project tree
    "deploy/../../escape",             # climbs out further along, mid-path
    "deploy/./orchestrator",           # a `.` segment is not a directory name
    "deploy//orchestrator",            # an empty segment
    "deploy\\provision",               # a backslash is not a separator here; say so
    "",                                # nothing at all
    "   ",                             # nothing at all, with whitespace
    ".",                               # the target root itself is not a block dir
    "..",
])
def test_a_path_that_escapes_or_confuses_is_refused(bad):
    # arrange / act / assert: refused at render time, before a single byte is written
    with pytest.raises(ValueError):
        bootstrap.render("democtl", orch_dir=bad)


def test_the_refusal_names_the_value_and_the_rule():
    # arrange / act
    with pytest.raises(ValueError) as excinfo:
        bootstrap.render("democtl", orch_dir="../escape")

    # assert: an error a user can act on without reading the source
    message = str(excinfo.value)
    assert "../escape" in message
    assert "relative" in message.lower()


def test_a_refused_path_writes_nothing(tmp_path):
    # arrange / act
    with pytest.raises(ValueError):
        bootstrap.write("democtl", tmp_path, orch_dir="../escape")

    # assert: the check runs BEFORE the writing, so a bad value leaves no half-scaffold behind
    assert list(tmp_path.iterdir()) == []


# --- backwards compatibility: the default is exactly what it was -------------------------------------

def test_the_default_is_byte_identical_to_passing_it_explicitly():
    # arrange / act
    implicit = bootstrap.render("democtl")
    explicit = bootstrap.render("democtl", orch_dir="orchestrator")

    # assert: same paths, same bytes - the parameter's default IS the old behaviour, not a near miss
    assert implicit == explicit


def test_the_default_still_writes_the_root_level_block(tmp_path):
    # arrange / act
    bootstrap.write("democtl", tmp_path)

    # assert: an `init` with no new flag is the scaffold it always was
    assert (tmp_path / "orchestrator" / "requirements.txt").is_file()
    assert (tmp_path / "orchestrator" / "src" / "python" / "orchestrator" / "cli.py").is_file()
    assert f'LAUNCH_ORCH_DIR="$ROOT/orchestrator"' in (tmp_path / "democtl.sh").read_text()
    assert 'set "LAUNCH_ORCH_DIR=%LAUNCH_ROOT%\\orchestrator"' in (tmp_path / "democtl.cmd").read_text()


# --- the CLI surface --------------------------------------------------------------------------------

def test_init_accepts_the_flag_and_scaffolds_there(tmp_path, capsys):
    # arrange / act
    rc = bootstrap.main(["init", "democtl", "--dir", str(tmp_path), "--orch-dir", NESTED])

    # assert
    assert rc == 0
    assert (tmp_path / NESTED / "requirements.txt").is_file()
    assert not (tmp_path / "orchestrator").exists()


def test_init_refuses_a_bad_orch_dir_with_a_message_and_no_traceback(tmp_path, capsys):
    # arrange / act
    rc = bootstrap.main(["init", "democtl", "--dir", str(tmp_path), "--orch-dir", "/etc/orchestrator"])

    # assert: exit 2, the same fail-loud contract a bad product name gets
    assert rc == 2
    err = capsys.readouterr().err
    assert "/etc/orchestrator" in err
    assert list(tmp_path.iterdir()) == [], "a refused run scaffolded anyway"


# --- and it actually runs from down there ------------------------------------------------------------

@pytest.mark.parametrize("orch_dir", RELOCATED)
def test_a_relocated_scaffold_assembles_and_finds_its_repo_root(tmp_path, orch_dir):
    """Textual checks cannot show this: the generated `paths.py` derives the repo ROOT by walking up from
    its own file to the manifest marker. At the default depth that is four levels; under
    `deploy/orchestrator` five and under `deploy/provision/orchestrator` six. A fixed parent depth would
    have passed every assertion above and then resolved the root one or two directories too low, at
    import, on the consumer's machine.

    Both relocated depths are run, and the second one is not decoration: si#24 moved the KERNEL's own
    block to `deploy/orchestrator`, and the evidence si#4 took at six levels says nothing about five.
    """
    # arrange: a real relocated scaffold on disk
    bootstrap.write("democtl", tmp_path, orch_dir=orch_dir)

    # act: import the generated package the way its own shim does - kernel + the nested src/python on
    # PYTHONPATH, in a SUBPROCESS so the import-time set_current() does not leak into this one
    probe = (
        "from orchestrator import paths\n"       # import runs context.bootstrap()'s marker walk
        "print('ROOT=%s' % paths.ROOT)\n"
        "print('MANIFEST=%s' % paths.MANIFEST)\n"
    )
    res = _run_generated(tmp_path / orch_dir / "src" / "python", [], code=probe)

    # assert: the root is the scaffold target itself, not a directory inside the block
    assert res.returncode == 0, res.stderr
    assert f"ROOT={tmp_path}" in res.stdout, res.stdout
    assert f"MANIFEST={tmp_path / 'democtl.yaml'}" in res.stdout, res.stdout


@pytest.mark.parametrize("orch_dir", RELOCATED)
def test_a_relocated_scaffold_runs_its_aggregate_through_the_shared_runner(tmp_path, orch_dir):
    # arrange
    bootstrap.write("democtl", tmp_path, orch_dir=orch_dir)
    probe = (
        "from simplon.orchestrator import product\n"
        "seen = {}\n"
        "def _record(pipeline):\n"
        "    seen['commands'] = [s.command for s in pipeline.steps]\n"
        "    return 0\n"
        "product.dispatch = _record\n"
        "from typer.testing import CliRunner\n"
        "from orchestrator import cli\n"          # import assembles the app from the nested manifest
        "result = CliRunner().invoke(cli.app, ['all'])\n"
        "assert result.exit_code == 0, result.output\n"
        "assert seen['commands'] == ['build.build', 'deploy.up'], seen\n"
        "print('RELOCATED_AGGREGATE_REACHABLE')\n"
    )

    # act
    res = _run_generated(tmp_path / orch_dir / "src" / "python", [], code=probe)

    # assert: a product whose block dir moved still gets a working, manifest-driven CLI
    assert res.returncode == 0, res.stderr
    assert "RELOCATED_AGGREGATE_REACHABLE" in res.stdout
