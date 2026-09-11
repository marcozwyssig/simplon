"""The .NET use case chapter, held against the things it claims (si#109).

WHY A TEST AND NOT PROOFREADING. `site/content/using/case-dotnet.md` walks one delivery loop over a
toolchain the kernel runs but does not know, and like its two siblings it is made almost entirely of
second sources: command names its product's manifest already assembles, coordinates `catalogue.yaml`
already declares, an argv `simplon.tasks.profiles` already carries, refusal sentences the kernel already
builds word for word, and tables of its own rows. Every one of those is a fact stated twice.

WHAT IS DIFFERENT HERE FROM `test_case_java_chapter.py`, beyond the language. The Java product
hand-writes `impl: orchestrator.gradle:build`, so its manifest is its own invention and the suite can
only hold the page against it. This product writes NO task body for the build: `compile`, `unit` and
`analyse` are `toolchain:run` commands, and their three argv belong to `PROFILES["dotnet"]` in the
kernel. So the fixture is held against the KERNEL's own table as well as against the page - a profile
edit that changed how a .NET product compiles turns this suite red, rather than leaving a chapter
describing a build nobody would get.

WHAT THE CHAPTER PROMISES ITS READER, and therefore what has to be held:

  * THE LABELS. `run`, `derived`, `does not exist yet`, nothing else, and a step that does not exist
    carries the ticket where the decision is open. The page's own ratio sentence is computed from the
    table it summarises. This chapter has four such rows where the Java one has one, and that is the
    point of the label existing rather than a defect in the page.
  * THE COMMANDS AND COORDINATES. Resolved against the tree ASSEMBLED from
    `tests/fixtures/case_dotnet_manifest.yaml` by the same loader a real product goes through, and
    against the catalogue.
  * THE MANIFEST IT QUOTES. Every YAML block on the page is a verbatim part of the fixture, and the
    fixture's three build commands are the kernel's `dotnet` profile rather than a hand-typed copy of it.
  * THE REFUSALS. Four of them, and none is remembered: the image pin gate's, the binder's refusal of
    the `with:` shape the design writes, the missing `instance:` section, and the `KeyError` the
    scaffolder raises for every language. Each is BUILT here by the code that raises it.
  * THE MEASUREMENTS. Nothing here can prove a run happened. What it CAN prove is that the run table is
    arithmetically coherent, that it agrees with the suite size the chapter states one screen higher,
    and that the two runs with different causes really carry the same rc - which is the whole argument
    of the chapter's `test` section and the first thing a copied-and-edited table would break.
  * THE COUNTS. The scaffold's Python files and the empty ribs, read off the thing that owns them.

WHAT IS NOT CHECKED, said rather than left as a silence. The prose. The transcripts, which are dated
evidence from one machine on one day and are deliberately never a live claim. The solution file's own
numbers - 54 lines, five GUIDs, 24 configuration rows - which describe a file that is not in this
repository and never will be; they belong to si#107 and are recorded there. And the links, which are
`test_site_links.py`'s: it walks EVERY page with `sitepages`, so this chapter is inside its population
already, and a second walker here would be the drifting copy.

RED WHEN THERE IS NOTHING. Every helper raises rather than returning an empty result, and every count
assertion is paired with the population it ruled on.

AAA throughout.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import typer
import yaml

from simplon import bootstrap, docker, labinstance
from simplon import catalogue as catalogue_mod
from simplon import cli as simplon_cli
from simplon.orchestrator import manifest as manifest_mod
from simplon.tasks import profiles, toolchain
from simplon.tasks.testrun import Gate

import sitepages
from conftest import ROOT

#: The chapter under test.
CHAPTER = sitepages.chapter("case-dotnet.md")

#: The card list this half of the site renders, and the place the chapter has to appear in.
INDEX = sitepages.index("what")

#: The manifest of the product the chapter follows. `dotnetdemo` is not in this repository, so it
#: travels with the chapter and every command the page types is resolved against the tree assembled
#: from it.
FIXTURE = ROOT / "tests" / "fixtures" / "case_dotnet_manifest.yaml"

#: The closed vocabulary of honesty labels - the same three the other two case chapters carry, so a
#: reader moving between them is reading one scale and not three.
LABELS = ("run", "derived", "does not exist yet")

#: The label whose rows owe the reader a ticket.
OPEN = "does not exist yet"

#: The language whose profile this chapter is about.
LANGUAGE = "dotnet"

#: The version the chapter's product pins. Read back out of the fixture below rather than trusted here:
#: this constant only says which key the profile's image template is filled from.
VERSION_PARAM = "version"


# --- reading the page back -----------------------------------------------------------------------------


def _text() -> str:
    """The chapter, refusing to be empty."""
    body = CHAPTER.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{CHAPTER} is empty")
    return body


def _prose() -> str:
    """The chapter with its fenced blocks removed - what is left is prose and tables."""
    return sitepages.without_code(_text())


def _blocks(language: str) -> list[str]:
    """Every fenced block of one language, refusing to be empty."""
    found = re.findall(rf"^```{language}\n(.*?)^```", _text(), re.S | re.M)
    if not found:
        raise ValueError(f"{CHAPTER}: no ```{language} block, so there is nothing to compare")
    return found


def _flat(text: str) -> str:
    """One line, single-spaced - the shape a quoted message can be compared in after the page wrapped it
    across three lines to fit a column."""
    return " ".join(text.split())


def _rows(header_starts_with: str) -> list[list[str]]:
    """Every data row of the one table whose header row starts with `header_starts_with`.

    Located by its header rather than by "the n-th table", so a table added above it does not silently
    become the thing under test. A table that is not there raises.
    """
    out: list[list[str]] = []
    seen = False
    for line in _text().split("\n"):
        if line.startswith(header_starts_with):
            seen = True
            continue
        if not seen:
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):
            continue
        out.append(cells)
    if not out:
        raise ValueError(f"{CHAPTER}: no table whose header starts with {header_starts_with!r}")
    return out


def _steps() -> list[list[str]]:
    """The honesty table: [number, step, command, label, evidence] per row."""
    return _rows("| # | Step |")


def _runs() -> list[list[str]]:
    """The three-run table: [run, rc, what came out] per row."""
    return _rows("| run | rc |")


def _fixture_text() -> str:
    """The fixture as written, refusing to be empty."""
    body = FIXTURE.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{FIXTURE} is empty")
    return body


def _fixture_data() -> dict:
    """The fixture, parsed."""
    return yaml.safe_load(_fixture_text())


def _product():
    """The dotnetdemo command tree, assembled from the fixture by the loader a real product goes
    through."""
    return manifest_mod.load(_fixture_text(), catalogue=catalogue_mod.load())


def _build_commands() -> dict[str, dict]:
    """The fixture's three `build` commands, refusing to be empty."""
    commands = (_fixture_data().get("groups", {}).get("build", {}).get("commands") or {})
    if not commands:
        raise ValueError(f"{FIXTURE} declares no `build` command, so the toolchain could not be read")
    return commands


