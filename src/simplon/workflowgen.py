"""Render a product's committed GitHub workflows from its manifest (si#40) - the SECOND of the "one
source, two outputs" this kernel has promised since `simplon.orchestrator.manifest` was written.

WHAT MAKES THIS A GENERATOR RATHER THAN A TRANSCODER. A workflow that lists build steps restates
something the manifest already says, and the restatement is not checked by anything: agile-cockpit's
workflows name five commands out of its manifest, and the only thing holding those five names to reality
is that somebody typed them correctly. Eighteen unit tests were then written to guard properties of
those hand-written files, and a review found seven blind spots in the tests themselves. Derived data
maintained by hand has to be guarded by hand, and the guard is only ever as good as its wording.

So a step that runs a product command says `command: test all` and nothing else. This module resolves
that against the LOADED manifest - the command must exist in the command tree - and renders
`./<product>.sh test all`. A renamed command breaks generation loudly instead of leaving a workflow
calling a command that is gone. That resolution is the whole value; the YAML around it is bookkeeping.

WHAT BELONGS TO THE PRODUCT, AND WHAT DOES NOT (si#40's first hard question). Runner images, triggers,
permissions, schedules, environments and concurrency are the PRODUCT's: the kernel cannot know them and
must not guess. They are carried through VERBATIM, dumped as they were declared. What is not the
product's is the step SEQUENCE - it is already in the manifest - and the invariants the kernel has
learned the hard way, which is why `actions/checkout` is emitted by this module with `fetch-depth: 0`
rather than declared per job: si#3 measured that a shallow clone makes setuptools-scm derive a version
that is merely wrong, and `tests/test_version_source.py` asserts the setting over the whole workflows
directory precisely because a NEW workflow gets the default and the default is wrong. A rule a new file
inherits beats a rule somebody has to remember.

COMMENTS SURVIVE, and that is a requirement rather than a nicety. simplon's own `release.yml` is roughly
two-thirds prose - measured values, and the reasoning for an absence a reviewer cannot see - and
agile-cockpit's nightly workflow carries the same kind of thing (a measured 16m03s, why there is no
`push` trigger, why `pipefail`). A generator that dropped it would make the files worse than the ones it
replaced. So `note:` may be attached to a workflow, to a job and to a step, and it is emitted as a YAML
comment block in that position. The prose moves next to the declaration it explains; none of it is lost.

AND A WORKFLOW MAY DECLINE TO BE GENERATED. `handwritten:` states, in one line and with a reason, that a
file is somebody's own work. It is not an escape hatch, it is the other half of the answer: some
workflows really are hand-work, and the honest thing is to say so where the manifest can see it. What
this buys is the thing si#40 actually asks for - a file in the workflows directory that NO entry names
is reported and makes `--check` red. That is the case that has already cost this family of projects
once: agile-cockpit ran three assertions against a `.gitlab-ci.yml` nothing executed any more, and
nobody noticed, because an unmanaged file looks exactly like a managed one.

TWO MEASURED TRAPS, both live in this file.

1. YAML 1.1 READS `on:` AS A BOOLEAN. `yaml.safe_load("on: [push]")` returns a mapping keyed by `True`,
   not by `"on"`, and `yaml.safe_dump({"on": ...})` writes `'on':` - the quoted STRING, which is not
   what a reader of the file expects to round-trip. Emitting a workflow by dumping a whole document is
   therefore wrong in both directions, so the document scaffolding here is written as TEXT and only the
   product's verbatim sub-trees go through the dumper. `validate` below reads the trigger back under the
   boolean key, which is where it actually lands.

2. A WORKFLOW NOBODY CAN RUN IS WORTH NOTHING. Having written the text, `render` parses it back and
   checks that what came out is a workflow GitHub would accept - a name, a trigger, at least one job,
   and every job carrying `runs-on` and a non-empty `steps`. Asserting that bytes were written asserts
   that this module ran, which is not the same claim.
"""
from __future__ import annotations

import difflib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import yaml

from simplon.orchestrator.manifest import Manifest

#: The manifest section this module owns. A product that declares no section declares no workflows, and
#: is told so rather than handed an empty report - "nothing declared" and "nothing wrong" are different
#: answers, and this repository's recurring defect is exactly the pair that cannot be told apart.
SECTION = "workflows"

