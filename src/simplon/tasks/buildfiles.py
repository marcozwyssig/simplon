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

from simplon import log

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
    return _overridden(targets, overrides)


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
    """One target per `tests/<name>_test.<ext>` file. A test is its own executable and its own ctest
    case, so the file is the unit here where a directory is the unit above."""
    tests = root / "tests"
    if not tests.is_dir():
        return []
    return [Target(name=source.stem, kind="test", directory=tests.relative_to(root),
                   sources=[source.relative_to(root)])
            for source in _sources(tests) if source.stem.endswith(TEST_SUFFIX)]


def _sources(directory: Path) -> list[Path]:
    """The source files directly in `directory`, sorted. Sorted HERE rather than at every caller, so no
    renderer can be the one that forgot."""
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.suffix in SOURCE_SUFFIXES)


def _overridden(targets: list[Target], overrides: Mapping[str, Mapping[str, object]]) -> list[Target]:
    """Apply `targets:` over the model, refusing a key that names no target.

    The refusal LISTS the targets that exist, because the fault is almost always a typo and the way out
    is the correct spelling rather than the news that something was wrong.
    """
    known = {t.name for t in targets}
    unknown = sorted(set(overrides) - known)
    if unknown:
        log.die(f"`targets:` names {', '.join(unknown)}, which the tree does not hold - "
                f"this product's targets are {', '.join(sorted(known)) or '(none)'}")
    by_name = {t.name: t for t in targets}
    for name, body in overrides.items():
        target = by_name[name]
        by_name[name] = Target(name=target.name, kind=target.kind, directory=target.directory,
                               sources=target.sources,
                               depends=_names(body.get("depends")),
                               include=_names(body.get("include")))
    return [by_name[t.name] for t in targets]


def _names(raw: object) -> list[str]:
    """A `depends:`/`include:` list, in the order the manifest states it - that order is the product's
    own statement, and for a linker it can matter."""
    if raw is None:
        return []
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        return [str(raw)]
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
XML_HEADER = "".join(f"<!-- {line.lstrip('# ')} -->\n" for line in HEADER.splitlines())

#: The floor the generated projects require. Stated once, as a constant, rather than derived from the
#: toolchain image: the design's section 5 puts per-configuration knobs out of scope, and a product that
#: needs another floor is the ticket that makes this a manifest key.
CMAKE_VERSION = "3.20"


# --- CMake, rendered (spec section 2) ----------------------------------------------------------------


def cmake_files(targets: list[Target], root: Path) -> dict[Path, str]:
    """Every CMakeLists.txt this product needs, keyed by where it lands.

    The keys carry `root`; the CONTENTS never do. That is what lets the same model render the same bytes
    on two machines whose checkouts sit in different places.
    """
    files = {root / "CMakeLists.txt": _render_root(targets, root.name)}
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
        lines.append(f"target_include_directories({target.name} PRIVATE {' '.join(target.include)})")
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
TARGET_FRAMEWORK = "net8.0"

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
    files = {root / f"{product}.sln": _render_solution(targets)}
    for target in sorted(targets, key=lambda t: t.name):
        files[root / _project_path(target)] = _render_csproj(target, projects)
    return files


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
