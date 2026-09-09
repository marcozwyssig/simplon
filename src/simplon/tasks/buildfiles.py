"""`build:cmake-files` and `build:dotnet-solution` - a product's build files, written from its tree (si#102).

WHY THE TREE IS THE DECLARATION AND THE MANIFEST IS THE EXCEPTION. A directory holding sources already
says what it is: a library, or - when it holds a `main` - an executable. Repeating that in a manifest
would be a second statement of the same fact, and the two would drift. So the tree is read, and the
manifest carries only what a directory cannot show. That is now two things rather than one: what a
target DEPENDS on, and whether a library wants an archive or a shared object (`kind:`, si#131). Where a
source sits still decides everything else - a nested directory folds into the target above it, a
`main.cpp` at a target's root makes it an executable, and a `<name>_test.<ext>` beside a unit is that
unit's test rather than part of it (si#134).

WHY A DEPENDENCY IS NEVER INFERRED FROM AN INCLUDE PATH. It was considered and rejected in the design: it
reads a C++ preprocessor approximately, and an approximate answer in a build file is worse than a
declared one, because it fails at LINK time in a message about symbols rather than about the manifest.
An override key naming no target is therefore refused by name, with the targets that do exist listed -
a typo in `targets:` is otherwise silent, and silently does nothing.

WHY EVERYTHING IS SORTED. The generated files are COMMITTED: they appear in diffs and are reviewed. A
directory listing is not an order, so an unsorted one would churn the diff on every run and the review
value would be gone within a week. The same reasoning makes the solution's GUIDs derived (`uuid5` over a
fixed namespace and the project's path) rather than generated - see `project_guid`.

WHY THE RENDERERS TOUCH NO FILESYSTEM. `read_tree` reads once, the renderers assemble text, and the task
writes it - the split `tasks/toolchain.py` and `tasks/image.py` already use. It is what lets every
assertion about the output be a string comparison rather than a directory walk.
"""
from __future__ import annotations

import posixpath
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from simplon import context, log

#: The extensions that make a directory a target. `.cs` is here because the same model feeds the .NET
#: half - one tree read, two renderers - and not because a C++ product ever holds one.
SOURCE_SUFFIXES = (".cpp", ".cc", ".cxx", ".cs")

#: The file whose presence makes a directory an executable rather than a library. Two spellings for the
#: two languages, and both are the convention their toolchain already assumes.
MAIN_FILES = ("main.cpp", "Program.cs")

#: A test target is one file, not a directory: `tests/<name>_test.<ext>` becomes the target `<name>_test`.
#:
#: ONE SPELLING, AND `test_<name>` IS DELIBERATELY NOT A SECOND ONE (si#134). Both are common in the
#: wild, and carrying both would make `test_helpers.cpp` - the helper file a great many C++ projects
#: have - a test target with no `main`, refused by the linker in a message about `_start`. A convention
#: a product must follow belongs on the docs page as well as in this constant, and `case-cpp.md` states
#: it.
TEST_SUFFIX = "_test"

#: The kinds a `targets: <name>: kind:` may name. `test` is NOT among them: where a file sits is what
#: makes it a test, and a manifest turning one into a library would drop its `add_test` in silence.
DECLARABLE_KINDS = ("executable", "shared", "static")

#: The two kinds something can LINK, which is the one distinction the include visibility turns on.
LIBRARY_KINDS = ("shared", "static")

#: The level a co-located test carries, and the two a `tests/` subdirectory may name (si#134). THE
#: LOCATION IS THE LEVEL: `src/<target>/<name>_test.<ext>` sits beside its unit, and `tests/` holds what
#: is about the assembled product and has no single unit to sit beside. A reader has to be able to tell
#: a level from a path without opening the file, which is why this is a rule about meaning rather than a
#: convenience.
UNIT_LEVEL = "unit"
TEST_LEVELS = ("acceptance", "system")


@dataclass(frozen=True)
class Target:
    """One thing the build produces, as the tree declares it.

    `directory` and every entry of `sources` are relative to the product root, never absolute: an
    absolute path would put the machine that ran the generator into a committed file.

    `directory` is the target's ROOT and not necessarily where each source sits: a nested directory
    folds into the target above it (si#131), so `src/net/tcp/socket.cpp` is a source of `net` whose
    directory is still `src/net`. That is what lets one `CMakeLists.txt` per target root carry a whole
    subtree, and it is why every renderer takes a source relative to `directory` rather than to itself.

    `level` is a test's LEVEL and is `None` on everything else - including on a test that sits directly
    in `tests/`, which is the shape si#102 shipped and which names no level.
    """

    name: str
    kind: str
    directory: Path
    sources: list[Path] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    level: str | None = None


def read_tree(root: Path, overrides: Mapping[str, Mapping[str, object]]) -> list[Target]:
    """Read the product tree into the model, and apply the manifest's `targets:` block over it.

    `src/<name>/` holding sources is a target - a library, or an executable when it holds a main. Each
    `tests/<name>_test.<ext>` is one test target. Everything comes back sorted by name, because what
    comes out of here decides the order of every line in every generated file.
    """
    targets = _library_targets(root) + _test_targets(root)
    targets.sort(key=lambda t: t.name)
    _unique(targets)
    return _overridden(targets, overrides)


