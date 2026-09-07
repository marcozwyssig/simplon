"""The simplon host CLI (Typer), assembled from simplon.yaml by Simplon.

Scaffolded by `python -m simplon.bootstrap` (netctl#651 strand 4), then filled in with simplon's OWN
commands: this is the kernel building and testing itself with the kernel. It is the product's composition
root: it creates the root Typer app, ships the command-impl callables the manifest's "module:function" refs
resolve to, and hands the app + product context + environments + aliases to Simplon's binding layer
(simplon.cli). The generic assembly (a sub-app per group, hidden flat aliases, the flat-group collapse,
the CI/CD panels) and the env-first dispatch live in the kernel, driven entirely by the manifest - so a
fresh product adds groups/commands in simplon.yaml and impl callables HERE, and nowhere else.

build.wheel, test.all and support.doctor below are simplon.yaml's three commands; keep them as
module-level callables so the manifest's impl refs resolve (simplon.orchestrator.manifest.resolve_impl
imports THIS module and getattrs the function named after the `:`). Each shells out to the working tree at
ROOT (a subprocess, not an in-process call) so `./simplon.sh build wheel` / `test all` / `support doctor`
exercise the exact commands a developer would run by hand.
"""
from __future__ import annotations

import subprocess
import sys

import typer

from simplon import cli as simplon_cli
from simplon.orchestrator.product import StepFactoryContext

from . import environments
from . import paths

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help=("simplon orchestrator (simplon scaffolded on itself): build (wheel), test (all) "
                        "and support (doctor) drive the kernel's own build/test loop against this working "
                        "tree. Grow it by editing simplon.yaml and this module."))

# Back-compat command aliases (old token -> canonical), passed IN so the kernel hardcodes none. Empty for a
# fresh product; add entries here as you rename commands and want the old muscle memory to keep working.
_ALIASES: dict[str, str] = {}

# The repo root, and it is READ from the product context rather than counted out in `parents[n]`.
# There used to be a `parents[4]` here with a comment explaining the count, next to a `paths.ROOT`
# that already carried the answer -- two sources for one path, and the counted one was wrong the
# moment the block moved (si#24): it resolved to `deploy/`, and `test all` went looking for
# `deploy/tests`. It failed loudly, which is the only reason this is a finding and not a silently
# wrong build. `simplon.context.bootstrap` walks up to the manifest marker, so the derived one is
# right at any depth, and deleting the second source is cheaper than keeping it in step.
ROOT = paths.ROOT


def _run(*args: str) -> int:
    return subprocess.run([sys.executable, *args], cwd=ROOT).returncode


def build_wheel() -> int:
    """Build the wheel."""
    return _run("-m", "build", "--wheel")


def test_all() -> int:
    """Run every test. Runs from tests/, so conftest applies."""
    return subprocess.run([sys.executable, "-m", "pytest", "-q"],
                          cwd=ROOT / "tests").returncode


def doctor() -> int:
    """Check the tools and the environment."""
    ok = True
    for mod in ("build", "pytest"):
        try:
            __import__(mod)
        except ImportError:
            print(f"missing: {mod}", file=sys.stderr)
            ok = False
    print(f"python {sys.version.split()[0]}")
    return 0 if ok else 1


# The parsed manifest, read ONCE: the CLI is assembled from it below, and the step factory resolves each
# planned command's dotted identity through it.
_MANIFEST = paths.CONTEXT.manifest()

# The step-factory seam (#895/#896): if simplon.yaml ever grows an impl-less aggregate (a `depends_on`
# command, no `impl`), the kernel would need this to turn its plan into live-streamed `./simplon.sh <cmd>`
# steps. None of today's three commands are aggregates, but assemble() always takes a step_context, so it
# is built here regardless. StepFactoryContext is simplon.orchestrator.product's step-factory seam (kept
# distinct from the identity context in simplon.context, netctl#737); `for_shim` is the kernel's own
# factory for this shape, stamping each step with the planned command's exact-command identity so the
# kernel can verify step i really is the step for plan leaf i (#42).
_STEP_CONTEXT = StepFactoryContext.for_shim("simplon", paths.ROOT / "simplon.sh", _MANIFEST)


# Assemble the CLI from the manifest via Simplon's binding layer. Runs at import (like netctl's cli.py):
# resolve_impl imports this module and binds each leaf command's callback (build_wheel, test_all, doctor),
# so every command above must already be defined. The product name only shapes the usage hints.
simplon_cli.assemble(app, _MANIFEST, product=paths.CONTEXT.name, step_context=_STEP_CONTEXT)


def main() -> None:
    """Entry point (`python -m orchestrator`): env-first dispatch via Simplon's binding layer. The
    product context, the environments module and the alias map are injected, so simplon.cli hardcodes
    nothing product-specific."""
    simplon_cli.main(app=app, context=paths.CONTEXT, environments=environments.PROVIDER,
                      aliases=_ALIASES)
