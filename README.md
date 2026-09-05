# Simplon

Simplon is a delivery orchestrator for any software component that wants to
follow a CI/CD flow. It gives you a framework for the tasks that make up that
flow -- build, test, release, deploy, monitor -- and a way to bring in
additional tasks of your own.

A component declares its commands in one manifest. Simplon assembles the CLI
from it, runs the steps, and knows nothing about the component itself. The
`*ctl` product family (netctl, infractl) is where it grew up and is its first
user -- an example of who uses it, not a limit on who can.

## Using it

    pip install simplon

The runtime dependencies are ranges, not exact pins: a product's own
`requirements.txt` is where exact versions belong, and a published package's
pins become its consumers' pins.

One extra: `pip install simplon[typecheck]` adds mypy, which the
`test:typecheck-python` gate runs. A product that does not declare that
command does not need it.

## Starting a product

The very first launcher has a chicken-and-egg: a fresh product has no venv,
so it has no Simplon to write its launcher with. Break it once by hand:

    pipx run simplon init myctl --dir .

or `pip install simplon` into any venv and run `simplon init myctl --dir .` in
the product repo. Without `--dir` the skeleton lands in a new `./myctl/`
subdirectory instead of at the repo root, so pass `--dir .` whenever the repo
is already the product. After that the generated `myctl.sh` carries itself, and
a later `simplon init` refreshes it.

The orchestrator block -- the directory holding `.venv`, `requirements.txt` and
`src/python/` -- lands in `orchestrator/` by default. A product whose own
structure reserves the repo root passes `--orch-dir`:

    simplon init myctl --dir . --orch-dir deploy/provision/orchestrator

The value has to be a plain relative path under the target; an absolute one, or
one containing `..`, is refused rather than scaffolded somewhere unexpected. It
moves the whole block together -- both launchers' `LAUNCH_ORCH_DIR` and every
path derived from it -- so nothing needs a hand-edit afterwards. Pass the same
flag on a later refresh: `--force` overwrites the launchers, so an edit made by
hand does not survive one.

The Python package stays `orchestrator` wherever the block sits: it is an
identifier resolved on `PYTHONPATH`, which the launcher points at
`$LAUNCH_ORCH_DIR/src/python`.

## Layout

`src/simplon/` is the kernel: the import package, the thing that gets
published. `orchestrator/` is Simplon's own product surface -- its manifest,
its commands -- because Simplon is a product of itself and builds and tests
itself with itself. The two layouts differ on purpose: the kernel uses the
conventional src-layout, while `orchestrator/` has exactly the shape
`simplon init` writes into every product. If that shape is awkward, Simplon
feels it first.

## Why a gate is red

A gate can be red for two reasons, and they are not the same statement: the
**probe is red** (the suite ran and found something) or the **setup failed**
(the suite never ran, because the preparation fell over first). Both are
`rc != 0`, and they stay that way -- an exit code is one bit and no reserved
value is invented for this. The distinction lives in what gets **written**:

* `test/reports/test-verdict.json` -- the stamp of the last invocation, always
  written, including for a run that never started. A run that leaves no record
  reads as the last green one, which is the defect this exists against.
* `environment.properties` in the run's allure results -- the same verdict
  inside the archive, where somebody handed only the HTML report still sees it.

`simplon.verdict` holds the four outcomes (`passed`, `failed`, `setup-failed`,
`not-run`) and the reasoning; `simplon.tasks.testrun.assess_gate` produces one
per gate for a caller that wants it in hand rather than as an rc.

A product whose lab is prepared through the gate's `precondition:` or
`preamble:` hooks gets this for free. A product that builds its lab **inside a
pytest session fixture**, where the kernel cannot see it, says so by writing the
failed stage into the file named by `$SIMPLON_SETUP_FAILED`:

```python
def pytest_sessionfinish(session, exitstatus):
    marker = os.environ.get("SIMPLON_SETUP_FAILED")
    if lab_never_came_up and marker:
        with open(marker, "w") as fh:
            fh.write("provision\n")
```

`.get`, not `[...]`: the same suite has to run under a bare `pytest` too -- from
an IDE, or in a checkout without the kernel -- and a `KeyError` raised out of
`pytest_sessionfinish` would turn "the lab did not come up" into an internal
error about a missing variable.

Nothing is imported from the kernel to do that, on purpose: it is a path in the
environment and a file with a stage name in it, so a suite in its own venv needs
no version of anything to stay in step with.

A run carrying passthrough args (`test system -k something`) is exploratory and
therefore partial. Its results are quarantined into their own dir, its archive
gets its own prefix, and its verdict gets its own stamp
(`test-verdict-filtered.json`) -- a one-test hunt can never overwrite the record
of the last full gate, in either direction.

## Developing Simplon

Simplon builds and tests itself with itself:

    pip install -e ".[typecheck]"
    ./simplon.sh test all
    ./simplon.sh test typecheck-python
    ./simplon.sh build wheel

Those three are exactly what CI runs, in that order. The type gate is the
kernel's own `test:typecheck-python`, placed on itself: what it covers and what
it excuses is stated in `mypy.ini`, and it pins the language level to the
`requires-python` floor rather than to whichever interpreter you have, so its
verdict is the same on your machine as in the pipeline.

## Releasing

Tag `vX.Y.Z`. The release workflow runs the tests, builds the wheel and
publishes to PyPI via Trusted Publishing. Releases are cut from tags only, so
every version points at a named commit.

**The tag IS the version.** There is no number to edit first: `pyproject.toml`
declares `dynamic = ["version"]` and setuptools-scm derives it from the tag, so
`git tag v0.1.13` is the whole act of choosing 0.1.13. A tag is unique on the
remote, which is what makes the number unclaimable twice -- whoever pushes it
first has it, and the second person is told by `git push` rather than by a
reviewer.

Between tags the kernel calls itself `0.1.12.post1.dev4+g1234abc`: the release
it descends from, plus how far. `simplon init` pins the released part
(`simplon==0.1.12`) into a scaffolded product's `requirements.txt`, because a
pin has to name something PyPI actually has.