def _environments() -> set[str]:
    """The env names the fixture declares - the outer token an env-first command takes."""
    names = set(_fixture_data().get("environments") or {})
    if not names:
        raise ValueError(f"{FIXTURE} declares no environment, so an env-first command could not be read")
    return names


def _pinned_version() -> str:
    """The SDK version the product pins, read off the image reference the fixture's `compile` carries."""
    image = _build_commands()["compile"]["with"]["body"]["image"]
    _repository, _, tag = image.rpartition(":")
    if not tag:
        raise ValueError(f"{FIXTURE}: `build compile` names {image!r}, which pins no version")
    return tag


# --- the chapter exists, and is placed -----------------------------------------------------------------


def test_the_chapter_is_not_empty():
    """The one that has to fail first. Every comparison below reads this file, so a deleted or blanked
    page must be a red suite rather than a page of vacuous truths."""
    # act
    body = _text()

    # assert: a real chapter, not a stub
    assert body.startswith('---\ntitle: "A .NET product, end to end"\n')
    assert len(body.splitlines()) > 100


def test_the_chapter_is_listed_on_the_section_index():
    """A page Hugo renders and nothing links to is a page nobody reads."""
    # act
    index = INDEX.read_text(encoding="utf-8")

    # assert
    assert 'card link="case-dotnet/"' in index


