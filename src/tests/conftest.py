"""pytest bootstrap for the simplon unit tests: put the src-layout source tree on sys.path so
`from simplon import ...` resolves without an install (mirrors netctl's convention)."""
import sys
from pathlib import Path

import pytest

# The source tree now sits in src-layout one level above the tests. The wheel check
# (test_wheel.py) deliberately runs WITHOUT this path -- it is the only test that uses the
# package the way a consumer would.
# si#283: the unit suite lives beside the code it judges, under `src/`, so the product root is two
# levels up rather than one. `tests/` at the root still holds the acceptance level and the run's
# artefacts, which are not unit tests and do not move with them.
ROOT = Path(__file__).resolve().parents[2]

#: The suite's own fixture tree, anchored on THIS file rather than spelled out from the root (si#283).
#: Three chapter tests wrote `ROOT / "tests" / "fixtures"` and all three broke the moment the suite moved
#: - the same second source as the root anchor itself, one level down. A path relative to the suite
#: follows the suite.
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "src"))

from simplon.adapters import hostpath   # noqa: E402  (needs the sys.path line above)

def pytest_configure(config):
    """si#400 4d: a kernel read of a field the command's own kind does not have is an ERROR here, so every
    such read is found by the suite rather than shipped behind the one-release compatibility. Here and not
    in `pyproject.toml`, which has no pytest section: adding one would move pytest's rootdir/inifile for a
    single line. A test that means to read one (`test_command.py`) says so with `pytest.warns`."""
    config.addinivalue_line("filterwarnings", "error::simplon.domain.command.CompatWarning")


#: The environment variables that change what a PURE kernel function returns, cleared for every test.
AMBIENT = ("DELIVERY_HOST_ROOT", "DELIVERY_MOUNT_ROOT")


@pytest.fixture(autouse=True)
def _this_suite_runs_as_if_on_a_host(monkeypatch):
    """Pin the two facts the kernel reads about WHERE it is running, so a unit test says the same thing
    on both of si#201's routes.

    WHY IT EXISTS, measured rather than reasoned. `simplon test all` can now be run through the kernel's
    container image, and inside it both facts are true: `DELIVERY_HOST_ROOT` is exported by the launcher,
    and `/.dockerenv` is on the filesystem. `simplon.adapters.hostpath.translate` consults both, so every unit
    test of an argv builder that passes a `tmp_path` - which is not under the mount - met a refusal it
    was never written for. The container route came back 74 failed against 4 on the venv route, and
    every one of the 74 was that.

    The routes have to reach the same verdict; that is si#199's whole acceptance criterion. A suite whose
    result depends on where the interpreter happens to sit cannot give one. So the default is "on a
    host", stated once, and a test that is ABOUT the container branch sets these itself with monkeypatch
    - a later `setattr` on the same attribute simply wins.
    """
    for name in AMBIENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hostpath, "in_a_container", lambda: False)


@pytest.fixture(autouse=True)
def _a_run_has_the_host_the_cli_registers():
    """Every real run starts in `cli.main`, which registers the run host the kernel reads (si#391). The
    suite registers the same one, built by the same function, so a test sees what a run sees. A test that
    is ABOUT the unregistered case clears it with `runhost.register(None)`."""
    from simplon import cli
    from simplon.kernel import runhost
    runhost.register(cli.run_host())
    yield
    runhost.register(None)


class Recorder:
    """A Portainer that records the calls and answers by path.

    IN CONFTEST RATHER THAN IN A TEST MODULE, and the reason is a gate that went red. The second suite to
    need it imported it as `from tests.test_portainer import ...`, which resolves when pytest is invoked
    from the repository root and does NOT when it is invoked from inside `tests/` - and inside `tests/` is
    how `test suite` runs it, so its conftest applies. Copying the class into the second module would
    have been the second source this repository removes everywhere else. A shared fixture module is the
    place that is on the path either way.
    """

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.calls: list = []

    def __call__(self, _target, method: str, path: str, body: dict | None = None) -> object:
        self.calls.append((method, path, body))
        for prefix, answer in self.answers.items():
            if path.startswith(prefix):
                return answer
        return None


def docker_is_usable() -> bool:
    """Whether a real docker CLI on this machine can be run at all - the guard the e2e suites skip on.

    IN CONFTEST BECAUSE IT WAS IN THREE FILES, wordforword, and because the third state it now handles
    was found the expensive way. The line used to read:

        shutil.which("docker") is not None and run(["docker", "version"]).ok

    which knows two states and met a third on a CI runner (2026-09-16): `shutil.which` returned a path -
    it checks the permission bits and they were set - and the exec then failed with
    `PermissionError: [Errno 13] Permission denied: 'docker'`, the signature of a binary on a `noexec`
    mount. A guard whose job is to decide whether to SKIP crashed the whole module instead, and three
    copies of it crashed identically.

    "Present but unusable" is the same answer as "absent" to the question these suites ask.
    """
    import shutil

    from simplon.kernel.run import run

    if shutil.which("docker") is None:
        return False
    try:
        return run(["docker", "version"]).ok
    except OSError:
        return False


def lifecycle_name(argv: list[str], product: str) -> str:
    """The container name a `docker run` line carries, once it is shown to carry all of si#409's
    lifecycle: `--init`, a `--name`, and the `simplon.run=<product>` label (si#412).

    One helper for every site because the property is one property: a site that grew its own
    spelling of the check would be the place the next one drifts from it."""
    assert argv[:2] == ["docker", "run"], f"not a docker run line: {argv}"
    assert "--init" in argv, f"no --init: {argv}"
    labels = [argv[i + 1] for i, token in enumerate(argv[:-1]) if token == "--label"]
    assert f"simplon.run={product}" in labels, f"no simplon.run={product} label: {argv}"
    assert "--name" in argv, f"no --name: {argv}"
    return argv[argv.index("--name") + 1]


@pytest.fixture
def removals(monkeypatch):
    """Every `docker rm -f <name>` the si#409 unwind issues, recorded instead of run (si#412).

    The unwind runs through `simplon.adapters.docker.run`, so a site's own faked `run`/`stream` never
    sees it - which is what lets a test tell the site's container line from the cleanup after it."""
    from simplon.adapters import docker
    from simplon.kernel.run import Result
    seen: list[str] = []

    def fake(argv, **kwargs):
        if argv[:3] == ["docker", "rm", "-f"]:
            seen.append(argv[3])
        return Result(rc=0, out="", err="")
    monkeypatch.setattr(docker, "run", fake)
    return seen


def without_lifecycle(argv: list[str]) -> list[str]:
    """`argv` with si#409's lifecycle flags taken out, for a test that pins the REST of a line.

    The name is fresh per run by construction, so a test that compares a whole line would otherwise have
    to fake the name generator; this keeps such a test about what it was written for."""
    out: list[str] = []
    skip = False
    for i, token in enumerate(argv):
        if skip:
            skip = False
            continue
        if token == "--init":
            continue
        if token == "--name" or (token == "--label" and i + 1 < len(argv)
                                 and argv[i + 1].startswith("simplon.")):
            skip = True
            continue
        out.append(token)
    return out