def _unique(targets: list[Target]) -> None:
    """Refuse two directories that would carry one target name, and name both of them.

    A NAME IS THE ONE THING THIS MODEL CANNOT SHARE, and it is the tools rather than the model that
    decide that: `src/core/` and `tests/core/` both derive the target `core`, and CMake answers the
    second one with `add_executable cannot create target "core" because another target with the same
    name already exists`. So the generated tree could not have configured either way, and a refusal
    here says which two directories collided instead of leaving CMake to say that something did.

    What made it worth a refusal rather than a comment is what happened WITHOUT one. `_overridden`
    round-trips the list through a dict keyed on the name, so one of the two silently replaced the
    other: the library disappeared, the test target was written twice, and the run reported success -
    the exact defect this repository hunts, in a file nobody opens again because a generator wrote it.

    The refusal is diagnosis and costs no flexibility: it forbids nothing a product could have shipped.
    """
    seen: dict[str, Path] = {}
    for target in targets:
        first = seen.get(target.name)
        if first is not None:
            log.die(f"two directories both declare the target `{target.name}` - "
                    f"{first.as_posix()} and {target.directory.as_posix()}. A target name is what "
                    f"CMake and the solution both key on, so one of the two has to be renamed; "
                    f"nothing was written.")
            raise SystemExit(1)
        seen[target.name] = target.directory


def _library_targets(root: Path) -> list[Target]:
    """The directories under `src/`, one target each, WITH EVERYTHING BENEATH THEM (si#131).

    A NESTED DIRECTORY IS NOT ITS OWN TARGET; its sources fold into the target above it. Three things
    decided that, and the first is the one si#102 got wrong by accident. Making `src/net/tcp/` a target
    needs an answer to what it is CALLED, and every answer is a new rule: `tcp` collides with
    `src/util/tcp` in the flat namespace `_unique`, `_overridden`, `depends:`, `add_subdirectory` and
    the `.csproj` GUID derivation all key on, and `net_tcp` or `net.tcp` are inventions this design has
    no reason to choose between. Folding needs no name at all.

    The second is that the .NET half already works this way and cannot be made to work the other way:
    an SDK-style project globs `**/*.cs` beneath itself - `_render_csproj` emits no `<Compile>` items -
    so a directory under a project directory is ALREADY part of that project whatever this model says.
    One target per `src/<name>/` with recursive sources is the rule that reads the same tree twice.

    The third is that only this default is escapable. A product that wants `src/net/tcp` to be its own
    library writes `src/tcp/`; under the other rule a product that wants folding cannot ask for it.

    A `_test`-suffixed source is LIFTED OUT rather than compiled in, which is si#134's whole subject -
    see `_colocated_tests`.
    """
    src = root / "src"
    if not src.is_dir():
        return []
    out: list[Target] = []
    for directory in sorted(p for p in src.iterdir() if p.is_dir()):
        found = _tree_sources(directory)
        sources = [p for p in found if not p.stem.endswith(TEST_SUFFIX)]
        kind = ""
        if sources:
            _no_buried_main(directory, sources)
            kind = "executable" if any((directory / m).is_file() for m in MAIN_FILES) else "static"
            out.append(Target(name=directory.name, kind=kind,
                              directory=directory.relative_to(root),
                              sources=[p.relative_to(root) for p in sources]))
        out += _colocated_tests(root, directory, kind)
    return out


def _colocated_tests(root: Path, directory: Path, kind: str) -> list[Target]:
    """The unit tests that sit inside `directory`, each its own target rather than part of it (si#134).

    THIS IS THE DEFECT THE RULE EXISTS FOR, and it was not a missing feature. `_sources` returned every
    source directly in a directory, so `src/net/net_test.cpp` was swept into the LIBRARY's source list
    and compiled into it: the test's code, its `main` and whatever framework it links shipped inside the
    artefact, and nothing in any run said a word - a static archive gives up a member only to resolve an
    undefined symbol, and `main` is already defined by whoever links the archive, so the stray one is
    never even reached. No assertion over generated text can see it either, which is why it survived
    si#102's entire review and why `tests/test_buildfiles_e2e.py` reads `nm` over the archive.

    THE DEPENDENCY IS DERIVED AND NOT DECLARED, which is the point of putting the test there. The test
    sits INSIDE the library's directory, so the tree already says which library it tests and where its
    header is; a `depends:`/`include:` pair in the manifest would be a second statement of a fact the
    location makes. It is derived only for a LIBRARY, because CMake refuses `target_link_libraries`
    against an executable - a unit test beside a `main.cpp` links nothing and says so by linking
    nothing.
    """
    return [Target(name=source.stem, kind="test", directory=directory.relative_to(root),
                   sources=[source.relative_to(root)], level=UNIT_LEVEL,
                   depends=[directory.name] if kind in LIBRARY_KINDS else [])
            for source in _tree_sources(directory) if source.stem.endswith(TEST_SUFFIX)]


def _no_buried_main(directory: Path, sources: list[Path]) -> None:
    """Refuse a `main` below a target's root, which folding would otherwise archive in silence.

    `src/net/tools/main.cpp` folds into the library `net` under the rule above, and the result is a
    static archive carrying a stray `main` that nothing ever complains about: the linker pulls an
    archive member only to resolve an undefined symbol, and every program that links `net` has defined
    `main` itself already. That is the same class of defect as si#134 one directory over - wrong,
    silent, and inside a committed artefact - so it is refused where it is created rather than found
    later with `nm`.

    It forbids nothing a product could have shipped: an executable is a `src/<name>/` whose main sits at
    its root, and the message says exactly that.
    """
    buried = [p for p in sources if p.name in MAIN_FILES and p.parent != directory]
    if buried:
        log.die(f"{buried[0].relative_to(directory.parent.parent).as_posix()} is a `main` below the "
                f"target `{directory.name}`, and a nested directory folds into the target above it - "
                f"so this would be compiled INTO the library, where a stray `main` is invisible. An "
                f"executable is a `src/<name>/` holding its main at the root: move it to "
                f"`src/{buried[0].parent.name}/`. Nothing was written.")
        raise SystemExit(1)


