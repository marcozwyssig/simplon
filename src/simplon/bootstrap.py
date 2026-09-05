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
    <product>.yaml                                   the starter manifest (groups tree/env_groups/
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
      - a single-command-per-group starter manifest that loads clean and exercises BOTH an agnostic group
        (`build`, flat-collapsed) and an env-first CD group (`deploy`), plus a WORKING aggregate (`all` is
        an impl-less `depends_on: [build, up]` command the kernel binds via assemble(step_context=...), so
        `<product> all` runs build->up, not a dead placeholder) and the env matrix;
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


def validate_orch_dir(value: str) -> str:
    """Return the normalised block directory if it is a plain relative path, else raise ValueError.

    Checked here rather than at the write, so a bad value costs nothing: an absolute path or one with a
    `..` in it would scaffold OUTSIDE the target the user named -- silently, and over whatever happens to
    live there. Refuse it loudly instead. `\\` is refused rather than translated, because the cmd shim gets
    its backslashes written for it and a value carrying both separators is a guess about which one was meant.
    """
    trimmed = (value or "").strip()
    hint = (f"give a plain relative path under the scaffold target, e.g. {_ORCH_DIR!r} (the default) "
            f"or 'deploy/provision/orchestrator'")
    if not trimmed:
        raise ValueError(f"orchestrator directory {value!r} is empty; {hint}")
    if "\\" in trimmed:
        raise ValueError(
            f"orchestrator directory {value!r} is invalid: '/' is the separator here, not '\\' "
            f"(the Windows shim gets its backslashes written for it); {hint}")
    if trimmed.startswith("/") or _DRIVE_RE.match(trimmed):
        raise ValueError(
            f"orchestrator directory {value!r} is invalid: it must be relative, so that the scaffold "
            f"lands under the target directory and nowhere else; {hint}")

    segments = trimmed.rstrip("/").split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ValueError(
                f"orchestrator directory {value!r} is invalid: {segment!r} is not a directory name, and a "
                f"path that climbs or doubles back does not stay relative to the target; {hint}")
    return "/".join(segments)


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


# --- file templates (PURE text; @@PRODUCT@@ / @@ENV_VAR@@ are the only substitutions) ----------------------
# Kept as literal strings with sentinel placeholders (not str.format) so the embedded shell/python braces
# stay verbatim and free of escaping. render() substitutes both tokens.

_MANIFEST = """\
# @@PRODUCT@@ delivery manifest - the single declarative source Simplon
# (simplon.orchestrator.manifest) assembles @@PRODUCT@@'s CLI from. Scaffolded by
# `simplon init` (netctl#651 strand 4). Fill it in: add your real groups + commands and
# wire each `impl` to a "module:function" your orchestrator package exports.
#
# Sections:
#   product       the product label (shim/manifest name + diagnostics).
#   groups        the ONE command tree: group -> command -> { impl: "module:function", help: "one-line
#                 summary" }. The key order within a group is its membership order; the env-gate is derived.
#   env_groups    the subset of groups that are env-first (`@@PRODUCT@@ <env> <group> <cmd>`, default below).
#   environments  the deployment env matrix (a backend per env) + the default env.
product: @@PRODUCT@@

# --- product build data (read RAW by your paths adapter, IGNORED by the CLI engine) ---
# The CLI engine reads only groups/env_groups and ignores any other top-level section, so your product's
# own build data lives here. Uncomment + extend as the pipeline grows.
# images:
#   app: @@PRODUCT@@:local
# volumes:
#   build_cache: @@PRODUCT@@-build-cache

# The ONE command tree, along the CI/CD loop: group -> command -> { impl: "module:function", help }. The
# key order within a group is its membership order. `build` is a single-member group whose member shares its
# name, so it collapses to ONE flat top-level command (`@@PRODUCT@@ build`); `deploy` is a multi-member
# env-first group (see env_groups). The starter impls point at the generated `orchestrator.cli` callbacks;
# replace them with your own as you add commands.
#
# `all` is an impl-less AGGREGATE (#895/#896): it declares no impl, only `depends_on`, and the kernel
# binds it at assembly time (assemble(step_context=...) in orchestrator/cli.py) to run its dependency
# plan build->up as live-streamed `./@@PRODUCT@@.sh <cmd>` steps - a live example, not a dead
# placeholder. `stop_on_failure: false` (the default) runs every planned step and takes the worst rc.
groups:
  build:
    build: { impl: "orchestrator.cli:build", help: "Build the product artefacts (placeholder)." }
  deploy:
    up:   { impl: "orchestrator.cli:up",     help: "Deploy the product to the target environment (placeholder)." }
    down: { impl: "orchestrator.cli:down",   help: "Tear the deployment down (placeholder)." }
    all:  { help: "Run build then deploy up end to end (the build->up dependency plan).",
            depends_on: [build, up], stop_on_failure: false }

# The env-first CD groups: `@@PRODUCT@@ <env> deploy up` (default env below). Every other group is
# environment-agnostic and rejects an env prefix.
env_groups: [deploy]

# The deployment environment matrix (#15, folded into the one manifest per #651 strand 1): one env per row,
# `backend` decides HOW it is realised (`local` today; add a cloud backend and widen _VALID_BACKENDS in
# environments.py later). A deploy command runs against ONE env, selected env-first; `default` is the
# implicit one.
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
simplon==0.1.10

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

Replace the placeholder commands (build/up/down) with your own; keep them as module-level callables so the
manifest's impl refs resolve (simplon.orchestrator.manifest.resolve_impl imports THIS module and getattrs
the function named after the `:`). The `all` command in @@PRODUCT@@.yaml is a WORKING example of an
impl-less AGGREGATE (#895/#896): it carries only `depends_on: [build, up]` and the kernel binds it at
assembly time via the step context below, so a fresh product sees the pattern live instead of a dead
placeholder - grow it by adding dependencies to that command in the manifest.
"""
from __future__ import annotations

import typer

from simplon import cli as simplon_cli
from simplon import log
from simplon.orchestrator.product import StepFactoryContext

from . import environments
from . import paths

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help=("@@PRODUCT@@ orchestrator (scaffolded on Simplon). AGNOSTIC groups take "
                        "no env (build); ENV-FIRST CD groups run against a target env as the outer prefix "
                        "`@@PRODUCT@@ <env> <group> <cmd>` (default dev): deploy (up/down/all, where `all` "
                        "runs the build->up dependency plan). Fill in @@PRODUCT@@.yaml to grow the CLI."))