#: Where GitHub looks. Not configurable: it is GitHub's path, not the product's, and a product that put
#: its workflows elsewhere would have no workflows.
DIRECTORY = ".github/workflows"

#: The file extensions GitHub reads out of that directory. Both, because GitHub reads `.yaml` exactly as
#: it reads `.yml`, and a scan that globbed one of them would leave the other unmanaged and unreported -
#: the same blind spot one file extension over that `tests/test_version_source.py` names.
EXTENSIONS = ("*.yml", "*.yaml")

#: The two actions the kernel emits itself, and the reason each is here rather than in the manifest.
#: `checkout` carries si#3's `fetch-depth: 0` invariant, which must not be a thing a product remembers.
#: `setup-python` is how the launcher gets an interpreter to build its venv with; a job that declares no
#: `python:` gets neither the step nor an opinion.
CHECKOUT_ACTION = "actions/checkout@v4"
SETUP_PYTHON_ACTION = "actions/setup-python@v5"

#: The clone depth si#3 measured. A shallow clone has the tag without the history behind it, so
#: setuptools-scm derives a version that is wrong rather than failing, and PyPI accepts the wheel.
FETCH_DEPTH = 0

#: Why the checkout looks the way it does, emitted INTO the generated file above the step.
#:
#: A generated file has to explain itself to whoever opens it, and this reasoning used to live in
#: simplon's own ci.yml as a hand-written comment. Moving the setting into the generator without moving
#: its justification would leave a reader looking at `fetch-depth: 0` with nowhere to find out why - the
#: quiet kind of loss si#40 says a generator must not cause. It is the kernel's prose because the setting
#: is the kernel's, so it is stated here once instead of in every product's manifest.
CHECKOUT_NOTE = """The full history, and it is a precondition rather than an optimisation (si#3).
The version comes from the git tag via setuptools-scm, and checkout's default shallow
clone has the tag without the history behind it: the derivation then produces a version
that is merely WRONG instead of failing, and PyPI accepts the wheel. Emitted by the
generator rather than declared per job, so a workflow written later inherits the rule
instead of somebody having to remember it."""

_HEADER = ("GENERATED from {source} by `{product} support workflows`. Do not edit.",
           "",
           "The steps below are the product's own commands, resolved against {source}'s command tree, so",
           "a command that is renamed or removed breaks generation instead of leaving a workflow calling",
           "something that is gone. `--check` reports drift and returns 1.")


class Step(NamedTuple):
    """One step: either a product COMMAND or a verbatim GitHub step, never both.

    A command step is the point of this module - `command: test all` is resolved against the manifest and
    rendered as one `run:` line through the product's launcher. A verbatim step is everything a product
    legitimately needs that the kernel has no business modelling: `pypa/gh-action-pypi-publish`,
    `actions/upload-pages-artifact`, a shell script that reports whether a tag sits on `main`. It is
    dumped as declared.

    `note` is prose, emitted as a comment ABOVE the step. It exists because the alternative measured in
    the field is a generator that silently deletes the reasoning somebody wrote down.
    """

    command: str = ""
    verbatim: Mapping[str, object] | None = None
    note: str = ""


@dataclass(frozen=True)
class Job:
    """One job. `runs_on` and the extras are the product's; the checkout and the interpreter are ours.

    `extras` is every job-level key the kernel does not interpret - `permissions`, `environment`,
    `needs`, `concurrency`, `if`, `strategy`, `timeout-minutes`. Carried through untouched rather than
    enumerated, because enumerating them would make this module the gatekeeper of GitHub's schema and it
    would be wrong the week GitHub adds a key.
    """

    name: str
    runs_on: str
    steps: tuple[Step, ...]
    python: str = ""
    checkout: bool = True
    note: str = ""
    extras: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Workflow:
    """One workflow file: what it is called, when it runs, and what it does.

    `handwritten` is the declared decline (see the module docstring). A workflow that carries it has no
    jobs and no trigger here - the file is somebody's own - and the string says WHY, because a decline
    with no reason is indistinguishable from an oversight the day somebody reads it.
    """

    key: str
    path: str
    name: str = ""
    note: str = ""
    on: object = None
    jobs: tuple[Job, ...] = ()
    handwritten: str = ""

    @property
    def generated(self) -> bool:
        return not self.handwritten


