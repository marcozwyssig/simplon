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