def _test_targets(root: Path) -> list[Target]:
    """The test targets under `tests/`, and the LEVEL each one carries (si#134).

    `tests/` holds two levels now - system and acceptance, which are about the assembled product and
    have no single unit to sit beside - so the generator has to tell them apart, and a subdirectory
    named for the level is how a product says which. Anything else directly under `tests/` keeps
    exactly the meaning si#102 shipped and carries no level: refusing the shape cppdemo runs today, to
    make a rule tidy, would break a product for nothing.
    """
    tests = root / "tests"
    if not tests.is_dir():
        return []
    out: list[Target] = []
    for directory, level in [(tests, None), *((tests / name, name) for name in TEST_LEVELS)]:
        if directory.is_dir():
            out += _at_level(root, directory, level)
    return out


def _at_level(root: Path, directory: Path, level: str | None) -> list[Target]:
    """The two shapes `tests/` holds, at one level, and the two are the design's own table rather than
    a choice here.

    A `<name>_test.<ext>` FILE is one target: a C++ test is its own executable and its own ctest case.
    A DIRECTORY is one target too: a .NET test project is a directory of `.cs` files, and one project
    per file is not a shape that language has. A level directory holds both, so a .NET product can name
    a level as well - which is what keeps this a rule about location rather than a C++ feature.
    """
    out = [Target(name=source.stem, kind="test", directory=directory.relative_to(root),
                  sources=[source.relative_to(root)], level=level)
           for source in _sources(directory) if source.stem.endswith(TEST_SUFFIX)]
    for sub in sorted(p for p in directory.iterdir()
                      if p.is_dir() and not (level is None and p.name in TEST_LEVELS)):
        sources = _tree_sources(sub)
        if sources:
            out.append(Target(name=sub.name, kind="test", directory=sub.relative_to(root),
                              sources=[p.relative_to(root) for p in sources], level=level))
    return out


def _sources(directory: Path) -> list[Path]:
    """The source files DIRECTLY in `directory`, sorted. Sorted here rather than at every caller, so no
    renderer can be the one that forgot.

    Direct children, because this answers the one question that is about a directory's own contents:
    which `<name>_test.<ext>` FILES are targets in their own right. A directory that IS a target reads
    its whole subtree instead - see `_tree_sources`.
    """
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.suffix in SOURCE_SUFFIXES)


def _tree_sources(directory: Path) -> list[Path]:
    """Every source BENEATH `directory`, at any depth, sorted - a target's whole subtree (si#131).

    Sorted over the full relative path rather than over the filename, so `calculator.cpp` precedes
    `detail/mul.cpp` on every machine. The generated files are committed and reviewed; a directory walk
    is not an order, and `rglob` gives none at all.
    """
    return sorted(p for p in directory.rglob("*")
                  if p.is_file() and p.suffix in SOURCE_SUFFIXES)


def _overridden(targets: list[Target], overrides: Mapping[str, Mapping[str, object]]) -> list[Target]:
    """Apply `targets:` over the model, refusing a key that names no target.

    IT KEYS ON THE NAME, so it assumes what `_unique` has already refused: two targets sharing a name
    would collapse into one here and the other would vanish without a word. The precondition is stated
    rather than defended twice - `read_tree` runs the refusal one line before this call.

    The refusal LISTS the targets that exist, because the fault is almost always a typo and the way out
    is the correct spelling rather than the news that something was wrong.
    """
    known = {t.name for t in targets}
    unknown = sorted(set(overrides) - known)
    if unknown:
        log.die(f"`targets:` names {', '.join(unknown)}, which the tree does not hold - "
                f"this product's targets are {', '.join(sorted(known)) or '(none)'}")
        # The `raise` is not dead code, it is the shape `toolchain.declared` keeps for the same reason:
        # a refusal has to be a hard stop even if `log.die` ever stops being one, because the line below
        # assumes the key is known and would end in a KeyError where a diagnosis was promised.
        raise SystemExit(1)
    by_name = {t.name: t for t in targets}
    for name, body in overrides.items():
        target = by_name[name]
        by_name[name] = Target(name=target.name, kind=_kind(body, target), directory=target.directory,
                               sources=target.sources,
                               depends=_merged(target.depends,
                                               _names(body.get("depends"), name, "depends")),
                               include=_names(body.get("include"), name, "include"),
                               level=target.level)
    return [by_name[t.name] for t in targets]


