"""Where a product's own tree sits, said by the product instead of assumed by the kernel (si#250).

THE DEFECT THIS REMOVES is not that products disagree about layout - they do, and that is allowed. It is
that the kernel GENERATES against a layout it never states, so a product arranged differently gets
commands that look right and are not. si#250 found it the expensive way: the Java profile scaffolds
`gradle assemble` and the runner mounts the product root at `workdir`, which assumes the Gradle build root
IS the product root. When it was not, the scaffolded command was silently wrong, and the only place in
this whole family where that trap is written down was a comment in the affected product's own manifest.

WHY THE LAYOUT IS DECLARED AND NOT PRESCRIBED, with the number that decided it. Measured on 2026-09-16
over the GitHub API, the six repositories in this family plus this kernel have SIX different shapes:

    simplon         src/simplon/                    tests/              tests/acceptance/
    agile-cockpit   src/agile_cockpit/              src/tests/          tests/
    netctl          src/<component>/src/            src/<component>/test/   test/acceptance/python
    biz-cockpit     src/<component>/src/            src/<component>/test/   -
    firn            src/java/<module>               src/test/unit/      tests/
    cleon           src/<eclipse.plugin>/ (asrc/, src-gen/)             -
    asbundle        no `src/` at all - `.github/` and `deploy/`

A kernel that stated one layout and held products to it would refuse FIVE of those six, and two of them
could not comply at all: cleon's shape is Eclipse's, and asbundle deploys rather than builds. That is
CLAUDE.md's first question answered with a count rather than an opinion, and it is why nothing here
refuses a tree. What the section does is let a product SAY what the kernel was otherwise guessing.

WHY ONLY TWO KEYS. Every key here has a reader in the kernel today, and a key with no reader is
decoration that the next release has to keep working. Three more were written down and struck:
`sources:` and `unit_tests:` have no reader - `buildfiles.py` states its own `src/<name>/` shape for the
CMake and .NET generators and refuses in its own words - and a `components:` flag has none either. They
belong here the day something reads them, and si#48 is what happens when that rule is not kept.

LIBRARY BY INTENT, in `simplon.surface`'s sense, and it names no product: a manifest-section vocabulary
that is pure and has no I/O in it, the same shape as `carrierspec` and `deployment`. A product's own task
body has the same question the kernel's do - where does my build run, where do my tests live - and this is
the one place that answers it. No product imports it today.

`tests:` IS A DIRECTORY AND `tests` IS ITS SPELLING (owner, 2026-09-16). The two spellings were both in
live use - `tests/` at the root of three products and the kernel's own ignore block, `test/` at netctl's
root and inside netctl's and biz-cockpit's components - and nothing had ever decided. `tests` is now what
the kernel writes and defaults to. netctl's `test/` is not refused: it says so here, in one line, which is
the whole point of the section.
"""
from __future__ import annotations

import posixpath
from typing import Mapping, NamedTuple

#: The manifest section this module owns.
SECTION = "layout"

#: The keys it accepts. Named, because an unrecognised key is REFUSED rather than ignored - and here that
#: is not tidiness either. A manifest that writes `build-root:` for `build_root:` would be read as
#: declaring nothing, the command would run at the product root, and the product would be back in exactly
#: the silent wrongness si#250 was filed about. The refusal is what makes a typo loud.
LAYOUT_KEYS = ("build_root", "tests")

#: What a product that says nothing means. The empty build root is the product root - which is what every
#: profile assumed before this section existed, so a manifest with no `layout:` runs byte-for-byte the
#: line it ran yesterday.
DEFAULT_BUILD_ROOT = ""
DEFAULT_TESTS = "tests"


class Layout(NamedTuple):
    """Where this product's build runs and where its tests above the acceptance line live.

    `build_root` is relative to the product root and defaults to the root itself. It is the answer to the
    question `workdir:` looks like it answers and does not: `workdir:` is the path the product tree is
    MOUNTED at inside the container, so naming a subdirectory there relocates the whole tree rather than
    descending into it. `build_root` descends.

    `tests` is the directory above the acceptance line - where a report lands and where acceptance
    features are read from. It is one directory rather than a map of levels because that is what the two
    readers in this kernel actually ask for; the levels below it are the product's own business, and
    `buildfiles.py` is where the kernel states the one shape it does generate.
    """

    build_root: str = DEFAULT_BUILD_ROOT
    tests: str = DEFAULT_TESTS

    def workdir(self, mount: str) -> str:
        """Where a containerised command RUNS, given the path the tree is mounted at.

        The one place the two ideas are joined, so no caller has to remember which of them `workdir:`
        was. With no `build_root` it is the mount itself, byte-for-byte what every scaffolded command
        produced before this section existed.
        """
        return posixpath.join(mount, self.build_root) if self.build_root else mount

    @property
    def acceptance(self) -> str:
        """Where acceptance features are read from."""
        return posixpath.join(self.tests, "acceptance")

    @property
    def reports(self) -> str:
        """Where a merged test report lands."""
        return posixpath.join(self.tests, "reports")


def _relative(value: object, key: str, where: str) -> str:
    """One path a product may state, refused when it is not a plain relative path inside the tree.

    An absolute path and a `..` are refused for the same reason and it is not tidiness: both name
    something OUTSIDE the product root, and the product root is the only thing the runner mounts. A
    `build_root: /kernel` would produce a container working directory that exists in the image and not in
    the mount, which fails with a message about the image rather than about the manifest.
    """
    path = str(value or "").strip().strip("/")
    if not path:
        raise ValueError(
            f"{where}: `{key}:` is empty, which says nothing. Leave the key out to mean the default, or "
            f"name a directory under the product root")
    if posixpath.isabs(str(value).strip()) or ".." in path.split("/"):
        raise ValueError(
            f"{where}: `{key}: {value}` has to be a plain relative path under the product root - that is "
            f"the only tree the toolchain runner mounts, so anything outside it is not there to run in")
    return path


def declared(data: Mapping[str, object], source: str = "manifest") -> Layout:
    """The layout this document declares, or the defaults.

    AN ABSENT SECTION IS THE NORMAL CASE and returns the defaults rather than refusing: every product in
    this family predates the section, and the defaults are exactly what the kernel assumed before it
    existed. That is what makes this change invisible to a manifest that does not opt in.
    """
    section = data.get(SECTION)
    if section is None:
        return Layout()
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section must be a mapping of "
                         f"{', '.join(LAYOUT_KEYS)}, not {type(section).__name__}")
    unknown = sorted(str(k) for k in section if str(k) not in LAYOUT_KEYS)
    if unknown:
        raise ValueError(
            f"{source}: the '{SECTION}' section does not take {', '.join(unknown)} - it takes "
            f"{', '.join(LAYOUT_KEYS)}. A key it ignored would leave the kernel guessing the very thing "
            f"this section exists to be told")
    where = f"{source}: '{SECTION}'"
    return Layout(
        build_root=(_relative(section["build_root"], "build_root", where)
                    if "build_root" in section else DEFAULT_BUILD_ROOT),
        tests=(_relative(section["tests"], "tests", where)
               if "tests" in section else DEFAULT_TESTS),
    )