def test_the_chapter_renders_after_the_cases_it_is_the_third_of():
    """The three cases are one series and this is its last member, so the reader must meet it after the
    two that establish the shape. Hextra orders by `weight:`, so the check is over the front matter of
    the whole directory - and the weights must stay distinct, so the order is stated rather than left to
    a tie-break.

    WHAT si#170 RETIRED HERE, said rather than deleted. This used to compare this chapter's weight with
    `getting-started` and `releasing` as well. `weight:` orders within a SECTION, and after the site was
    divided by question those two are in `how/`, which is offered AFTER `what/` - deliberately, because
    the division shows what the loop looks like before it explains it. So "must not be offered before
    them" is no longer true of this site, and a weight comparison across two sections would be a
    number that holds for a reason nobody stated. What replaces it is the half that was always the
    point and is section-independent: the chapter POINTS at those pages instead of retelling them."""
    # arrange
    weights = {}
    for page in sorted(CHAPTER.parent.glob("*.md")):
        if page.name == "_index.md" or page in sitepages.generated_pages():
            continue
        match = re.search(r"^weight: (\d+)$", page.read_text(encoding="utf-8"), re.M)
        assert match, f"{page} declares no weight"
        weights[page.stem] = int(match.group(1))

    # assert: after the two cases it completes
    assert weights["case-dotnet"] > weights["case-java"]
    assert weights["case-dotnet"] > weights["case-python"]

    # assert: the weights are still distinct
    assert len(set(weights.values())) == len(weights)

    # assert: it points at the pages it leans on rather than retelling them
    linked = {sitepages.resolve(link) for link in sitepages.internal_links(CHAPTER)}
    for name in ("getting-started.md", "case-python.md", "case-java.md"):
        assert sitepages.chapter(name) in linked, (
            f"{CHAPTER.name} no longer links to {name}, so it either retells that page or leaves the "
            f"reader without it")


# --- the labels, which are the whole ticket ------------------------------------------------------------


def test_every_step_carries_exactly_one_of_the_three_labels():
    """The honesty rule, in the only shape a machine can hold: the vocabulary is closed.

    Nothing here can prove a `run` label true - that took running the command, and the evidence column
    says where. What it CAN prove is that no row escaped the question, which is how such a table rots: a
    step is added, nobody knows whether it was driven, and the cell gets a fourth word that means
    "unsure" without admitting it.
    """
    # arrange
    rows = _steps()

    # act
    labels = [cells[3] for cells in rows]

    # assert
    assert rows, "the honesty table has no rows, so this test is ruling on nothing"
    for cells, label in zip(rows, labels):
        assert label in LABELS, f"step {cells[0]} is labelled {label!r}, which is not one of {LABELS}"

    # assert: and it really ruled on every row
    assert len(labels) == len(rows)


def test_every_step_that_does_not_exist_yet_links_the_ticket_where_it_is_open():
    """The label that would otherwise be a shrug. "Does not exist yet" is only honest if the reader can
    go and read why - otherwise it is indistinguishable from "we forgot". This chapter leans on it four
    times, which makes the rule load-bearing here rather than decorative."""
    # arrange
    rows = [cells for cells in _steps() if cells[3] == OPEN]

    # act / assert
    assert rows, f"no step is labelled {OPEN!r}; if the loop is complete now, this test has to go"
    for cells in rows:
        assert re.search(r"https://github\.com/marcozwyssig/simplon/issues/\d+", cells[4]), (
            f"step {cells[0]} says {OPEN!r} and names no ticket: {cells[4]!r}")


def test_the_ratio_the_chapter_states_is_the_one_its_own_table_has():
    """The typed number, which is the failure this repository has produced repeatedly on this site. The
    paragraph under the table counts the labels; the table is the source, so the paragraph is computed
    from it here rather than read."""
    # arrange
    rows = _steps()
    counted = {label: sum(1 for cells in rows if cells[3] == label) for label in LABELS}

    # act
    match = re.search(r"Of the (\d+) steps above, (\d+) are \*\*run\*\*, (\d+) are \*\*derived\*\* and "
                      r"(\d+) \*\*does not exist yet\*\*", _text())

    # assert
    assert match, "the chapter states no ratio for its own table, so the count is unwatched"
    total, run, derived, missing = (int(part) for part in match.groups())
    assert total == len(rows), f"the paragraph says {total} steps, the table has {len(rows)}"
    assert run == counted["run"]
    assert derived == counted["derived"]
    assert missing == counted[OPEN]

    # assert: and the three labels account for every row, so nothing hid outside the sum
    assert run + derived + missing == len(rows)

    # assert: the chapter's argument is that a .NET product really can be driven this way, so the driven
    # steps have to outnumber the ones that were only read
    assert run > derived + missing, (
        f"{run} of {len(rows)} steps are `run`; a chapter of derivations is not a case study")


