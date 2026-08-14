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
"""
from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import typer

from delivery import context, log
from delivery.run import run

# The manifest section this module owns.
SECTION = "claude"

# Claude Code's BUILT-IN marketplace. Its own settings schema exempts this name from needing an
# `extraKnownMarketplaces` entry, because only the official Anthropic source can ever register under it. A
# product's manifest may still declare it (so the section describes every source a plugin comes from) while
# its `.claude/settings.json` omits it; a product-side parity test encodes that one exemption.
BUILTIN_MARKETPLACE = "claude-plugins-official"


@dataclass(frozen=True)
class Marketplace:
    """One plugin source: the name plugin ids reference it by, and the `owner/repo` it is fetched from."""

    name: str
    repo: str


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
    section = data.get(SECTION)
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section is missing or is not a mapping")

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
        markets.append(Marketplace(name=str(name), repo=repo))
    if not markets:
        raise ValueError(f"{source}: '{SECTION}.marketplaces' declares none")

    raw_plugins = section.get("plugins") or []
    if not isinstance(raw_plugins, (list, tuple)):
        raise ValueError(f"{source}: '{SECTION}.plugins' must be a list of 'name@marketplace' ids")
    known = {market.name for market in markets}
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
    if not plugins:
        raise ValueError(f"{source}: '{SECTION}.plugins' declares none")
    return tuple(markets), tuple(plugins)


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


def _installed() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Ask the `claude` CLI what is registered and installed. Dies on a failed query rather than treating it
    as an empty machine (see `_json_list` for the same reasoning)."""
    res = run(["claude", "plugin", "marketplace", "list", "--json"])
    if not res.ok:
        log.die(f"`claude plugin marketplace list --json` failed (rc {res.rc}): "
                f"{res.err.strip() or res.out.strip()}")
    markets = installed_marketplace_names(res.out)
    res = run(["claude", "plugin", "list", "--json"])
    if not res.ok:
        log.die(f"`claude plugin list --json` failed (rc {res.rc}): {res.err.strip() or res.out.strip()}")
    return markets, installed_plugin_ids(res.out)


def install(dry_run: bool = False) -> int:
    """Bring this machine to the declared plugin set; 0 when every step succeeded.

    Installs at USER scope, because the point is an agent that behaves the same in every checkout of the
    product's repo, including linked worktrees. A plugin whose marketplace could not be registered is
    SKIPPED rather than attempted: it would fail anyway, and one clear cause reads better than a cascade of
    consequences.
    """
    if shutil.which("claude") is None:
        log.die("the `claude` CLI is not on PATH; install Claude Code first")

    ctx = context.current()
    markets, plugins = declared(ctx.manifest_data(), source=str(ctx.manifest_path))
    todo = plan(markets, plugins, *_installed())

    for plugin_id in todo.present_plugins:
        log.info(f"{plugin_id} already installed")
    if todo.is_complete:
        log.ok(f"all {len(plugins)} declared Claude Code plugins are installed; nothing to do")
        return 0
    if dry_run:
        for market in todo.add_marketplaces:
            log.info(f"would register marketplace {market.name} ({market.repo})")
        for plugin_id in todo.install_plugins:
            log.info(f"would install {plugin_id}")
        log.ok(f"dry run: {len(todo.add_marketplaces)} marketplace(s) and "
               f"{len(todo.install_plugins)} plugin(s) missing")
        return 0

    failures = 0
    unusable: set[str] = set()
    for market in todo.add_marketplaces:
        log.info(f"registering marketplace {market.name} ({market.repo})")
        if run(["claude", "plugin", "marketplace", "add", market.repo], capture=False).ok:
            log.ok(f"marketplace {market.name} registered")
        else:
            failures += 1
            unusable.add(market.name)
            log.warn(f"marketplace {market.name} ({market.repo}) could not be registered")
    for plugin_id in todo.install_plugins:
        market_name = plugin_id.partition("@")[2]
        if market_name in unusable:
            failures += 1
            log.warn(f"{plugin_id} skipped: its marketplace {market_name} could not be registered")
            continue
        log.info(f"installing {plugin_id}")
        if run(["claude", "plugin", "install", plugin_id, "--scope", "user"], capture=False).ok:
            log.ok(f"{plugin_id} installed")
        else:
            failures += 1
            log.warn(f"{plugin_id} could not be installed")

    if failures:
        log.warn(f"{failures} step(s) failed; the plugin set is INCOMPLETE")
        return 1
    log.ok("the declared Claude Code plugin set is installed; restart Claude Code to load it")
    return 0


def install_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="print what is missing, change nothing"),
) -> None:
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
    raise typer.Exit(install(dry_run=dry_run))