# Back-compat command aliases (old token -> canonical), passed IN so the kernel hardcodes none. Empty for a
# fresh product; add entries here as you rename commands and want the old muscle memory to keep working.
_ALIASES: dict[str, str] = {}


def build() -> int:
    """Build the product artefacts (placeholder). Replace with your real build pipeline."""
    log.info("@@PRODUCT@@: build (placeholder) - wire me up in @@PKG_DIR@@/cli.py")
    # The generated wrapper's exit code IS this return value (cli.py.j2's `_rc` reads it), not a
    # raise - a framework-free body reports success by what it returns.
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
    @@ENV_VAR@@ and @@PKG_DIR@@ substituted. No I/O, no yaml/pydantic import - so a test can validate the
    rendered manifest through the real loader and assert the exact file set without a filesystem or the
    product's deps.

    `orch_dir` moves the whole block: the requirements file, the package source, both shims' LAUNCH_ORCH_DIR
    and the one place the generated cli.py tells the reader which file to edit. Defaults to `orchestrator`,
    and that default renders byte-for-byte what it always did."""
    product = validate_product_name(name)
    block = validate_orch_dir(orch_dir)
    env_var = env_var_name(product)
    pkg_dir = pkg_dir_for(block)
    return {
        rel: (template.replace("@@PRODUCT@@", product)
                      .replace("@@ENV_VAR@@", env_var)
                      .replace("@@PKG_DIR@@", pkg_dir))
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
    print the next steps. Returns 0 on success, 2 on a bad product name or a clobber conflict (fail loud, no
    traceback)."""
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
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(next_steps(product, target, orch_dir=orch_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
