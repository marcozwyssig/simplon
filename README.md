# Simplon

Simplon is a delivery orchestrator for any software component that wants to
follow a CI/CD flow. It gives you a framework for the tasks that make up that
flow -- build, test, release, deploy, monitor -- and a way to bring in
additional tasks of your own.

A component declares its commands in one manifest. Simplon assembles the CLI
from it, runs the steps, and knows nothing about the component itself. It grew
up inside netctl and is now installed by several unrelated products -- an
example of who uses it, not a limit on who can. Who those are is measured and
written down in `simplon.surface`.

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

The product name is **optional** inside a git repository named after the
product, where the whole command is:

    simplon init

The name is read from the repository -- the `origin` remote's repository name,
or the working tree's root directory name when there is no remote yet -- and
the run prints which of the two it used. The argument still wins, because a
repository can be called `tooling` or hold two products at once. A name that
cannot be a product name is refused with the argument named as the fix rather
than mangled into one, and a directory with no `.git` is told what it is
missing. With the name read from the repository and no `--dir`, the skeleton
lands at the repository ROOT, since reading the name from the repository is
already the statement that the repository is the product.

The orchestrator block -- the directory holding `.venv`, `requirements.txt` and
`src/python/` -- lands in `deploy/provision/orchestrator` by default, which is
where every product that adopted Simplon put it by hand. A product that owns
its repo root moves it back up with `--orch-dir`:

    simplon init myctl --dir . --orch-dir orchestrator

The value has to be a plain relative path under the target; an absolute one, or
one containing `..`, is refused rather than scaffolded somewhere unexpected. It
moves the whole block together -- both launchers' `LAUNCH_ORCH_DIR` and every
path derived from it -- so nothing needs a hand-edit afterwards. Pass the same
flag on a later refresh: `--force` overwrites the launchers, so an edit made by
hand does not survive one.

It writes ten files:

    myctl.sh                                               the entry point (bash)
    myctl.cmd                                              the same entry point for cmd.exe
    myctl.yaml                                             the starter manifest
    .gitignore                                             what the kernel writes into your tree
    deploy/provision/orchestrator/requirements.txt         the host-venv deps, kernel pinned by version
    deploy/provision/orchestrator/src/python/orchestrator/
        __init__.py                                        the product package
        __main__.py                                        `python -m orchestrator` entry
        cli.py                                             the composition root
        paths.py                                           the product-context wiring
        environments.py                                    the environment provider

The Python package stays `orchestrator` wherever the block sits: it is an
identifier resolved on `PYTHONPATH`, which the launcher points at
`$LAUNCH_ORCH_DIR/src/python`.

## Layout

`src/simplon/` is the kernel: the import package, the thing that gets
published. `deploy/orchestrator/` is Simplon's own product surface -- its
manifest, its commands -- because Simplon is a product of itself and builds and
tests itself with itself. The two layouts differ on purpose: the kernel uses
the conventional src-layout, while the orchestrator block has exactly the shape
`simplon init` writes into every product. If that shape is awkward, Simplon
feels it first.

It sits under `deploy/` rather than at the repo root, and that is the same
`--orch-dir` any other product passes: Simplon scaffolded its own launchers
with it. The kernel's block is one level shallower than the default a product
gets, because it has no `provision/` layer to sit under; what the two share is
that the repo root is not the block's home, which is exactly what the default
now says. A kernel that offers a parameter and then keeps the one placement it
made configurable is not using what it ships.

## Why a gate is red

A gate can be red for several reasons, and they are not the same statement: the
**probe is red** (the suite ran and found something), the **setup failed** (the
suite never ran, because the preparation fell over first), or the run was
**killed** (a signal ended it, so it reported nothing at all). All are
`rc != 0`, and they stay that way -- an exit code is one bit and no reserved
value is invented for this. The distinction lives in what gets **written**:

* `test/reports/test-verdict.json` -- the stamp of the last invocation, always
  written, including for a run that never started. A run that leaves no record
  reads as the last green one, which is the defect this exists against.
