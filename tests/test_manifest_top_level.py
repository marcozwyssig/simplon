"""The top-level manifest keys the kernel reads, and what a run says when one is missing (si#159).

WHAT si#159 ASKED. `groups:` is refused when it names a group the platform's tree does not declare, and
the message is a good one. Every OTHER top-level key is subject to nothing: it is a product DATA section,
the mechanism `site:`, `images:`, `releases:`, `workflows:`, `nexus:` and `claude:` all use, and a product
adds its own freely. The ticket's worry was that a typo in one of those names is therefore silent - the
section simply does not exist, the task that reads it behaves as though the product opted out, and no run
says a word.

WHAT WAS MEASURED, BEFORE ANY RULE WAS DESIGNED. Every manifest this kernel can reach was read: this
repository's own `simplon.yaml` plus the five in `simplon.surface.CONSUMERS` (agile-cockpit, asbundle,
biz-cockpit, cleon, netctl) and `secure-windows-images`, the manifest the ticket was written against, on
its `migrate-to-simplon` branch. Seventy top-level keys across the seven.

    read by a kernel task  59
    read by NOBODY          0
    read by the PRODUCT'S OWN task bodies  11

The eleven are asbundle's `jdk` `ant` `eclipse` `container` `system` `github`, biz-cockpit's `image_tag`,
cleon's `release`, netctl's `volumes` `topology` and secure-windows-images' `release`. Each was traced to
the line that reads it - `orchestrator/config.py`, `orchestrator/cli.py`, `orchestrator/paths.py`,
`packer/manifest.py` - so not one of them is a typo, a leftover, or anything a rule should have caught.
**The population an "unknown top-level key" rule would exist for is zero.** That is si#85's shape and it
decides the ticket.

IT ALSO KILLS EACH CANDIDATE RULE INDIVIDUALLY, which is worth writing down so the next reader does not
re-derive it:

  - WARN ON A KEY NO DECLARED TASK READS. Sixteen per cent of the measured population (11 of 70) is read
    by a body the kernel cannot see - a product's own `impl:`, in the product's own repository. The rule
    fires on every one of them. It is not that the kernel struggles to know which sections ITS tasks read
    (it can - that is `MODULES` below); it is that the question the rule asks is not answerable at all.
  - LET A TASK DECLARE THE SECTION IT READS. Same population, plus a manifest surface change that every
    existing task in five repositories would have to adopt before the check said anything true.
  - REFUSE A KEY CLOSE TO A KNOWN ONE. Measured against the real manifests, an edit-distance-1 rule
    refuses TWO of the seven: cleon and secure-windows-images both declare a top-level `release:` section
    of their own, one character from the kernel's `releases:`, and both are read by the product. A rule
    that refuses the legitimate case is worse than the silence it replaces.

AND THE PREMISE ITSELF DID NOT SURVIVE. A mistyped kernel section is NOT silent today. Fifteen of the
seventeen top-level keys the kernel reads are NAMED by the reader that wanted them, the moment that reader
runs - `test_a_mistyped_section_is_named_by_the_reader_that_wanted_it` drives every one of them through a
real manifest on disk and a real `ProductContext` to prove it, rather than reading the source and
believing it. So what si#159 found is not an enforcement gap. It is two smaller things, and this module
holds both:

  1. WHICH NAMES THE KERNEL HAS CLAIMED WAS DISCOVERABLE ONLY BY READING THE KERNEL. The ticket's own
     case: a product whose domain word is "release" had to read `src/simplon/tasks/releasenotes.py` to
     learn that `releases:` means `{page, from, complete_from}` to somebody. The names are published on
     `building/manifest.md` now, and `test_the_page_publishes_every_key_the_kernel_reads` holds the page
     to this module in BOTH directions, so the list cannot rot in either.
  2. TWO KEYS ARE SILENT ON ABSENCE, AND THAT IS A DECISION RATHER THAN AN OVERSIGHT. `build:` and
     `env_var:` are in `SILENT_ON_ABSENCE` with the reason each was written for. They are DRIVEN too,
     asserting the silence - a declared exception nobody measured is a claim, and this repository has
     been wrong about one before.

WHY THE POPULATION IS DERIVED AND NOT TYPED, which `test_refusal_census` learned the expensive way (si#61:
a module missing from a typed list put sixteen refusals outside a census whose whole job was that the sum
could not grow quietly). A manifest DOCUMENT leaves the kernel through exactly one accessor,
`ProductContext.manifest_data()`, so the modules that read one are a fact about the source rather than
about anybody's memory. `_document_readers()` reads them off the call sites and
`test_every_module_that_reads_the_manifest_document_is_accounted_for` goes red the day a new one appears.
What a module then READS is declared in `MODULES` - that half cannot be derived without following the
document through a parameter into a module constant, and a walk that clever is a second thing to be wrong
about.

AAA throughout.
"""
from __future__ import annotations

