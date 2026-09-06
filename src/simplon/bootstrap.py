"""simplon.bootstrap - scaffold a fresh product onto the delivery orchestrator (netctl#651 strand 4).

A brand-new product has no shim, no manifest and no product package yet, so it cannot reach the kernel
through its own CLI. This module is the ONE kernel entry that runs WITHOUT a product context: it writes a
minimal, valid product skeleton and prints the next steps, after which the new product configures only its
`<product>.yaml`.

Run it standalone (with `simplon` installed, e.g. `pip install simplon`)::

    simplon init <product> [--dir DIR] [--orch-dir DIR] [--force]

`python -m simplon.bootstrap <product> ...` keeps working for anyone who has it in muscle memory, but
the console script is the entry point the README documents.

It renders, mirroring the shape netctl's own `netctl.yaml` + `netctl.sh` use but stripped to the bones:

    <product>.sh                                     the entry point (bash): declares the four LAUNCH_*
                                                     params, provisions a host venv, execs the CLI
    <product>.cmd                                    the same entry point for Windows (cmd.exe)
    <product>.yaml                                   the starter manifest (tasks/groups tree/
                                                     environments the Pydantic loader accepts)
    <orch-dir>/requirements.txt                      the host-venv deps: the kernel pinned by version
                                                     (`simplon==...`) + product-only pins
    <orch-dir>/src/python/orchestrator/
        __init__.py                                  the product package
        __main__.py                                  `python -m orchestrator` entry
        cli.py                                       composition root: root Typer app + assemble
                                                     (step_context binds the `all` aggregate) + main
        paths.py                                     the ProductContext wiring (simplon.context); repo root
                                                     found by walking up to the manifest marker, not a depth
        environments.py                              the EnvironmentProvider (its three product values)

`<orch-dir>` is `orchestrator` unless `--orch-dir` says otherwise (#4). It is the block LAUNCH_ORCH_DIR
points at, and both shims derive their venv, their requirements file and PYTHONPATH from that one variable,
so the whole block moves together. The package name stays `orchestrator` under any layout - it is an
identifier on PYTHONPATH, not a location.

The generated manifest VALIDATES through `simplon.orchestrator.manifest.load`; the generated `paths.py`
registers a `ProductContext` exactly as netctl's adapter does, so the new product has a working,
manifest-driven CLI right away (`./<product>.sh help`) - the launcher provisions its own venv and installs
the pinned kernel from PyPI on first run; nothing needs vendoring.

Design / scope (best-effort MINIMAL slice; netctl#651 strand 4 is under-specified on purpose):

    IN this slice
      - a starter manifest in the COMMAND TREE form that loads clean and shows ALL FIVE phases of the
        CI/CD loop plus `support` (si#33), each holding at least one command: an agnostic group that
        collapses to one flat command (`build`), two env-first groups (`deploy`, `monitor`), two commands
        that place a catalogue coordinate rather than a body of their own (`release tag`,
        `support install`), a WORKING aggregate (`all` is an impl-less `depends_on: [build, up]` command
        the kernel binds via assemble(step_context=...), so `<product> all` runs build->up, not a dead
        placeholder) and the env matrix;
      - the full product-adapter wiring (paths/environments/cli/__main__) so the CLI actually assembles;
      - the two launchers (`.sh` + `.cmd`) + requirements (the kernel pinned by version), so
        `./<product>.sh help` runs on a fresh clone with nothing to vendor;
      - PURE render (text only, no I/O, no yaml/pydantic import) split from the file-writing, so the manifest
        can be validated and the file set asserted in unit tests;
      - clobber-safety: refuses to overwrite an existing file unless `--force`.

    DEFERRED to a fuller scaffolder (documented, deliberately NOT built here)
      - a `bootstrap`/`init` subcommand woven into an assembled product CLI (the `simplon` console
        script covers the pre-product case, which is the only one that cannot go through a product);
      - `git init` automation (side-effecting VCS state); a one-command scaffold + verify flow is left
        to a repo-root wrapper script, deferred here;
      - schema-per-section docs, includes/anchors and a `--profile` menu (network-lab vs plain-service) that
        seeds a richer manifest;
      - product-name -> package-name derivation (the package is the fixed identifier `orchestrator`, as in
        netctl, so any product slug incl. hyphens works without sanitisation);
      - a post-scaffold `verify` that boots the generated CLI headless and asserts the surface.
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib.resources import files
from pathlib import Path

import simplon

# A product name is a lowercase slug: it becomes the shim/manifest filename, the manifest `product:` label,
# the LAUNCH_PRODUCT diagnostic token and the `<PRODUCT>_ENV` variable stem. The package itself is the FIXED
# identifier `orchestrator` (as in netctl), so a hyphenated slug never has to be a Python identifier.
_PRODUCT_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# The generated product package is always `orchestrator` (LAUNCH_MODULE), mirroring netctl. The BLOCK DIR
# below it is LAUNCH_ORCH_DIR: it holds `.venv`, `requirements.txt` and `src/python/`, and it is the part
# that MOVES (#4). Two of the three consumers keep it at `deploy/provision/orchestrator` because their own
# structure rule reserves the repo root, so the location is a parameter with `orchestrator` as the default,
# not a decree. The package NAME does not move with it: it is an identifier resolved on PYTHONPATH, which
# the shim points at `$LAUNCH_ORCH_DIR/src/python` wherever that is. `paths.py` finds the repo root by
# walking up to the manifest marker (netctl#737), so a deeper block dir needs no hand-edit either.
_ORCH_DIR = "orchestrator"

# The Windows drive prefix (`C:`, `c:/...`): absolute, and neither the leading-slash nor the `..` check
# would catch it on its own.
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def pkg_dir_for(orch_dir: str) -> str:
    """The generated package's directory, relative to the scaffold target, for a given block dir."""
    return f"{orch_dir}/src/python/orchestrator"


