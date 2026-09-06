"""Unit tests for simplon.workflowgen (si#40): the manifest's SECOND output.

WHAT IS ACTUALLY WORTH ASSERTING HERE, because "the generator wrote a file" is not it. si#40 names two
traps and both are measured in this module rather than described:

  * YAML 1.1 READS `on:` AS A BOOLEAN, on BOTH sides. A manifest author writing the trigger the natural
    way hands the parser a mapping keyed by `True` - that one bit the very first run of this module
    against simplon's own manifest - and a renderer that dumped a document back out would write `true:`,
    which GitHub does not read as a trigger at all. So there is a test for each direction, and the
    emitting one reads the raw TEXT: a parsed document cannot tell `on:` from `true:`, because both land
    on the same key, so a test that only parsed would pass while the file was dead.

  * A WORKFLOW NOBODY CAN RUN IS WORTH NOTHING. `render` parses its own output back and refuses anything
    GitHub would not execute. The tests below drive that from the inside (`validate` against each broken
    shape) rather than trusting it to be exercised by the good cases.

AND THE JOIN, which is the whole reason this exists rather than a YAML template: a step says
`command: test all` and it is resolved against the loaded manifest. A workflow can no longer name a
command that does not exist, which is the property agile-cockpit's five hand-typed command lines have
never had.

AAA throughout.
"""
import textwrap

import pytest
import yaml

from simplon import catalogue as catalogue_mod, workflowgen
from simplon.orchestrator import manifest as manifest_mod

from conftest import ROOT

#: A throwaway product whose command tree is real enough to resolve against. `stamp` under `support.git`
#: rather than one of the catalogue's own git verbs, for the reason test_tasks_tasks.py gives: the
#: catalogue PLACES commit/push there, and a second body under a placed name is refused by design.
_MANIFEST = """
tasks:
  stamp: { impl: "simplon.test_impls:nullary", help: "Stamp the tree." }
  suite: { impl: "simplon.test_impls:nullary", help: "Run every test." }

groups:
  test:
    commands:
      all: { task: suite }
  support:
    groups:
      git:
        commands:
          stamp: { task: "stamp" }
env_groups: []
"""


@pytest.fixture(scope="module")
def manifest():
    """The fixture product's manifest, loaded the way the CLI loads it."""
    return manifest_mod.load(_MANIFEST, catalogue=catalogue_mod.load())


def _section(body: str) -> dict:
    """A raw manifest carrying just a `workflows:` section, parsed the way `manifest_data()` parses one.

    Through `yaml.safe_load` deliberately, and it is not a convenience: writing the declarations as
    Python dicts would hand the parser a `"on"` key it never sees in real life, and the whole first half
    of this module is about what YAML actually produces for that word.
    """
    return yaml.safe_load(textwrap.dedent(body))


def _render(manifest, body: str, key: str = "ci") -> str:
    workflows = workflowgen.parse(_section(body))
    picked = next(w for w in workflows if w.key == key)
    return workflowgen.render(picked, manifest=manifest, product="sample", source="sample.yaml")


_MINIMAL = """
    workflows:
      ci:
        on: [push]
        jobs:
          build:
            runs-on: ubuntu-latest
            steps:
              - command: test all
    """


# --- trap 1, reading: YAML 1.1 puts a bare `on:` under the boolean key --------------------------------


def test_a_bare_on_key_in_the_manifest_is_read_as_the_trigger(manifest):
    """THE trap, on the input side, and it is not hypothetical: it broke the first run of this generator
    against simplon's own manifest.

    `yaml.safe_load("on: [push]")` returns a mapping keyed by `True`, so a parser looking for the string
    `"on"` finds nothing and reports a manifest with a perfectly good trigger as declaring none. The
    author must be able to write the trigger exactly as it is written in a workflow file.
    """
    # Arrange: prove the premise rather than assume it - this is the fact the rest of the test rests on
    raw = _section(_MINIMAL)
    assert True in raw["workflows"]["ci"], "PyYAML stopped reading `on` as a boolean; retire this test"
    assert "on" not in raw["workflows"]["ci"]

    # Act
    workflows = workflowgen.parse(raw)

    # Assert
    assert workflows[0].on == ["push"]


