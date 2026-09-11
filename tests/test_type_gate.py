"""Tests over simplon's OWN type gate (#8) - the join between mypy.ini, simplon.yaml and ci.yml.

WHY A TEST OVER A CI FILE AND A MANIFEST, and it is the whole point of #8.

#8 was raised as an environment difference: `mypy src` reported 36 findings on a developer's Python 3.14
while the CI, on 3.12, was green - so the findings were read as an artefact of the version gap and left
alone for months. Every part of that reasoning was sound except its premise. The CI was not typechecking
anything. `.github/workflows/ci.yml` ran `test all` and `build wheel`, and this repository - which SHIPS
`test:typecheck-python` and `simplon[typecheck]` for every other product to adopt - had never declared
the gate for itself. Its green was the green of a question nobody asked, and one of the 36 was a live bug
that skipped a test gate and reported success.

What must therefore be held is not "mypy passes" - `./simplon.sh test typecheck-python` is that, and it
runs in CI now. It is the three-part ADOPTION, because each part is silently removable and each removal
restores the exact condition #8 describes:

  1. the manifest declares the gate, so the command exists at all;
  2. EVERY workflow that verifies this tree REACHES that command - not a `mypy` line of its own, which
     would be a second route to the same verdict and the one nobody runs by hand;
  3. the requirements ask for the `[typecheck]` extra, so the checker is present in the venv the gate
     points at - without it the task reports a setup error rather than findings.

And the config file, because the task REFUSES to run without one: a gate whose rules are implicit cannot
be argued with when it goes red, and the first argument it loses is its own existence.

WHY PART 2 IS A RULE OVER THE DIRECTORY AND NOT A LIST OF FILES. The first version of this module looked
at `ci.yml` alone, and `release.yml` - the path that actually reaches consumers - ran `test all` and
`build wheel` without the gate. `ci.yml` triggers on `push`, tags included, so a tagged commit was in
fact checked; but by a PARALLEL workflow with no dependency on the release job. Restrict that trigger and
the release path silently loses the check. That is si#8 committed a second time, one level up, and an
enumeration of filenames is exactly the shape that lets it happen again in a file nobody has written yet.
So the rule is: any job that runs the suite runs the gate. Asserted the way #3's `fetch-depth` rule is,
over `*.y*ml` in the workflows directory, because the failure is invisible in a diff - a new workflow
gets no gate, and no gate is the default.

AND THE RULE NEEDS A SECOND GUARD, which si#156 supplied by breaking it. "Any job that runs the suite"
was written as the single string `./simplon.sh test all`; that ticket renamed the pytest leaf to `test
suite` and `ci.yml` with it, and every assertion here stayed green while the rule matched no job in that
file at all. The vacuity test was asking whether both pipelines carry the GATE - which a rename does not
touch - rather than whether both still match the PREDICATE. Both questions are asked now.

WHAT si#163 CHANGED, AND WHAT THE RULE STILL PROTECTS. `test all` is an aggregate that plans the type
gate since that ticket, so a job spelling `./simplon.sh test all` runs the gate whether or not it also
names it. That takes half of what this rule used to protect away: for THAT spelling, "runs the suite" and
"runs the gate" are no longer two things a job can get wrong separately.

The rule is kept and narrowed rather than deleted, because the other half is not only alive but is the
shape `ci.yml` deliberately has. si#156's reason stands: a GitHub job stops at its first failed step, so
`ci.yml` names the LEAVES - `test suite`, then the gate, then the wheel, then the prose guard - and a job
built that way carries no aggregate to drag the gate along. Delete its `test typecheck-python` step and
the tree is unchecked again, with nothing else in the repository saying so. That is a live failure, it is
one line wide, and it was seen red before this sentence was written.

So the question the rule asks moved from "does the job NAME the gate" to "does the job REACH it", and the
answer is derived from the manifest rather than matched against a table of spellings. A hand-written
"these commands carry the gate" list would be si#156's defect one level up: it would keep saying `test
all` carries the gate on the day somebody edits that `depends_on:`, and `release.yml` - which reaches the
suite by the aggregate and, since si#163, names no gate step of its own - would be covered by a claim and
by nothing else.

The claim itself is held separately, by `test_theLocalGateAggregateReachesTheGate` below, and that is not
redundancy. Drop the dependency today and the rule does catch it, because `release.yml` happens to have
no other route to the gate - but that is a property of which workflows exist this week, not of the
aggregate, and it would stop being true the moment a job named both. The separate assertion holds the
claim itself, does not depend on any workflow, and names the CAUSE where the rule can only report the
symptom.
"""
import configparser
import functools
import tomllib