def validate_relative_dir(value: str, what: str, hint: str, *, inside: str = "the target directory") -> str:
    """Return the normalised directory if `value` is a plain relative path, else raise ValueError naming
    `what` (the caller's word for the value) and `hint` (what a good one looks like).

    Checked before anything acts on the path, so a bad value costs nothing: an absolute path or one with a
    `..` in it would land OUTSIDE the directory the caller named - silently, and over whatever happens to
    live there. Refuse it loudly instead. `\\` is refused rather than translated, because a value carrying
    both separators is a guess about which one was meant.

    Shared rather than restated: `--orch-dir` scaffolds INTO the path (#4) and the site build's `source`
    and `output` are read from a manifest and then handed to `shutil.rmtree` (#2), so the second one turns
    a leading slash into a deleted directory somewhere else entirely. Same rule, same escape, one place.
    """
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError(f"{what} {value!r} is empty; {hint}")
    if "\\" in trimmed:
        raise ValueError(f"{what} {value!r} is invalid: '/' is the separator here, not '\\'; {hint}")
    if trimmed.startswith("/") or _DRIVE_RE.match(trimmed):
        raise ValueError(
            f"{what} {value!r} is invalid: it must be relative, so that it lands under "
            f"{inside} and nowhere else; {hint}")

    segments = trimmed.rstrip("/").split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ValueError(
                f"{what} {value!r} is invalid: {segment!r} is not a directory name, and a "
                f"path that climbs or doubles back does not stay relative to {inside}; {hint}")
    return "/".join(segments)


def validate_orch_dir(value: str) -> str:
    """Return the normalised block directory if it is a plain relative path, else raise ValueError. The
    rule and its reasoning live in `validate_relative_dir`; this names the value and the good example."""
    return validate_relative_dir(
        value, "orchestrator directory",
        f"give a plain relative path under the scaffold target, e.g. {_ORCH_DIR!r} (the default) "
        f"or 'deploy/provision/orchestrator'; the Windows shim gets its backslashes written for it",
        inside="the target directory")


def validate_product_name(name: str) -> str:
    """Return the trimmed product name if it is a legal lowercase slug, else raise ValueError. Enforced up
    front so a bad name fails loudly here, not as a broken filename / manifest label downstream."""
    trimmed = (name or "").strip()
    if not _PRODUCT_RE.match(trimmed):
        raise ValueError(
            f"product name {name!r} is invalid; use a lowercase slug matching {_PRODUCT_RE.pattern} "
            f"(a letter, then letters/digits/hyphens), e.g. 'fooctl'")
    return trimmed


def env_var_name(name: str) -> str:
    """The active-environment variable stem for a product: `netctl` -> `NETCTL_ENV`, `foo-ctl` -> `FOO_CTL_ENV`."""
    return name.upper().replace("-", "_") + "_ENV"