class Drift(NamedTuple):
    """One generated workflow that disagrees with the manifest, and the diff that shows how."""

    path: str
    diff: str


class Report(NamedTuple):
    """What `check` found, split so that a caller can say WHICH kind of wrong it is.

    Four buckets rather than a boolean, and the split is the point: "up to date", "drifted", "declared
    hand-written" and "in the directory and named by nobody" are four different situations, and a check
    that collapsed them would answer the one question si#40 says is unanswerable today.
    """

    agreed: tuple[str, ...]
    drifted: tuple[Drift, ...]
    handwritten: tuple[str, ...]
    unmanaged: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """True when every claim the manifest makes about this directory holds.

        An UNMANAGED file counts against it. That is deliberate and it is the whole reason this bucket
        exists: a workflow nothing generates and nothing declares is the shape that already went wrong
        once, when three assertions ran against a CI file that had stopped executing months earlier.
        Declaring it `handwritten:` costs one line and moves it into a bucket that says somebody knows.
        """
        return not self.drifted and not self.unmanaged


# --- parsing the section ---------------------------------------------------------------------------------


def parse(data: Mapping[str, object]) -> tuple[Workflow, ...]:
    """The `workflows:` section of a raw manifest, validated.

    Loud on every defect, like `simplon.environments.parse` and every other section parser here: a
    manifest that says something this module cannot render is a manifest defect, and the message names
    the workflow it is talking about.
    """
    section = data.get(SECTION)
    if section is None:
        raise ValueError(
            f"the manifest declares no '{SECTION}' section, so there is nothing to generate - declare "
            f"one workflow per file under `{SECTION}:`, or drop the command if this product has none")
    if not isinstance(section, Mapping) or not section:
        raise ValueError(f"'{SECTION}' must be a non-empty mapping of workflow name -> its declaration")

    out = []
    for key, body in section.items():
        out.append(_workflow(str(key), body))
    _reject_duplicate_paths(out)
    return tuple(out)


def _workflow(key: str, body: object) -> Workflow:
    where = f"workflow '{key}'"
    if not isinstance(body, Mapping):
        raise ValueError(f"{where}: must be a mapping, not {type(body).__name__}")
    path = str(body.get("path") or f"{DIRECTORY}/{key}.yml")
    _check_path(path, where)

    handwritten = str(body.get("handwritten") or "").strip()
    if handwritten:
        # A declined workflow must decline COMPLETELY. Carrying jobs beside the decline would leave two
        # readings of one entry and no way to tell which the author meant.
        stray = sorted(k for k in ("jobs", "note", "name") if body.get(k) is not None)
        if _declared_trigger(body, where) is not None:
            stray = sorted([*stray, "on"])
        if stray:
            raise ValueError(
                f"{where}: `handwritten:` says this file is not generated, so it cannot also declare "
                f"{', '.join(stray)} - remove the decline or remove the declaration")
        return Workflow(key=key, path=path, handwritten=handwritten)

    if "handwritten" in body:
        # An EMPTY `handwritten:` is the case worth naming: it reads as a decline and behaves as none.
        raise ValueError(f"{where}: `handwritten:` must say why this file is not generated, not be empty")

    trigger = _declared_trigger(body, where)
    if trigger is None:
        raise ValueError(
            f"{where}: declares no `on:` trigger. The kernel does not invent one - whether a tag "
            f"publishes, or a push runs the suite, is this product's statement and not something that "
            f"can be derived from a command tree")
    jobs = body.get("jobs")
    if not isinstance(jobs, Mapping) or not jobs:
        raise ValueError(f"{where}: `jobs:` must be a non-empty mapping of job name -> its declaration")

    return Workflow(key=key, path=path, name=str(body.get("name") or key),
                    note=str(body.get("note") or ""), on=trigger,
                    jobs=tuple(_job(str(name), spec, where) for name, spec in jobs.items()))