import yaml

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIREMENTS = ROOT / "deploy" / "orchestrator" / "requirements.txt"
CONFIG = ROOT / "mypy.ini"

#: The catalogue coordinate the kernel carries, and the command that instantiates it in this manifest's
#: `test` group (the coordinate's second half is the command name, as with `build reference` / `build
#: site`). The coordinate is the ONE constant this module still types: si#163 replaced the literal step
#: spelling `./simplon.sh test typecheck-python` with `_gate_command()`, which reads the command name out
#: of the placement, so a rename shows up as a failing placement rather than as a rule matching nothing.
COORDINATE = "test:typecheck-python"

#: The commands whose presence in a job means that job VERIFIES this tree - and therefore owes the gate.
#: A job that only builds (release.yml's `docs`) is not covered, deliberately: it makes no claim about
#: whether the code is correct, only about whether the site renders.
#:
#: TWO SPELLINGS since si#156, and the second one is why this stopped being a single string. That ticket
#: renamed the pytest leaf to `test suite` and gave the name `test all` to an aggregate over it and the
#: release-notes guard; `ci.yml` now says `test suite` and `release.yml` still says `test all`. Measured
#: on the branch that made the change: with only the old string here, every assertion below stayed GREEN
#: while the rule silently stopped covering `ci.yml` at all - a rule over a predicate goes green when
#: nothing matches the predicate, which is the failure mode the vacuity test underneath was written for
#: and which it did not catch, because it asked about the GATE rather than about the predicate.
#:
#: A set rather than a derivation (expanding each command through the manifest plan) on purpose: what is
#: being held is that a job SAYS it verified this tree, and both spellings are things a workflow says.
#: This is the PREDICATE side and it stays a set for that reason; the GATE side is derived, see `_plan`.
VERIFIES = ("./simplon.sh test all", "./simplon.sh test suite")


@functools.cache
def _loaded() -> "manifest_mod.Manifest":
    """This repository's own manifest, loaded the way the CLI loads it - with the catalogue, so a command
    that merely names a coordinate is a command with a body."""
    return manifest_mod.load(MANIFEST.read_text(encoding="utf-8"), catalogue=catalogue_mod.load())


