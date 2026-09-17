"""The runner table and what a job gets for naming a kind (si#267).

WHAT THIS FILE IS FOR. si#267 was raised after moving this repository's CI to a self-hosted runner took a
day, and every hour of it was spent rediscovering something another product in this family already knew -
all of it written down in a comment in netctl's manifest, learned there once and here a second time. The
repair is that a KIND of machine is the kernel's, carried once for everybody, and this measures the two
halves of that: the table answers for a kind, and a job that names one gets the consequences without
having to know them.

WHY THE TABLE ITSELF IS ASSERTED ABOUT. Every field in it was measured on a real machine on 2026-09-16,
and a table of guesses about other people's machines would be worse than no table - a product that
trusted it would be wrong in a way it had no way to check. So the two entries are pinned here: not
because the values are clever, but so that changing one is a decision somebody makes rather than a typo
nobody sees.

AAA throughout.
"""
import pytest
import yaml

from simplon import runners, workflowgen

from conftest import ROOT  # noqa: F401  (keeps the src tree on sys.path)


# --- the table --------------------------------------------------------------------------------------

def test_the_github_hosted_kind_is_what_every_product_had_before_the_table_existed():
    """`github-ubuntu` is the default, and it has to stay what the generator already emitted: changing it
    would rewrite files nobody asked to have rewritten."""
    # arrange + act
    runner = runners.TABLE[runners.DEFAULT]

    # assert
    assert runners.DEFAULT == "github-ubuntu"
    assert runner.labels == ("ubuntu-latest",)
    assert runner.setup_python is True
    assert runner.env == {}


def test_the_self_hosted_debian_kind_carries_the_three_facts_that_cost_a_day():
    """Measured on `ghr-8` on 2026-09-16, and each of the three is a thing somebody had to learn twice.

    `actions/setup-python` does not install Python - it unpacks prebuilt archives, and its manifest
    carries Ubuntu 22.04/24.04/26.04 and RHEL 9/10 and nothing else. Docker arrives through the bootstrap
    because a container job needs docker in order to START. And the machine has no label the kernel could
    guess, because a self-hosted runner's label belongs to whoever registered it.
    """
    # arrange + act
    runner = runners.TABLE["self-hosted-debian"]

    # assert
    assert runner.setup_python is False, "a kind that cannot be handed an interpreter said it could"
    assert runner.env == {runners.BOOTSTRAP: "1"}
    assert runner.labels == (), "the kernel invented a label for somebody else's machine"


def test_a_kind_the_kernel_does_not_carry_is_refused_naming_the_ones_it_does():
    """Diagnosis, and the message says where a new kind goes: into the kernel's table once for
    everybody, which is the whole principle this ticket is about."""
    # act
    with pytest.raises(ValueError) as refused:
        runners.resolve("self-hosted-freebsd", "`workflows.ci.jobs.build`")

    # assert
    said = str(refused.value)
    assert "not a runner kind this kernel knows" in said, said
    assert "github-ubuntu" in said and "self-hosted-debian" in said, said
    assert "once for everybody" in said, said


# --- naming the machine -----------------------------------------------------------------------------

def test_a_kind_with_labels_of_its_own_needs_nothing_else():
    # act
    runner, labels = runners.resolve("github-ubuntu", "`where`")

    # assert
    assert runner.kind == "github-ubuntu"
    assert labels == ("ubuntu-latest",)


def test_a_self_hosted_kind_without_a_label_is_refused_and_told_why_the_standard_three_are_not_one():
    """SEEN RED against the obvious wrong answer. `[self-hosted, Linux, X64]` looks like a label set and
    is a trap: it describes every self-hosted Linux machine an account will ever register, so the day a
    second one joins, the jobs are shared out with nothing saying so."""
    # act
    with pytest.raises(ValueError) as refused:
        runners.resolve("self-hosted-debian", "`workflows.ci.jobs.build`")

    # assert
    said = str(refused.value)
    assert "carries no label of its own" in said, said
    assert "[self-hosted, Linux, X64]` is not an answer" in said, said


def test_one_label_may_be_written_as_a_string_and_several_as_a_list():
    """One label is what most products have, and a list of one reads like a mistake."""
    # act
    _, one = runners.resolve({"kind": "self-hosted-debian", "labels": "ghr-8"}, "`where`")
    _, several = runners.resolve(
        {"kind": "self-hosted-debian", "labels": ["self-hosted", "windows", "vmware"]}, "`where`")

    # assert
    assert one == ("ghr-8",)
    assert several == ("self-hosted", "windows", "vmware")


def test_labels_override_a_kinds_own_rather_than_being_ignored():
    """A GitHub-hosted kind has labels, and a product that names its own means them - an override that
    was silently dropped would send the job to a machine the manifest did not ask for."""
    # act
    _, labels = runners.resolve({"kind": "github-ubuntu", "labels": "ubuntu-22.04"}, "`where`")

    # assert
    assert labels == ("ubuntu-22.04",)


@pytest.mark.parametrize("declared, complaint", [
    ({"kind": "github-ubuntu", "image": "x"}, "takes `kind:` and `labels:`"),
    ({"labels": "ghr-8"}, "names a kind of machine"),
    (7, "names a kind of machine"),
    ({"kind": "self-hosted-debian", "labels": ["ghr-8", 7]}, "is a list of runner LABELS"),
])
def test_a_declaration_that_is_not_a_kind_is_refused_naming_the_line(declared, complaint):
    # act
    with pytest.raises(ValueError) as refused:
        runners.resolve(declared, "`workflows.ci.jobs.build`")

    # assert
    said = str(refused.value)
    assert complaint in said, said
    assert "workflows.ci.jobs.build" in said, said