# --- the commands and coordinates it types -------------------------------------------------------------


def _typed_commands() -> list[tuple[str, ...]]:
    """Every `./dotnetdemo.sh ...` the chapter types, as its token path with the env prefix removed.

    Options and arguments are dropped: `release tag v0.1.0` names the same command as `release tag`. An
    env-first command carries its environment as the OUTER token, which is a value and not part of the
    command's name, so a leading token the fixture declares as an environment comes off here.
    """
    envs = _environments()
    found = []
    for line in re.findall(r"\./dotnetdemo\.sh ([^\n`]+)", _text()):
        tokens = [token for token in line.split() if not token.startswith("-")]
        if tokens and tokens[0] in envs:
            tokens = tokens[1:]
        if tokens:
            found.append(tuple(tokens))
    return found


def test_every_command_the_chapter_types_is_one_this_product_assembles():
    """A chapter that tells people to type a command which no longer exists is worse than one that says
    nothing: they conclude they misread the site rather than that the site is stale.

    Resolved against the tree ASSEMBLED from the fixture, not against a list of names read out of it.
    """
    # arrange
    product = _product()
    typed = _typed_commands()

    # act / assert
    assert typed, "the chapter types no command at all, so this test is ruling on nothing"
    ruled = 0
    for tokens in typed:
        group = tokens[0]
        assert group in product.groups, f"'{' '.join(tokens)}': dotnetdemo has no group '{group}'"
        assert len(tokens) > 1, f"'{' '.join(tokens)}' names a group and no command"
        assert tokens[1] in product.groups[group], (
            f"'{' '.join(tokens)}': group '{group}' has no command '{tokens[1]}' "
            f"(it has {sorted(product.groups[group])})")
        ruled += 1

    # assert: the walk really covers the loop rather than one command repeated
    assert len({tokens[:2] for tokens in typed}) >= 5
    assert ruled == len(typed)


def test_the_command_the_chapter_says_does_not_exist_really_does_not():
    """The mirror of the test above, and the one that keeps an honesty label honest. The chapter tells
    the reader that `./dotnetdemo.sh test unit` is not there - the design's own command table promises
    it, and the scaffolder writes all three commands under `build` instead. A page saying that while the
    product grew the command would be teaching a falsehood in green."""
    # arrange
    product = _product()

    # act / assert: the page says it
    assert "`test unit`" in _text(), (
        "the chapter no longer names the command the design promises and this product does not have")

    # assert: and the assembled product really has no `test` group at all
    assert "test" not in product.groups, (
        f"dotnetdemo now assembles a `test` group ({sorted(product.groups.get('test', ()))}); the "
        f"chapter's claim that the toolchain commands land under `build` has to be rewritten")


def test_every_catalogue_coordinate_the_chapter_names_exists():
    """The coordinates are the kernel's own vocabulary, and the chapter uses them to say which task
    stands behind a product's command. A coordinate that has been renamed or removed makes the sentence
    around it false without changing a word of it.

    A coordinate is recognised by its NAMESPACE being one the catalogue carries, which is what keeps an
    image reference the chapter also writes in backticks from being read as a task nobody declared.
    """
    # arrange
    catalogue = catalogue_mod.load()
    known = set(catalogue.tasks)
    namespaces = {coordinate.split(":")[0] for coordinate in known}
    assert namespaces, "the catalogue carries no task at all, so this test is ruling on nothing"
    pattern = rf"`(({'|'.join(sorted(namespaces))}):[a-z][a-z0-9-]*)`"

    # act
    named = {match[0] for match in re.findall(pattern, _prose())}

    # assert
    assert named, "the chapter names no coordinate, so this test is ruling on nothing"
    for coordinate in sorted(named):
        assert coordinate in known, f"the chapter names '{coordinate}', the catalogue does not carry it"

    # assert: and the two the chapter is ABOUT are among them, so this did not pass over a page that
    # stopped naming its own subject
    assert {"toolchain:run", "support:toolchain"} <= named


# --- the manifest it quotes, and where its contents come from -------------------------------------------


