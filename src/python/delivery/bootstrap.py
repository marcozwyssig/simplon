"""delivery.bootstrap - scaffold a fresh product onto the delivery orchestrator (netctl#651 strand 4).

A brand-new product has no shim, no manifest and no product package yet, so it cannot reach the kernel
through its own CLI. This module is the ONE kernel entry that runs WITHOUT a product context: it writes a
minimal, valid product skeleton and prints the next steps, after which the new product configures only its
`<product>.yaml`.

Run it standalone (the kernel's python source must be on sys.path, e.g. via a checked-out submodule)::

    python -m delivery.bootstrap <product> [--dir DIR] [--force]

It renders, mirroring the shape netctl's own `netctl.yaml` + `netctl.sh` use but stripped to the bones:

    <product>.sh                                     the thin shim onto lib/platform's launch.sh
    <product>.yaml                                   the starter manifest (groups tree/env_groups/
                                                     environments the Pydantic loader accepts)
    orchestrator/requirements.txt                    the host-venv deps: `-r` the kernel's requirements
                                                     (netctl#730) + product-only pins (no re-pinned kernel)
    orchestrator/src/python/orchestrator/
        __init__.py                                  the product package
        __main__.py                                  `python -m orchestrator` entry
        cli.py                                       composition root: root Typer app + assemble
                                                     (step_context binds the `all` aggregate) + main
        paths.py                                     the ProductContext wiring (delivery.context); repo root
                                                     found by walking up to the manifest marker, not a depth
        environments.py                              the EnvironmentProvider (backends + the env-gate)

The generated manifest VALIDATES through `delivery.orchestrator.manifest.load`; the generated `paths.py`
registers a `ProductContext` exactly as netctl's adapter does, so a `git submodule add ... lib/platform`
away the new product has a working, manifest-driven CLI (`./<product>.sh help`).

Design / scope (best-effort MINIMAL slice; netctl#651 strand 4 is under-specified on purpose):

    IN this slice
      - a single-command-per-group starter manifest that loads clean and exercises BOTH an agnostic group
        (`build`, flat-collapsed) and an env-first CD group (`deploy`), plus a WORKING aggregate (`all` is
        an impl-less `depends_on: [build, up]` command the kernel binds via assemble(step_context=...), so
        `<product> all` runs build->up, not a dead placeholder) and the env matrix;
      - the full product-adapter wiring (paths/environments/cli/__main__) so the CLI actually assembles;
      - the shim + requirements (kernel deps via `-r`, netctl#730), so `./<product>.sh help` runs once
        lib/platform is vendored;
      - PURE render (text only, no I/O, no yaml/pydantic import) split from the file-writing, so the manifest
        can be validated and the file set asserted in unit tests;
      - clobber-safety: refuses to overwrite an existing file unless `--force`.

    DEFERRED to a fuller scaffolder (documented, deliberately NOT built here)
      - a real `delivery` console-script / a `bootstrap` subcommand woven into the assembled product CLI
        (today it is `python -m delivery.bootstrap`, the only honest entry before a product exists);
      - `git init` automation (side-effecting VCS state); the `git submodule add lib/platform` + bootstrap
        + verify one-command flow now lives in the repo-root `init-product.sh` wrapper (netctl#740);
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
from pathlib import Path

# A product name is a lowercase slug: it becomes the shim/manifest filename, the manifest `product:` label,
# the LAUNCH_PRODUCT diagnostic token and the `<PRODUCT>_ENV` variable stem. The package itself is the FIXED
# identifier `orchestrator` (as in netctl), so a hyphenated slug never has to be a Python identifier.
_PRODUCT_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# The generated product package is always `orchestrator` (LAUNCH_MODULE), mirroring netctl. Relative to the
# scaffolded root, its source lives here; the block dir `orchestrator/` is LAUNCH_ORCH_DIR (holds .venv +
# requirements.txt). `paths.py` locates the repo root by walking up to the manifest marker (netctl#737), so
# this layout can move without a hand-edit.
_PKG_DIR = "orchestrator/src/python/orchestrator"
_ORCH_DIR = "orchestrator"


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
# @@PRODUCT@@ delivery manifest - the single declarative source the delivery kernel
# (delivery.orchestrator.manifest) assembles @@PRODUCT@@'s CLI from. Scaffolded by
# `python -m delivery.bootstrap` (netctl#651 strand 4). Fill it in: add your real groups + commands and
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

_SHIM = """\
#!/usr/bin/env bash
#
# @@PRODUCT@@.sh - thin shim onto the shared delivery launcher (scaffolded, netctl#651 strand 4).
#
# Its ONLY job is to declare @@PRODUCT@@'s product parameters (ROOT, the orchestrator dir, the module, the
# name), export the PYTHONPATH it wants, and delegate the whole host-venv bootstrap + exec to lib/platform's
# launch.sh. Every command lives in Python under orchestrator/src/python/orchestrator. Run
# `./@@PRODUCT@@.sh help` for the command list; edit @@PRODUCT@@.yaml to grow the CLI.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# The delivery kernel, vendored as a git submodule at lib/platform. The launcher lives INSIDE it, so its
# absence means the submodule was never populated. Add it once with:
#   git submodule add https://github.com/marcozwyssig/platform.git lib/platform
# and re-init a fresh checkout with `git submodule update --init lib/platform`.
PLATFORM_SRC="$ROOT/lib/platform/src/delivery/src/python"
LAUNCH="$ROOT/lib/platform/src/delivery/src/sh/launch.sh"
if [ ! -f "$LAUNCH" ]; then
    printf '@@PRODUCT@@: delivery launcher not found at %s\\n' "$LAUNCH" >&2
    printf '@@PRODUCT@@: run: git submodule update --init lib/platform\\n' >&2
    exit 1
