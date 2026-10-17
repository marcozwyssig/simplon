"""`launcher: env: pass:` - the variables a product passes into the kernel's container by name (si#467).

THE GAP. On the container route the launcher forwards a fixed set into the kernel's container -
`DELIVERY_*`, `CI`, `NO_COLOR`, `TERM`, `TZ`, `GITHUB_TOKEN`, `GH_TOKEN` and `<PRODUCT>_*` - and nothing
else, on purpose: forwarding an unbounded environment is how a secret reaches a place nobody looked. A
third-party tool that reads its secret under its own fixed name could therefore not be reached. firn's
`release publish-extension` needs `VSCE_PAT`, the name `vsce` reads, and ran only on the venv route
(firn#1041).

THE SHAPE, decided by Marco on 2026-10-16:

    launcher:
      env:
        pass: [VSCE_PAT]

Each name crosses BY NAME - `-e VSCE_PAT`, never `-e VSCE_PAT=<value>` - on the kernel's container line
and on every `toolchain:run` line, so the value is in no argv, no `docker inspect` of the command line and
no log. A name the host does not export stays unset on the far side; docker's `-e NAME` with no value
passes nothing for an unset name.

WHY THE LAUNCHER CARRIES A COPY, AND WHY THE COPY IS CHECKED. The launcher is bash and builds the kernel's
container line before any Python exists to parse this manifest with - the reason si#200 put the image pin
in a plain file. So `simplon init` renders the names into both launchers, and a launcher rendered before
the list changed would forward the old list. A name missing on the far side would then look exactly like a
name the host never set, which is the "nothing to do or failed" defect this kernel hunts. The launcher
therefore also exports the list it was rendered with, as `DELIVERY_ENV_PASS`, and `stale_launcher` refuses
a run on the container route whose launcher disagrees with the manifest. The venv route has no container
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
from collections.abc import Mapping
from importlib.resources import files

#: The manifest section this module owns.
SECTION = "launcher"

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


def declared(data: Mapping[str, object], source: str = "manifest") -> tuple[str, ...]:
    """The names this document passes through, in the order written, or () when it says nothing.

    AN ABSENT SECTION IS THE NORMAL CASE: no manifest in this family wrote `launcher:` before si#467, and a
    product that says nothing forwards exactly what it forwarded yesterday.
    """
    section = data.get(SECTION)
    if section is None:
        return ()
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section must be a mapping with `env: pass: [NAME, ...]`, "
                         f"not {type(section).__name__}")
    unknown = sorted(str(k) for k in section if str(k) != "env")
    if unknown:
        raise ValueError(f"{source}: the '{SECTION}' section does not take {', '.join(unknown)} - it takes "
                         f"`env:`. A key it ignored would forward nothing, and the command that needed the "
                         f"variable would fail on the container route with no word about why")
    env = section.get("env")
    if env is None:
        return ()
    if not isinstance(env, Mapping):
        raise ValueError(f"{source}: '{SECTION}: env' must be a mapping with `pass: [NAME, ...]`, "
                         f"not {type(env).__name__}")
    unknown = sorted(str(k) for k in env if str(k) != "pass")
    if unknown:
        raise ValueError(f"{source}: '{SECTION}: env' does not take {', '.join(unknown)} - it takes `pass:`. "
                         f"A key it ignored would forward nothing, and the command that needed the variable "
                         f"would fail on the container route with no word about why")
    names = env.get("pass")
    if names is None:
        return ()
    if not isinstance(names, list):
        raise ValueError(f"{source}: '{SECTION}: env: pass' must be a list of variable names, "
                         f"not {type(names).__name__}")
    out: list[str] = []
    for name in names:
        if not isinstance(name, str) or not _NAME.match(name):
            raise ValueError(f"{source}: '{SECTION}: env: pass' names {name!r}, which is not an environment "
                             f"variable name - a letter or `_`, then letters, digits and `_`")
        if _kernel_owned(name):
            raise ValueError(f"{source}: '{SECTION}: env: pass' names {name}, which the launcher sets on the "
                             f"kernel's container itself; forwarding the host's value over it would break "
                             f"the container. Leave it out")
        if name not in out:
            out.append(name)
    return tuple(out)


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
    return (f"{launcher} was rendered for a different `launcher: env: pass:` than the manifest declares: it "
            f"{' and '.join(said)}. A variable it does not forward would arrive here unset, which looks "
            f"exactly like one the host never set. Re-render the launchers at the product root with "
            f"`{FIX}` and run again. (Only the container route checks this: the venv route has no "
            f"container and inherits the whole environment.)")