# --- reducing this kernel's version to one a scaffolded product may pin -----------------------------------
#
# Three peelings and one gate, in that order. The peelings undo exactly what setuptools-scm ADDED to the
# tag; the gate then asks whether what is left is a version somebody published.
#
#   +g1234abc[.d20260905]   the local segment: the node, and a date when the tree was dirty. Never part
#                           of a published version - PyPI refuses one outright - so it always comes off.
#   .post1.dev3             the `no-guess-dev` DISTANCE marker: "3 commits past the tag, which was a
#                           release". Both halves together mean distance; either alone does not, which is
#                           why they are peeled as one unit and not separately.
#   what remains            the tag. It is the pin if it names a published version.
#
# The gate is PEP 440's normalised public version MINUS a `.dev` component, because a `.dev` version is by
# definition unfinished and unpublished. Everything else is deliberately let through:
#
#   1.0          two components is a legal version and a legal tag. The release workflow triggers on
#                `v*` and constrains the shape no further, so a parser stricter than the tag namespace is
#                a trap: `git tag v1.0` would publish a wheel whose `simplon init` fails for every user.
#   0.1.12.post1 a post-release. Published, installable, and a perfectly ordinary thing to tag.
#   0.2.0rc1     a pre-release. `pip install simplon==0.2.0rc1` INSTALLS it - an exact `==` is an explicit
#                request and pre-release exclusion does not apply to one (measured, not assumed). Refusing
#                it would break `simplon init` for whoever deliberately installed a release candidate,
#                which is the same defect as refusing `1.0`, arrived at from the other side.
#
# WHY NOT CONSTRAIN THE TAG IN THE WORKFLOW INSTEAD. That was the other repair available, and it is a
# policy - "this project may not have a version shaped like that" - invented to accommodate a parser
# rather than because anybody wants it. Widening the parser removes the need for the policy, and after it
# every version that gets through is one `pip install` can actually resolve. There is nothing left for a
# tag gate to protect.
#
# THE ONE SENTINEL. `0.0` is not a shape, it is setuptools-scm's hard-coded stand-in for "found no tag at
# all" (vcs_versioning/_backends/_git.py, and the same literal in the hg and jj backends). A shallow
# `actions/checkout` produces exactly that - with a WARNING and not an error - so it is refused by name.
# It is the only value here rejected for what it means rather than for how it is spelled, and it is a
# second line: the first is `fetch-depth: 0` on every checkout, asserted in tests/test_version_source.py.
_LOCAL_SEGMENT_RE = re.compile(r"\+[A-Za-z0-9.]+$")
_DISTANCE_RE = re.compile(r"\.post\d+\.dev\d+$")
_PUBLISHED_RE = re.compile(r"^\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?$")

#: setuptools-scm's "no tag found" fallback. See the sentinel note above.
_NO_TAG_SENTINEL = "0.0"


def released_pin(version: str) -> str:
    """The kernel version a scaffolded product may pin, derived from `version`, or ValueError.

    THE PROBLEM THIS SOLVES (#3). The pin goes into a generated product's `requirements.txt` as
    `simplon==<x>`, and that file is the first thing its author runs `pip install -r` against. It must
    therefore name a version that EXISTS on PyPI. Since the kernel's own version now comes from the git
    tag, a kernel built anywhere but at a tag calls itself something like `0.1.12.post1.dev3+g1234abc` -
    correct for the kernel, and fatal as a pin: `pip install simplon==0.1.12.post1.dev3+g1234abc` resolves
    to nothing, and the product arrives broken.

    THE DECISION, and why it is not "pin what we are". A dev build is not published, so no `==` pin can
    name it truthfully. The closest true statement available is the release the build DESCENDS FROM, and
    the `no-guess-dev` version scheme was chosen precisely so that this string carries it: the release is
    the part before `.post`. So a product scaffolded from a developer's checkout pins the newest kernel
    that actually shipped - older than the one doing the scaffolding, never newer, and always installable.

    THE ALTERNATIVES, and why not. Pinning `0.1.13.dev3+…` writes a broken file. Pinning the default
    scheme's guessed `0.1.13` writes a file that is broken TODAY and might start working later on a
    version nobody verified against. Refusing to scaffold at all from an untagged tree would fail the one
    command every new user runs first, for a reason that is the kernel's business and not theirs.

    WHAT IT ACCEPTS is every published shape, not just `N.N.N` - two components, a post-release and a
    pre-release all get through, because the release workflow triggers on `v*` and a parser stricter than
    the tag namespace turns a legal tag into a wheel whose `simplon init` fails for everybody. The block
    comment above this function has the reasoning and the measurement for each.

    WHAT RAISES is a `.dev` version (unfinished by definition, and never published), anything a changed
    version scheme produces that is not PEP 440, the `0.0.0.dev0+unknown` a kernel reports when it is
    neither built nor installed, and setuptools-scm's `0.0` no-tag sentinel. Each means "no released
    version can be derived from this", and the honest place to say so is here - loudly, in the
    scaffolder's own process - rather than in somebody else's `pip install` a week later. `main()` turns
    it into a message and exit code 2, not a traceback.
    """
    peeled = _LOCAL_SEGMENT_RE.sub("", (version or "").strip())
    peeled = _DISTANCE_RE.sub("", peeled)
    if not _PUBLISHED_RE.match(peeled) or peeled == _NO_TAG_SENTINEL:
        raise ValueError(
            f"simplon.bootstrap: cannot derive a released kernel version from {version!r}, so there is "
            f"no pin a scaffolded product could install; expected a published version ('0.1.12', '1.0', "
            f"'0.2.0rc1') or a no-guess-dev descendant of one ('0.1.12.post1.dev3+g1234abc'). "
            f"'0.0.0.dev0+unknown' means this kernel is neither built nor installed - install it "
            f"(`pip install -e .`) and scaffold again. A version built on '0.0' means setuptools-scm "
            f"found no tag at all, which is what a shallow `git clone --depth 1` looks like - fetch the "
            f"history (`git fetch --unshallow --tags`) and build again")
    return peeled