def _kind(body: Mapping[str, object], target: Target) -> str:
    """A `kind:` entry, or the one the tree derived - the whole of si#131's second face.

    A DIRECTORY CANNOT SHOW WHETHER IT WANTS AN ARCHIVE OR A SHARED OBJECT, which is exactly the shape
    of thing this key exists for: `src/<name>/` holding sources says library, and nothing about it says
    which of the two. Everything else stays derived - a `main` at the root still makes an executable -
    because the tree does say that.

    A value outside the three is refused rather than passed on, because it would reach `_render_target`
    and select nothing: `add_library` and `add_executable` are the two constructs there are, and a
    typo like `kind: dynamic` would otherwise be written into a committed file as one of them.

    `kind:` on a TEST is refused for a different reason: where a file sits is what makes it a test, and
    turning one into a library here would silently drop its `add_test` - the suite would shrink by one
    case and every run would still be green.
    """
    raw = body.get("kind")
    if raw is None:
        return target.kind
    if target.kind == "test":
        log.die(f"`targets: {target.name}: kind:` cannot be declared for a test - where a file sits is "
                f"what makes it one, and a test that became a library would lose its `add_test` and "
                f"shrink the suite without a word. Move the file if it is not a test.")
        raise SystemExit(1)
    if raw not in DECLARABLE_KINDS:
        log.die(f"`targets: {target.name}: kind:` is {raw!r}, which is no kind - a target is one of "
                f"{', '.join(DECLARABLE_KINDS)}. A library defaults to `static`; `shared` is the one "
                f"thing a directory of sources cannot show about itself.")
        raise SystemExit(1)
    return str(raw)


def _merged(derived: list[str], declared: list[str]) -> list[str]:
    """The tree's own dependencies first, then the manifest's - and the manifest ADDS rather than
    replaces.

    A co-located unit test gets its library from where it sits (`_colocated_tests`). If a `depends:`
    block overwrote that, then declaring one extra dependency on such a test - a mocking library, a
    second component it exercises - would silently unlink it from the very unit it tests, and the
    failure would arrive as an undefined symbol rather than as anything about the manifest. Nothing is
    lost the other way: a target the tree derived nothing for has an empty list here and reads exactly
    as it did before.

    Order is kept, and for a linker it can matter: the derived library comes first, the manifest's
    entries after it in the order the product wrote them.
    """
    return [*derived, *[name for name in declared if name not in derived]]


def _names(raw: object, target: str, key: str) -> list[str]:
    """A `depends:`/`include:` list, in the order the manifest states it - that order is the product's
    own statement, and for a linker it can matter.

    A value that is not a list is REFUSED rather than stringified. `depends: {core: yes}` is a typo, and
    turning it into one dependency named `{'core': True}` would write that into a committed build file
    and fail at link time, in a message about symbols rather than about the manifest - which is the
    whole reason this key exists (see the module head).
    """
    if raw is None:
        return []
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        log.die(f"`targets: {target}: {key}:` must be a list of names, got "
                f"{type(raw).__name__} - a single name is written as a one-entry list")
        raise SystemExit(1)
    return [str(item) for item in raw]


# --- what every generated file says about itself (spec section 3) ------------------------------------

#: The two sentences, because two questions follow a surprise: what overwrote this, and where do I change
#: it instead. A header answering only the first sends the reader looking.
#:
#: THE COMMAND IS NAMED GENERICALLY AND THE DESIGN'S LITERAL IS NOT USED VERBATIM. The design writes
#: `Generated by cppdemo support cmake-files`, which carries a product's name and a group this kernel
#: does not have - the coordinates its own section 1 declares are `build:cmake-files` and
#: `build:dotnet-solution`. A constant cannot carry a product's name at all, and naming one of the two
#: coordinates in a file the other one may have written would answer the first question wrongly. What
#: both files share is the generator and the place to change the input, so that is what this says.
HEADER = (
    "# Generated by simplon from this product's source tree. "
    "DO NOT EDIT - your changes are reverted on the next run.\n"
    "# What this file renders lives in this product's manifest and in the tree beside it.\n"
)

#: The same two sentences for a file that is XML. A `.csproj` is parsed as XML before it is anything
#: else, so a `#` line in front of `<Project>` is not a comment there, it is a broken build.
XML_HEADER = "".join(f"<!-- {line.removeprefix('# ')} -->\n" for line in HEADER.splitlines())

#: The floor the generated projects require. Stated once, as a constant, rather than derived from the
#: toolchain image: the design's section 5 puts per-configuration knobs out of scope, and a product that
#: needs another floor is the ticket that makes this a manifest key.
CMAKE_VERSION = "3.20"


# --- CMake, rendered (spec section 2) ----------------------------------------------------------------


def cmake_files(targets: list[Target], root: Path, product: str) -> dict[Path, str]:
    """Every CMakeLists.txt this product needs, keyed by where it lands.

    The keys carry `root`; the CONTENTS never do. That is what lets the same model render the same bytes
    on two machines whose checkouts sit in different places.

    THE PROJECT IS NAMED AFTER THE PRODUCT AND NOT AFTER THE ROOT DIRECTORY, which is the same source
    the .NET half names its solution from. `root.name` reads as the product's name right up to the point
    where one checkout is not called what another one is - an agent worktree, a CI job that clones into
    `work/`, a second clone beside the first - and then `project(...)` changes in a COMMITTED file for a
    reason that has nothing to do with the product. The root then decides only where the files land,
    which is what the paragraph above already claims.
    """
    files = {root / "CMakeLists.txt": _render_root(targets, product)}
    for directory in sorted({t.directory for t in targets}):
        files[root / directory / "CMakeLists.txt"] = render_cmake(targets, directory)
    return files


def _render_root(targets: list[Target], project: str) -> str:
    """The top-level file: the version floor, the project, and one `add_subdirectory` per directory.

    `enable_testing()` is written when a test target exists and not otherwise - `add_test` in a
    subdirectory registers nothing without it, and a product with no test does not need the line.
    """
    lines = [HEADER,
             f"cmake_minimum_required(VERSION {CMAKE_VERSION})",
             f"project({project} LANGUAGES CXX)",
             ""]
    if any(t.kind == "test" for t in targets):
        lines += ["enable_testing()", ""]
    lines += [f"add_subdirectory({d.as_posix()})" for d in sorted({t.directory for t in targets})]
    return _text(lines)


