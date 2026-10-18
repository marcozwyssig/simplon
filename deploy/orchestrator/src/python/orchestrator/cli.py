"""The simplon host CLI (Typer), assembled from simplon.yaml by Simplon.

Scaffolded by `python -m simplon.cli.bootstrap` (netctl#651 strand 4), then filled in with simplon's OWN
commands: this is the kernel building and testing itself with the kernel. It is the product's composition
root: it creates the root Typer app, ships the command-impl callables the manifest's "module:function" refs
resolve to, and hands the app + product context + environments + aliases to Simplon's binding layer
(simplon.cli). The generic assembly (a sub-app per group, hidden flat aliases, the flat-group collapse,
the CI/CD panels) and the env-first dispatch live in the kernel, driven entirely by the manifest - so a
fresh product adds groups/commands in simplon.yaml and impl callables HERE, and nowhere else.

build.wheel, test.suite, support.doctor and build.model-guard below are simplon.yaml's BODIES; keep them as
module-level callables so the manifest's impl refs resolve (simplon.manifest.load.resolve_impl
imports THIS module and getattrs the function named after the `:`). Each shells out to the working tree at
ROOT (a subprocess, not an in-process call) so `./simplon.sh build wheel` / `test suite` / `support doctor`
exercise the exact commands a developer would run by hand.

`test suite` answered to `test all` until si#156. The name moved to an impl-less aggregate in the
manifest that plans the suite and the release-notes guard, so `test all` is once again what it says it
is; the body here did not change, only what it is called.
"""
from __future__ import annotations

import re
import subprocess
import sys

import typer

from simplon import cli as simplon_cli
from simplon.kernel.product import StepFactoryContext

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
# wrong build. `simplon.manifest.context.bootstrap` walks up to the manifest marker, so the derived one is
# right at any depth, and deleting the second source is cheaper than keeping it in step.
ROOT = paths.ROOT


def _run(*args: str) -> int:
    return subprocess.run([sys.executable, *args], cwd=ROOT).returncode


def build_wheel() -> int:
    """Build the wheel."""
    return _run("-m", "build", "--wheel")


#: Where the suite leaves its raw Allure results (si#248), ABSOLUTE because pytest runs with `cwd` inside
#: `tests/` and a relative `--alluredir` would land wherever the runner happened to stand. The manifest's
#: `suites:` gate names the same directory as `results_from:`, relative to the product root - two
#: spellings of one path, which is a second source; what keeps them together is that `test report` says
#: out loud when a declared source directory is not there, rather than merging nothing and reporting
#: green.
ALLURE_RESULTS = ROOT / "tests" / "allure-results"

def test_suite() -> int:
    """Run the pytest suite. Runs from src/tests/, so conftest applies.

    The pytest run ALONE, which is what the si#156 rename says out loud: `test all` is the aggregate
    over this and `test release-notes`, and a body that quietly ran a second gate would put the kernel's
    own "one implementation per verdict" rule back where si#89 found it.

    THE ONE THING THIS SUITE CANNOT DO ON si#201's CONTAINER ROUTE, said here because it is this
    invocation that meets it. Thirteen tests scaffold a fixture product into pytest's `tmp_path` and then
    really run its gate, which is a `docker run -v <tmp_path>:/src`. With the kernel itself in a
    container the daemon resolves that source against the HOST, where the container's temp directory does
    not exist, so `simplon.adapters.hostpath.translate` refuses by name rather than let the daemon create an empty
    one. Moving pytest's basetemp into the tree was tried and rejected: it makes those thirteen pass and
    breaks four others that must run OUTSIDE a git repository (`init` outside a repo, the two
    self-ignoring caches, the unreadable-checkout guard), which is a worse trade on both routes at once.
    """
    return subprocess.run([sys.executable, "-m", "pytest", "-q", f"--alluredir={ALLURE_RESULTS}"],
                          cwd=ROOT / "src" / "tests").returncode


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


# The catalogue's protected region, spelled exactly as firn spells it (TWO spaces after `End`).
_BEGIN = "# Begin Protected Region [handwritten]"
_END = "# End Protected Region  [handwritten]"
# What firn itself writes outside the region, and nothing else: its header comments, `kinds:`, one
# `  <kind>: {...}` line per kind, blank lines - and after the End marker exactly one line, its id.
_GENERATED_ABOVE = re.compile(r"(#.*|kinds:|  [a-z][a-z0-9-]*: \{.*\}|\s*)")
_ID_LINE = re.compile(r"# Generated by firn\b.*\bid=\[.*\]")


