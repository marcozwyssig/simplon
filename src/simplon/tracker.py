"""A refused acceptance step becomes a bug ticket on the product's tracker (si#206).

WHY THE KERNEL HAS THIS AT ALL. si#205 gave a person a way to say no, one keypress, and put the no in a
run transcript that `steplog` overwrites on the next run of anything in the same tree. That is a verdict
with a lifetime of one command. What the customer's no has to become is an artefact somebody else can
find next week: the step they refused, their reason in their words, the product version it was refused
against, and the scenario it belongs to. A ticket is what this family of repositories already uses for
that, so this opens one.

MANUAL MODE ONLY, and it is a decision rather than a first slice. The obvious next move is to have the
automatic gate do the same on a red pytest-bdd run, and it is declined: one broken build becomes forty
tickets and a flaky scenario becomes a new ticket every night, which is how a tracker stops being read.
Nothing here is reachable from `test suite`; `tasks.walk` is the only caller, and it calls this after a
PERSON has said no.

THE KERNEL DOES NOT KNOW WHICH TRACKER A PRODUCT USES, and the narrow version of that is what is built.
`gh` is reached for in three other places here (`tasks.asset`, `tasks.gitops`, `githubpackages`), so
GitHub is the plausible default rather than the only answer, and `KINDS` below is the seam: one entry, a
`kind:` the manifest names, and a second tracker is a second function in that mapping and no change at
any call site. What is ALREADY general is the half that would otherwise leak product knowledge into the
kernel - the destination, the labels and the wording all arrive through the manifest's `tracker:`
section, the way `releases:` and `claude:` arrive.

WHERE THE LINE BETWEEN THE PRODUCT'S WORDING AND THE KERNEL'S EVIDENCE IS DRAWN, because it is not
obvious and it is not "all of it is the product's". The TITLE is entirely the product's, a format string
over the fields in `TITLE_FIELDS`, and there is no kernel fallback for it: a kernel-invented title is the
kernel wording a bug, which is what this ticket forbids. The PREAMBLE is the product's too, free prose
prepended to the body. The EVIDENCE BLOCK is the kernel's and is not configurable, because si#206's
second requirement is a rule about what a ticket must carry - "a ticket reading 'acceptance test failed'
is worse than none, because it looks like the work was done" - and a rule a product can word away is not
one.

THE IDENTITY, AND WHY THE LOOKUP HAS TWO LEVELS. One ticket per scenario per version, not per run, so the
identity is sha256 over exactly (product, version, address) and it is written into the body as
`marker_line`. `open_ticket` searches the tracker for that digest before creating anything.

That search alone is NOT enough, and the reason was measured rather than assumed: GitHub's issue search
is an INDEX, not a read of the table, and it is not read-your-writes. An issue created and searched for a
few seconds later comes back as no result, so two walks in one afternoon over the same refusal would open
two tickets - the exact defect this is here to prevent. So `tasks.walk` keeps what was opened in the walk
state and consults that first; this module's search is the level that survives a `clean`, a second
checkout or a colleague's machine, where the index has long since caught up. Neither level alone is
right: the state is immediately consistent and local, the search is global and late.

AND THE SEARCH RESULT IS VERIFIED HERE rather than trusted. GitHub's issue search tokenises, so a query
for one digest can return neighbours; `_matching` keeps only an issue whose body really contains the
marker line. A fuzzy match accepted as "already open" would be worse than a duplicate - it would file a
refusal against somebody else's bug and report success.

NOTHING IN HERE RAISES AT THE CALLER. Every failure - `gh` missing, a token without scope, a host that is
down, an answer that is not JSON, a title the product mis-spelled - comes back as a `Ticket` carrying a
`problem` and no url. That is si#206's third requirement and it is a shape rather than a promise: the
walk state is written BEFORE this module is reached (`tasks.walk.walk`), so a refusal is already durable
when the network is tried, and a run that could not open a ticket says so and can open it on the next
sitting. The opposite arrangement - a raise out of here - would end the walk after the answers were given
and before the record was written.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass

from simplon import context, log, run

#: The manifest section this module reads. A product that declares none opens no tickets, and a walk with
#: a refusal in it says so by name rather than passing over it in silence - `declared` is only ever called
#: when there is something to file, so the sentence lands where it is useful.
SECTION = "tracker"

#: The one tracker this kernel implements, and the value `kind:` takes when a product leaves it out.
KIND_GITHUB = "github"

#: kind -> the pair of functions that reach it: (find an issue carrying this identity, open one).
#: THE SEAM, named rather than built out. A second tracker is an entry here; nothing above it changes,
#: because `open_ticket` already talks to this mapping and not to `gh`. It is a mapping of one on purpose:
#: si#206 says to build the narrow version with the seam named if the general one is more than the ticket
#: can carry, and a plugin protocol for a population of one is the abstraction this repository removes.
#: The day a product declares `kind: gitlab`, the work is two functions and no redesign.
KINDS = (KIND_GITHUB,)

#: The line the identity travels in, and the line the lookup verifies. Visible prose rather than an HTML
#: comment, because a person reading the ticket is the other consumer of it: they should be able to see
#: why a second walk did not open a second ticket.
MARKER = "simplon-walk-id:"

#: What a product's `title:` may name. Declared rather than derived off `Refusal`'s fields, so that adding
#: a field to the evidence does not silently widen a product's template surface - and so a mis-spelling is
#: answered with the list of what exists.
TITLE_FIELDS = ("product", "version", "revision", "address", "feature", "scenario", "step",
                "step_number", "step_total")

#: The byte the identity's three parts are joined by. NUL cannot occur in a product name, a
#: `git describe` output or a Gherkin address, so `wid` + `get` and `widget` + `` cannot produce one
#: digest. Concatenating with nothing would have been one character shorter and would make two different
#: walks share a ticket.
_JOIN = chr(0)


# --- the product's declaration --------------------------------------------------------------------------


@dataclass(frozen=True)
class Destination:
    """Where a ticket goes and how the product words it. Every field comes out of the manifest."""

    kind: str
    #: `owner/name`, or "" to let `gh` resolve the repository from the checkout's own remote. Left
    #: optional because that is what `gh` does everywhere else here, and a product whose tracker is its
    #: own repository should not have to say its name twice.
    repo: str
    labels: tuple[str, ...]
    title: str
    preamble: str


def declared() -> Destination | None:
    """The `tracker:` section, or None with the reason already said.

    None and a `log.error` rather than a raise, the shape `tasks.releasenotes.declared` uses and for the
    same reason twice over: the caller is a walk that has just collected a person's answers, so a
    traceback out of a manifest typo would throw away the sitting, and si#206 requires that a tracker
    problem never costs a refusal.
    """
    ctx = context.current()
    where = ctx.manifest_path.name
    try:
        document = ctx.manifest_data()
    except RuntimeError as exc:
        # `manifest_data()` raises this for a manifest it cannot read or parse. Inside the try for the
        # reason the whole module is written around: this is reached after a person has answered a walk,
        # and a YAML typo answered with a traceback would take the record down with it.
        log.error(f"{exc} - so no ticket could be opened for the refusals this walk recorded")
        return None
    section, blame, _ = context.section(document, SECTION)
    if blame or not section:
        log.error(
            f"{where} has no `{SECTION}:` section, so a refused step cannot become a ticket - the "
            f"refusals are in the walk's record and nothing was filed. The section needs a `title:` (the "
            f"product's own wording for the bug) and takes `kind:` (default {KIND_GITHUB}), `repo:` "
            f"(default: the checkout's own remote), `labels:` and `preamble:`")
        return None

    kind = str(section.get("kind", "") or KIND_GITHUB).strip()
    if kind not in KINDS:
        log.error(f"{where}'s `{SECTION}: kind:` is '{kind}', which this simplon cannot reach. It "
                  f"implements: {', '.join(KINDS)}")
        return None

    title = str(section.get("title", "") or "").strip()
    if not title:
        log.error(
            f"{where}'s `{SECTION}:` section declares no `title:`, and the kernel will not word a "
            f"product's bug for it. It is a format string over "
            f"{', '.join('{' + name + '}' for name in TITLE_FIELDS)}")
        return None

    raw_labels = section.get("labels") or ()
    labels = tuple(str(label).strip() for label in raw_labels if str(label).strip()) \
        if isinstance(raw_labels, (list, tuple)) else ()
    return Destination(kind=kind, repo=str(section.get("repo", "") or "").strip(), labels=labels,
                       title=title, preamble=str(section.get("preamble", "") or "").strip())


# --- what is being filed ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Refusal:
    """One refused step, with everything a ticket has to carry, already resolved.

    A VALUE AND NOT A VIEW ONTO THE WALK, deliberately: this module reads no state file and no feature
    file, so the evidence that reaches a tracker is exactly what `tasks.walk` decided to send and can be
    seen in one place. It is also what lets the whole of this module be driven without a walk.
    """

    address: str
    feature: str
    scenario: str
    step: str
    step_number: int
    step_total: int
    #: What the person said, in their words. "" when they were asked and gave none - which the body says
    #: in those words rather than leaving a blank line that reads as "no comment was possible".
    said: str
    at: str
    by: str
    product: str
    version: str
    revision: str
    source: str
    selection: str

    @property
    def fields(self) -> dict[str, object]:
        """What a product's `title:` may interpolate. `TITLE_FIELDS` is the list, this is the values."""
        return {name: getattr(self, name) for name in TITLE_FIELDS}