# --- file templates (PURE text; @@PRODUCT@@ / @@ENV_VAR@@ / @@PKG_DIR@@ / @@KERNEL_PIN@@ substitute) ------
# Kept as literal strings with sentinel placeholders (not str.format) so the embedded shell/python braces
# stay verbatim and free of escaping. render() substitutes both tokens.

_MANIFEST = """\
# @@PRODUCT@@ delivery manifest - the single declarative source Simplon
# (simplon.orchestrator.manifest) assembles @@PRODUCT@@'s CLI from. Scaffolded by
# `simplon init`. Fill it in: replace the placeholder tasks with your real bodies and
# add the commands that instantiate them.
#
# Sections:
#   product       the product label (shim/manifest name + diagnostics).
#   tasks         the BODIES, each declared once: a bare name -> { impl: "module:function", help }.
#   groups        the COMMAND TREE, hung off the one the kernel's catalogue owns: group ->
#                 `commands:` -> command -> { task: <name>, ... }. A command is an INSTANCE of a
#                 task, so it never writes `impl:` itself.
#   environments  the deployment env matrix (a backend per env) + the default env.
product: @@PRODUCT@@

# --- product build data (read RAW by your paths adapter, IGNORED by the CLI engine) ---
# The CLI engine reads only tasks/groups and ignores any other top-level section, so your product's
# own build data lives here. Uncomment + extend as the pipeline grows.
# images:
#   app: @@PRODUCT@@:local
# volumes:
#   build_cache: @@PRODUCT@@-build-cache

# THE BODIES. A task is a TEMPLATE: it names a "module:function" this product's own package exports,
# and it is declared exactly once no matter how many commands run it. Two commands that differ only in
# the data they run with (`test unit` and `test system`) are two commands over ONE task, each pinning
# its own values with `with:` - which is why the body is here and the placement is below.
#
# These five are placeholders wired to the generated `orchestrator.cli` callbacks, one per phase, so a
# fresh product has a CLI that runs before it has anything to run. Replace them.
tasks:
  build:   { impl: "orchestrator.cli:build",   help: "Build the product artefacts (placeholder)." }
  check:   { impl: "orchestrator.cli:check",   help: "Verify the artefacts (placeholder)." }
  up:      { impl: "orchestrator.cli:up",      help: "Deploy the product to the target environment (placeholder)." }
  down:    { impl: "orchestrator.cli:down",    help: "Tear the deployment down (placeholder)." }
  status:  { impl: "orchestrator.cli:status",  help: "Report what is running in the target environment (placeholder)." }

# THE COMMAND TREE, and it is not this file's invention: the kernel's catalogue declares the CI/CD loop
# - build -> test -> release -> deploy -> monitor, plus support - and every product hangs its commands
# off those same six slots. That is the whole point: a person moving between two Simplon products finds
# the same groups holding the same general commands. A group name the catalogue does not declare is
# refused at load; add it to the platform's catalogue once, for everybody, or find the slot it belongs
# in.
#
# All six are shown here, each with at least one command, because a group is only useful once something
# is in it - and because the loop is easiest to learn on the day the product is empty. A group you
# declare and leave without a single command anywhere under it is a load error naming the group: it is a
# promise nobody kept. So grow a phase by ADDING to the list under its `commands:`, and if you truly
# have nothing for one yet, delete the group and let the catalogue's default (nothing rendered) stand.
groups:
  build:
    commands:
      # WHAT YOU PRODUCE: the wheel, the image, the bundle - whatever a later phase hands over.
      build: { task: build }
  test:
    commands:
      # WHAT YOU CHECK, and one command per level rather than one that runs everything: `test unit`,
      # `test system`, `test typecheck-python`. The kernel's `test:gate` runs a declared pytest suite,
      # `test:typecheck-python` runs mypy - declare a command for either the day you have its config.
      check: { task: check }
  release:
    commands:
      # WHAT YOU HAND OVER. `tag` is the catalogue's own `release:tag`: the BODY lives in the kernel,
      # this line only confirms the placement in your tree. A command with a colon in its `task:` names
      # a catalogue coordinate; one without names a task from the `tasks:` block above. Its neighbours
      # `release:artifact` and `release:image` need an `artifacts:`/`images:` section, so declare those
      # the day you have one.
      tag: { task: "release:tag" }
  deploy:
    commands:
      # WHERE IT RUNS. `deploy` and `monitor` are ENV-FIRST in the catalogue, so the environment is the
      # outer token: `@@PRODUCT@@ <env> deploy up` (`dev` below is the default). Every other group takes
      # no env and refuses one.
      up:   { task: up }
      down: { task: down }
      # An AGGREGATE: no body at all, only a plan. The kernel binds it at assembly time
      # (assemble(step_context=...) in orchestrator/cli.py) and runs its dependency plan build->up as
      # live-streamed `./@@PRODUCT@@.sh <cmd>` steps - a live example, not a dead placeholder. A command
      # is either an instance of a task or a plan over other commands, never both. `stop_on_failure:
      # false` (the default) runs every planned step and takes the worst rc.
      all:
        help: "Run build then deploy up end to end (the build->up dependency plan)."
        depends_on: [build, up]
        stop_on_failure: false
  monitor:
    commands:
      # WHAT IT LOOKS LIKE ONCE IT RUNS: health, logs, the version actually deployed. Env-first, like
      # `deploy` - you watch ONE environment.
      status: { task: status }
  support:
    commands:
      # HOST PREFLIGHT AND TOOLING - not a stage of the loop, which is why it sits beside the five
      # rather than among them. `install` is the catalogue's `support:install`, placed the same way
      # `release tag` is above. The catalogue also brings `support git` (commit/push/...) and
      # `support tasks` with no line from you at all - run `@@PRODUCT@@ support tasks catalogue` to see
      # every coordinate it offers.
      install: { task: "support:install" }

# The deployment environment matrix (#15, folded into the one manifest per #651 strand 1): one env per
# row, `backend` decides HOW it is realised (`local` today; add a cloud backend and widen
# _VALID_BACKENDS in environments.py later). An env-first command runs against ONE env, selected as the
# outer token; `default` is the implicit one.
default: dev
environments:
  dev: { backend: local, description: "Local development environment (the default)." }
"""