fi

# The kernel source + this product's orchestrator package, prepended to PYTHONPATH; the launcher execs the
# venv python with it inherited.
export PYTHONPATH="$PLATFORM_SRC:$ROOT/orchestrator/src/python${PYTHONPATH:+:$PYTHONPATH}"

LAUNCH_PRODUCT=@@PRODUCT@@ \\
LAUNCH_ROOT="$ROOT" \\
LAUNCH_ORCH_DIR="$ROOT/orchestrator" \\
LAUNCH_MODULE=orchestrator \\
    exec "$LAUNCH" "$@"
"""

_REQUIREMENTS = """\
# Host-Python deps for the @@PRODUCT@@ delivery orchestrator, scaffolded on the delivery kernel
# (netctl#651 strand 4). Installed into a host venv by @@PRODUCT@@.sh via the shared launcher.
#
# The delivery KERNEL owns its own dependency declaration (typer/click/PyYAML/rich/textual/pydantic drive
# manifest assembly + the split-pane step TUI); reference it here with -r rather than re-pinning it, so a
# kernel dep bump lands in ONE place and this file carries ONLY @@PRODUCT@@-product deps (netctl#730). pip
# resolves the -r path relative to THIS file: the kernel is vendored at <root>/lib/platform and this file is
# <root>/orchestrator/requirements.txt, so a single `../` reaches the root. (Relocate the orchestrator dir
# deeper and this is the one path to re-tune - one `../` per extra level - the Python side self-locates.)
-r ../lib/platform/src/delivery/requirements.txt

# --- @@PRODUCT@@-product-only deps ---
# Add @@PRODUCT@@'s OWN runtime deps below (HTTP clients, template engines, cloud SDKs, ...). The kernel's
# CLI/TUI stack is already covered by the -r reference above; do not re-pin it here.
"""

_INIT = '''\
"""@@PRODUCT@@ - host-Python delivery orchestrator, scaffolded on the delivery kernel (netctl#651 strand 4).

The CLI is assembled from @@PRODUCT@@.yaml by the delivery binding layer; see cli.py for the composition
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
"""The @@PRODUCT@@ host CLI (Typer), assembled from @@PRODUCT@@.yaml by the delivery kernel.

Scaffolded by `python -m delivery.bootstrap` (netctl#651 strand 4). This is the product's composition root:
it creates the root Typer app, ships the command-impl callables the manifest's "module:function" refs
resolve to, and hands the app + product context + environments + aliases to the delivery binding layer
(delivery.cli). The generic assembly (a sub-app per group, hidden flat aliases, the flat-group collapse,
the CI/CD panels) and the env-first dispatch live in the kernel, driven entirely by the manifest - so a
fresh product adds groups/commands in @@PRODUCT@@.yaml and impl callables HERE, and nowhere else.

Replace the placeholder commands (build/up/down) with your own; keep them as module-level callables so the
manifest's impl refs resolve (delivery.orchestrator.manifest.resolve_impl imports THIS module and getattrs
the function named after the `:`). The `all` command in @@PRODUCT@@.yaml is a WORKING example of an
impl-less AGGREGATE (#895/#896): it carries only `depends_on: [build, up]` and the kernel binds it at
assembly time via the step context below, so a fresh product sees the pattern live instead of a dead
placeholder - grow it by adding dependencies to that command in the manifest.
"""
from __future__ import annotations

import typer

from delivery import cli as delivery_cli
from delivery import log
from delivery.orchestrator.product import StepFactoryContext

from . import environments
from . import paths

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help=("@@PRODUCT@@ orchestrator (scaffolded on the delivery kernel). AGNOSTIC groups take "
                        "no env (build); ENV-FIRST CD groups run against a target env as the outer prefix "
                        "`@@PRODUCT@@ <env> <group> <cmd>` (default dev): deploy (up/down/all, where `all` "
                        "runs the build->up dependency plan). Fill in @@PRODUCT@@.yaml to grow the CLI."))

