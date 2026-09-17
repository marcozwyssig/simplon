"""Where the KERNEL's own orchestrator block sits, and that it got there through its own parameter (si#24).

si#4 made the block dir a parameter because two of the three products place their adapter under
`deploy/provision/orchestrator` and their structure rule reserves the repo root. The kernel then stayed
the one consumer the old default happened to suit, which is the shape si#47 and si#34 are both about: a
kernel that offers something and exempts itself from it. So the block moved to `deploy/orchestrator`, and
what these tests hold is that it moved as a USE of `--orch-dir` rather than as a hand-edit beside it.

WHAT IS NOT HELD HERE, deliberately. The DEFAULT belongs next door, in `test_init_orch_dir.py`. When this
file was written the default was `orchestrator/` at the target root and this move was simplon's own tree
rather than an instruction to anybody else's; si#130 has since moved the default to
`deploy/provision/orchestrator`, which is a level DEEPER than the kernel's own block. That is not a
contradiction and it is worth saying why: the kernel keeps `deploy/orchestrator` because it has no
`provision/` layer to sit under, and what both placements have in common - that the repository root is
not the block's home - is exactly what si#130 made the default.

The DEPTH belongs next door too (`test_init_orch_dir.py`): `deploy/orchestrator` puts the generated
package five directories below the root where the default puts it four, and the marker walk is what
carries that. Two subprocess tests there take the evidence at five levels, the way si#4 took it at six.
"""
import ast
import configparser
import subprocess

from conftest import ROOT

from simplon import bootstrap

#: Simplon's own block dir, as a POSIX-relative path -- the value `--orch-dir` was given.
OWN_ORCH_DIR = "deploy/orchestrator"

#: The files that CONFIGURE this repository, as opposed to the pages that describe how a product is
#: scaffolded. The distinction is the whole reason this is a list and not a sweep of the tree: the README
#: and the site spell `orchestrator/` as the last segment of every block path they show, and since si#130
#: what they show is a scaffolded product's real default. `test_getting_started_scaffold.py` sweeps those
#: two pages for the same leftover; these files are about THIS tree.
CONFIGURES_THIS_REPO = ["simplon.sh", "simplon.cmd", "mypy.ini", "simplon.yaml"]


def _own_shim(template: str) -> str:
    """The launcher the kernel's OWN scaffolder writes for the kernel, at the kernel's own block dir."""
    return bootstrap._render_launcher("simplon", template, OWN_ORCH_DIR)


def _counts_out_a_parent(rel: str) -> bool:
    """Whether the module at `rel` reaches for `.parents` in CODE.

    Parsed, not grepped: this file's own prose says `parents[4]` while explaining why the code no longer
    does, and a text search cannot tell the two apart -- which is the mistake `_config()` in
    `test_type_gate.py` names about mypy.ini, met from the other side.
    """
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    return any(isinstance(node, ast.Attribute) and node.attr == "parents" for node in ast.walk(tree))


def test_the_kernels_own_block_sits_under_deploy_and_not_at_the_root() -> None:
    # arrange / act
    block = ROOT / "deploy" / "orchestrator"

    # assert: the whole block moved together -- the requirements file and the package source, which are
    # the two halves the shim derives from LAUNCH_ORCH_DIR
    assert (block / "requirements.txt").is_file()
    assert (block / "src" / "python" / "orchestrator" / "cli.py").is_file()
    # The REPOSITORY must not carry the old block any more. Deliberately asked of git rather than of the
    # filesystem: a checkout that predates the move keeps an untracked `orchestrator/.venv` and its
    # `__pycache__`, and `exists()` cannot tell that leftover from a block somebody committed back. Two
    # states, one answer - the very confusion this repository is built to refuse. `git ls-files` answers
    # the question actually being asked, and a stale venv is a local cleanup rather than a red suite.
    tracked = subprocess.run(["git", "ls-files", "orchestrator"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
    assert not tracked, f"the old root-level block is still tracked: {tracked[:5]}"


def test_the_kernels_own_shims_are_exactly_what_its_own_scaffolder_writes() -> None:
    """The self-binding assertion, and the reason this file exists.

    A shim edited by hand to say `deploy/orchestrator` would pass every other test here and would still
    mean the kernel had NOT used `--orch-dir` -- it would mean somebody had done by hand what the flag
    does, in the one repository whose job is to prove the flag works. Held as byte equality against the
    template render, so the day the launcher template grows a line, simplon's own launcher grows it too
    or this goes red.

    Read with universal newlines on both sides on purpose: `.gitattributes` pins `*.cmd` to CRLF, so
    `simplon.cmd` on disk differs from the LF template in exactly that, and that difference is the
    policy `test_launch_cmd.py` holds rather than something for this test to trip over.
    """
    # arrange / act / assert
    assert (ROOT / "simplon.sh").read_text(encoding="utf-8") == _own_shim("launch.sh.j2")
    assert (ROOT / "simplon.cmd").read_text(encoding="utf-8") == _own_shim("launch.cmd.j2")


def test_the_kernels_own_shim_is_executable() -> None:
    # the scaffolder sets 0o755 on the shim it writes; regenerating simplon's own must not lose it
    assert (ROOT / "simplon.sh").stat().st_mode & 0o111


def test_no_file_that_configures_this_repository_still_names_a_root_level_block() -> None:
    """The ticket's acceptance criterion, scoped to the files it can honestly be asked of.

    `orchestrator/src/python` and `orchestrator/requirements.txt` are the two spellings that mean "the
    block", and under si#24 every one of them in THIS repository's own configuration has to be prefixed
    by `deploy/`. A bare occurrence is a path the move did not reach -- the failure mode si#4 named: a
    shim whose LAUNCH_ORCH_DIR moved and whose derived paths did not.
    """
    # arrange
    tails = ("orchestrator/src/python", "orchestrator/requirements.txt")
    files = [ROOT / rel for rel in CONFIGURES_THIS_REPO]
    files += sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))

    # act
    stray = []
    for path in files:
        text = path.read_text(encoding="utf-8").replace("\\", "/")
        for tail in tails:
            start = 0
            while (hit := text.find(tail, start)) != -1:
                if not text[:hit].endswith("deploy/"):
                    stray.append(f"{path.relative_to(ROOT)}: ...{text[max(0, hit - 40):hit + len(tail)]}")
                start = hit + len(tail)

    # assert
    assert stray == [], f"these still point at a root-level block: {stray}"


