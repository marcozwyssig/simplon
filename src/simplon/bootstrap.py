"""simplon.bootstrap - scaffold a fresh product onto the delivery orchestrator (netctl#651 strand 4).

A brand-new product has no shim, no manifest and no product package yet, so it cannot reach the kernel
through its own CLI. This module is the ONE kernel entry that runs WITHOUT a product context: it writes a
minimal, valid product skeleton and prints the next steps, after which the new product configures only its
`<product>.yaml`.

Run it standalone (with `simplon` installed, e.g. `pip install simplon`)::

    simplon init [<product>] [--dir DIR] [--orch-dir DIR] [--force]

`python -m simplon.bootstrap <product> ...` keeps working for anyone who has it in muscle memory, but
the console script is the entry point the README documents.

It renders, mirroring the shape netctl's own `netctl.yaml` + `netctl.sh` use but stripped to the bones:

    <product>.sh                                     the entry point (bash): declares the four LAUNCH_*
                                                     params, provisions a host venv, execs the CLI
    <product>.cmd                                    the same entry point for Windows (cmd.exe)
    <product>.yaml                                   the starter manifest (tasks/groups tree/
                                                     environments the Pydantic loader accepts)
    <orch-dir>/requirements.txt                      the host-venv deps: the kernel pinned by version
                                                     (`simplon==...`) + product-only pins
    <orch-dir>/src/python/orchestrator/
        __init__.py                                  the product package
        __main__.py                                  `python -m orchestrator` entry
        cli.py                                       composition root: root Typer app + assemble
                                                     (step_context binds the `all` aggregate) + main
        paths.py                                     the ProductContext wiring (simplon.context); repo root
                                                     found by walking up to the manifest marker, not a depth
        environments.py                              the EnvironmentProvider (its three product values)

`<orch-dir>` is `deploy/provision/orchestrator` unless `--orch-dir` says otherwise (#4, si#130). It is the
block LAUNCH_ORCH_DIR points at, and both shims derive their venv, their requirements file and PYTHONPATH
from that one variable, so the whole block moves together. The package name stays `orchestrator` under any
layout - it is an identifier on PYTHONPATH, not a location.

The generated manifest VALIDATES through `simplon.orchestrator.manifest.load`; the generated `paths.py`
registers a `ProductContext` exactly as netctl's adapter does, so the new product has a working,
manifest-driven CLI right away (`./<product>.sh help`) - the launcher provisions its own venv and installs
the pinned kernel from PyPI on first run; nothing needs vendoring.

Design / scope (best-effort MINIMAL slice; netctl#651 strand 4 is under-specified on purpose):

    IN this slice
      - a starter manifest in the COMMAND TREE form that loads clean and shows ALL FIVE phases of the
        CI/CD loop plus `support` (si#33), each holding at least one command: an agnostic group that
        collapses to one flat command (`build`), two env-first groups (`deploy`, `monitor`), two commands
        that place a catalogue coordinate rather than a body of their own (`release tag`,
        `support install`), a WORKING aggregate (`all` is an impl-less `depends_on: [build, up]` command
        the kernel binds via assemble(step_context=...), so `<product> all` runs build->up, not a dead
        placeholder) and the env matrix;
      - the full product-adapter wiring (paths/environments/cli/__main__) so the CLI actually assembles;
      - the two launchers (`.sh` + `.cmd`) + requirements (the kernel pinned by version), so
        `./<product>.sh help` runs on a fresh clone with nothing to vendor;
      - PURE render (text only, no I/O, no yaml/pydantic import) split from the file-writing, so the manifest
        can be validated and the file set asserted in unit tests;
      - clobber-safety: refuses to overwrite an existing file unless `--force`.

    DEFERRED to a fuller scaffolder (documented, deliberately NOT built here)
      - a `bootstrap`/`init` subcommand woven into an assembled product CLI (the `simplon` console
        script covers the pre-product case, which is the only one that cannot go through a product);
      - `git init` automation (side-effecting VCS state); a one-command scaffold + verify flow is left
        to a repo-root wrapper script, deferred here;
      - schema-per-section docs, includes/anchors and a `--profile` menu (network-lab vs plain-service) that
        seeds a richer manifest;
      - product-name -> package-name derivation (the package is the fixed identifier `orchestrator`, as in
        netctl, so any product slug incl. hyphens works without sanitisation);
      - a post-scaffold `verify` that boots the generated CLI headless and asserts the surface.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import simplon
from simplon.run import run

# A product name is a lowercase slug: it becomes the shim/manifest filename, the manifest `product:` label,
# the LAUNCH_PRODUCT diagnostic token and the `<PRODUCT>_ENV` variable stem. The package itself is the FIXED
# identifier `orchestrator` (as in netctl), so a hyphenated slug never has to be a Python identifier.
_PRODUCT_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# The generated product package is always `orchestrator` (LAUNCH_MODULE), mirroring netctl. The BLOCK DIR
# below it is LAUNCH_ORCH_DIR: it holds `.venv`, `requirements.txt` and `src/python/`, and it is the part
# that MOVES (#4). The package NAME does not move with it: it is an identifier resolved on PYTHONPATH,
# which the shim points at `$LAUNCH_ORCH_DIR/src/python` wherever that is. `paths.py` finds the repo root
# by walking up to the manifest marker (netctl#737), so a deeper block dir needs no hand-edit either.
#
# THE DEFAULT IS WHERE THE BLOCK ACTUALLY GOES (si#130), and it did not used to be. `orchestrator/` at the
# target root was the layout this scaffolder grew up in and nobody else's practice: netctl passes
# `deploy/provision/orchestrator`, biz-cockpit passes it, and si#24 moved the kernel's own block under
# `deploy/` too, because each of their structure rules reserves the repository root. So the old default
# was a shape every consumer corrected on the command line, and the page that documented it taught the
# layout twice - once as shown, once as corrected four lines below.
#
# It is still a PARAMETER and not a decree, and the alternative simply changed sides: a product that owns
# its repository root now passes `--orch-dir orchestrator`, which is the mirror image of what every
# product passed before. Nothing existing moves - every current consumer already states the value it
# wants, and this changes what a NEW scaffold does.
DEFAULT_ORCH_DIR = "deploy/provision/orchestrator"

# The Windows drive prefix (`C:`, `c:/...`): absolute, and neither the leading-slash nor the `..` check
# would catch it on its own.
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def pkg_dir_for(orch_dir: str) -> str:
    """The generated package's directory, relative to the scaffold target, for a given block dir."""
    return f"{orch_dir}/src/python/orchestrator"


def validate_relative_dir(value: str, what: str, hint: str, *, inside: str = "the target directory") -> str:
    """Return the normalised directory if `value` is a plain relative path, else raise ValueError naming
    `what` (the caller's word for the value) and `hint` (what a good one looks like).

    Checked before anything acts on the path, so a bad value costs nothing: an absolute path or one with a
    `..` in it would land OUTSIDE the directory the caller named - silently, and over whatever happens to
    live there. Refuse it loudly instead. `\\` is refused rather than translated, because a value carrying
    both separators is a guess about which one was meant.

    Shared rather than restated: `--orch-dir` scaffolds INTO the path (#4) and the site build's `source`
    and `output` are read from a manifest and then handed to `shutil.rmtree` (#2), so the second one turns
    a leading slash into a deleted directory somewhere else entirely. Same rule, same escape, one place.
    """
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError(f"{what} {value!r} is empty; {hint}")
    if "\\" in trimmed:
        raise ValueError(f"{what} {value!r} is invalid: '/' is the separator here, not '\\'; {hint}")
    if trimmed.startswith("/") or _DRIVE_RE.match(trimmed):
        raise ValueError(
            f"{what} {value!r} is invalid: it must be relative, so that it lands under "
            f"{inside} and nowhere else; {hint}")

    segments = trimmed.rstrip("/").split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ValueError(
                f"{what} {value!r} is invalid: {segment!r} is not a directory name, and a "
                f"path that climbs or doubles back does not stay relative to {inside}; {hint}")
    return "/".join(segments)