# Back-compat command aliases (old token -> canonical), passed IN so the kernel hardcodes none. Empty for a
# fresh product; add entries here as you rename commands and want the old muscle memory to keep working.
_ALIASES: dict[str, str] = {}


def build() -> None:
    """Build the product artefacts (placeholder). Replace with your real build pipeline."""
    log.info("@@PRODUCT@@: build (placeholder) - wire me up in orchestrator/src/python/orchestrator/cli.py")


def up() -> None:
    """Deploy the product to the target environment (placeholder)."""
    log.info("@@PRODUCT@@: up (placeholder)")


def down() -> None:
    """Tear the deployment down (placeholder)."""
    log.info("@@PRODUCT@@: down (placeholder)")


# The parsed manifest, read ONCE: the CLI is assembled from it below, and the step factory resolves each
# planned command's dotted identity through it.
_MANIFEST = paths.CONTEXT.manifest()

# The step-factory seam (#895/#896): a command NAME becomes a live-streamed `./@@PRODUCT@@.sh <cmd>` step,
# so the manifest's impl-less aggregates (`all`: depends_on build->up) run as DATA through the shared
# runner - no product Python per aggregate. Built once; StepFactoryContext is
# delivery.orchestrator.product's step-factory seam (kept distinct from the identity context in
# delivery.context, netctl#737).
#
# `for_shim` is the kernel's own factory for this shape, and using it is not a style choice: it STAMPS
# each step with the planned command's exact-command identity (`build.build`, `deploy.up`), which is what
# lets the kernel verify that step i really is the step for plan leaf i. A factory that does not stamp
# leaves that pairing unverifiable, and the kernel then drops the whole plan tree - taking every subtree's
# `stop_on_failure` with it, so a failing gate no longer stops the chain that declared it (#42).
_STEP_CONTEXT = StepFactoryContext.for_shim("@@PRODUCT@@", paths.ROOT / "@@PRODUCT@@.sh", _MANIFEST)


# Assemble the CLI from the manifest via the delivery binding layer. Runs at import (like netctl's cli.py):
# resolve_impl imports this module and binds each leaf command's callback, so every command above must
# already be defined; step_context lets the kernel synthesize the callback for each impl-less aggregate
# (`all` runs its build->up dependency plan, reachable as `@@PRODUCT@@ all` or `@@PRODUCT@@ <env> deploy
# all`). The product name only shapes the usage hints.
delivery_cli.assemble(app, _MANIFEST, product=paths.CONTEXT.name, step_context=_STEP_CONTEXT)


def main() -> None:
    """Entry point (`python -m orchestrator`): env-first dispatch via the delivery binding layer. The
    product context, the environments module and the alias map are injected, so delivery.cli hardcodes
    nothing product-specific."""
    delivery_cli.main(app=app, context=paths.CONTEXT, environments=environments, aliases=_ALIASES)
'''

_PATHS = '''\
"""@@PRODUCT@@'s product adapter onto the delivery kernel (netctl#592 Train B): derive the repo ROOT + the
manifest path and register ONE ProductContext at import, so kernel code reads them back product-agnostically
via delivery.context.current() and never hardcodes "@@PRODUCT@@". Scaffolded by `python -m
delivery.bootstrap` (netctl#651 strand 4).

The repo ROOT is found by WALKING UP from this file to the directory that holds the manifest
`@@PRODUCT@@.yaml` (the marker), NOT a hardcoded parent depth - so relocating this orchestrator package
deeper in the tree (e.g. under deploy/provision/) needs no hand-edit (netctl#737). DELIVERY_PRODUCT_ROOT /
DELIVERY_MANIFEST (the kernel's DELIVERY_* namespace) still OVERRIDE the derived defaults for a relocated
checkout / a test fixture tree; with neither set the values are the marker-walk derivation below. Extend
this adapter to read the manifest's raw build-data sections (images/volumes/...) via CONTEXT.manifest_data()
as your pipeline grows - see netctl's paths.py for the pattern.
"""
from __future__ import annotations

