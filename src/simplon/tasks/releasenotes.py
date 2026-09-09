"""`test:release-notes` - a product's releases page against the tags and merges its repository carries.

WHY THIS IS THE KERNEL'S (si#89). The rule was written here, as `tests/test_releases_page.py`, and it
worked: it caught v0.7.1 going out with notes that described ONE of the seven merges the tag carried,
and it caught a section that described a pull request instead of a release. But a test in a product's
own `tests/` guards that product and nothing else, so netctl, cleon and agile-cockpit can tag, publish
and never write a word, and nothing says anything. That is the exact case netctl#1280 generalises: an
`impl:` belongs in the platform as soon as it needs no product knowledge.

And this needs none. Which versions EXIST is `git tag`; which ones the page DOCUMENTS is its headings;
which tickets landed between two tags is `git log`; and the four verdicts over those three are the same
in every repository. What is a product's own is DATA, and there are exactly three values of it - which
page holds the notes, from which release there has to be a section at all, and from which release a
section has to name every ticket in its range. All three arrive through the manifest's `releases:`
section and none of them is imported.

WHY A GATE AND NOT A RELEASE STEP. Folding this into `release:tag` was the live alternative, and it
would sit exactly where the damage is: one command, no bypass. It is rejected because the notes are
written BEFORE the tag - the tag points at a tree that already carries them (si#3) - so a guard that
only speaks when `release tag` is typed speaks after every cheap chance to fix it has passed. It would
also have caught neither of the two cases that prompted this work, both of which were pull requests days
away from a tag. The prepared release's range already ends at `HEAD`, so the same question is answerable
on every push, and being answerable continuously is what makes this a gate rather than a ceremony.

WHAT IS AND IS NOT CHECKED, and the line between them is the point. The PROSE of a release note cannot
be derived - it says what a change MEANT, which no tool knows - so nothing here reads a word of it. What
IS derivable is completeness: the merges between one tag and the next are a fact, and whether a section
mentions each of their numbers is a string search. That is the whole claim - a number appears - and it is
deliberately the weakest claim that would have caught the failure this exists for.

THE RANGE IS `<last tag>..HEAD` OF THE STATE BEING CHECKED, AND THAT IS SAID OUT LOUD. This guard fired
twice in one evening, both times correctly and both times as a surprise, because which state `HEAD` is
depends on the event: a `pull_request` run checks out `refs/pull/N/merge`, the branch merged with the
base, so a branch whose own tip is green goes red the moment the base moves; a `push` to the default
branch has the merge that just landed as `HEAD`, so a pull request's own ticket is in range from the
second it merges. Neither fact was hidden - neither was ever stated either. So every run of this gate
names what `HEAD` resolved to before it names anything else.

THE REFUSALS HERE ARE RUN-TIME, and that is a deliberate placement rather than an accident. The
`releases:` section is read inside the body, the shape `tasks.artifact` reads `artifacts:` with, so no
load-time refusal is added and the kernel's refusal census keeps its counts. A product meets these
messages only by asking for the gate.

GIT IS RUN DIRECTLY HERE rather than through `tasks.gitops`, following `tasks.image`. `gitops` keeps a
module-global `ROOT` that a caller configures, which is state this module has no use for: every function
below takes the root it reads, so two repositories can be asked about in one process - which is exactly
what this module's own tests do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from simplon import context, log
from simplon.run import run

#: The manifest section this task reads. Three values, and a product that declares none of them does not
#: place the command - which is the right outcome, and why this coordinate is offered and not placed.
SECTION = "releases"

#: A version as the PAGE spells one: `0.4.0`, three parts, no `v`. The tag carries the `v` and the
#: heading does not, so a product that wrote the tag into the manifest would get a floor matching no
#: section at all - which is why `v0.4.0` is refused here rather than helpfully stripped.
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")

#: A `## X.Y.Z` heading, which is what gives a version a section.
_HEADING = re.compile(r"^## (\d+\.\d+\.\d+)\s*$", re.MULTILINE)

#: The three spellings a merge subject names a ticket in, and it is MEASURED which source is complete
#: rather than chosen. Over `v0.4.0..v0.5.0` in the kernel's own repository - fourteen merges, the
#: population any candidate source has to produce whole:
#:
#:   | source                          | numbers | verdict                                        |
#:   | merge SUBJECTS, both spellings  |      14 | exactly the fourteen                           |
#:   | merge subjects, `#N` only       |      14 | but leaves one merge naming nothing            |
#:   | merge subjects AND bodies       |      19 | adds five tickets from EARLIER releases         |
#:   | every commit, subject and body  |      27 | adds eight more, and a foreign project's issue |
#:
#: The third row is why bodies are not read. A merge body argues, and arguing cites tickets from earlier
#: releases - demanding those in this section would make the rule overbroad in the direction hardest to
#: notice, because it would fail against notes that are correct.
#:
#: THE LIMIT IS RECORDED RATHER THAN IMPLIED. A subject is what the rule can read, so a ticket closed
#: inside another ticket's merge is invisible to it. That is a floor on what the notes must say, not a
#: claim that it is the ceiling.
_TICKET = re.compile(r"(?:si)?#(\d+)\b")
_BRANCH = re.compile(r"\bsi(\d+)-")

#: The subject GitHub composes when a pull request is merged from its web interface (si#103). The number
#: in it is the PULL REQUEST's, which is a statement about the vorgang and not about the work - and when
#: the notes PR is merged that way it names ITSELF, which no notes could have anticipated. So this
#: subject is not read for tickets; the commits it brought in are read instead.
_GITHUB_PR_MERGE = re.compile(r"Merge pull request #\d+ from \S+")

#: The subject GitHub composes for the merge it builds ITSELF - two full hashes and not one word more
#: (si#97). Matched in that EXACT machine format on purpose: a subject a person wrote is a subject a
#: person can put the number into, so a short hash, a branch name, or anything past the second hash is
#: still held to the rule.
_GITHUB_MERGE = re.compile(r"Merge [0-9a-f]{40} into [0-9a-f]{40}")

Version = tuple[int, ...]


@dataclass(frozen=True)
class Declared:
    """The product's three values, validated. The kernel knows nothing else about its release notes."""

    page: Path
    first: Version
    complete_from: Version