def test_a_quoted_on_key_is_read_as_the_trigger_too(manifest):
    """The other spelling, because an author who knows about the trap writes `"on":` to dodge it and must
    not be punished for knowing."""
    # Arrange / Act
    workflows = workflowgen.parse(_section("""
    workflows:
      ci:
        "on": [push]
        jobs:
          build: { runs-on: ubuntu-latest, steps: [{ command: test all }] }
    """))

    # Assert
    assert workflows[0].on == ["push"]


def test_declaring_the_trigger_under_both_spellings_is_refused():
    """Two keys carrying one meaning, with only PyYAML's ordering deciding which wins. Refused rather
    than resolved: a declaration whose meaning depends on a detail nobody should have to know is worse
    than one that does not load."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="declares the trigger twice"):
        workflowgen.parse(_section("""
        workflows:
          ci:
            on: [push]
            "on": [pull_request]
            jobs:
              build: { runs-on: ubuntu-latest, steps: [{ command: test all }] }
        """))


# --- trap 1, writing: the rendered file must say `on:` and not `true:` -------------------------------


def test_the_rendered_trigger_is_spelled_on_and_not_true(manifest):
    """THE trap on the output side, asserted against the raw TEXT because nothing else can see it.

    `yaml.safe_dump({True: ...})` writes `true:`, and GitHub reads that as a job-less document with a
    key it does not know - the workflow never runs. Parsed back, `true:` and `on:` land on the SAME key,
    so a test that only inspected the document would be green over a dead file. That is precisely the
    shape si#40 warns about: not finding something in a section you never had, and reading the miss as
    an answer.
    """
    # Arrange / Act
    text = _render(manifest, _MINIMAL)

    # Assert
    assert "\non:\n" in text, f"the trigger is not spelled `on:` in the rendered text:\n{text}"
    assert "\ntrue:" not in text
    assert "\n'on':" not in text


def test_the_rendered_trigger_reads_back_under_the_boolean_key(manifest):
    """And the other half: what was written really is a trigger once GitHub's parser has it."""
    # Arrange
    text = _render(manifest, _MINIMAL)

    # Act
    doc = yaml.safe_load(text)

    # Assert
    assert workflowgen.trigger_of(doc) == ["push"]


# --- trap 2: what came out has to be a workflow, not merely a file -----------------------------------


def test_the_rendered_workflow_is_something_github_would_run(manifest):
    """The cheap half of "does this actually work", answered at generation time for nothing: it parses,
    it has a name, it has a trigger, and every job has a runner and at least one step."""
    # Arrange / Act
    doc = yaml.safe_load(_render(manifest, _MINIMAL))

    # Assert
    assert doc["name"] == "ci"
    assert doc["jobs"]["build"]["runs-on"] == "ubuntu-latest"
    assert doc["jobs"]["build"]["steps"]


