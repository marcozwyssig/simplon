"""The C++ use case chapter, held against the things it claims (si#108).

WHY A TEST AND NOT PROOFREADING. `site/content/using/case-cpp.md` walks one delivery loop with a product
that writes no build body at all: four commands, one catalogue coordinate, one pinned image. Everything
load-bearing on that page is a fact stated twice - the argv the kernel's C++ profile carries, the command
names the product's manifest assembles, the docker line `toolchain.docker_argv` builds, the refusals the loader
and the image gate raise word for word, and a table of its own rows. The Java and Python chapters already
measured what an unwatched copy does, five times over; this suite is the same construction for the third
case.

WHAT IS DIFFERENT HERE FROM `test_case_java_chapter.py`, beyond the product. The Java chapter's product
hand-writes `impl: orchestrator.gradle:build`, so its suite pins a task body. This one's product declares
nothing but data, so the pins go one level deeper: the four `with:` blocks in the fixture are compared
with `simplon.tasks.profiles.PROFILES["cpp"]` ENTRY BY ENTRY. That is the chapter's whole argument - "the
product runs the kernel's ready-made configuration, unedited" - and it is the sentence a hand-tuned
fixture would break first.

WHAT THE CHAPTER PROMISES ITS READER, and therefore what has to be held:

  * THE LABELS. `run`, `derived`, `does not exist yet`, nothing else, and a step that does not exist has
    to carry the ticket where the decision is open. The page's own ratio sentence is computed from the
    table it summarises.
  * THE COMMANDS AND COORDINATES. Resolved against the tree ASSEMBLED from
    `tests/fixtures/case_cpp_manifest.yaml` by the same loader a real product goes through - the manifest
    the transcripts were produced with, travelling with the chapter because cppdemo is not in this
    repository.
  * THE MANIFEST IT QUOTES. Every YAML block on the page is a verbatim part of that fixture.
  * THE PROFILE. The four commands, their argv and the pinned image, read out of the kernel's own table.
  * THE REFUSALS. Four quoted messages - the missing profile parameter, the assembly refusal that makes
    the scaffolded form unusable, the image pin gate, and clang-tidy's own - and the first three are
    BUILT here from the code that raises them rather than remembered.
  * THE DOCKER LINE. Assembled by `toolchain.docker_argv` from the fixture's own `with:` block.
  * THE THREE RUNS. Nothing here can prove a measurement and nothing tries. What it CAN prove is that the
    three rows are arithmetically coherent with ctest's own summary line, that they agree with the suite
    size the chapter states one screen higher, and that one of them is the run where a tree that does not
    compile still reports every test passing - which is the property si#106 is about and the one a
    copied-and-edited table would break first.

WHAT IS NOT CHECKED, said rather than left as a silence. The prose. The transcripts, which are dated
evidence from one machine on one day and are deliberately never a live claim. And the links, which are
`test_site_links.py`'s: it walks EVERY page with `sitepages`, so this chapter is inside its population
already, and a second walker here would be the drifting copy this repository spends its time deleting.

RED WHEN THERE IS NOTHING. Every helper raises rather than returning an empty result, and every count
assertion is paired with the population it ruled on.

AAA throughout.
"""
from __future__ import annotations

import dataclasses
import re

import pytest
import typer
import yaml

from simplon import bootstrap, cli as cli_mod
from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod
from simplon.tasks import profiles, toolchain
from simplon.tasks.testrun import Gate

import sitepages
from conftest import ROOT

#: The chapter under test.
CHAPTER = ROOT / "site" / "content" / "using" / "case-cpp.md"

#: The card list this half of the site renders, and the place the chapter has to appear in.
INDEX = ROOT / "site" / "content" / "using" / "_index.md"

#: The manifest of the product the chapter follows. cppdemo is not in this repository - it is a C++
#: product driven for si#108 - so it travels with the chapter, and every command the page types is
#: resolved against the tree this file assembles.
FIXTURE = ROOT / "tests" / "fixtures" / "case_cpp_manifest.yaml"

#: The closed vocabulary of honesty labels - the same three the other two cases carry, deliberately, so a
#: reader moving between them is reading one scale and not three.
LABELS = ("run", "derived", "does not exist yet")