def _render_launcher(name: str, template: str, orch_dir: str) -> str:
    """Read a launcher template from package data and fill in the product name + the block dir.

    Package data rather than a string constant: the launchers are read by
    humans debugging a broken checkout, and a .sh file in the tree beats a
    triple-quoted blob in a Python module.

    The block dir goes in twice under two spellings, because cmd.exe wants
    backslashes: a nested `deploy/provision/orchestrator` carried over verbatim
    is the kind of path that half-works until it meets a tool that does not
    normalise it. Only `LAUNCH_ORCH_DIR` is substituted -- the venv, the
    requirements file and PYTHONPATH DERIVE from that variable inside the
    template, which is what keeps a half-parametrised shim from being possible.
    """
    # files("simplon") and then joinpath -- not files("simplon.templates"):
    # the templates directory is not a package and has no __init__.py.
    raw = files("simplon").joinpath("templates", template).read_text(encoding="utf-8")
    return (raw.replace("{{ product }}", name)
               .replace("{{ orch_dir_win }}", orch_dir.replace("/", "\\"))
               .replace("{{ orch_dir }}", orch_dir))


_REQUIREMENTS = """\
# Host-Python deps for the @@PRODUCT@@ orchestrator.
#
# The kernel is an ordinary dependency now. Bump the pin to move to a new
# kernel; nothing is vendored and nothing is included by path. Declaring the
# `test:typecheck-python` gate? Its mypy is an optional extra, so write
# `simplon[typecheck]==...` here instead.
#
# The number below is not typed by anyone: it is the RELEASED version of the
# kernel that scaffolded this product (simplon.bootstrap.released_pin). When
# that kernel was itself a development build, this is the release it descended
# from - the newest simplon on PyPI at the time, and one that installs.
simplon==@@KERNEL_PIN@@

# --- @@PRODUCT@@-product-only deps ---
"""

_INIT = '''\
"""@@PRODUCT@@ - the host-Python delivery orchestrator, scaffolded on Simplon (netctl#651 strand 4).

The CLI is assembled from @@PRODUCT@@.yaml by Simplon's binding layer; see cli.py for the composition
root and paths.py for the ProductContext wiring. Grow the CLI by editing the manifest, not this package.
"""

__version__ = "0.1.0"
'''

_MAIN = '''\
"""`python -m orchestrator ...` entry point - hands argv to the assembled Typer CLI (matches the shim's
LAUNCH_MODULE=orchestrator target `python -u -m orchestrator "$@"`)."""
from .cli import main

if __name__ == "__main__":
    main()
'''

