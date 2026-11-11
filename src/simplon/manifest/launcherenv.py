"""A command's `env: pass:` - the variables a product passes by name to ONE command's toolchain (si#467, si#492).

THE GAP. On the container route the launcher forwards a fixed set into the kernel's container -
`DELIVERY_*`, `CI`, `NO_COLOR`, `TERM`, `TZ`, `GITHUB_TOKEN`, `GH_TOKEN` and `<PRODUCT>_*` - and nothing
else, on purpose: forwarding an unbounded environment is how a secret reaches a place nobody looked. A
third-party tool that reads its secret under its own fixed name could therefore not be reached. firn's
`release publish-extension` needs `VSCE_PAT`, the name `vsce` reads, and ran only on the venv route
(firn#1041).

THE SHAPE, decided by Marco on 2026-11-11 (si#492), on the command that needs the variable:

    ci:
      release:
        commands:
          publish-extension:
            task: ...
            env: { pass: [VSCE_PAT] }

Each name crosses BY NAME - `-e VSCE_PAT`, never `-e VSCE_PAT=<value>` - so the value is in no argv, no
`docker inspect` of the command line and no log. A name the host does not export stays unset on the far
side; docker's `-e NAME` with no value passes nothing for an unset name.

TWO HOPS, AND ONLY THE SECOND IS PER COMMAND. si#467 had one manifest-wide `launcher: env: pass:`, and its
names reached every `toolchain:run` container - so declaring `VSCE_PAT` for one publish handed the token to
gradle and `npm install` as well (firn's security review, firn#1056). Now:

- the launcher's hop into the kernel's container carries the UNION of every command's list (`declared`).
  It has to: the launcher is bash, builds that line before any manifest is parsed, and the command that
  needs the name runs inside that container. That container runs simplon's own code and installs nothing
  third-party;
- the `toolchain:run` hop carries the names of the command being run and of no other (`running`). The
  dispatch wrappers - `cli._bound`, the generated module, a gate's call - set them around the body with
  `within`; outside a command nothing is passed. An aggregate passes nothing of its own: each member keeps
  its own list, so one member's secret never reaches a sibling.

`launcher: env: pass:` is retired, not kept as a second form (#33): a manifest that still writes it is
refused by name with the way out. None of the eight reachable manifests wrote it (measured 2026-11-11).

WHY THE LAUNCHER CARRIES A COPY, AND WHY THE COPY IS CHECKED. The launcher is bash and builds the kernel's
container line before any Python exists to parse this manifest with - the reason si#200 put the image pin
in a plain file. So `simplon init` renders the names into both launchers, and a launcher rendered before
the list changed would forward the old list. A name missing on the far side would then look exactly like a
name the host never set, which is the "nothing to do or failed" defect this kernel hunts. The launcher
therefore also exports the list it was rendered with, as `DELIVERY_ENV_PASS`, and `stale_launcher` refuses
a run on the container route whose launcher disagrees with the manifest's union. The venv route has no container
and inherits the caller's whole environment, so there is nothing to compare there.

THE NAMES THE LAUNCHER SETS ITSELF ARE REFUSED, and they are read off the launcher templates rather than
typed a second time here: every `-e NAME=...` the container line writes, plus the `LAUNCH_` namespace the
launcher's own parameters live in. Forwarding the host's `HOME` or `PYTHONPATH` over the launcher's would
break the container, so that is a diagnosis. A name the launcher already forwards (`GH_TOKEN`,
`<PRODUCT>_*`, a `DELIVERY_*` it does not set) is accepted quietly: declaring it changes nothing.

LIBRARY BY INTENT, pure apart from reading the two templates the kernel ships, and it names no product.
"""
from __future__ import annotations

import functools
import re
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from importlib.resources import files

from simplon.manifest import treeform

#: The retired top-level section (si#467's form), refused by name since si#492. Not a `SECTION`: the kernel
#: reads it only to refuse it.
RETIRED = "launcher"

#: The command key this module owns, and the one key under it.
KEY = "env"
PASS = "pass"

#: The names the running command passes to its `toolchain:run` line; () outside a command.
_running: ContextVar[tuple[str, ...]] = ContextVar("env_pass", default=())

#: The variable the launcher exports the list it was rendered with through. `DELIVERY_`-prefixed, so it is
#: the kernel's namespace; the launcher sets it explicitly and skips a host value of it.
EXPORTED = "DELIVERY_ENV_PASS"

#: THE FIXED NAMES BOTH LAUNCHERS FORWARD on the container route, beside the `DELIVERY_*` and `<PRODUCT>_*`
#: namespaces: the handful a CI runner speaks, and `gh`'s two tokens - `GH_TOKEN`, which it reads first, and
#: `GITHUB_TOKEN`, its fallback (si#225). Written once, here, and rendered into `launch.sh.j2` and
#: `launch.cmd.j2` by `simplon init`: si#225 added `GH_TOKEN` to the `.sh` list by hand and the `.cmd` copy
#: stayed one name short (si#479).
FORWARDED = ("CI", "NO_COLOR", "TERM", "TZ", "GITHUB_TOKEN", "GH_TOKEN")

#: The namespace the launcher's own parameters live in (`LAUNCH_PRODUCT`, `LAUNCH_ORCH_DIR`, ...).
LAUNCHER_PREFIX = "LAUNCH_"

#: A POSIX environment variable name: a letter or underscore, then letters, digits and underscores. The
#: launcher matches names inside a space-separated list, so anything else could not even be written there.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: `-e NAME=` / `-e "NAME=` in a launcher template - a variable the launcher itself sets on the line.
_SETS = re.compile(r'-e\s+"?([A-Za-z_][A-Za-z0-9_]*)=')