def test_every_manifest_block_the_chapter_quotes_is_the_products_own():
    """A chapter quoting a manifest it edited for the page is a transcript with one half retyped. Every
    YAML block is compared with the fixture the commands above were resolved against, verbatim, so the
    page and the product cannot describe two different declarations."""
    # arrange
    fixture = _fixture_text()
    quoted = _blocks("yaml")

    # act / assert
    ruled = 0
    for block in quoted:
        for line in block.splitlines():
            if not line.strip():
                continue
            assert line in fixture, (
                f"the chapter quotes a manifest line dotnetdemo does not have: {line!r}")
            ruled += 1

    # assert: it really compared something, and more than one block was reached
    assert len(quoted) >= 2, f"the chapter quotes {len(quoted)} manifest blocks; it walks a loop"
    assert ruled >= 10


def test_the_three_build_commands_are_the_kernels_own_dotnet_profile():
    """The load-bearing check of the whole chapter, and the reason this suite exists beside the Java one.

    The chapter's claim is that a .NET product writes NO task body for its build: it names a language and
    a version, and the argv come from the kernel. So the fixture's three `build` commands are compared
    with `PROFILES["dotnet"]` rather than read - argv, workdir and the image the version fills in. A
    profile edit that changed how a .NET product compiles turns this red, instead of leaving a chapter
    describing a build nobody would get.
    """
    # arrange
    version = _pinned_version()
    profile = profiles.profile(LANGUAGE, **{VERSION_PARAM: version})
    declared = _build_commands()

    # act / assert: the same three commands, no more and no fewer
    assert set(declared) == set(profile.commands), (
        f"dotnetdemo declares {sorted(declared)}; the kernel's {LANGUAGE} profile carries "
        f"{sorted(profile.commands)}")

    ruled = 0
    for name, expected in profile.commands.items():
        body = declared[name]["with"]["body"]
        assert body["argv"] == expected["argv"], (
            f"`build {name}` runs {body['argv']}; the profile says {expected['argv']}")
        assert body["workdir"] == expected["workdir"], (
            f"`build {name}` works in {body['workdir']!r}; the profile says {expected['workdir']!r}")
        assert body["image"] == profile.image, (
            f"`build {name}` runs in {body['image']!r}; the profile resolves to {profile.image!r}")
        ruled += 1

    # assert: it really ruled on all three, and the chapter shows the image it agreed on
    assert ruled == len(profile.commands) >= 3
    assert profile.image in _text(), (
        f"the chapter does not name the image its product runs in ({profile.image})")


def test_the_analyse_step_runs_in_the_same_image_as_the_compile_step():
    """The design's section 3 rule, which the chapter states in prose: a checker that cannot see what the
    compiler saw is analysing a program nobody builds. It is a property of the fixture, so it is read off
    the fixture rather than believed."""
    # arrange
    declared = _build_commands()

    # act
    images = {name: spec["with"]["body"]["image"] for name, spec in declared.items()}

    # assert
    assert images["analyse"] == images["compile"], (
        f"`build analyse` runs in {images['analyse']}, `build compile` in {images['compile']}")
    assert len(set(images.values())) == 1, f"the product's build spans several images: {images}"


def test_the_pinned_toolchain_image_is_one_the_gate_accepts():
    """The product picks its own toolchain reference and inherits the kernel's argument about what one
    may say. Handed to the real gate here, so a reference that stopped passing would leave the chapter
    printing a manifest that no longer runs."""
    # arrange
    image = _build_commands()["compile"]["with"]["body"]["image"]

    # act / assert
    assert docker.pinned_image(image, "build compile") == image


# --- the four refusals, which are quoted strings ---------------------------------------------------------


def test_the_pin_refusal_the_chapter_quotes_is_the_gates_own_message():
    """A quoted error text is a second source for a string, not prose. The chapter shows what the product
    gets for writing `:latest`, and the message is BUILT here - through `toolchain.declared`, so the
    toolchain's own hint is part of the comparison rather than the plain gate's wording."""
    # arrange
    quoted = [block for block in _blocks("text") if "must pin a version" in block]
    assert len(quoted) == 1, f"the chapter shows {len(quoted)} pin refusals; it argues from one"
    repository = _build_commands()["compile"]["with"]["body"]["image"].rpartition(":")[0]

    # act
    with pytest.raises(SystemExit):
        toolchain.declared({"image": f"{repository}:latest", "argv": ["dotnet", "build"]},
                           "build compile")
    with pytest.raises(ValueError) as raised:
        docker.pinned_image(f"{repository}:latest", "build compile",
                            hint="a toolchain must name its version")

    # assert: the page carries the transcript line, so its own timestamp and level prefix come off before
    # the sentence is compared - what is pinned is the message, not the clock
    shown = re.sub(r"^\[\d\d:\d\d:\d\d\]\s*ERR\s*", "", _flat(quoted[0]))
    assert shown == _flat(str(raised.value)), (
        f"the chapter quotes:\n  {shown}\nthe gate says:\n  {_flat(str(raised.value))}")


