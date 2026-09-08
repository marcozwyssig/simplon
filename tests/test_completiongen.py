"""Unit tests for simplon.completiongen (si#58): the manifest -> shell completion generator.

WHAT THIS FILE IS FOR, and it is not "the generator produces some text". The generated file is a SECOND
description of the command tree, and a second description is worth having only while something holds it
against the first. Two things do:

  * `test_the_completion_offers_exactly_what_the_assembled_app_offers` - the completion tree is compared
    to the tree Typer really assembles from the same manifest, walked as Click objects. That is the join.
    A rule this module gets wrong about flat groups, group-default groups, nested groups or hidden
    commands shows up there as a difference, not as a green run over a fixture that agreed with itself;
  * `tests/test_own_completion.py` - the committed file against simplon's own manifest.

The generated SHELL is executed rather than read (`_complete` below runs bash), because a `case`
statement that is one quote short is still a perfectly good Python string. Every assertion about what a
user sees runs the file in a real bash and reads COMPREPLY back.

AAA throughout.
"""
import shutil
import subprocess
import textwrap

import pytest
import typer
from typer.main import get_command

from simplon import cli, completiongen
from simplon.orchestrator import manifest as manifest_mod

BASH = shutil.which("bash")

_MANIFEST = """
product: demo
tasks:
  one:   { impl: "simplon.test_impls:nullary", help: "One." }
  two:   { impl: "simplon.test_impls:nullary", help: "Two." }
  three: { impl: "simplon.test_impls:nullary", help: "Three." }
  four:  { impl: "simplon.test_impls:nullary", help: "Four." }
  five:  { impl: "simplon.test_impls:nullary", help: "Five." }
  six:   { impl: "simplon.test_impls:nullary", help: "Six." }
  seven: { impl: "simplon.test_impls:nullary", help: "Seven." }

groups:
  # a collapsed single-member flat group: its member is a VISIBLE top-level command, no group token
  package:
    commands:
      package: { task: one }
  # a multi-member group whose name is also a member: the bare token runs the namesake
  build:
    commands:
      build: { task: two }
      diff:  { task: three }
  # an ordinary group, one of whose members is hidden from --help
  test:
    commands:
      unit:  { task: four }
      inner: { task: five, hidden: true }
  # a NESTED group
  support:
    groups:
      git:
        commands:
          commit: { task: six }
  # an env-first group
  deploy:
    commands:
      up: { task: seven }
env_groups: [deploy]
default: dev
environments:
  dev:  { backend: local }
  prod: { backend: local }
"""


def _manifest(text=_MANIFEST):
    return manifest_mod.load(textwrap.dedent(text))


def _tree(text=_MANIFEST, environments=("dev", "prod")):
    return completiongen.tree(_manifest(text), environments=environments)