def _include(path: str) -> str:
    """One include path, anchored where the manifest meant it.

    `include: [vendor/asio/include]` names a directory at the PRODUCT ROOT, and the line carrying it
    lands in `src/<target>/CMakeLists.txt`, where CMake resolves a relative path against
    `CMAKE_CURRENT_SOURCE_DIR` - so the bare string would point at `src/<target>/vendor/asio/include`
    and the compile would fail on a header the manifest correctly named. The .NET half solves the same
    problem in `_reference`; this is that fix on this side.

    An absolute path and one that is already a CMake variable are left alone: a product that writes
    either of those means it.

    QUOTED, because CMake splits an UNQUOTED argument on whitespace and on `;`. A directory a real
    filesystem allows - `Program Files`, a vendor drop carrying its version - would otherwise arrive as
    two arguments naming two directories that do not exist, and the compile would fail on a header the
    manifest named correctly, which is the very defect the anchoring above was added for. Quoting is
    what a hand-written CMakeLists does and it forbids a product nothing: a path with no space renders
    the same either way, and `${CMAKE_SOURCE_DIR}` still expands inside a quoted argument.
    """
    anchored = path if path.startswith(("/", "$")) else f"${{CMAKE_SOURCE_DIR}}/{path}"
    return f'"{anchored}"'


def _text(lines: list[str]) -> str:
    """The lines as a file: exactly one trailing newline, whatever separators the blocks left behind.
    A file whose tail depends on how many targets it holds would put whitespace into a review."""
    return "\n".join(lines).rstrip("\n") + "\n"


def render_cmake(targets: list[Target], directory: Path) -> str:
    """The CMakeLists.txt for ONE directory. PURE: it takes the model and returns text, and touches no
    filesystem - which is what lets every assertion about it be a string comparison.

    It filters `targets` itself rather than trusting a caller to pass the right subset: `tests/` holds
    several targets in one directory, and a caller that filtered by name would have to know that.
    """
    lines = [HEADER]
    for target in [t for t in targets if t.directory == directory]:
        lines += _render_target(target)
    return _text(lines)


#: How each kind is added, and the two library keywords are written OUT rather than left off (si#131).
#: A bare `add_library(<name> <sources>)` follows `BUILD_SHARED_LIBS`, which nobody sets and which is
#: therefore `OFF` - so every library was static, no product could have both, and the file said nothing
#: about it either way. A generated file that states what it produces is also the only one a reviewer
#: can check against what came out.
ADD_TARGET = {
    "static": "add_library({name} STATIC {sources})",
    "shared": "add_library({name} SHARED {sources})",
    "executable": "add_executable({name} {sources})",
    "test": "add_executable({name} {sources})",
}

#: What a library EXPORTS: the directory its own CMakeLists.txt sits in, which is where its headers sit
#: beside its sources. `CMAKE_CURRENT_SOURCE_DIR` rather than a path assembled from the model, because
#: this line lands in that directory's own file and the two can then never disagree.
OWN_DIRECTORY = '"${CMAKE_CURRENT_SOURCE_DIR}"'


def _render_target(target: Target) -> list[str]:
    """One target's lines: what it is, what it links, what it offers, and - for a test - its ctest case
    and its level.

    THE INCLUDE VISIBILITY IS ONE RULE AND NOT A KEYWORD PER LINE (si#131). A library EXPORTS its
    include directories; an executable and a test keep theirs private, because nothing links either of
    them and `PUBLIC` there says nothing to anybody. `PRIVATE` on a library was the defect: the
    directory was used to compile the target and inherited by nothing, so a library whose headers no
    consumer could find - not even one target over in the same project - was the only kind this
    generator could produce.

    HOW FAR THE EXPORT GOES: USABLE WITHIN THE GENERATED PROJECT, and that is a decision rather than a
    first cut. There is no `install(TARGETS ... EXPORT ...)` and no generated package config, because an
    export set with no importer is code written for a consumer that does not exist; the consumer that
    will exist is si#128's registry. The consequence is named rather than left to be found: the exported
    path is a bare source-tree directory and not `$<BUILD_INTERFACE:...>`, so `install(TARGETS)` will
    refuse this target the day somebody adds one, and si#128 is the ticket that wraps it.

    WINDOWS IS NAMED AND NOT SOLVED. A `SHARED` target here gets no `-fvisibility=hidden`, no
    `__declspec(dllexport)` and no generated export header, so it links on Linux and does not link on
    Windows. The kernel ships no Windows toolchain; this is the boundary, not an oversight.
    """
    sources = " ".join(p.relative_to(target.directory).as_posix() for p in target.sources)
    lines = [ADD_TARGET[target.kind].format(name=target.name, sources=sources)]
    if target.depends:
        lines.append(f"target_link_libraries({target.name} PRIVATE {' '.join(target.depends)})")
    exports = target.kind in LIBRARY_KINDS
    paths = ([OWN_DIRECTORY] if exports else []) + [_include(path) for path in target.include]
    if paths:
        visibility = "PUBLIC" if exports else "PRIVATE"
        lines.append(f"target_include_directories({target.name} {visibility} {' '.join(paths)})")
    if target.kind == "test":
        lines.append(f"add_test(NAME {target.name} COMMAND {target.name})")
        if target.level is not None:
            # THE LEVEL BECOMES A LABEL, which is what makes it a fact about the build rather than a
            # fact about a path: `ctest -L unit` really selects the unit tests, and si#133 has
            # something to carry into a report. A level the tree does not state renders no line at all.
            lines.append(f'set_tests_properties({target.name} PROPERTIES LABELS "{target.level}")')
    return [*lines, ""]