* `environment.properties` in the run's allure results -- the same verdict
  inside the archive, where somebody handed only the HTML report still sees it.

`simplon.verdict` holds the five outcomes (`passed`, `failed`, `setup-failed`,
`not-run`, `killed`) and the reasoning; `simplon.tasks.testrun.assess_gate`
produces one per gate for a caller that wants it in hand rather than as an rc.

`killed` is read off the pytest child's wait status, which is negative when a
signal ended it, and the sentence names the **signal** rather than the number:
`killed (SIGTERM)`, not `rc -15`. The one number that does change is the gate's
own exit code, because `sys.exit(-15)` is taken modulo 256 and leaves a shell
reading `241` -- neither the signal nor anything reserved. A killed gate exits
`128+n` instead, which is what a shell already writes into `$?` for a child
killed by signal `n`.

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
    ./simplon.sh build wheel

CI runs the same gates, and it spells the first one differently: `test all` is
an aggregate over `test suite` (the pytest run), `test typecheck-python` (the
type gate, si#163) and `test release-notes` (si#156), and `ci.yml` names those
three leaves separately, with the notes check LAST rather than second. That is
not cosmetic. A GitHub job stops at its first failed step, so a release section
still to be written would otherwise go red in front of the type gate and the
wheel; locally nothing stops at a failure, so one command that runs all three is
the better shape. Typing `test all` here gets you the suite, the type gate and
the notes check in one go, and each leaf is still a command of its own when you
want just that one.

The type gate is the
kernel's own `test:typecheck-python`, placed on itself: what it covers and what
it excuses is stated in `mypy.ini`, and it pins the language level to the
`requires-python` floor rather than to whichever interpreter you have, so its
verdict is the same on your machine as in the pipeline.

## Releasing

```sh
./simplon.sh release tag v0.1.13
```

That is the release. The workflow then runs the tests, builds the wheel and
publishes to PyPI via Trusted Publishing, and rebuilds this project's website.
Releases are cut from tags only, so every version points at a named commit.

**The tag IS the version.** There is no number to edit first: `pyproject.toml`
declares `dynamic = ["version"]` and setuptools-scm derives it from the tag, so
`release tag v0.1.13` is the whole act of choosing 0.1.13. A tag is unique on
the remote, which is what makes the number unclaimable twice -- whoever pushes
it first has it, and the second person is told by `git push` rather than by a
reviewer. The command does not pre-empt that: it pushes, and lets the remote
answer.

Two things the command does that the two hand-typed git commands did not. It
pushes **that one tag** (`git push origin <tag>`, never `git push --tags`,
which offers every local tag including whatever someone left behind while
trying something out). And it refuses to tag a commit `main` does not carry --
loudly, naming the commit, the branch and `main`'s head -- because the workflow
publishes whatever the tag points at, so a tag on a feature branch would go to
PyPI without complaint. There is no flag to switch that off; `git tag && git
push origin <tag>` still works and is the deliberate way round it.

If the push is refused, the tag stays cut locally and the message says so.
Re-running the command pushes it again rather than reading "tag already exists"
as a release that already happened.

**Spell the tag the way the workflow reads it.** `release tag 0.1.14` -- no
`v` -- cuts the tag, pushes it, verifies origin has it and reports success,
because all four happened. What does not happen is a release: `tags: ["v*"]`
never sees it. Nothing fails and nothing warns, which is why the command
reports only that the tag is on origin and never claims what a workflow will
do with it. It cannot read your triggers, so it does not pretend to.

**A push to `main` publishes nothing.** Both the PyPI release and the website
hang off the `v*` tag. A merged documentation fix appears when the next release
is cut, and not before.

The full story, including what the guard deliberately does not check, is on the
site: <https://marcozwyssig.github.io/simplon/using/releasing/>.

Between tags the kernel calls itself `0.1.12.post1.dev4+g1234abc`: the release
it descends from, plus how far. `simplon init` pins the released part
(`simplon==0.1.12`) into a scaffolded product's `requirements.txt`, because a
pin has to name something PyPI actually has.