def _declared_trigger(body: Mapping[object, object], where: str) -> object:
    """A workflow declaration's `on:`, read under the key it actually lands on.

    THE TRAP, ON THE INPUT SIDE, and it caught the first run of this module against simplon's own
    manifest. YAML 1.1 reads the bare word `on` as a BOOLEAN, so an author who writes the trigger the
    natural way - exactly as it is written in a workflow file - hands `yaml.safe_load` a mapping keyed by
    `True`, and a parser looking for `"on"` finds nothing and reports a manifest with a perfectly good
    trigger as declaring none. That is the failure si#40 names from the other direction: searching for
    `push` in a section you never had, and reading the miss as an answer.

    So BOTH spellings are accepted, because both are things a reasonable author writes, and declaring
    them TOGETHER is refused: two keys that mean one thing, with only PyYAML's opinion deciding which
    wins, is a declaration whose meaning depends on a detail nobody should have to know.
    """
    quoted, bare = body.get("on"), body.get(True)
    if quoted is not None and bare is not None:
        raise ValueError(
            f"{where}: declares the trigger twice, as `on:` and as `\"on\":`. YAML 1.1 reads the bare "
            f"word as a boolean, so those are two different keys carrying one meaning - keep one")
    return bare if bare is not None else quoted


def _check_path(path: str, where: str) -> None:
    """The file must land where GitHub reads, under a name GitHub reads.

    A workflow written anywhere else is a file nobody runs, which is the failure this whole module is
    about - so it is refused at declaration time rather than produced and wondered at.
    """
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{where}: `path:` must be relative to the product root, got '{path}'")
    if candidate.parent.as_posix() != DIRECTORY:
        raise ValueError(f"{where}: `path:` must be under '{DIRECTORY}/', got '{path}'")
    if candidate.suffix not in (".yml", ".yaml"):
        raise ValueError(f"{where}: `path:` must end in .yml or .yaml, got '{path}'")


def _reject_duplicate_paths(workflows: Sequence[Workflow]) -> None:
    """Two entries writing one file is a manifest defect, not a last-one-wins.

    It matters more here than it would elsewhere: the loser would silently never be produced, and the
    directory scan would still find the file and call it managed - so nothing would report it.
    """
    seen: dict[str, str] = {}
    for workflow in workflows:
        if workflow.path in seen:
            raise ValueError(f"workflows '{seen[workflow.path]}' and '{workflow.key}' both declare "
                             f"'{workflow.path}'; one file has one owner")
        seen[workflow.path] = workflow.key


def _job(name: str, spec: object, where: str) -> Job:
    where = f"{where}, job '{name}'"
    if not isinstance(spec, Mapping):
        raise ValueError(f"{where}: must be a mapping, not {type(spec).__name__}")
    runs_on = spec.get("runs-on") or spec.get("runs_on")
    if not runs_on:
        raise ValueError(f"{where}: declares no `runs-on:`. The runner image is the product's choice "
                         f"and the kernel has no default worth imposing")
    steps = spec.get("steps")
    if not isinstance(steps, Sequence) or isinstance(steps, str) or not steps:
        raise ValueError(f"{where}: `steps:` must be a non-empty list")

    python = spec.get("python")
    checkout = spec.get("checkout", True)
    if not isinstance(checkout, bool):
        raise ValueError(f"{where}: `checkout:` is true or false, got '{checkout}'")

    known = {"runs-on", "runs_on", "steps", "python", "checkout", "note"}
    extras = {str(k): v for k, v in spec.items() if str(k) not in known}
    return Job(name=name, runs_on=str(runs_on), python=str(python) if python is not None else "",
               checkout=checkout, note=str(spec.get("note") or ""),
               steps=tuple(_step(item, f"{where}, step {i + 1}") for i, item in enumerate(steps)),
               extras=extras)


def _step(item: object, where: str) -> Step:
    if not isinstance(item, Mapping):
        raise ValueError(f"{where}: must be a mapping, not {type(item).__name__}")
    note = str(item.get("note") or "")
    command = str(item.get("command") or "").strip()
    rest = {str(k): v for k, v in item.items() if str(k) not in ("command", "note")}

    if command and rest:
        # `command:` IS the step. Letting it carry `uses:` or its own `run:` beside it would produce a
        # step whose meaning depends on which key the renderer happens to read first.
        raise ValueError(f"{where}: `command:` renders the whole step, so it cannot also declare "
                         f"{', '.join(sorted(rest))}")
    if command:
        return Step(command=command, note=note)
    if not rest:
        raise ValueError(f"{where}: declares neither `command:` nor a verbatim GitHub step")
    if "uses" not in rest and "run" not in rest:
        raise ValueError(f"{where}: a verbatim step needs `uses:` or `run:`; for a product command say "
                         f"`command: <group> <name>` and let it be resolved against the manifest")
    return Step(verbatim=rest, note=note)