@dataclass(frozen=True)
class Ticket:
    """What came of one refusal. `url` empty and `problem` set means no ticket, and the run says so."""

    address: str
    identity: str
    url: str = ""
    #: True when the ticket was already there - the idempotence property, visible in the record rather
    #: than merely true.
    existed: bool = False
    problem: str = ""


def identity(product: str, version: str, address: str) -> str:
    """The digest that makes a second ticket for one scenario at one version impossible.

    THE THREE PARTS ARE THE WHOLE RULE. `product` because a state file and a tracker can be shared;
    `version` because si#206 says one ticket per scenario per VERSION, so a refusal that survives a
    release is a new ticket and not a comment on an old one; `address` because that is the scenario, in
    allure-pytest-bdd's own spelling (si#204), so the ticket joins the machine's results on the same key
    the human verdict does.

    PER SCENARIO AND NOT PER STEP, which the walk's own shape already guarantees rather than this
    enforcing it: `stop_on_failure` on the scenario node means a scenario stops at its first refusal, so
    there is at most one refused step in it. Keying on the step as well would therefore change nothing
    today and would open a second ticket the day that flag moved.
    """
    payload = _JOIN.join((product, version, address)).encode()
    return hashlib.sha256(payload).hexdigest()


def marker_line(ident: str) -> str:
    """The line the identity is written into the ticket body as, and the line a lookup verifies."""
    return f"{MARKER} {ident}"