#: The label whose rows owe the reader a ticket.
OPEN = "does not exist yet"

#: The language this chapter is about, as the profile table spells it.
LANGUAGE = "cpp"

#: The compiler version cppdemo declares. Read back off the fixture below rather than trusted - it is
#: here only so the profile can be resolved the way the product resolved it.
VERSION = "19"


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
    """Every fenced block of one language, refusing to be empty.

    A chapter that lost its YAML would otherwise make the "the manifest it quotes is the product's own"
    assertion pass over nothing at all.
    """
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
    """The three-run table: [run, compile rc, unit rc, ctest's own summary line] per row."""
    return _rows("| run | `build compile` |")


def _product():
    """The cppdemo command tree, assembled from the fixture by the loader a real product goes through."""
    return manifest_mod.load(FIXTURE.read_text(encoding="utf-8"), catalogue=catalogue_mod.load())


def _raw() -> dict:
    """The fixture as data - what the product declares, before any command tree is built from it."""
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    if not data:
        raise ValueError(f"{FIXTURE} parses to nothing, so nothing could be read from it")
    return data


def _bodies() -> dict[str, dict]:
    """The `with: body:` block of every build command the fixture declares, by command name."""
    commands = _raw()["groups"]["build"]["commands"]
    found = {name: spec["with"]["body"] for name, spec in commands.items()}
    if not found:
        raise ValueError(f"{FIXTURE} declares no build command, so nothing could be compared")
    return found


def _environments() -> set[str]:
    """The env names the fixture declares - the outer token an env-first command takes."""
    names = set(_raw().get("environments") or {})
    if not names:
        raise ValueError(f"{FIXTURE} declares no environment, so an env-first command could not be read")
    return names


def _profile() -> profiles.Profile:
    """The kernel's C++ profile, resolved with the version the FIXTURE declares - so a product that moved
    to clang 20 moves this comparison with it instead of breaking it."""
    declared = {body["image"].rpartition(":")[2] for body in _bodies().values()}
    if len(declared) != 1:
        raise ValueError(f"{FIXTURE} pins {sorted(declared)}; the chapter argues from one toolchain")
    return profiles.profile(LANGUAGE, version=declared.pop())


# --- the chapter exists, and is placed -----------------------------------------------------------------


def test_the_chapter_is_not_empty():
    """The one that has to fail first. Every comparison below reads this file, so a deleted or blanked
    page must be a red suite rather than a page of vacuous truths."""
    # act
    body = _text()

    # assert: a real chapter, not a stub
    assert body.startswith('---\ntitle: "A C++ product, end to end"\n')
    assert len(body.splitlines()) > 100


def test_the_chapter_is_listed_on_the_section_index():
    """A page Hugo renders and nothing links to is a page nobody reads."""
    # act
    index = INDEX.read_text(encoding="utf-8")

    # assert
    assert 'card link="case-cpp/"' in index


def test_the_chapter_renders_after_the_two_cases_it_leans_on():
    """It is the THIRD case and says so: it defers the loop to the Python chapter and the before/after to
    the Java one, so a reader must meet it after both. Hextra orders by `weight:`, so the check is over
    the front matter of the whole directory.

    The relation to its siblings is stated as an ORDER rather than as `java + 1`: a fourth case chapter
    landing between them is a legitimate edit, and a suite that had to be rewritten for it would teach
    people to rewrite it without reading it. What must hold is that nothing which is NOT a case chapter
    is filed between two that are.
    """
    # arrange
    weights = {}
    for page in sorted(CHAPTER.parent.glob("*.md")):
        if page.name in ("_index.md", "commands.md"):
            continue
        match = re.search(r"^weight: (\d+)$", page.read_text(encoding="utf-8"), re.M)
        assert match, f"{page} declares no weight"
        weights[page.stem] = int(match.group(1))

    # assert: after the pages it defers to
    assert weights["case-cpp"] > weights["getting-started"]
    assert weights["case-cpp"] > weights["examples"]
    assert weights["case-cpp"] > weights["case-python"]
    assert weights["case-cpp"] > weights["case-java"]

    # assert: the case chapters are one block, with nothing else wedged between them
    cases = {stem: weight for stem, weight in weights.items() if stem.startswith("case-")}
    between = [stem for stem, weight in weights.items()
               if stem not in cases and min(cases.values()) < weight < max(cases.values())]
    assert not between, f"{between} sit between the case chapters, which are meant to read as one block"

    # assert: the weights are still distinct, so the order is stated rather than left to a tie-break
    assert len(set(weights.values())) == len(weights)