# --- the .NET solution, rendered (spec sections 2 and 4) ---------------------------------------------

#: The namespace every project GUID is derived under, `uuid5(NAMESPACE_DNS, "buildfiles.simplon")`,
#: written out as the constant it has to be: the whole property is that the same project path yields the
#: same GUID on every machine and every run, and a namespace computed at import would still be stable
#: only as long as nobody edits the string it is computed from. Changing this value renumbers every
#: project in every product, so it is a breaking change and not a detail.
GUID_NAMESPACE = uuid.UUID("b41d069f-c5c2-5976-bbc6-ed79c621125d")

#: MICROSOFT'S, NOT OURS. The project TYPE GUID of an SDK-style C# project is a fixed constant published
#: by Microsoft; it identifies the KIND of project and is the same in every solution file in the world.
#: It is quoted here rather than derived for exactly that reason.
CSHARP_PROJECT_TYPE = "{9A19103F-16F7-4668-BE54-9A1E7A4F7556}"

#: The framework the generated projects target. One constant, because the design's section 5 puts
#: per-configuration knobs out of scope; a product that needs another one is the ticket that turns this
#: into a manifest key.
#:
#: THE NUMBER IS THE ONE THE KERNEL'S OWN TOOLCHAIN SHIPS, and it is a measurement rather than a
#: preference (si#102, task 5). The first cut said `net8.0`, a version this kernel names nowhere else:
#: `profiles.PROFILES["dotnet"]` runs `mcr.microsoft.com/dotnet/sdk:{version}` and the .NET chapter
#: pins 9.0. Driven end to end in that image, a `net8.0` project BUILDS - the SDK restores an 8.0
#: targeting pack from NuGet and reports `Build succeeded` - and then does not run:
#: `dotnet E2eDemo.dll` answers `You must install or update .NET to run this application ... The
#: following frameworks were found: 9.0.20`, rc 150. A generated project whose output cannot run in
#: the image that compiled it is si#102's own failure one level down, so the default is the framework
#: the SDK image carries rather than one chosen for it.
TARGET_FRAMEWORK = "net9.0"

#: The configurations the solution offers. Sorted, and stated once: these rows are the bulk of a
#: solution file (24 of them in the two-project measurement the design quotes) and are the reason
#: generating one is worth it at all.
CONFIGURATIONS = ("Debug|Any CPU", "Release|Any CPU")


def project_guid(project_path: str) -> str:
    """The GUID of one project, DERIVED from its path relative to the product root and never generated.

    `uuid5` over a fixed namespace, so the same project yields the same GUID on every machine and every
    run. A `uuid4` would put a new GUID into the diff on every run and make the committed-output
    decision unusable within a week. Upper case without braces - the sln adds the braces at the two
    places that want them.
    """
    return str(uuid.uuid5(GUID_NAMESPACE, project_path)).upper()


def dotnet_files(targets: list[Target], root: Path, product: str) -> dict[Path, str]:
    """The `.sln` and every `.csproj`, keyed by where they land. PURE, like the CMake half.

    Paths inside the files use forward slashes on every platform. MSBuild and Visual Studio both read
    them, and one spelling is what makes the bytes identical no matter which machine ran the generator.
    """
    _expressible(targets)
    projects = {t.name: _project_path(t) for t in targets}
    _referenced(targets, projects)
    files = {root / f"{product}.sln": _render_solution(targets)}
    for target in sorted(targets, key=lambda t: t.name):
        files[root / _project_path(target)] = _render_csproj(target, projects)
    return files


def _expressible(targets: list[Target]) -> None:
    """Refuse a co-located unit test on the .NET side, because there is nothing correct to generate.

    THE C++ ANSWER DOES NOT PORT, AND THE REASON IS THE SDK'S GLOB RATHER THAN ITS PACKAGE REFERENCES.
    A second `.csproj` in the library's own directory is not a shape MSBuild has, and an SDK-style
    project compiles `**/*.cs` beneath itself - `_render_csproj` emits no `<Compile>` items at all - so
    the test file lands INSIDE the library whatever this model says about it. That is si#134's defect
    with no generated statement able to undo it: the only fixes are a `<Compile Remove=...>` in every
    library, or the move this message names.

    So it says so. The design's section 8 asked exactly this question and asked for a plain answer
    rather than something that builds and is wrong, and a refusal at the seam is the plain answer: the
    CMake half keeps the feature, the .NET half keeps the truth, and nobody discovers the difference
    from a shipped assembly.
    """
    colocated = [t for t in sorted(targets, key=lambda t: t.name) if t.level == UNIT_LEVEL]
    if colocated:
        source = colocated[0].sources[0].as_posix()
        log.die(f"{source} is a unit test inside a project directory, and .NET cannot express that: an "
                f"SDK-style project compiles every `.cs` beneath itself, so this file is part of the "
                f"library whatever the solution says - the test framework's references and its code "
                f"ship inside the artefact. Move it to `tests/{colocated[0].name}/`. Nothing was "
                f"written.")
        raise SystemExit(1)


