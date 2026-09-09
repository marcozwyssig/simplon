"""The ready-made toolchain configurations (si#95): DATA, scaffolded once, then inert.

WHY THE KERNEL MAY CARRY LANGUAGE KNOWLEDGE HERE, having refused it for modules. The design says the
kernel learns no CMake, no MSBuild and no pip, because four language modules would be four surfaces that
age. This file does not break that rule, it stays on the other side of it: a profile is a TABLE of argv
and paths - no behaviour, nothing to call, nothing that decides anything at run time.

And it is not read at run time either, which is the property that makes it safe. `support:toolchain`
writes the profile INTO the product's own manifest, and from that moment the product owns what it runs:
the expanded form sits in its file, reviewable, editable, pinned. A profile resolved on every build would
mean a kernel bump could silently change how a product compiles - the same class of defect as an
unpinned image, one level up - and that is exactly what the scaffold step buys away. The table below can
therefore evolve freely: it moves nobody's build, and a wrong entry is fixed by editing a manifest
rather than by waiting for a kernel release.

The commands are the spec's convention (`compile`, `unit`, `analyse`), documented rather than enforced,
and the image is a TEMPLATE the product's own parameters fill in - so compiler and version are manifest
data, and swapping 19 for 20 is a one-line diff.
"""
from __future__ import annotations

from dataclasses import dataclass

from simplon import log


@dataclass(frozen=True)
class Profile:
    """One language's ready-made configuration: the image template, and the command bodies for it.

    A command body is exactly what a `toolchain:run` command's `with:` block takes minus the image -
    a non-empty `argv` and the `workdir` it runs in - so the scaffolder writes it out verbatim.
    """

    image: str
    commands: dict[str, dict[str, object]]


#: The kernel's starting points, one per language. Data, not behaviour: nothing here runs, and after
#: `support:toolchain` has written a copy into a product's manifest, nothing here reaches that product
#: again either.
PROFILES: dict[str, Profile] = {
    "cpp": Profile(
        image="silkeh/clang:{version}",
        commands={
            "configure": {"workdir": "/src", "argv": ["cmake", "-S", ".", "-B", "build"]},
            "compile": {"workdir": "/src", "argv": ["cmake", "--build", "build", "-j"]},
            "unit": {"workdir": "/src", "argv": ["ctest", "--test-dir", "build", "--output-on-failure"]},
            "analyse": {"workdir": "/src", "argv": ["clang-tidy", "-p", "build"]},
        },
    ),
    "java": Profile(
        image="gradle:jdk{version}",
        commands={
            "compile": {"workdir": "/work", "argv": ["gradle", "build", "--no-daemon", "--console=plain"]},
            "unit": {"workdir": "/work", "argv": ["gradle", "test", "--no-daemon", "--console=plain"]},
        },
    ),
    "dotnet": Profile(
        image="mcr.microsoft.com/dotnet/sdk:{version}",
        commands={
            "compile": {"workdir": "/src", "argv": ["dotnet", "build"]},
            "unit": {"workdir": "/src", "argv": ["dotnet", "test"]},
            "analyse": {"workdir": "/src", "argv": ["dotnet", "format", "--verify-no-changes"]},
        },
    ),
    "python": Profile(
        image="python:{version}",
        commands={
            "unit": {"workdir": "/src", "argv": ["pytest", "-q"]},
            "analyse": {"workdir": "/src", "argv": ["mypy", "."]},
        },
    ),
}


def profile(language: str, **params: str) -> Profile:
    """The profile for a language, with its image resolved from the caller's parameters.

    An unknown language is refused by NAME and told what exists, because the answer a reader needs there
    is which four words are spelled how - not that the lookup failed.

    `cpp`'s `compiler` parameter is accepted and unused in this first cut: the image reference decides
    the compiler, so `compiler: gcc` would select a different profile entry rather than a different
    format field. That is a table entry when a product asks for it, not a knob to grow now.
    """
    if language not in PROFILES:
        log.die(
            f"no toolchain profile for '{language}' - the kernel carries: {', '.join(sorted(PROFILES))}"
        )
        raise SystemExit(1)
    prof = PROFILES[language]
    return Profile(image=prof.image.format(**params), commands=prof.commands)