def _complete(text, line, product="demo"):
    """What bash's COMPREPLY holds after `line` - the generated file RUN, not inspected.

    `line` is the whole command line with the cursor at its end; the words are handed to the generated
    function the way bash's completion machinery hands them over (COMP_WORDS / COMP_CWORD), so what comes
    back is the answer a user would see. A trailing space means the cursor sits on a fresh, empty word,
    which is exactly the `<TAB>` at the start of a new token.
    """
    words = line.split(" ")
    script = "\n".join([
        "source /dev/stdin <<'__COMPLETION__'",
        text,
        "__COMPLETION__",
        "COMP_WORDS=(" + " ".join(f"'{w}'" for w in words) + ")",
        f"COMP_CWORD={len(words) - 1}",
        f"{completiongen.identifier(product)}_complete",
        'printf "%s\\n" "${COMPREPLY[@]}"',
    ])
    done = subprocess.run([BASH, "--noprofile", "--norc", "-c", script],
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return sorted(word for word in done.stdout.split("\n") if word)


@pytest.fixture
def rendered():
    return completiongen.render(_tree(), product="demo", source="demo.yaml")


# --- the tree, as data ---------------------------------------------------------------------------------


def test_the_root_offers_the_groups_and_the_collapsed_flat_command():
    """The two shapes that share the first position, and they are not the same kind of thing: `build`,
    `test`, `support` and `deploy` are groups with a sub-app, while `package` is a single-member group
    that `assemble` collapses onto ONE visible top-level command. A completion that offered only groups
    would leave a command nobody could reach by TAB."""
    # arrange / act
    root = _tree().nodes[""]

    # assert
    assert set(root) == {"package", "build", "test", "support", "deploy", "dev", "prod"}


def test_a_hidden_command_is_not_offered():
    """DECIDED, not derived (si#58 question 3). `inner` declares `hidden: true`, so it is absent from
    `--help` on purpose; completion is the same surface - what the tool volunteers when asked what it can
    do - so offering it would overrule the product's own statement about its surface. It stays
    invocable."""
    # arrange / act
    test_group = _tree().nodes["test"]

    # assert
    assert test_group == ("unit",)


def test_a_group_default_group_offers_its_siblings_and_not_its_namesake():
    """`demo build` runs the namesake member, `demo build diff` the sibling. There is no `demo build
    build`, so offering `build` under `build` would complete a line that does not dispatch."""
    # arrange / act
    build = _tree().nodes["build"]

    # assert
    assert build == ("diff",)


def test_a_nested_group_is_addressed_by_its_leaf_and_carries_its_own_members():
    """`demo support git commit`, and the dotted path never reaches the shell - it is only this module's
    key for the node."""
    # arrange / act
    spec = _tree()

    # assert
    assert spec.nodes["support"] == ("git",)
    assert spec.nodes["support.git"] == ("commit",)


def test_an_environment_is_offered_only_where_an_env_first_group_exists():
    """`simplon.cli.main` refuses an explicit env to an agnostic group, so a product with no env-first
    group must not have environments completed at all - every such completion would be a line the
    dispatcher then rejects."""
    # arrange: the same manifest with its one env-first group made agnostic
    agnostic = _MANIFEST.replace("env_groups: [deploy]", "env_groups: []")

    # act
    spec = _tree(agnostic)

    # assert
    assert spec.environments == ()
    assert "dev" not in spec.nodes[""]


def test_an_environment_that_names_a_group_is_not_offered():
    """`main` consumes a leading env token only when the token names no GROUP - which is how netctl's
    `test` environment and `test` group coexist. Completing it would suggest an environment selection the
    very next token turns into a group dispatch."""
    # arrange: an environment called `test`, beside the `test` GROUP the manifest already declares
    text = _MANIFEST.replace("  prod: { backend: local }", "  test: { backend: local }")

    # act
    spec = _tree(text, environments=("dev", "test"))

    # assert
    assert spec.environments == ("dev",)


def test_after_an_environment_only_the_env_first_groups_are_offered():
    """The second position after an env token is not the root again: an agnostic group given an explicit
    env is refused by the dispatch, so `deploy` is the only thing worth offering there."""
    # arrange / act
    spec = _tree()

    # assert
    assert spec.nodes[completiongen.ENV_NODE] == ("deploy",)


def test_a_name_the_shell_cannot_say_is_refused_where_it_was_declared():
    """DIAGNOSIS, not an expression rule: such a name cannot be typed as a shell token in the first
    place, so nothing a product could legitimately want is refused. What it prevents is a manifest
    turning into a `case` arm that is a glob or an unbalanced quote in somebody's interactive shell,
    where the failure arrives with no connection to the manifest that caused it."""
    # arrange
    text = _MANIFEST.replace("      unit:  { task: four }", "      \"uni t\":  { task: four }")

    # act / assert
    with pytest.raises(ValueError, match=r"command 'test uni t'"):
        _tree(text)


# --- the join: the completion against the app that is really assembled ----------------------------------


def _click_tree(mf, product="demo"):
    """Every VISIBLE path through the app Typer really assembles, as `{node: (tokens, ...)}`.

    Read off Click objects rather than off `--help` text, for the reason `simplon.tasks.cliref` gives: a
    chapter parsed out of formatted output still looks like a chapter when the format changes under it.
    """
    app = typer.Typer(add_completion=False)
    cli.assemble(app, mf, product=product)
    out: dict[str, tuple[str, ...]] = {}

    def walk(command, path):
        names = []
        for name, sub in getattr(command, "commands", {}).items():
            if sub.hidden:
                continue
            names.append(name)
            walk(sub, f"{path}.{name}" if path else name)
        if names:
            out[path] = tuple(sorted(names))

    walk(get_command(app), "")
    return out


def test_the_completion_offers_exactly_what_the_assembled_app_offers():
    """THE JOIN, and the reason this file is worth more than a golden-text comparison.

    The completion is a second description of the command tree. This holds it against the first - the
    Typer application `simplon.cli.assemble` really builds from the same manifest - so a rule about flat
    groups, group-default groups, nesting or hidden commands that this generator gets wrong is a
    DIFFERENCE here rather than a fixture agreeing with itself.

    The environment tokens are removed before comparing: they are not commands, Click has never heard of
    them, and `simplon.cli.main` consumes them before the app is called at all.
    """
    # arrange
    mf = _manifest()
    spec = completiongen.tree(mf, environments=("dev", "prod"))

    # act
    completed = {node: tuple(sorted(set(words) - set(spec.environments)))
                 for node, words in spec.nodes.items() if node != completiongen.ENV_NODE}

    # assert
    assert completed == _click_tree(mf)


# --- the generated shell, executed -----------------------------------------------------------------------


@pytest.mark.skipif(BASH is None, reason="no bash on this host to run the generated file with")
def test_the_generated_file_completes_the_groups_at_the_first_position(rendered):
    # arrange / act
    reply = _complete(rendered, "./demo.sh ")

    # assert
    assert reply == ["build", "deploy", "dev", "package", "prod", "support", "test"]


@pytest.mark.skipif(BASH is None, reason="no bash on this host to run the generated file with")
def test_the_generated_file_completes_a_nested_group_member(rendered):
    # arrange / act
    reply = _complete(rendered, "./demo.sh support git c")

    # assert
    assert reply == ["commit"]


@pytest.mark.skipif(BASH is None, reason="no bash on this host to run the generated file with")
def test_the_generated_file_completes_after_an_environment_token(rendered):
    """The env-first line, end to end in a shell: the token is consumed and the second position offers
    the env-first group rather than the whole root again."""
    # arrange / act
    reply = _complete(rendered, "./demo.sh dev ")

    # assert
    assert reply == ["deploy"]


@pytest.mark.skipif(BASH is None, reason="no bash on this host to run the generated file with")
def test_the_generated_file_says_nothing_past_a_leaf(rendered):
    """A command's own options and arguments are not described here, so the function answers nothing and
    `complete -o default` gives the user filenames - which is what bash would have done for an
    unregistered command anyway. Answering the root's groups again would be worse than saying nothing."""
    # arrange / act
    reply = _complete(rendered, "./demo.sh test unit ")

    # assert
    assert reply == []


@pytest.mark.skipif(BASH is None, reason="no bash on this host to run the generated file with")
def test_the_generated_file_ignores_an_option_when_walking_the_tree(rendered):
    """An option is not a node. `demo --help support <TAB>` still stands inside `support`."""
    # arrange / act
    reply = _complete(rendered, "./demo.sh --verbose support ")

    # assert
    assert reply == ["git"]


@pytest.mark.skipif(BASH is None, reason="no bash on this host to run the generated file with")
def test_the_generated_file_is_syntactically_valid_shell(rendered):
    # arrange / act
    done = subprocess.run([BASH, "-n"], input=rendered, capture_output=True, text=True, timeout=30)

    # assert
    assert done.returncode == 0, done.stderr


# --- what the file says about itself --------------------------------------------------------------------


def test_the_file_registers_on_the_launcher_basename_not_on_the_typed_path(rendered):
    """MEASURED on bash 5.3.9(1) in a pty, because the manual's wording ("bash attempts to find a
    compspec for the portion following the final slash") is a claim about an implementation: with a
    compspec registered for `simplon.sh` alone, `./simplon.sh typech<TAB>` completed to
    `typecheck-python`, and so did the same line with an absolute path; with nothing sourced, neither
    completed anything. Registering on `./demo.sh` instead would work only from the product root."""
    # arrange / act / assert
    assert rendered.rstrip().endswith("complete -o default -F _demo_complete demo.sh")


def test_the_file_says_where_it_came_from_and_how_to_install_it(rendered):
    """A generated file has to explain itself to whoever opens it, and this one has a second job: it is
    inert until somebody sources it. Both sentences are in the header, and the install line carries no
    absolute path - the file is committed, so a machine-specific byte in it would make two checkouts of
    one commit disagree and turn the drift gate into noise."""
    # arrange / act
    header = [line for line in rendered.splitlines() if line.startswith("#")]

    # assert
    assert any("GENERATED from demo.yaml" in line for line in header)
    assert any(".bashrc" in line for line in header)
    assert any("bashcompinit" in line for line in header), "the one zsh sentence is missing"
    assert not any(line.startswith("#     echo \"source /") for line in header)


def test_a_second_render_of_the_same_manifest_is_byte_identical():
    """Determinism is what makes `--check` a gate rather than a coin toss."""
    # arrange / act
    first = completiongen.render(_tree(), product="demo", source="demo.yaml")
    second = completiongen.render(_tree(), product="demo", source="demo.yaml")

    # assert
    assert first == second


def test_the_function_names_are_derived_from_the_product():
    """A product cannot end up with a completion whose functions are named after a different one, and a
    name with a dash in it still has to produce a legal shell identifier."""
    # arrange / act / assert
    assert completiongen.identifier("agile-cockpit") == "_agile_cockpit"
    assert completiongen.identifier("simplon") == "_simplon"


# --- write and check -------------------------------------------------------------------------------------


def test_a_missing_file_is_drift_rather_than_an_error(tmp_path):
    """A fresh checkout that has never generated has to be TOLD what to run. Raising there would read as
    a broken gate rather than as the ordinary thing it is - the stance `simplon.workflowgen` and
    `simplon.taskgen` already take."""
    # arrange / act
    drift = completiongen.check(_tree(), tmp_path, product="demo", source="demo.yaml")

    # assert
    assert drift is not None and drift.path == "deploy/completions/demo.bash"


def test_write_reports_whether_the_bytes_changed(tmp_path):
    """`True` on the first write and `False` on the second, so a caller can say "regenerated" or "already
    up to date" instead of claiming one of them every time."""
    # arrange / act
    first = completiongen.write(_tree(), tmp_path, product="demo", source="demo.yaml")
    second = completiongen.write(_tree(), tmp_path, product="demo", source="demo.yaml")

    # assert
    assert (first, second) == (True, False)
    assert (tmp_path / "deploy" / "completions" / "demo.bash").exists()


def test_a_grown_manifest_makes_check_report_the_new_command(tmp_path):
    """THE PROPERTY si#58's acceptance asks for, stated where it can be seen red: a command joins the
    manifest, the committed completion does not know it, and the check says so - naming it in the diff so
    the reader does not have to work out which of thirty lines moved.
    """
    # arrange: a written file, then a manifest that has grown a command
    completiongen.write(_tree(), tmp_path, product="demo", source="demo.yaml")
    grown = _MANIFEST.replace("      unit:  { task: four }",
                              "      unit:  { task: four }\n      smoke: { task: four }")

    # act
    drift = completiongen.check(_tree(grown), tmp_path, product="demo", source="demo.yaml")

    # assert
    assert drift is not None
    assert "smoke" in drift.diff