def _referenced(targets: list[Target], projects: Mapping[str, Path]) -> None:
    """Refuse a `depends:` entry that names no project, before a single file is rendered.

    THE TWO HALVES DIVERGE HERE, and it is the two tools that divide them rather than a preference.
    CMake's `target_link_libraries` takes a LIBRARY, and a name this generator does not know is a
    legitimate thing to write there - `pthread`, `m`, a path to an archive the product ships - so the
    CMake half passes an entry through and the design's own sentence about failing at link time is what
    covers it. A `ProjectReference` cannot mean that: it is a PATH to a `.csproj`, and there is no path
    to a project that does not exist.

    Without this, `depends: [Coer]` reached `projects[name]` in `_render_csproj` and ended in
    `KeyError: 'Coer'` - a traceback out of the CLI where this module promises a diagnosis, for what is
    almost always a typo. So it is refused the way the typo one level up is refused: naming the target,
    the name it got wrong, and the projects that do exist.
    """
    for target in sorted(targets, key=lambda t: t.name):
        for name in target.depends:
            if name not in projects:
                log.die(f"`targets: {target.name}: depends:` names {name}, which is no project in "
                        f"this tree - a .NET dependency is a ProjectReference and there is no path to "
                        f"a project that does not exist. This product's projects are "
                        f"{', '.join(sorted(projects)) or '(none)'}; nothing was written.")
                raise SystemExit(1)


def _project_path(target: Target) -> Path:
    """Where a target's project file lives, relative to the product root - which is also the string its
    GUID is derived from, so the two can never disagree."""
    return target.directory / f"{target.name}.csproj"


def _render_csproj(target: Target, projects: Mapping[str, Path]) -> str:
    """One SDK-style project. A dependency becomes a `ProjectReference` and nothing else does: the
    design's section 5 keeps package references, multi-targeting and property groups out of scope."""
    lines = [XML_HEADER, '<Project Sdk="Microsoft.NET.Sdk">', "", "  <PropertyGroup>"]
    if target.kind == "executable":
        lines.append("    <OutputType>Exe</OutputType>")
    lines.append(f"    <TargetFramework>{TARGET_FRAMEWORK}</TargetFramework>")
    if target.kind == "test":
        # The one property that makes `dotnet test` recognise the project. The test SDK's package
        # reference is out of scope (section 5), so this states the intent the tree already shows.
        lines.append("    <IsTestProject>true</IsTestProject>")
    lines += ["  </PropertyGroup>"]
    if target.depends:
        lines += ["", "  <ItemGroup>"]
        lines += [f'    <ProjectReference Include="{_reference(target, projects[name])}" />'
                  for name in target.depends]
        lines += ["  </ItemGroup>"]
    lines += ["", "</Project>"]
    return _text(lines)


def _reference(target: Target, dependency: Path) -> str:
    """The path from one project to the project it references, relative and in forward slashes.

    `posixpath.relpath` rather than `os.path.relpath`: both paths are model values in posix spelling,
    and a generator run on Windows must not put backslashes into a file a Linux checkout then reads.
    It is pure arithmetic on two strings and touches no filesystem.
    """
    return posixpath.relpath(dependency.as_posix(), target.directory.as_posix())


def _render_solution(targets: list[Target]) -> str:
    """The solution: the file's own opening lines, the header, one row per project, and the matrix.

    THE HEADER IS NOT FIRST HERE, and that is the one place the "starts with the header" rule bends. A
    solution file is parsed by its opening line - `Microsoft Visual Studio Solution File, Format Version`
    - and a comment in front of it is read as a MISSING header rather than as a comment. So the two
    sentences sit exactly where every other `#` comment in a `.sln` sits, one line further down.
    """
    ordered = sorted(targets, key=lambda t: t.name)
    lines = ["Microsoft Visual Studio Solution File, Format Version 12.00",
             "# Visual Studio Version 17",
             HEADER.rstrip("\n")]
    for target in ordered:
        path = _project_path(target).as_posix()
        lines += [f'Project("{CSHARP_PROJECT_TYPE}") = "{target.name}", "{path}", '
                  f'"{{{project_guid(path)}}}"',
                  "EndProject"]
    lines += ["Global",
              "\tGlobalSection(SolutionConfigurationPlatforms) = preSolution"]
    lines += [f"\t\t{config} = {config}" for config in sorted(CONFIGURATIONS)]
    lines += ["\tEndGlobalSection",
              "\tGlobalSection(ProjectConfigurationPlatforms) = postSolution"]
    for target in ordered:
        guid = f"{{{project_guid(_project_path(target).as_posix())}}}"
        for config in sorted(CONFIGURATIONS):
            lines += [f"\t\t{guid}.{config}.ActiveCfg = {config}",
                      f"\t\t{guid}.{config}.Build.0 = {config}"]
    lines += ["\tEndGlobalSection", "EndGlobal"]
    return _text(lines)


# --- the two coordinates, and the only two functions here that touch a disk (spec sections 1 and 3) ---

#: The manifest section the `targets:` block lives under. A TOP-LEVEL `build:` section, beside `images:`
#: and `artifacts:`, and NOT the `build` group: a product's command tree hangs off `groups:`, so the two
#: names never meet, and the CLI engine ignores a section it does not model (`extra="ignore"`).
SECTION = "build"

#: The one key this kernel reads out of that section. Named as a constant because every refusal below
#: quotes the path a reader has to edit, and a message pointing at a key spelled differently from the
#: one that was looked up is worse than no message.
TARGETS_KEY = "targets"