import ast
import contextlib
import functools
import io
import re

import pytest
import yaml

from simplon import context, labegress, labinstance, nexusproxy, tracker, workflowgen
from simplon.tasks import (artifact, asset, buildfiles, claudeplugins, docs, env, image, releasenotes,
                           site, testrun)

import sitepages
from conftest import ROOT

SRC = ROOT / "src" / "simplon"

#: The one accessor a product's manifest DOCUMENT leaves `simplon.context` through. Read off the call
#: sites rather than assumed, exactly as `test_refusal_census` does with the same name: a rename here
#: finds no readers at all and `_document_readers` raises rather than quietly measuring nothing.
DOCUMENT_ACCESSOR = "manifest_data"

#: The page that publishes the names, so a manifest author learns them from the documentation instead of
#: from `src/simplon/tasks/releasenotes.py` - which is what the product in si#159 actually had to do.
PAGE = sitepages.chapter("manifest.md")

#: The heading the published table sits under. A heading rather than a line number, because a page moves.
PUBLISHED_UNDER = "### The names the kernel has claimed"

#: Every module that reads the manifest document, and the top-level keys it reads out of it. The KEYS are
#: declared; the MODULES are derived and checked against this mapping, so a reader cannot join quietly.
#:
#: ONE entry reads no key of its own, `tasks.completion`: it fetches the document and hands it to
#: `completiongen.environments_of`, which reads `environments:` and `default:` - keys `tasks.env` already
#: declares. It is here because the derivation finds it, and a module that reads the document is a module
#: this mapping must rule on, whether or not it has a key of its own. (`tasks.workflows` hands the
#: document on too, to `workflowgen.parse`, but `workflows:` is read for that command and nobody else's,
#: so it is declared here rather than left to a module that does not appear in the walk at all.)
MODULES: dict[str, tuple[str, ...]] = {
    "environments": ("environments", "default"),
    "labegress": ("lab_egress",),
    "labinstance": ("instance",),
    "nexusproxy": ("nexus",),
    "tasks.artifact": ("artifacts",),
    "tasks.asset": ("assets",),
    "tasks.buildfiles": ("build",),
    "tasks.claudeplugins": ("claude",),
    "tasks.completion": (),          # hands the document to `completiongen.environments_of`
    "tasks.conan": ("artifacts",),   # the same `artifacts:` section as tasks.artifact (si#127)
    "tasks.docs": ("doctoolchain_version",),
    "tasks.env": ("environments", "default", "env_var"),
    "tasks.image": ("images",),
    "tasks.nuget": ("artifacts",),   # likewise
    "tasks.releasenotes": ("releases",),
    "tasks.site": ("site",),
    "tasks.testrun": ("suites",),
    "tasks.workflows": ("workflows",),  # hands the document to `workflowgen.parse`
    "tracker": ("tracker",),
}