def test_the_type_gate_checks_the_block_where_it_now_lives() -> None:
    """mypy.ini names the block by path, so it is one of the places a move silently stops covering.

    A `files =` that pointed at a directory which no longer exists would not go red -- mypy would report
    success over a tree it never read, which is si#8's shape exactly.
    """
    # arrange
    parser = configparser.ConfigParser()
    parser.read_string((ROOT / "mypy.ini").read_text(encoding="utf-8"))

    # act
    covered = [root.strip() for root in parser["mypy"]["files"].split(",")]

    # assert: every root it names is a directory that exists
    assert covered == ["src", f"{OWN_ORCH_DIR}/src/python/orchestrator"]
    for root in covered:
        assert (ROOT / root).is_dir(), f"mypy.ini covers {root}, which is not there"


def test_the_kernels_own_cli_reads_its_root_from_the_product_context() -> None:
    """One source for the repo root in the kernel's own adapter, not two.

    MEASURED, on the day (si#24): this module carried `ROOT = Path(__file__).resolve().parents[4]` with
    a comment counting the levels, three lines under a `from . import paths` whose `paths.ROOT` already
    held the answer from the marker walk. The count was right at the old depth and wrong at the new one,
    so `test all` went looking for `deploy/tests` and stopped. It failed LOUDLY, which is the only
    reason it is a finding rather than a wrong build -- but a second source that has to be kept in step
    with the first is the thing to delete, not to guard.
    """
    # arrange
    rel = "deploy/orchestrator/src/python/orchestrator/cli.py"

    # act / assert
    assert "ROOT = paths.ROOT" in (ROOT / rel).read_text(encoding="utf-8")
    assert not _counts_out_a_parent(rel), "the repo root is being counted out again instead of derived"


def test_the_product_adapter_derives_the_root_by_walking_rather_than_counting() -> None:
    # the other half of the same statement, in the file that is supposed to own it: paths.py hands the
    # kernel a start location and nothing else, and simplon.context.bootstrap does the walking
    rel = "deploy/orchestrator/src/python/orchestrator/paths.py"

    assert 'context.bootstrap("simplon", Path(__file__).resolve().parent)' in (
        ROOT / rel).read_text(encoding="utf-8")
    assert not _counts_out_a_parent(rel)


def test_the_kernels_block_is_what_its_scaffolder_would_have_written_there(tmp_path) -> None:
    """The ticket's Gegenprobe: `simplon init --orch-dir deploy/orchestrator` and the kernel's own tree
    must agree about the SHAPE -- the file set and where it hangs.

    Not about the CONTENTS: simplon's manifest and its `cli.py` are grown, they carry its three real
    commands, and a scaffold cannot know them. What a fresh scaffold does decide is the layout, and if
    the two disagreed about that, one of them would be wrong and it would not be obvious which.
    """
    # arrange
    bootstrap.write("simplon", tmp_path, orch_dir=OWN_ORCH_DIR)

    # act: every path the scaffolder places under the block, relative to the block
    block = tmp_path / "deploy" / "orchestrator"
    scaffolded = sorted(p.relative_to(block).as_posix() for p in block.rglob("*") if p.is_file())
    own_block = ROOT / "deploy" / "orchestrator"
    own = sorted(p.relative_to(own_block).as_posix() for p in own_block.rglob("*")
                 if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts)

    # assert
    assert scaffolded == own