@pytest.mark.parametrize("text, complaint", [
    ("[]", "not a mapping"),
    ("name: ''\non: [push]\njobs: { a: { runs-on: x, steps: [{run: y}] } }", "no `name:`"),
    ("name: ci\njobs: { a: { runs-on: x, steps: [{run: y}] } }", "no `on:` trigger"),
    ("name: ci\non:\njobs: { a: { runs-on: x, steps: [{run: y}] } }", "trigger is empty"),
    ("name: ci\non: [push]\njobs: {}", "declares no jobs"),
    ("name: ci\non: [push]\njobs: { a: { steps: [{run: y}] } }", "has no `runs-on`"),
    ("name: ci\non: [push]\njobs: { a: { runs-on: x, steps: [] } }", "has no steps"),
    ("name: ci\non: [push]\njobs: { a: [1, 2] }", "is not a mapping"),
    ("name: ci\non: [push\njobs: {}", "not valid YAML"),
])
def test_validate_refuses_a_document_that_is_not_a_runnable_workflow(text, complaint):
    """Driven from the inside, one broken shape at a time. Left to be exercised only by the good cases,
    a validator's branches are code nothing has ever run."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match=complaint):
        workflowgen.validate(text, where="under test")


def test_an_empty_trigger_is_told_apart_from_an_absent_one():
    """`on:` with nothing under it parses to None under the boolean key - present, and worth nothing.

    Two messages rather than one, and the distinction is this repository's oldest rule applied to its
    own diagnostics: "the key is missing" and "the key is there and says nothing" are different
    situations, they have different fixes, and a check that reported them identically would send
    somebody looking in the wrong place.
    """
    # Arrange
    jobs = "jobs: { a: { runs-on: x, steps: [{run: y}] } }"

    # Act / Assert
    with pytest.raises(ValueError, match="carries no `on:` trigger"):
        workflowgen.validate(f"name: ci\n{jobs}", where="under test")
    with pytest.raises(ValueError, match="`on:` trigger is empty"):
        workflowgen.validate(f"name: ci\non:\n{jobs}", where="under test")


# --- the join: a step names a command the manifest actually declares ---------------------------------


def test_a_command_step_becomes_the_launcher_line_a_developer_types(manifest):
    """THE point of the whole module. The workflow says `test all`; what is written is the command a
    human runs in a checkout, so there is one route to the verdict rather than two."""
    # Arrange / Act
    doc = yaml.safe_load(_render(manifest, _MINIMAL))

    # Assert
    assert [step["run"] for step in doc["jobs"]["build"]["steps"] if "run" in step] == \
        ["./sample.sh test all"]


def test_a_nested_group_is_addressed_by_its_path(manifest):
    """`support.git stamp` is typed `sample support git stamp`, so that is what is written. Using the
    dotted path would put a string in the file that nobody can run."""
    # Arrange / Act
    doc = yaml.safe_load(_render(manifest, """
    workflows:
      ci:
        on: [push]
        jobs:
          build:
            runs-on: ubuntu-latest
            steps:
              - command: support git stamp
    """))

    # Assert
    assert doc["jobs"]["build"]["steps"][-1]["run"] == "./sample.sh support git stamp"


def test_a_command_the_manifest_does_not_declare_stops_generation(manifest):
    """The property agile-cockpit's five hand-typed command lines have never had. A renamed command
    breaks generation here, loudly, instead of leaving a workflow calling something that is gone and
    finding out on a runner."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="names no command in group 'test'"):
        _render(manifest, """
        workflows:
          ci:
            on: [push]
            jobs:
              build: { runs-on: ubuntu-latest, steps: [{ command: test unit }] }
        """)


def test_the_refusal_names_what_the_group_does_hold(manifest):
    """A refusal that only says no makes somebody go and read the manifest; one that lists the members
    answers the question it raised."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="it holds: all"):
        workflowgen.resolve_command(manifest, "test unit", where="under test")


def test_a_command_naming_an_unknown_group_is_refused(manifest):
    """And the groups it could have meant are listed for the same reason."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="names group 'deploy', which this manifest does not declare"):
        workflowgen.resolve_command(manifest, "deploy all", where="under test")


def test_a_one_word_command_is_refused(manifest):
    """A command is a group and a name. One token could only be guessed at, and the guess would be
    written into a file nobody re-reads."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="must name a group and a command"):
        workflowgen.resolve_command(manifest, "all", where="under test")


# --- what the kernel contributes, and what it carries through ----------------------------------------


def test_every_job_gets_the_full_history_without_asking_for_it(manifest):
    """si#3's invariant, emitted rather than declared.

    `tests/test_version_source.py` asserts this over the whole workflows directory precisely because a
    NEW workflow gets actions/checkout's default and the default is wrong here. Making it the
    generator's makes a workflow written next year inherit the rule rather than depend on somebody
    remembering it.
    """
    # Arrange / Act
    doc = yaml.safe_load(_render(manifest, _MINIMAL))

    # Assert
    checkout = doc["jobs"]["build"]["steps"][0]
    assert checkout["uses"].startswith("actions/checkout")
    assert checkout["with"]["fetch-depth"] == 0


def test_the_reason_for_the_full_history_is_written_into_the_file(manifest):
    """The setting moved into the generator; its justification had to move with it.

    It used to sit in simplon's own ci.yml as a hand-written comment. A reader who opens the generated
    file and finds `fetch-depth: 0` with nowhere to learn why is exactly the loss si#40 says a generator
    must not cause - so the kernel's prose is emitted with the kernel's setting.
    """
    # Arrange / Act
    text = _render(manifest, _MINIMAL)

    # Assert
    assert "# The full history" in text
    assert "setuptools-scm" in text


def test_a_job_may_decline_the_checkout(manifest):
    """An escape hatch that is visible in the manifest, and therefore arguable. A job needing something
    else says so; it does not get it by a default nobody wrote down."""
    # Arrange / Act
    doc = yaml.safe_load(_render(manifest, """
    workflows:
      ci:
        on: [push]
        jobs:
          build:
            runs-on: ubuntu-latest
            checkout: false
            steps:
              - uses: actions/checkout@v4
                with: { fetch-depth: 1 }
    """))

    # Assert
    assert [step["uses"] for step in doc["jobs"]["build"]["steps"]] == ["actions/checkout@v4"]
    assert doc["jobs"]["build"]["steps"][0]["with"]["fetch-depth"] == 1


def test_the_interpreter_version_stays_a_string(manifest):
    """`3.12` unquoted is the NUMBER 3.12, and setup-python would be handed 3.1 - a real Python that is
    not the one anybody meant. The dumper decides the quoting, so this holds the outcome rather than the
    mechanism."""
    # Arrange / Act
    text = _render(manifest, """
    workflows:
      ci:
        on: [push]
        jobs:
          build:
            runs-on: ubuntu-latest
            python: "3.12"
            steps: [{ command: test all }]
    """)

    # Assert
    assert yaml.safe_load(text)["jobs"]["build"]["steps"][1]["with"]["python-version"] == "3.12"
    assert "python-version: '3.12'" in text


def test_a_job_that_declares_no_python_gets_no_opinion_about_one(manifest):
    """The kernel contributes an interpreter where one was asked for and nowhere else. A default here
    would be simplon's Python imposed on every product."""
    # Arrange / Act
    doc = yaml.safe_load(_render(manifest, _MINIMAL))

    # Assert
    assert not [s for s in doc["jobs"]["build"]["steps"] if "setup-python" in str(s.get("uses", ""))]