#: The two keys whose ABSENCE says nothing, each with the reason it was written that way. Both are driven
#: below, asserting the silence rather than asserting the comment: a declared exception nobody measured is
#: a claim, and si#48/si#83 are what that costs when the claim is about a set nobody looked at.
SILENT_ON_ABSENCE = {
    "build": "an absent `build:` section is the NORMAL case - `build cmake-files` renders the build "
             "files from the SOURCES, and `build: targets:` only adds the dependency edges a directory "
             "cannot show. `_declared_targets` says so at its own docstring and returns an empty "
             "mapping. So does a `build:` section a product declares for its OWN reasons and that "
             "holds no `targets:`, which two live manifests have - si#172, and "
             "`tests/test_manifest_build_section.py` drives it.",
    "env_var": "`env_var:` names the variable a product's env-first CLI publishes the active environment "
               "into. A product that selects an environment by token and `default:` alone has no such "
               "variable, so `_active` answers with the default - 'not an error, since a listing must "
               "still work on a manifest that has not adopted the key yet'.",
}

#: For each key, a manifest document in which it is correctly declared, and the reader that acts on it.
#: The test MISTYPES the key in that document and drives the reader, so what is proved is that the reader
#: got past everything else and then named THIS key - not merely that it raised something.
#:
#: Every driver goes through a manifest FILE on disk and a registered `ProductContext`, including the ones
#: whose function takes the document as an argument. A uniform front door is what makes the two halves
#: comparable: the loud fifteen and the silent two are driven by the same harness.
DRIVERS: dict[str, tuple[dict, object]] = {
    "images": ({"images": {"web": {}}},
               lambda: image.declared(context.current().manifest_data(), "web")),
    "site": ({"site": {"image": "x"}},
             lambda: site.declared(context.current().manifest_data())),
    "suites": ({"suites": {"gates": []}},
               lambda: testrun.declared(context.current().manifest_data())),
    "claude": ({"claude": {"marketplaces": {}}},
               lambda: claudeplugins.declared(context.current().manifest_data())),
    "nexus": ({"nexus": {"proxy_repositories": []}},
              lambda: nexusproxy.declared(context.current().manifest_data(), context.current().root)),
    "workflows": ({"workflows": {"ci": {}}},
                  lambda: workflowgen.parse(context.current().manifest_data())),
    "releases": ({"releases": {"page": "releases.md"}}, releasenotes.declared),
    "assets": ({"assets": {"bundle": {}}}, lambda: asset._declared("bundle")),
    "artifacts": ({"artifacts": {"site": {}}}, lambda: artifact._declared("site")),
    "instance": ({"instance": {"env_var": "X", "max_id_len": 2}}, labinstance.spec),
    "lab_egress": ({"lab_egress": {"interface": "eth0"}}, labegress.spec),
    "doctoolchain_version": ({"doctoolchain_version": "docker/x:1"},
                             lambda: docs._version(context.current().manifest_data())),
    "environments": ({"environments": {"dev": {}}, "default": "dev"}, env.environments),
    "default": ({"environments": {"dev": {}}, "default": "dev"}, env.environments),
    "build": ({"build": {"targets": {}}},
              lambda: buildfiles._declared_targets(context.current())),
    "env_var": ({"environments": {"dev": {}}, "default": "dev", "env_var": "SAMPLE_ENV"},
                env.environments),
    "tracker": ({"tracker": {"title": "Refused: {scenario}"}}, tracker.declared),
}

KEYS = tuple(sorted({key for keys in MODULES.values() for key in keys}))


def _mistyped(key: str) -> str:
    """The key with its last two characters transposed: `suites` -> `suitse`, `build` -> `buidl`.

    A transposition rather than a random string, because what si#159 is about is a MISTAKE that looks
    like the real name - `claued`, `nexsu`, `imagse`. A key spelled `zzz` would prove the reader refuses
    something; this proves it refuses the thing a person actually types.
    """
    return key[:-2] + key[-1] + key[-2]


def _register(monkeypatch, tmp_path, document: dict):
    """Write `document` as a real manifest on disk and make it the current product for ONE test.

    Through `monkeypatch.setattr` rather than `context.set_current`, and the distinction is this
    repository's own (`test_releases_page._declared` says it in as many words): `context._current` is a
    module global, so registering a tmp_path product through the real setter would decide the current
    product for every test module that runs after this one in the same process. pytest reverts an
    attribute it patched; it reverts nothing a setter did.
    """
    path = tmp_path / "sample.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext("sample", tmp_path, path))
    return path