# --- the labels, which are the whole ticket ------------------------------------------------------------


def test_every_step_carries_exactly_one_of_the_three_labels():
    """The honesty rule, in the only shape a machine can hold: the vocabulary is closed.

    Nothing here can prove a `run` label true - that took running the command, and the evidence column
    says where. What it CAN prove is that no row escaped the question, which is how such a table rots: a
    step is added, nobody knows whether it was driven, and the cell gets a fourth word that means "unsure"
    without admitting it.
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
    """The label that would otherwise be a shrug. "Does not exist yet" is only honest if the reader can go
    and read why - otherwise it is indistinguishable from "we forgot". This chapter has more such rows
    than either of its siblings, which makes the rule matter more here rather than less."""
    # arrange
    rows = [cells for cells in _steps() if cells[3] == OPEN]

    # act / assert
    assert rows, f"no step is labelled {OPEN!r}; if the loop is complete now, this test has to go"
    for cells in rows:
        assert re.search(r"https://github\.com/marcozwyssig/simplon/issues/\d+", cells[4]), (
            f"step {cells[0]} says {OPEN!r} and names no ticket: {cells[4]!r}")


def test_the_ratio_the_chapter_states_is_the_one_its_own_table_has():
    """The typed number, which is the failure this repository has now produced five times on this site.
    The paragraph under the table counts the labels; the table is the source, so the paragraph is computed
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

    # assert: the chapter's argument is that a C++ toolchain really runs on this kernel, so most of the
    # table has to be driven. A page that had quietly become mostly derivation would still pass every
    # check above.
    assert run > derived + missing, (
        f"{run} of {len(rows)} steps are `run`; a chapter of derivations is not evidence")


# --- the commands and coordinates it types -------------------------------------------------------------


def _typed_commands() -> list[tuple[str, ...]]:
    """Every `./cppdemo.sh ...` the chapter types, as its token path with the env prefix removed.

    Options and arguments are dropped: `release tag v0.1.0` names the same command as `release tag`. An
    env-first command carries its environment as the OUTER token (`./cppdemo.sh dev deploy up`), which is
    a value and not part of the command's name, so a leading token the fixture declares as an environment
    comes off here.
    """
    envs = _environments()
    found = []
    for line in re.findall(r"\./cppdemo\.sh ([^\n`]+)", _text()):
        tokens = [token for token in line.split() if not token.startswith("-")]
        if tokens and tokens[0] in envs:
            tokens = tokens[1:]
        if tokens:
            found.append(tuple(tokens))
    return found


def test_every_command_the_chapter_types_is_one_this_product_assembles():
    """A chapter that tells people to type a command which no longer exists is worse than one that says
    nothing: they conclude they misread the site rather than that the site is stale.

    Resolved against the tree ASSEMBLED from the fixture, not against a list of names read out of it - so
    a kernel change that breaks the load path for a product whose every command is a catalogue coordinate
    turns this red, which is the exact shape this chapter is about.
    """
    # arrange
    product = _product()
    typed = _typed_commands()

    # act / assert
    assert typed, "the chapter types no command at all, so this test is ruling on nothing"
    ruled = 0
    for tokens in typed:
        group = tokens[0]
        assert group in product.groups, f"'{' '.join(tokens)}': cppdemo has no group '{group}'"
        assert len(tokens) > 1, f"'{' '.join(tokens)}' names a group and no command"
        assert tokens[1] in product.groups[group], (
            f"'{' '.join(tokens)}': group '{group}' has no command '{tokens[1]}' "
            f"(it has {sorted(product.groups[group])})")
        ruled += 1

    # assert: the walk really covers the loop rather than one command repeated
    assert len({tokens[:2] for tokens in typed}) >= 5
    assert ruled == len(typed)