from pathlib import Path

from delivery import context

# The manifest file doubles as the repo-root MARKER: it sits at the repo root in the scaffolded layout.
_MANIFEST_NAME = "@@PRODUCT@@.yaml"


def _find_root(start: Path, marker: str) -> Path:
    """Walk up from `start` (inclusive) to the first directory that contains `marker`, and return it as the
    repo root. Robust to relocating this package deeper in the tree - no hardcoded parent depth (netctl#737).
    Fails loudly if the marker is never found, so a broken checkout is caught here, not as a wrong path
    downstream."""
    for candidate in (start, *start.parents):
        if (candidate / marker).is_file():
            return candidate
    raise RuntimeError(
        f"@@PRODUCT@@: cannot locate '{marker}' walking up from {start}; is the checkout intact?")


_DERIVED_ROOT = _find_root(Path(__file__).resolve().parent, _MANIFEST_NAME)
_DERIVED_MANIFEST = _DERIVED_ROOT / _MANIFEST_NAME

# Register the context ONCE at import; kernel code reads it back through delivery.context.current().
CONTEXT = context.set_current(
    context.ProductContext.resolve("@@PRODUCT@@", _DERIVED_ROOT, _DERIVED_MANIFEST))
ROOT = CONTEXT.root
MANIFEST = CONTEXT.manifest_path
'''

_ENVIRONMENTS = '''\
"""@@PRODUCT@@'s named, isolated deployment environments (#15). The env matrix lives in @@PRODUCT@@.yaml
(the `environments:`/`default:` sections, #651 strand 1); this adapter supplies @@PRODUCT@@'s VALID backend
names and the active-environment gate on top of the shared delivery.environments types. Scaffolded by
`python -m delivery.bootstrap` (netctl#651 strand 4).

A deployment command always targets ONE environment, selected env-first on the CLI (`@@PRODUCT@@ <env>
<command>`); with no prefix the manifest's `default` is used. The active environment rides in
$@@ENV_VAR@@ (set by delivery.cli.main). `backend` decides HOW a command realises the environment: `local`
today - add your cloud backend (e.g. a VM-per-site provider) to _VALID_BACKENDS and gate on it here.

This module satisfies the delivery.cli EnvironmentProvider protocol structurally (ENV_VAR, LOCAL, names,
default, is_local, require_backend), so nothing named is imported by the kernel - the coupling flows product
-> kernel.
"""
from __future__ import annotations

import os

from delivery import context, log
from delivery.environments import Environment, Registry, parse_data as _parse_data

ENV_VAR = "@@ENV_VAR@@"
LOCAL = "local"
_VALID_BACKENDS = (LOCAL,)


def _registry() -> Registry:
    # The env matrix lives in the one manifest: read the already-parsed mapping straight from the context.
    data = context.current().manifest_data()
    if not data.get("environments"):
        # No environments section: fall back to a single local `dev` so the orchestrator still runs.
        return Registry({"dev": Environment("dev", LOCAL, "Local development environment.")}, "dev")
    return _parse_data(data, _VALID_BACKENDS)


def names() -> list[str]:
    return list(_registry().environments)


def default() -> str:
    return _registry().default


def get(name: str) -> Environment | None:
    return _registry().environments.get(name)


def current() -> Environment:
    """The active environment: $@@ENV_VAR@@ if set + known, else the manifest default."""
    reg = _registry()
    return reg.environments.get(os.environ.get(ENV_VAR, ""), reg.environments[reg.default])


def is_local(name: str | None = None) -> bool:
    env = get(name) if name else current()
    return env is not None and env.backend == LOCAL


def require_backend(backend: str = LOCAL) -> None:
    """Gate a deployment command on the active environment's backend. Only `local` is implemented in the
    scaffold, so a non-local target dies clean instead of mis-running the local path."""
    env = current()
    if env.backend != backend:
        log.die(f"environment '{env.name}' needs backend '{backend}', has '{env.backend}'")