def test_the_product_keys_the_kernel_does_not_understand_are_carried_through(manifest):
    """Permissions, environments, `needs:`, concurrency, `if:` - the release and Pages shapes are made
    of these, and they are the PRODUCT's.

    Carried rather than enumerated: a kernel that listed the job keys it allows would be the gatekeeper
    of GitHub's schema, and would be wrong the week GitHub adds one.
    """
    # Arrange / Act
    doc = yaml.safe_load(_render(manifest, """
    workflows:
      release:
        on: { push: { tags: ["v*"] } }
        jobs:
          publish:
            runs-on: ubuntu-latest
            environment: pypi
            permissions: { id-token: write }
            steps: [{ command: test all }]
          docs:
            needs: publish
            runs-on: ubuntu-latest
            environment: { name: github-pages, url: "${{ steps.deployment.outputs.page_url }}" }
            permissions: { pages: write, id-token: write }
            concurrency: { group: pages, cancel-in-progress: false }
            steps:
              - uses: actions/upload-pages-artifact@v3
                with: { path: build/website }
    """, key="release"))

    # Assert
    assert workflowgen.trigger_of(doc) == {"push": {"tags": ["v*"]}}
    assert doc["jobs"]["publish"]["permissions"] == {"id-token": "write"}
    assert doc["jobs"]["publish"]["environment"] == "pypi"
    assert doc["jobs"]["docs"]["needs"] == "publish"
    assert doc["jobs"]["docs"]["concurrency"] == {"group": "pages", "cancel-in-progress": False}
    assert doc["jobs"]["docs"]["environment"]["url"] == "${{ steps.deployment.outputs.page_url }}"


def test_a_verbatim_step_keeps_a_multi_line_script_intact(manifest):
    """The half of a real release workflow the kernel has no business modelling: a shell script that
    reports something. Dumped as declared, newlines and all."""
    # Arrange
    script = "set -euo pipefail\nif ! git fetch origin; then\n  echo stale\nfi\nexit 0\n"

    # Act
    doc = yaml.safe_load(_render(manifest, """
    workflows:
      ci:
        on: [push]
        jobs:
          build:
            runs-on: ubuntu-latest
            steps:
              - name: Is this tag on main? (report only)
                run: |
                  set -euo pipefail
                  if ! git fetch origin; then
                    echo stale
                  fi
                  exit 0
    """))

    # Assert
    step = doc["jobs"]["build"]["steps"][-1]
    assert step["name"] == "Is this tag on main? (report only)"
    assert step["run"] == script


