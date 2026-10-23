"""Install the Claude Code plugins a product is developed with (netctl#1286).

The plugin SET is declared in the product's manifest, in a top-level `claude` section read RAW through
`ProductContext.manifest_data()` - the same way a product's build data (images, cache volumes) is read. The
CLI engine tolerates unknown top-level keys, so a product adopts this by adding the section and one manifest
entry pointing at `install_cmd`; nothing here knows which product it is serving.

TWO FILES, ONE TRUTH. `.claude/settings.json` is the NATIVE half - Claude Code reads `enabledPlugins` from
every settings.json it finds, so a human who merely opens the repo is offered the plugins with no command at
all. This module is the SCRIPTED half, for a fresh machine, an unattended agent or a CI image, where nobody
is there to accept a trust prompt. Keeping the two in agreement is the PRODUCT's job: the mechanism is here,
the assertion that a particular repo's two files match is a test in that repo, because only the product
knows where its settings.json lives and which marketplaces it is entitled to.

The decision of WHAT IS MISSING is pure (`declared` + `plan`) and unit-tested against captured
`claude plugin list --json` output; only `install` shells out. That split is why the tests need no `claude`
CLI and no network.

FRAMEWORK-FREE since netctl#1444: `install_cmd` takes plain parameters and returns an exit code, and the
`--dry-run` / `-n` declaration that used to sit in its signature is manifest `params:` data the generated
CLI module renders.
"""
from __future__ import annotations

import enum
import json
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from simplon.manifest import context
from simplon.kernel import log
from simplon.kernel.run import run

# The manifest section this module owns.
SECTION = "claude"

# Claude Code's BUILT-IN marketplace. Its own settings schema exempts this name from needing an
# `extraKnownMarketplaces` entry, because only the official Anthropic source can ever register under it. A
# product's manifest may still declare it (so the section describes every source a plugin comes from) while
# its `.claude/settings.json` omits it; a product-side parity test encodes that one exemption.
BUILTIN_MARKETPLACE = "claude-plugins-official"


@dataclass(frozen=True)
class Marketplace:
    """One plugin source: the name plugin ids reference it by, the `owner/repo` it is fetched from, and
    optionally the ref it is fetched AT.

    `ref` IS A BRANCH OR A TAG AND NOT A DIGEST (si#292), and saying so is half the point of having it.
    Claude Code's marketplace sources take `ref` and explicitly not `sha` - a plugin source inside a
    marketplace takes both, a marketplace source takes one - so the strongest pin available here is a
    name somebody upstream can move. `ref: v1.2.3` stops the silent redraw on every fetch and does not
    stop the owner of that repository from moving the tag. Both halves belong in the sentence, because
    "pinned" is otherwise read as the stronger thing.

    WHY IT EXISTS AT ALL, and it is not a security feature. This section reads as a declaration of what a
    product is developed with, and until now it could not say the one thing that makes a dependency
    declaration mean anything: WHICH. Measured over the eight manifests this family can reach, six named
    the same third-party marketplace and none of them could say a version. That is an expressiveness gap
    in this kernel's own vocabulary.
    """

    name: str
    repo: str
    ref: str = ""


@dataclass(frozen=True)
class Plan:
    """What the command would do, in DECLARATION order: the marketplaces to register, the plugins to
    install, and the ones already present - the last so a complete machine can be told it is complete
    instead of being shown nothing at all."""

    add_marketplaces: tuple[Marketplace, ...]
    install_plugins: tuple[str, ...]
    present_plugins: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        """True when this machine already matches the declaration, which is what makes a rerun a no-op."""
        return not self.add_marketplaces and not self.install_plugins


def _source_of(market: Marketplace) -> str:
    """What `claude plugin marketplace add` is handed: `owner/repo`, or `owner/repo#ref` when pinned.

    The `#` is assembled HERE and refused in the manifest, so there is one place that knows the CLI's
    spelling and the manifest names the two halves separately.
    """
    return f"{market.repo}#{market.ref}" if market.ref else market.repo