def title_for(destination: Destination, refusal: Refusal) -> str:
    """The product's `title:` with this refusal filled in.

    A `KeyError` naming the fields that exist when the template names one that does not. It is caught in
    `open_ticket` and turned into a `problem`, so a manifest typo costs a ticket and never a walk - but it
    raises HERE rather than returning a half-rendered string, because a title reading `{sceanrio}` is the
    kind of artefact that looks like the work was done.
    """
    try:
        return destination.title.format(**refusal.fields)
    except KeyError as exc:
        raise KeyError(f"the `{SECTION}: title:` names {exc}, which is not a field of a refused step. "
                       f"It may name: {', '.join(TITLE_FIELDS)}") from exc


def body_for(destination: Destination, refusal: Refusal, ident: str) -> str:
    """The ticket's body: the product's preamble, then the kernel's evidence, then the identity.

    THE ORDER IS FOR THE READER RATHER THAN FOR THE PARSER. What a person opening this ticket needs
    first is the product's own sentence about what such a ticket means; what they need next is which
    scenario, which step and what was said; the marker is last because nothing but a lookup reads it.
    """
    lines: list[str] = []
    if destination.preamble:
        lines += [destination.preamble, ""]
    lines += [
        f"**{refusal.scenario}** was refused while a person walked "
        f"{refusal.product}'s acceptance scenarios.",
        "",
        f"- scenario: `{refusal.address}`",
        f"- feature: {refusal.feature}",
        f"- refused at step {refusal.step_number} of {refusal.step_total}: `{refusal.step}`",
        f"- product version: `{refusal.version or '(none could be derived)'}`"
        + (f" at revision `{refusal.revision}`" if refusal.revision else ""),
        f"- scenarios read from: `{refusal.source}`, selection: {refusal.selection}",
        f"- refused on {refusal.at} by {refusal.by} (claimed, not verified)",
        "",
        "What they said:",
        "",
    ]
    lines += ([f"> {line}" for line in refusal.said.splitlines()] if refusal.said
              else ["> no reason was given - the step was refused and the question was left unanswered"])
    lines += [
        "",
        "This ticket was opened by `simplon test walk`. Its identity is the product, the version and the "
        "scenario address, so walking the same scenario again at the same version finds this ticket "
        "instead of opening another.",
        "",
        marker_line(ident),
    ]
    return "\n".join(lines)