def test_the_declared_order_of_a_trigger_survives(manifest):
    """`sort_keys=False`, and it is not cosmetic: re-sorting would make the generated file disagree with
    the declaration it came from, for no reason, in a diff somebody has to read."""
    # Arrange / Act
    text = _render(manifest, """
    workflows:
      ci:
        on:
          push: { branches: [main] }
          pull_request: null
        jobs:
          build: { runs-on: ubuntu-latest, steps: [{ command: test all }] }
    """)

    # Assert
    assert text.index("push:") < text.index("pull_request:")


# --- the comments, which are the whole answer to "what happens to hand-written prose" ------------------


def test_prose_is_carried_at_every_level_it_can_be_declared(manifest):
    """si#40's second hard question, answered by carrying rather than by an escape hatch.

    A generator that dropped this would make the files worse than the hand-written ones it replaced -
    simplon's own release workflow is roughly two-thirds reasoning, and agile-cockpit's nightly carries
    measured values in its comments. So `note:` is allowed on the workflow, on a job and on a step, and
    lands as a comment in that position.
    """
    # Arrange / Act
    text = _render(manifest, """
    workflows:
      ci:
        note: |
          why this workflow exists
        on: [push]
        jobs:
          build:
            note: |
              why this job exists
            runs-on: ubuntu-latest
            steps:
              - note: |
                  measured at 16m03s
                command: test all
    """)

    # Assert
    assert "# why this workflow exists" in text
    assert "  # why this job exists" in text
    assert "      # measured at 16m03s" in text
    # and it is still a workflow afterwards
    assert yaml.safe_load(text)["jobs"]["build"]["steps"][-1]["run"] == "./sample.sh test all"


def test_a_paragraph_break_inside_a_note_survives_as_one(manifest):
    """A blank line becomes a bare `#`. Collapsing it would run two paragraphs of reasoning together,
    which is how carried prose quietly becomes unreadable prose."""
    # Arrange / Act
    text = _render(manifest, """
    workflows:
      ci:
        note: |
          first paragraph

          second paragraph
        on: [push]
        jobs:
          build: { runs-on: ubuntu-latest, steps: [{ command: test all }] }
    """)

    # Assert
    assert "# first paragraph\n#\n# second paragraph" in text


def test_the_step_a_note_belongs_to_is_the_one_it_sits_above(manifest):
    """Position is the whole of what a comment means. A note rendered above the wrong step would be
    worse than no note, because it would be believed."""
    # Arrange / Act
    text = _render(manifest, """
    workflows:
      ci:
        on: [push]
        jobs:
          build:
            runs-on: ubuntu-latest
            steps:
              - command: test all
              - note: about the second one
                command: support git stamp
    """)

    # Assert
    assert "# about the second one\n      - run: ./sample.sh support git stamp" in text


# --- a product's OWN workflow, which si#40 calls the actual requirement -------------------------------


def test_a_product_may_declare_a_workflow_the_kernel_knows_nothing_about(manifest):
    """ACCEPTANCE 3, and the reason this is a mechanism rather than three canned templates.

    A generator that only knew CI, release and Pages would be a dead end for the first product with a
    fourth - and agile-cockpit already has one, a nightly system run. Nothing in this module names a
    workflow kind, so a nightly is not a special case: it is a declaration like any other, with a
    schedule for a trigger and a step the kernel has never heard of beside one it resolves.
    """
    # Arrange / Act
    text = _render(manifest, """
    workflows:
      nightly:
        note: |
          The full system gate, measured at 16m03s. No `push` trigger, deliberately: it is too long to
          sit in front of a pull request, and a gate people learn to skip is worse than no gate.
        on:
          schedule:
            - cron: "0 2 * * *"
          workflow_dispatch: null
        jobs:
          system:
            runs-on: ubuntu-latest
            timeout-minutes: 45
            python: "3.12"
            steps:
              - command: test all
              - name: Publish the report
                if: always()
                uses: actions/upload-artifact@v4
                with: { name: allure, path: build/allure-report }
    """, key="nightly")
    doc = yaml.safe_load(text)

    # Assert: the trigger is the product's, the timeout is the product's, and the command is the join
    assert set(workflowgen.trigger_of(doc)) == {"schedule", "workflow_dispatch"}
    assert workflowgen.trigger_of(doc)["schedule"] == [{"cron": "0 2 * * *"}]
    assert doc["jobs"]["system"]["timeout-minutes"] == 45
    assert "./sample.sh test all" in [s.get("run") for s in doc["jobs"]["system"]["steps"]]
    assert doc["jobs"]["system"]["steps"][-1]["if"] == "always()"
    # and the measured reasoning is still in the file
    assert "16m03s" in text