def test_the_design_shape_the_chapter_says_is_refused_now_assembles():
    """WAS `test_the_with_refusal_the_chapter_quotes_is_the_binders_own_message`, and its own docstring
    asked for this rewrite: "a kernel that started accepting the shape would turn this red rather than
    leave the chapter warning about nothing." si#105 is that kernel.

    The chapter's central correction was that the design and the scaffolder both write
    `image:`/`workdir:`/`argv:` directly under `with:`, `manifest.load` accepts it and
    `simplon.cli.assemble` then refuses it. `toolchain:run` takes the manifest's keys as its parameters
    now, so the same construction is executed and the expectation is inverted: the design's shape
    assembles. The page keeps the quoted refusal as the dated record of what dotnetdemo met, so the
    assertion below ALSO demands the note that says it is closed.
    """
    # arrange
    body = _build_commands()["compile"]["with"]["body"]
    command = {"task": "toolchain:run", "with": dict(body)}
    flat = {"product": "dotnetdemo",
            "groups": {"build": {"commands": {"compile": command}}}}
    parsed = manifest_mod.load(yaml.safe_dump(flat), catalogue=catalogue_mod.load())
    quoted = [block for block in _blocks("text") if "the impl does not take" in block]
    assert len(quoted) == 1, f"the chapter shows {len(quoted)} binder refusals; it argues from one"

    # act: the design's own section 1 block, through the binder that used to refuse it
    simplon_cli.assemble(typer.Typer(), parsed, product="dotnetdemo")

    # assert: the chapter no longer leaves that refusal standing as the present tense
    assert "Since this walk" in _flat(_text()), (
        "the chapter still shows the binder refusal with nothing saying si#105 closed it")
    assert "issues/105" in _text(), "the note that closes those rows names no ticket"


def test_the_missing_instance_refusal_the_chapter_quotes_is_the_kernels_own():
    """`toolchain:run` resolves the lab instance before it looks at whether the command declares a cache,
    so a product without an `instance:` section dies on its first toolchain command. The chapter shows
    that refusal; the sentence is built from `simplon.labinstance`'s own section name rather than
    retyped, and the fixture is checked to really carry the section that answers it."""
    # act / assert: the page quotes the message, spelled the way the kernel spells it
    assert f"is missing the '{labinstance.MANIFEST_SECTION}' section" in _text(), (
        f"the chapter does not quote the refusal for a manifest with no "
        f"'{labinstance.MANIFEST_SECTION}' section")

    # assert: and the product declares the section, with the three keys `spec()` insists on
    section = _fixture_data().get(labinstance.MANIFEST_SECTION)
    assert isinstance(section, dict), f"{FIXTURE} declares no '{labinstance.MANIFEST_SECTION}' section"
    assert set(labinstance.InstanceSpec._fields) <= set(section), (
        f"{FIXTURE}'s '{labinstance.MANIFEST_SECTION}' section is missing "
        f"{sorted(set(labinstance.InstanceSpec._fields) - set(section))}")


def test_the_scaffolder_failure_the_chapter_quotes_is_the_one_the_profile_raises():
    """`support toolchain <language>` takes one parameter, and every profile's image is a template with a
    `{version}` nothing can fill. The chapter shows the resulting KeyError; it is raised here, and by
    every language rather than only this one - which is what makes the row's claim ("it is not a .NET
    quirk") a measurement instead of an assumption."""
    # arrange
    body = _text()

    # act / assert: this chapter's own language
    with pytest.raises(KeyError) as raised:
        profiles.profile(LANGUAGE)
    assert f"KeyError: {raised.value}" in body, (
        f"the chapter does not quote the failure the scaffolder raises ({raised.value})")

    # assert: and it really is every language the kernel carries, which the page says in as many words
    ruled = 0
    for language in profiles.PROFILES:
        with pytest.raises(KeyError):
            profiles.profile(language)
        ruled += 1
    assert ruled == len(profiles.PROFILES) >= 4
    word = sitepages.number_word(len(profiles.PROFILES))
    assert f"all {word} profiles" in body, (
        f"the kernel carries {len(profiles.PROFILES)} profiles: {sorted(profiles.PROFILES)}")