def validate_orch_dir(value: str) -> str:
    """Return the normalised block directory if it is a plain relative path, else raise ValueError. The
    rule and its reasoning live in `validate_relative_dir`; this names the value and the good example."""
    return validate_relative_dir(
        value, "orchestrator directory",
        f"give a plain relative path under the scaffold target, e.g. {DEFAULT_ORCH_DIR!r} (the default) "
        f"or 'orchestrator' for a product that owns its repository root; the Windows shim gets its "
        f"backslashes written for it",
        inside="the target directory")


def validate_product_name(name: str) -> str:
    """Return the trimmed product name if it is a legal lowercase slug, else raise ValueError. Enforced up
    front so a bad name fails loudly here, not as a broken filename / manifest label downstream."""
    trimmed = (name or "").strip()
    if not _PRODUCT_RE.match(trimmed):
        raise ValueError(
            f"product name {name!r} is invalid; use a lowercase slug matching {_PRODUCT_RE.pattern} "
            f"(a letter, then letters/digits/hyphens), e.g. 'fooctl'")
    return trimmed


#: The way out of every refusal below, spelled once. Each of them has the SAME fix - name the product
#: yourself - and a message that only says what went wrong leaves a first-time user with a broken command
#: and no next move.
_NAME_THE_ARGUMENT = ("give the name as the argument instead: `simplon init <product>` "
                      "(a lowercase slug: a letter, then letters, digits and hyphens, e.g. 'fooctl')")


@dataclass(frozen=True)
class RepositoryDefault:
    """What the repository a `simplon init` runs in says the product should be called, and where it is.

    `source` is carried rather than reconstructed because the run PRINTS it: two defaults fall out of one
    omitted argument (the name, and with it the target directory), and a user who did not type either has
    to be told which repository was read and where the skeleton went.
    """

    #: The product name, already through `validate_product_name`.
    name: str
    #: Where it was read from, in words, for the note the CLI prints.
    source: str
    #: The repository's working-tree root - the scaffold target a defaulted name implies.
    root: Path