def test_the_generator_carries_no_list_of_workflow_kinds():
    """The same requirement from the other side, and the one that would rot silently.

    "CI, release and Pages" appearing anywhere in this module as a set of known names would mean the
    fourth case works by accident today and breaks the first time somebody adds a branch for the three.
    """
    # Arrange
    source = (ROOT / "src" / "simplon" / "workflowgen.py").read_text(encoding="utf-8")

    # Act: the code, without the prose that legitimately discusses those words
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    code = code.split('"""')[0] + '"""'.join(code.split('"""')[2:])

    # Assert
    for special in ('"ci"', "'ci'", '"release"', "'release'", '"pages"', "'pages'"):
        assert special not in code, f"{special} is a workflow kind the generator special-cases"


# --- refusals over the declaration -------------------------------------------------------------------


def test_a_product_with_no_workflows_section_is_told_so():
    """Not handed an empty report. "Nothing declared" and "nothing wrong" are different answers, and a
    check that cannot tell them apart is this repository's recurring defect."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="declares no 'workflows' section"):
        workflowgen.parse({})


def test_an_empty_workflows_section_is_refused():
    """`workflows:` with nothing under it is somebody halfway through a thought, not a statement that
    this product has none."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="non-empty mapping"):
        workflowgen.parse({"workflows": {}})


@pytest.mark.parametrize("path, complaint", [
    ("ci.yml", "must be under '.github/workflows/'"),
    ("build/ci.yml", "must be under '.github/workflows/'"),
    ("/etc/ci.yml", "must be relative to the product root"),
    (".github/workflows/../../ci.yml", "must be relative to the product root"),
    (".github/workflows/ci.txt", "must end in .yml or .yaml"),
])
def test_a_workflow_must_land_where_github_reads(path, complaint):
    """A workflow written anywhere else is a file nobody runs, which is the whole failure this module is
    about - so it is refused at declaration time rather than produced and wondered at."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match=complaint):
        workflowgen.parse({"workflows": {"ci": {"path": path, "on": ["push"],
                                                "jobs": {"a": {"runs-on": "x",
                                                               "steps": [{"run": "y"}]}}}}})


def test_two_workflows_may_not_write_one_file():
    """Last-one-wins would be silent twice over: the loser is never produced, and the directory scan
    still finds the file and calls it managed."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="both declare"):
        workflowgen.parse(_section("""
        workflows:
          ci:
            path: .github/workflows/build.yml
            on: [push]
            jobs: { a: { runs-on: x, steps: [{ run: y }] } }
          build:
            on: [push]
            jobs: { a: { runs-on: x, steps: [{ run: y }] } }
        """))


def test_a_workflow_declaring_no_trigger_is_refused():
    """The kernel does not invent one. Whether a tag publishes is the product's statement, and si#40
    says plainly that the generator must not promise more than it knows."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="declares no `on:` trigger"):
        workflowgen.parse(_section("""
        workflows:
          ci:
            jobs: { a: { runs-on: x, steps: [{ run: y }] } }
        """))


def test_a_job_declaring_no_runner_is_refused():
    """The runner image is product data, and the kernel has no default worth imposing - `ubuntu-latest`
    would be simplon's choice made on somebody else's behalf, invisibly."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="declares no `runs-on:`"):
        workflowgen.parse(_section("""
        workflows:
          ci:
            on: [push]
            jobs: { a: { steps: [{ run: y }] } }
        """))


@pytest.mark.parametrize("steps, complaint", [
    ("[]", "must be a non-empty list"),
    ("[{ command: test all, uses: actions/checkout@v4 }]", "renders the whole step"),
    ("[{ note: nothing else }]", "neither `command:` nor a verbatim"),
    ("[{ name: a step with no body }]", "needs `uses:` or `run:`"),
    ("['a bare string']", "must be a mapping"),
])
def test_a_step_must_be_one_thing_or_the_other(steps, complaint):
    """`command:` IS the step. A step carrying both would have a meaning that depends on which key the
    renderer happens to read first, which is exactly the kind of thing nobody discovers by reading."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match=complaint):
        workflowgen.parse(_section(f"""
        workflows:
          ci:
            on: [push]
            jobs: {{ a: {{ runs-on: x, steps: {steps} }} }}
        """))


def test_a_non_boolean_checkout_is_refused():
    """`checkout: "no"` is a truthy string, and would silently keep the checkout it was written to
    remove."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="`checkout:` is true or false"):
        workflowgen.parse(_section("""
        workflows:
          ci:
            on: [push]
            jobs: { a: { runs-on: x, checkout: "no", steps: [{ run: y }] } }
        """))


