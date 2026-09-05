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
  2. the workflow runs THAT command - not a `mypy` line of its own, which would be a second route to the
     same verdict and the one nobody runs by hand;
  3. the requirements ask for the `[typecheck]` extra, so the checker is present in the venv the gate
     points at - without it the task reports a setup error rather than findings.

And the config file, because the task REFUSES to run without one: a gate whose rules are implicit cannot
be argued with when it goes red, and the first argument it loses is its own existence.
"""
import configparser
import tomllib

import yaml

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
REQUIREMENTS = ROOT / "orchestrator" / "requirements.txt"
CONFIG = ROOT / "mypy.ini"

#: The catalogue coordinate the kernel carries, and the command it becomes under this manifest's flat
#: form (the coordinate's second half is the command name, as with `build reference` / `build site`).
COORDINATE = "test:typecheck-python"
COMMAND = "./simplon.sh test typecheck-python"


def _config() -> configparser.ConfigParser:
    """mypy.ini PARSED, not grepped: this file carries as much prose as configuration, and a test that
    searched the raw text would be satisfied by a sentence describing a setting the file does not set."""
    parser = configparser.ConfigParser()
    parser.read_string(CONFIG.read_text(encoding="utf-8"))
    return parser


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _ci_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def test_theManifestPlacesTheKernelsOwnTypeGate() -> None:
    # arrange / act
    data = _manifest()

    # assert: the coordinate is imported AND instantiated - importing a namespace without using it is
    # caught by the loader, but declaring neither would just make the command quietly not exist.
    assert "test" in data["import"]["delivery"]
    assert COORDINATE in data["tasks"]
    assert data["tasks"][COORDINATE]["group"] == "test"


def test_theWorkflowRunsTheGateAsTheProductCommand_notAsAMypyLineOfItsOwn() -> None:
    runs = [step["run"] for step in _ci_steps() if "run" in step]

    # THE assertion of #8: the gate is in the pipeline at all ...
    assert COMMAND in runs
    # ... and it is the same command a developer runs. A bare `mypy` step would typecheck a tree nobody
    # can reproduce by hand, with roots and rules the workflow chose rather than mypy.ini.
    assert not [run for run in runs if run.split()[0] in {"mypy", "python", "pip"}]


def test_theWorkflowStillBuildsAndTestsAroundTheGate() -> None:
    # the gate is an addition, not a replacement: a run that typechecks and stops proves less than before
    runs = [step["run"] for step in _ci_steps() if "run" in step]

    assert "./simplon.sh test all" in runs
    assert "./simplon.sh build wheel" in runs


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


def test_noBlanketExcuseHidesAMissingStub() -> None:
    # `ignore_missing_imports = True` would absorb the day a dependency loses its types, which is the same
    # quiet #8 was made of. Every kernel dependency ships py.typed or has a stub in `simplon[typecheck]`.
    config = _config()

    assert not config.has_option("mypy", "ignore_missing_imports")
    assert config["mypy"].getboolean("warn_unused_ignores")
    # and no per-module excuse either - a `[mypy-<module>]` section is where one would live
    assert config.sections() == ["mypy"]