# --- resolving a command step against the manifest ---------------------------------------------------------


def resolve_command(manifest: Manifest, command: str, *, where: str) -> tuple[str, str]:
    """`test all` -> ('test', 'all'); `support tasks generate` -> ('support.tasks', 'generate').

    THE JOIN si#40 is about. A workflow may only run a command the manifest declares, so the last token
    is the command name and everything before it is the group PATH - the same dotted path the taxonomy
    uses. A name the tree does not carry is refused here, with the group's real members listed, rather
    than becoming a `run:` line that fails on a runner three minutes into a job.
    """
    tokens = command.split()
    if len(tokens) < 2:
        raise ValueError(f"{where}: `command: {command}` must name a group and a command "
                         f"(`test all`, `support tasks generate`)")
    group, name = ".".join(tokens[:-1]), tokens[-1]
    members = manifest.commands.get(group)
    if members is None:
        raise ValueError(f"{where}: `command: {command}` names group '{group}', which this manifest "
                         f"does not declare - it has: {', '.join(sorted(manifest.commands))}")
    if name not in members:
        raise ValueError(f"{where}: `command: {command}` names no command in group '{group}' "
                         f"- it holds: {', '.join(sorted(members))}")
    return group, name


def launcher(product: str) -> str:
    """How a workflow invokes the product, and it is the SAME string a developer types in a checkout.

    That sameness is a rule this repository already enforces from the other side (si#8:
    `tests/test_type_gate.py` refuses a workflow step that reaches for `mypy`, `pytest` or `pip`
    directly). Deriving the launcher here rather than letting a workflow spell out a `run:` line is what
    makes a generated workflow unable to grow a second route to a verdict.
    """
    return f"./{product}.sh"


# --- rendering -----------------------------------------------------------------------------------------------


def render(workflow: Workflow, *, manifest: Manifest, product: str, source: str) -> str:
    """One workflow's text. Deterministic: same manifest, same bytes.

    Written as TEXT rather than dumped as a document, for the reason the module docstring measures: a
    dumped `on:` comes back as the quoted string `'on'`, because YAML 1.1 reads the bare word as a
    boolean. Only the product's own verbatim sub-trees go through the dumper, where that question does
    not arise.
    """
    if not workflow.generated:
        raise ValueError(f"workflow '{workflow.key}' is declared hand-written "
                         f"({workflow.handwritten}); there is nothing to render")

    lines: list[str] = [f"# {line}".rstrip()
                        for line in (text.format(source=source, product=product) for text in _HEADER)]
    lines.append("")
    lines += _comment(workflow.note, "")
    lines.append(f"name: {_scalar(workflow.name)}")
    lines.append("on:")
    lines += _dumped(workflow.on, "  ")
    lines.append("")
    lines.append("jobs:")
    for job in workflow.jobs:
        lines += _render_job(job, manifest=manifest, product=product, workflow=workflow.key)
    text = "\n".join(lines).rstrip("\n") + "\n"

    validate(text, where=f"workflow '{workflow.key}'")
    return text


def _render_job(job: Job, *, manifest: Manifest, product: str, workflow: str) -> list[str]:
    where = f"workflow '{workflow}', job '{job.name}'"
    lines = [""]
    lines += _comment(job.note, "  ")
    lines.append(f"  {_scalar(job.name)}:")
    lines.append(f"    runs-on: {_scalar(job.runs_on)}")
    for key, value in job.extras.items():
        lines += _key_and_value(key, value, "    ")
    lines.append("    steps:")

    if job.checkout:
        # si#3's invariant, emitted rather than declared - see the module docstring. A job that wants a
        # different checkout says `checkout: false` and writes its own, which is visible in the manifest
        # and therefore arguable; a defaulted-away one would not be.
        lines += _comment(CHECKOUT_NOTE, "      ")
        lines.append(f"      - uses: {CHECKOUT_ACTION}")
        lines.append("        with:")
        lines.append(f"          fetch-depth: {FETCH_DEPTH}")
    if job.python:
        lines.append(f"      - uses: {SETUP_PYTHON_ACTION}")
        lines.append("        with:")
        lines.append(f"          python-version: {_scalar(job.python)}")

    for index, step in enumerate(job.steps):
        lines += _comment(step.note, "      ")
        if step.command:
            group, name = resolve_command(manifest, step.command,
                                          where=f"{where}, step {index + 1}")
            lines.append(f"      - run: {launcher(product)} {group.replace('.', ' ')} {name}")
        else:
            lines += _dumped_step(step.verbatim or {}, "      ")
    return lines