# --- reaching the tracker ---------------------------------------------------------------------------------


def _where(destination: Destination) -> list[str]:
    """`--repo owner/name`, or nothing at all so `gh` reads the checkout's own remote."""
    return ["--repo", destination.repo] if destination.repo else []


def _matching(listing: str, ident: str) -> str:
    """The url of the issue in `listing` whose body really carries this identity, or "".

    The exact match is made HERE and not left to the query. GitHub's issue search tokenises a body, so a
    query for one digest can answer with a neighbour, and an issue accepted on the strength of the search
    alone would file a customer's refusal against somebody else's bug and report success.
    """
    for issue in json.loads(listing) or []:
        if marker_line(ident) in str(issue.get("body", "")):
            return str(issue.get("url", ""))
    return ""


def _github_find(destination: Destination, ident: str) -> tuple[str, str]:
    """(url, problem) for an existing ticket carrying `ident`. Both empty means "none, and that is fine".

    `--state all`, because a refusal that was filed and CLOSED must not be filed again: the second ticket
    would arrive with no memory of why the first was closed, which is the duplicate this exists to
    prevent wearing a different hat.
    """
    found = run.run(["gh", "issue", "list", *_where(destination), "--state", "all", "--search",
                     f"{ident} in:body", "--limit", "50", "--json", "number,url,body"])
    if not found.ok:
        return "", (f"the tracker could not be searched for an existing ticket "
                    f"({(found.err or found.out).strip() or f'gh exited {found.rc}'})")
    try:
        return _matching(found.out, ident), ""
    except (ValueError, AttributeError) as exc:
        return "", f"the tracker's answer could not be read as a list of issues ({exc})"


def _github_create(destination: Destination, title: str, body: str) -> tuple[str, str]:
    """(url, problem) for a newly opened ticket.

    `--body-file -` rather than `--body`: a body carrying a person's own words, a data table and a
    docstring has no business on an argv, where the length limit is the host's and the quoting is the
    shell's.
    """
    labels = [flag for label in destination.labels for flag in ("--label", label)]
    made = run.run(["gh", "issue", "create", *_where(destination), "--title", title,
                    "--body-file", "-", *labels], input_text=body)
    if not made.ok:
        return "", (f"the ticket could not be created "
                    f"({(made.err or made.out).strip() or f'gh exited {made.rc}'})")
    return made.out.strip().splitlines()[-1].strip() if made.out.strip() else "", ""


def open_ticket(destination: Destination, refusal: Refusal) -> Ticket:
    """Find or open the one ticket for this refusal, and never raise.

    LOOK UP, THEN CREATE, AND A FAILED LOOKUP IS NOT AN EMPTY ONE. A search that errored returns here
    without creating anything: treating "I could not ask" as "there is none" is precisely how a broken
    token opens a duplicate on every run, which is the failure mode si#206's idempotence requirement is
    about. The cost is that a tracker which is down files nothing; that is the right side to fail on,
    because the refusal itself is already in the walk state before this is reached.
    """
    ident = identity(refusal.product, refusal.version, refusal.address)
    if shutil.which("gh") is None:
        return Ticket(refusal.address, ident,
                      problem="`gh` is not on this host's PATH, so no ticket could be opened")
    try:
        title = title_for(destination, refusal)
    except KeyError as exc:
        return Ticket(refusal.address, ident, problem=str(exc.args[0]))

    url, problem = _github_find(destination, ident)
    if problem:
        return Ticket(refusal.address, ident, problem=problem)
    if url:
        return Ticket(refusal.address, ident, url=url, existed=True)

    url, problem = _github_create(destination, title, body_for(destination, refusal, ident))
    return Ticket(refusal.address, ident, url=url, problem=problem)