def declared(data: Mapping[str, object],
             source: str = "manifest") -> tuple[tuple[Marketplace, ...], tuple[str, ...]]:
    """The marketplaces and plugin ids the manifest declares, validated LOUDLY.

    A malformed section fails HERE rather than reaching the `claude` CLI as a nonsense argument, and every
    rule names the offending key: the section is a mapping, each marketplace is a github source with an
    `owner/name` repo, each plugin id is `name@marketplace`, and each marketplace a plugin names is
    declared. An empty section is an error too - a command that cheerfully installs nothing would look like
    success on a machine that has nothing.

    `source` only labels the errors (the caller passes its manifest path, so the message points at a file).
    """
    if data.get(SECTION) is None:
        return (), ()
    section, blame, _ = context.section(data, SECTION)
    if blame:
        raise ValueError(f"{source}: the '{SECTION}' section is not a mapping")

    raw_markets = section.get("marketplaces") or {}
    if not isinstance(raw_markets, Mapping):
        raise ValueError(f"{source}: '{SECTION}.marketplaces' must be a mapping of name -> source")
    markets: list[Marketplace] = []
    for name, body in raw_markets.items():
        where = f"{SECTION}.marketplaces.{name}"
        if not isinstance(body, Mapping):
            raise ValueError(f"{source}: '{where}' must be a mapping with 'source' and 'repo'")
        kind = str(body.get("source", "")).strip()
        repo = str(body.get("repo", "")).strip()
        if kind != "github":
            raise ValueError(f"{source}: '{where}': only source 'github' is supported, got '{kind}'")
        if repo.count("/") != 1 or not all(repo.split("/")):
            raise ValueError(f"{source}: '{where}': repo must be 'owner/name', got '{repo}'")
        ref = str(body.get("ref", "")).strip()
        if "#" in ref:
            # The CLI spells a ref as `owner/repo#ref`, so somebody will write the `#` here too. It is
            # refused rather than stripped: a value that is silently edited before use is one the
            # manifest no longer describes.
            raise ValueError(
                f"{source}: '{where}': `ref:` is the branch or tag alone, not '{ref}' - the `#` belongs "
                f"to the command line spelling, and this section names the two halves separately")
        markets.append(Marketplace(name=str(name), repo=repo, ref=ref))

    raw_plugins = section.get("plugins") or []
    if not isinstance(raw_plugins, (list, tuple)):
        raise ValueError(f"{source}: '{SECTION}.plugins' must be a list of 'name@marketplace' ids")
    known = {market.name for market in (*markets, *DEFAULT_MARKETPLACES)}
    plugins: list[str] = []
    for entry in raw_plugins:
        plugin_id = str(entry).strip()
        name, sep, market = plugin_id.partition("@")
        if sep != "@" or not name or not market:
            raise ValueError(f"{source}: '{SECTION}.plugins': '{plugin_id}' must be 'name@marketplace'")
        if market not in known:
            raise ValueError(
                f"{source}: '{SECTION}.plugins': '{plugin_id}' names undeclared marketplace '{market}'")
        plugins.append(plugin_id)
    return tuple(markets), tuple(plugins)


# --- the default simplon ships, and the set a product ends up with (si#525) ---------------------------

_OFFICIAL = BUILTIN_MARKETPLACE

#: The marketplaces the default installs from. A product declares only the ones its own additions need.
DEFAULT_MARKETPLACES: tuple[Marketplace, ...] = (
    Marketplace(name=_OFFICIAL, repo="anthropics/claude-plugins-official"),
    Marketplace(name="alexgreensh-token-optimizer", repo="alexgreensh/token-optimizer"),
)

#: Every product with the `claude` toolchain gets these (Marco, 2026-10-23), in this order.
BASE_PLUGINS: tuple[str, ...] = (
    f"superpowers@{_OFFICIAL}", f"feature-dev@{_OFFICIAL}", f"code-review@{_OFFICIAL}",
    f"code-simplifier@{_OFFICIAL}", f"security-guidance@{_OFFICIAL}", f"github@{_OFFICIAL}",
    f"frontend-design@{_OFFICIAL}", "token-optimizer@alexgreensh-token-optimizer",
)

