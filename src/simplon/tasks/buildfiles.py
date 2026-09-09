"""`build:cmake-files` and `build:dotnet-solution` - a product's build files, written from its tree (si#102).

WHY THE TREE IS THE DECLARATION AND THE MANIFEST IS THE EXCEPTION. A directory holding sources already
says what it is: a library, or - when it holds a `main` - an executable. Repeating that in a manifest
would be a second statement of the same fact, and the two would drift. So the tree is read, and the
manifest carries the ONE thing a directory cannot show, which is what a target depends on.

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
TEST_SUFFIX = "_test"


@dataclass(frozen=True)
class Target:
    """One thing the build produces, as the tree declares it.

    `directory` and every entry of `sources` are relative to the product root, never absolute: an
    absolute path would put the machine that ran the generator into a committed file.
    """

    name: str
    kind: str
    directory: Path
    sources: list[Path] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)


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
    """The directories under `src/`, one target each. Direct children only - a nested layout needs a
    naming rule the design does not state, and inventing one here would decide it by accident."""
    src = root / "src"
    if not src.is_dir():
        return []
    out: list[Target] = []
    for directory in sorted(p for p in src.iterdir() if p.is_dir()):
        sources = _sources(directory)
        if not sources:
            continue
        kind = "executable" if any((directory / m).is_file() for m in MAIN_FILES) else "library"
        out.append(Target(name=directory.name, kind=kind,
                          directory=directory.relative_to(root),
                          sources=[p.relative_to(root) for p in sources]))
    return out


def _test_targets(root: Path) -> list[Target]:
    """The test targets, and the two spellings are the design's own table rather than a choice here.

    A `tests/<name>_test.<ext>` FILE is one target: a C++ test is its own executable and its own ctest
    case. A DIRECTORY under `tests/` is one target too: a .NET test project is a directory of `.cs`
    files, and one project per file is not a shape that language has.
    """
    tests = root / "tests"
    if not tests.is_dir():
        return []
    out = [Target(name=source.stem, kind="test", directory=tests.relative_to(root),
                  sources=[source.relative_to(root)])
           for source in _sources(tests) if source.stem.endswith(TEST_SUFFIX)]
    for directory in sorted(p for p in tests.iterdir() if p.is_dir()):
        sources = _sources(directory)
        if sources:
            out.append(Target(name=directory.name, kind="test",
                              directory=directory.relative_to(root),
                              sources=[p.relative_to(root) for p in sources]))
    return out


def _sources(directory: Path) -> list[Path]:
    """The source files DIRECTLY in `directory`, sorted. Sorted here rather than at every caller, so no
    renderer can be the one that forgot.

    A file one level deeper - `src/core/detail/x.cpp` - is not read and not reported. Reading it would
    need the nested naming rule the design does not state (see `_library_targets`), and reporting it
    would refuse a layout that is legal in both languages. It is named here so it is a documented edge
    rather than a discovered one.
    """
    return sorted(p for p in directory.iterdir()
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
        by_name[name] = Target(name=target.name, kind=target.kind, directory=target.directory,
                               sources=target.sources,
                               depends=_names(body.get("depends"), name, "depends"),
                               include=_names(body.get("include"), name, "include"))
    return [by_name[t.name] for t in targets]


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


def _render_target(target: Target) -> list[str]:
    """One target's lines. A library is added, an executable and a test are built, and a test is also
    registered with ctest - which is the whole of what the design's table says (section 2)."""
    sources = " ".join(p.relative_to(target.directory).as_posix() for p in target.sources)
    command = "add_library" if target.kind == "library" else "add_executable"
    lines = [f"{command}({target.name} {sources})"]
    if target.depends:
        lines.append(f"target_link_libraries({target.name} PRIVATE {' '.join(target.depends)})")
    if target.include:
        anchored = " ".join(_include(path) for path in target.include)
        lines.append(f"target_include_directories({target.name} PRIVATE {anchored})")
    if target.kind == "test":
        lines.append(f"add_test(NAME {target.name} COMMAND {target.name})")
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
    projects = {t.name: _project_path(t) for t in targets}
    _referenced(targets, projects)
    files = {root / f"{product}.sln": _render_solution(targets)}
    for target in sorted(targets, key=lambda t: t.name):
        files[root / _project_path(target)] = _render_csproj(target, projects)
    return files


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
                f"directory holding {', '.join(SOURCE_SUFFIXES)} sources, or a "
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
                f"{{ depends: [...], include: [...] }}, got {type(declared).__name__}")
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
