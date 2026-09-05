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
  2. EVERY workflow that verifies this tree runs THAT command - not a `mypy` line of its own, which
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
So the rule is: any job that runs `test all` runs the gate. Asserted the way #3's `fetch-depth` rule is,
over `*.y*ml` in the workflows directory, because the failure is invisible in a diff - a new workflow
gets no gate, and no gate is the default.
"""
import configparser
import tomllib

import yaml

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIREMENTS = ROOT / "orchestrator" / "requirements.txt"
CONFIG = ROOT / "mypy.ini"

#: The catalogue coordinate the kernel carries, and the command it becomes under this manifest's flat
#: form (the coordinate's second half is the command name, as with `build reference` / `build site`).
COORDINATE = "test:typecheck-python"
GATE = "./simplon.sh test typecheck-python"

#: The command whose presence in a job means that job VERIFIES this tree - and therefore owes the gate.
#: A job that only builds (release.yml's `docs`) is not covered, deliberately: it makes no claim about
#: whether the code is correct, only about whether the site renders.
VERIFIES = "./simplon.sh test all"


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

    # assert: the coordinate is imported AND instantiated - importing a namespace without using it is
    # caught by the loader, but declaring neither would just make the command quietly not exist.
    assert "test" in data["import"]["delivery"]
    assert COORDINATE in data["tasks"]
    assert data["tasks"][COORDINATE]["group"] == "test"


def test_everyWorkflowThatVerifiesThisTreeAlsoRunsTheGate() -> None:
    # THE assertion of #8, and it is a rule rather than a list: whichever workflow claims to have checked
    # this tree - `ci` on every push, `release` on the path that reaches consumers, and any file written
    # after this one - owes the same verdict. A named-file version of this test passed while `release.yml`
    # published wheels nothing had typechecked.
    ungated = [f"{file}:{job}" for file, job, runs in _jobs()
               if VERIFIES in runs and GATE not in runs]

    assert ungated == [], (
        f"these jobs run the suite but not the type gate: {ungated}; a pipeline that is green because a "
        f"question is not asked is the whole of si#8")


def test_bothPipelinesAreCovered_soTheRuleIsNotVacuous() -> None:
    # A rule over a predicate goes green when NOTHING matches the predicate, which is how a rule quietly
    # stops holding anything. Name the two files that must be in it - if a rename makes this red, the
    # rename also has to say what now carries the release.
    gated = {file for file, _, runs in _jobs() if GATE in runs}

    assert {"ci.yml", "release.yml"} <= gated


def test_noWorkflowReachesForTheCheckerItself() -> None:
    # The gate must be the same command a developer runs. A bare `mypy` step would typecheck a tree nobody
    # can reproduce by hand, with roots and rules the workflow chose rather than mypy.ini.
    direct = [f"{file}:{job}: {run}" for file, job, runs in _jobs() for run in runs
              if run.split()[0] in {"mypy", "python", "pip", "pytest"}]

    assert direct == [], f"these steps bypass the product command: {direct}"


def test_theWorkflowsStillBuildAndTestAroundTheGate() -> None:
    # the gate is an addition, not a replacement: a run that typechecks and stops proves less than before
    everything = [run for _, _, runs in _jobs() for run in runs]

    assert VERIFIES in everything
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
    assert covered == ["src", "orchestrator/src/python/orchestrator"]


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