#: What a base plugin needs on PATH to work (si#396): token-optimizer's status line is `node …`.
BASE_REQUIRES: dict[str, tuple[str, ...]] = {"token-optimizer@alexgreensh-token-optimizer": ("node",)}

#: One LSP plugin per `toolchains:` language, so a Java product does not inherit simplon's Python one.
LANGUAGE_PLUGINS: dict[str, tuple[str, ...]] = {
    "python": (f"pyright-lsp@{_OFFICIAL}",), "java": (f"jdtls-lsp@{_OFFICIAL}",),
    "cpp": (f"clangd-lsp@{_OFFICIAL}",), "dotnet": (f"csharp-lsp@{_OFFICIAL}",),
}

#: The binary each LSP plugin launches - measured 2026-10-23 as `lspServers.<name>.command` in the
#: marketplace's own `.claude-plugin/marketplace.json`.
LANGUAGE_REQUIRES: dict[str, tuple[str, ...]] = {
    "python": ("pyright-langserver",), "java": ("jdtls",), "cpp": ("clangd",), "dotnet": ("csharp-ls",),
}


@dataclass(frozen=True)
class Effective:
    """The plugin set a product ends up with, and for each id where it came from - `default`,
    `toolchain <language>` or `product` - so a dry run can say which entries a product added."""

    markets: tuple[Marketplace, ...]
    plugins: tuple[str, ...]
    requires: tuple[str, ...]
    origin: Mapping[str, str]


def effective(data: Mapping[str, object], source: str = "manifest") -> Effective | None:
    """Default + the product's additions - its `exclude:`; None when the `claude` toolchain is off.

    A product never restates simplon's list (Marco, 2026-10-23): it was copied by hand before, and a copy
    drifts the day the default changes. An exclusion that names nothing in the default is refused, because
    excluding nothing is a typo, and so is a set left empty - installing nothing is not what a product that
    turned Claude support on asked for.
    """
    from simplon.tasks import profiles

    toolchains = profiles.declared_toolchains(data, source=source)
    if "claude" not in toolchains:
        return None
    own_markets, own_plugins = declared(data, source=source)
    section, _, _ = context.section(data, SECTION)   # a mapping: `declared` above has refused anything else
    raw_exclude = section.get("exclude") or []
    if not isinstance(raw_exclude, (list, tuple)):
        raise ValueError(f"{source}: '{SECTION}.exclude' must be a list of 'name@marketplace' ids")

    origin: dict[str, str] = {}
    needs: dict[str, tuple[str, ...]] = {}
    for plugin in BASE_PLUGINS:
        origin.setdefault(plugin, "default")
        needs[plugin] = BASE_REQUIRES.get(plugin, ())
    for language in toolchains:
        for plugin in LANGUAGE_PLUGINS.get(language, ()):
            origin.setdefault(plugin, f"toolchain {language}")
            needs[plugin] = LANGUAGE_REQUIRES.get(language, ())
    for plugin in own_plugins:
        origin.setdefault(plugin, "product")
    for entry in raw_exclude:
        plugin_id = str(entry).strip()
        if plugin_id not in origin or origin[plugin_id] == "product":
            raise ValueError(f"{source}: '{SECTION}.exclude' excludes '{plugin_id}', which is not in the "
                             f"default - nothing to exclude")
        del origin[plugin_id]
    if not origin:
        raise ValueError(f"{source}: '{SECTION}.exclude' excludes every plugin, so the effective plugin set is empty - remove "
                         f"'claude' from 'toolchains:' to turn Claude support off instead")
    plugins = tuple(origin)
    used = {plugin.partition("@")[2] for plugin in plugins}
    markets = tuple(m for m in (*DEFAULT_MARKETPLACES, *own_markets) if m.name in used)
    requires: list[str] = []
    for name in (*(n for plugin in plugins for n in needs.get(plugin, ())), *required(data, source)):
        if name not in requires:
            requires.append(name)
    return Effective(markets=markets, plugins=plugins, requires=tuple(requires), origin=origin)