def repository_name_from_url(url: str) -> str:
    """The repository name a remote URL spells, with the URL's own punctuation dropped and NOTHING else.

    A trailing `/` and a trailing `.git` belong to the URL rather than to the name, so removing them is
    parsing. Everything after that is handed on untouched, `Ops%20Tools` and `my.ctl` included, and
    `validate_product_name` is what refuses them - which is the point: a name repaired here would be
    repaired silently and by the wrong layer, and the caller could no longer tell whether the repository
    really is called that.

    The split is on `/` AND `:` because git accepts the scp-like `git@host:acme/netctl.git`, where the
    last path separator before the name may be a colon.

    The slash is stripped AGAIN after `.git` comes off, and that is not belt-and-braces: a remote
    pointing straight at a git directory, `/srv/git/netctl/.git`, is an ordinary local remote, and
    removing the suffix re-exposes the separator in front of it. Stripping once left an empty name and a
    refusal quoting `''`, which names the value and explains nothing.
    """
    trimmed = url.strip().rstrip("/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[:-len(".git")].rstrip("/")
    return re.split(r"[/:]", trimmed)[-1]


#: The `user[:password]@` between a URL's scheme and its host. Anchored on `//` so the scp-like
#: `git@github.com:acme/netctl.git` is left alone: that `git@` is the ordinary shape of an SSH remote and
#: carries no secret, while `https://oauth2:TOKEN@host/...` carries one in every character after the colon.
_URL_CREDENTIALS_RE = re.compile(r"(?<=//)[^/@]+@")


def redact_url(url: str) -> str:
    """`url` with any embedded credentials replaced by `***@`, for printing.

    The remote URL is quoted back to the user - it is the answer to "where did this name come from" - and
    a remote URL is one of the places a token routinely lives. GitLab CI writes
    `https://gitlab-ci-token:<job token>@gitlab.com/...` into every job's checkout, and a PAT-based HTTPS
    clone looks the same. Printing that verbatim puts a live credential into terminal scrollback and, far
    worse, into a CI log that outlives the job.

    Replaced rather than deleted, so the printed URL is visibly not the one in `.git/config` instead of
    silently differing from it. A bare `user@` goes too: it is not a secret, but a rule that has to decide
    which halves of a userinfo field are safe would be a rule that can be wrong.
    """
    return _URL_CREDENTIALS_RE.sub("***@", url)


def _git(args: list[str], *, cwd: Path) -> str | None:
    """One read-only git call from `cwd`: its trimmed stdout, or None when git had no answer to give.

    NO ANSWER COVERS BOTH A NON-ZERO RC AND AN EMPTY STDOUT, and collapsing them is the point rather than
    a shortcut. This is the ambiguity CLAUDE.md hunts, and the callers below are exactly where it would
    bite: an empty `--show-toplevel` would become `Path("")`, which resolves to the CURRENT directory, so
    a repository that could not name its own root would scaffold into wherever the command was typed and
    call it a success. Every caller here wants a non-empty string or nothing, and there is no third
    meaning for either of them to carry.

    OSError (no git on PATH at all) is deliberately NOT caught: it is a different condition and gets its
    own sentence at the call site.
    """
    result = run(["git", "-C", str(cwd), *args])
    return (result.out.strip() or None) if result.ok else None


def repository_default(start: Path) -> RepositoryDefault:
    """The product name the repository containing `start` implies, or ValueError naming the fix (si#129).

    WHICH NAME, and why the remote wins. The `origin` remote's repository name and the working tree's
    root directory name disagree the moment somebody clones into a differently named folder, and the
    remote is the one that survives it: `git clone .../netctl.git myproject` makes the directory an
    accident of one machine while the remote still carries the name the product is published under. A
    linked git worktree is the same case from the other side - its basename is `agent-3f2a` and the
    product is still netctl. So the remote is the primary and the working tree is the FALLBACK rather
    than a competitor: a repository with no remote yet is the ordinary state of a brand-new product, and
    failing there would refuse the one case this default exists for.

    The fallback reads `git rev-parse --show-toplevel`, not `start.name`. Running the command from a
    subdirectory would otherwise name the product after the subdirectory, silently.

    A DEFAULT, NEVER A DECREE, and si#102 is the fresh counter-example: its generator derived a CMake
    target from `root.name` and got the product name wrong, because a directory is named for where it
    sits and not for what it is. A repository can be `tooling`, or a monorepo holding two products. So
    the argument still wins, and a repository whose name cannot BE a product name is refused with the
    argument named rather than mangled into something that half works.
    """
    # ONE try over BOTH calls. `_git` states that OSError is the call site's to answer, and a guard on
    # only the first would leave the second able to traceback out of `simplon init` - which is exactly
    # what `main` promises never happens. The window is small (git on PATH for one call and gone for the
    # next) and the cost of closing it is an indent.
    try:
        toplevel = _git(["rev-parse", "--show-toplevel"], cwd=start)
        if toplevel is None:
            raise ValueError(
                f"no product name was given and {start} is not inside a git repository, so there is no "
                f"repository name to read; run it inside one, or {_NAME_THE_ARGUMENT}")
        root = Path(toplevel).resolve()
        url = _git(["remote", "get-url", "origin"], cwd=root)
    except OSError:
        raise ValueError(
            f"no product name was given and git is not on PATH, so the repository's name cannot be "
            f"read; install git or {_NAME_THE_ARGUMENT}") from None

    if url:
        # Redacted, and never the raw string: this URL is printed back to the user and to whatever log is
        # capturing the run. See `redact_url`.
        raw, source = repository_name_from_url(url), f"the 'origin' remote ({redact_url(url)})"
    else:
        # "No URL" rather than "no remote": `_git` gives the same nothing for a missing remote and for one
        # configured with a blank url, and a message that picked one of the two would be wrong about the
        # other.
        raw, source = root.name, f"the working tree at {root}, which has no 'origin' remote URL"

    try:
        name = validate_product_name(raw)
    except ValueError as exc:
        raise ValueError(
            f"{exc}. It was read from {source}, because no product name was given. It is not repaired "
            f"here on purpose: the name becomes the launcher's filename, the manifest's filename, the "
            f"package path and the <PRODUCT>_ENV variable stem, so a mangled one would name all four "
            f"after something nobody chose. So {_NAME_THE_ARGUMENT}") from None
    return RepositoryDefault(name=name, source=source, root=root)


def env_var_name(name: str) -> str:
    """The active-environment variable stem for a product: `netctl` -> `NETCTL_ENV`, `foo-ctl` -> `FOO_CTL_ENV`."""
    return name.upper().replace("-", "_") + "_ENV"


# --- reducing this kernel's version to one a scaffolded product may pin -----------------------------------
#
# Three peelings and one gate, in that order. The peelings undo exactly what setuptools-scm ADDED to the
# tag; the gate then asks whether what is left is a version somebody published.
#
#   +g1234abc[.d20260905]   the local segment: the node, and a date when the tree was dirty. Never part
#                           of a published version - PyPI refuses one outright - so it always comes off.
#   .post1.dev3             the `no-guess-dev` DISTANCE marker: "3 commits past the tag, which was a
#                           release". Both halves together mean distance; either alone does not, which is
#                           why they are peeled as one unit and not separately.
#   what remains            the tag. It is the pin if it names a published version.
#
# The gate is PEP 440's normalised public version MINUS a `.dev` component, because a `.dev` version is by
# definition unfinished and unpublished. Everything else is deliberately let through:
#
#   1.0          two components is a legal version and a legal tag. The release workflow triggers on
#                `v*` and constrains the shape no further, so a parser stricter than the tag namespace is
#                a trap: `git tag v1.0` would publish a wheel whose `simplon init` fails for every user.
#   0.1.12.post1 a post-release. Published, installable, and a perfectly ordinary thing to tag.
#   0.2.0rc1     a pre-release. `pip install simplon==0.2.0rc1` INSTALLS it - an exact `==` is an explicit
#                request and pre-release exclusion does not apply to one (measured, not assumed). Refusing
#                it would break `simplon init` for whoever deliberately installed a release candidate,
#                which is the same defect as refusing `1.0`, arrived at from the other side.
#
# WHY NOT CONSTRAIN THE TAG IN THE WORKFLOW INSTEAD. That was the other repair available, and it is a
# policy - "this project may not have a version shaped like that" - invented to accommodate a parser
# rather than because anybody wants it. Widening the parser removes the need for the policy, and after it
# every version that gets through is one `pip install` can actually resolve. There is nothing left for a
# tag gate to protect.
#
# THE ONE SENTINEL. `0.0` is not a shape, it is setuptools-scm's hard-coded stand-in for "found no tag at
# all" (vcs_versioning/_backends/_git.py, and the same literal in the hg and jj backends). A shallow
# `actions/checkout` produces exactly that - with a WARNING and not an error - so it is refused by name.
# It is the only value here rejected for what it means rather than for how it is spelled, and it is a
# second line: the first is `fetch-depth: 0` on every checkout, asserted in tests/test_version_source.py.
_LOCAL_SEGMENT_RE = re.compile(r"\+[A-Za-z0-9.]+$")
_DISTANCE_RE = re.compile(r"\.post\d+\.dev\d+$")
_PUBLISHED_RE = re.compile(r"^\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?$")

#: setuptools-scm's "no tag found" fallback. See the sentinel note above.
_NO_TAG_SENTINEL = "0.0"


def released_pin(version: str) -> str:
    """The kernel version a scaffolded product may pin, derived from `version`, or ValueError.

    THE PROBLEM THIS SOLVES (#3). The pin goes into a generated product's `requirements.txt` as
    `simplon==<x>`, and that file is the first thing its author runs `pip install -r` against. It must
    therefore name a version that EXISTS on PyPI. Since the kernel's own version now comes from the git
    tag, a kernel built anywhere but at a tag calls itself something like `0.1.12.post1.dev3+g1234abc` -
    correct for the kernel, and fatal as a pin: `pip install simplon==0.1.12.post1.dev3+g1234abc` resolves
    to nothing, and the product arrives broken.

    THE DECISION, and why it is not "pin what we are". A dev build is not published, so no `==` pin can
    name it truthfully. The closest true statement available is the release the build DESCENDS FROM, and
    the `no-guess-dev` version scheme was chosen precisely so that this string carries it: the release is
    the part before `.post`. So a product scaffolded from a developer's checkout pins the newest kernel
    that actually shipped - older than the one doing the scaffolding, never newer, and always installable.

    THE ALTERNATIVES, and why not. Pinning `0.1.13.dev3+…` writes a broken file. Pinning the default
    scheme's guessed `0.1.13` writes a file that is broken TODAY and might start working later on a
    version nobody verified against. Refusing to scaffold at all from an untagged tree would fail the one
    command every new user runs first, for a reason that is the kernel's business and not theirs.

    WHAT IT ACCEPTS is every published shape, not just `N.N.N` - two components, a post-release and a
    pre-release all get through, because the release workflow triggers on `v*` and a parser stricter than
    the tag namespace turns a legal tag into a wheel whose `simplon init` fails for everybody. The block
    comment above this function has the reasoning and the measurement for each.

    WHAT RAISES is a `.dev` version (unfinished by definition, and never published), anything a changed
    version scheme produces that is not PEP 440, the `0.0.0.dev0+unknown` a kernel reports when it is
    neither built nor installed, and setuptools-scm's `0.0` no-tag sentinel. Each means "no released
    version can be derived from this", and the honest place to say so is here - loudly, in the
    scaffolder's own process - rather than in somebody else's `pip install` a week later. `main()` turns
    it into a message and exit code 2, not a traceback.
    """
    peeled = _LOCAL_SEGMENT_RE.sub("", (version or "").strip())
    peeled = _DISTANCE_RE.sub("", peeled)
    if not _PUBLISHED_RE.match(peeled) or peeled == _NO_TAG_SENTINEL:
        raise ValueError(
            f"simplon.bootstrap: cannot derive a released kernel version from {version!r}, so there is "
            f"no pin a scaffolded product could install; expected a published version ('0.1.12', '1.0', "
            f"'0.2.0rc1') or a no-guess-dev descendant of one ('0.1.12.post1.dev3+g1234abc'). "
            f"'0.0.0.dev0+unknown' means this kernel is neither built nor installed - install it "
            f"(`pip install -e .`) and scaffold again. A version built on '0.0' means setuptools-scm "
            f"found no tag at all, which is what a shallow `git clone --depth 1` looks like - fetch the "
            f"history (`git fetch --unshallow --tags`) and build again")
    return peeled


# --- file templates (PURE text; @@PRODUCT@@ / @@ENV_VAR@@ / @@PKG_DIR@@ / @@KERNEL_PIN@@ substitute) ------
# Kept as literal strings with sentinel placeholders (not str.format) so the embedded shell/python braces
# stay verbatim and free of escaping. render() substitutes both tokens.

_MANIFEST = """\
# @@PRODUCT@@ delivery manifest - the single declarative source Simplon
# (simplon.orchestrator.manifest) assembles @@PRODUCT@@'s CLI from. Scaffolded by
# `simplon init`. Fill it in: replace the placeholder tasks with your real bodies and
# add the commands that instantiate them.
#
# Sections:
#   product       the product label (shim/manifest name + diagnostics).
#   tasks         the BODIES, each declared once: a bare name -> { impl: "module:function", help }.
#   groups        the COMMAND TREE, hung off the one the kernel's catalogue owns: group ->
#                 `commands:` -> command -> { task: <name>, ... }. A command is an INSTANCE of a
#                 task, so it never writes `impl:` itself.
#   environments  the deployment env matrix (a backend per env) + the default env.
product: @@PRODUCT@@

# --- product build data (read RAW by your paths adapter, IGNORED by the CLI engine) ---
# The CLI engine reads only tasks/groups and ignores any other top-level section, so your product's
# own build data lives here. Uncomment + extend as the pipeline grows.
# images:
#   app: @@PRODUCT@@:local
# volumes:
#   build_cache: @@PRODUCT@@-build-cache

# THE BODIES. A task is a TEMPLATE: it names a "module:function" this product's own package exports,
# and it is declared exactly once no matter how many commands run it. Two commands that differ only in
# the data they run with (`test unit` and `test system`) are two commands over ONE task, each pinning
# its own values with `with:` - which is why the body is here and the placement is below.
#
# These five are placeholders wired to the generated `orchestrator.cli` callbacks, one per phase, so a
# fresh product has a CLI that runs before it has anything to run. Replace them.
tasks:
  build:   { impl: "orchestrator.cli:build",   help: "Build the product artefacts (placeholder)." }
  check:   { impl: "orchestrator.cli:check",   help: "Verify the artefacts (placeholder)." }
  up:      { impl: "orchestrator.cli:up",      help: "Deploy the product to the target environment (placeholder)." }
  down:    { impl: "orchestrator.cli:down",    help: "Tear the deployment down (placeholder)." }
  status:  { impl: "orchestrator.cli:status",  help: "Report what is running in the target environment (placeholder)." }

# THE COMMAND TREE, and it is not this file's invention: the kernel's catalogue declares the CI/CD loop
# - build -> test -> release -> deploy -> monitor, plus support - and every product hangs its commands
# off those same six slots. That is the whole point: a person moving between two Simplon products finds
# the same groups holding the same general commands. A group name the catalogue does not declare is
# refused at load; add it to the platform's catalogue once, for everybody, or find the slot it belongs
# in.
#
# All six are shown here, each with at least one command, because a group is only useful once something
# is in it - and because the loop is easiest to learn on the day the product is empty. A group you
# declare and leave without a single command anywhere under it is a load error naming the group: it is a
# promise nobody kept. So grow a phase by ADDING to the list under its `commands:`, and if you truly
# have nothing for one yet, delete the group and let the catalogue's default (nothing rendered) stand.
groups:
  build:
    commands:
      # WHAT YOU PRODUCE: the wheel, the image, the bundle - whatever a later phase hands over.
      build: { task: build }
  test:
    commands:
      # WHAT YOU CHECK, and one command per level rather than one that runs everything: `test unit`,
      # `test system`, `test typecheck-python`. The kernel's `test:gate` runs a declared pytest suite,
      # `test:typecheck-python` runs mypy - declare a command for either the day you have its config.
      check: { task: check }
  release:
    commands:
      # WHAT YOU HAND OVER. `tag` is the catalogue's own `release:tag`: the BODY lives in the kernel,
      # this line only confirms the placement in your tree. A command with a colon in its `task:` names
      # a catalogue coordinate; one without names a task from the `tasks:` block above. Its neighbours
      # `release:artifact` and `release:image` need an `artifacts:`/`images:` section, so declare those
      # the day you have one.
      tag: { task: "release:tag" }
  deploy:
    commands:
      # WHERE IT RUNS. `deploy` and `monitor` are ENV-FIRST in the catalogue, so the environment is the
      # outer token: `@@PRODUCT@@ <env> deploy up` (`dev` below is the default). Every other group takes
      # no env and refuses one.
      up:   { task: up }
      down: { task: down }
      # An AGGREGATE: no body at all, only a plan. The kernel binds it at assembly time
      # (assemble(step_context=...) in orchestrator/cli.py) and runs its dependency plan build->up as
      # live-streamed `./@@PRODUCT@@.sh <cmd>` steps - a live example, not a dead placeholder. A command
      # is either an instance of a task or a plan over other commands, never both. `stop_on_failure:
      # false` (the default) runs every planned step and takes the worst rc.
      all:
        help: "Run build then deploy up end to end (the build->up dependency plan)."
        depends_on: [build, up]
        stop_on_failure: false
  monitor:
    commands:
      # WHAT IT LOOKS LIKE ONCE IT RUNS: health, logs, the version actually deployed. Env-first, like
      # `deploy` - you watch ONE environment.
      status: { task: status }
  support:
    commands:
      # HOST PREFLIGHT AND TOOLING - not a stage of the loop, which is why it sits beside the five
      # rather than among them. `install` is the catalogue's `support:install`, placed the same way
      # `release tag` is above. The catalogue also brings `support git` (commit/push/...) and
      # `support tasks` with no line from you at all - run `@@PRODUCT@@ support tasks catalogue` to see
      # every coordinate it offers.
      install: { task: "support:install" }

# The deployment environment matrix (#15, folded into the one manifest per #651 strand 1): one env per
# row, `backend` decides HOW it is realised (`local` today; add a cloud backend and widen
# _VALID_BACKENDS in environments.py later). An env-first command runs against ONE env, selected as the
# outer token; `default` is the implicit one.
default: dev
environments:
  dev: { backend: local, description: "Local development environment (the default)." }
"""

def _render_launcher(name: str, template: str, orch_dir: str) -> str:
    """Read a launcher template from package data and fill in the product name + the block dir.

    Package data rather than a string constant: the launchers are read by
    humans debugging a broken checkout, and a .sh file in the tree beats a
    triple-quoted blob in a Python module.

    The block dir goes in twice under two spellings, because cmd.exe wants
    backslashes: a nested `deploy/provision/orchestrator` carried over verbatim
    is the kind of path that half-works until it meets a tool that does not
    normalise it. Only `LAUNCH_ORCH_DIR` is substituted -- the venv, the
    requirements file and PYTHONPATH DERIVE from that variable inside the
    template, which is what keeps a half-parametrised shim from being possible.
    """
    # files("simplon") and then joinpath -- not files("simplon.templates"):
    # the templates directory is not a package and has no __init__.py.
    raw = files("simplon").joinpath("templates", template).read_text(encoding="utf-8")
    return (raw.replace("{{ product }}", name)
               .replace("{{ orch_dir_win }}", orch_dir.replace("/", "\\"))
               .replace("{{ orch_dir }}", orch_dir))


_REQUIREMENTS = """\
# Host-Python deps for the @@PRODUCT@@ orchestrator.
#
# The kernel is an ordinary dependency now. Bump the pin to move to a new
# kernel; nothing is vendored and nothing is included by path. Declaring the
# `test:typecheck-python` gate? Its mypy is an optional extra, so write
# `simplon[typecheck]==...` here instead.
#
# The number below is not typed by anyone: it is the RELEASED version of the
# kernel that scaffolded this product (simplon.bootstrap.released_pin). When
# that kernel was itself a development build, this is the release it descended
# from - the newest simplon on PyPI at the time, and one that installs.
simplon==@@KERNEL_PIN@@

# --- @@PRODUCT@@-product-only deps ---
"""

_INIT = '''\
"""@@PRODUCT@@ - the host-Python delivery orchestrator, scaffolded on Simplon (netctl#651 strand 4).

The CLI is assembled from @@PRODUCT@@.yaml by Simplon's binding layer; see cli.py for the composition
root and paths.py for the ProductContext wiring. Grow the CLI by editing the manifest, not this package.
"""

__version__ = "0.1.0"
'''

_MAIN = '''\
"""`python -m orchestrator ...` entry point - hands argv to the assembled Typer CLI (matches the shim's
LAUNCH_MODULE=orchestrator target `python -u -m orchestrator "$@"`)."""
from .cli import main

if __name__ == "__main__":
    main()
'''

_CLI = '''\
"""The @@PRODUCT@@ host CLI (Typer), assembled from @@PRODUCT@@.yaml by Simplon.

Scaffolded by `simplon init` (netctl#651 strand 4). This is the product's composition root:
it creates the root Typer app, ships the command-impl callables the manifest's "module:function" refs
resolve to, and hands the app + product context + environments + aliases to Simplon's binding layer
(simplon.cli). The generic assembly (a sub-app per group, hidden flat aliases, the flat-group collapse,
the CI/CD panels) and the env-first dispatch live in the kernel, driven entirely by the manifest - so a
fresh product adds groups/commands in @@PRODUCT@@.yaml and impl callables HERE, and nowhere else.

Replace the placeholder bodies (build/check/up/down/status - one per phase of the loop) with your own;
keep them as module-level callables so the manifest's task refs resolve
(simplon.orchestrator.manifest.resolve_impl imports THIS module and getattrs the function named after
the `:`). Note where they are NAMED: a body is declared once under `tasks:` in @@PRODUCT@@.yaml and a
command instantiates it with `task:` - a command never carries an `impl:` of its own, so there is one
place a body is written down and one place it is placed. The `all` command in @@PRODUCT@@.yaml is a
WORKING example of an impl-less AGGREGATE (#895/#896): it carries only `depends_on: [build, up]` and the
kernel binds it at assembly time via the step context below, so a fresh product sees the pattern live
instead of a dead placeholder - grow it by adding dependencies to that command in the manifest.
"""
from __future__ import annotations

import typer

from simplon import cli as simplon_cli
from simplon import log
from simplon.orchestrator.product import StepFactoryContext

from . import environments
from . import paths

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help=("@@PRODUCT@@ orchestrator (scaffolded on Simplon). The CI/CD loop is the "
                        "kernel's: build -> test -> release -> deploy -> monitor, plus support. AGNOSTIC "
                        "groups take no env (build, test, release, support); ENV-FIRST groups run "
                        "against a target env as the outer prefix `@@PRODUCT@@ <env> <group> <cmd>` "
                        "(default dev): deploy (up/down/all, where `all` runs the build->up dependency "
                        "plan) and monitor (status). Fill in @@PRODUCT@@.yaml to grow the CLI."))

# Back-compat command aliases (old token -> canonical), passed IN so the kernel hardcodes none. Empty for a
# fresh product; add entries here as you rename commands and want the old muscle memory to keep working.
_ALIASES: dict[str, str] = {}


def build() -> int:
    """Build the product artefacts (placeholder). Replace with your real build pipeline."""
    log.info("@@PRODUCT@@: build (placeholder) - wire me up in @@PKG_DIR@@/cli.py")
    # The generated wrapper's exit code IS this return value (cli.py.j2's `_rc` reads it), not a
    # raise - a framework-free body reports success by what it returns.
    return 0


def check() -> int:
    """Verify the artefacts (placeholder). Replace with your real checks.

    One command per LEVEL rather than one that runs everything: the kernel's `test:gate` runs a declared
    pytest suite and `test:typecheck-python` runs mypy, so a real product usually replaces this with a
    `suites:` section and one command per gate - and keeps each verdict its own.
    """
    log.info("@@PRODUCT@@: check (placeholder) - wire me up in @@PKG_DIR@@/cli.py")
    # See build() above: the exit code is the return value, not a raise.
    return 0


def up() -> int:
    """Deploy the product to the target environment (placeholder)."""
    log.info("@@PRODUCT@@: up (placeholder)")
    # See build() above: the exit code is the return value, not a raise.
    return 0


def down() -> int:
    """Tear the deployment down (placeholder)."""
    log.info("@@PRODUCT@@: down (placeholder)")
    # See build() above: the exit code is the return value, not a raise.
    return 0


def status() -> int:
    """Report what is running in the target environment (placeholder)."""
    log.info("@@PRODUCT@@: status (placeholder)")
    # See build() above: the exit code is the return value, not a raise.
    return 0


# The parsed manifest, read ONCE: the CLI is assembled from it below, and the step factory resolves each
# planned command's dotted identity through it.
_MANIFEST = paths.CONTEXT.manifest()

# The step-factory seam (#895/#896): a command NAME becomes a live-streamed `./@@PRODUCT@@.sh <cmd>` step,
# so the manifest's impl-less aggregates (`all`: depends_on build->up) run as DATA through the shared
# runner - no product Python per aggregate. Built once; StepFactoryContext is
# simplon.orchestrator.product's step-factory seam (kept distinct from the identity context in
# simplon.context, netctl#737).
#
# `for_shim` is the kernel's own factory for this shape, and using it is not a style choice: it STAMPS
# each step with the planned command's exact-command identity (`build.build`, `deploy.up`), which is what
# lets the kernel verify that step i really is the step for plan leaf i. A factory that does not stamp
# leaves that pairing unverifiable, and the kernel then drops the whole plan tree - taking every subtree's
# `stop_on_failure` with it, so a failing gate no longer stops the chain that declared it (#42).
_STEP_CONTEXT = StepFactoryContext.for_shim("@@PRODUCT@@", paths.ROOT / "@@PRODUCT@@.sh", _MANIFEST)


# Assemble the CLI from the manifest via Simplon's binding layer. Runs at import (like netctl's cli.py):
# resolve_impl imports this module and binds each leaf command's callback, so every command above must
# already be defined; step_context lets the kernel synthesize the callback for each impl-less aggregate
# (`all` runs its build->up dependency plan, reachable as `@@PRODUCT@@ all` or `@@PRODUCT@@ <env> deploy
# all`). The product name only shapes the usage hints.
simplon_cli.assemble(app, _MANIFEST, product=paths.CONTEXT.name, step_context=_STEP_CONTEXT)


def main() -> None:
    """Entry point (`python -m orchestrator`): env-first dispatch via Simplon's binding layer. The
    product context, the environments module and the alias map are injected, so simplon.cli hardcodes
    nothing product-specific."""
    simplon_cli.main(app=app, context=paths.CONTEXT, environments=environments.PROVIDER,
                      aliases=_ALIASES)
'''

_PATHS = '''\
"""@@PRODUCT@@'s product adapter onto Simplon: derive the repo ROOT + the manifest path and
register ONE ProductContext at import, so kernel code reads them back product-agnostically via
simplon.context.current() and never hardcodes "@@PRODUCT@@".

The walk up to the marker, the DELIVERY_* overrides and the fail-loud on a broken checkout are the
KERNEL's (simplon.context.bootstrap). What only this product knows is its name and where this file
sits, so that is all this module says. Extend it to read the manifest's raw build-data sections
(images/volumes/...) through CONTEXT.manifest_data() as your pipeline grows.
"""
from __future__ import annotations

from pathlib import Path

from simplon import context

CONTEXT = context.bootstrap("@@PRODUCT@@", Path(__file__).resolve().parent)
ROOT = CONTEXT.root
MANIFEST = CONTEXT.manifest_path
'''

_ENVIRONMENTS = '''\
"""@@PRODUCT@@'s named, isolated deployment environments. The matrix itself lives in @@PRODUCT@@.yaml
(the `environments:`/`default:` sections); this adapter supplies the three things that are @@PRODUCT@@'s
own and lets simplon.environments.Provider do the rest.

  * the process variable the active environment rides in (set by simplon.cli.main);
  * the backends this product IMPLEMENTS - `local` today; add your cloud backend (e.g. a VM-per-site
    provider) here and gate a command on it with PROVIDER.require_backend();
  * how this product's shim spells a command, so an error message can hand an operator a line that
    actually dispatches.

PROVIDER satisfies the simplon.cli EnvironmentProvider protocol structurally, so nothing named is
imported by the kernel - the coupling flows product -> kernel, never the reverse.
"""
from __future__ import annotations

from simplon.environments import LOCAL, Provider

ENV_VAR = "@@ENV_VAR@@"

PROVIDER = Provider(ENV_VAR, shim="./@@PRODUCT@@.sh", valid_backends=(LOCAL,))
'''

#: The file the block below goes into. Named rather than spelled inline, because three things key on it:
#: the template map, the one branch in `write` that treats it unlike every other scaffolded file, and the
#: test that drives a real `git check-ignore` over a scaffold.
GITIGNORE = ".gitignore"

#: The line that says the block is already here. Detection is a plain substring search for this, and a
#: search is ALL that is ever done with it: nothing looks for a closing marker, because nothing ever
#: rewrites what sits between two. A closing marker would be a promise to re-render the block later, and
#: si#110 measured what that promise costs - `support:toolchain` round-tripped a product's manifest
#: through `yaml.safe_dump` and forty-two comment lines went with it.
GITIGNORE_MARKER = "# --- written by simplon ---"

#: What the kernel puts in a product's tree, and therefore what a product must not be asked to discover
#: on its first `git status` (si#155). MEASURED on a scaffolded product driven through `./<p>.sh help`,
#: `support toolchain python 3.12`, `build deps`, `build unit` and `build analyse`: with no `.gitignore`
#: at all, `git status --porcelain` answers
#:
#:     ?? .simplon-toolchain/
#:     ?? deploy/provision/orchestrator/src/python/orchestrator/__pycache__/
#:     ?? src/__pycache__/
#:     ?? src/pydemo/__pycache__/
#:
#: - 80 MB of it the python profile's user base, and three of the four entries produced by a run nobody
#: would call a build. The FIRST of them arrives from `./<product>.sh help`: the launcher puts the
#: product's own orchestrator package on PYTHONPATH and the kernel imports it, so a product has an
#: untracked directory before it has a command of its own.
#:
#: THE RULE IS NOT "IGNORE EVERYTHING THE KERNEL WRITES". Three populations are deliberately absent, and
#: each absence was checked rather than reasoned about.
#:
#: * The paths that ALREADY IGNORE THEMSELVES. `python -m venv`, pytest and mypy each drop a `.gitignore`
#:   holding `*` into the directory they create. Driven on the scaffolded product, `git check-ignore -v`
#:   names each cache's OWN file as the rule that hides it, which is why `.pytest_cache` and
#:   `.mypy_cache` are missing from the four lines above even though both directories are there. So
#:   `<orch-dir>/.venv` (the launcher's), a pytest gate's `<suite>/.venv`, `.pytest_cache` and
#:   `.mypy_cache` need no line from anybody. The 0.10.0 notes told a product to add three lines here;
#:   two of the three were already unnecessary on the day they were written, and a block carrying them
#:   would read as though it were doing that work.
#: * The files the kernel GENERATES TO BE COMMITTED. si#102's `CMakeLists.txt` (the product root and
#:   every target directory), `<product>.sln` and each `<target>.csproj` carry a `DO NOT EDIT` header
#:   and land among the SOURCES, never under `build/`; so do `nuget.config`, `deploy/completions/
#:   <product>.bash`, `.github/workflows/*.yml` and the generated CLI module. An ignore rule that
#:   swallowed any of them would silently reverse a decided question, so a test drives the si#102
#:   generator over a real tree and asserts git can still see every file it wrote.
#: * What ANOTHER TOOL'S CONVENTION names and a product already ignores its own way. `bin/` and `obj/`
#:   are MSBuild's, and any .NET product's ignore file carries them; unanchored here they would also
#:   hide a `bin/` of shell scripts, which is a far more common directory than either.
#:
#: WHICH LINES ARE ANCHORED IS A MEASUREMENT TOO. A leading `/` pins a pattern to the product root; a
#: bare name matches at every depth. The first four are written at the root and only there
#: (`steplog`/`tools`/`site`/`docs`/`nuget` all build on `root / "build"`, `PYTHONUSERBASE=
#: /src/.simplon-toolchain` over a root bind mount, `docs.GRADLE_STATE`, `testrun.REPORTS`), so they are
#: anchored - and `build/` unanchored would additionally swallow a target directory named `build`, into
#: which si#102 writes a `CMakeLists.txt` that is meant to be committed. The last three cannot be
#: anchored: `allure-results`/`allure-report` keep their names under a `reports:` a product may move,
#: and `__pycache__` lands wherever python imported something.
#:
#: WHAT IS NOT HERE AND CANNOT BE. Three kernel outputs sit at a path the MANIFEST names, and two of
#: those keys have no default at all - `site: output:` and `site: source:` (hugo's `resources/` and its
#: build lock live under the latter), and `docs:reference`'s `output`, which is why this kernel
#: gitignores `site/content/using/commands.md` by hand. The kernel refuses those sections rather than
#: guessing a path, so a scaffolder running before any of them exists cannot write their lines either.
#: They are published on `using/getting-started.md` as the product's own; this constant is the part a
#: scaffold can be sure of.
_GITIGNORE = f"""\
{GITIGNORE_MARKER}
# Paths the kernel's own commands leave in this tree. Appended once and never rewritten, so edit,
# reorder or delete any line and a later `simplon init` will leave your version alone.
#
# Not here on purpose: .venv, .pytest_cache and .mypy_cache each write their own `.gitignore` holding
# `*`, so git already cannot see them; si#102's generated CMakeLists.txt / .sln / .csproj, the generated
# completions, workflows and nuget.config are meant to be COMMITTED; and `bin/`/`obj/` belong to
# MSBuild's ignore file rather than to this one.

# `build deps` installs pytest and mypy into the bind mount, because a --user container may write
# nothing else (si#121). Measured at 80 MB, 61 of them mypy's mypyc-compiled binary.
/.simplon-toolchain/

# Every build output the kernel names: build/logs/ (a log per step plus the run transcript, si#148),
# build/tools/bin, build/hugo-cache, build/docToolchain, build/dotnet-home, build/nuget, and the
# `cmake -B build` the C++ profile runs. Anchored, because a target directory named `build` is a source
# tree and si#102 writes a committed CMakeLists.txt into it.
/build/

# gradle's project-local state, which docToolchain's own gradle writes during `docs:render`.
/.gradle/

# Where a test gate puts its allure run, its junit xml and its verdict stamp. This is the kernel's
# DEFAULT for `suites: reports:`; a product that moves that key owns the line for the new place.
/tests/reports/

# The two of those whose names are fixed wherever `reports:` points, so a moved report directory still
# does not put a run's results in front of a reviewer.
allure-results/
allure-report/

# The kernel imports the product's orchestrator package on EVERY run, so `./<product>.sh help` leaves
# one of these behind before the product has a command of its own. A containerised `build unit` adds one
# per package it collects.
__pycache__/
"""


def _templates(name: str, orch_dir: str) -> dict[str, str]:
    """The (relative POSIX path -> template) map for a product, BEFORE placeholder substitution."""
    pkg_dir = pkg_dir_for(orch_dir)
    return {
        f"{name}.sh": _render_launcher(name, "launch.sh.j2", orch_dir),
        f"{name}.cmd": _render_launcher(name, "launch.cmd.j2", orch_dir),
        f"{name}.yaml": _MANIFEST,
        GITIGNORE: _GITIGNORE,
        f"{orch_dir}/requirements.txt": _REQUIREMENTS,
        f"{pkg_dir}/__init__.py": _INIT,
        f"{pkg_dir}/__main__.py": _MAIN,
        f"{pkg_dir}/cli.py": _CLI,
        f"{pkg_dir}/paths.py": _PATHS,
        f"{pkg_dir}/environments.py": _ENVIRONMENTS,
    }


def render(name: str, *, orch_dir: str = DEFAULT_ORCH_DIR) -> dict[str, str]:
    """PURE: the product skeleton as a {relative POSIX path -> file content} map, with @@PRODUCT@@,
    @@ENV_VAR@@, @@PKG_DIR@@ and @@KERNEL_PIN@@ substituted. No I/O, no yaml/pydantic import - so a test can validate the
    rendered manifest through the real loader and assert the exact file set without a filesystem or the
    product's deps.

    `orch_dir` moves the whole block: the requirements file, the package source, both shims' LAUNCH_ORCH_DIR
    and the one place the generated cli.py tells the reader which file to edit. Defaults to
    `deploy/provision/orchestrator` (si#130), which is where every consumer of this scaffolder already put
    it by hand; a product that owns its repository root passes `orchestrator`."""
    product = validate_product_name(name)
    block = validate_orch_dir(orch_dir)
    env_var = env_var_name(product)
    pkg_dir = pkg_dir_for(block)
    # Still pure - a module constant read, no I/O - and it raises BEFORE any of the other files are
    # rendered, so a kernel that cannot name a released version scaffolds nothing at all rather than a
    # tree with one un-installable file in it.
    kernel_pin = released_pin(simplon.__version__)
    return {
        rel: (template.replace("@@PRODUCT@@", product)
                      .replace("@@ENV_VAR@@", env_var)
                      .replace("@@PKG_DIR@@", pkg_dir)
                      .replace("@@KERNEL_PIN@@", kernel_pin))
        for rel, template in _templates(product, block).items()
    }


def manifest_yaml(name: str) -> str:
    """Just the rendered starter manifest text (the piece a test feeds to simplon.orchestrator.manifest.load)."""
    return render(name)[f"{validate_product_name(name)}.yaml"]


def shim_relpath(name: str) -> str:
    """The rendered shim's relative path (the one file that must be executable)."""
    return f"{validate_product_name(name)}.sh"


#: The two line endings a scaffolded file can carry, named so the choice below reads as a choice.
CRLF, LF = "\r\n", "\n"

#: The suffixes cmd.exe reads. Everything else a scaffold writes - the shell shim, the manifest, the
#: generated python - is read on the host the product RUNS on, and that host wants LF.
_BATCH_SUFFIXES = (".cmd",)


def newline_for(rel: str) -> str:
    """The line ending the scaffolded file at `rel` must carry, decided by the host that will RUN it (si#57).

    NOT the host that scaffolds it, which is what `Path.write_text` does by default: `newline=None`
    translates `\n` to `os.linesep`, so the launcher a Linux CI job writes reaches a Windows user as LF and
    the launcher a Windows developer writes reaches a Linux user as CRLF. A generator whose output depends
    on the machine it happened to run on is the defect either way, and the file extension is the only thing
    in the scaffold that knows which host the file is for.

    THE TWO HALVES ARE NOT EQUALLY WELL EVIDENCED, and this docstring says so rather than implying they
    are. The shell half is measured: a shim written with CRLF does not launch at all on this host - the
    kernel reads `bash\r` as the interpreter name and reports "No such file or directory"; the test beside
    it runs exactly that. The batch half is this repository's own standing claim, carried in
    `.gitattributes` (`*.cmd text eol=crlf`) and in `tests/test_launch_cmd.py`: cmd.exe mis-parses the
    multi-line `if (...)` blocks the launcher is built from when the file is LF-only. That claim is
    inherited, not reproduced - there is no Windows here to shoot it at. What is reproduced is the
    inconsistency: the kernel keeps that promise for its OWN `simplon.cmd` through `.gitattributes`, and a
    scaffolded product is handed no `.gitattributes` at all.

    So the pin lives in `write` rather than in a `.gitattributes` shipped alongside: the bytes were wrong
    where they were written, and a file that only takes effect once the product is in git would leave the
    scaffold itself producing whatever its host had.
    """
    return CRLF if rel.endswith(_BATCH_SUFFIXES) else LF


def apply_ignore_block(path: Path, block: str) -> bool:
    """Put `block` into the `.gitignore` at `path` if the marker is not there yet; return whether it wrote.

    THE ONE SCAFFOLDED FILE THAT IS NOT THE SCAFFOLD'S. `<product>.yaml`, the two launchers and the
    generated package are the kernel's output, so `write` may refuse to clobber them and `--force` may
    overwrite them. A `.gitignore` is a file the wider world already maintains - `simplon init` lands at
    the repository ROOT now (si#129), and a repository being adopted onto simplon usually has one - so
    both of those answers are wrong here: refusing would fail the whole scaffold over a file the scaffold
    does not own, and forcing would delete the product's rules.

    SO IT ONLY EVER APPENDS, and that is si#110's finding applied one file over. `support:toolchain`
    round-tripped a product's manifest through `yaml.safe_load`/`safe_dump` and forty-two comment lines -
    nearly every explanatory line the scaffold had written - did not come back. What replaced it keeps
    every existing byte and splices. This does less than that and needs to: existing bytes are not read
    for structure at all, only searched for the marker, so there is nothing here that a hand-edited,
    reordered or partly deleted block can confuse. The block cannot be duplicated (the marker is the
    guard), cannot be reordered into meaning something else (nothing looks at position) and cannot eat a
    product's rules (nothing is rewritten). The cost is stated rather than hidden: a block that goes
    stale is never refreshed, which is the correct trade for a file the product owns - the current list
    is published on `using/getting-started.md`.

    `--force` does not reach this, deliberately. Forcing a re-scaffold is how somebody refreshes a
    launcher they hand-edited; it must not be how they discover their ignore rules are gone.
    """
    if not path.exists():
        path.write_text(block, encoding="utf-8", newline=LF)
        return True
    text = path.read_text(encoding="utf-8")
    if GITIGNORE_MARKER in text:
        return False
    # Close a last line the product left open, then one blank line, so the block never lands glued to
    # somebody's final rule - `foo.log# --- written by simplon ---` is not a comment, it is a pattern.
    lead = ("" if text.endswith("\n") else "\n") + "\n" if text else ""
    with path.open("a", encoding="utf-8", newline=LF) as handle:
        handle.write(lead + block)
    return True


def write(name: str, target: Path, *, force: bool = False, orch_dir: str = DEFAULT_ORCH_DIR) -> list[Path]:
    """Render the skeleton and write it under ``target``, returning the written paths (sorted). Creates parent
    dirs; sets the shim executable (0o755). Refuses to overwrite an existing file unless ``force`` - a fresh
    scaffold must never silently clobber a hand-edited manifest or shim - raising FileExistsError listing the
    conflicts.

    Line endings come from `newline_for`, so what is written is decided by the host the file will RUN on and
    not by the one it was scaffolded on (si#57)."""
    product = validate_product_name(name)
    # render() validates `orch_dir`, and it does so before any directory is created: a refused path must
    # leave no half-scaffold behind.
    files = render(product, orch_dir=orch_dir)
    # Taken OUT of the clobber rule and out of the write loop both, because it is the one rendered path
    # the product may already own - see `apply_ignore_block`. Leaving it in would mean a scaffold into
    # any existing repository refuses everything over a file the scaffold is not entitled to anyway.
    ignore_block = files.pop(GITIGNORE)
    shim = shim_relpath(product)

    existing = sorted(rel for rel in files if (target / rel).exists())
    if existing and not force:
        raise FileExistsError(
            f"simplon.bootstrap: refusing to overwrite existing files under {target}: {existing}; "
            f"pass force=True (--force) to overwrite")

    written: list[Path] = []
    for rel, content in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline=newline_for(rel))
        path.chmod(0o755 if rel == shim else 0o644)
        written.append(path)
    # After the loop: the target directory exists by now even on a scaffold into a fresh `./<product>/`.
    # No chmod either - on a file that was already there it would change a mode nobody asked about.
    if apply_ignore_block(target / GITIGNORE, ignore_block):
        written.append(target / GITIGNORE)
    return sorted(written)