def _drive(monkeypatch, tmp_path, document: dict, reader) -> str:
    """Register `document` as the current product, run `reader`, and return everything the run said - the
    message of whatever it raised, plus whatever it printed.

    All three channels, because the kernel refuses a section in all three: a `ValueError` out of a
    `declared()`, a `log.error` plus a `None` out of the release-notes gate (whose whole output is a
    return code and a sentence), and a `log.die` out of the buildfiles module. A harness that only caught
    the raise would report the gate as silent and be wrong about it.
    """
    _register(monkeypatch, tmp_path, document)

    out, err, raised = io.StringIO(), io.StringIO(), ""
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            reader()
        except (ValueError, SystemExit) as exc:
            raised = str(exc)
    return f"{raised}\n{out.getvalue()}\n{err.getvalue()}"


@functools.lru_cache(maxsize=None)
def _document_readers() -> tuple[str, ...]:
    """Every kernel module that calls `ProductContext.manifest_data()`, read off the call sites.

    AST rather than grep, and the difference is measured: `bootstrap` and `completiongen` both carry the
    string `manifest_data()` - in a scaffolding template and in a module docstring - and a text search
    reports them as readers of a document neither one touches.
    """
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == DOCUMENT_ACCESSOR for node in ast.walk(tree)):
            parts = list(path.relative_to(SRC).with_suffix("").parts)
            found.append(".".join(parts))
    if not found:
        raise ValueError(f"no kernel module calls {DOCUMENT_ACCESSOR}() - the walk is broken, not the "
                         f"kernel")
    return tuple(found)


@functools.lru_cache(maxsize=None)
def _published() -> tuple[str, ...]:
    """The keys the manifest page publishes, read out of the table under `PUBLISHED_UNDER`."""
    text = PAGE.read_text(encoding="utf-8")
    if PUBLISHED_UNDER not in text:
        raise ValueError(f"{PAGE} has no '{PUBLISHED_UNDER}' heading - the page this module holds is "
                         f"gone, which is a failure and not an empty result")
    # To the next SUBSECTION, not the next chapter: `## Product data sections` runs on for another 200
    # lines past this table, and three `###` sections in it carry tables of their own. Slicing to `\n## `
    # would sweep a future row shaped `| \`ci:\` | ... |` into the published set and report it as a stale
    # key, which is a true failure pointing at the wrong file.
    after = text.split(PUBLISHED_UNDER, 1)[1].split("\n### ", 1)[0]
    return tuple(re.findall(r"^\|\s*`([a-z_]+):`", after, flags=re.MULTILINE))


# --- the population ------------------------------------------------------------------------------------

def test_every_module_that_reads_the_manifest_document_is_accounted_for():
    # arrange: the modules are derived from the source, the keys they read are declared above
    derived = set(_document_readers())

    # act
    unaccounted = derived - set(MODULES)
    invented = set(MODULES) - derived

    # assert
    assert derived, "the walk found no manifest readers at all"
    assert not unaccounted, (
        f"module(s) {sorted(unaccounted)} read the manifest document and are in no entry of MODULES - "
        f"say which top-level key(s) each reads, or an empty tuple if it hands the document on")
    assert not invented, (
        f"MODULES names {sorted(invented)}, which read no manifest document any more - a reader that "
        f"has gone is a second source that has started to rot")


def test_the_keys_are_the_ones_the_readers_are_driven_with():
    # arrange / act: the declared keys, and the keys the harness can actually drive
    missing = set(KEYS) - set(DRIVERS)
    extra = set(DRIVERS) - set(KEYS)

    # assert
    assert KEYS, "no top-level key is declared at all"
    assert LOUD_ON_ABSENCE, ("every key the kernel reads is in SILENT_ON_ABSENCE, so the parametrisation "
                             "that drives a mistyped one collects nothing and reports green")
    assert not missing, f"key(s) {sorted(missing)} are declared and driven by nothing"
    assert not extra, f"DRIVERS names {sorted(extra)}, which no module reads"