def required(data: Mapping[str, object], source: str = "manifest") -> tuple[str, ...]:
    """The executables the manifest says its plugins run, validated LOUDLY; none when it says nothing.

    WHY THE PRODUCT SAYS IT (si#396). A plugin set can be complete on a machine that cannot run it:
    token-optimizer's status line is `node …/statusline.js`, and with no `node` on PATH Claude Code shows
    a blank status line and surfaces no error. This command then said "nothing to do". The kernel knows
    executables and not which plugin needs which, so the list is the product's, and the check is generic.

    A `requires: node` would iterate as `n`, `o`, `d`, `e`, so anything but a list is refused, and so is
    an entry that names nothing.
    """
    section, _, _ = context.section(data, SECTION)
    raw = section.get("requires")
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{source}: '{SECTION}.requires' must be a list of executable names, got {raw!r}")
    names: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{source}: '{SECTION}.requires': {entry!r} is not an executable name")
        names.append(entry.strip())
    return tuple(names)


def missing(names: Iterable[str], which: Callable[[str], object] = shutil.which) -> tuple[str, ...]:
    """The required executables `which` cannot find, in DECLARATION order."""
    return tuple(name for name in names if not which(name))


def _json_list(payload: str, what: str) -> list:
    """Parse one `claude ... --json` answer, failing loudly. An unreadable answer must NOT degrade to an
    empty list: empty means "this machine has nothing", which would turn a broken CLI into a full reinstall."""
    try:
        parsed = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"`claude {what} --json` did not return JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"`claude {what} --json` returned {type(parsed).__name__}, expected a list")
    return parsed


def installed_marketplace_names(payload: str) -> tuple[str, ...]:
    """The registered marketplace names from `claude plugin marketplace list --json`."""
    return tuple(str(entry["name"]) for entry in _json_list(payload, "plugin marketplace list")
                 if isinstance(entry, Mapping) and entry.get("name"))


def installed_plugin_ids(payload: str) -> tuple[str, ...]:
    """The installed plugin ids from `claude plugin list --json`, DEDUPED by id.

    The CLI lists one entry per SCOPE, so a plugin installed at user and project scope appears twice. This
    module only asks whether a plugin is there at all, so the duplicate would otherwise make the
    already-present count disagree with the declaration for no reason.
    """
    seen: list[str] = []
    for entry in _json_list(payload, "plugin list"):
        if isinstance(entry, Mapping) and entry.get("id") and str(entry["id"]) not in seen:
            seen.append(str(entry["id"]))
    return tuple(seen)


def plan(markets: Iterable[Marketplace], plugins: Iterable[str],
         installed_markets: Iterable[str], installed_plugins: Iterable[str]) -> Plan:
    """What is missing: a pure set difference kept in DECLARATION order, so the output reads like the
    manifest. Idempotency falls out of this rather than being a separate guard - on a complete machine both
    lists are empty and the command has nothing to do."""
    have_markets = set(installed_markets)
    have_plugins = set(installed_plugins)
    plugin_ids = tuple(plugins)
    return Plan(
        add_marketplaces=tuple(m for m in markets if m.name not in have_markets),
        install_plugins=tuple(p for p in plugin_ids if p not in have_plugins),
        present_plugins=tuple(p for p in plugin_ids if p in have_plugins),
    )


class State(enum.Enum):
    """What the plugin step did (si#525), five values because there are five things to tell a person."""

    OFF = "off"                         # the product does not have the `claude` toolchain
    SKIPPED = "skipped"                 # it does, and this machine or route cannot install (detail: why)
    NOTHING_MISSING = "nothing missing"
    INSTALLED = "installed"             # count: how many; Claude Code must restart to load them
    FAILED = "failed"                   # detail: which step and why


@dataclass(frozen=True)
class Outcome:
    state: State
    detail: str = ""
    count: int = 0
    #: False when a `requires` executable is missing (si#396): a complete set this machine cannot run.
    ready: bool = True