#: The fix a stale launcher is told, written once.
FIX = "simplon init --dir . --launchers-only"


@functools.cache
def launcher_sets() -> frozenset[str]:
    """The variables the launchers set on the kernel's container line themselves, read off the templates."""
    found: set[str] = set()
    for template in ("launch.sh.j2", "launch.cmd.j2"):
        text = files("simplon").joinpath("templates", template).read_text(encoding="utf-8")
        found.update(_SETS.findall(text))
    return frozenset(found)


def _kernel_owned(name: str) -> bool:
    return name in launcher_sets() or name.startswith(LAUNCHER_PREFIX)


def check_retired(data: Mapping[str, object], source: str = "manifest") -> None:
    """Refuse si#467's manifest-wide `launcher:` section, which si#492 retired, with the way out."""
    if RETIRED in data:
        raise ValueError(f"{source}: the '{RETIRED}' section is gone (si#492): `launcher: env: pass:` handed "
                         f"its names to every `toolchain:run` container. Declare `env: {{ pass: [NAME, ...] }}` "
                         f"on each command whose toolchain needs a name instead - only that command's "
                         f"`toolchain:run` line passes it - and re-render the launchers with `{FIX}`")


def of_command(env: object, where: str) -> tuple[str, ...]:
    """The names one command's `env:` passes, in the order written, or () when it says nothing.

    `where` is the command as the CLI types it (`release publish-extension`). AN ABSENT KEY IS THE NORMAL
    CASE: a command that says nothing passes exactly what it passed before.
    """
    if env is None:
        return ()
    said = f"command '{where}': `{KEY}:`"
    said_pass = f"command '{where}': `{KEY}: {PASS}:`"
    if not isinstance(env, Mapping):
        raise ValueError(f"{said} must be a mapping with `{PASS}: [NAME, ...]`, not {type(env).__name__}")
    unknown = sorted(str(k) for k in env if str(k) != PASS)
    if unknown:
        raise ValueError(f"{said} does not take {', '.join(unknown)} - it takes `{PASS}:`. A key it ignored "
                         f"would pass nothing, and the command that needed the variable would fail on the "
                         f"container route with no word about why")
    names = env.get(PASS)
    if names is None:
        return ()
    if not isinstance(names, list):
        raise ValueError(f"{said_pass} must be a list of variable names, not {type(names).__name__}")
    out: list[str] = []
    for name in names:
        if not isinstance(name, str) or not _NAME.match(name):
            raise ValueError(f"{said_pass} names {name!r}, which is not an environment variable name - a "
                             f"letter or `_`, then letters, digits and `_`")
        if _kernel_owned(name):
            raise ValueError(f"{said_pass} names {name}, which the launcher sets on the kernel's "
                             f"container itself; forwarding the host's value over it would break the "
                             f"container. Leave it out")
        if name not in out:
            out.append(name)
    return tuple(out)


def declared(data: Mapping[str, object], source: str = "manifest") -> tuple[str, ...]:
    """The UNION of every task command's `env: pass:` in this document, in the order written, or () when
    none says anything - the names the launcher forwards into the kernel's container.

    Read off the raw document, because two of its readers have no loaded manifest: the launcher renderer
    (`simplon init --launchers-only`) and the container-route check, which runs before the CLI is
    assembled. An aggregate's list is not in it: an aggregate runs no `toolchain:run` line (si#492).
    """
    check_retired(data, source)
    _, flat = treeform.lower(treeform.tree_from_areas(dict(data), {}))
    out: list[str] = []
    for group, members in flat.items():
        for name, spec in (members or {}).items():
            if not isinstance(spec, Mapping) or spec.get("depends_on"):
                continue
            parts = group.split(".")
            where = " ".join([*(parts[1:] if parts[0] in ("ci", "cd") else parts), str(name)])
            for passed in of_command(spec.get(KEY), where):
                if passed not in out:
                    out.append(passed)
    return tuple(out)


def within(names: tuple[str, ...], body: Callable[[], int]) -> int:
    """`body()`'s rc, with `names` what `running()` answers while it runs, and reset after, even on a raise."""
    token = _running.set(tuple(names))
    try:
        return body()
    finally:
        _running.reset(token)


def running() -> tuple[str, ...]:
    """The names the running command passes to its `toolchain:run` line; () outside a command, or for one
    that declares none - both pass nothing, so one value serves both."""
    return _running.get()


def stale_launcher(declared_names: tuple[str, ...], environ: Mapping[str, str], launcher: str) -> str | None:
    """Why the launcher that started this container forwards a different list than the manifest declares,
    or None when they agree.

    Asked on the container route only - the caller decides that - because only there does a launcher stand
    between the host's environment and the kernel. A launcher from before si#467 exports nothing, which
    reads as the empty list: a product that declares nothing is not refused for running one.
    """
    rendered = tuple(environ.get(EXPORTED, "").split())
    missing = [n for n in declared_names if n not in rendered]
    extra = [n for n in rendered if n not in declared_names]
    if not missing and not extra:
        return None
    said = []
    if missing:
        said.append(f"does not forward {', '.join(missing)}")
    if extra:
        said.append(f"still forwards {', '.join(extra)}")
    return (f"{launcher} was rendered for different names than the commands' `env: pass:` lists declare: it "
            f"{' and '.join(said)}. A variable it does not forward would arrive here unset, which looks "
            f"exactly like one the host never set. Re-render the launchers at the product root with "
            f"`{FIX}` and run again. (Only the container route checks this: the venv route has no "
            f"container and inherits the whole environment.)")