# --- what a run says when a key is mistyped --------------------------------------------------------------

#: The keys a run must NAME when they are missing: every one the kernel reads, less the two whose silence
#: is declared. Bound to a name and asserted non-empty below, because a parametrisation that collected
#: nothing would pass exactly like one that collected fourteen - this repository's own recurring defect.
LOUD_ON_ABSENCE = tuple(key for key in KEYS if key not in SILENT_ON_ABSENCE)


@pytest.mark.parametrize("key", LOUD_ON_ABSENCE)
def test_a_mistyped_section_is_named_by_the_reader_that_wanted_it(key, monkeypatch, tmp_path):
    # arrange: a real manifest in which the key is spelled the way a person mistypes it
    document, reader = DRIVERS[key]
    document = {_mistyped(name) if name == key else name: value for name, value in document.items()}

    # act
    said = _drive(monkeypatch, tmp_path, document, reader)

    # assert
    assert key in said, (
        f"a manifest that spells '{key}' as '{_mistyped(key)}' produced: {said.strip()!r}. The reader "
        f"has to NAME the key it wanted, or the typo is exactly the silent opt-out si#159 reported")


@pytest.mark.parametrize("key", sorted(SILENT_ON_ABSENCE))
def test_the_two_keys_whose_absence_says_nothing_are_the_two_declared_so(key, monkeypatch, tmp_path):
    # arrange: the same mistyping, on a key whose absence is a documented opt-out
    document, reader = DRIVERS[key]
    document = {_mistyped(name) if name == key else name: value for name, value in document.items()}

    # act
    said = _drive(monkeypatch, tmp_path, document, reader)

    # assert
    assert key not in said, (
        f"'{key}' is in SILENT_ON_ABSENCE, whose reason reads: {SILENT_ON_ABSENCE[key]} - but the run "
        f"named it: {said.strip()!r}. Either the reader now speaks and the entry should go, or the "
        f"reason is about a different key")


# --- what the documentation says -------------------------------------------------------------------------

def test_the_page_publishes_every_key_the_kernel_reads():
    # arrange
    published = _published()

    # act
    unpublished = set(KEYS) - set(published)
    stale = set(published) - set(KEYS)

    # assert
    assert published, f"{PAGE} publishes no key under '{PUBLISHED_UNDER}'"
    assert not unpublished, (
        f"the kernel reads {sorted(unpublished)} and the page does not say so - which is si#159's own "
        f"case: a reserved name discoverable only by reading the kernel is a trap with a delay on it")
    assert not stale, (
        f"the page publishes {sorted(stale)}, which no kernel module reads any more")


def test_the_page_says_which_of_them_are_silent_when_absent():
    # arrange
    text = PAGE.read_text(encoding="utf-8")

    # act / assert: both silent keys are named on the page, so the two exceptions are not kernel folklore
    for key in SILENT_ON_ABSENCE:
        assert f"`{key}:`" in text, f"{PAGE} never mentions `{key}:`, whose absence a run says nothing about"


# --- the freedom si#159 must not close --------------------------------------------------------------------

def test_a_top_level_key_the_kernel_never_heard_of_is_read_by_nobody_and_refused_by_nobody(
        monkeypatch, tmp_path):
    # arrange: the shape every measured product uses - a data section of the product's own invention,
    # here secure-windows-images' `packer:`, beside a correctly spelled kernel section
    document = {"site": {"image": "hugomods/hugo:exts-0.148.2", "source": "site", "output": "build/site"},
                "packer": {"cpus": 4, "memory": 8192}}
    _register(monkeypatch, tmp_path, document)

    # act
    data = context.current().manifest_data()
    declared = site.declared(data)

    # assert: the unknown section survives the read and costs the known one nothing
    assert data["packer"] == {"cpus": 4, "memory": 8192}
    assert declared.source == "site"
