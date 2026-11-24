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
  third-party. The launcher's dependency install and its check start from the same line, and they are not
  handed the names (si#757): the install resolves third-party packages. Inside the kernel, once dispatch
  has picked the command, `confine` unsets every forwarded name that command (or an aggregate's plan) does
  not declare - but the value stays in `docker inspect` of the kernel's container (si#757, option B);
- the `toolchain:run` hop carries the names of the command being run and of no other (`running`). The
  dispatch wrappers - `cli._bound`, the generated module, a gate's call - set them around the body with
  `within`; outside a command nothing is passed. An aggregate passes nothing of its own: each member keeps
  its own list, so one member's secret never reaches a sibling. An `env:` written on an aggregate would
  reach nothing, so the loader refuses it and points at the members (`load._command`).

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

NAMES THE MANIFEST ALREADY DECLARES ARE DERIVED, NOT REPEATED (si#810, decided by Marco 2026-11-20). A
command bound to `deploy:up` reads the carrier's `<url_from>_*`, the clone credential and the environment's
`required:`/`optional:`, all named in the manifest already; a `deploy:carrier` command reads the carrier's
password and tokens (si#812). `declared` takes them from a `derive` its
callers hand in (`tasks.deploy.variables_read`, above this layer), so they are on the launcher's list and
in the stale check; the dispatch wrappers add them to that command's keep-list for `confine`, and to no
other command's. A derived name takes a carrier's prefix, so `url_from: my-haus` derives `my-haus_PASSWORD`,
which bash cannot export and the launcher still carries (si#824, `_CARRIED`). One no launcher can carry is
left off the list and named - by `simplon init --launchers-only`, and by the kernel when the command that
reads it runs - rather than arriving unset behind a "not set" that blames the host. `support sources` is
placed by the catalogue, so no command of the document carries its names: they are read off the `sources:`
section itself (`sources.variable_roles`, si#873) and appended after every command's.

THE NAMES THE LAUNCHER SETS ITSELF ARE REFUSED, and they are read off the launcher templates rather than
typed a second time here: every `-e NAME=...` the container line writes, plus the `LAUNCH_` namespace the
launcher's own parameters live in. Forwarding the host's `HOME` or `PYTHONPATH` over the launcher's would
break the container, so that is a diagnosis. A name the launcher already forwards (`GH_TOKEN`,
`<PRODUCT>_*`, a `DELIVERY_*` it does not set) is accepted quietly: declaring it changes nothing.

LIBRARY BY INTENT, pure apart from reading the two templates the kernel ships, and it names no product.
"""
from __future__ import annotations

import contextlib
import functools
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from contextvars import ContextVar
from importlib.resources import files

from simplon.kernel import secrets
from simplon.manifest import sources, treeform

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
#: Each with its role (si#833): `gh`'s two tokens are secret, the rest are plain.
FORWARDED_ROLES = {"CI": secrets.PLAIN, "NO_COLOR": secrets.PLAIN, "TERM": secrets.PLAIN, "TZ": secrets.PLAIN,
                   "GITHUB_TOKEN": secrets.SECRET, "GH_TOKEN": secrets.SECRET}
FORWARDED = tuple(FORWARDED_ROLES)

#: The namespace the launcher's own parameters live in (`LAUNCH_PRODUCT`, `LAUNCH_ORCH_DIR`, ...).
LAUNCHER_PREFIX = "LAUNCH_"

#: A POSIX environment variable name: a letter or underscore, then letters, digits and underscores. The
#: launcher matches names inside a space-separated list, so anything else could not even be written there.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: A name BOTH LAUNCHERS CAN CARRY by name (si#824): the POSIX names, and `-` and `.` after the first
#: character. A derived name takes a carrier's prefix, and si#820 lets `url_from: my-haus` stand; measured
#: 2026-11-21, bash hands `my-haus_PASSWORD` to its children unchanged, `docker run -e` carries it and the
#: kernel's Python reads it. Nothing else: the `.sh` renders the list inside double quotes (`$`, a backquote,
#: `"`), the `.cmd` inside `set "..."` and a `for` list (`%`, `!`, `^`, `,`, `;`, `=`), and both split it on
#: whitespace. A derived name outside this is left off the list and NAMED, never dropped quietly
#: (`left_out`, `cannot_carry`).
_CARRIED = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

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


def forwardable(name: str) -> bool:
    """Whether the launcher can forward `name` by name at all: a name it can carry (`_CARRIED`, which takes
    `my-haus_PASSWORD` since si#824) and does not set itself."""
    return bool(_CARRIED.match(name)) and not _kernel_owned(name)


def forwarded_anyway(name: str, product: str) -> bool:
    """Whether every launcher forwards `name` without a list: `FORWARDED`, the `DELIVERY_*` namespace and the
    product's own `<PRODUCT>_*` (the launcher's `ENV_PREFIX`: upper case, `-` as `_`)."""
    prefix = product.upper().replace("-", "_")
    return name in FORWARDED or name.startswith("DELIVERY_") or bool(prefix) and name.startswith(f"{prefix}_")


def cannot_carry(name: str) -> str:
    """Why the launcher does not forward the derived name `name`, and the way out (si#824) - the sentence the
    renderer and the kernel both say, so a variable the host set is never reported only as "not set"."""
    why = ("the launcher sets it on the kernel's container itself" if _kernel_owned(name) else
           "a launcher can carry only letters, digits, `_`, `-` and `.` in a variable name")
    return (f"{name} does not reach the kernel on the container route: {why}. Rename what it is derived "
            f"from (a carrier's `url_from:`/`token_from:`, an environment's `required:`/`optional:`), or run "
            f"on the venv route (DELIVERY_ROUTE=venv), which inherits the whole environment")


def _commands(data: Mapping[str, object], source: str,
              derive: Callable[[str], tuple[str, ...]]) -> Iterator[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Each task command's own `env: pass:` and what `derive` answers for its task, in document order."""
    check_retired(data, source)
    _, flat = treeform.lower(treeform.tree_from_areas(dict(data), {}))
    for group, members in flat.items():
        for name, spec in (members or {}).items():
            if not isinstance(spec, Mapping) or spec.get("depends_on"):
                continue
            parts = group.split(".")
            where = " ".join([*(parts[1:] if parts[0] in ("ci", "cd") else parts), str(name)])
            task = spec.get("task")
            yield of_command(spec.get(KEY), where), (derive(task) if isinstance(task, str) else ())


def left_out(data: Mapping[str, object], source: str = "manifest", *,
             derive: Callable[[str], tuple[str, ...]]) -> tuple[str, ...]:
    """The derived names `declared` leaves off the launcher's list because no launcher can forward them, in
    the order written, each once (si#824) - for the renderer to name, each with `cannot_carry`."""
    out: list[str] = []
    for _, derived in _commands(data, source, derive):
        out += [name for name in derived if not forwardable(name) and name not in out]
    out += [name for name in sources.variable_roles(data) if not forwardable(name) and name not in out]
    return tuple(out)


def declared(data: Mapping[str, object], source: str = "manifest", *,
             derive: Callable[[str], tuple[str, ...]]) -> tuple[str, ...]:
    """The UNION of every task command's `env: pass:` in this document, and of the names the kernel derives
    for its task (si#810), in the order written, or () when there are none - the names the launcher
    forwards into the kernel's container.

    Read off the raw document, because two of its readers have no loaded manifest: the launcher renderer
    (`simplon init --launchers-only`) and the container-route check, which runs before the CLI is
    assembled. An aggregate's list is not in it: an aggregate runs no `toolchain:run` line (si#492).

    `derive(task)` is the names a kernel task reads that this same document already declares elsewhere -
    `tasks.deploy.variables_read` over it, for `deploy:up`, `deploy:down` (si#810) and `deploy:carrier`
    (si#812). It is handed in because the readers live above this layer, and it is REQUIRED so that
    neither caller can render or check a list without it: the launcher and the stale check disagreeing
    would refuse every run. It is
    asked only for a task a command is bound to, so a document whose commands bind no such task reads no
    environment at all. It takes the task and not the document, so the census's section walk follows the
    document into the reader by name at the caller (`test_every_hand_off_of_the_document_is_followed`). A
    derived name
    the launcher could not forward by name (`HOME`, or `my$haus_PASSWORD`) is left off rather than
    refused - the manifest that wrote it wrote it for the deployment, not for the launcher, and the venv
    route reads it - but it is NAMED, by `left_out` at render time and by the kernel when the command
    that reads it runs (si#824).
    """
    out: list[str] = []
    for passed_by_command, derived in _commands(data, source, derive):
        for passed in (*passed_by_command, *filter(forwardable, derived)):
            if passed not in out:
                out.append(passed)
    # si#873: `support sources` is placed by the catalogue, so no command of this document carries its names;
    # they are derived from the `sources:` section itself, after every command's, and () without one.
    # One the launcher forwards anyway (`GH_TOKEN`, `DELIVERY_*`, `<PRODUCT>_*`) stays off: on the list,
    # `confine` would unset it for every other command, which it never did before.
    product = data.get("product")
    out += [name for name in filter(forwardable, sources.variable_roles(data))
            if name not in out and not forwarded_anyway(name, product if isinstance(product, str) else "")]
    return tuple(out)


def within(names: tuple[str, ...], body: Callable[[], int]) -> int:
    """`body()`'s rc, with `names` what `running()` answers while it runs, and reset after, even on a raise.

    Every name is SECRET by role (si#833): the kernel only forwards an `env: pass:` name and never reads its
    value into a string, so calling it secret costs nothing - and its value, when set, is registered here,
    before the body runs, so no sink prints it."""
    for name in names:
        secrets.read(name)
    token = _running.set(tuple(names))
    try:
        return body()
    finally:
        _running.reset(token)


def confine(keep: Iterable[str], environ: MutableMapping[str, str] | None = None) -> tuple[str, ...]:
    """Unset every name the launcher forwarded that `keep` does not hold, and say which went (si#757).

    The launcher hands the kernel's container the UNION of every command's list, because it builds that
    line before any manifest is parsed. So once dispatch has picked the command, the kernel takes back what
    that command did not ask for: `keep` is its own `env: pass:`, or for an aggregate every planned leaf's,
    since the leaves run as processes that inherit this one's environment. Neither the body nor anything it
    starts (a third-party library, a `gh` extension) can then read a name meant for another command.

    THE LIST IS THE LAUNCHER'S OWN, `DELIVERY_ENV_PASS`, and nothing re-derives it: what is unset is exactly
    what was forwarded. With no such variable (the venv route, which inherits the caller's whole environment
    on purpose) nothing is unset. Called once per process, at the top-level dispatch only; a name kept here
    is what `within` then hands to the command's `toolchain:run` line.

    THE ACCEPTED LIMIT: the value stays visible in `docker inspect` of the kernel's container, whose Config.Env
    recorded it when the launcher started it. Only the launcher could keep it off that line, and it cannot
    tell which command runs without a second copy of the CLI's argument grammar (si#757, option B). si#833
    accepted it with a reopen trigger, recorded in `simplon.kernel.secrets`: a docker daemon shared with a
    principal who is not root-equivalent on that host. The other exposures accepted beside it (si#840: a
    child's own output under `capture=False`, Portainer's stored stack environment, a secret-named bind
    source) and their reopen triggers stand in the same place.
    """
    env = os.environ if environ is None else environ
    kept = set(keep)
    gone = tuple(name for name in env.get(EXPORTED, "").split() if name not in kept and name in env)
    for name in gone:
        del env[name]
    return gone


def of_plan(tree: object) -> tuple[str, ...]:
    """The names an aggregate keeps: every planned leaf's `env: pass:`, in plan order, each once. `tree` is
    `Manifest.plan_tree_for`'s root; a leaf whose declaration carries no list contributes nothing."""
    out: list[str] = []
    for leaf in tree.leaves():      # type: ignore[attr-defined]
        for name in getattr(leaf.spec, "env_pass", ()):
            if name not in out:
                out.append(name)
    return tuple(out)


def tasks_of_plan(tree: object) -> tuple[str, ...]:
    """The task every planned leaf is bound to, in plan order, each once - what an aggregate's derived names
    (si#810) are asked for, beside its leaves' own lists (`of_plan`)."""
    out: list[str] = []
    for leaf in tree.leaves():      # type: ignore[attr-defined]
        task = getattr(leaf.spec, "task", "")
        if task and task not in out:
            out.append(task)
    return tuple(out)


@contextlib.contextmanager
def withheld(environ: MutableMapping[str, str] | None = None) -> Iterator[None]:
    """Every forwarded name unset for the duration, and put back exactly as it was afterwards (si#757).

    For what runs in the kernel BEFORE dispatch has picked a command - the launcher's plugin step, which
    installs third-party code with `claude plugin` - so no command's name reaches it. Afterwards the
    command's own `confine` decides as usual. A name that was unset before is unset after, even if the
    step set it; one that was set gets its own value back.
    """
    env = os.environ if environ is None else environ
    forwarded = env.get(EXPORTED, "").split()
    held = {name: env[name] for name in forwarded if name in env}
    confine((), env)
    try:
        yield
    finally:
        for name in forwarded:
            env.pop(name, None)
        env.update(held)


def confined(keep: tuple[str, ...], body: Callable[[], int]) -> int:
    """`body()`'s rc, run after `confine(keep)` - the form the dispatch wrappers call."""
    confine(keep)
    return body()


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
    return (f"{launcher} was rendered for different names than the manifest declares (the commands' `env: "
            f"pass:` lists, and what a `deploy:up`/`deploy:down`/`deploy:carrier` command reads off its "
            f"carriers and environments): it {' and '.join(said)}. A variable it does not forward would "
            f"arrive here unset, which looks exactly like one the host never set. Re-render the launchers "
            f"at the product root with `{FIX}` and run again. (Only the container route checks this: the "
            f"venv route has no container and inherits the whole environment.)")