# --- what a job gets for naming one -------------------------------------------------------------------

def _section(body: str) -> dict:
    return yaml.safe_load(body)


_WITH_KIND = """
workflows:
  ci:
    on: [push]
    jobs:
      build:
        runner: { kind: self-hosted-debian, labels: ghr-8 }
        steps:
          - command: test all
"""


def test_naming_a_kind_gives_the_job_its_labels_and_its_environment():
    """The join, and the reason the table is worth having: the product said `self-hosted-debian` and did
    not have to know that such a machine reaches docker through the bootstrap."""
    # act
    workflow = workflowgen.parse(_section(_WITH_KIND))[0]
    job = workflow.jobs[0]

    # assert
    assert job.runs_on == "ghr-8"
    assert job.extras["env"] == {runners.BOOTSTRAP: "1"}
    assert job.python == "", "a kind that cannot be handed an interpreter got a setup-python step"


def test_the_reason_travels_into_the_generated_file_rather_than_staying_in_the_kernel():
    """A reader who finds `runs-on: ghr-8` and `DELIVERY_DOCKER_BOOTSTRAP: '1'` beside each other must not
    have to find this kernel to learn why they belong together - the same rule `CHECKOUT_NOTE` follows."""
    # act
    job = workflowgen.parse(_section(_WITH_KIND))[0].jobs[0]

    # assert
    assert "unpacks prebuilt archives" in job.note, job.note
    assert "container job would need docker in order to start" in job.note, job.note


def test_a_jobs_own_note_is_kept_and_the_kinds_line_goes_in_front_of_it():
    """The kind explains the machine; the product explains itself. Neither replaces the other."""
    # arrange
    text = _WITH_KIND.replace("        steps:", "        note: |\n          Ours.\n        steps:")

    # act
    job = workflowgen.parse(_section(text))[0].jobs[0]

    # assert
    assert job.note.rstrip().endswith("Ours."), job.note
    assert "unpacks prebuilt archives" in job.note, job.note


def test_a_python_pin_on_a_kind_that_cannot_honour_it_is_refused_with_the_measurement():
    """si#267's whole point in one refusal. This was a day's work to learn once: `actions/setup-python`
    never installs Python, so on a Debian runner a pin is not a guarantee, it is a wish - and a wish that
    reads like a guarantee is worse than no pin at all. The kernel says so now, at generation, instead of
    the runner saying `not found for this operating system` three minutes into a job."""
    # arrange
    text = _WITH_KIND.replace("        steps:", '        python: "3.12"\n        steps:')

    # act
    with pytest.raises(ValueError) as refused:
        workflowgen.parse(_section(text))

    # assert
    said = str(refused.value)
    assert "cannot be handed an interpreter" in said, said
    assert "reads as a guarantee and is a wish" in said, said


def test_a_python_pin_on_a_kind_that_can_honour_it_is_carried_as_always():
    """The assurance the refusal must not spend: a GitHub-hosted job still gets its interpreter step."""
    # arrange
    text = _WITH_KIND.replace("runner: { kind: self-hosted-debian, labels: ghr-8 }",
                              "runner: github-ubuntu").replace(
        "        steps:", '        python: "3.12"\n        steps:')

    # act
    job = workflowgen.parse(_section(text))[0].jobs[0]

    # assert
    assert job.python == "3.12"
    assert job.runs_on == "ubuntu-latest"


def test_declaring_both_a_kind_and_runs_on_is_refused_because_they_answer_one_question():
    # arrange
    text = _WITH_KIND.replace("        steps:", "        runs-on: ubuntu-latest\n        steps:")

    # act
    with pytest.raises(ValueError) as refused:
        workflowgen.parse(_section(text))

    # assert
    assert "declares both `runner:` and `runs-on:`" in str(refused.value)


def test_a_job_that_names_no_kind_is_exactly_what_it_was_before():
    """`runs-on:` is not deprecated and is not going to be. It is the whole of what a product needs when
    its machine has nothing to teach anybody, and a kernel that forced everyone through a table of kinds
    would refuse something they can legitimately say."""
    # arrange
    text = _WITH_KIND.replace("        runner: { kind: self-hosted-debian, labels: ghr-8 }",
                              "        runs-on: ubuntu-latest")

    # act
    job = workflowgen.parse(_section(text))[0].jobs[0]

    # assert
    assert job.runs_on == "ubuntu-latest"
    assert "env" not in job.extras
    assert job.note == ""


def test_a_job_that_sets_the_kinds_own_variable_differently_is_refused_rather_than_resolved():
    """Letting either win silently would make the generated file disagree with one of the two lines that
    produced it, and a reader of the workflow would have no way to tell which."""
    # arrange
    text = _WITH_KIND.replace(
        "        steps:", f'        env:\n          {runners.BOOTSTRAP}: "0"\n        steps:')

    # act
    with pytest.raises(ValueError) as refused:
        workflowgen.parse(_section(text))

    # assert
    said = str(refused.value)
    assert "already sets" in said and "say it once" in said, said


def test_a_job_may_still_set_variables_of_its_own_beside_the_kinds():
    # arrange
    text = _WITH_KIND.replace("        steps:", '        env:\n          OURS: "1"\n        steps:')

    # act
    job = workflowgen.parse(_section(text))[0].jobs[0]

    # assert
    assert job.extras["env"] == {runners.BOOTSTRAP: "1", "OURS": "1"}