def test_every_catalogue_coordinate_the_chapter_names_exists():
    """The coordinates are the kernel's own vocabulary, and the chapter uses them to say which task stands
    behind a product's command. A coordinate that has been renamed or removed makes the sentence around it
    false without changing a word of it.

    A coordinate is recognised by its NAMESPACE being one the catalogue carries, which keeps an image
    reference the chapter also writes in backticks - `silkeh/clang:19` - from being read as a task nobody
    declared.
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

    # assert: and the two the whole chapter rests on are among them
    assert {"toolchain:run", "support:toolchain"} <= named


# --- the manifest it quotes, and the profile behind it -------------------------------------------------


def test_every_manifest_block_the_chapter_quotes_is_the_products_own():
    """A chapter quoting a manifest it edited for the page is a transcript with one half retyped. Every
    YAML block is compared with the fixture the commands above were resolved against, verbatim, so the
    page and the product cannot describe two different declarations."""
    # arrange
    fixture = FIXTURE.read_text(encoding="utf-8")
    quoted = _blocks("yaml")

    # act / assert
    ruled = 0
    for block in quoted:
        for line in block.splitlines():
            if not line.strip():
                continue
            assert line in fixture, f"the chapter quotes a manifest line cppdemo does not have: {line!r}"
            ruled += 1

    # assert: it really compared something, and several blocks were reached
    assert len(quoted) >= 2, f"the chapter quotes {len(quoted)} manifest blocks; it walks a loop"
    assert ruled >= 20


def test_the_four_commands_the_chapter_counts_are_the_kernels_own_profile():
    """THE CLAIM THE WHOLE CHAPTER RESTS ON: cppdemo runs the kernel's ready-made C++ configuration, and
    edited none of it. So the fixture's four bodies are compared with `profiles.PROFILES['cpp']` entry by
    entry - the image, the workdir and the argv - rather than eyeballed, and the page's own count of them
    is computed from the same table.

    A hand-tuned fixture is exactly what would make the chapter's argument false while every transcript on
    it stayed true, and it is the first thing this comparison catches.
    """
    # arrange
    profile = _profile()
    bodies = _bodies()

    # act / assert
    ruled = 0
    for name, declared in profile.commands.items():
        assert name in bodies, f"the profile carries '{name}'; cppdemo declares {sorted(bodies)}"
        assert bodies[name]["argv"] == declared["argv"], (
            f"cppdemo's '{name}' runs {bodies[name]['argv']}, the profile says {declared['argv']}")
        assert bodies[name]["workdir"] == declared["workdir"]
        assert bodies[name]["image"] == profile.image, (
            f"cppdemo's '{name}' names {bodies[name]['image']!r}, the profile resolves {profile.image!r}")
        ruled += 1

    # assert: and the chapter says how many there are, spelled the way this site spells counts
    word = sitepages.number_word(ruled)
    assert f"{word} commands" in _text(), (
        f"the C++ profile carries {ruled} commands ({', '.join(profile.commands)}); the chapter does not "
        f"say '{word} commands'")
    assert ruled == len(profile.commands) >= 4


def test_the_languages_the_chapter_says_the_kernel_carries_are_the_ones_in_the_table():
    """The page places C++ among the profiles beside it. The list is the kernel's table, so it is read off
    `PROFILES` rather than typed - a fifth language would otherwise leave the sentence quietly wrong."""
    # arrange
    known = sorted(profiles.PROFILES)
    body = _text()

    # act / assert
    assert known, "the kernel carries no profile at all, so this test is ruling on nothing"
    word = sitepages.number_word(len(known))
    assert f"{word} profiles" in body, (
        f"the kernel carries {len(known)} profiles ({', '.join(known)}); the chapter does not say "
        f"'{word} profiles'")
    for language in known:
        assert f"`{language}`" in body, f"the chapter names no profile '{language}'"


def test_the_block_the_chapter_shows_the_scaffolder_writing_is_the_one_it_writes(tmp_path, monkeypatch):
    """The before half of the chapter's before/after, and it is quoted OUTPUT rather than prose: the page
    shows the block `support:toolchain` puts into a manifest, and says it does not assemble.

    Produced here by running the scaffolder into a throwaway manifest, so the day si#105 changes the shape
    it writes, the page that shows the old one goes red instead of describing a defect nobody has any
    more.
    """
    # arrange
    manifest = tmp_path / "cppdemo.yaml"
    manifest.write_text("product: cppdemo\ngroups:\n  build:\n    commands: {}\n", encoding="utf-8")
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: manifest)
    quoted = [block for block in _blocks("text") if "task: toolchain:run" in block]

    # act
    toolchain.scaffold(LANGUAGE, version=VERSION)
    written = manifest.read_text(encoding="utf-8")

    # assert
    assert len(quoted) == 1, (
        f"the chapter shows {len(quoted)} scaffolded manifest blocks; its before/after rests on one")
    assert quoted[0] in written, (
        f"the chapter shows:\n{quoted[0]}\nthe scaffolder writes:\n{written}")

    # assert: and it is really the flat shape - the one whose absence of `body:` is the whole point
    assert "body:" not in quoted[0]


# --- the refusals, which are quoted strings ------------------------------------------------------------


def test_the_missing_profile_parameter_the_chapter_shows_is_the_one_the_profile_raises():
    """`./cppdemo.sh support toolchain cpp` ends in a traceback rather than a diagnosis, and the chapter
    quotes its last line. Raised here rather than remembered, so the day si#105 is fixed - or the day the
    refusal becomes a `log.die` - this goes red with the page still promising a KeyError."""
    # arrange
    body = _flat(_text())

    # act
    with pytest.raises(KeyError) as raised:
        profiles.profile(LANGUAGE)

    # assert
    missing = raised.value.args[0]
    assert f"KeyError: {missing!r}" in body, (
        f"the chapter does not quote the profile's own failure: KeyError: {missing!r}")

    # assert: and it really is the version, which is what makes the command unusable rather than merely
    # noisy - the image template cannot be resolved without it
    assert missing == "version"


def test_the_scaffolded_manifest_now_assembles_and_the_chapter_says_so(tmp_path, monkeypatch):
    """WAS `test_the_assembly_refusal_the_chapter_quotes_is_the_loaders_own`, and the rewrite is the
    point rather than the maintenance (si#105).

    The refusal this used to build - the manifest the scaffolder writes LOADS and does not ASSEMBLE - was
    the load-bearing defect on the page, and si#105 fixed it by making `toolchain:run` take the
    manifest's keys as its parameters. So the same end-to-end construction stands (scaffold, load,
    assemble) and the expectation is inverted: nothing raises. The page keeps the quoted refusal as the
    dated record of what cppdemo met, which is why the assertion below ALSO demands the note that says it
    is closed - a page carrying only the old message would read as a live warning about nothing.
    """
    # arrange
    manifest = tmp_path / "cppdemo.yaml"
    manifest.write_text("product: cppdemo\ngroups:\n  build:\n    commands: {}\n", encoding="utf-8")
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: manifest)
    toolchain.scaffold(LANGUAGE, version=VERSION)
    parsed = manifest_mod.load(manifest.read_text(encoding="utf-8"), catalogue=catalogue_mod.load())

    # act: the shape the scaffolder writes, through the binder that used to refuse it
    cli_mod.assemble(typer.Typer(), parsed, product="cppdemo")

    # assert: the chapter no longer leaves that refusal standing as the present tense
    assert "Since this walk" in _flat(_text()), (
        "the chapter still shows the assembly refusal with nothing saying si#105 closed it")
    assert "issues/105" in _text(), "the note that closes those rows names no ticket"


def test_the_pin_refusal_the_chapter_quotes_is_the_gates_own_message(monkeypatch):
    """A quoted error text is a second source for a string, not prose. The chapter shows what cppdemo gets
    for writing `silkeh/clang:latest`, and the message is built here through the toolchain's own gate -
    including its hint, which is the half a `docker.pinned_image` call written here would have missed."""
    # arrange
    said: list[str] = []
    monkeypatch.setattr(toolchain.log, "die", lambda message, *a, **k: said.append(str(message)))
    unpinned = re.search(r"`(silkeh/clang:latest)`", _text())
    assert unpinned, "the chapter shows no unpinned reference, so there is nothing to refuse"

    # act
    with pytest.raises(SystemExit):
        toolchain.declared({"image": unpinned.group(1), "argv": ["cmake"]}, "build configure")

    # assert
    assert len(said) == 1, f"the gate said {said}; the chapter argues from one refusal"
    assert _flat(said[0]) in _flat(_text()), (
        f"the chapter quotes something other than:\n  {said[0]}")

    # assert: the message really carries the PRODUCT's command as the `where`, which is what makes it
    # actionable rather than a complaint about an image somewhere
    assert "build configure" in said[0]


def test_the_docker_line_the_chapter_shows_is_the_one_the_kernel_assembles():
    """The page prints the container line one command becomes, and it is the kernel's assembly rather than
    a hand-written illustration: image, mount, workdir, `--user` and the profile's argv, in that order.

    The uid/gid pair is normalised on both sides. It is the ONE part of that line that is a fact about the
    machine the transcript was taken on rather than about the product, and a suite that compared it
    literally would be red on every host but one - which is a checker reporting whose laptop ran it.
    """
    # arrange
    body = _bodies()["compile"]
    root = re.search(r"-v (\S+):/src", _text())
    assert root, "the chapter prints no docker line to compare"

    # act
    line = " ".join(toolchain.docker_argv(toolchain.declared(body, "build compile"),
                                          root=root.group(1), product="cppdemo", instance="dev",
                                          extra=[]))

    # assert
    generic = re.sub(r"--user \d+:\d+", "--user <uid>:<gid>", line)
    shown = [re.sub(r"--user \d+:\d+", "--user <uid>:<gid>", block.strip())
             for block in _blocks("text") if "docker run" in block]
    assert any(generic in candidate for candidate in shown), (
        f"the kernel assembles:\n  {generic}\nthe chapter shows:\n  " + "\n  ".join(shown))

    # assert: and the line really carries the two things the design promises every product - the pinned
    # image and the calling user
    assert body["image"] in line
    assert "--user" in line


# --- the three runs ------------------------------------------------------------------------------------


def test_the_three_runs_agree_with_each_other_and_with_the_suite_the_chapter_shows():
    """The measurement is not derivable and nothing here pretends otherwise. What IS derivable is that the
    three rows are coherent: ctest's own summary line has to add up, the totals have to be the suite the
    chapter says the product has, and the pairs of exit codes have to say the thing the section is about.

    The row that matters most is the last one - a `build compile` that failed and a `build unit` that then
    reported every test passing. That is si#106's consequence in one line, and it is exactly the row a
    copied-and-edited table would soften first.
    """
    # arrange
    rows = _runs()
    cases = re.search(r"tests/calculator_test\.cpp\s+(\w+) ctest cases", _text())
    assert cases, "the chapter's tree listing does not say how many test cases the product has"
    size = {sitepages.number_word(n): n for n in range(0, 100)}[cases.group(1)]

    # act / assert
    ruled, stale = 0, 0
    for cells in rows:
        compile_rc, unit_rc = int(cells[1].strip("`")), int(cells[2].strip("`"))
        summary = re.search(r"(\d+)% tests passed, (\d+) tests failed out of (\d+)", cells[3])
        assert summary, f"the '{cells[0]}' run quotes no ctest summary line: {cells[3]!r}"
        percent, failed, total = (int(part) for part in summary.groups())

        # assert: ctest's own line adds up, and over the suite the chapter says the product has
        assert total == size, f"the '{cells[0]}' run reports {total} cases; the product has {size}"
        assert percent == round(100 * (total - failed) / total), (
            f"the '{cells[0]}' run says {percent}% with {failed} of {total} failed")

        # assert: and the exit code agrees with the line above it
        assert (unit_rc == 0) == (failed == 0), (
            f"the '{cells[0]}' run exits {unit_rc} with {failed} failing tests")
        if compile_rc != 0 and unit_rc == 0:
            stale += 1
        ruled += 1

    # assert: the table is a distinction rather than a constant, and it carries the row the section exists
    # for - a tree that does not compile reporting a full green suite
    assert ruled == len(rows) >= 3
    assert {int(cells[2].strip("`")) == 0 for cells in rows} == {True, False}
    assert stale == 1, (
        "no row pairs a failed compile with a green test run, so the chapter never shows the answer "
        "si#106 is about")


def test_the_gate_keys_the_chapter_names_are_the_ones_a_gate_really_takes():
    """The `test` section used to make a NEGATIVE claim - a gate can name a suite or an impl, and there
    is no key for a COMMAND, so a `toolchain:run` build has no way into a verdict - and it was read off
    the value object precisely because such a claim rots the moment somebody adds the key. si#106 added
    it, the section now shows the answer instead of the gap, and this holds the same join the other way
    round: every key the section's yaml block spells is a key a gate really takes."""
    # arrange
    keys = {field.name for field in dataclasses.fields(Gate)}
    body = _text()

    # act / assert
    assert keys, "the gate declares no field at all, so this test is ruling on nothing"
    for key in ("suite", "impl", "command", "preamble"):
        assert key in keys, f"a gate no longer takes '{key}'; the chapter's section rests on it"
    # The three the section itself spells: the Java answer it compares against, and the two this
    # product's answer is made of. `suite:` is held above as a field only - the section names pytest
    # nowhere, and demanding the word would be this file writing the chapter.
    for key in ("impl", "command", "preamble"):
        assert f"`{key}:`" in body, f"the chapter does not name the '{key}:' key a gate takes"