# --- what the kernel assembles, and what it cannot ------------------------------------------------------


def test_the_docker_line_the_chapter_describes_is_the_one_the_kernel_assembles():
    """The chapter's `build` section says what the product gets for its four manifest lines: the pinned
    image, the tree bind-mounted at the workdir, the caller's own uid, and the argv unchanged. That is
    `toolchain.docker_argv`, which is pure, so it is assembled here rather than described from memory."""
    # arrange
    body = _build_commands()["compile"]["with"]["body"]
    cfg = toolchain.declared(body, "build compile")

    # act
    line = toolchain.docker_argv(cfg, root=Path("/home/dev/dotnetdemo"), product="dotnetdemo",
                                 instance="dev", extra=[])

    # assert: every element the chapter promises is really there
    assert line[:3] == ["docker", "run", "--rm"]
    assert docker.user_args()[0] in line, "the assembled line does not run as the calling user"
    assert f"/home/dev/dotnetdemo:{body['workdir']}" in line
    assert line[-len(body["argv"]):] == body["argv"], (
        f"the caller's argv is not the manifest's tail: {line}")
    assert body["image"] in line

    # assert: nothing this product did not declare - no cache volume, no environment
    assert not cfg.caches and not cfg.env


def test_a_toolchain_command_is_something_a_gate_can_name():
    """The chapter's `test` section rested on the opposite of this and said so - a gate took `suite:` or
    `impl:`, a `toolchain:run` command was neither, and this product's `build unit` returned an rc and
    never a verdict. si#106 added the third kind, so the section now shows the block that closes it, and
    what has to be read off the value object is that the block would load: a gate really does take a
    `command:`, which is the only thing making the section's answer more than prose."""
    # arrange
    kinds = {name for name in Gate.__dataclass_fields__ if name in ("suite", "impl", "command")}

    # act / assert
    assert kinds == {"suite", "impl", "command"}, (
        f"`Gate` accepts {sorted(kinds)}; the chapter's `test` section says a gate takes `suite:`, "
        f"`impl:` or `command:` - the third is si#106's answer and the section is written on it")
    assert "`command:`" in _text() and "`preamble:`" in _text(), (
        "the chapter no longer names the two keys that close si#106 for this product")

    # assert: and the product really declares no taxonomy, so the page is describing its own product
    assert "suites" not in _fixture_data(), (
        f"{FIXTURE} now declares a `suites:` section; the chapter says it has none")


# --- the measurements it prints -------------------------------------------------------------------------


def test_the_three_runs_agree_with_each_other_and_with_the_suite_the_chapter_shows():
    """The measurement is not derivable and nothing here pretends otherwise. What IS derivable is that
    the run table is coherent: each block's parts sum to its own total, the runs that reached the tests
    report the suite the chapter says the product has, and the run that never compiled reports none.

    The last assertion is the chapter's whole argument: two runs with completely different causes carry
    the SAME rc, because there is no gate to tell them apart. A copied-and-edited table would break that
    pairing first.
    """
    # arrange
    rows = _runs()
    tests = re.search(r"CalculatorTests\.cs\s+(\w+) \[Fact\] methods", _text())
    assert tests, "the chapter's tree listing does not say how many tests the product has"
    size = {word: number for number, word in enumerate(
        ["zero", "one", "two", "three", "four", "five", "six", "seven"])}[tests.group(1)]

    # act
    ruled = 0
    counted: list[dict[str, int]] = []
    for cells in rows:
        found = re.findall(r"(Failed|Passed|Skipped|Total):\s*(\d+)", cells[2])
        if not found:
            assert "no test ran" in cells[2].lower(), (
                f"the '{cells[0]}' run reports neither a count nor 'no test ran': {cells[2]!r}")
            counted.append({})
            ruled += 1
            continue
        block = {key: int(value) for key, value in found}
        assert block["Failed"] + block["Passed"] + block["Skipped"] == block["Total"], (
            f"the '{cells[0]}' run's parts do not sum to its own total: {block}")
        assert block["Total"] == size, (
            f"the '{cells[0]}' run reports {block['Total']} tests; the product has {size}")
        counted.append(block)
        ruled += 1

    # assert: it ruled on every row, and there really are three
    assert ruled == len(rows) >= 3

    # assert: one green, one red, one that never got as far as a test
    assert any(block.get("Failed") == 0 and block.get("Passed") == size for block in counted)
    assert any(block.get("Failed", 0) > 0 for block in counted), (
        "no run in the table reports a failing test, so the chapter never shows a red xUnit test "
        "arriving red")
    assert {} in counted, (
        "no run in the table failed before the tests, which is the pair the chapter is about")

    # assert: and the two runs that failed did so with the same rc, which is the point of the section
    reds = {cells[1] for cells, block in zip(rows, counted)
            if block.get("Failed", 0) > 0 or block == {}}
    assert len(reds) == 1, (
        f"the chapter's two failing runs report rcs {sorted(reds)}; its argument is that they are "
        f"indistinguishable to the kernel")