def _key_and_value(key: str, value: object, indent: str) -> list[str]:
    """A job-level key the kernel carries through: a scalar on one line, anything else as a block."""
    if isinstance(value, (Mapping, list, tuple)):
        return [f"{indent}{key}:", *_dumped(value, indent + "  ")]
    return [f"{indent}{key}: {_scalar(value)}"]


def _dumped(value: object, indent: str) -> list[str]:
    """A product's verbatim sub-tree, dumped and indented.

    `sort_keys=False` because the manifest's ORDER is the author's statement - a trigger's `push` before
    `pull_request`, a permission list in the order somebody reasoned about it - and re-sorting it would
    make the generated file disagree with the declaration it came from for no reason at all.
    """
    text = yaml.safe_dump(_plain(value), sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=100)
    return [f"{indent}{line}".rstrip() for line in text.rstrip("\n").splitlines()]


def _dumped_step(step: Mapping[str, object], indent: str) -> list[str]:
    """One verbatim step as a YAML list item, dumped so a multi-line `run:` block keeps its shape."""
    text = yaml.safe_dump([_plain(step)], sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=100)
    return [f"{indent}{line}".rstrip() for line in text.rstrip("\n").splitlines()]


def _plain(value: object) -> object:
    """Raw YAML data as something `safe_dump` will accept.

    A manifest read by `yaml.safe_load` is already plain, so this is a guard rather than a conversion -
    but a caller that built a declaration in Python could hand in a tuple, and `safe_dump` refuses one
    with a RepresenterError rather than writing a list.
    """
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _comment(note: str, indent: str) -> list[str]:
    """Prose as a YAML comment block. Blank lines are kept as bare `#`, so a paragraph break survives."""
    if not note.strip():
        return []
    return [f"{indent}#{' ' + line if line.strip() else ''}".rstrip()
            for line in note.rstrip("\n").splitlines()]


#: The throwaway key `_scalar` dumps a value under. A one-key mapping is the only shape whose output is
#: reliably `<key>: <the scalar as YAML needs it>`; dumping a bare scalar appends YAML's document-end
#: marker (`ubuntu-latest\n...\n`), and stripping that off by character set eats a trailing dot out of a
#: value that legitimately ends in one.
_SCALAR_KEY = "v"


def _scalar(value: object) -> str:
    """One scalar, quoted only where YAML needs it - decided by the dumper rather than by guessing.

    Guessing is what a hand-written `if` here would be doing, and it would be wrong on the two cases this
    file is full of: `3.12` is a string that MUST stay quoted or it becomes the number 3.12, and `on`
    quoted or not is the trap the module docstring measures.
    """
    dumped = yaml.safe_dump({_SCALAR_KEY: value}, default_flow_style=True,
                            allow_unicode=True, width=10_000).strip()
    prefix = f"{{{_SCALAR_KEY}: "
    if not dumped.startswith(prefix) or not dumped.endswith("}"):
        raise ValueError(f"cannot render {value!r} as a single-line YAML scalar")
    return dumped[len(prefix):-1]


# --- validation: what came out has to be a workflow GitHub would run -------------------------------------------