def _plan(step: str) -> tuple[str, ...]:
    """The leaf commands a `./simplon.sh <group> <command>` step really runs, expanded through the
    manifest, or `()` for anything that is not one of those.

    WHY THIS IS DERIVED AND NOT A TABLE (si#163). A workflow step is one string and can be several
    verdicts: `./simplon.sh test all` plans three commands since si#163 and two before it. Asking whether
    a job runs the gate by searching its `run:` lines for the gate's own spelling answers a question about
    TEXT, and the fact it needs is a fact about the plan. A table mapping the one to the other would be
    exactly the single string si#156 found here, one level up - correct on the day it is typed and silent
    on the day the `depends_on:` under it changes.

    Anything with a different shape - a multi-line `run: |` script, an `npm` line, a command with
    arguments - plans nothing as far as this module is concerned. That is deliberate: this answers "which
    of the product's own commands did this step invoke", and a step that is not one of them invokes none.
    A command that took an argument would be a real gap, and there is none in either workflow today; the
    generator writes `./simplon.sh <group> <command>` and si#40's `with:`-pinning is what keeps it that
    way.

    A step that LOOKS like one and names a command the manifest does not carry is a third case, and it
    fails loudly rather than resolving to `()`. Swallowing it would be the quiet defect: a typo would drop
    the step out of every population below, the job would match no spelling in VERIFIES either, and the
    whole file would go green over a workflow that runs nothing. `ci.yml` cannot reach that state -
    `support workflows --check` regenerates it from this manifest - but `release.yml` is hand-written, so
    the message is written out here rather than left as a traceback into the loader.
    """
    parts = step.split()
    if len(parts) != 3 or parts[0] != "./simplon.sh":
        return ()
    _, group, command = parts
    try:
        return _loaded().plan_for(command, group=group)
    except ValueError as exc:
        raise AssertionError(
            f"a workflow step runs `{step}`, and simplon.yaml carries no such command: {exc}. Either the "
            f"command was renamed and the workflow was not, or the workflow has a typo - a step that "
            f"names nothing runs nothing, and no gate in this file can see it") from exc


def _reached(runs: list[str]) -> set[str]:
    """Every leaf command a job really runs: the union of its steps' plans."""
    return {leaf for step in runs for leaf in _plan(step)}


def _gate_command() -> str:
    """The name of the command in the `test` group that instantiates the gate's coordinate.

    Derived rather than typed, the way tests/test_releases_page.py derives the notes guard's: renaming
    `typecheck-python` then keeps every assertion below honest instead of turning them into a search for
    a string that has stopped meaning anything. `test_theManifestPlacesTheKernelsOwnTypeGate` is what
    holds the name to the coordinate; everything here works in names because that is what a plan carries.

    It asserts only that the placement is UNIQUE, not what the command is called. The name is pinned once,
    by the test named above, and pinning it a second time here would turn a rename into two failures
    saying the same thing - and would make this helper's own promise false.
    """
    commands = _manifest()["groups"]["test"]["commands"]
    placed = [name for name, spec in commands.items() if spec.get("task") == COORDINATE]
    assert len(placed) == 1, (
        f"simplon's `test` group no longer instantiates {COORDINATE} exactly once - found {placed}; si#8 "
        f"is about this manifest being where the kernel's own gate is placed")
    return placed[0]


def _config() -> configparser.ConfigParser:
    """mypy.ini PARSED, not grepped: this file carries as much prose as configuration, and a test that
    searched the raw text would be satisfied by a sentence describing a setting the file does not set."""
    parser = configparser.ConfigParser()
    parser.read_string(CONFIG.read_text(encoding="utf-8"))
    return parser


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _jobs() -> list[tuple[str, str, list[str]]]:
    """Every job in every workflow, as (file, job name, the `run:` lines it spells out).

    THE LIMIT, stated rather than left to be discovered, and it is the same one #3's `fetch-depth` rule
    carries: this reads the steps a workflow spells out itself. A step inside a composite action, or
    inside a reusable workflow called with a job-level `uses:`, is invisible here - there is no file in
    this repository to read it out of. Neither exists today.

    `*.y*ml` because GitHub reads `.yaml` exactly as it reads `.yml`, and a test that globbed one of them
    would be the same blind spot one file extension over.
    """
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert files, WORKFLOWS
    out = []
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in doc.get("jobs", {}).items():
            out.append((path.name, name, [s["run"] for s in job.get("steps", []) if "run" in s]))
    return out


def test_theManifestPlacesTheKernelsOwnTypeGate() -> None:
    # arrange / act
    data = _manifest()

    # assert: a command in the `test` group instantiates the coordinate. Reading the manifest rather than
    # the loaded model is deliberate - what si#8 is about is the DECLARATION being present in this file,
    # and a command that merely resolves would still be one somebody could delete here without noticing.
    commands = data["groups"]["test"]["commands"]
    assert commands["typecheck-python"]["task"] == COORDINATE


