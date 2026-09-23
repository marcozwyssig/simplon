"""WHERE A PRODUCT'S BUILD OUTPUT GOES - one directory, with one name, in every product (si#314).

THE GAP THIS CLOSES was not that `build/` was unsafe to clean. The kernel had already decided that and
written it down in three places - `tools.py` ("a fetched binary is a BUILD OUTPUT and must die with
`clean`"), `steplog.py` ("the same `build/` a product's `clean` removes") and the `.gitignore` rule
`bootstrap.py` scaffolds. The gap is that a product's own ARTEFACTS never arrived there at all: the
worked example is a product whose jars sit under `src/java/<module>/build/libs/` and whose native binary
sits under `firn-cli/build/native/`, each wherever its own tool happens to default to. Nobody could
clean a build with one directory, and nobody could find what a build produced without first knowing
which tool produced it.

A VALUE, NOT AN EXPRESSION RULE, and that is measured rather than preferred. Over all eight reachable
manifests, seven producing coordinates name a destination and TWO of them are outside `build/`: cleon
publishes out of `build-out/` (it keeps `build/` for what it FETCHES), and this repository's own two
documentation pages are written INTO the source tree, because hugo reads its content from
`docs/site/content/`. A rule over "every producing coordinate" would therefore have refused the kernel's
own manifest first - and a rule that exempts the kernel from what it asks of a product is the kind si#53
struck. So a coordinate that names its destination gets exactly what it named, and this module answers
for the ones that do not. Nothing here refuses a manifest that could have worked; the refusals below are
diagnosis.

THE KINDS ARE WHAT THE PRODUCING COORDINATES ALREADY ARE, not a taxonomy invented up front. `site` is
its own kind beside `docs` because a built website is not a document, and `logs` is its own beside both:
on DISPOSAL a step log is a build output like everything else and needs no rule of its own, but on KIND
it is the record of what ran, and a split that omitted it would file run protocol with the artefacts.

THE ONE THAT IS NOT A FILE. A container image lives in a daemon rather than in a directory, so the rule
cannot simply extend to it. What is written instead is a POINTER - the reference and the digest, in
`<output>/docker/image.txt` - which is what a deployment redeems anyway, and the same shape as
`deploy/image/image.pin`. The alternative measured and rejected: `docker save` of a toolchain image is
about 1 GB written on every build, by something nobody reads.
"""
from __future__ import annotations

from pathlib import Path

from simplon import context
from simplon.bootstrap import validate_relative_dir

#: The manifest key. A top-level SCALAR rather than a section: it carries one value, and a section would
#: invite a second key to grow beside it that says the same thing differently.
KEY = "output"

#: The default, and it is a convention rather than an invention: gradle, maven, cargo and the two
#: manifests in this family that already name a destination all say `build` or a sibling of it.
DEFAULT = "build"

#: The kinds a build actually has. Not a taxonomy invented up front: the four language kinds are
#: exactly the kernel's own toolchain profiles - a .NET build produces dlls and exes where a java build
#: produces jars, and filing both under one "code" would put two products' artefacts in one directory in
#: any tree that has both. `test_every_language_profile_has_a_kind` holds that correspondence from the
#: other side, so a fifth profile cannot arrive without a kind for what it produces.
#:
#: The four language kinds are stated here rather than imported from `tasks.profiles`, because this is a
#: LIBRARY module and that is a task body: the dependency would run the wrong way, and the test that
#: compares them is the honest way to keep one list from drifting from the other.
KINDS = ("cpp", "dotnet", "java", "python", "docker", "docs", "logs", "site")


def declared(data: dict, source: str = "manifest") -> str:
    """The relative output root the manifest states, or `DEFAULT` when it states none. Pure.

    A key that is ABSENT takes the convention. A key that carries a broken value is ruled on - the same
    line every optional key in this kernel draws, and here it matters more than most: the value is joined
    onto the product root and then handed to a clean, so an absolute path or a `..` would delete
    somewhere else entirely. `validate_relative_dir` is that check, shared with `--orch-dir` and the
    site build rather than restated.
    """
    value = data.get(KEY)
    if value is None:
        return DEFAULT
    if not isinstance(value, str):
        raise ValueError(
            f"{source}: '{KEY}' must be a relative directory, got {value!r} - it is joined onto the "
            f"product root and then cleaned, so it is read strictly rather than coerced")
    return validate_relative_dir(
        value, f"{source}: '{KEY}'",
        f"give a plain relative directory under the product root, e.g. '{DEFAULT}'",
        inside="the product root")


def root() -> Path:
    """The absolute output root of the registered product.

    The document is fetched and HANDED ON rather than read here, and that shape is not a style choice:
    the refusal census walks what the kernel passes `manifest_data()` to, so a reader that keeps the
    document to itself is one the census cannot follow and has to be excused by hand
    (`tests/test_refusal_census.py`). A caller that already holds the document calls `declared` instead.
    """
    ctx = context.current()
    return ctx.root / declared(ctx.manifest_data(), str(ctx.manifest_path))


def for_kind(kind: str) -> Path:
    """`<output>/<kind>/` for one of `KINDS`. The directory is NOT created here - a caller that writes
    creates it, and a caller that only reports a path should not leave an empty directory behind as a
    side effect of being asked a question.

    An unknown kind is refused rather than taken: the argument comes from a kernel task body, so a typo
    would otherwise write into `<output>/dokcer/` and report success - a build whose output nobody finds,
    which is the whole defect this module exists against.
    """
    if kind not in KINDS:
        raise ValueError(f"simplon: '{kind}' is not a kind of build output; the kinds are "
                         f"{', '.join(KINDS)}")
    return root() / kind
