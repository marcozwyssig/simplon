"""simplon's OWN shell completion, held against simplon's own manifest (si#58).

WHY THIS FILE EXISTS SEPARATELY from test_completiongen.py. That module proves the generator works and
that what it renders is what Typer really assembles. This one proves the generator is USED - that
`completions/simplon.bash` is the file `simplon.yaml` describes, today, in this commit. It is the drift
gate itself, run by the product's own unit suite, exactly as `support completion --check` is meant to be.

THE RULE IT KEEPS is this repository's oldest: a tool never used in its own house rots unseen. simplon
builds, tests, releases, documents and generates its workflows with the kernel it ships; a completion
generator it shipped and did not point at itself would be the same omission one output further along.

WHY A DRIFT GATE IS THE WHOLE PRICE OF THIS FEATURE. The generated file exists because a TAB must not
start an interpreter - measured, 340-360 ms per start against 0.16 ms for one call of the generated
function, some two thousand times - and that speed is bought by writing the command tree down a second
time. A second source that nothing checks is worse than no completion at all: a completion that has
fallen behind fails in the quietest way there is, since the command still runs when it is typed in full
and only the TAB goes silent. So the second source is bought and the check is what pays for it.

WHAT THIS DOES NOT CLAIM. Not that any shell has sourced the file - that takes a real interactive
session, and `tests/test_completiongen.py` runs the generated text through bash for the part that can be
measured here. What this holds is the thing that would make such a session quietly wrong: a completion
that no longer says what the manifest says.
"""
import subprocess

import yaml

from simplon import catalogue as catalogue_mod, completiongen, context
from simplon.orchestrator import manifest as manifest_mod

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"

#: The product token the launcher carries, and therefore the one the generated file must be named and
#: registered for.
PRODUCT = "simplon"


def _source():
    return MANIFEST.read_text(encoding="utf-8")


def _tree():
    raw = yaml.safe_load(_source())
    mf = manifest_mod.load(_source(), catalogue=catalogue_mod.load())
    return completiongen.tree(mf, environments=completiongen.environments_of(raw))


def _committed():
    return (ROOT / completiongen.path_for(PRODUCT)).read_text(encoding="utf-8")


# --- the gate ---------------------------------------------------------------------------------------


def test_the_committed_completion_agrees_with_the_manifest():
    """THE drift gate, and the reason `--check` exists at all.

    This is the assertion si#58's acceptance asks for: it falls when a command joins `simplon.yaml` and
    `completions/simplon.bash` does not know it. Seen red before it was believed - a command added to the
    manifest and the file left alone makes it fail with the new name in the diff.
    """
    # arrange / act
    drift = completiongen.check(_tree(), ROOT, product=PRODUCT, source=MANIFEST.name)

    # assert
    assert drift is None, (
        "the committed shell completion no longer says what simplon.yaml says; regenerate with "
        "`./simplon.sh support completion`\n" + (drift.diff if drift else ""))


def test_the_gate_is_ruling_on_something():
    """A check over a file that is not there goes green in every implementation that treats absence as
    "nothing to do" - which this one deliberately does not, but the file still has to be the one the
    product ships. So the path is named here as well, and a rename has to say what now carries the
    completion."""
    # arrange / act
    path = completiongen.path_for(PRODUCT)

    # assert
    assert path == "completions/simplon.bash"
    assert (ROOT / path).is_file()


def test_the_committed_completion_covers_every_group_the_manifest_declares():
    """The gate above compares BYTES, which is what makes it exact and also what makes it silent about
    what it is comparing: a generator that started emitting an empty tree would still agree with a
    committed empty tree. This names the join the bytes stand for - every group path the manifest holds
    is a node in the file - so both halves would have to go wrong together."""
    # arrange
    mf = manifest_mod.load(_source(), catalogue=catalogue_mod.load())
    text = _committed()

    # act / assert
    assert mf.groups, "the manifest declares no groups at all, so this test is ruling on nothing"
    for group in mf.groups:
        assert f"'{group}') _simplon_reply=(" in text, f"the completion has no node for '{group}'"
        for name in mf.groups[group]:
            assert f"'{name}'" in text, f"'{group} {name}' is not completable"


def test_the_committed_completion_registers_on_the_launcher_this_product_ships():
    """`simplon.sh` and not `./simplon.sh`, measured rather than read - see
    `test_completiongen.test_the_file_registers_on_the_launcher_basename_not_on_the_typed_path`. And it
    is the file that actually exists at the root, so a rename of the launcher takes this red with it."""
    # arrange / act
    text = _committed()

    # assert
    assert text.rstrip().endswith(f"complete -o default -F _simplon_complete {context.shim(PRODUCT)}")
    assert (ROOT / context.shim(PRODUCT)).is_file()


def test_the_committed_completion_is_shell_bash_will_accept():
    """The file is committed, so it is what a user sources - and a syntax error in it does not fail the
    build, it breaks the shell of whoever installed it. `bash -n` parses without executing."""
    # arrange / act
    done = subprocess.run(["bash", "-n"], input=_committed(), capture_output=True, text=True, timeout=30)

    # assert
    assert done.returncode == 0, done.stderr


# --- the two decisions this repository made, stated as assertions ----------------------------------


def test_simplon_completes_no_environment_because_it_has_no_env_first_group():
    """A DECISION with a measurable consequence (si#58 question 2). simplon declares `env_groups: []`,
    so `simplon.cli.main` would refuse an explicit env to every one of its groups - and completing `dev`
    at the first position would have offered a token that leads only to that refusal. The environments
    are still read from the manifest; there is simply nothing there to read."""
    # arrange
    mf = manifest_mod.load(_source(), catalogue=catalogue_mod.load())

    # act
    spec = _tree()

    # assert
    assert mf.env_groups == frozenset()
    assert spec.environments == ()
    assert "@env" not in spec.nodes


def test_the_hidden_flat_aliases_are_not_completed():
    """The OTHER decision (si#58 question 3). Every grouped command is additionally registered as a
    hidden flat alias, so `./simplon.sh generate` works - and it is deliberately absent from `--help`.
    Completion is the same surface, so it is absent here too, which is why the root offers four groups
    rather than four groups and seventeen aliases."""
    # arrange
    mf = manifest_mod.load(_source(), catalogue=catalogue_mod.load())
    aliases = {name for names in mf.groups.values() for name in names}

    # act
    root = set(_tree().nodes[""])

    # assert: there really ARE such aliases, and none of them is at the root
    assert "generate" in aliases and "commit" in aliases
    assert root == set(mf.groups) - {group for group in mf.groups if "." in group}
    assert not (root & aliases), f"a hidden flat alias reached the first position: {sorted(root & aliases)}"