def test_everyWorkflowThatVerifiesThisTreeAlsoRunsTheGate() -> None:
    # THE assertion of #8, and it is a rule rather than a list: whichever workflow claims to have checked
    # this tree - `ci` on every push, `release` on the path that reaches consumers, and any file written
    # after this one - owes the same verdict. A named-file version of this test passed while `release.yml`
    # published wheels nothing had typechecked.
    #
    # REACHES, not NAMES, since si#163: `test all` plans the gate now, so a job that spells only the
    # aggregate is gated and a job that spells the LEAF `test suite` is not. Both sides are read out of
    # the manifest, so the question asked is the one that decides whether mypy ran.
    gate = _gate_command()

    ungated = [f"{file}:{job}" for file, job, runs in _jobs()
               if any(cmd in runs for cmd in VERIFIES) and gate not in _reached(runs)]

    assert ungated == [], (
        f"these jobs run the suite but not the type gate: {ungated}; naming `test suite` reaches the "
        f"pytest leaf ONLY - add `./simplon.sh test {gate}` as its own step, or run the `test all` "
        f"aggregate that plans it. A pipeline that is green because a question is not asked is the whole "
        f"of si#8")


def test_bothPipelinesAreCovered_soTheRuleIsNotVacuous() -> None:
    # A rule over a predicate goes green when NOTHING matches the predicate, which is how a rule quietly
    # stops holding anything. Name the two files that must be in it - if a rename makes this red, the
    # rename also has to say what now carries the release.
    #
    # Asked through the plan too (si#163), for one reason: the literal version of this test forbade a
    # workflow from reaching the gate the way the manifest now lets it, by running `test all` alone. It
    # would have gone red on a shape that is correct, which is worse than a rule that cannot fail - it is
    # a rule that refuses the right answer.
    gate = _gate_command()

    gated = {file for file, _, runs in _jobs() if gate in _reached(runs)}

    assert {"ci.yml", "release.yml"} <= gated


def test_theLocalGateAggregateReachesTheGate() -> None:
    """si#163: `./simplon.sh test all` must RUN the type gate, not merely be a command that could.

    THE HALF THE RULE ABOVE ONLY HAPPENS TO HOLD, and the reason this is a separate test rather than one
    more line in it. That rule reads the plan to decide whether a job reaches the gate, so dropping
    `typecheck-python` from this aggregate turns it red TODAY - only because no workflow has a second
    route to the gate. That is a fact about `ci.yml` and `release.yml` this week, not about the aggregate,
    and the day a job names both the rule goes quiet again. This asks the question directly, the way
    `test_bothPipelinesMatchThePredicateItself_soTheRuleAboveHasSomethingToRuleOn` does for the
    predicate side, and it is also the ONLY
    assertion behind the local gate's own promise: `test all` is what a developer runs, and no workflow
    file has anything to say about that.

    WHAT THIS DOES AND DOES NOT PROVE, in the same words tests/test_releases_page.py uses for si#156's
    half: this asserts the PLAN, and a plan is not a verdict. What holds the verdict is the run - break an
    annotation, type `./simplon.sh test all`, watch the type row go red - and no unit test can stand in
    for that. This is the regression guard beside it.
    """
    # arrange / act
    plan = _loaded().plan_for("all", group="test")

    # assert
    assert _gate_command() in plan, (
        f"`test all` plans {list(plan)}, which does not include '{_gate_command()}': the command named "
        f"`all`, whose help says every test, has stopped running the type gate (si#163)")