# --- the declared decline ----------------------------------------------------------------------------


def test_a_workflow_may_declare_itself_hand_written():
    """si#40's other half, and an explained possibility rather than an emergency exit. Some files really
    are hand-work; the honest thing is to say so where the manifest can see it."""
    # Arrange / Act
    workflows = workflowgen.parse(_section("""
    workflows:
      release:
        handwritten: two shell scripts and a great deal of reasoning
    """))

    # Assert
    assert not workflows[0].generated
    assert workflows[0].path == ".github/workflows/release.yml"
    assert "reasoning" in workflows[0].handwritten


def test_a_decline_must_say_why():
    """A decline with no reason is indistinguishable from an oversight the day somebody reads it - which
    is the day it matters, because that is when they decide whether it still holds."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="must say why"):
        workflowgen.parse(_section("""
        workflows:
          release:
            handwritten: ""
        """))


def test_a_decline_may_not_also_declare_the_workflow():
    """Two readings of one entry, and no way to tell which the author meant."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="cannot also declare"):
        workflowgen.parse(_section("""
        workflows:
          release:
            handwritten: hand-written
            on: [push]
            jobs: { a: { runs-on: x, steps: [{ run: y }] } }
        """))


def test_rendering_a_hand_written_workflow_is_refused(manifest):
    """Nothing to render, said out loud. A caller that reached here would otherwise get an empty file
    written over somebody's work."""
    # Arrange
    workflows = workflowgen.parse(_section("""
    workflows:
      release:
        handwritten: hand-written on purpose
    """))

    # Act / Assert
    with pytest.raises(ValueError, match="declared hand-written"):
        workflowgen.render(workflows[0], manifest=manifest, product="sample", source="sample.yaml")


# --- write and check ---------------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path):
    """A product root with an empty workflows directory."""
    (tmp_path / workflowgen.DIRECTORY).mkdir(parents=True)
    return tmp_path


def _parse_minimal():
    return workflowgen.parse(_section(_MINIMAL))


def test_write_produces_a_file_and_says_it_changed(manifest, tree):
    # Arrange
    workflows = _parse_minimal()

    # Act
    changed = workflowgen.write(workflows, tree, manifest=manifest, product="sample",
                                source="sample.yaml")

    # Assert
    assert changed == (".github/workflows/ci.yml",)
    assert (tree / ".github/workflows/ci.yml").exists()


def test_writing_twice_changes_nothing_the_second_time(manifest, tree):
    """Deterministic output, asserted as the thing that matters: a generator whose bytes moved on every
    run would make `--check` red forever and would be turned off within a week."""
    # Arrange
    workflows = _parse_minimal()
    workflowgen.write(workflows, tree, manifest=manifest, product="sample", source="sample.yaml")

    # Act
    changed = workflowgen.write(workflows, tree, manifest=manifest, product="sample",
                                source="sample.yaml")

    # Assert
    assert changed == ()


def test_check_is_green_when_the_file_agrees(manifest, tree):
    # Arrange
    workflows = _parse_minimal()
    workflowgen.write(workflows, tree, manifest=manifest, product="sample", source="sample.yaml")

    # Act
    report = workflowgen.check(workflows, tree, manifest=manifest, product="sample",
                               source="sample.yaml")

    # Assert
    assert report.ok
    assert report.agreed == (".github/workflows/ci.yml",)
    assert report.drifted == ()