# --- the counts it takes from somewhere else ------------------------------------------------------------


def test_the_scaffold_count_the_chapter_states_is_the_one_simplon_init_writes():
    """The first row of the honesty table says how much Python `simplon init` puts in a product, and the
    tree listing adds the one module this one wrote. Both numbers are read off `bootstrap.render`, which
    IS the scaffold - so a template gaining a module turns this red instead of leaving a chapter whose
    opening claim quietly stopped being true."""
    # arrange
    scaffolded = [name for name in bootstrap.render("dotnetdemo") if name.endswith(".py")]
    body = _text()

    # act / assert: what the scaffold writes
    assert scaffolded, "the scaffold writes no Python at all, so this test is ruling on nothing"
    word = sitepages.number_word(len(scaffolded))
    assert f"{word} Python files" in body, (
        f"`simplon init` writes {len(scaffolded)} Python files: {sorted(scaffolded)}")

    # assert: and the tree listing's arithmetic - the product's own on top of them
    listing = re.search(r"orchestrator/src/python/orchestrator/\s+(\w+) \.py files - (\w+) scaffolded, "
                        r"(\w+) written here", body)
    assert listing, "the chapter's tree listing does not break its Python file count down"
    total, base, own = listing.groups()
    numbers = {sitepages.number_word(n): n for n in range(0, 100)}
    assert numbers[base] == len(scaffolded), (
        f"the listing says {base} scaffolded; `simplon init` writes {len(scaffolded)}")
    assert numbers[total] == numbers[base] + numbers[own], (
        f"the listing says {total} = {base} + {own}, which does not add up")


def test_the_empty_ribs_count_the_chapter_names_is_the_catalogues_own():
    """`deploy` is one of the groups the catalogue draws empty, and the chapter says how many there are
    while pointing at the page that owns the argument. A pointer carrying a stale number sends the reader
    looking for something that is not there."""
    # arrange
    catalogue = catalogue_mod.load()
    empty = {group for group in catalogue.groups
             if not any(coordinate.startswith(f"{group}:") for coordinate in catalogue.tasks)}

    # act / assert
    assert empty, "the catalogue draws no group empty, so this test is ruling on nothing"
    word = sitepages.number_word(len(empty))
    assert f"one of the {word} ribs" in _text(), (
        f"the catalogue draws {len(empty)} groups empty: {sorted(empty)}")

    # assert: and `deploy` - the rib this chapter's own section is about - is really one of them
    assert "deploy" in empty


# --- the chapter's own design ---------------------------------------------------------------------------


def test_the_chapter_defers_rather_than_retelling_the_two_before_it():
    """Its whole design is to be the THIRD case: the same five verbs with a toolchain the product does
    not write a body for, leaning on the pages that own each detail instead of restating them."""
    # act
    links = set(re.findall(r"\]\((\.\.?/[^)]*)\)", _text()))

    # assert: it really points somewhere, and at several different places
    assert len(links) >= 5, f"the chapter points at {len(links)} pages; its whole design is deferring"

    # assert: and it points at both siblings, which is the pairing the series depends on
    assert any(link.startswith("../case-java/") for link in links), (
        "the chapter never links the Java case it is the counterpart to")
    assert any(link.startswith("../case-python/") for link in links), (
        "the chapter never links the Python case the series opens with")

    # assert: it does NOT restate the five-outcome table `case-python.md` owns - and it has no business
    # printing one at all, since this product reaches no verdict
    assert "| outcome |" not in _text(), (
        "the chapter reprints the gate outcome table; `case-python.md` owns it and this page links it")