def test_bothPipelinesMatchThePredicateItself_soTheRuleAboveHasSomethingToRuleOn() -> None:
    # The half the test above does NOT hold, and si#156 is the ticket that found it out: it asks whether
    # the two files carry the GATE, which stays true no matter what happens to VERIFIES. Rename the
    # command a job runs the suite with and the rule stops matching that job - green, covering nothing,
    # and the next workflow written against the new name inherits no gate at all. This asks the other
    # question: each pipeline must still SAY it verified this tree, in a spelling VERIFIES knows.
    verifying = {file for file, _, runs in _jobs() if any(cmd in runs for cmd in VERIFIES)}

    assert {"ci.yml", "release.yml"} <= verifying, (
        f"these pipelines match no VERIFIES spelling: {{'ci.yml', 'release.yml'}} - {verifying}; the rule "
        f"above is now vacuous for them, so add the new spelling to VERIFIES rather than leaving it")


def test_noWorkflowReachesForTheCheckerItself() -> None:
    # The gate must be the same command a developer runs. A bare `mypy` step would typecheck a tree nobody
    # can reproduce by hand, with roots and rules the workflow chose rather than mypy.ini.
    direct = [f"{file}:{job}: {run}" for file, job, runs in _jobs() for run in runs
              if run.split()[0] in {"mypy", "python", "pip", "pytest"}]

    assert direct == [], f"these steps bypass the product command: {direct}"


def test_theWorkflowsStillBuildAndTestAroundTheGate() -> None:
    # the gate is an addition, not a replacement: a run that typechecks and stops proves less than before
    everything = [run for _, _, runs in _jobs() for run in runs]

    assert any(cmd in everything for cmd in VERIFIES)
    assert "./simplon.sh build wheel" in everything


def test_theHostVenvAsksForTheCheckerTheGateNeeds() -> None:
    # The gate runs mypy from the host venv and reports a SETUP error, not findings, when it is absent -
    # which is a green-looking red nobody would chase. The extra is what stops that happening.
    text = REQUIREMENTS.read_text(encoding="utf-8")

    assert "-e .[typecheck]" in text


def test_theConfigurationExistsAndCoversTheTreesThisRepositoryShips() -> None:
    # The task refuses to run without this file, so its absence would break the build rather than hide -
    # but its CONTENTS are what decide whether the gate means anything.
    config = _config()

    assert config.has_section("mypy")
    covered = [root.strip() for root in config["mypy"]["files"].split(",")]
    assert covered == ["src", "deploy/orchestrator/src/python/orchestrator"]


def test_theGateChecksTheFloorTheWheelPromises_notWhicheverPythonIsAtHand() -> None:
    # The direct answer to #8's hypothesis. `requires-python` is a promise to consumers, and the language
    # level the checker applies is a SETTING here - not the interpreter mypy happens to run on. Pinning it
    # is what makes the gate's verdict the same on a maintainer's 3.14 and on the CI's 3.12.
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    floor = pyproject["project"]["requires-python"].lstrip(">=")
    assert _config()["mypy"]["python_version"] == floor


def test_theGateLooksInsideUnannotatedBodies_theOmissionThatIsNotAPath() -> None:
    # mypy skips the body of a function with no annotations by default, so a gate without this setting
    # reports `Success` over code it never read - and unlike the path exclusions, nothing in the config
    # would say so. Measured before adopting it: it adds zero findings to this tree, so it constrains only
    # what gets written next. (`disallow_untyped_defs` is a separate decision, costs 18, deliberately not
    # taken - this test would be the wrong place to smuggle it in, so it asserts only the one setting.)
    assert _config()["mypy"].getboolean("check_untyped_defs")


def test_noBlanketExcuseHidesAMissingStub() -> None:
    # `ignore_missing_imports = True` would absorb the day a dependency loses its types, which is the same
    # quiet #8 was made of. Every kernel dependency ships py.typed or has a stub in `simplon[typecheck]`.
    config = _config()

    assert not config.has_option("mypy", "ignore_missing_imports")
    assert config["mypy"].getboolean("warn_unused_ignores")
    # and no per-module excuse either - a `[mypy-<module>]` section is where one would live
    assert config.sections() == ["mypy"]