def version_of(text: str) -> Version | None:
    """`0.4.0` -> `(0, 4, 0)`; anything else -> None (a release candidate, a stray tag, a typo)."""
    match = _VERSION.fullmatch(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def spell(version: Version) -> str:
    """`(0, 4, 0)` -> `0.4.0`, the spelling a heading uses."""
    return ".".join(str(part) for part in version)


def tag_of(version: Version) -> str:
    """`(0, 4, 0)` -> `v0.4.0`, the spelling `git` knows the version by."""
    return "v" + spell(version)


# --- the product's declaration -----------------------------------------------------------------------

def declared() -> Declared | None:
    """The `releases:` section, or None with the reason already said.

    None rather than a raise, because the caller is a gate whose whole output is a return code and a
    sentence: a traceback out of a manifest typo would be the failure declining to say what it knows.
    """
    ctx = context.current()
    where = ctx.manifest_path.name
    section = ctx.manifest_data().get(SECTION)
    if not isinstance(section, dict) or not section:
        log.error(
            f"{where} has no `{SECTION}:` section, so this gate has nothing to measure. It needs three "
            f"values: `page:` (where the notes live, relative to the product root), `from:` (the first "
            f"release that must have a section at all) and `complete_from:` (the first section that "
            f"must name every ticket merged into its range)")
        return None

    page = str(section.get("page", "") or "").strip()
    if not page:
        log.error(f"{where}'s `{SECTION}:` section declares no `page:` - the kernel cannot guess where "
                  f"a product keeps its release notes, and a default would be one product's layout "
                  f"imposed on every other")
        return None
    resolved = (ctx.root / page).resolve()
    if Path(page).is_absolute() or not resolved.is_relative_to(ctx.root.resolve()):
        log.error(f"{where}'s `{SECTION}: page:` is '{page}', which is outside the product root "
                  f"({ctx.root}). The notes of a product are a file in its own checkout")
        return None

    floors: dict[str, Version] = {}
    for key in ("from", "complete_from"):
        raw = str(section.get(key, "") or "").strip()
        parsed = version_of(raw)
        if parsed is None:
            log.error(
                f"{where}'s `{SECTION}: {key}:` is '{raw}', which is not a version. It is spelled the "
                f"way the page spells a heading - three parts and no `v`, e.g. `0.4.0` - because that "
                f"is what it is compared against")
            return None
        floors[key] = parsed

    if floors["complete_from"] < floors["from"]:
        log.error(
            f"{where} declares `complete_from: {spell(floors['complete_from'])}` below "
            f"`from: {spell(floors['from'])}`, which would mean nothing: a release below `from:` is not "
            f"required to have a section at all, so requiring one to name every ticket is a statement "
            f"about a section the same manifest says may be absent")
        return None

    return Declared(page=resolved, first=floors["from"], complete_from=floors["complete_from"])


# --- the repository ----------------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    """`git -C <root> ...`, refusing to turn a broken checkout into an empty answer.

    An empty string here would read as "no tags" or "no merges" and make a repository git cannot even
    open come out GREEN, which is this project's recurring defect wearing a release note as a hat. So a
    non-zero rc raises, and the gate turns it into one sentence naming the command that failed.
    """
    result = run(["git", "-C", str(root), *args])
    if not result.ok:
        raise RuntimeError(f"`git {' '.join(args)}` failed in {root} (rc={result.rc}): "
                           f"{result.err.strip() or 'no output'}")
    return result.out


def released_versions(root: Path) -> list[Version]:
    """Every `vX.Y.Z` tag in the checkout, oldest first. The tag IS the version (si#3), so this is the
    authority the page is measured against - not a list maintained beside it."""
    found = [version_of(line.strip()[1:]) for line in _git(root, "tag").splitlines()
             if line.strip().startswith("v")]
    return sorted(version for version in found if version is not None)


def is_githubs_own_merge(subject: str) -> bool:
    """True for the ephemeral merge GitHub builds for a `pull_request` run, and for nothing else.

    That commit exists on no branch and is never pushed; it is `HEAD` in the `pull_request` checkout, so
    it lands inside the prepared release's range, and its subject is machine-written - there is no author
    to ask for a ticket and no place to write one. It is not a change the release carries.
    """
    return _GITHUB_MERGE.fullmatch(subject) is not None


def merges_in(root: Path, start: str, end: str) -> list[tuple[str, str]]:
    """`(sha, subject)` for every merge commit in `start..end`, newest first.

    MERGES AND NOT COMMITS, because a merge is the unit a release is assembled from: work happens on a
    branch and arrives in one commit whose subject says which ticket arrived. Counting commits instead
    would count a branch's internal history, which nobody promised to describe.
    """
    out = _git(root, "log", "--merges", "--format=%H\t%s", f"{start}..{end}")
    found = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\t")
        subject = subject.strip()
        if subject and not is_githubs_own_merge(subject):
            found.append((sha, subject))
    return found


def tickets_in(text: str) -> set[int]:
    """Every ticket number a piece of text names, in either spelling."""
    return {int(n) for n in _TICKET.findall(text)} | {int(n) for n in _BRANCH.findall(text)}


def tickets_of(root: Path, sha: str, subject: str) -> set[int]:
    """The tickets a merge NAMES, reading one level down when GitHub wrote the subject (si#103).

    An authored merge subject is a statement about the work, and it is read as one. GitHub's
    `Merge pull request #N from <branch>` is not: the number in it is the pull request's, so a notes PR
    merged that way names ITSELF and nothing could have anticipated it - a release died on exactly that,
    and no follow-up PR could have fixed it, because it would have brought its own number too.

    The assurance does not weaken. What the author wrote is still required; it is simply looked for where
    the author wrote it, which for a web-interface merge is the commits the merge brought in.
    """
    if not _GITHUB_PR_MERGE.fullmatch(subject):
        return tickets_in(subject)
    written = {number
               for line in _git(root, "log", "--no-merges", "--format=%s", f"{sha}^1..{sha}^2").splitlines()
               for number in tickets_in(line)}
    # The author's statement if there is one, else the only number there is. The fallback keeps the older
    # ranges honest - several merges from before the convention name nothing in their commits either, and
    # dropping them would excuse work rather than describe it.
    return written or tickets_in(subject)


def head_note(root: Path) -> str:
    """What `HEAD` is, in one line, and it is the line this gate exists to stop surprising people.

    The range every prepared section is measured over ends at `HEAD`, and which commit that is depends on
    the EVENT, not on the branch: a `pull_request` run checks out `refs/pull/N/merge`, so `HEAD` is
    GitHub's own merge of the branch with the base, and the range therefore carries whatever the base has
    gained since the branch was cut - a branch that is green on its own tip goes red here, correctly, and
    for a reason nothing used to state.
    """
    sha = _git(root, "rev-parse", "--short", "HEAD").strip()
    subject = _git(root, "log", "-1", "--format=%s", "HEAD").strip()
    if is_githubs_own_merge(subject):
        return (f"HEAD is {sha} {subject!r} - GitHub's own merge, which is what a `pull_request` run "
                f"checks out. Every range below therefore ends at your branch AS MERGED with the base, "
                f"not at your branch tip, and can carry merges your tip does not")
    return f"HEAD is {sha} {subject!r}"


# --- the page ------------------------------------------------------------------------------------------

def sections(body: str) -> dict[Version, str]:
    """Each `## X.Y.Z` heading's text, up to the next heading of the same level."""
    parts = _HEADING.split(body)
    found = {}
    for name, text in zip(parts[1::2], parts[2::2]):
        version = version_of(name)
        if version is not None:
            found[version] = text
    return found


def documented_versions(body: str) -> list[Version]:
    """Every version the page gives a section to, oldest first."""
    return sorted(sections(body))


def ranges_under_test(root: Path, body: str, first: Version) -> dict[Version, tuple[str, str]]:
    """Every documented version at or above the floor, with the `git` range its section describes.

    A RELEASED version's range ends at its own tag. The one version that is documented and NOT tagged is
    the release being prepared, and its range ends at `HEAD`, because that is what the tag will point at.
    Writing the notes before the tag is the workflow (si#3), so the prepared section has to be measurable
    before there is anything to measure it against.

    A version with no earlier tag is skipped: its range has no lower end, so there is nothing to compute.
    """
    released = released_versions(root)
    found: dict[Version, tuple[str, str]] = {}
    for version in documented_versions(body):
        if version < first:
            continue
        earlier = [other for other in released if other < version]
        if not earlier:
            continue
        found[version] = (tag_of(earlier[-1]), tag_of(version) if version in released else "HEAD")
    return found


# --- the gate --------------------------------------------------------------------------------------

def check() -> int:
    """Measure the product's releases page against the tags and merges its repository carries.

    Four verdicts, and each one exists for a failure that was silent before it:

      1. a release is tagged, published, and never written up;
      2. the page promises a version nobody can install;
      3. a merge lands naming no ticket, so no section can be asked to describe it - the precondition
         the fourth rests on, held as its own verdict rather than assumed, because a rule reading merge
         subjects is worth exactly what those subjects say;
      4. a section describes the pull request it was written in instead of the release it names.

    Every one of them reports EVERY offender rather than the first, because a gate that stops at one
    finding turns a five-minute fix into five runs.
    """
    spec = declared()
    if spec is None:
        return 1
    root = context.current().root
    try:
        return _assess(root, spec)
    except RuntimeError as exc:
        log.error(str(exc))
        return 1


def _assess(root: Path, spec: Declared) -> int:
    """The four verdicts over one product, separated from `check` so the manifest and the git failures
    are handled once, at the seam, rather than in the middle of the rule."""
    if not spec.page.is_file():
        log.error(f"the declared release notes are not there: {spec.page} does not exist. The manifest "
                  f"says this is where they live, so either the path is wrong or the page is missing")
        return 1
    body = spec.page.read_text(encoding="utf-8")

    released = released_versions(root)
    documented = documented_versions(body)
    log.info(f"{spec.page.name}: {len(documented)} documented, {len(released)} tagged, notes from "
             f"{spell(spec.first)}, complete from {spell(spec.complete_from)}")
    log.info(head_note(root))

    findings: list[str] = []
    ruled = 0

    # 1. A release at or above the floor with no section at all.
    scope = [version for version in released if version >= spec.first]
    ruled += len(scope)
    absent = [version for version in scope if version not in documented]
    if absent:
        findings.append("released but not on the page: "
                        + ", ".join(tag_of(version) for version in absent))

    # 2. A section for a version that carries no tag. Exactly ONE of those is legitimate and it is the
    #    release being prepared - the notes are written before the tag, so the highest documented
    #    version may be ahead of every tag. Two is either a release somebody forgot to cut or a number
    #    written down twice, and both promise a release nobody can install.
    ahead = sorted(version for version in documented if version not in released)
    highest = released[-1] if released else (0, 0, 0)
    ruled += len(ahead)
    unexplained = [version for version in ahead if version <= highest] + ahead[1:]
    if unexplained:
        findings.append(
            "the page documents versions that carry no tag and are not the one being prepared: "
            + ", ".join(tag_of(version) for version in sorted(set(unexplained)))
            + f" (highest tag: {tag_of(highest)})")

    # 3 and 4 share the ranges, and each range is REPORTED whether or not it has a finding: the range
    #   and what HEAD resolved to are the two facts that make a red legible, and a run that prints them
    #   only on failure teaches nobody why a green run was green either.
    body_of = sections(body)
    for version, (start, end) in sorted(ranges_under_test(root, body, spec.first).items()):
        merges = merges_in(root, start, end)
        silent = [subject for sha, subject in merges if not tickets_of(root, sha, subject)]
        merged = {number for sha, subject in merges for number in tickets_of(root, sha, subject)}
        named = tickets_in(body_of[version])
        held = version >= spec.complete_from
        missing = sorted(merged - named) if held else []
        ruled += len(merges)
        log.info(f"  {tag_of(version):<10} {start}..{end}  {len(merges)} merges, {len(merged)} tickets, "
                 + (f"{len(merged & named)} named" if held else "not held to completeness"))
        if silent:
            findings.append(
                f"{start}..{end}: these merges name no ticket in their subject, so no release section "
                f"can be asked to describe them: " + "; ".join(repr(s) for s in silent)
                + ". A merge subject is where a release range says what it carries - write the number "
                  "into it (`#42`, `si#42`, or a `si42-` branch name), or this gate cannot see the "
                  "change at all")
        if missing:
            findings.append(
                f"the {tag_of(version)} section names {len(merged) - len(missing)} of the {len(merged)} "
                f"tickets merged into {start}..{end}; missing: "
                + ", ".join("si#" + str(number) for number in missing))

    # RED WHEN THERE IS NOTHING, because a gate that ruled on nothing passes exactly like one that ruled
    # on fifty. That is this repository's most-hunted defect, and a release-notes gate is a place it
    # would hide well: a floor above every tag, a page whose headings stopped matching, a checkout with
    # no tags fetched, and the run says OK.
    if not ruled:
        log.error(
            f"this gate ruled on NOTHING and is therefore not reporting a pass. No release at or above "
            f"{spell(spec.first)} carries a tag here and no documented section has a measurable range. "
            f"Either the floor is above every release this product has cut, or the checkout has no tags "
            f"(a shallow or tag-less clone does that), or the page's headings are not `## X.Y.Z`")
        return 1

    if findings:
        for finding in findings:
            log.error(finding)
        return 1

    log.ok(f"the release notes are complete: {ruled} tags, sections and merges ruled on, and every "
           f"section from {spell(spec.complete_from)} on names every ticket its range carries")
    return 0