_CLI = '''\
"""The @@PRODUCT@@ host CLI (Typer), assembled from @@PRODUCT@@.yaml by Simplon.

Scaffolded by `simplon init` (netctl#651 strand 4). This is the product's composition root:
it creates the root Typer app, ships the command-impl callables the manifest's "module:function" refs
resolve to, and hands the app + product context + environments + aliases to Simplon's binding layer
(simplon.cli). The generic assembly (a sub-app per group, hidden flat aliases, the flat-group collapse,
the CI/CD panels) and the env-first dispatch live in the kernel, driven entirely by the manifest - so a
fresh product adds groups/commands in @@PRODUCT@@.yaml and impl callables HERE, and nowhere else.

Replace the placeholder bodies (build/check/up/down/status - one per phase of the loop) with your own;
keep them as module-level callables so the manifest's task refs resolve
(simplon.orchestrator.manifest.resolve_impl imports THIS module and getattrs the function named after
the `:`). Note where they are NAMED: a body is declared once under `tasks:` in @@PRODUCT@@.yaml and a
command instantiates it with `task:` - a command never carries an `impl:` of its own, so there is one
place a body is written down and one place it is placed. The `all` command in @@PRODUCT@@.yaml is a
WORKING example of an impl-less AGGREGATE (#895/#896): it carries only `depends_on: [build, up]` and the
kernel binds it at assembly time via the step context below, so a fresh product sees the pattern live
instead of a dead placeholder - grow it by adding dependencies to that command in the manifest.
"""
from __future__ import annotations

import typer

from simplon import cli as simplon_cli
from simplon import log
from simplon.orchestrator.product import StepFactoryContext

from . import environments
from . import paths

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help=("@@PRODUCT@@ orchestrator (scaffolded on Simplon). The CI/CD loop is the "
                        "kernel's: build -> test -> release -> deploy -> monitor, plus support. AGNOSTIC "
                        "groups take no env (build, test, release, support); ENV-FIRST groups run "
                        "against a target env as the outer prefix `@@PRODUCT@@ <env> <group> <cmd>` "
                        "(default dev): deploy (up/down/all, where `all` runs the build->up dependency "
                        "plan) and monitor (status). Fill in @@PRODUCT@@.yaml to grow the CLI."))

# Back-compat command aliases (old token -> canonical), passed IN so the kernel hardcodes none. Empty for a
# fresh product; add entries here as you rename commands and want the old muscle memory to keep working.
_ALIASES: dict[str, str] = {}


def build() -> int:
    """Build the product artefacts (placeholder). Replace with your real build pipeline."""
    log.info("@@PRODUCT@@: build (placeholder) - wire me up in @@PKG_DIR@@/cli.py")
    # The generated wrapper's exit code IS this return value (cli.py.j2's `_rc` reads it), not a
    # raise - a framework-free body reports success by what it returns.
    return 0


def check() -> int:
    """Verify the artefacts (placeholder). Replace with your real checks.

    One command per LEVEL rather than one that runs everything: the kernel's `test:gate` runs a declared
    pytest suite and `test:typecheck-python` runs mypy, so a real product usually replaces this with a
    `suites:` section and one command per gate - and keeps each verdict its own.
    """
    log.info("@@PRODUCT@@: check (placeholder) - wire me up in @@PKG_DIR@@/cli.py")
    # See build() above: the exit code is the return value, not a raise.
    return 0


def up() -> int:
    """Deploy the product to the target environment (placeholder)."""
    log.info("@@PRODUCT@@: up (placeholder)")
    # See build() above: the exit code is the return value, not a raise.
    return 0


def down() -> int:
    """Tear the deployment down (placeholder)."""
    log.info("@@PRODUCT@@: down (placeholder)")
    # See build() above: the exit code is the return value, not a raise.
    return 0


def status() -> int:
    """Report what is running in the target environment (placeholder)."""
    log.info("@@PRODUCT@@: status (placeholder)")
    # See build() above: the exit code is the return value, not a raise.
    return 0


# The parsed manifest, read ONCE: the CLI is assembled from it below, and the step factory resolves each
# planned command's dotted identity through it.
_MANIFEST = paths.CONTEXT.manifest()

# The step-factory seam (#895/#896): a command NAME becomes a live-streamed `./@@PRODUCT@@.sh <cmd>` step,
# so the manifest's impl-less aggregates (`all`: depends_on build->up) run as DATA through the shared
# runner - no product Python per aggregate. Built once; StepFactoryContext is
# simplon.orchestrator.product's step-factory seam (kept distinct from the identity context in
# simplon.context, netctl#737).
#
# `for_shim` is the kernel's own factory for this shape, and using it is not a style choice: it STAMPS
# each step with the planned command's exact-command identity (`build.build`, `deploy.up`), which is what
# lets the kernel verify that step i really is the step for plan leaf i. A factory that does not stamp
# leaves that pairing unverifiable, and the kernel then drops the whole plan tree - taking every subtree's
# `stop_on_failure` with it, so a failing gate no longer stops the chain that declared it (#42).
_STEP_CONTEXT = StepFactoryContext.for_shim("@@PRODUCT@@", paths.ROOT / "@@PRODUCT@@.sh", _MANIFEST)


# Assemble the CLI from the manifest via Simplon's binding layer. Runs at import (like netctl's cli.py):
# resolve_impl imports this module and binds each leaf command's callback, so every command above must
# already be defined; step_context lets the kernel synthesize the callback for each impl-less aggregate
# (`all` runs its build->up dependency plan, reachable as `@@PRODUCT@@ all` or `@@PRODUCT@@ <env> deploy
# all`). The product name only shapes the usage hints.
simplon_cli.assemble(app, _MANIFEST, product=paths.CONTEXT.name, step_context=_STEP_CONTEXT)


def main() -> None:
    """Entry point (`python -m orchestrator`): env-first dispatch via Simplon's binding layer. The
    product context, the environments module and the alias map are injected, so simplon.cli hardcodes
    nothing product-specific."""
    simplon_cli.main(app=app, context=paths.CONTEXT, environments=environments.PROVIDER,
                      aliases=_ALIASES)
'''