# --- the counts it takes from somewhere else -----------------------------------------------------------


def test_the_scaffold_count_the_chapter_states_is_the_one_simplon_init_writes():
    """The tree listing says how much Python is in a C++ product, and the answer is the chapter's second
    punchline: all of it is the scaffold's, and none of it is a build body. Both numbers are read off
    `bootstrap.render`, which IS the scaffold, so a template gaining a module turns this red instead of
    leaving the opening claim quietly false."""
    # arrange
    scaffolded = [name for name in bootstrap.render("cppdemo") if name.endswith(".py")]
    body = _text()

    # act / assert
    assert scaffolded, "the scaffold writes no Python at all, so this test is ruling on nothing"
    listing = re.search(r"orchestrator/src/python/orchestrator/\s+(\w+) \.py files - (\w+) scaffolded, "
                        r"(\w+) written here", body)
    assert listing, "the chapter's tree listing does not break its Python file count down"
    total, base, own = listing.groups()
    numbers = {sitepages.number_word(n): n for n in range(0, 100)}
    assert numbers[base] == len(scaffolded), (
        f"the listing says {base} scaffolded; `simplon init` writes {len(scaffolded)}")
    assert numbers[total] == numbers[base] + numbers[own], (
        f"the listing says {total} = {base} + {own}, which does not add up")

    # assert: and the number that makes this chapter different from the Java one is really zero
    assert numbers[own] == 0, (
        "the chapter's product wrote a body of its own; the whole before/after is that it does not")


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
    """Its whole design is to be the THIRD case: the same loop with a toolchain the product declares
    rather than writes, leaning on the pages that own each detail instead of restating them. Both things
    are checked because Hugo would render either failure silently.

    (The links themselves are `test_site_links.py`'s, which walks every page there is - this chapter is
    inside that population already, and a second walker here would be the drifting copy.)
    """
    # act
    links = set(re.findall(r"\]\((\.\.?/[^)]*)\)", _text()))

    # assert: it really points somewhere, and at several different places
    assert len(links) >= 5, f"the chapter points at {len(links)} pages; its whole design is deferring"

    # assert: and at both siblings, which is what makes the three a series rather than three pages
    assert any(link.startswith("../case-java/") for link in links), (
        "the chapter never links the Java case it is the before/after of")
    assert any(link.startswith("../case-python/") for link in links), (
        "the chapter never links the Python case that owns the loop")

    # assert: it does NOT restate the five-outcome table `case-python.md` owns - a second copy of that
    # table is precisely the second source si#66 keeps finding on this site
    assert "| outcome |" not in _text(), (
        "the chapter reprints the gate outcome table; `case-python.md` owns it and this page links it")
