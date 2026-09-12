"""A person walks the product's acceptance scenarios and answers each step (si#205).

ONE SOURCE, TWO MODES, and the mode is a choice at RUN TIME. The scenarios are the `.feature` files
si#204's reader already reads for the acceptance document; nothing here is a second list. A product's
`test suite` runs them with pytest-bdd and `test walk` runs them with a person, over the same files,
addressed the same way - `<feature file>:<scenario>`, which is allure-pytest-bdd's own `fullName` byte
for byte, so a human verdict and a machine result join on one key rather than on a resemblance.
`simplon.tasks.acceptance.features` is called from here exactly as the document calls it: one reader,
two consumers, which is what si#204 built it callable outside a docs build for.

THE STEP MAPPING HELD, AND ONE PART OF IT IS LOAD-BEARING RATHER THAN CONVENIENT. si#205 asks whether a
Gherkin scenario really is a `steps.Pipeline` whose steps take their outcome from a person. It is, and
the part that decides it is not the tree or the transcript - both of which do come for free - it is
`stop_on_failure` PER SCENARIO. pytest-bdd stops a scenario at its first failing step and runs the next
scenario anyway; `steps.abort_after` scopes a failure to the outermost ancestor whose flag is true, so a
plan whose SCENARIO nodes carry the flag and whose feature and root nodes do not reproduces that rule
exactly, with nothing written here to enforce it. A flat pipeline would have had to choose between
skipping everything after a refusal and asking a person questions whose precondition has just been
denied, and either would be a manual mode answering a different question than the automatic one. That is
the whole "one verdict" property, and it is spelled `stop_on_failure`.

WHAT THE MAPPING COSTS, said plainly. A `PlanNode` carries a `CommandSpec`, which is a manifest
declaration, and a Gherkin step is not a command - so `_plan_spec` builds specs no manifest ever wrote.
That is a seam being borrowed rather than fitted, and it is accepted for one reason: everything
downstream of the plan (`build_rows`, `abort_after`, `status_line`, `transcript`, `failure_report`,
`overall_rc`) then works unchanged, and there is exactly one way to reach a verdict. The alternative was
a second runner, which is the second source this repository spends its time removing.

A STEP NOBODY REACHED IS A THIRD STATE, and it turns out to be two of them, which is better than one. A
step the person refused makes the rest of ITS scenario `SKIPPED` (the scope above), and a walk the person
stopped leaves everything after it `PENDING`. `overall_rc` is 0 only when every step is OK, so neither
reads as green, and `transcript` already prints the two differently - `⊘ ... (skipped: <scope> stopped on
a failure)` against `· ... (pending)`. Nothing was added for either.

REFUSING IS EXACTLY AS CHEAP AS ACCEPTING, and it is arranged rather than asserted: `a` accepts, `r`
refuses, one key each, no default, no confirmation on either, and both sit at the FRONT of the runner's
footer so a narrow terminal drops the navigation keys before it drops these two. See
`orchestrator.tui._WalkApp`, which is where the two bindings live. A prompt whose yes is Enter and whose
no is a menu collects signatures; the customer's no is the outcome the session exists to make possible.

THE RECORD IS THE RUN TRANSCRIPT, not a fourth artefact. si#148's transcript already carries the run's
name, its start, its environment, its instance and si#125's provenance line, plus every step with its
verdict and its duration; what a walk adds is `header()` - who walked it, which product version was in
front of them, which scenarios were selected and which were NOT. si#205 asks for who, when, which
product version, which scenarios and each step's outcome: three of the five were already written, and
inventing a second document would have meant a second spelling of them.

THE LIMIT THAT COMES WITH THAT, stated rather than found later: the transcript is ONE file per checkout,
overwritten by the next run of anything (`steplog.RUN_TRANSCRIPT`, and si#148 decided that deliberately -
"the interesting run is the last one"). A walk's record therefore survives until the next run in the same
tree, and a customer keeps it by taking it away. Keeping it for good is a question about ARCHIVING that
si#133's Allure path already owns for the automatic side; joining the two there beats a second log file
here.

AND THE LIMIT si#204 LEFT IS STILL OPEN. Simplon's own nine scenarios have no step definitions, so
`test suite` executes none of them and the two modes cannot be compared inside this repository by running
both. This command does not change that and does not pretend to. What it ASSUMES is only that the address
is the join key, which si#204 measured against a real allure-pytest-bdd run rather than derived; si#205's
proof was driven the same way, against a throwaway suite of step definitions pointed at these very
feature files.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import shutil
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from simplon import context, log, steplog
from simplon.orchestrator.manifest import CommandSpec, PlanNode
from simplon.orchestrator.steps import (Emit, Outcome, Pipeline, Step, StepState,
                                        write_run_transcript)
from simplon.run import run
from simplon.tasks.acceptance import DEFAULT_SOURCE, Feature, Scenario
from simplon.tasks.acceptance import Step as GherkinStep
from simplon.tasks.acceptance import features
from simplon.tasks.image import REVISION_ARG, VERSION_ARG, provenance

#: Where a walk's state lives: beside the per-step logs and the run transcript, under the `build/` a
#: product's `clean` removes.
#:
#: si#155 lists what the kernel writes into a product tree and `build/logs/` is already on it, so this
#: adds no directory, no `.gitignore` line and nothing new to clean. That a `clean` between two sittings
#: discards the state is the right direction: the walk is then walked again, which costs time and claims
#: nothing false. The opposite arrangement - state outliving a `clean` - is the one that can hand a person
#: answers belonging to a tree that is no longer there.
STATE_FILE = "acceptance-walk.json"

#: The state document's own version. A file written by a format this version does not know is not read
#: and not silently deleted either: `load_state` says which it found. si#177's rule, other sidecar.
STATE_FORMAT = 1

#: The two verdicts a person can give. A SKIPPED or PENDING step is ABSENT from the record rather than
#: carrying a third value, because both are derived - the first by `abort_after` from the refusal above
#: it, the second by the walk not having got there. Recording either would be a second source for a state
#: the runner already computes.
ANSWER_OK = "ok"
ANSWER_FAILED = "failed"

#: How wide the header's labels are padded. `steplog._LABEL`'s own width, so the walk's lines and si#148's
#: form ONE column in the file rather than two that nearly line up.
_LABEL = 14


class WalkAbandoned(BaseException):
    """The person stopped the walk while a step was being asked.

    A `BaseException` and not an `Exception`, for exactly the reason `steps.Step.run` gives about
    `KeyboardInterrupt`: this is the operator saying stop, not the step blowing up, and `run` must not
    turn it into a verdict. It leaves the step RUNNING, which is not a state a finished record may carry -
    `tui.run_walk` normalises it to PENDING once the app is down, where no thread can race it.
    """


# --- who, and against what --------------------------------------------------------------------------


def who(root: Path) -> str:
    """The person the record will name, taken from the product checkout's own git identity.

    A CLAIM AND NOT A CREDENTIAL, and the header says so in those words. Nothing here verifies that the
    name belongs to whoever pressed the keys. What it buys over `getpass.getuser()` alone is that a record
    made in a container says a person's name instead of `root`, which is the difference between a document
    worth attaching to a delivery and one worth nothing. The login user is the fallback rather than the
    answer for exactly that reason.
    """
    if shutil.which("git") is None:
        return getpass.getuser()
    name = run(["git", "-C", str(root), "config", "user.name"]).out.strip()
    email = run(["git", "-C", str(root), "config", "user.email"]).out.strip()
    if name and email:
        return f"{name} <{email}>"
    return name or email or getpass.getuser()


# --- selection ----------------------------------------------------------------------------------------


def parse_tags(tags: str) -> tuple[str, ...]:
    """The tag selection as tags, `@` optional and separators loose (comma or whitespace).

    Loose on the way in and canonical on the way out, so `@gate, documents` and `documents gate` are one
    selection rather than two spellings that would key two different resumes.
    """
    tokens = [token.strip().lstrip("@") for token in tags.replace(",", " ").split()]
    return tuple(sorted({token for token in tokens if token}))


def selection_text(wanted: Sequence[str]) -> str:
    """How the selection is written in the record and in the run key. `all scenarios` is a VALUE and not
    a blank: a record whose selection line is empty cannot be told from one whose selection was lost."""
    return " ".join(f"@{tag}" for tag in wanted) if wanted else "all scenarios"


def matches(feature: Feature, scenario: Scenario, wanted: Sequence[str]) -> bool:
    """Whether a scenario is in the selection.

    THE FEATURE'S OWN TAGS COUNT, and that is not a courtesy. pytest-bdd applies a feature-level tag to
    every scenario in the file and allure-pytest-bdd records it on every result, so a selection reading
    only `Scenario.tags` would walk a different set than the automatic mode selects - two modes, two
    answers, over one source. si#204's reader keeps the two apart on the model because the page prints
    them apart; the union is made here, once, where selecting happens.

    A TAG SELECTS FOR A RUN AND DOES NOT CLASSIFY A SCENARIO FOREVER, which is si#205's constraint and the
    reason there is no `@manual`: any tag a file already carries selects, so nothing has to be marked as
    belonging to one mode. ANY rather than ALL, and no negation - one tag is how a group is named, and an
    expression language is a second thing to learn for a case nobody has brought.
    """
    return not wanted or bool(set(wanted) & (set(feature.tags) | set(scenario.tags)))


def select(found: Sequence[Feature],
           wanted: Sequence[str]) -> tuple[list[tuple[Feature, tuple[Scenario, ...]]], list[str]]:
    """The selected scenarios grouped by feature, and the ADDRESSES of the ones left out.

    BOTH HALVES ARE RETURNED because both are evidence. si#205 puts it as a document rule: a record saying
    "passed" when twelve of forty were walked is a false document, so the twenty-eight reach the header by
    name. A count alone would not do it - a reader cannot tell which functionality went unverified from
    the number 28.
    """
    taken: list[tuple[Feature, tuple[Scenario, ...]]] = []
    left: list[str] = []
    for feature in found:
        chosen: list[Scenario] = []
        for scenario in feature.scenarios:
            (chosen.append(scenario) if matches(feature, scenario, wanted)
             else left.append(scenario.address))
        if chosen:
            taken.append((feature, tuple(chosen)))
    return taken, left


# --- what the walk was carried out against, and when it stops being true --------------------------------


def digest(found: Sequence[Feature]) -> str:
    """A sha256 over the QUESTIONS, not over the files.

    WHAT IS IN IT: every feature in path order, and for each one its runner spelling, its title, its free
    description and its tags, then every scenario's address and tags, then every step's keyword, text and
    payload lines. That is the whole of what a person is shown and the whole of what an address is built
    from, so anything that changes a question changes this - a reworded step, a renamed scenario, a new
    Examples row, a tag that moves a scenario in or out of a selection, a docstring under a step.

    WHAT IS DELIBERATELY NOT IN IT: comments, blank lines and indentation. Hashing the raw bytes would
    have been one line shorter and would invalidate a person's afternoon over a typo in a comment nobody
    was ever shown.

    It is one SIDE of the run key and never the whole of it. The feature files still saying the same thing
    does not mean the product does, which is what `RunKey.version` is for.
    """
    sha = hashlib.sha256()
    separator = chr(0)
    for feature in found:
        sha.update(f"F{separator}{feature.rel}{separator}{feature.name}{separator}"
                   f"{'|'.join(feature.tags)}{separator}"
                   f"{separator.join(feature.description)}\n".encode())
        for scenario in feature.scenarios:
            sha.update(f"S{separator}{scenario.address}{separator}"
                       f"{'|'.join(scenario.tags)}\n".encode())
            for step in scenario.steps:
                sha.update(f"T{separator}{int(step.background)}{separator}{step.announced}{separator}"
                           f"{separator.join(step.payload)}\n".encode())
    return f"sha256:{sha.hexdigest()}"


@dataclass(frozen=True)
class RunKey:
    """What a walk was carried out against - and therefore what must be unchanged for an interrupted walk
    to be CONTINUED rather than started again.

    THE INVALIDATION RULE IS THE DESIGN, exactly as in `simplon.checksum` (si#177) and for the same
    reason: being wrong here is SILENT. Twelve steps answered on Monday, the product rebuilt on Tuesday,
    the walk resumed on Wednesday - the record then claims twelve verifications against something that no
    longer exists, and every line of it reads correct. So the rule is four conditions and a refusal:

      1. `product` - the product's own name. Cheap, and it catches a state file that travelled.
      2. `version` and `revision` - `git describe --tags --always --dirty` and `git rev-parse HEAD` of the
         PRODUCT's own checkout, taken through `tasks.image.provenance` rather than derived here. Not
         thrift: that is the same pair stamped into the product's container image, so the record names
         what was verified by the string the artefact itself carries. A version of this module's own
         invention would name the product by something no artefact carries.
      3. `scenarios` - `digest` above. Catches every change to a question, including one that leaves the
         version alone because nothing was committed.
      4. `source` and `selection` - a walk of `@gate` is not a walk of `@documents`, and answers recorded
         for one are not answers to the other.

    WHEN ANY OF THEM MOVED, THE RESUME IS REFUSED. Not repaired, not partly replayed, not warned about and
    continued: `moved_from` names which of them moved and the walk stops. Continuing is the silent wrong
    answer, and starting over WITHOUT saying so is the same wrong answer with the earlier sitting's
    evidence thrown away as well - so a person who wants to start over says `--restart`, which discards
    the answers deliberately and says that it did.

    WHAT THE RULE STILL MISSES, listed rather than discovered later:

      * A CHANGE THAT LEAVES A DIRTY TREE DIRTY. `git describe --dirty` distinguishes clean from dirty and
        nothing finer, so two different uncommitted edits give the same `version`. The `scenarios` digest
        catches the subset of those that changed a question and nothing catches the rest. This is the
        biggest hole and it is the ordinary development case; the answer for a walk that has to BE
        evidence is to walk a committed tree, which is also when `version` is a tag rather than a sha.
      * A CHANGE DURING ONE SITTING. The key is taken when the walk starts and checked when it is resumed,
        so a product rebuilt between step three and step four is not seen at all. The same shape as
        si#177's stat-then-read window and the same answer: out of reach of anything that does not
        re-measure between every question.
      * A PRODUCT WHOSE VERSION CANNOT BE READ. `provenance` gives nothing for a tree that is not its own
        git checkout, and a key with no version could not see a rebuild. Such a walk may be STARTED and
        may never be RESUMED - `refuse_to_resume` says so in those words rather than resuming against a
        key that cannot fail.
      * A `clean` BETWEEN TWO SITTINGS, which removes the state with the rest of `build/`. Nothing false
        follows; the walk is simply walked again.
    """

    product: str
    version: str
    revision: str
    source: str
    selection: str
    scenarios: str

    #: What each part is called where a person reads it. Beside the fields rather than inside the message,
    #: so a part added here with no word for it is a `KeyError` and not a silent omission from the
    #: comparison - `moved_from` iterates THIS, not the dataclass's fields.
    LABELS: ClassVar[dict[str, str]] = {
        "product": "the product", "version": "the product version",
        "revision": "the product revision", "source": "the scenarios' source directory",
        "selection": "the selection", "scenarios": "the scenarios themselves"}

    def moved_from(self, earlier: "RunKey") -> list[str]:
        """Each part that differs, spelled `<what> (<then> -> <now>)`. Empty means the walk may go on."""
        return [f"{self.LABELS[name]} ({getattr(earlier, name)!r} -> {getattr(self, name)!r})"
                for name in self.LABELS if getattr(self, name) != getattr(earlier, name)]

    @property
    def resumable(self) -> bool:
        """False when the key carries no product version, so nothing in it could ever see a rebuild."""
        return bool(self.version)

    def as_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.LABELS}


def run_key(product: str, root: Path, source: str, selection: str,
            found: Sequence[Feature]) -> RunKey:
    """The key for this walk.

    `provenance` warns for itself when it has nothing to give, and its wording is an image build's
    ("the Dockerfile's own ARG defaults apply") because that is its other caller. Rather than rewrite
    three messages in a module this has no business editing, the consequence for a WALK is said here, once
    and immediately after: no version means no resume.
    """
    stamped = provenance(root)
    if not stamped:
        log.warn(f"no version could be derived for {product}, so a walk started now can be carried out "
                 f"but never continued in a second sitting - the state would have nothing to check the "
                 f"product against")
    return RunKey(product=product, version=stamped.get(VERSION_ARG, ""),
                  revision=stamped.get(REVISION_ARG, ""), source=source, selection=selection,
                  scenarios=digest(found))


# --- the state a sitting leaves behind ------------------------------------------------------------------


@dataclass
class State:
    """The answers the sittings so far produced, and the key they were given against."""

    key: RunKey
    #: One entry per sitting, oldest first: when it began, when it ended, and who drove it. The record
    #: prints them all, because si#205 asks that a reader be able to tell a walk done in one sitting from
    #: one resumed, and the only honest way to say that is to name the sittings.
    sittings: list[dict[str, str]] = field(default_factory=list)
    #: address -> step index (a STRING, because JSON object keys are) -> `{"verdict": ..., "at": ...}`.
    #: The instant is per STEP rather than per sitting: it is what lets the record say, on the one line
    #: that carries the verdict, that this step was answered on Monday and its neighbour on Wednesday.
    answers: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)

    def answer_for(self, address: str, index: int) -> dict[str, str]:
        """The recorded answer for one step, or `{}` when nobody has answered it."""
        return self.answers.get(address, {}).get(str(index), {})

    def record(self, address: str, index: int, accepted: bool, when: datetime) -> None:
        self.answers.setdefault(address, {})[str(index)] = {
            "verdict": ANSWER_OK if accepted else ANSWER_FAILED, "at": f"{when:%Y-%m-%d %H:%M:%S}"}

    def answered(self) -> int:
        return sum(len(steps) for steps in self.answers.values())

    def as_document(self) -> dict[str, object]:
        return {"format": STATE_FORMAT, "key": self.key.as_dict(), "sittings": self.sittings,
                "answers": self.answers}


def state_path() -> Path | None:
    """Where the state file goes, or None when there is nowhere to put it (no product registered)."""
    directory = steplog.log_directory()
    return None if directory is None else directory / STATE_FILE


def _object(value: object) -> dict[str, object]:
    """`value` as a JSON object, or a `TypeError` naming what stood there instead.

    IT REPLACED `dict(value)`, AND THE DIFFERENCE WAS MEASURED RATHER THAN REASONED ABOUT: a state file
    whose `answers` was written as `[]` was ACCEPTED, because `dict([])` is `{}`. Benign in that one
    spelling and not in the next - `[["a", {}]]` is a dict to the same call - so the reader was COERCING
    where its whole job is to refuse anything it cannot fully check (si#177's rule). The coercion also
    swallowed the shape into the message: the warning said "dictionary update sequence element #0 has
    length 1" for a document whose real fault was that a list stood where an object belongs.
    """
    if not isinstance(value, dict):
        raise TypeError(f"expected an object, found {type(value).__name__}")
    return {str(name): item for name, item in value.items()}


def _array(value: object) -> list[object]:
    """`value` as a JSON array, or a `TypeError` naming what stood there instead. `_object`'s twin."""
    if not isinstance(value, list):
        raise TypeError(f"expected an array, found {type(value).__name__}")
    return list(value)


def load_state(path: Path) -> State | None:
    """The state a previous sitting left, or None when there is none to be had - with a WARNING for every
    way that second answer can arise other than "there is no file".

    UNUSABLE IS NOT THE SAME AS MOVED, and keeping the two apart is this module's whole safety. A file
    that cannot be read, is not JSON, is not an object, carries a `format` this version does not know or
    is missing a part means the kernel does not know what was answered - so it claims nothing, the walk
    starts from the beginning, and every question is asked again. That is safe. A file that IS readable
    and whose key has MOVED is the dangerous one, because it holds answers that look applicable and are
    not; that is `refuse_to_resume`'s case and it stops the walk.

    It warns rather than passing silently, because a state file that exists and is not being used is
    exactly the situation in which a person expects to continue and is about to be asked forty questions
    again.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warn(f"{path} could not be read as a walk state ({exc}), so this walk starts from the "
                 f"beginning and nothing recorded earlier is claimed")
        return None
    found_format = document.get("format") if isinstance(document, dict) else None
    if not isinstance(document, dict) or found_format != STATE_FORMAT:
        log.warn(f"{path} is not a walk state this simplon can read (format {found_format!r}, expected "
                 f"{STATE_FORMAT}), so this walk starts from the beginning")
        return None
    try:
        stated = _object(document["key"])
        key = RunKey(**{name: str(stated[name]) for name in RunKey.LABELS})
        sittings = [{name: str(item) for name, item in _object(entry).items()}
                    for entry in _array(document["sittings"])]
        answers = {address: {index: {name: str(item) for name, item in _object(answer).items()}
                             for index, answer in _object(steps).items()}
                   for address, steps in _object(document["answers"]).items()}
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        log.warn(f"{path} is a walk state this simplon cannot fully check ({exc!r}), so this walk starts "
                 f"from the beginning rather than trusting half of it")
        return None
    return State(key=key, sittings=sittings, answers=answers)


def save_state(path: Path, state: State) -> Path | None:
    """Write the state; returns the path, or None when it could not be written - which is warned about
    and never fatal.

    The rule `steplog.write` states: a walk's verdict is what the person came for, and a read-only
    checkout is a reason to lose the ability to CONTINUE, never a reason to lose the answers already
    given. What differs from `steplog` is that the loss is not silent: without this file the next sitting
    asks everything again, and the person should hear that at the moment it happens.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state.as_document(), indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    except OSError as exc:
        log.warn(f"the walk state could not be written to {path} ({exc}), so this sitting cannot be "
                 f"continued later - the answers given are still in the record")
        return None
    return path


def refuse_to_resume(key: RunKey, earlier: State, path: Path) -> str:
    """Why this walk may not be continued, or "" when it may.

    The message names WHAT moved and both ways out, because a refusal saying only "the state is stale"
    leaves its reader to guess which of six things changed and whether walking again is the answer.
    """
    moved = key.moved_from(earlier.key)
    if moved:
        return (f"simplon: this walk cannot be continued. {earlier.answered()} step(s) were answered "
                f"against a different state of this product, and {'; '.join(moved)}. Resuming would "
                f"record those answers as verifications of what is here now, which they are not. Walk it "
                f"again with `--restart`, which discards them, or put the product back the way it was. "
                f"The state is {path}")
    if not key.resumable:
        return (f"simplon: this walk cannot be continued. No version could be derived for {key.product}, "
                f"so nothing in the recorded state could tell whether the product moved since the earlier "
                f"sitting, and {earlier.answered()} answer(s) would be replayed against an unknown. Walk "
                f"it again with `--restart`. The state is {path}")
    return ""


# --- the plan a person walks ------------------------------------------------------------------------------


def question(scenario: Scenario, index: int, step: GherkinStep, replayed: str) -> list[str]:
    """The lines the person is shown for one step, in the order they are read.

    The address first and the step itself last but one, because the pane is scrolled to the tail and the
    last thing written is the thing being answered. The two keys are named on EVERY step rather than once
    at the top: a footer is a reminder for somebody who already knows, and half of these sessions are
    somebody's first.
    """
    lines = [scenario.address,
             f"step {index + 1} of {len(scenario.steps)}"
             f"{' (from the feature background)' if step.background else ''}",
             "", f"    {step.announced}"]
    # `.strip()`, the way `acceptance._steps` renders the same payload onto the page: the lines carry the
    # indentation of the file they were written in, and re-indenting THAT under a step reads as a
    # staircase. The person and the reader of the document see one shape.
    lines += [f"      {line.strip()}" for line in step.payload]
    lines.append("")
    lines.append(f"already answered: {replayed}" if replayed else
                 "press  a  to accept this step, or  r  to refuse it - one key either way")
    return lines


def _plan_spec(help_text: str, *, leaf: bool = False, stop: bool = False) -> CommandSpec:
    """A `CommandSpec` for a plan node no manifest declared - see the module head on what borrowing this
    seam costs.

    `impl` names THIS command for a leaf, because `PlanNode.is_leaf` is `bool(spec.impl)` and a reference
    that resolves to nothing would be a second kind of lie to save a line. Nothing resolves it: `plan`
    hands the runner the steps it built. `depends_on` stays empty on purpose - it is read only by
    `steps.omitted_note`, which exists to explain a dependency planned somewhere else, and nothing in a
    walk is planned somewhere else.
    """
    return CommandSpec(impl="simplon.tasks.walk:walk" if leaf else "", help=help_text,
                       stop_on_failure=stop)


def plan(taken: Sequence[tuple[Feature, tuple[Scenario, ...]]], state: State,
         prompt: "Prompt") -> Pipeline:
    """The walk as a `Pipeline` the ordinary runner drives: root -> feature -> scenario -> step.

    The SCENARIO node carries `stop_on_failure`, which is the mapping's load-bearing half (module head).

    The leaf's dotted path is the step as it will be announced, numbered, so the left pane reads as a
    scenario and not as a column of forty identical-looking addresses; the ADDRESS travels in `Step.help`,
    which `steps.step_header` prints under every line of the transcript - so the RECORD stays unambiguous
    while the tree stays readable. That is si#148's own division between the tree (where am I) and the
    section header (what exactly is this), applied to a question instead of to a command.
    """
    feature_nodes: list[PlanNode] = []
    steps: list[Step] = []
    for feature, scenarios in taken:
        scenario_nodes: list[PlanNode] = []
        for scenario in scenarios:
            leaves: list[PlanNode] = []
            for index, step in enumerate(scenario.steps):
                label = f"{index + 1}. {step.announced}"
                help_text = scenario.address + _replay_note(state.answer_for(scenario.address, index))
                leaves.append(PlanNode(name=label, path=label, spec=_plan_spec(help_text, leaf=True)))
                steps.append(Step(label=label, command=label, help=help_text,
                                  stream=_answering(scenario, index, step, state, prompt)))
            scenario_nodes.append(PlanNode(
                name=scenario.name, path=scenario.name,
                spec=_plan_spec(f"{len(leaves)} step(s), walked by a person", stop=True),
                children=tuple(leaves)))
        feature_nodes.append(PlanNode(name=feature.rel, path=feature.rel,
                                      spec=_plan_spec(feature.name),
                                      children=tuple(scenario_nodes)))
    root = PlanNode(name="walk", path="test.walk",
                    spec=_plan_spec("acceptance scenarios answered by a person"),
                    children=tuple(feature_nodes))
    return Pipeline("test.walk", steps, False, root, root.path)


def _replay_note(answer: dict[str, str]) -> str:
    """What `Step.help` adds for a step somebody answered in an EARLIER sitting: the verdict and the
    instant. Empty for a step this sitting will ask.

    Per step and not per run, because "resumed at least once" on forty lines says nothing about which of
    the forty were answered when - and telling a walk done in one sitting from one spread over three is
    exactly what si#205 asks the record to make possible.
    """
    if not answer:
        return ""
    verdict = "accepted" if answer.get("verdict") == ANSWER_OK else "REFUSED"
    return f" - {verdict} in an earlier sitting at {answer.get('at', 'an unrecorded time')}"


def _answering(scenario: Scenario, index: int, step: GherkinStep, state: State,
               prompt: "Prompt") -> Callable[[Emit], Outcome]:
    """One step's body: show the question, then take its verdict from the person - or from the record.

    A REPLAY GOES THROUGH THE SAME BODY, which is why a resumed walk has no second path anywhere. What
    that costs is one cosmetic defect, named here so nobody has to find it: a replayed step's DURATION is
    this sitting's replay of it rather than the seconds the person spent, because `Step.run` stamps both
    ends itself and an action cannot reach back past them. The record says which steps those are, on every
    one of them, through `Step.help`.
    """
    def body(emit: Emit) -> Outcome:
        recorded = state.answer_for(scenario.address, index)
        replayed = (("accepted" if recorded.get("verdict") == ANSWER_OK else "refused")
                    + f" at {recorded.get('at', 'an unrecorded time')}" if recorded else "")
        lines = question(scenario, index, step, replayed)
        for line in lines:
            emit(line)
        if recorded:
            return Outcome(rc=0 if recorded.get("verdict") == ANSWER_OK else 1,
                           output="\n".join(lines))
        accepted = prompt.ask(f"{scenario.address} - {step.announced}")
        answered_at = datetime.now()
        state.record(scenario.address, index, accepted, answered_at)
        lines.append(f"answered: {'accepted' if accepted else 'REFUSED'} at "
                     f"{answered_at:%Y-%m-%d %H:%M:%S}")
        emit(lines[-1])
        return Outcome(rc=0 if accepted else 1, output="\n".join(lines))

    return body


# --- the person's end of it -------------------------------------------------------------------------------


class Prompt:
    """The seam a person's verdict arrives through: the runner's worker thread blocks in `ask`, the UI
    thread answers on a keypress.

    ONE QUESTION AT A TIME, and the plan guarantees it rather than a lock here: nothing in a walk declares
    `parallel:`, so `steps.schedule_for` produces a single sequence and exactly one step is ever inside
    `ask`. A `threading.Event` is then the whole mechanism.

    It knows nothing about Textual, which is what lets `tui._WalkApp` take it structurally and lets a test
    drive a walk with no terminal at all.
    """

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._verdict: bool | None = None
        self._question = ""
        self._abandoned = False

    @property
    def question(self) -> str:
        """The step being asked right now, or "" when none is. The UI reads it to decide whether a
        keypress means anything at all."""
        return self._question

    def ask(self, question: str) -> bool:
        """Block until somebody answers; raise `WalkAbandoned` when the walk was stopped instead."""
        self._verdict = None
        self._ready.clear()
        # CHECKED AFTER `clear()` and before the wait: `abandon` may have run while the previous step was
        # finishing, and a walk that was stopped between two questions has no keypress coming. Without
        # this the worker would block on an event nobody will ever set, and a `@work(thread=True)` thread
        # that never returns is a process that does not exit.
        if self._abandoned:
            raise WalkAbandoned(question)
        self._question = question
        self._ready.wait()
        self._question = ""
        if self._verdict is None:
            raise WalkAbandoned(question)
        return self._verdict

    def answer(self, accepted: bool) -> bool:
        """Record a verdict for the step being asked; False when nothing was being asked, so a stray
        keypress is a no-op rather than a signature."""
        if not self._question or self._ready.is_set():
            return False
        self._verdict = accepted
        self._ready.set()
        return True

    def abandon(self) -> None:
        """Release whoever is waiting, with no verdict. Idempotent, and safe when nothing is being asked -
        which is the case it exists for, since it is called on the way out of the app whether or not a
        question was open."""
        self._abandoned = True
        self._verdict = None
        self._ready.set()


# --- the record's own header ------------------------------------------------------------------------------


def header(key: RunKey, state: State, taken: Sequence[tuple[Feature, tuple[Scenario, ...]]],
           left: Sequence[str]) -> list[str]:
    """The lines a walk adds to si#148's transcript header - what was verified, by whom, against what, and
    what was NOT.

    It restates none of `started`, `environment`, `instance` or si#125's provenance line: `steplog
    .run_header` writes those and this is appended to it, in the same label column, so the file carries
    one header rather than two.
    """
    walked = sum(len(scenarios) for _, scenarios in taken)
    driver = state.sittings[-1].get("by", "?") if state.sittings else "?"
    lines = [f"{'walked by:':<{_LABEL}}{driver} (claimed, not verified)",
             f"{'verdicts:':<{_LABEL}}a person's judgement, one answer per Gherkin step - not a "
             f"measurement",
             f"{'product:':<{_LABEL}}{key.product} {key.version or '(no version could be derived)'}"
             f"{f' at {key.revision}' if key.revision else ''}",
             f"{'scenarios:':<{_LABEL}}{key.source} ({key.scenarios})",
             f"{'selection:':<{_LABEL}}{key.selection} - {walked} of {walked + len(left)} scenario(s) "
             f"in {len(taken)} feature file(s)"]
    for number, sitting in enumerate(state.sittings, start=1):
        lines.append(f"{f'sitting {number}:':<{_LABEL}}{sitting.get('started', '?')} to "
                     f"{sitting.get('ended') or 'in progress'}, driven by {sitting.get('by', '?')}")
    if left:
        lines.append(f"{'not walked:':<{_LABEL}}{len(left)} scenario(s) were not selected and carry no "
                     f"verdict in this record:")
        lines += [f"{'':<{_LABEL}}  {address}" for address in left]
    return lines


# --- the task ---------------------------------------------------------------------------------------------


def _no_selection(found: Sequence[Feature], wanted: Sequence[str], source: str) -> str:
    """The refusal for a selection that matched nothing, listing the tags these files really carry."""
    available = sorted({f"@{tag}" for feature in found for tag in feature.tags}
                       | {f"@{tag}" for feature in found
                          for scenario in feature.scenarios for tag in scenario.tags})
    total = sum(len(feature.scenarios) for feature in found)
    return (f"simplon: {selection_text(wanted)} matched none of the {total} scenario(s) under {source}, "
            f"so there is nothing to walk - and a record of an empty walk would carry a verdict over no "
            f"evidence. The tags these files carry: {', '.join(available) or '(none)'}")


def walk(source: str = DEFAULT_SOURCE, tags: str = "", by: str = "", restart: bool = False) -> int:
    """Walk the product's acceptance scenarios with a person answering each step.

    `source` is only ever read and takes si#204's default; `tags` selects (see `matches`); `by` names the
    person in the record and defaults to the checkout's own git identity; `restart` discards an earlier
    sitting's answers deliberately.

    IT REFUSES RATHER THAN DEGRADING, in four places, and every one of them is a check that could
    otherwise not fail:

      * NOT A TERMINAL. There is nobody to ask, so a walk here would produce a record of nothing with a
        verdict on it. There is no headless fallback, for the same reason there is no unattended mode.
      * AN EMPTY SELECTION. A walk of no scenarios would end `no steps` and `overall_rc` would call it
        rc 1 - which is right, but the reason has to be the tag that matched nothing rather than a run
        that merely looks as though it went wrong.
      * A STATE THAT MOVED, or one that cannot be checked. `refuse_to_resume`, and the argument is on
        `RunKey`.
      * TEXTUAL MISSING, which `tui.run_walk` refuses for itself where the import is.
    """
    ctx = context.current()
    if not sys.stdout.isatty():
        raise ValueError(
            "simplon: `test walk` puts a person through the acceptance scenarios one step at a time, so "
            "it needs a terminal to ask them in, and this is not one. Run it from a terminal; the "
            "automatic mode over the same scenarios is the product's own pytest-bdd suite.")
    found = features(ctx.root, source)
    wanted = parse_tags(tags)
    taken, left = select(found, wanted)
    if not taken:
        raise ValueError(_no_selection(found, wanted, source))

    key = run_key(ctx.name, ctx.root, source, selection_text(wanted), found)
    path = state_path()
    earlier = None if path is None or restart else load_state(path)
    if earlier is not None:
        refusal = refuse_to_resume(key, earlier, path if path is not None else Path(STATE_FILE))
        if refusal:
            raise ValueError(refusal)
        state = earlier
    else:
        if restart and path is not None and path.is_file():
            log.warn(f"--restart: the answers recorded in {path} are discarded and every step is asked "
                     f"again")
        state = State(key=key)
    started = datetime.now()
    state.sittings.append({"started": f"{started:%Y-%m-%d %H:%M:%S}", "ended": "",
                           "by": by or who(ctx.root)})

    prompt = Prompt()
    pipeline = plan(taken, state, prompt)
    from simplon.orchestrator.tui import run_walk    # local: Textual is not a kernel-wide import
    rc = run_walk(pipeline, prompt)
    state.sittings[-1]["ended"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    if path is not None:
        save_state(path, state)
    write_record(pipeline, started, header(key, state, taken, left))
    total = sum(len(scenario.steps) for _, scenarios in taken for scenario in scenarios)
    unreached = sum(1 for step in pipeline.steps if step.state is StepState.PENDING)
    log.ok(f"acceptance walk: {state.answered()} of {total} step(s) answered by "
           f"{state.sittings[-1]['by']}" + (f", {unreached} never reached" if unreached else ""))
    return rc


def write_record(pipeline: Pipeline, started: datetime, extra: Sequence[str]) -> Path | None:
    """Write the walk's record, which IS si#148's run transcript with the walk's own header under it.

    Here rather than inside `run_walk` because the header can only be composed once the app is DOWN: the
    last sitting's end time and the answers it produced are part of it, and a header written while the
    person was still answering would say `in progress` on the run it is the record of.
    """
    return write_run_transcript(pipeline, started, extra=extra)