def test_a_hand_edited_workflow_makes_check_red_and_shows_the_difference(manifest, tree):
    """SEEN RED, which is acceptance 5 and the reason any of this is worth building.

    A workflow that has drifted from its manifest is invisible today: it runs, it goes green, and it
    tests whatever it happens to say. Here the property is broken on purpose and the check is watched
    failing - with a diff naming the line, not merely a verdict.
    """
    # Arrange
    workflows = _parse_minimal()
    workflowgen.write(workflows, tree, manifest=manifest, product="sample", source="sample.yaml")
    target = tree / ".github/workflows/ci.yml"
    target.write_text(target.read_text(encoding="utf-8").replace("./sample.sh test all", "pytest -q"),
                      encoding="utf-8")

    # Act
    report = workflowgen.check(workflows, tree, manifest=manifest, product="sample",
                               source="sample.yaml")

    # Assert
    assert not report.ok
    assert [d.path for d in report.drifted] == [".github/workflows/ci.yml"]
    assert "-      - run: pytest -q" in report.drifted[0].diff
    assert "+      - run: ./sample.sh test all" in report.drifted[0].diff


def test_a_workflow_that_was_never_generated_is_drift_and_not_an_error(manifest, tree):
    """A fresh checkout has to be TOLD what to run. Raising there would read as a broken gate rather
    than as the ordinary thing it is - the same call `simplon.taskgen.check` makes."""
    # Arrange
    workflows = _parse_minimal()

    # Act
    report = workflowgen.check(workflows, tree, manifest=manifest, product="sample",
                               source="sample.yaml")

    # Assert
    assert not report.ok
    assert report.drifted[0].path == ".github/workflows/ci.yml"


def test_a_file_nobody_declares_is_reported(manifest, tree):
    """THE check si#40 was raised for. agile-cockpit kept three assertions pointed at a `.gitlab-ci.yml`
    nothing had executed for months, and they passed the whole time - because from the directory, an
    unmanaged file looks exactly like a maintained one."""
    # Arrange
    workflows = _parse_minimal()
    workflowgen.write(workflows, tree, manifest=manifest, product="sample", source="sample.yaml")
    (tree / ".github/workflows/legacy.yml").write_text("name: legacy\n", encoding="utf-8")

    # Act
    report = workflowgen.check(workflows, tree, manifest=manifest, product="sample",
                               source="sample.yaml")

    # Assert
    assert report.unmanaged == (".github/workflows/legacy.yml",)
    assert not report.ok, "an unmanaged workflow must count against the check, or nothing changes"


def test_both_extensions_are_scanned(manifest, tree):
    """GitHub reads `.yaml` exactly as it reads `.yml`, so a scan that globbed one of them would leave
    the other unmanaged AND unreported - the same blind spot one file extension over that
    tests/test_version_source.py names."""
    # Arrange
    workflows = _parse_minimal()
    (tree / ".github/workflows/legacy.yaml").write_text("name: legacy\n", encoding="utf-8")

    # Act
    found = workflowgen.unmanaged(workflows, tree)

    # Assert
    assert found == (".github/workflows/legacy.yaml",)


def test_a_declared_hand_written_file_is_not_unmanaged(manifest, tree):
    """The one line that moves a file out of the reported bucket. That is what makes `handwritten:` an
    answer rather than a hole: it costs a sentence and it is visible in the manifest."""
    # Arrange
    (tree / ".github/workflows/release.yml").write_text("name: release\n", encoding="utf-8")
    workflows = workflowgen.parse(_section("""
    workflows:
      release:
        handwritten: two shell scripts and a great deal of reasoning
    """))

    # Act
    report = workflowgen.check(workflows, tree, manifest=manifest, product="sample",
                               source="sample.yaml")

    # Assert
    assert report.unmanaged == ()
    assert report.handwritten == (".github/workflows/release.yml",)
    assert report.ok


def test_a_hand_written_workflow_is_never_written_to(manifest, tree):
    """The manifest declared the file somebody's own; a generator that wrote to it anyway would have
    made the declaration a lie."""
    # Arrange
    target = tree / ".github/workflows/release.yml"
    target.write_text("name: release\n", encoding="utf-8")
    workflows = workflowgen.parse(_section("""
    workflows:
      release:
        handwritten: hand-written on purpose
    """))

    # Act
    changed = workflowgen.write(workflows, tree, manifest=manifest, product="sample",
                                source="sample.yaml")

    # Assert
    assert changed == ()
    assert target.read_text(encoding="utf-8") == "name: release\n"


def test_a_missing_workflows_directory_is_not_a_complaint(manifest, tmp_path):
    """A product may legitimately declare only hand-written workflows it has not written yet, and that
    is not this scan's complaint to make."""
    # Arrange / Act / Assert
    assert workflowgen.unmanaged(_parse_minimal(), tmp_path) == ()