_PATHS = '''\
"""@@PRODUCT@@'s product adapter onto Simplon: derive the repo ROOT + the manifest path and
register ONE ProductContext at import, so kernel code reads them back product-agnostically via
simplon.context.current() and never hardcodes "@@PRODUCT@@".

The walk up to the marker, the DELIVERY_* overrides and the fail-loud on a broken checkout are the
KERNEL's (simplon.context.bootstrap). What only this product knows is its name and where this file
sits, so that is all this module says. Extend it to read the manifest's raw build-data sections
(images/volumes/...) through CONTEXT.manifest_data() as your pipeline grows.
"""
from __future__ import annotations

from pathlib import Path

from simplon import context

CONTEXT = context.bootstrap("@@PRODUCT@@", Path(__file__).resolve().parent)
ROOT = CONTEXT.root
MANIFEST = CONTEXT.manifest_path
'''

_ENVIRONMENTS = '''\
"""@@PRODUCT@@'s named, isolated deployment environments. The matrix itself lives in @@PRODUCT@@.yaml
(the `environments:`/`default:` sections); this adapter supplies the three things that are @@PRODUCT@@'s
own and lets simplon.environments.Provider do the rest.

  * the process variable the active environment rides in (set by simplon.cli.main);
  * the backends this product IMPLEMENTS - `local` today; add your cloud backend (e.g. a VM-per-site
    provider) here and gate a command on it with PROVIDER.require_backend();
  * how this product's shim spells a command, so an error message can hand an operator a line that
    actually dispatches.

PROVIDER satisfies the simplon.cli EnvironmentProvider protocol structurally, so nothing named is
imported by the kernel - the coupling flows product -> kernel, never the reverse.
"""
from __future__ import annotations

from simplon.environments import LOCAL, Provider

ENV_VAR = "@@ENV_VAR@@"

PROVIDER = Provider(ENV_VAR, shim="./@@PRODUCT@@.sh", valid_backends=(LOCAL,))
'''

def _templates(name: str, orch_dir: str) -> dict[str, str]:
    """The (relative POSIX path -> template) map for a product, BEFORE placeholder substitution."""
    pkg_dir = pkg_dir_for(orch_dir)
    return {
        f"{name}.sh": _render_launcher(name, "launch.sh.j2", orch_dir),
        f"{name}.cmd": _render_launcher(name, "launch.cmd.j2", orch_dir),
        f"{name}.yaml": _MANIFEST,
        f"{orch_dir}/requirements.txt": _REQUIREMENTS,
        f"{pkg_dir}/__init__.py": _INIT,
        f"{pkg_dir}/__main__.py": _MAIN,
        f"{pkg_dir}/cli.py": _CLI,
        f"{pkg_dir}/paths.py": _PATHS,
        f"{pkg_dir}/environments.py": _ENVIRONMENTS,
    }


def render(name: str, *, orch_dir: str = _ORCH_DIR) -> dict[str, str]:
    """PURE: the product skeleton as a {relative POSIX path -> file content} map, with @@PRODUCT@@,
    @@ENV_VAR@@, @@PKG_DIR@@ and @@KERNEL_PIN@@ substituted. No I/O, no yaml/pydantic import - so a test can validate the
    rendered manifest through the real loader and assert the exact file set without a filesystem or the
    product's deps.

    `orch_dir` moves the whole block: the requirements file, the package source, both shims' LAUNCH_ORCH_DIR
    and the one place the generated cli.py tells the reader which file to edit. Defaults to `orchestrator`,
    and that default renders byte-for-byte what it always did."""
    product = validate_product_name(name)
    block = validate_orch_dir(orch_dir)
    env_var = env_var_name(product)
    pkg_dir = pkg_dir_for(block)
    # Still pure - a module constant read, no I/O - and it raises BEFORE any of the other files are
    # rendered, so a kernel that cannot name a released version scaffolds nothing at all rather than a
    # tree with one un-installable file in it.
    kernel_pin = released_pin(simplon.__version__)
    return {
        rel: (template.replace("@@PRODUCT@@", product)
                      .replace("@@ENV_VAR@@", env_var)
                      .replace("@@PKG_DIR@@", pkg_dir)
                      .replace("@@KERNEL_PIN@@", kernel_pin))
        for rel, template in _templates(product, block).items()
    }


def manifest_yaml(name: str) -> str:
    """Just the rendered starter manifest text (the piece a test feeds to simplon.orchestrator.manifest.load)."""
    return render(name)[f"{validate_product_name(name)}.yaml"]


def shim_relpath(name: str) -> str:
    """The rendered shim's relative path (the one file that must be executable)."""
    return f"{validate_product_name(name)}.sh"


