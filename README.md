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

## Layout

`src/simplon/` is the kernel: the import package, the thing that gets
published. `orchestrator/` is Simplon's own product surface -- its manifest,
its commands -- because Simplon is a product of itself and builds and tests
itself with itself. The two layouts differ on purpose: the kernel uses the
conventional src-layout, while `orchestrator/` has exactly the shape
`simplon init` writes into every product. If that shape is awkward, Simplon
feels it first.

## Developing Simplon

Simplon builds and tests itself with itself:

    pip install -e .
    ./simplon.sh test all
    ./simplon.sh build wheel

## Releasing

Tag `vX.Y.Z`. The release workflow runs the tests, builds the wheel and
publishes to PyPI via Trusted Publishing. Releases are cut from tags only, so
every version points at a named commit.
