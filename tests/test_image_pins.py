"""Every container image the KERNEL itself names, held to the pin rule the kernel demands of a product
(si#47).

WHY THIS FILE EXISTS. `docs:site` refuses a product's manifest image when it names no version, and says
why at length: an untagged reference is ':latest', and ':latest' means the same command runs something
else tomorrow. Meanwhile the kernel handed docker two references of exactly that shape - a bare
`frankescobar/allure-docker-service` in the report render and a bare `tonistiigi/binfmt` in the colima
amd64 setup - and `docs:render` asked only that a tag be DECLARED, so `doctoolchain_version: latest`
came through. Neither was risky on the day it was found; both were a rule with the author standing
outside it, and that costs the next rule its credibility.

THE SHAPE IS si#34's. There, `check_coordinate_placement` runs over the MERGED tree, so the catalogue's
own placements are held to the rule the catalogue states - the kernel subjects itself rather than
exempting itself. Here the same move has two halves, and they only work together:

  * every image the kernel CHOOSES is declared as a module constant and validated by
    `docker.pinned_image` where it is declared, at import (so an unpinned one cannot even be imported);
  * and this file sweeps the sources to check that the first half has no way to be bypassed - an image
    typed straight into a `docker run` argv is an image no gate ever sees, which is precisely how both
    of the above got in.

WHAT THE SWEEP CANNOT SEE, said plainly rather than implied. It reads one shape: a list LITERAL that has
`"docker", "run"` in it. `simplon.nexus` builds its probe argv by appending to a list and puts the
product's own `nexus: probe_image` in that position - product data rather than a kernel choice, and
deliberately not gated: si#47 takes an exception away from the kernel, it does not add a demand to a
product. A future module that assembles its argv the same way would also be invisible here, and the
paired count assertions below are what make that a visible gap rather than a green sweep over nothing.

AAA throughout.
"""
import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

import simplon
from simplon import allure, docker, labhost

from conftest import ROOT

#: The kernel's sources - the tree the sweep reads, and the tree the constants live in.
SRC = ROOT / "src" / "simplon"

#: `docker run` flags that CONSUME the argument after them. Without this the sweep would read
#: `--platform`'s `linux/amd64` and `--entrypoint`'s `hugo` as the image, because in a `docker run` argv
#: the image is simply the first POSITIONAL after the flags.
_FLAGS_TAKING_A_VALUE = {"-v", "-w", "-e", "-u", "-o", "-p", "-c", "--volume", "--workdir", "--env",
                         "--user", "--entrypoint", "--platform", "--network", "--name", "--mount",
                         "--add-host", "--label", "--publish"}


def _modules() -> list:
    """Every module of the kernel, imported. A constant that is only validated at import is only
    validated for a module something imports, so the sweep imports all of them itself."""
    found = []
    for info in pkgutil.walk_packages(simplon.__path__, prefix="simplon."):
        found.append(importlib.import_module(info.name))
    if not found:
        raise ValueError(f"no modules found under {SRC}")
    return found


def _image_positions(source: str) -> list[tuple[int, ast.expr]]:
    """`(line, node)` for the IMAGE argument of every `docker run` argv written as a list literal.

    The image is the first positional after the flags, which is docker's own rule for reading its
    command line - so the sweep reads the argv the way docker will rather than pattern-matching on what
    a reference looks like.
    """
    positions = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.List):
            continue
        words = [e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else None
                 for e in node.elts]
        start = next((i + 2 for i in range(len(words) - 1)
                      if words[i] == "docker" and words[i + 1] == "run"), None)
        if start is None:
            continue
        index = start
        while index < len(node.elts):
            word = words[index]
            if word is not None and word.startswith("-"):
                index += 2 if word in _FLAGS_TAKING_A_VALUE else 1
                continue
            if isinstance(node.elts[index], ast.Starred):     # *docker.user_args() - flags only
                index += 1
                continue
            positions.append((node.elts[index].lineno, node.elts[index]))
            break
    return positions


# --- the constants the kernel chooses -------------------------------------------------------------------


def test_the_images_the_kernel_names_itself_are_pinned():
    """The kernel's own two images, held to the gate a product's manifest image goes through. They are
    validated at import as well, which is what makes an unpinned one unimportable; this says so where a
    reader looks for the rule, and names them so the pair cannot silently become one."""
    # arrange / act
    chosen = {"simplon.allure.IMAGE": allure.IMAGE, "simplon.labhost.BINFMT_IMAGE": labhost.BINFMT_IMAGE}

    # assert: each passes the gate unchanged, and there really were images to rule on
    for where, image in chosen.items():
        assert docker.pinned_image(image, where) == image
        assert ":" in image, f"{where} names {image!r}, which is ':latest' by another spelling"
    assert len(chosen) == 2


def test_every_module_level_image_constant_in_the_kernel_is_pinned():
    """The sweep over the constants, so a THIRD image declared tomorrow is held to the rule without
    anybody remembering to add it above."""
    # arrange
    modules = _modules()

    # act: every module-level string constant whose name says it is an image
    ruled = {}
    for module in modules:
        for name in dir(module):
            if (name == "IMAGE" or name.endswith("_IMAGE")) and isinstance(getattr(module, name), str):
                ruled[f"{module.__name__}.{name}"] = getattr(module, name)

    # assert
    for where, image in ruled.items():
        assert docker.pinned_image(image, where) == image

    # assert: it ruled on something. A sweep that found no constant would pass exactly like one that
    # found ten, and only one of those is evidence
    assert len(modules) > 40
    assert len(ruled) >= 2, f"the image constants disappeared rather than being pinned: {sorted(ruled)}"


# --- and no way around them -----------------------------------------------------------------------------


def test_no_module_types_an_image_straight_into_a_docker_run_argv():
    """The half that makes the constants complete. Both unpinned references were LITERALS in an argv,
    which is why nothing could check them: an image that is never declared is an image no gate sees. So
    the image position has to be a name or an expression - and a name resolves to a constant the test
    above already holds to the rule."""
    # arrange
    sources = sorted(SRC.rglob("*.py"))

    # act
    inline = []
    swept = 0
    for path in sources:
        for line, node in _image_positions(path.read_text(encoding="utf-8")):
            swept += 1
            if isinstance(node, ast.Constant):
                inline.append(f"{path.relative_to(ROOT)}:{line}: {node.value!r}")

    # assert
    assert inline == [], ("an image typed into a docker argv is one no pin gate ever sees; declare it "
                          f"as a module constant validated by docker.pinned_image: {inline}")

    # assert: and the reader is not looking at a sweep that walked past every argv there is
    assert len(sources) > 40
    assert swept >= 2, "the sweep found no docker run image position at all - it is measuring nothing"


# --- the gate itself, at the edges the two images sat on ------------------------------------------------


@pytest.mark.parametrize("image", ["frankescobar/allure-docker-service", "tonistiigi/binfmt",
                                   "doctoolchain/doctoolchain:latest", "hugomods/hugo:"])
def test_the_gate_refuses_the_forms_the_kernel_was_using(image):
    """The refusals seen red, at the exact references si#47 measured: two untagged images the kernel
    handed docker, and the `latest` that `docs:render` used to accept."""
    # act / assert
    with pytest.raises(ValueError, match="image"):
        docker.pinned_image(image, "test")