def validate(text: str, *, where: str) -> dict:
    """Parse the rendered text back and check it is a workflow, not merely a file. Returns the document.

    THE SECOND TRAP si#40 names, and the reason this is not optional. A generator whose test asserts that
    bytes were written has asserted that the generator ran. What matters is whether GitHub would execute
    the result, and the cheap half of that question - does it parse, does it carry a trigger, does every
    job have a runner and at least one step - is answerable here, at generation time, for nothing.

    THE TRIGGER IS READ UNDER THE BOOLEAN KEY `True`, because YAML 1.1 says the bare word `on` is a
    boolean and PyYAML obeys it. A check that looked for the string `"on"` would find nothing, in a
    document that carries a perfectly good trigger, and would report the absence as a defect - or, worse,
    would be written the other way round and report "no trigger" as "nothing to check".
    """
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"{where}: the rendered workflow is not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{where}: the rendered workflow is not a mapping")
    if not str(doc.get("name") or "").strip():
        raise ValueError(f"{where}: the rendered workflow carries no `name:`")
    if True not in doc:
        raise ValueError(f"{where}: the rendered workflow carries no `on:` trigger (read back under the "
                         f"boolean key True, which is where YAML 1.1 puts it)")
    if not doc[True]:
        raise ValueError(f"{where}: the rendered workflow's `on:` trigger is empty")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ValueError(f"{where}: the rendered workflow declares no jobs")
    for name, job in jobs.items():
        if not isinstance(job, dict):
            raise ValueError(f"{where}: job '{name}' is not a mapping")
        if not job.get("runs-on"):
            raise ValueError(f"{where}: job '{name}' has no `runs-on`")
        if not job.get("steps"):
            raise ValueError(f"{where}: job '{name}' has no steps")
    return doc


def trigger_of(doc: Mapping[object, object]) -> object:
    """A parsed workflow's `on:` section, read under the key it actually lands on.

    Exported because every consumer of a parsed workflow needs it and every one of them is one keystroke
    from looking under `"on"`, finding nothing, and believing the file has no trigger. Naming the trap
    once is cheaper than each caller rediscovering it.
    """
    return doc.get(True)


# --- write, check ----------------------------------------------------------------------------------------------


def write(workflows: Sequence[Workflow], root: Path, *, manifest: Manifest, product: str,
          source: str) -> tuple[str, ...]:
    """Render every generated workflow under `root`. Returns the paths whose bytes CHANGED.

    A hand-written entry is skipped rather than touched: the manifest declared it somebody's own, and a
    generator that wrote to it anyway would have made the declaration a lie.
    """
    changed = []
    for workflow in workflows:
        if not workflow.generated:
            continue
        text = render(workflow, manifest=manifest, product=product, source=source)
        target = root / workflow.path
        if target.exists() and target.read_text(encoding="utf-8") == text:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        changed.append(workflow.path)
    return tuple(changed)


def check(workflows: Sequence[Workflow], root: Path, *, manifest: Manifest, product: str,
          source: str) -> Report:
    """What disagrees, split four ways - see `Report`.

    A MISSING target is drift, not an error, for the same reason it is in `simplon.taskgen`: a fresh
    checkout that has never generated has to be told what to run, and a gate that raised there would read
    as a broken gate rather than as the ordinary thing it is.
    """
    agreed: list[str] = []
    drifted: list[Drift] = []
    handwritten: list[str] = []

    for workflow in workflows:
        if not workflow.generated:
            handwritten.append(workflow.path)
            continue
        text = render(workflow, manifest=manifest, product=product, source=source)
        target = root / workflow.path
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current == text:
            agreed.append(workflow.path)
            continue
        diff = "".join(difflib.unified_diff(
            current.splitlines(keepends=True), text.splitlines(keepends=True),
            fromfile=f"{workflow.path} (committed)", tofile=f"{source} (now)"))
        drifted.append(Drift(path=workflow.path, diff=diff))

    return Report(agreed=tuple(agreed), drifted=tuple(drifted), handwritten=tuple(handwritten),
                  unmanaged=unmanaged(workflows, root))


def unmanaged(workflows: Sequence[Workflow], root: Path) -> tuple[str, ...]:
    """Every file in the workflows directory that no entry names.

    THE CHECK si#40 asks for, and the one nothing in this family of projects has had. A workflow that
    stopped being generated, a file left behind by a rename, a `.gitlab-ci.yml` that three assertions
    still ran against months after anything executed it: all of them look, from the directory, exactly
    like a file somebody maintains. Naming it costs one manifest line - a declaration or a
    `handwritten:` - and until somebody spends it, the file is reported.

    A missing directory yields nothing rather than raising: a product may legitimately declare only
    hand-written workflows it has not written yet, and that is not this function's complaint to make.
    """
    directory = root / DIRECTORY
    if not directory.is_dir():
        return ()
    declared = {workflow.path for workflow in workflows}
    found = sorted({path.relative_to(root).as_posix()
                    for pattern in EXTENSIONS for path in directory.glob(pattern)})
    return tuple(path for path in found if path not in declared)