'''


def _templates(name: str) -> dict[str, str]:
    """The (relative POSIX path -> template) map for a product, BEFORE placeholder substitution."""
    return {
        f"{name}.sh": _SHIM,
        f"{name}.yaml": _MANIFEST,
        f"{_ORCH_DIR}/requirements.txt": _REQUIREMENTS,
        f"{_PKG_DIR}/__init__.py": _INIT,
        f"{_PKG_DIR}/__main__.py": _MAIN,
        f"{_PKG_DIR}/cli.py": _CLI,
        f"{_PKG_DIR}/paths.py": _PATHS,
        f"{_PKG_DIR}/environments.py": _ENVIRONMENTS,
    }


def render(name: str) -> dict[str, str]:
    """PURE: the product skeleton as a {relative POSIX path -> file content} map, with @@PRODUCT@@ and
    @@ENV_VAR@@ substituted. No I/O, no yaml/pydantic import - so a test can validate the rendered manifest
    through the real loader and assert the exact file set without a filesystem or the product's deps."""
    product = validate_product_name(name)
    env_var = env_var_name(product)
    return {
        rel: template.replace("@@PRODUCT@@", product).replace("@@ENV_VAR@@", env_var)
        for rel, template in _templates(product).items()
    }


def manifest_yaml(name: str) -> str:
    """Just the rendered starter manifest text (the piece a test feeds to delivery.orchestrator.manifest.load)."""
    return render(name)[f"{validate_product_name(name)}.yaml"]


def shim_relpath(name: str) -> str:
    """The rendered shim's relative path (the one file that must be executable)."""
    return f"{validate_product_name(name)}.sh"


def write(name: str, target: Path, *, force: bool = False) -> list[Path]:
    """Render the skeleton and write it under ``target``, returning the written paths (sorted). Creates parent
    dirs; sets the shim executable (0o755). Refuses to overwrite an existing file unless ``force`` - a fresh
    scaffold must never silently clobber a hand-edited manifest or shim - raising FileExistsError listing the
    conflicts."""
    product = validate_product_name(name)
    files = render(product)
    shim = shim_relpath(product)

    existing = sorted(rel for rel in files if (target / rel).exists())
    if existing and not force:
        raise FileExistsError(
            f"delivery.bootstrap: refusing to overwrite existing files under {target}: {existing}; "
            f"pass force=True (--force) to overwrite")

    written: list[Path] = []
    for rel, content in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755 if rel == shim else 0o644)
        written.append(path)
    return sorted(written)


def next_steps(name: str, target: Path) -> str:
    """The post-scaffold guidance printed after a successful write: vendor the kernel, then run the CLI."""
    product = validate_product_name(name)
    return "\n".join([
        f"Scaffolded '{product}' under {target}",
        "",
        "Next steps:",
        f"  1. cd {target}",
        "  2. git init  (if this is a fresh repo)",
        "  3. vendor the delivery kernel as a submodule at lib/platform:",
        "       git submodule add https://github.com/marcozwyssig/platform.git lib/platform",
        f"  4. run the CLI:  ./{product}.sh help",
        f"  5. grow it: add groups + commands in {product}.yaml and impl callables in",
        f"       {_PKG_DIR}/cli.py",
    ])


def main(argv: list[str] | None = None) -> int:
    """`python -m delivery.bootstrap <product> [--dir DIR] [--force]`: scaffold a product skeleton and print
    the next steps. Returns 0 on success, 2 on a bad product name or a clobber conflict (fail loud, no
    traceback)."""
    parser = argparse.ArgumentParser(
        prog="python -m delivery.bootstrap",
        description="Scaffold a fresh product onto the delivery orchestrator (netctl#651 strand 4).")
    parser.add_argument("product", help="the product slug (lowercase; letters, digits, hyphens), e.g. 'fooctl'")
    parser.add_argument("--dir", dest="directory", default=None,
                        help="target directory (default: ./<product>); use '.' to scaffold in place")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files instead of refusing")
    args = parser.parse_args(argv)

    try:
        product = validate_product_name(args.product)
    except ValueError as exc:
        print(f"delivery.bootstrap: {exc}", file=sys.stderr)
        return 2

    target = Path(args.directory).resolve() if args.directory else (Path.cwd() / product)
    try:
        write(product, target, force=args.force)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(next_steps(product, target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