def cmake() -> int:
    """Write this product's CMakeLists.txt files from its source tree, replacing whatever is there.

    NEITHER OF THESE TWO TAKES A PARAMETER, and that is the manifest's shape rather than an omission
    (si#105). The loader binds a command's `with:` block to the impl's PARAMETERS one for one -
    `simplon.cli._bound` refuses a key no parameter answers to, and `signatures.bindable` drops the
    `**kwargs` that would have swallowed one silently - so every parameter written here is a promise
    that a manifest may pin it, and every one a manifest pins has to be written here. Everything these
    two need is already a statement the product makes elsewhere: its root and its name come from the
    registered ProductContext, and the one thing a directory cannot show comes from the
    `build: targets:` section. A parameter for either would be a second place to say the same thing,
    which is exactly what the tree-first rule at the head of this module refuses.
    """
    product = context.current()
    return _written(cmake_files(_model(product), product.root, product.name), product.root)


def dotnet() -> int:
    """Write this product's .sln and .csproj files from its source tree, replacing whatever is there.

    The solution is named after the PRODUCT and every project after its directory, so the two names a
    .NET developer sees are the two the product already carries. See `cmake` for why this takes nothing.
    """
    product = context.current()
    return _written(dotnet_files(_model(product), product.root, product.name), product.root)


def _model(product: context.ProductContext) -> list[Target]:
    """This product's targets, or a refusal - never an empty list.

    A tree with no target renders a project that configures, compiles nothing, and is then COMMITTED,
    which is the worst of the three outcomes available: it is wrong, it is silent, and it is in the
    repository where the next reader takes it for a statement somebody made. The cause is almost always
    a layout the reader believes is already there, so the refusal says what was looked for rather than
    that nothing was found.
    """
    targets = read_tree(product.root, _declared_targets(product))
    if not targets:
        log.die(f"{product.name}: nothing to build under {product.root} - a target is a `src/<name>/` "
                f"directory holding {', '.join(SOURCE_SUFFIXES)} sources at any depth, a "
                f"`src/<name>/<unit>{TEST_SUFFIX}.<ext>` unit test beside the unit it tests, or a "
                f"`tests/<name>{TEST_SUFFIX}.<ext>` file. Nothing was written, because an empty "
                f"project is the worst answer available here: it configures cleanly, produces nothing, "
                f"and is then committed.")
        raise SystemExit(1)
    return targets


def _declared_targets(product: context.ProductContext) -> Mapping[str, Mapping[str, object]]:
    """The manifest's `build: targets:` block, in the shape `read_tree` is allowed to assume.

    THE TREE IS THE DEFAULT AND THE MANIFEST IS THE EXCEPTION (si#102), so a product that declares
    neither the section nor the block is the NORMAL case and gets an empty mapping rather than a
    complaint. What is refused is a block of the wrong shape: `targets: { net: core }` is a plausible
    typo for `net: { depends: [core] }`, and handed on it reaches `_overridden` as a string whose `.get`
    does not exist - an AttributeError where this module promises a diagnosis.

    The shape check lives here rather than in `read_tree` because this is the only function in the
    module that touches a manifest at all; the renderers and the tree read stay unable to name one.
    """
    where = str(product.manifest_path)
    section = product.manifest_data().get(SECTION)
    if section is None:
        return {}
    if not isinstance(section, Mapping):
        log.die(f"{where}: the `{SECTION}:` section must be a mapping holding `{TARGETS_KEY}:`, got "
                f"{type(section).__name__}")
        raise SystemExit(1)
    declared = section.get(TARGETS_KEY)
    if declared is None:
        return {}
    if not isinstance(declared, Mapping):
        log.die(f"{where}: `{SECTION}: {TARGETS_KEY}:` must be a mapping of target name to "
                f"{{ kind: ..., depends: [...], include: [...] }}, got {type(declared).__name__}")
        raise SystemExit(1)
    for name, body in declared.items():
        if not isinstance(body, Mapping):
            log.die(f"{where}: `{SECTION}: {TARGETS_KEY}: {name}:` must be a mapping, got "
                    f"{type(body).__name__} - a dependency is written as "
                    f"`{name}: {{ depends: [<name>] }}`")
            raise SystemExit(1)
    return {str(name): body for name, body in declared.items()}


def _written(files: Mapping[Path, str], root: Path) -> int:
    """Write every file, then NAME every file. Sorted, so two runs report in one order.

    IT ALWAYS OVERWRITES, with no `--force` and no confirmation, and that is si#102's decision rather
    than an unfinished one (spec section 2). A manifest is a product's own statement and `support
    toolchain` never clobbers one; a CMakeLists.txt is a RENDERING of a statement, and reverting a
    rendering is the whole point. A prompt would be asking somebody about a file this generator wrote.

    The report is the other half of that decision. The run took an action nobody confirmed, so it says
    which files carry it - relative to the product root, because an absolute path would name the machine
    that ran the generator, which is exactly what the generated files themselves refuse to carry.

    THE NEWLINE IS PINNED TO LF, because Python otherwise translates a line feed into the platform's
    own line ending on write: the same model rendered on Windows would land as a CRLF file where a Linux
    checkout wrote LF, which is a whole-file diff produced by nothing but the machine that ran the
    generator, against output whose only value is that it is byte-identical between runs.
    """
    ordered = sorted(files)
    for path in ordered:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[path], encoding="utf-8", newline="\n")
    log.ok(f"wrote {len(ordered)} file(s): "
           + ", ".join(path.relative_to(root).as_posix() for path in ordered))
    return 0
