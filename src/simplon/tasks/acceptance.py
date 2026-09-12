"""Write a product's acceptance document as Markdown, read off the `.feature` files a runner executes
(si#204).

WHAT IS DERIVABLE IS GENERATED, and this is that rule one level over from `simplon.tasks.cliref`. That
module writes the command reference off the ASSEMBLED application, and the home page calls the result "a
reference that cannot go stale" because it lists what can be TYPED rather than what was intended. This
one lists what is VERIFIED rather than what somebody remembered writing a test for. The failure it rules
out is the same and it is silent in the same way: a hand-maintained list of acceptance tests loses a
scenario and nothing anywhere goes red.

THE MECHANISM IS DELIBERATELY cliref's, NOT A SECOND ONE. Same split - a reader that produces a data
model, a `render` that turns the model into Markdown with Hugo front matter, a task body that writes the
file and logs one line - same `validate_relative_dir` on the output path, same generated-do-not-edit
banner, same `_yaml` quoting of a manifest-supplied title. si#204 asked whether the two are nearly the
same before anything was designed; they are, so nothing new was invented for the second one.

The ONE difference is the source, and it has a consequence worth stating. cliref reads a LIVE object -
`click.get_current_context()` - so it can only run inside an invocation. This reads FILES, so `features()`
is callable from anywhere. That is not a nicety: si#205 puts a person through the same scenarios, and its
runner needs the same list outside a docs build. One reader, two consumers, which is si#197's "one source,
two modes" carried into the document.

NO GHERKIN DEPENDENCY, and the reason is agreement rather than thrift. si#142 records why this kernel
declares none lightly, and si#197 says a parser in `simplon`'s own dependencies is very likely the wrong
answer. The stronger reason is what this page is FOR: it is evidence, and evidence is worthless if the
document and the runner disagree about what a file says. `gherkin-official` parses a grammar wider than
pytest-bdd executes - `Rule:`, localised keywords - so importing it would give the kernel a DEEPER answer
than the runner's, and every construct in the gap would appear on the page and never run. So the reader
below is a keyword-prefix scan over the constructs pytest-bdd 8 actually executes, and it REFUSES the ones
it does not (`Rule:`, a non-English `# language:` header) instead of describing them.

MEASURED, ON 2026-09-12, AND THE FORMAT IS THE MEASUREMENT. si#204 says the format is what si#205 will be
built against, so it was driven rather than chosen: pytest 9.1.1 / pytest-bdd 8.1.0 / allure-pytest-bdd
2.16.0, over feature files carrying a `Background:`, a `Scenario:`, a `Scenario Outline:` with two
`Examples:` rows, a docstring payload and a table payload. What the Allure result actually carried:

  * `fullName` is `<feature file>:<scenario>` - the feature path as pytest sees it, one colon, the
    scenario title. `features/reference.feature:Every command the CLI offers is on the page`;
  * a SCENARIO OUTLINE becomes ONE RESULT PER EXAMPLES ROW, and both `name` and `fullName` carry the
    placeholders SUBSTITUTED: `A gate named unit reports green`, not `A gate named <level> reports
    <verdict>`. The outline's own title appears nowhere in the archive;
  * BACKGROUND STEPS ARE PREPENDED to every scenario's step list, each with the keyword it was written
    with: `['Given a product', 'And a manifest', 'When the gate unit runs', ...]`;
  * a step's name is exactly `<Keyword> <text>` and carries NEITHER its docstring nor its table;
  * the `Feature:` line becomes a `feature` label, and feature-level and scenario-level tags flatten into
    one list of `tag` labels with the `@` dropped.

Three of those five decide this page and none of them is guessable, which is why they were driven:

  * THE ADDRESS ON THE PAGE IS `<feature file>:<scenario>`, because that string already exists in the
    archive. Inventing a second identifier would mean si#205's human verdict and si#133's Allure result
    could not be joined at all - two records of the same scenario with no key between them. The first
    version of this module got the left half WRONG and the second run of the measurement caught it: the
    path is NOT relative to the product root, it is `basename(features base dir)/<path under it>`
    (`pytest_bdd.parser.FeatureParser.rel_filename`), so `tests/acceptance/one-verdict.feature` is
    `acceptance/one-verdict.feature` to the runner. `runner_path` is that rule and the page prints both
    spellings, because an address that is not a repository path has to say where the file is somewhere;
  * OUTLINES ARE EXPANDED, one entry per Examples row, with the placeholders substituted in the title and
    in every step. A page listing the outline once would carry an address matching nothing that ever ran;
  * BACKGROUND STEPS ARE PART OF EACH SCENARIO'S STEP LIST, marked but not moved. A person walking a
    scenario has to perform them, and if the page grouped them under the feature instead, the human
    walk and the machine run would produce evidence at two different granularities - the exact
    incomparability PR #198 measured and si#205 must not inherit.

STEPS, NOT SCENARIO NAMES ALONE. si#204 leaves it open and answers itself: a customer reads this to decide
whether their functionality is covered, and a scenario NAME is the author's one-line summary of the steps
- the same second source this project spends its time removing, except here the drift is between a title
and its own body. The comparability argument settles it independently: `allure-pytest-bdd` records one
result per STEP, each with its own status, and si#205's person must produce the same. A document one level
coarser than the evidence on both sides would be the only artefact of the three that cannot be lined up.

WHAT THE PAGE DOES NOT CLAIM, said plainly on the page itself rather than only here. It lists what the
feature files DECLARE. Whether a run executed them, and how each went, is the Allure archive's answer -
and only if the product put `allure-pytest-bdd` in its requirements, because with plain `allure-pytest` a
result carries `steps: []` and the mangled pytest function name (PR #198). So the page names that
requirement in its own generated prose: without it there is no per-step evidence on the automatic side
either, si#205's manual mode has nothing to be comparable WITH, and the two modes cannot be read together
at all.

WHERE THE FEATURE FILES LIVE: a default for `source`, none for `output`, which is si#183's asymmetry
applied unchanged. `source` is only ever READ, so the kernel may assume where to look; `output` is
WRITTEN, and cliref's has no default either. The default's value is the one thing si#183 could measure and
this cannot: it had three consumer manifests declaring a `site:` section and could count how they
disagreed, and here the population is ZERO - no product on this machine carries a `.feature` file. So the
default is not consumer agreement, it is a convention offered to the FIRST product, which is the same
argument si#183 ended on ("what it changes is the day a product gets a website"). `tests/acceptance` puts
the scenarios where an acceptance SUITE would run them - beside the tests rather than in `docs/`, because
they are executable sources that a document happens to be generated from, and not the other way round.

RED WHEN THERE IS NOTHING. A `source` that does not exist and a `source` holding no `.feature` file both
refuse. This project's recurring defect is an outcome that cannot tell "nothing to do" from "failed", and
a page rendered from an empty directory is its purest form: a document headed "acceptance scenarios"
listing none, published, and read as evidence that there are none to list.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn

from simplon import context, log
from simplon.bootstrap import validate_relative_dir

#: Where a product's `.feature` files are when its manifest does not say (si#183's rule, see the head of
#: this file for why the value is a convention rather than a measured agreement).
DEFAULT_SOURCE = "tests/acceptance"

#: What a feature file is called. Gherkin's own extension, and pytest-bdd's default glob.
SUFFIX = ".feature"

#: The plugin without which the automatic side carries no per-step evidence (PR #198). Named as a constant
#: because the page prints it and a test pins it: it is a REQUIREMENT this document states about the
#: product, and a requirement spelled by hand in prose is a requirement nothing reads back.
PLUGIN = "allure-pytest-bdd"

#: The keyword a step may open with. `*` is Gherkin's bullet form and pytest-bdd accepts it.
_STEP_KEYWORDS = ("Given", "When", "Then", "And", "But", "*")

#: Gherkin's two spellings for a plain scenario and its two for an outline. pytest-bdd 8 executes all
#: four, so the page describes all four and calls the last two outlines.
_SCENARIO_KEYWORDS = ("Scenario:", "Example:")
_OUTLINE_KEYWORDS = ("Scenario Outline:", "Scenario Template:")

#: Constructs this reader refuses rather than describes, each with what a product does instead. `Rule:` is
#: real Gherkin 6 that pytest-bdd 8 does not execute, so a page carrying one would list scenarios grouped
#: under a heading the runner never saw; a non-English `# language:` header changes every keyword below,
#: so the scan would silently read a feature file as pure description and report a feature with no
#: scenarios at all - which is this project's recurring defect exactly.
_REFUSED = {
    "Rule:": "pytest-bdd 8 does not execute a 'Rule:', so the page would describe a grouping no run "
             "honours - split the rule into its own feature file instead",
}

#: A placeholder inside a Scenario Outline title or step: `<level>`.
_PLACEHOLDER = re.compile(r"<([^<>]+)>")

#: A `# language:` header. Only `en` is read, because every keyword this module matches is English.
_LANGUAGE = re.compile(r"^#\s*language\s*:\s*(\S+)", re.I)


@dataclass(frozen=True)
class Step:
    """One step of one scenario, as the runner will announce it.

    `text` carries the keyword's ARGUMENT and `keyword` the word itself, kept apart so a renderer can set
    the keyword off and `announced` can put them back together in the one spelling that matters: measured
    on allure-pytest-bdd 2.16.0, an Allure step's name is exactly `<Keyword> <text>`, so that string is
    the join between a human's verdict on a step and a machine's.

    `payload` is a docstring or a data table attached to the step, kept as the lines it was written with.
    It is NOT part of `announced`, because the archive does not carry it either - but a person walking the
    step needs it, so it is on the page and off the address.

    `background` says the step came from the feature's `Background:` rather than from the scenario's own
    body. Both are walked, in this order, which is what the runner does; the flag only lets a renderer say
    so.
    """

    keyword: str
    text: str
    payload: tuple[str, ...] = ()
    background: bool = False

    @property
    def announced(self) -> str:
        """The step as allure-pytest-bdd names it: keyword, one space, text. Measured, see the head."""
        return f"{self.keyword} {self.text}".strip()


@dataclass(frozen=True)
class Scenario:
    """One scenario a run executes, and therefore one row of evidence.

    ONE PER EXAMPLES ROW, already substituted - an outline is not a scenario, it is a template for
    several, and the archive knows only the several. `outline` keeps the template's own title for the page
    to mention and `row` the 1-based row it came from; both are empty/zero for a plain scenario.

    TWO PATH SPELLINGS, because the runner and the repository do not agree and pretending they do is what
    would break the format. `path` is where the file IS, relative to the product root - what somebody
    opens. `rel` is what the RUNNER calls the same file, and it is the one the address is built from.
    """

    path: str
    rel: str
    name: str
    tags: tuple[str, ...]
    steps: tuple[Step, ...]
    outline: str = ""
    row: int = 0

    @property
    def address(self) -> str:
        """`<rel>:<scenario>` - allure-pytest-bdd's own `fullName`, byte for byte (measured, see the head).

        The identifier si#205 records a human verdict against, and the reason it is not invented here: a
        manual verdict and an Allure result have to be joinable, and a second identifier would leave two
        records of one scenario with no key between them.
        """
        return f"{self.rel}:{self.name}"


@dataclass(frozen=True)
class Feature:
    """One `.feature` file: what it is called, what it says about itself, and what it verifies.

    `description` is the free prose Gherkin allows under the `Feature:` line, kept because it is the one
    place an author explains a whole file to the reader this page is written for. `background` is carried
    separately as well as prepended into every scenario, so a renderer can name it once without having to
    re-derive which steps came from it.
    """

    path: str
    rel: str
    name: str
    description: tuple[str, ...]
    tags: tuple[str, ...]
    background: tuple[Step, ...]
    scenarios: tuple[Scenario, ...]


# --- reading ---------------------------------------------------------------------------------------------


def _refuse(path: str, line_no: int, message: str) -> NoReturn:
    """Every refusal below names the file and the line. A parser that says only 'bad feature file' makes
    the reader do the search the parser had already done."""
    raise ValueError(f"simplon: {path}:{line_no}: {message}")


def _tags(line: str) -> tuple[str, ...]:
    """The tags on a tag line, with the `@` dropped - which is how allure-pytest-bdd records them."""
    return tuple(token.lstrip("@") for token in line.split() if token.startswith("@"))


def _substitute(text: str, values: dict[str, str]) -> str:
    """`<level>` replaced by the Examples row's value for `level`.

    An unknown placeholder is LEFT AS WRITTEN rather than blanked: pytest-bdd leaves it too, so blanking it
    would make the page's address differ from the archive's on exactly the file that has a typo in it -
    the one case somebody is looking the address up for.
    """
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def _row_values(headers: Sequence[str], cells: Sequence[str]) -> dict[str, str]:
    """An Examples row as a lookup. `strict=True` because a row with the wrong number of cells is the
    silent-wrong-answer shape: zip would drop the surplus, the page would print a half-substituted title,
    and that title is the ADDRESS - so it would match nothing in the archive and say why nowhere."""
    return dict(zip(headers, cells, strict=True))


def _table_row(line: str) -> tuple[str, ...]:
    """The cells of a `| a | b |` line. The leading and trailing empties the split produces are dropped."""
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def _expand(name: str, tags: tuple[str, ...], path: str, rel: str, background: tuple[Step, ...],
            steps: tuple[Step, ...], examples: list[tuple[Sequence[str], Sequence[str]]]) -> list[Scenario]:
    """A parsed scenario block as the scenarios a run will really execute.

    With no Examples this is one scenario; with them it is one per row, substituted. The background is
    prepended HERE rather than by the renderer, because the step list is what an address is about: two
    consumers (this page and si#205's runner) must not each decide separately whether setup counts.
    """
    if not examples:
        return [Scenario(path=path, rel=rel, name=name, tags=tags, steps=background + steps)]
    found = []
    for index, (headers, cells) in enumerate(examples, start=1):
        values = _row_values(headers, cells)
        walked = background + tuple(
            Step(keyword=step.keyword, text=_substitute(step.text, values), payload=step.payload,
                 background=step.background) for step in steps)
        found.append(Scenario(path=path, rel=rel, name=_substitute(name, values), tags=tags,
                              steps=walked, outline=name, row=index))
    return found


def read(text: str, path: str, rel: str = "") -> Feature:
    """One feature file's text as a `Feature`, or a refusal naming the file and the line.

    `rel` is the runner's own spelling of the same file (see `runner_path`); it defaults to `path` so a
    caller that only wants the scenarios need not supply it.

    A LINE SCAN AND NOT A GRAMMAR, deliberately - see the head of this file. What it recognises is exactly
    what pytest-bdd 8 executes; what it recognises as Gherkin and cannot honour, it refuses; everything
    else under a `Feature:` or a scenario is free description, which Gherkin allows and this keeps.
    """
    rel = rel or path
    lines = text.splitlines()
    feature_name = ""
    feature_tags: tuple[str, ...] = ()
    description: list[str] = []
    background: list[Step] = []
    scenarios: list[Scenario] = []

    line_no = 0
    pending_tags: tuple[str, ...] = ()
    # The block currently being filled: "" before the Feature line, "description", "background", or
    # "scenario". A step's home is decided by this and never by how far it is indented, because Gherkin
    # does not make indentation meaningful and a reader that did would disagree with the runner.
    block = ""
    name = ""
    tags: tuple[str, ...] = ()
    steps: list[Step] = []
    outline = False
    examples: list[tuple[Sequence[str], Sequence[str]]] = []
    example_headers: tuple[str, ...] = ()
    in_examples = False
    docstring: list[str] | None = None

    def close() -> None:
        nonlocal steps, examples, in_examples, example_headers
        if block == "scenario":
            if outline and not examples:
                _refuse(path, line_no, f"the outline {name!r} has no Examples row, so it describes a "
                                       f"scenario no run will ever execute")
            scenarios.extend(_expand(name, tags, path, rel, tuple(background), tuple(steps), examples))
        steps, examples, in_examples, example_headers = [], [], False, ()

    for line_no, raw in enumerate(lines, start=1):
        stripped = raw.strip()

        if docstring is not None:                       # inside a """ payload: every line is content
            if stripped == '"""':
                held = steps if block == "scenario" else background
                held[-1] = Step(keyword=held[-1].keyword, text=held[-1].text, payload=tuple(docstring),
                                background=held[-1].background)
                docstring = None
            else:
                docstring.append(raw)
            continue

        if not stripped:
            continue
        if stripped.startswith("#"):
            language = _LANGUAGE.match(stripped)
            if language and language.group(1).lower() not in ("en", "en-us", "en-gb"):
                _refuse(path, line_no,
                        f"'# language: {language.group(1)}' renames every Gherkin keyword, and this "
                        f"reader matches the English ones - the page would report a feature with no "
                        f"scenarios rather than fail")
            continue
        for keyword, instead in _REFUSED.items():
            if stripped.startswith(keyword):
                _refuse(path, line_no, f"{keyword!r} is not supported: {instead}")

        if stripped.startswith("@"):
            pending_tags = _tags(stripped)
            continue

        if stripped.startswith("Feature:"):
            if feature_name:
                _refuse(path, line_no, f"a second 'Feature:' - one file is one feature, and pytest-bdd "
                                       f"reads only the first, so the page would list scenarios under a "
                                       f"title nothing ran them under")
            feature_name = stripped[len("Feature:"):].strip()
            feature_tags, pending_tags, block = pending_tags, (), "description"
            continue

        if not feature_name:
            _refuse(path, line_no, "a line before the 'Feature:' line - the file states no feature, so "
                                   "nothing on the page could say what these scenarios are about")

        if stripped.startswith("Background:"):
            if scenarios or block == "scenario":
                _refuse(path, line_no, "a 'Background:' after a scenario - the runner applies it to every "
                                       "scenario in the file, so a page honouring the file order would "
                                       "print a shorter walk than the one that runs")
            close()
            block, name, tags, outline = "background", "", (), False
            continue

        keyword = next((k for k in _SCENARIO_KEYWORDS + _OUTLINE_KEYWORDS if stripped.startswith(k)), "")
        if keyword:
            close()
            block, outline = "scenario", keyword in _OUTLINE_KEYWORDS
            name, tags, pending_tags = stripped[len(keyword):].strip(), pending_tags, ()
            if not name:
                _refuse(path, line_no, f"{keyword} with no title - the title IS the address a verdict is "
                                       f"recorded against, so an untitled scenario has none")
            continue

        if stripped.startswith("Examples:") or stripped.startswith("Scenarios:"):
            if block != "scenario" or not outline:
                _refuse(path, line_no, "'Examples:' outside a 'Scenario Outline:' - only an outline is "
                                       "expanded per row, so these rows would be read by nothing")
            in_examples, example_headers = True, ()
            continue

        if stripped.startswith("|"):
            cells = _table_row(stripped)
            if in_examples:
                if not example_headers:
                    example_headers = cells
                else:
                    examples.append((example_headers, cells))
                continue
            target = steps if block == "scenario" else background
            if not target:
                _refuse(path, line_no, "a table before any step - a table is a step's argument and has "
                                       "nowhere else to belong")
            target[-1] = Step(keyword=target[-1].keyword, text=target[-1].text,
                              payload=target[-1].payload + (stripped,), background=target[-1].background)
            continue

        if stripped == '"""':
            if not (steps if block == "scenario" else background):
                _refuse(path, line_no, "a docstring before any step - a docstring is a step's argument "
                                       "and has nowhere else to belong")
            docstring = []
            continue

        word = stripped.split(" ", 1)[0]
        if word in _STEP_KEYWORDS:
            rest = stripped[len(word):].strip()
            if block == "background":
                background.append(Step(keyword=word, text=rest, background=True))
            elif block == "scenario":
                steps.append(Step(keyword=word, text=rest))
            else:
                _refuse(path, line_no, f"a {word!r} step outside a Background or a Scenario - a step with "
                                       f"no scenario is run by nothing and verifies nothing")
            continue

        if block == "description":
            description.append(stripped)
        # Anything else is a scenario's own free description, which Gherkin allows. It is dropped rather
        # than printed: it sits between a scenario's title and its steps, and the page's job there is the
        # steps.

    line_no = len(lines)
    close()

    if not feature_name:
        raise ValueError(f"simplon: {path} carries no 'Feature:' line, so it declares nothing this "
                         f"document could list")
    _one_address_each(path, scenarios)
    return Feature(path=path, rel=rel, name=feature_name, description=tuple(description),
                   tags=feature_tags, background=tuple(background), scenarios=tuple(scenarios))


def _one_address_each(path: str, scenarios: Sequence[Scenario]) -> None:
    """Refuse a file whose scenarios do not each have their own address.

    FOUND BY DRIVING THE ARTEFACT, not by reasoning about it (si#204). The first real feature file written
    for this page carried `Scenario Outline: A leaf that fails turns the aggregate red` over three
    Examples rows and NO placeholder in the title, and the generated page came out with three rows
    carrying one identical address. The address is the whole format decision - it is the key si#205
    records a human verdict against and the key an Allure `fullName` is joined on - so three results and
    one key means two of the three verdicts have nowhere to go.

    This is pytest-bdd's own naming, not this reader's invention: allure-pytest-bdd derives `fullName`
    the same way, so the archive collides identically. Refusing here is therefore the only place the
    collision is visible at all, and it is a Diagnosis - a feature file that says something it did not
    mean, named where it is written. The cure is one placeholder in the outline's title.
    """
    seen: dict[str, Scenario] = {}
    for scenario in scenarios:
        first = seen.get(scenario.address)
        if first is not None:
            where = (f"the outline {scenario.outline!r} carries no placeholder that differs between rows "
                     f"{first.row} and {scenario.row}, so both expand to the same title"
                     if scenario.outline else
                     f"two scenarios are titled {scenario.name!r}")
            raise ValueError(
                f"simplon: {path}: {where} - the address {scenario.address!r} would then name two "
                f"results, and a verdict recorded against it could belong to either")
        seen[scenario.address] = scenario


def features(root: Path, source: str) -> list[Feature]:
    """Every feature file under `source`, in path order, or a refusal saying which of the two nothings it
    found.

    THE TWO REFUSALS ARE THE POINT and they are separate on purpose. A directory that is not there is a
    manifest pointing at nothing; a directory that is there and empty is a product that has not written
    its scenarios yet. Both are red, because a page listing no scenarios reads as "this product has none
    to verify" and is published as evidence of it, but they are not the same mistake and the message says
    which one happened.
    """
    where = root / source
    if not where.is_dir():
        raise ValueError(f"simplon: {source} is not a directory under the product root, so no acceptance "
                         f"scenario could be read - point `source:` at the directory holding the "
                         f"{SUFFIX} files")
    found = sorted(where.rglob(f"*{SUFFIX}"))
    if not found:
        raise ValueError(f"simplon: {source} holds no {SUFFIX} file, so the document would list no "
                         f"scenario at all - which reads as 'nothing is verified' rather than as 'nothing "
                         f"was found'")
    return [read(path.read_text(encoding="utf-8"), path.relative_to(root).as_posix(),
                 runner_path(where, path)) for path in found]


def runner_path(source: Path, feature: Path) -> str:
    """The feature file as pytest-bdd names it, which is NOT its path in the repository.

    MEASURED, and it killed the first version of this module's central claim. `pytest_bdd.parser.
    FeatureParser` sets `rel_filename = os.path.join(os.path.basename(basedir), filename)`, so the runner
    knows a feature file by the BASENAME of the features base directory plus the path under it - never by
    a path relative to the product root. Driven twice: `scenarios("features")` produced
    `features/reference.feature`, and `scenarios("tests/acceptance")` over this repository's own files
    produced `acceptance/generated-documents.feature` and not `tests/acceptance/...`.

    That string is what allure-pytest-bdd puts in front of the colon in a result's `fullName`, so it is
    what the page has to print for the address to be a join key rather than a resemblance. The page keeps
    the repository path too, once per feature section under `Source:`, because the address no longer says
    where the file is.

    THE ONE COUPLING THIS LEAVES, stated rather than hidden: the answer is right when the suite's features
    base directory is the directory the manifest names in `source:`. A product whose `scenarios()` call
    points deeper than `source:` gets a different basename in the archive, and the two spellings part.
    That is a property of pytest-bdd's naming rather than a choice made here, and the alternative - a path
    of this module's own invention - would part from the archive in EVERY product instead of in that one.
    """
    return f"{source.name}/{feature.relative_to(source).as_posix()}"


# --- rendering -------------------------------------------------------------------------------------------


def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell: one line, and no unescaped column separator."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _yaml(value: str) -> str:
    """A YAML double-quoted scalar, the way `cliref._yaml` does it and for the same reason: the title
    arrives from a manifest, so Python's own quoting rules are not enough to keep the front matter valid.
    """
    text = " ".join(str(value).split())
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tag_note(tags: Iterable[str]) -> str:
    return " ".join(f"`@{tag}`" for tag in tags)


def _steps(scenario: Scenario) -> list[str]:
    """One scenario's walk, as a numbered list.

    NUMBERED and not a table, because a step may carry a docstring or a table of its own and a cell cannot
    hold either. The keyword is bold so the Given/When/Then shape is readable at a glance, and the text
    beside it is verbatim, so the line a person reads and the Allure step name are the same string.
    """
    out: list[str] = [""]
    for index, step in enumerate(scenario.steps, start=1):
        note = "  *(background)*" if step.background else ""
        out.append(f"{index}. **{step.keyword}** {step.text}{note}")
        if step.payload:
            out.append("")
            out.append("   ```text")
            out += [f"   {line.strip()}" for line in step.payload]
            out.append("   ```")
    return out


def render(found: Sequence[Feature], *, product: str, title: str, source: str) -> str:
    """The whole page, as Markdown with Hugo front matter.

    The shape is `cliref.render`'s: front matter, a do-not-edit banner, a lead paragraph carrying the
    COMPUTED counts, an index table, then one section per source. What is added is the paragraph about
    evidence, and it is generated rather than written for the same reason the counts are - it states a
    requirement on the product (`allure-pytest-bdd`), and a requirement typed into a document is a
    requirement nothing reads back.
    """
    scenarios = [scenario for feature in found for scenario in feature.scenarios]
    out: list[str] = [
        "---",
        f"title: {_yaml(title)}",
        "---",
        "",
        "<!-- GENERATED by the simplon task `docs:acceptance` from the product's own .feature files.",
        "     Do not edit: the next build overwrites it. Add or change a scenario instead. -->",
        "",
        f"This page lists {len(scenarios)} acceptance "
        f"scenario{'' if len(scenarios) == 1 else 's'} across "
        f"{len(found)} feature file{'' if len(found) == 1 else 's'}, read off `{source}/` in "
        f"`{product}`'s own tree - so it lists what is verified, not what somebody remembered writing a "
        f"test for.",
        "",
        "**What this page does and does not say.** It says what the scenarios ARE. Whether a run "
        "executed them, and how each step went, is the run's own archive - and that archive only "
        f"carries a step at all when the product's suite requirements name **`{PLUGIN}`**. With plain "
        "`allure-pytest` a result carries the mangled pytest function name and an empty step list, "
        "measured; with this plugin it carries the scenario title verbatim, one entry per step with its "
        "own status, and a failing step named with its assertion. A person walking these scenarios "
        "produces per-step evidence either way, so without the plugin the two modes cannot be compared "
        "at all.",
        "",
        "Each scenario is addressed by its feature file and its title, separated by a colon. That is "
        "the string the run's archive records as a result's `fullName`, byte for byte, so a walked "
        "verdict and a machine one line up on one key. The file is named the way the RUNNER names it - "
        "the base directory's own name plus the path under it - so the address is not where the file "
        "sits in the repository; each feature section below says that too.",
        "",
        "| Scenario | Feature | Steps | Address |",
        "| --- | --- | --- | --- |",
    ]
    for scenario in scenarios:
        feature = next(f for f in found if f.rel == scenario.rel)
        out.append(f"| {_cell(scenario.name)} | {_cell(feature.name)} | {len(scenario.steps)} | "
                   f"`{_cell(scenario.address)}` |")

    for feature in found:
        out += ["", f"## {feature.name}", "",
                f"Source: `{feature.path}`, which the runner knows as `{feature.rel}`."]
        if feature.tags:
            out += ["", f"Tagged {_tag_note(feature.tags)}."]
        if feature.description:
            out += ["", " ".join(feature.description)]
        if feature.background:
            out += ["", f"Every scenario below opens with the same {len(feature.background)} "
                        f"background step{'' if len(feature.background) == 1 else 's'}, which is why "
                        f"they are repeated in each walk rather than stated once: a person performs "
                        f"them once per scenario, and so does the runner."]
        for scenario in feature.scenarios:
            out += ["", f"### {scenario.name}", "", f"`{scenario.address}`"]
            if scenario.tags:
                out += ["", f"Tagged {_tag_note(scenario.tags)}."]
            if scenario.outline:
                # The outline's title is printed in a CODE SPAN and not in italics: it carries the
                # placeholders (`<leaf>`), and Hugo's renderer reads `<leaf>` in prose as an HTML tag and
                # drops it - so the one line whose job is to show the template would show it with the
                # template taken out.
                out += ["", f"Row {scenario.row} of the outline `{scenario.outline}`. The outline itself "
                            f"is not a scenario and never runs: each of its rows does, under the title "
                            f"above."]
            out += _steps(scenario)
    return "\n".join(out) + "\n"


# --- the task --------------------------------------------------------------------------------------------


def document(output: str, source: str = DEFAULT_SOURCE, title: str = "") -> int:
    """Write the product's acceptance document to `output`, as Markdown for Hugo.

    `output` goes through `validate_relative_dir` for the reason `cliref.reference` states: the value
    comes from a manifest and is then WRITTEN to, so an absolute one would land outside the product
    entirely. `source` is only ever read and therefore takes the default this module declares (si#183).
    """
    ctx = context.current()
    relative = validate_relative_dir(
        output, "the acceptance document's output path",
        "give a plain relative path under the product root, e.g. "
        "'docs/site/content/with-what/acceptance.md'",
        inside="the product root")
    found = features(ctx.root, source)
    page = render(found, product=ctx.name, title=title or f"{ctx.name} acceptance scenarios",
                  source=source)
    path = ctx.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    count = sum(len(feature.scenarios) for feature in found)
    log.ok(f"acceptance document -> {relative} ({count} scenario{'' if count == 1 else 's'} from "
           f"{len(found)} feature file{'' if len(found) == 1 else 's'})")
    return 0