def write(name: str, target: Path, *, force: bool = False, orch_dir: str = _ORCH_DIR) -> list[Path]:
    """Render the skeleton and write it under ``target``, returning the written paths (sorted). Creates parent
    dirs; sets the shim executable (0o755). Refuses to overwrite an existing file unless ``force`` - a fresh
    scaffold must never silently clobber a hand-edited manifest or shim - raising FileExistsError listing the
    conflicts."""
    product = validate_product_name(name)
    # render() validates `orch_dir`, and it does so before any directory is created: a refused path must
    # leave no half-scaffold behind.
    files = render(product, orch_dir=orch_dir)
    shim = shim_relpath(product)

    existing = sorted(rel for rel in files if (target / rel).exists())
    if existing and not force:
        raise FileExistsError(
            f"simplon.bootstrap: refusing to overwrite existing files under {target}: {existing}; "
            f"pass force=True (--force) to overwrite")

    written: list[Path] = []
    for rel, content in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755 if rel == shim else 0o644)
        written.append(path)
    return sorted(written)


def next_steps(name: str, target: Path, *, orch_dir: str = _ORCH_DIR) -> str:
    """The post-scaffold guidance printed after a successful write: nothing to vendor, just run the CLI -
    the launcher provisions its own venv and installs the pinned kernel from PyPI on first run."""
    product = validate_product_name(name)
    pkg_dir = pkg_dir_for(validate_orch_dir(orch_dir))
    return "\n".join([
        f"Scaffolded '{product}' under {target}",
        "",
        "Next steps:",
        f"  1. cd {target}",
        "  2. git init  (if this is a fresh repo)",
        f"  3. fill in {product}.yaml with your real groups and commands",
        f"  4. run the CLI:  ./{product}.sh help",
        f"  5. grow it: add groups + commands in {product}.yaml and impl callables in",
        f"       {pkg_dir}/cli.py",
    ])


def main(argv: list[str] | None = None) -> int:
    """`simplon init <product> [--dir DIR] [--orch-dir DIR] [--force]`: scaffold a product skeleton and
    print the next steps. Returns 0 on success, 2 on a bad product name, a clobber conflict, or a kernel
    whose version yields no pin a product could install (fail loud, no traceback)."""
    # `simplon init <name>` reads like a command; the bare product name as the first argument read like a
    # typo. The old call pattern stays valid, so `python -m simplon.bootstrap <name>` keeps working.
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "init":
        argv = argv[1:]
    elif not argv:
        # A bare `simplon` must name the one thing it can do. argparse alone would only complain about a
        # missing `product`, which tells a first-time user nothing about the subcommand they omitted.
        print("simplon: nothing to do. The one command is `simplon init <product> [--dir DIR] "
              "[--orch-dir DIR] [--force]`; "
              "use `simplon init --help` for the options.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(
        # The console script is the documented entry point, so its usage line is the one to print.
        # `python -m simplon.bootstrap <product>` still works, it is just no longer what we advertise.
        prog="simplon init",
        description="Scaffold a fresh product onto the delivery orchestrator (netctl#651 strand 4).")
    parser.add_argument("product", help="the product slug (lowercase; letters, digits, hyphens), e.g. 'fooctl'")
    parser.add_argument("--dir", dest="directory", default=None,
                        help="target directory (default: ./<product>); use '.' to scaffold in place")
    parser.add_argument("--orch-dir", dest="orch_dir", default=_ORCH_DIR,
                        help=("where the orchestrator block goes, relative to the target: it holds .venv, "
                              "requirements.txt and src/python/ (default: %(default)s). A product whose "
                              "structure reserves the repo root passes e.g. 'deploy/provision/orchestrator'. "
                              "Pass it again on a later re-run: --force overwrites the shim, so hand-editing "
                              "the generated one does not survive."))
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files instead of refusing")
    args = parser.parse_args(argv)

    try:
        product = validate_product_name(args.product)
        orch_dir = validate_orch_dir(args.orch_dir)
    except ValueError as exc:
        print(f"simplon init: {exc}", file=sys.stderr)
        return 2

    target = Path(args.directory).resolve() if args.directory else (Path.cwd() / product)
    try:
        write(product, target, force=args.force, orch_dir=orch_dir)
    except (FileExistsError, ValueError) as exc:
        # ValueError as well as FileExistsError, and it is not a formality: `write` -> `render` ->
        # `released_pin` raises one when this kernel's version cannot be reduced to something a
        # scaffolded product could install. That is a real condition a user meets - a checkout that is
        # neither built nor installed, or a shallow clone - and it must arrive the way this function
        # promises above, as a message and exit code 2. A traceback out of `simplon init`, the first
        # command any new user types, is the wrong end of the tool to be shown.
        #
        # Nothing half-written survives either: `write` calls `render` before its first mkdir, so the
        # target directory does not exist when this is reached.
        print(str(exc), file=sys.stderr)
        return 2

    print(next_steps(product, target, orch_dir=orch_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