def outside_region(text: str) -> list[int]:
    """The 1-based numbers of the lines outside the protected region that firn would not write back.

    firn rewrites everything outside the region on every `gen`, with rc 0 (final review of si#344 B1): a
    task added after the id line - the end of the file, the natural place for one - loads, and the next
    `gen` deletes it. So whatever is outside and is not firn's own output is a line about to be lost.

    A text without exactly one of each marker, in order, is a ValueError rather than an answer: with a
    marker gone firn wipes the region itself, and "nothing outside" would read as safe.
    """
    lines = text.splitlines()
    for marker in (_BEGIN, _END):
        if lines.count(marker) != 1:
            raise ValueError(f"expected exactly one '{marker}' line, found {lines.count(marker)}")
    begin, end = lines.index(_BEGIN), lines.index(_END)
    if begin > end:
        raise ValueError(f"'{_END}' (line {end + 1}) comes before '{_BEGIN}' (line {begin + 1})")
    offending = [n for n, line in enumerate(lines[:begin], 1) if not _GENERATED_ABOVE.fullmatch(line)]
    after = lines[end + 1:]
    if not after or not _ID_LINE.fullmatch(after[0]):
        offending.append(end + 2)
    offending += range(end + 3, len(lines) + 1)
    return offending


def region_guard(file: str | None = None) -> int:
    """Refuse `file` (relative to the repository root) when it holds lines outside its protected region
    that firn would delete: `build model-guard`, the step BEFORE `build model-gen`.

    rc 1 names each line and says where it belongs, and firn never runs over them (the `model`
    aggregate stops on this step's failure). No file, a missing file, or one without its markers is rc 1
    too - a guard that checked nothing has not passed anything.
    """
    if not file:
        print("region-guard: no file given (pin it with `with: { file: ... }`)", file=sys.stderr)
        return 1
    path = ROOT / file
    if not path.is_file():
        print(f"region-guard: no such file: {file}", file=sys.stderr)
        return 1
    try:
        offending = outside_region(path.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"region-guard: {file}: {e}", file=sys.stderr)
        return 1
    if not offending:
        return 0
    where = ", ".join(f"line {n}" for n in offending)
    print(f"region-guard: {file}: {where} lie outside the protected region, and firn would delete them. "
          f"Move them inside the protected region (above '{_END}'), then run it again.", file=sys.stderr)
    return 1

#: Every version simplon has released is spelled this way (src/tests/test_own_release_version.py holds the
#: population), and the button is the first route on which a different spelling would publish.
_RELEASE_VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")


def release_version(tag: str = "") -> int:
    """Refuse a release version not spelled `vX.Y.Z`, before anything is cut: `release all`'s first member.

    The final review of si#491 measured `0.99.0` on the button passing the cut, the stamping check, the
    notes guard and the wheel check - a public tag and a PyPI number that could never be re-used. The old
    tag-push route ignored such a tag (`tags: ["v*"]`); nothing on the dispatch route does. This is
    simplon's guard until the kernel's `release:check` (si#487) has one, and then it goes.
    """
    if _RELEASE_VERSION.fullmatch(tag):
        return 0
    print(f"release version: {tag!r} is not a release version - simplon's are spelled vX.Y.Z (e.g. v0.34.0), "
          f"exactly as the tag will be. Nothing was cut; start the release again with that spelling.",
          file=sys.stderr)
    return 1


# The parsed manifest, read ONCE: the CLI is assembled from it below, and the step factory resolves each
# planned command's dotted identity through it.
_MANIFEST = paths.CONTEXT.manifest()

# The step-factory seam (#895/#896): it turns an impl-less aggregate's plan into live-streamed
# `./simplon.sh <cmd>` steps. simplon.yaml has two of those - `build docs` and, since si#156, `test all` -
# so this is load-bearing rather than provisional; assemble() takes a step_context either way.
# StepFactoryContext is simplon.kernel.product's step-factory seam (kept
# distinct from the identity context in simplon.manifest.context, netctl#737); `for_shim` is the kernel's own
# factory for this shape, stamping each step with the planned command's exact-command identity so the
# kernel can verify step i really is the step for plan leaf i (#42).
_STEP_CONTEXT = StepFactoryContext.for_shim("simplon", paths.ROOT / "simplon.sh", _MANIFEST)


# Assemble the CLI from the manifest via Simplon's binding layer. Runs at import (like netctl's cli.py):
# resolve_impl imports this module and binds each leaf command's callback (build_wheel, test_suite,
# doctor), so every command above must already be defined. The product name only shapes the usage hints.
simplon_cli.assemble(app, _MANIFEST, product=paths.CONTEXT.name, step_context=_STEP_CONTEXT)


def main() -> None:
    """Entry point (`python -m orchestrator`): env-first dispatch via Simplon's binding layer. The
    product context, the environments module and the alias map are injected, so simplon.cli hardcodes
    nothing product-specific."""
    simplon_cli.main(app=app, context=paths.CONTEXT, environments=environments.PROVIDER,
                      aliases=_ALIASES)