#: How long one `claude ... --json` query may take before the step gives up. Measured at about 0.5 s.
QUERY_TIMEOUT_S = 60.0


class _Failed(Exception):
    """A query that failed or hung: the step's FAILED, never an empty machine."""


def _installed(timeout_s: float) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Ask the `claude` CLI what is registered and installed. A failed or hung query is `_Failed`, never
    an empty machine (see `_json_list` for the same reasoning)."""
    answers = []
    for what in (["plugin", "marketplace", "list"], ["plugin", "list"]):
        shown = f"`claude {' '.join(what)} --json`"
        try:
            res = run(["claude", *what, "--json"], timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise _Failed(f"{shown} did not answer within {timeout_s:g}s") from exc
        if not res.ok:
            raise _Failed(f"{shown} failed (rc {res.rc}): {res.err.strip() or res.out.strip()}")
        answers.append(res.out)
    try:
        return installed_marketplace_names(answers[0]), installed_plugin_ids(answers[1])
    except ValueError as exc:
        raise _Failed(str(exc)) from exc


def _skip_reason(env: Mapping[str, str], container: bool) -> str:
    """Why this machine or route installs nothing, or "" when it can."""
    if container:
        return "the container route: `claude` runs on the host"
    for variable in ("CI", "GITHUB_ACTIONS"):
        if env.get(variable, "").lower() == "true":
            return f"{variable}=true: plugins are for a machine somebody develops on"
    if shutil.which("claude", path=env.get("PATH")) is None:
        return "no `claude` on PATH"
    return ""


def _effective_here() -> Effective | None:
    ctx = context.current()
    return effective(ctx.manifest_data(), source=str(ctx.manifest_path))


def step(*, env: Mapping[str, str] | None = None, container: bool = False,
         timeout_s: float = QUERY_TIMEOUT_S) -> Outcome:
    """Bring this machine to the product's effective plugin set, and say which of five things happened.

    NEVER RAISES AND NEVER DIES, because two of its callers must not stop: `support install` runs every
    gate, and the launcher must never fail a build over a plugin. A manifest the section cannot be read
    from is FAILED with the diagnosis as its detail. Installs at USER scope, so the agent behaves the same
    in every checkout of the product, linked worktrees included.
    """
    import os

    env = os.environ if env is None else env
    try:
        eff = _effective_here()
    except (ValueError, RuntimeError) as exc:     # RuntimeError: the manifest could not be read at all
        return Outcome(State.FAILED, str(exc))
    if eff is None:
        return Outcome(State.OFF)
    reason = _skip_reason(env, container)
    if reason:
        return Outcome(State.SKIPPED, reason)
    try:
        todo = plan(eff.markets, eff.plugins, *_installed(timeout_s))
    except _Failed as exc:
        return Outcome(State.FAILED, str(exc))
    ready = _report_missing(missing(eff.requires, lambda name: shutil.which(name, path=env.get("PATH"))))
    for plugin_id in todo.present_plugins:
        log.info(f"{plugin_id} already installed")
    if todo.is_complete:
        return Outcome(State.NOTHING_MISSING, count=len(eff.plugins), ready=ready)

    failed: list[str] = []
    unusable: set[str] = set()
    for market in todo.add_marketplaces:
        log.info(f"registering marketplace {market.name} ({market.repo})")
        if run(["claude", "plugin", "marketplace", "add", _source_of(market)], capture=False).ok:
            log.ok(f"marketplace {market.name} registered")
        else:
            unusable.add(market.name)
            failed.append(f"marketplace {market.name} ({market.repo}) could not be registered")
    installed = 0
    for plugin_id in todo.install_plugins:
        market_name = plugin_id.partition("@")[2]
        if market_name in unusable:
            failed.append(f"{plugin_id} skipped: its marketplace {market_name} could not be registered")
            continue
        log.info(f"installing {plugin_id}")
        if run(["claude", "plugin", "install", plugin_id, "--scope", "user"], capture=False).ok:
            log.ok(f"{plugin_id} installed")
            installed += 1
        else:
            failed.append(f"{plugin_id} could not be installed")
    if failed:
        return Outcome(State.FAILED, "; ".join(failed), count=installed, ready=ready)
    return Outcome(State.INSTALLED, count=installed, ready=ready)


def report(outcome: Outcome) -> None:
    """One line per state, worded so no two read alike."""
    if outcome.state is State.OFF:
        log.info("Claude support is off: 'claude' is not in toolchains:")
    elif outcome.state is State.SKIPPED:
        log.info(f"Claude Code plugins skipped: {outcome.detail}")
    elif outcome.state is State.NOTHING_MISSING:
        if outcome.ready:
            log.ok(f"all {outcome.count} Claude Code plugins are installed; nothing to do")
        else:
            log.warn(f"all {outcome.count} Claude Code plugins are installed, and this machine cannot run "
                     f"all of them")
    elif outcome.state is State.INSTALLED:
        log.ok(f"installed {outcome.count} Claude Code plugin(s); restart Claude Code to load them"
               + ("" if outcome.ready else ", and this machine cannot run all of them"))
    else:
        log.warn(f"Claude Code plugins: the set is INCOMPLETE - {outcome.detail}")


def _rc(outcome: Outcome) -> int:
    return 1 if outcome.state is State.FAILED or not outcome.ready else 0


def install(dry_run: bool = False) -> int:
    """`support claude-plugins`: the step, reported; 1 when it FAILED or the machine cannot run the set.

    The dry run lists each plugin with WHERE IT COMES FROM - the default, a toolchain, or the product - so
    the person running it can see what the product added on top of simplon's default.
    """
    if not dry_run:
        outcome = step()
        report(outcome)
        return _rc(outcome)
    try:
        eff = _effective_here()
    except ValueError as exc:
        log.warn(str(exc))
        return 1
    if eff is None:
        report(Outcome(State.OFF))
        return 0
    for plugin_id in eff.plugins:
        log.info(f"{plugin_id} ({eff.origin[plugin_id]})")
    reason = _skip_reason(__import__("os").environ, container=False)
    if reason:
        report(Outcome(State.SKIPPED, reason))
        return 0
    try:
        todo = plan(eff.markets, eff.plugins, *_installed(QUERY_TIMEOUT_S))
    except _Failed as exc:
        report(Outcome(State.FAILED, str(exc)))
        return 1
    ready = _report_missing(missing(eff.requires, shutil.which))
    for market in todo.add_marketplaces:
        log.info(f"would register marketplace {market.name} ({market.repo})")
    for plugin_id in todo.install_plugins:
        log.info(f"would install {plugin_id}")
    log.ok(f"dry run: {len(todo.add_marketplaces)} marketplace(s) and {len(todo.install_plugins)} "
           f"plugin(s) missing")
    return 0 if ready else 1


def _report_missing(absent: tuple[str, ...]) -> bool:
    """Name every required executable that is not on PATH; True when none is missing (si#396)."""
    for name in absent:
        log.warn(f"`{name}` is not on PATH, and a Claude Code plugin this product uses runs it; "
                 f"that plugin will not work on this machine")
    return not absent


def install_cmd(dry_run: bool = False) -> int:
    """Install the Claude Code plugins this repo is developed with, as declared in the manifest's `claude`
    section.

    `.claude/settings.json` is the NATIVE half of the same declaration: Claude Code reads `enabledPlugins`
    from every settings.json it finds, so a human who merely opens the repo is offered the plugins with no
    command. This is the SCRIPTED half, for a fresh machine, an unattended agent or a CI image where nobody
    is there to accept a trust prompt. A product-side unit test asserts the two declare the same set, so the
    pair cannot drift.

    Idempotent: it asks the `claude` CLI what is already registered and installed and adds only the
    difference, so a second run reports the set as complete and changes nothing. Installs at USER scope, so
    the agent behaves the same in every checkout including linked worktrees."""
    return install(dry_run=dry_run)