def next_steps(name: str, target: Path, *, orch_dir: str = DEFAULT_ORCH_DIR) -> str:
    """The post-scaffold guidance printed after a successful write: nothing to vendor, just run the CLI -
    the launcher provisions its own venv and installs the pinned kernel from PyPI on first run."""
    product = validate_product_name(name)
    pkg_dir = pkg_dir_for(validate_orch_dir(orch_dir))
    return "\n".join([
        f"Scaffolded '{product}' under {target}",
        "",
        "Next steps:",
        f"  1. cd {target}",
        "  2. git init  (if this is a fresh repo)",
        f"  3. fill in {product}.yaml with your real groups and commands",
        f"  4. run the CLI:  ./{product}.sh help",
        f"  5. grow it: add groups + commands in {product}.yaml and impl callables in",
        f"       {pkg_dir}/cli.py",
    ])


def main(argv: list[str] | None = None) -> int:
    """`simplon init [<product>] [--dir DIR] [--orch-dir DIR] [--force]`: scaffold a product skeleton and
    print the next steps. Returns 0 on success, 2 on a bad product name, a directory with no repository
    to read a name from, a clobber conflict, or a kernel whose version yields no pin a product could
    install (fail loud, no traceback).

    THE PRODUCT ARGUMENT IS OPTIONAL (si#129), and omitting it decides TWO things, which is why neither
    of them is silent:

        name given, --dir given      the argument, and --dir. Unchanged.
        name given, no --dir         the argument, and `./<name>/`. Unchanged.
        name defaulted, --dir given  the repository's name, and --dir.
        name defaulted, no --dir     the repository's name, and the REPOSITORY ROOT.

    The last row is the only new placement, and it is not a second default falling out of the first by
    accident. Reading the name from the repository IS the statement that the repository is the product,
    so `./<repo>/` inside that same repository contradicts the fact just used to name it - and it would
    put the launcher one directory below the manifest marker its own `paths.py` walks up to. The run
    prints the name it read, where it read it and where the skeleton is going.

    The name is read from the repository the command RUNS in, never from `--dir`. One rule rather than
    two: with `--dir .`, which is the case this default is for, the two are the same directory anyway.
    """
    # `simplon init <name>` reads like a command; the bare product name as the first argument read like a
    # typo. The old call pattern stays valid, so `python -m simplon.bootstrap <name>` keeps working.
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "init":
        argv = argv[1:]
    elif not argv:
        # A bare `simplon` must name the one thing it can do, and since si#129 that is no longer something
        # argparse could say for us: `product` is optional now, so `simplon` with no argv at all would
        # otherwise scaffold whatever repository the shell happened to be sitting in. `simplon init` with
        # nothing after it is a legal command; `simplon` alone is not, and the two must not collapse.
        print("simplon: nothing to do. The one command is `simplon init [<product>] [--dir DIR] "
              "[--orch-dir DIR] [--force]`, and the product name is optional inside a git repository; "
              "use `simplon init --help` for the options.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(
        # The console script is the documented entry point, so its usage line is the one to print.
        # `python -m simplon.bootstrap <product>` still works, it is just no longer what we advertise.
        prog="simplon init",
        description="Scaffold a fresh product onto the delivery orchestrator (netctl#651 strand 4).")
    parser.add_argument("product", nargs="?", default=None,
                        help=("the product slug (lowercase; letters, digits, hyphens), e.g. 'fooctl'. "
                              "OPTIONAL: with no argument it is read from the git repository you are "
                              "standing in - the 'origin' remote's repository name, or the working "
                              "tree's root directory name when there is no remote - and the skeleton "
                              "then lands at the repository root rather than in a subdirectory"))
    parser.add_argument("--dir", dest="directory", default=None,
                        help=("target directory (default: ./<product>, or the repository root when the "
                              "product name was read from the repository); use '.' to scaffold in place"))
    parser.add_argument("--orch-dir", dest="orch_dir", default=DEFAULT_ORCH_DIR,
                        help=("where the orchestrator block goes, relative to the target: it holds .venv, "
                              "requirements.txt and src/python/ (default: %(default)s, which is where "
                              "every product puts it). A product that owns its repository root passes "
                              "'orchestrator'. Pass it again on a later re-run: --force overwrites the "
                              "shim, so hand-editing the generated one does not survive."))
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files instead of refusing")
    args = parser.parse_args(argv)

    # Both defaults are resolved before anything is written, and both can refuse: a directory that is not
    # a repository has no name to give, and a repository whose name is not a legal product name is a
    # refusal rather than a repair. See this function's docstring for the four cases.
    found: RepositoryDefault | None = None
    try:
        if args.product is None:
            found = repository_default(Path.cwd())
            product, implied_target = found.name, found.root
        else:
            product = validate_product_name(args.product)
            implied_target = Path.cwd() / product
        orch_dir = validate_orch_dir(args.orch_dir)
    except ValueError as exc:
        print(f"simplon init: {exc}", file=sys.stderr)
        return 2

    target = Path(args.directory).resolve() if args.directory else implied_target
    if found is not None:
        # Nothing that was DECIDED for the user stays unsaid. The name first, with the source, because a
        # repository can be named for where it sits rather than for what it is; then the target, because
        # the omitted argument moved that too.
        print(f"simplon init: no product name given, so it is {product!r}, read from {found.source}",
              file=sys.stderr)
        if args.directory is None:
            print(f"simplon init: the repository is the product, so the skeleton lands at {target} "
                  f"rather than in a subdirectory (pass --dir to change that)", file=sys.stderr)
        else:
            print(f"simplon init: writing it to {target}, as --dir asks", file=sys.stderr)
    # Read BEFORE the write, because afterwards the three outcomes are indistinguishable from the tree:
    # a `.gitignore` holding the block looks the same whether this run created it, appended it, or found
    # it there. A scaffolder that touches a file the product maintains has to say which of those it did.
    had_ignore = (target / GITIGNORE).exists()
    try:
        written = write(product, target, force=args.force, orch_dir=orch_dir)
    except (FileExistsError, ValueError) as exc:
        # ValueError as well as FileExistsError, and it is not a formality: `write` -> `render` ->
        # `released_pin` raises one when this kernel's version cannot be reduced to something a
        # scaffolded product could install. That is a real condition a user meets - a checkout that is
        # neither built nor installed, or a shallow clone - and it must arrive the way this function
        # promises above, as a message and exit code 2. A traceback out of `simplon init`, the first
        # command any new user types, is the wrong end of the tool to be shown.
        #
        # Nothing half-written survives either: `write` calls `render` before its first mkdir, so the
        # target directory does not exist when this is reached.
        print(str(exc), file=sys.stderr)
        return 2

    if not had_ignore:
        pass  # a fresh .gitignore is part of the file list next_steps' caller already sees
    elif (target / GITIGNORE) in written:
        print(f"simplon init: appended simplon's ignore block to the {GITIGNORE} that was already there; "
              f"nothing in it was rewritten", file=sys.stderr)
    else:
        print(f"simplon init: the {GITIGNORE} already carries simplon's block, so it was left untouched",
              file=sys.stderr)
    print(next_steps(product, target, orch_dir=orch_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
